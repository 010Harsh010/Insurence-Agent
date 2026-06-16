"""
decision_maker.py  (v3.0 — Production Overhaul)
================================================
Automated AI Adjudication Pipeline for Health Insurance Claims.

Changes in v3.0
───────────────
  Req 1  DocumentRegistry: each uploaded document is individually normalised
         before any merging takes place.
  Req 2  Step 3A — Wrong document type detection          (TC001)
  Req 3  Step 3B — Unreadable document detection          (TC002)
  Req 4  Step 3C — Cross-document patient mismatch        (TC003)
  Req 5  Multi-document category inference (all docs + line items)
  Req 6  Pre-auth failure → REJECTED, reason = PRE_AUTH_MISSING
  Req 7  Network discount: base × (1 − pct), THEN copay
  Req 8  Per-claim limit exceeded → REJECTED, reason = PER_CLAIM_EXCEEDED
  Req 9  Dental line-item adjudication (Step 12B)
  Req 10 Waiting period output includes eligibility date
  Req 11 Same-day fraud threshold correctly triggers MANUAL_REVIEW
  Req 12 Component failure simulation with COMPONENT_SKIPPED trace
  Req 13 Deterministic exclusion keyword map (supplements LLM)
  Req 14 StepResult enhanced with inputs / outputs / rules_applied
  Req 15 DecisionType normalised: PARTIAL (was PARTIALLY_APPROVED)
  Req 17 ClaimDecision.claim_id always uses generated UUID
  Req 18 Required-doc rules read from policy record, not hardcoded
  Req 19 Early-exit document validation stage before policy/financial logic
"""

from __future__ import annotations

import json
import os
import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Optional

import dotenv
import psycopg2
import psycopg2.extras
from pydantic import BaseModel, Field

import sub_agent.llm as llm_module

dotenv.load_dotenv()


# ──────────────────────────────────────────────────────────────────────────────
# ENUMS
# ──────────────────────────────────────────────────────────────────────────────

class DecisionType(str, Enum):
    APPROVED      = "APPROVED"
    PARTIAL       = "PARTIAL"           # was PARTIALLY_APPROVED (Req #15)
    REJECTED      = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class DocumentValidationStatus(str, Enum):
    OK                         = "OK"
    DOCUMENT_VALIDATION_FAILED = "DOCUMENT_VALIDATION_FAILED"


class StepStatus(str, Enum):
    PASSED           = "PASSED"
    FAILED           = "FAILED"
    WARNING          = "WARNING"
    SKIPPED          = "SKIPPED"
    COMPONENT_SKIPPED = "COMPONENT_SKIPPED"   # Req #12


# ──────────────────────────────────────────────────────────────────────────────
# DOCUMENT RECORD  (Req #1)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class DocumentRecord:
    """Normalised representation of a single uploaded document."""
    file_id:             str
    file_name:           str
    doc_type:            str            # PRESCRIPTION, HOSPITAL_BILL, …
    patient_name:        Optional[str] = None
    date:                Optional[str] = None
    total_amount:        Optional[float] = None
    line_items:          list[dict] = field(default_factory=list)
    diagnosis:           Optional[str] = None
    hospital_name:       Optional[str] = None
    doctor_name:         Optional[str] = None
    doctor_registration: Optional[str] = None
    medicines:           list[str] = field(default_factory=list)
    tests_ordered:       list[str] = field(default_factory=list)
    quality:             str = "GOOD"   # GOOD | POOR | UNREADABLE
    confidence:          float = 1.0
    raw:                 dict = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# PYDANTIC MODELS
# ──────────────────────────────────────────────────────────────────────────────

class StepResult(BaseModel):
    """Result from a single pipeline step — full audit trace (Req #14)."""
    step_name:     str
    status:        StepStatus
    passed:        bool
    confidence:    float = Field(ge=0.0, le=1.0, default=1.0)
    reason:        Optional[str] = None
    details:       dict[str, Any] = Field(default_factory=dict)
    fatal:         bool = False
    # Audit fields (Req #14)
    inputs:        dict[str, Any] = Field(default_factory=dict)
    outputs:       dict[str, Any] = Field(default_factory=dict)
    rules_applied: list[str] = Field(default_factory=list)


class ClaimDecision(BaseModel):
    """Final output of the adjudication pipeline."""
    claim_id:                   str
    decision:                   Optional[DecisionType] = None   # null for doc-validation failures
    document_validation_status: DocumentValidationStatus = DocumentValidationStatus.OK
    approved_amount:            float = 0.0
    claimed_amount:             float = 0.0
    confidence_score:           float = 0.0
    fraud_score:                float = 0.0
    rejection_reason:           Optional[str] = None
    missing_documents:          list[str] = Field(default_factory=list)
    explanation:                str = ""
    trace:                      list[StepResult] = Field(default_factory=list)
    needs_manual_review:        bool = False
    created_at:                 datetime = Field(default_factory=datetime.utcnow)
    # Derived fields
    inferred_category:          Optional[str] = None
    inferred_amount:            Optional[float] = None
    inferred_diagnosis:         Optional[str] = None
    # Dental line-item result (Req #9)
    approved_items:             list[dict] = Field(default_factory=list)
    rejected_items:             list[dict] = Field(default_factory=list)


class ClaimInput(BaseModel):
    """Minimal input — only member_id and the document payloads."""
    member_id:               str
    document_agent_response: Optional[dict[str, Any]] = None
    extra_documents:         list[dict[str, Any]] = Field(default_factory=list)
    # Derived (populated by pipeline)
    policy_id:               Optional[str] = None
    claim_category:          Optional[str] = None
    claimed_amount:          Optional[float] = None
    treatment_date:          Optional[date] = None
    submission_date:         date = Field(default_factory=date.today)
    hospital_name:           Optional[str] = None
    diagnosis:               Optional[str] = None
    # Feature flags
    simulate_component_failure: bool = False
    # External claims history (for fraud check — e.g. TC009)
    claims_history:          list[dict] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# FALLBACK CONSTANTS  (used ONLY when policy has no document_requirements — Req #18)
# ──────────────────────────────────────────────────────────────────────────────

_FALLBACK_REQUIRED_DOCS: dict[str, list[str]] = {
    "PHARMACY":             ["PRESCRIPTION", "PHARMACY_BILL"],
    "CONSULTATION":         ["PRESCRIPTION", "HOSPITAL_BILL"],
    "DIAGNOSTIC":           ["PRESCRIPTION", "LAB_REPORT", "HOSPITAL_BILL"],
    "DENTAL":               ["HOSPITAL_BILL"],
    "VISION":               ["PRESCRIPTION", "HOSPITAL_BILL"],
    "ALTERNATIVE_MEDICINE": ["PRESCRIPTION", "HOSPITAL_BILL"],
}

_FALLBACK_CATEGORY_MAP: dict[str, str] = {
    "PHARMACY_BILL":        "PHARMACY",
    "MEDICINE_BILL":        "PHARMACY",
    "DRUG_INVOICE":         "PHARMACY",
    "PRESCRIPTION":         "CONSULTATION",
    "DOCTOR_CONSULTATION":  "CONSULTATION",
    "OPD_RECEIPT":          "CONSULTATION",
    "LAB_REPORT":           "DIAGNOSTIC",
    "DIAGNOSTIC_REPORT":    "DIAGNOSTIC",
    "PATHOLOGY_REPORT":     "DIAGNOSTIC",
    "RADIOLOGY_REPORT":     "DIAGNOSTIC",
    "DENTAL_REPORT":        "DENTAL",
    "DENTAL_BILL":          "DENTAL",
    "HOSPITAL_BILL":        "CONSULTATION",
    "DISCHARGE_SUMMARY":    "CONSULTATION",
    "VISION_REPORT":        "VISION",
    "EYE_REPORT":           "VISION",
    "OPTOMETRY_REPORT":     "VISION",
    "AYURVEDA_REPORT":      "ALTERNATIVE_MEDICINE",
    "HOMEOPATHY_REPORT":    "ALTERNATIVE_MEDICINE",
}

# Document-type alias normalisation
DOC_TYPE_ALIASES: dict[str, str] = {
    "MEDICINE_BILL":       "PHARMACY_BILL",
    "DRUG_INVOICE":        "PHARMACY_BILL",
    "DOCTOR_CONSULTATION": "PRESCRIPTION",
    "OPD_RECEIPT":         "HOSPITAL_BILL",
    "DENTAL_BILL":         "HOSPITAL_BILL",
    "DISCHARGE_SUMMARY":   "HOSPITAL_BILL",
}

# Deterministic exclusion keyword map (Req #13)
EXCLUSION_KEYWORD_MAP: dict[str, list[str]] = {
    "Obesity and weight loss programs": [
        "obesity", "bariatric", "bmi", "weight loss", "diet program",
        "diet plan", "nutrition program", "weight management", "morbid obesity",
    ],
    "Bariatric surgery": [
        "bariatric", "gastric bypass", "sleeve gastrectomy", "lap band",
    ],
    "Cosmetic or aesthetic procedures": [
        "cosmetic", "aesthetic", "whitening", "veneer", "bleaching",
        "botox", "filler", "liposuction",
    ],
    "LASIK / Refractive surgery": [
        "lasik", "refractive surgery", "laser eye",
    ],
    "Infertility and assisted reproduction": [
        "ivf", "infertility", "assisted reproduction", "surrogacy",
    ],
    "Experimental treatments": [
        "experimental", "clinical trial", "investigational",
    ],
    "Substance abuse treatment": [
        "alcohol", "drug abuse", "addiction",
    ],
    "Self-inflicted injuries": [
        "self-inflicted", "self inflicted", "suicide attempt",
    ],
}


# ──────────────────────────────────────────────────────────────────────────────
# DATABASE HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _db_connect() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "4000"),
        database=os.getenv("DB_NAME", "claims"),
        user=os.getenv("DB_USER", "admin"),
        password=os.getenv("DB_PASSWORD", "admin"),
    )


def _fetch_policy(policy_id: str) -> Optional[dict]:
    try:
        conn = _db_connect()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM policies WHERE policy_id = %s", (policy_id,))
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as exc:
        print(f"[DB] fetch_policy error: {exc}")
        return None


def _fetch_member(member_id: str) -> Optional[dict]:
    try:
        conn = _db_connect()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM members WHERE member_id = %s", (member_id,))
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as exc:
        print(f"[DB] fetch_member error: {exc}")
        return None


def _fetch_network_hospitals(policy_id: str) -> list[str]:
    try:
        conn = _db_connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT hospital_name FROM network_hospitals WHERE policy_id = %s",
                (policy_id,),
            )
            rows = cur.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception as exc:
        print(f"[DB] fetch_network_hospitals error: {exc}")
        return []


def _fetch_recent_claims(member_id: str, days: int = 30) -> list[dict]:
    try:
        conn = _db_connect()
        since = date.today() - timedelta(days=days)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM claims
                   WHERE member_id = %s AND treatment_date >= %s
                   ORDER BY treatment_date DESC""",
                (member_id, since),
            )
            rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as exc:
        print(f"[DB] fetch_recent_claims error: {exc}")
        return []


def _save_decision(
    claim_id: str,
    decision: ClaimDecision,
    member_id: str,
    policy_id: str,
    claim_category: str,
    treatment_date: date,
    claimed_amount: float,
) -> bool:
    try:
        conn = _db_connect()
        status_str = (
            decision.decision.value if decision.decision
            else "DOCUMENT_VALIDATION_FAILED"
        )
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO claims
                     (claim_id, member_id, policy_id, claim_category,
                      treatment_date, submission_date, claimed_amount,
                      claim_status, confidence_score, fraud_score)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (claim_id) DO UPDATE SET
                     claim_status     = EXCLUDED.claim_status,
                     confidence_score = EXCLUDED.confidence_score,
                     fraud_score      = EXCLUDED.fraud_score""",
                (
                    claim_id, member_id, policy_id, claim_category,
                    treatment_date, date.today(), claimed_amount,
                    status_str,
                    round(decision.confidence_score, 2),
                    round(decision.fraud_score, 2),
                ),
            )
            cur.execute(
                """INSERT INTO claim_decisions
                     (claim_id, decision, approved_amount,
                      confidence_score, rejection_reason, explanation, trace)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    claim_id, status_str,
                    round(decision.approved_amount, 2),
                    round(decision.confidence_score, 2),
                    decision.rejection_reason,
                    decision.explanation,
                    psycopg2.extras.Json([s.model_dump() for s in decision.trace]),
                ),
            )
            for step in decision.trace:
                cur.execute(
                    """INSERT INTO claim_trace_steps
                         (claim_id, step_name, step_status,
                          confidence_score, output_data, reason)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (
                        claim_id, step.step_name, step.status.value,
                        round(step.confidence, 2),
                        psycopg2.extras.Json(step.details),
                        step.reason,
                    ),
                )
        conn.commit()
        conn.close()
        return True
    except Exception as exc:
        print(f"[DB] save_decision error: {exc}")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# POLICY HELPER FUNCTIONS  (Req #18 — read from policy, not hardcoded)
# ──────────────────────────────────────────────────────────────────────────────

def _get_required_docs(policy: dict, category: str) -> list[str]:
    """Read required document types from the DB policy record."""
    doc_reqs   = policy.get("document_requirements") or {}
    policy_req = doc_reqs.get(category.upper(), {})
    required   = policy_req.get("required", [])
    if required:
        return [r.upper() for r in required]
    return [r.upper() for r in _FALLBACK_REQUIRED_DOCS.get(category.upper(), [])]


def _get_covered_procedures(policy: dict, category: str) -> list[str]:
    return (policy.get("opd_categories", {}).get(category.lower(), {})
            .get("covered_procedures", []))


def _get_excluded_procedures(policy: dict, category: str) -> list[str]:
    return (policy.get("opd_categories", {}).get(category.lower(), {})
            .get("excluded_procedures", []))


def _normalise_doc_type(raw: str) -> str:
    """Uppercase, replace spaces, then apply alias map."""
    up = raw.upper().strip().replace(" ", "_")
    return DOC_TYPE_ALIASES.get(up, up)


# ──────────────────────────────────────────────────────────────────────────────
# DOCUMENT REGISTRY BUILDER  (Req #1)
# ──────────────────────────────────────────────────────────────────────────────

def _parse_doc_payload(payload: dict, file_id: str, file_name: str) -> DocumentRecord:
    """
    Convert one DocumentAgent response payload into a DocumentRecord.

    Supported input shapes:
      A) { "data": { "classification": { "document_type": … },
                     "document": { …fields… } } }       ← live DocumentAgent
      B) { "actual_type": "…", "content": { … },
           "quality": "GOOD|UNREADABLE|POOR" }           ← test-case inline
      C) { "document_type": "…", …flat fields… }          ← already-unwrapped
    """
    # Shape A
    data           = payload.get("data", {})
    classification = data.get("classification", {})
    doc_body       = data.get("document", {})

    # Shape B
    actual_type = payload.get("actual_type", "")
    content     = payload.get("content", {})

    # Resolve document_type
    doc_type = (
        _normalise_doc_type(classification.get("document_type", ""))
        or _normalise_doc_type(doc_body.get("document_type", ""))
        or _normalise_doc_type(actual_type)
        or _normalise_doc_type(payload.get("document_type", ""))
        or "UNKNOWN"
    )

    # Resolve quality
    quality = "GOOD"
    for src in [payload, doc_body]:
        q = str(src.get("quality", "")).upper()
        if q in ("GOOD", "POOR", "UNREADABLE"):
            quality = q
            break

    # Confidence
    confidence = max(
        float(classification.get("confidence", 0) or 0),
        float(doc_body.get("confidence", 0) or 0),
        1.0 if quality == "GOOD" else (0.5 if quality == "POOR" else 0.0),
    )

    # Merge content from both shapes
    merged: dict[str, Any] = {**doc_body, **content}

    def _g(*keys: str) -> Any:
        for k in keys:
            v = merged.get(k)
            if v is not None and v != "":
                return v
        return None

    # Derive total from line items if missing
    total = _g("total_amount", "total")
    if total is None:
        items = merged.get("line_items", [])
        if items:
            try:
                total = round(sum(float(i.get("amount", 0) or 0) for i in items), 2)
            except Exception:
                total = None

    return DocumentRecord(
        file_id=file_id or f"auto_{doc_type}",
        file_name=file_name or f"{doc_type.lower()}.unknown",
        doc_type=doc_type,
        patient_name=_g("patient_name"),
        date=str(_g("date")) if _g("date") else None,
        total_amount=float(total) if total is not None else None,
        line_items=merged.get("line_items", []),
        diagnosis=_g("diagnosis"),
        hospital_name=_g("hospital_name"),
        doctor_name=_g("doctor_name"),
        doctor_registration=_g("doctor_registration"),
        medicines=merged.get("medicines", []),
        tests_ordered=merged.get("tests_ordered", []),
        quality=quality,
        confidence=min(confidence, 1.0),
        raw=payload,
    )


def _build_document_registry(
    primary: dict | None,
    extras: list[dict],
) -> list[DocumentRecord]:
    """Build a DocumentRecord list from all uploaded documents."""
    records: list[DocumentRecord] = []
    if primary:
        records.append(_parse_doc_payload(
            primary,
            primary.get("file_id", "F_PRIMARY"),
            primary.get("file_name", "primary_document"),
        ))
    for i, extra in enumerate(extras or []):
        records.append(_parse_doc_payload(
            extra,
            extra.get("file_id", f"F_EXTRA_{i+1}"),
            extra.get("file_name", f"extra_document_{i+1}"),
        ))
    return records


# ──────────────────────────────────────────────────────────────────────────────
# MULTI-DOCUMENT CATEGORY INFERENCE  (Req #5)
# ──────────────────────────────────────────────────────────────────────────────

def _infer_category_multi(registry: list[DocumentRecord], policy: dict) -> str | None:
    """
    Infer claim category from ALL uploaded documents combined.

    Priority (deterministic):
      1. PHARMACY           — any PHARMACY_BILL present
      2. DIAGNOSTIC         — any LAB_REPORT / DIAGNOSTIC_REPORT present
      3. DENTAL             — DENTAL_REPORT, or dental keywords in line items
      4. VISION             — VISION_REPORT / EYE_REPORT
      5. ALTERNATIVE_MEDICINE — ayurveda/homeopathy docs or keywords
      6. CONSULTATION       — PRESCRIPTION + HOSPITAL_BILL
      7. Fallback           — first doc's type via _FALLBACK_CATEGORY_MAP
    """
    types = {r.doc_type for r in registry}
    all_line_text = " ".join(
        item.get("description", "") for r in registry for item in r.line_items
    ).lower()
    all_diag = " ".join(r.diagnosis or "" for r in registry).lower()
    all_tests = " ".join(t for r in registry for t in r.tests_ordered).lower()

    if "PHARMACY_BILL" in types:
        return "PHARMACY"

    if any(t in types for t in
           ("LAB_REPORT", "DIAGNOSTIC_REPORT", "PATHOLOGY_REPORT", "RADIOLOGY_REPORT")):
        return "DIAGNOSTIC"

    if "DENTAL_REPORT" in types:
        return "DENTAL"
    dental_kws = ["root canal", "tooth extract", "dental fill", "scaling", "dental x-ray",
                  "crown", "gum treatment", "teeth whitening", "veneer", "orthodont", "dental"]
    if any(kw in all_line_text for kw in dental_kws):
        return "DENTAL"

    if any(t in types for t in ("VISION_REPORT", "EYE_REPORT", "OPTOMETRY_REPORT")):
        return "VISION"

    if any(t in types for t in ("AYURVEDA_REPORT", "HOMEOPATHY_REPORT")):
        return "ALTERNATIVE_MEDICINE"
    alt_kws = ["panchakarma", "ayurveda", "homeopathy", "unani", "naturopathy", "siddha"]
    if any(kw in all_line_text or kw in all_diag for kw in alt_kws):
        return "ALTERNATIVE_MEDICINE"

    if "PRESCRIPTION" in types and "HOSPITAL_BILL" in types:
        return "CONSULTATION"

    # Single-document fallback
    for r in registry:
        cat = _FALLBACK_CATEGORY_MAP.get(r.doc_type)
        if cat:
            return cat

    return None


# ──────────────────────────────────────────────────────────────────────────────
# FACTS MERGER  (for downstream steps that need a single consolidated view)
# ──────────────────────────────────────────────────────────────────────────────

def _merge_facts_from_registry(registry: list[DocumentRecord]) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "patient_name": None, "doctor_name": None, "date": None,
        "total_amount": None, "line_items": [], "medicines": [],
        "tests_ordered": [], "diagnosis": None, "hospital_name": None,
        "document_type": None, "doctor_registration": None, "confidence": 0.0,
    }
    for r in registry:
        if not facts["patient_name"] and r.patient_name:
            facts["patient_name"] = r.patient_name
        if not facts["doctor_name"] and r.doctor_name:
            facts["doctor_name"] = r.doctor_name
        if not facts["date"] and r.date:
            facts["date"] = r.date
        if not facts["diagnosis"] and r.diagnosis:
            facts["diagnosis"] = r.diagnosis
        if not facts["hospital_name"] and r.hospital_name:
            facts["hospital_name"] = r.hospital_name
        if not facts["doctor_registration"] and r.doctor_registration:
            facts["doctor_registration"] = r.doctor_registration
        if not facts["document_type"] and r.doc_type != "UNKNOWN":
            facts["document_type"] = r.doc_type
        facts["line_items"].extend(r.line_items)
        facts["medicines"].extend(m for m in r.medicines if m not in facts["medicines"])
        facts["tests_ordered"].extend(t for t in r.tests_ordered if t not in facts["tests_ordered"])
        facts["confidence"] = max(facts["confidence"], r.confidence)

    if not facts["total_amount"] and facts["line_items"]:
        total = sum(float(i.get("amount", 0) or 0) for i in facts["line_items"])
        if total > 0:
            facts["total_amount"] = round(total, 2)
    elif not facts["total_amount"] and registry:
        for r in registry:
            if r.total_amount:
                facts["total_amount"] = r.total_amount
                break

    return facts


def _infer_amount(facts: dict) -> float | None:
    if facts.get("total_amount"):
        return float(facts["total_amount"])
    if facts.get("line_items"):
        total = sum(
            float(item.get("amount", 0))
            for item in facts["line_items"]
            if item.get("amount") is not None
        )
        return round(total, 2) if total > 0 else None
    return None


def _infer_treatment_date(facts: dict) -> date | None:
    date_str = facts.get("date")
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        for fmt in ["%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"]:
            try:
                return datetime.strptime(str(date_str), fmt).date()
            except (ValueError, TypeError):
                continue
    return None


# ──────────────────────────────────────────────────────────────────────────────
# NAME MATCHING UTILITY
# ──────────────────────────────────────────────────────────────────────────────

def _names_match(a: str, b: str) -> bool:
    """True if two name strings refer to the same person."""
    noise = {"mr", "mrs", "ms", "dr", ".", ","}
    aw = set(a.lower().split()) - noise
    bw = set(b.lower().split()) - noise
    if not aw or not bw:
        return True
    if a.lower() in b.lower() or b.lower() in a.lower():
        return True
    return bool(aw & bw)


# ──────────────────────────────────────────────────────────────────────────────
# ADJUDICATION PIPELINE
# ──────────────────────────────────────────────────────────────────────────────

class AdjudicationPipeline:
    """
    Full 14-step adjudication pipeline (v3.0).

    Execution order:
      PRE  Build DocumentRegistry + infer category / amount / date
      3A   Wrong document detection              (early-exit)
      3B   Unreadable document detection         (early-exit)
      3C   Cross-document patient mismatch       (early-exit)
      1    Member validation
      2    Policy validation
      3D   Required document check               (early-exit, policy-aware)
      4    Document quality check
      5    OCR + extraction validation
      6    Consistency validation
      7    Coverage validation
      8    Waiting period check
      9    Exclusion check
      10   Pre-auth check
      11   Fraud check
      12   Financial calculation
      12B  Dental line-item adjudication
      13   Decision generation
      14   Explanation generation
    """

    def __init__(self):
        try:
            self._llm = llm_module.LLMClient()
        except Exception:
            self._llm = None
            print("[Pipeline] LLM unavailable — LLM steps will be skipped.")

    # ── Step result helpers ───────────────────────────────────────────────────

    def _ok(self, step: str, reason: str = "Passed", confidence: float = 1.0,
            details: dict | None = None, fatal: bool = False,
            inputs: dict | None = None, outputs: dict | None = None,
            rules: list[str] | None = None) -> StepResult:
        return StepResult(
            step_name=step, status=StepStatus.PASSED, passed=True,
            confidence=confidence, reason=reason, details=details or {},
            fatal=fatal, inputs=inputs or {}, outputs=outputs or {},
            rules_applied=rules or [],
        )

    def _fail(self, step: str, reason: str, confidence: float = 0.0,
              details: dict | None = None, fatal: bool = True,
              inputs: dict | None = None, outputs: dict | None = None,
              rules: list[str] | None = None) -> StepResult:
        return StepResult(
            step_name=step, status=StepStatus.FAILED, passed=False,
            confidence=confidence, reason=reason, details=details or {},
            fatal=fatal, inputs=inputs or {}, outputs=outputs or {},
            rules_applied=rules or [],
        )

    def _warn(self, step: str, reason: str, confidence: float = 0.8,
              details: dict | None = None,
              inputs: dict | None = None, outputs: dict | None = None,
              rules: list[str] | None = None) -> StepResult:
        return StepResult(
            step_name=step, status=StepStatus.WARNING, passed=True,
            confidence=confidence, reason=reason, details=details or {},
            fatal=False, inputs=inputs or {}, outputs=outputs or {},
            rules_applied=rules or [],
        )

    def _skip(self, step: str, reason: str = "Component skipped") -> StepResult:
        return StepResult(
            step_name=step, status=StepStatus.COMPONENT_SKIPPED, passed=True,
            confidence=0.5, reason=reason, fatal=False,
            rules_applied=["simulate_component_failure"],
        )

    def _call_llm_json(self, messages: list[dict], fallback: dict) -> dict:
        if self._llm is None:
            return fallback
        try:
            raw = self._llm.call_llm(
                messages, temperature=0.0,
                response_format={"type": "json_object"},
            )
            return __import__("json").loads(raw) if raw else fallback
        except Exception as exc:
            print(f"[LLM] error: {exc}")
            return fallback

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1 – Member Validation
    # ─────────────────────────────────────────────────────────────────────────
    def step_01_member_validation(
        self, claim: ClaimInput, member: Optional[dict]
    ) -> StepResult:
        step = "Member Validation"
        if member is None:
            return self._fail(step, f"Member '{claim.member_id}' not found.",
                              inputs={"member_id": claim.member_id})
        member_policy = member.get("policy_id")
        if not member_policy:
            return self._fail(step, f"Member '{claim.member_id}' has no policy_id in DB.",
                              inputs={"member_id": claim.member_id})
        claim.policy_id = str(member_policy)
        return self._ok(
            step,
            f"Member '{member['name']}' (ID: {claim.member_id}) active under '{claim.policy_id}'.",
            inputs={"member_id": claim.member_id},
            outputs={"policy_id": claim.policy_id, "member_name": member["name"]},
            rules=["member_must_exist", "member_must_have_policy"],
            details={"name": member["name"], "relationship": member.get("relationship"),
                     "join_date": str(member.get("join_date", "")), "policy_id": claim.policy_id},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2 – Policy Validation
    # ─────────────────────────────────────────────────────────────────────────
    def step_02_policy_validation(
        self, claim: ClaimInput, policy: Optional[dict]
    ) -> StepResult:
        step = "Policy Validation"
        if policy is None:
            return self._fail(step, f"Policy '{claim.policy_id}' not found.")

        renewal = str(policy.get("renewal_status", "")).upper()
        if renewal != "ACTIVE":
            return self._fail(step, f"Policy renewal status is '{renewal}' — not ACTIVE.",
                              inputs={"policy_id": claim.policy_id},
                              rules=["policy_must_be_active"])

        today = date.today()
        start = policy.get("policy_start_date")
        end   = policy.get("policy_end_date")
        if start and isinstance(start, date) and today < start:
            return self._fail(step, f"Policy has not started yet (starts {start}).")
        if end and isinstance(end, date) and today > end:
            return self._fail(step, f"Policy has expired (ended {end}).")

        rules   = policy.get("submission_rules") or {}
        dd      = int(rules.get("deadline_days_from_treatment", 30))
        if claim.treatment_date:
            deadline = claim.treatment_date + timedelta(days=dd)
            if claim.submission_date > deadline:
                return self._fail(
                    step,
                    f"Submission {claim.submission_date} is past the {dd}-day deadline "
                    f"from treatment date {claim.treatment_date} (deadline: {deadline}).",
                )
        min_amt = float(rules.get("minimum_claim_amount", 0))
        if claim.claimed_amount is not None and claim.claimed_amount < min_amt:
            return self._fail(step,
                              f"Claimed ₹{claim.claimed_amount} is below minimum ₹{min_amt}.")

        return self._ok(
            step, f"Policy '{claim.policy_id}' is ACTIVE and valid.",
            inputs={"policy_id": claim.policy_id},
            outputs={"start": str(start), "end": str(end)},
            rules=["policy_must_be_active", "within_policy_dates"],
            details={"insurer": policy.get("insurer_name", ""),
                     "start": str(start), "end": str(end)},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3A – Wrong Document Detection  (TC001, Req #2)
    # ─────────────────────────────────────────────────────────────────────────
    def step_03a_wrong_document_detection(
        self,
        registry: list[DocumentRecord],
        required_docs: list[str],
    ) -> StepResult:
        """
        Detect when a wrong document type was uploaded instead of a required one.
        e.g. Two PRESCRIPTIONs when PRESCRIPTION + HOSPITAL_BILL is required.
        Produces a specific message naming both the uploaded type and the required type.
        """
        step = "Wrong Document Detection"
        uploaded = [r.doc_type for r in registry]

        # Count how many of each required type are satisfied
        satisfied: set[str] = set()
        used: dict[str, int] = {}   # track how many of each uploaded type are "consumed"
        for req in required_docs:
            for u in uploaded:
                if u == req and used.get(u, 0) < uploaded.count(u):
                    satisfied.add(req)
                    used[u] = used.get(u, 0) + 1
                    break

        unsatisfied = [r for r in required_docs if r not in satisfied]
        if not unsatisfied:
            return self._ok(
                step, "All required document types are correctly present.",
                inputs={"required": required_docs, "uploaded": uploaded},
                rules=["required_doc_types_must_be_present"],
            )

        # Find what was uploaded instead (surplus types)
        messages: list[str] = []
        for missing_req in unsatisfied:
            surplus = [
                t for t in uploaded
                if t not in required_docs or uploaded.count(t) > required_docs.count(t)
            ]
            if surplus:
                wrong = surplus[0]
                messages.append(
                    f"You uploaded {wrong} instead of {missing_req}. "
                    f"Please upload a {missing_req.replace('_', ' ').lower()}."
                )
            else:
                messages.append(
                    f"Required document {missing_req} is missing. "
                    f"Please upload a {missing_req.replace('_', ' ').lower()}."
                )

        return self._fail(
            step, " | ".join(messages),
            inputs={"required": required_docs, "uploaded": uploaded},
            outputs={"unsatisfied": unsatisfied},
            rules=["required_doc_types_must_be_present", "no_type_substitution"],
            details={"required": required_docs, "uploaded": uploaded,
                     "unsatisfied": unsatisfied, "messages": messages},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3B – Unreadable Document Detection  (TC002, Req #3)
    # ─────────────────────────────────────────────────────────────────────────
    def step_03b_unreadable_document_detection(
        self,
        registry: list[DocumentRecord],
        required_docs: list[str],
    ) -> StepResult:
        """
        Detect if any required document has quality == UNREADABLE.
        Names the exact file so the member knows what to re-upload.
        """
        step = "Unreadable Document Detection"
        unreadable = [
            {"file_name": r.file_name, "doc_type": r.doc_type}
            for r in registry
            if r.quality == "UNREADABLE"
        ]
        # Only block if an unreadable doc is of a required type (or no required list given)
        blocking = [
            u for u in unreadable
            if not required_docs or u["doc_type"] in required_docs
        ]

        if blocking:
            msgs = [
                f"Document {u['file_name']} is unreadable. "
                f"Please upload a clearer copy of your "
                f"{u['doc_type'].replace('_', ' ').lower()}."
                for u in blocking
            ]
            return self._fail(
                step, " | ".join(msgs),
                inputs={"checked": [r.file_name for r in registry]},
                outputs={"unreadable": blocking},
                rules=["required_documents_must_be_readable"],
                details={"unreadable_documents": blocking},
            )

        return self._ok(
            step, "All documents are readable.",
            inputs={"checked": [r.file_name for r in registry]},
            rules=["required_documents_must_be_readable"],
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3C – Cross-Document Patient Mismatch  (TC003, Req #4)
    # ─────────────────────────────────────────────────────────────────────────
    def step_03c_cross_document_patient_mismatch(
        self,
        registry: list[DocumentRecord],
    ) -> StepResult:
        """Compare patient names across ALL uploaded documents."""
        step = "Cross-Document Patient Mismatch"
        named = [(r.doc_type, r.patient_name, r.file_name)
                 for r in registry if r.patient_name]

        if len(named) < 2:
            return self._ok(step,
                            "Patient name cross-check not required (fewer than 2 named docs).",
                            rules=["cross_document_patient_consistency"])

        mismatches: list[str] = []
        for i in range(len(named)):
            for j in range(i + 1, len(named)):
                type_a, name_a, _ = named[i]
                type_b, name_b, _ = named[j]
                if not _names_match(name_a, name_b):
                    mismatches.append(
                        f"{type_a.replace('_',' ').title()} belongs to '{name_a}' "
                        f"but {type_b.replace('_',' ').title()} belongs to '{name_b}'."
                    )

        if mismatches:
            return self._fail(
                step, " | ".join(mismatches),
                inputs={"named_docs": {d[0]: d[1] for d in named}},
                outputs={"mismatches": mismatches},
                rules=["all_documents_must_belong_to_same_patient"],
                details={"mismatches": mismatches,
                         "named_docs": {d[0]: d[1] for d in named}},
            )

        return self._ok(
            step, "All documents belong to the same patient.",
            inputs={"named_docs": {d[0]: d[1] for d in named}},
            rules=["all_documents_must_belong_to_same_patient"],
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3D – Required Document Check  (policy-aware)
    # ─────────────────────────────────────────────────────────────────────────
    def step_03d_required_document_check(
        self,
        registry: list[DocumentRecord],
        required_docs: list[str],
        category: str,
    ) -> StepResult:
        step = "Required Document Check"
        uploaded = {r.doc_type for r in registry}
        # Expand with aliases
        expanded = set(uploaded)
        for t in list(uploaded):
            for alias, canonical in DOC_TYPE_ALIASES.items():
                if canonical == t:
                    expanded.add(alias)
                if alias == t:
                    expanded.add(canonical)

        missing = [r for r in required_docs if r not in expanded]
        if missing:
            return self._fail(
                step,
                f"Missing required document(s) for {category} claim: {', '.join(missing)}. "
                f"Please upload: {', '.join(missing)}.",
                inputs={"required": required_docs, "uploaded": list(uploaded)},
                outputs={"missing": missing},
                rules=["all_required_docs_must_be_present"],
                details={"required": required_docs, "uploaded": list(uploaded), "missing": missing},
            )

        return self._ok(
            step, f"All required documents for {category} are present.",
            inputs={"required": required_docs, "uploaded": list(uploaded)},
            rules=["all_required_docs_must_be_present"],
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 4 – Document Quality Check
    # ─────────────────────────────────────────────────────────────────────────
    def step_04_document_quality_check(
        self, registry: list[DocumentRecord], facts: dict
    ) -> StepResult:
        step = "Document Quality Check"
        scores  = [r.confidence for r in registry if r.confidence > 0]
        issues: list[str] = []

        if not scores:
            return self._warn(step,
                              "No quality scores available — proceeding with reduced confidence.",
                              confidence=0.7)

        avg = sum(scores) / len(scores)
        if not facts.get("date"):
            issues.append("Document date is missing")
        if not facts.get("total_amount") and not facts.get("line_items"):
            issues.append("No amount/line items found")
        if not facts.get("patient_name"):
            issues.append("Patient name not extracted")

        if avg < 0.5:
            return self._fail(step,
                              f"Document quality too low (avg confidence: {avg:.2f}). "
                              f"Issues: {'; '.join(issues) or 'Low OCR confidence'}.",
                              confidence=avg, details={"avg_confidence": avg, "issues": issues},
                              fatal=False)
        if avg < 0.75 or issues:
            return self._warn(step,
                              f"Document quality acceptable ({avg:.2f}). "
                              f"Issues: {'; '.join(issues) or 'None'}.",
                              confidence=avg,
                              details={"avg_confidence": avg, "issues": issues})

        return self._ok(step, f"Document quality is good ({avg:.2f}).",
                        confidence=avg, details={"avg_confidence": avg})

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 5 – OCR + Extraction Validation
    # ─────────────────────────────────────────────────────────────────────────
    def step_05_ocr_extraction(self, facts: dict) -> StepResult:
        step = "OCR + Extraction"
        missing = [f for f in ["patient_name", "date"] if not facts.get(f)]
        if missing:
            return self._warn(
                step,
                f"Extraction incomplete — missing: {', '.join(missing)}. "
                "Proceeding with available data.",
                confidence=0.75, details={"missing_fields": missing},
            )
        return self._ok(step,
                        f"Extracted data for patient '{facts.get('patient_name')}'.",
                        confidence=0.95)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 6 – Consistency Validation
    # ─────────────────────────────────────────────────────────────────────────
    def step_06_consistency_validation(
        self, claim: ClaimInput, member: dict, facts: dict
    ) -> StepResult:
        step = "Consistency Validation"
        issues: list[str] = []

        ext  = (facts.get("patient_name") or "").lower().strip()
        mem  = member.get("name", "").lower().strip()
        if ext and mem and not _names_match(ext, mem):
            issues.append(
                f"Patient name on document ('{facts['patient_name']}') "
                f"does not match member name ('{member['name']}')."
            )

        if claim.treatment_date:
            today = date.today()
            if claim.treatment_date > today:
                issues.append(f"Treatment date {claim.treatment_date} is in the future.")
            elif (today - claim.treatment_date).days > 365:
                issues.append(f"Treatment date {claim.treatment_date} is over a year old.")

        if claim.claimed_amount is not None:
            if claim.claimed_amount <= 0:
                issues.append(f"Claimed amount ₹{claim.claimed_amount} is zero or negative.")
            elif claim.claimed_amount > 500000:
                issues.append(f"Claimed amount ₹{claim.claimed_amount} is unusually high.")

        if not issues:
            return self._ok(step, "All document fields are consistent with claim data.",
                            rules=["name_match", "date_sanity", "amount_sanity"])

        return self._warn(step, "Consistency issues: " + " | ".join(issues),
                          confidence=0.70, details={"issues": issues})

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 7 – Coverage Validation
    # ─────────────────────────────────────────────────────────────────────────
    def step_07_coverage_validation(
        self, claim: ClaimInput, policy: dict
    ) -> tuple[StepResult, dict]:
        step = "Coverage Validation"
        opd  = policy.get("opd_categories") or {}
        cat  = (claim.claim_category or "").lower()

        if not cat:
            return (self._fail(step, "Claim category could not be inferred.",
                               details={"available": list(opd.keys())}), {})

        coverage = opd.get(cat)
        if not coverage:
            return (self._fail(
                step,
                f"Category '{claim.claim_category}' is not covered under this policy.",
                inputs={"category": claim.claim_category},
                outputs={"available_categories": list(opd.keys())},
                rules=["category_must_be_in_policy"],
            ), {})

        if not coverage.get("covered", False):
            return (self._fail(step, f"Category '{claim.claim_category}' is marked NOT covered.",
                               details=coverage), {})

        return (self._ok(
            step,
            f"'{claim.claim_category}' is covered (sub-limit ₹{coverage.get('sub_limit', 'unlimited')}).",
            inputs={"category": claim.claim_category},
            outputs={"coverage": coverage},
            rules=["category_must_be_covered"],
            details=coverage,
        ), coverage)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 8 – Waiting Period Check  (Req #10 — eligibility date output)
    # ─────────────────────────────────────────────────────────────────────────
    def step_08_waiting_period_check(
        self, claim: ClaimInput, member: dict, policy: dict, facts: dict
    ) -> StepResult:
        step = "Waiting Period Check"
        wp   = policy.get("waiting_periods") or {}

        jd_raw = member.get("join_date")
        if not jd_raw:
            return self._warn(step, "Member join date unknown — skipping.", confidence=0.8)

        jd = (jd_raw if isinstance(jd_raw, date)
              else datetime.strptime(str(jd_raw), "%Y-%m-%d").date())
        ref  = claim.treatment_date or date.today()
        days = (ref - jd).days

        init_wp = int(wp.get("initial_waiting_period_days", 30))
        if days < init_wp:
            elig = jd + timedelta(days=init_wp)
            return self._fail(
                step,
                f"Initial waiting period of {init_wp} days not fulfilled. "
                f"Member joined {jd}, treatment on {ref} ({days} days — need {init_wp}). "
                f"Eligible from: {elig}.",
                inputs={"join_date": str(jd), "treatment_date": str(ref)},
                outputs={"days_since_join": days, "required": init_wp,
                         "eligibility_date": str(elig)},
                rules=["initial_waiting_period"],
                details={"join_date": str(jd), "days_since_join": days,
                         "initial_wp": init_wp, "eligibility_date": str(elig)},
            )

        # Specific condition keywords
        combined = (
            " ".join(facts.get("medicines") or []) + " "
            + (facts.get("diagnosis") or claim.diagnosis or "")
        ).lower()

        keywords_map = {
            "diabetes":          ["metformin", "insulin", "glipizide", "januvia", "glucophage",
                                   "diabetes", "diabetic", "glimepiride"],
            "hypertension":      ["amlodipine", "lisinopril", "losartan", "atenolol",
                                   "telma", "hypertension", "blood pressure"],
            "thyroid_disorders": ["thyroxine", "eltroxin", "thyronorm", "levothyroxine", "thyroid"],
            "mental_health":     ["sertraline", "fluoxetine", "alprazolam", "clonazepam"],
            "hernia":            ["hernia"],
            "cataract":          ["cataract", "phacoemulsification"],
            "maternity":         ["maternity", "obstetric", "pregnancy"],
            "obesity_treatment": ["obesity", "bariatric", "weight loss", "bmi"],
        }
        specific_wp = wp.get("specific_conditions", {})
        triggered   = [c for c, kws in keywords_map.items() if any(k in combined for k in kws)]

        violations: list[str] = []
        elig_dates: dict[str, str] = {}
        for cond in triggered:
            req_days = int(specific_wp.get(cond, 0))
            if req_days and days < req_days:
                elig = jd + timedelta(days=req_days)
                elig_dates[cond] = str(elig)
                violations.append(
                    f"{cond.replace('_', ' ').title()}: needs {req_days} days "
                    f"({days} elapsed). Eligible from: {elig}."
                )

        if violations:
            return self._fail(
                step, f"Waiting period not fulfilled: {'; '.join(violations)}",
                inputs={"join_date": str(jd), "days_since_join": days},
                outputs={"violations": violations, "eligibility_dates": elig_dates},
                rules=["specific_condition_waiting_period"],
                details={"join_date": str(jd), "days_since_join": days,
                         "violations": violations, "eligibility_dates": elig_dates},
            )

        return self._ok(
            step, f"Waiting period passed. Member active for {days} days.",
            details={"days_since_join": days, "triggered_conditions": triggered},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 9 – Exclusion Check  (Req #13 — deterministic map first, LLM second)
    # ─────────────────────────────────────────────────────────────────────────
    def step_09_exclusion_check(
        self, claim: ClaimInput, policy: dict, facts: dict
    ) -> StepResult:
        step = "Exclusion Check"

        excl     = policy.get("exclusions") or {}
        opd      = policy.get("opd_categories") or {}
        cat      = (claim.claim_category or "").lower()
        g_excl   = [e.lower() for e in excl.get("conditions", [])]
        d_excl   = [e.lower() for e in excl.get("dental_exclusions", [])]
        v_excl   = [e.lower() for e in excl.get("vision_exclusions", [])]
        p_excl   = [e.lower() for e in opd.get(cat, {}).get("excluded_procedures", [])]
        i_excl   = [e.lower() for e in opd.get(cat, {}).get("excluded_items", [])]
        all_excl = g_excl + d_excl + v_excl + p_excl + i_excl

        diag      = (facts.get("diagnosis") or claim.diagnosis or "").lower()
        med_text  = " ".join(facts.get("medicines") or []).lower()
        item_text = " ".join(
            i.get("description", "") for i in (facts.get("line_items") or [])
        ).lower()
        treatment_txt = diag + " " + med_text + " " + item_text

        # ── Deterministic map (Req #13) ──────────────────────────────────
        triggered: list[str] = []
        for excl_name, keywords in EXCLUSION_KEYWORD_MAP.items():
            if any(kw in treatment_txt for kw in keywords):
                triggered.append(f"{excl_name} (keyword match)")

        # ── Policy-level procedure list ──────────────────────────────────
        for ex in all_excl:
            ex_words = [w for w in ex.split() if len(w) > 3]
            if any(w in treatment_txt for w in ex_words):
                entry = f"Policy exclusion: '{ex}'"
                if entry not in triggered:
                    triggered.append(entry)

        if triggered:
            return self._fail(
                step,
                f"Excluded conditions/procedures: {', '.join(triggered)}.",
                inputs={"diagnosis": diag, "line_items": item_text[:200]},
                outputs={"exclusions_triggered": triggered},
                rules=["deterministic_exclusion_map", "policy_exclusion_list"],
                details={"excluded_found": triggered, "diagnosis": diag},
            )

        # ── LLM fallback ─────────────────────────────────────────────────
        inferred: list[str] = []
        if (med_text or item_text or diag) and self._llm:
            result = self._call_llm_json(
                [
                    {"role": "system", "content": (
                        "You are a medical expert. Infer conditions from medicines and line items. "
                        "Return JSON with 'conditions' list."
                    )},
                    {"role": "user", "content": json.dumps({
                        "medicines": facts.get("medicines", []),
                        "line_items": [i.get("description", "") for i in
                                       (facts.get("line_items") or [])],
                        "diagnosis": diag,
                    })},
                ],
                fallback={"conditions": [diag] if diag else []},
            )
            inferred = result.get("conditions", [])
            for cond in inferred:
                cl = cond.lower()
                for ex in all_excl:
                    ex_words = [w for w in ex.split() if len(w) > 3]
                    if any(w in cl for w in ex_words):
                        triggered.append(f"{cond} (LLM inferred, matches: '{ex}')")
                        break
            if triggered:
                return self._fail(step, f"Excluded conditions: {', '.join(triggered)}.",
                                  details={"excluded": triggered, "inferred": inferred})

        return self._ok(
            step, "No excluded conditions detected.",
            inputs={"diagnosis": diag},
            rules=["deterministic_exclusion_map", "llm_condition_inference"],
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 10 – Pre-Auth Check  (Req #6 — REJECTED not WARNING)
    # ─────────────────────────────────────────────────────────────────────────
    def step_10_pre_auth_check(
        self, claim: ClaimInput, policy: dict, facts: dict
    ) -> StepResult:
        step    = "Pre-Auth Check"
        opd_cat = (policy.get("opd_categories") or {}).get(
            (claim.claim_category or "").lower(), {}
        )

        needs  = False
        reason = ""

        if opd_cat.get("requires_pre_auth"):
            needs  = True
            reason = f"{claim.claim_category} requires pre-authorization per policy."

        threshold = float(opd_cat.get("pre_auth_threshold", float("inf")))
        if claim.claimed_amount and claim.claimed_amount > threshold:
            needs  = True
            reason = (
                f"Claimed ₹{claim.claimed_amount:.0f} exceeds pre-auth threshold "
                f"₹{threshold:.0f} for {claim.claim_category}."
            )

        hvt = [t.lower() for t in opd_cat.get("high_value_tests_requiring_pre_auth", [])]
        all_text = (
            " ".join(facts.get("tests_ordered") or []) + " "
            + " ".join(i.get("description", "") for i in (facts.get("line_items") or []))
        ).lower().replace(" ", "")
        matched = [t for t in hvt if t.replace(" ", "") in all_text]
        if matched:
            needs  = True
            reason = (
                f"{', '.join(t.upper() for t in matched)} requires pre-authorization "
                f"for amounts above ₹{threshold:.0f}."
            )

        if needs:
            return self._fail(
                step,
                f"Pre-authorization was required but not obtained. {reason} "
                f"To resubmit: obtain pre-auth from your insurer, then resubmit with "
                f"the pre-auth reference number.",
                confidence=1.0,
                inputs={"category": claim.claim_category, "claimed_amount": claim.claimed_amount},
                outputs={"pre_auth_required": True, "rejection_code": "PRE_AUTH_MISSING"},
                rules=["pre_auth_required_for_high_value", "pre_auth_threshold"],
                details={
                    "requires_pre_auth": True, "reason": reason,
                    "rejection_code": "PRE_AUTH_MISSING",
                    "resubmission_instructions": (
                        "1. Contact your insurer for pre-authorization. "
                        "2. Obtain a pre-auth reference number. "
                        "3. Resubmit with the reference number."
                    ),
                },
            )

        return self._ok(step, "No pre-authorization required.",
                        inputs={"category": claim.claim_category},
                        outputs={"pre_auth_required": False},
                        rules=["pre_auth_threshold"])

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 11 – Fraud Check  (Req #11 — correct same-day threshold → MANUAL_REVIEW)
    # ─────────────────────────────────────────────────────────────────────────
    def step_11_fraud_check(
        self,
        claim: ClaimInput,
        policy: dict,
        member: dict,
        facts: dict,
        recent_claims: list[dict],
    ) -> tuple[StepResult, float]:
        step = "Fraud Check"
        thr  = policy.get("fraud_thresholds") or {}

        same_day_limit    = int(thr.get("same_day_claims_limit", 2))
        monthly_limit     = int(thr.get("monthly_claims_limit", 6))
        high_value_thr    = float(thr.get("high_value_claim_threshold", 25000))
        manual_review_thr = float(thr.get("fraud_score_manual_review_threshold", 0.80))
        auto_manual_above = float(thr.get("auto_manual_review_above", 25000))

        signals:     list[dict] = []
        fraud_score: float      = 0.0

        # Merge external claims history
        all_recent = list(recent_claims)
        ext_ids    = {c.get("claim_id") for c in all_recent}
        for ch in (claim.claims_history or []):
            if ch.get("claim_id") not in ext_ids:
                all_recent.append(ch)

        # Signal 1: Same-day claims  (Req #11)
        same_day = [
            c for c in all_recent
            if str(c.get("treatment_date") or c.get("date", "")) == str(claim.treatment_date or "")
        ]
        same_day_ids = [c.get("claim_id", "?") for c in same_day]
        if len(same_day) >= same_day_limit:
            signals.append({
                "signal": "same_day_claims",
                "description": (
                    f"Member already has {len(same_day)} same-day claim(s) on "
                    f"{claim.treatment_date} (policy limit: {same_day_limit}). "
                    f"This would be claim #{len(same_day) + 1}."
                ),
                "prior_claim_ids": same_day_ids,
                "weight": 0.40,
            })
            fraud_score += 0.40

        # Signal 2: Duplicate amounts
        if claim.claimed_amount:
            dups = [
                c for c in all_recent
                if abs(float(c.get("claimed_amount", c.get("amount", 0)) or 0)
                        - claim.claimed_amount) < 1.0
            ]
            if dups:
                signals.append({"signal": "duplicate_bills",
                                 "description": f"Found {len(dups)} claim(s) with same amount ₹{claim.claimed_amount}",
                                 "weight": 0.25})
                fraud_score += 0.25

        # Signal 3: High-value
        if claim.claimed_amount and claim.claimed_amount > high_value_thr:
            signals.append({"signal": "amount_spike",
                             "description": f"High-value claim ₹{claim.claimed_amount} > ₹{high_value_thr}",
                             "weight": 0.20})
            fraud_score += 0.20

        # Signal 4: Monthly abuse
        if len(all_recent) >= monthly_limit:
            signals.append({"signal": "monthly_abuse",
                             "description": f"Member has {len(all_recent)} claims in 30 days (limit {monthly_limit})",
                             "weight": 0.25})
            fraud_score += 0.25

        # Signal 5: Non-network hospital
        hospital = (facts.get("hospital_name") or claim.hospital_name or "").strip()
        if hospital and claim.policy_id:
            nh = [h.lower() for h in _fetch_network_hospitals(claim.policy_id)]
            if not any(h in hospital.lower() or hospital.lower() in h for h in nh):
                signals.append({"signal": "hospital_risk",
                                 "description": f"'{hospital}' not in network hospital list",
                                 "weight": 0.10})
                fraud_score += 0.10

        fraud_score = round(min(fraud_score, 1.0), 3)

        # LLM explanation (does NOT change the score)
        llm_exp = ""
        if signals and self._llm:
            r = self._call_llm_json(
                [{"role": "system", "content": "Write a brief fraud risk explanation. Return JSON with 'explanation'."},
                 {"role": "user",   "content": json.dumps({"fraud_score": fraud_score, "signals": signals,
                                                           "member_id": claim.member_id}, default=str)}],
                fallback={"explanation": "Score from deterministic signals."},
            )
            llm_exp = r.get("explanation", "")

        details = {
            "fraud_score": fraud_score, "signals": signals,
            "llm_explanation": llm_exp,
            "same_day_prior_claims": same_day_ids,
            "recent_claims_count": len(all_recent),
        }

        if fraud_score >= manual_review_thr:
            return (self._fail(
                step,
                f"High fraud risk (score: {fraud_score:.2f}). "
                f"Signals: {'; '.join(s['description'] for s in signals)}. "
                f"Routing to manual review.",
                confidence=1 - fraud_score, details=details, fatal=False,
                inputs={"claimed_amount": claim.claimed_amount,
                        "treatment_date": str(claim.treatment_date)},
                outputs={"fraud_score": fraud_score, "signals_count": len(signals)},
                rules=["fraud_score_manual_review_threshold"],
            ), fraud_score)

        # Moderate risk
        if fraud_score >= 0.40 or (claim.claimed_amount and claim.claimed_amount > auto_manual_above):
            return (self._fail(
                step,
                f"Moderate fraud risk (score: {fraud_score:.2f}). Flagging for manual review.",
                confidence=1 - fraud_score, details=details, fatal=False,
                rules=["fraud_score_manual_review_threshold"],
            ), fraud_score)

        return (self._ok(step, f"No significant fraud indicators. Score: {fraud_score:.2f}.",
                         confidence=1 - fraud_score, details=details), fraud_score)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 12 – Financial Calculation  (Req #7 & #8)
    # ─────────────────────────────────────────────────────────────────────────
    def step_12_financial_calculation(
        self, claim: ClaimInput, policy: dict, coverage: dict
    ) -> tuple[StepResult, float]:
        """
        Req #7: discounted = amount × (1 − discount%), THEN apply copay.
        Req #8: Per-claim limit exceeded → REJECTED (not silent cap).
        """
        step = "Financial Calculation"

        oc        = policy.get("coverage") or {}
        per_claim = float(oc.get("per_claim_limit", float("inf")))
        sub_limit = float(coverage.get("sub_limit", float("inf")))
        copay_pct = float(coverage.get("copay_percent", 0))
        opd_limit = float(oc.get("annual_opd_limit", float("inf")))
        sum_ins   = float(oc.get("sum_insured_per_employee", float("inf")))

        base = claim.claimed_amount or 0.0
        log: list[str] = []

        # Req #8: Per-claim limit → REJECT
        if base > per_claim and per_claim < float("inf"):
            return (self._fail(
                step,
                f"Claimed ₹{base:.0f} exceeds per-claim limit ₹{per_claim:.0f}. "
                f"Maximum payable per claim is ₹{per_claim:.0f}.",
                confidence=1.0,
                inputs={"claimed_amount": base, "per_claim_limit": per_claim},
                outputs={"rejection_code": "PER_CLAIM_EXCEEDED"},
                rules=["per_claim_limit"],
                details={"claimed_amount": base, "per_claim_limit": per_claim,
                         "rejection_code": "PER_CLAIM_EXCEEDED"},
            ), 0.0)

        # Sub-limit cap
        if base > sub_limit and sub_limit < float("inf"):
            base = sub_limit
            log.append(f"Capped at sub-limit ₹{sub_limit}")

        # Req #7: Network discount FIRST, then copay
        disc_pct     = float(coverage.get("network_discount_percent", 0))
        disc_applied = 0.0
        hospital     = (claim.hospital_name or "").strip()
        if hospital and claim.policy_id and disc_pct > 0:
            nh = [h.lower() for h in _fetch_network_hospitals(claim.policy_id)]
            if any(h in hospital.lower() or hospital.lower() in h for h in nh):
                discounted   = base * (1 - disc_pct / 100)
                disc_applied = base - discounted
                log.append(
                    f"Network discount {disc_pct}%: ₹{base:.2f} → ₹{discounted:.2f} "
                    f"(saved ₹{disc_applied:.2f})"
                )
                base = discounted

        # Copay on already-discounted amount
        copay_amt = base * (copay_pct / 100)
        approved  = base - copay_amt
        if copay_pct > 0:
            log.append(f"Co-pay {copay_pct}%: ₹{base:.2f} → ₹{approved:.2f} (-₹{copay_amt:.2f})")

        if approved > opd_limit and opd_limit < float("inf"):
            approved = opd_limit
            log.append(f"Capped at OPD limit ₹{opd_limit}")
        if approved > sum_ins and sum_ins < float("inf"):
            approved = sum_ins
            log.append(f"Capped at sum insured ₹{sum_ins}")

        approved = round(approved, 2)

        return (self._ok(
            step,
            f"Approved ₹{approved:.2f} (claimed ₹{claim.claimed_amount}). " + "; ".join(log),
            confidence=0.98,
            inputs={"claimed_amount": claim.claimed_amount, "sub_limit": sub_limit,
                    "per_claim_limit": per_claim, "network_discount_pct": disc_pct,
                    "copay_pct": copay_pct},
            outputs={"approved_amount": approved, "discount_applied": round(disc_applied, 2),
                     "copay_amount": round(copay_amt, 2)},
            rules=["network_discount_before_copay", "copay_deduction"],
            details={"claimed_amount": claim.claimed_amount, "approved_amount": approved,
                     "sub_limit": sub_limit, "per_claim_limit": per_claim,
                     "copay_percent": copay_pct, "copay_amount": round(copay_amt, 2),
                     "network_discount_applied": round(disc_applied, 2),
                     "calculation_steps": log},
        ), approved)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 12B – Dental Line-Item Adjudication  (Req #9, TC006)
    # ─────────────────────────────────────────────────────────────────────────
    def step_12b_dental_line_items(
        self, claim: ClaimInput, policy: dict, registry: list[DocumentRecord]
    ) -> tuple[StepResult, float, list[dict], list[dict]]:
        step = "Dental Line-Item Adjudication"

        covered  = [p.lower() for p in _get_covered_procedures(policy, "dental")]
        excluded = [p.lower() for p in _get_excluded_procedures(policy, "dental")]

        all_items = [item for r in registry for item in r.line_items]
        if not all_items:
            return (self._warn(step, "No line items found — using standard financial calculation.",
                               confidence=0.8),
                    claim.claimed_amount or 0.0, [], [])

        approved_items: list[dict] = []
        rejected_items: list[dict] = []

        def _covers(desc: str, lst: list[str]) -> bool:
            dl = desc.lower()
            for p in lst:
                if p in dl or any(w in dl for w in p.split() if len(w) > 3):
                    return True
            return False

        for item in all_items:
            desc   = item.get("description", "")
            if _covers(desc, excluded):
                rejected_items.append({**item, "reason": f"Cosmetic/excluded: '{desc}'"})
            elif _covers(desc, covered) or not excluded:
                approved_items.append(item)
            else:
                approved_items.append({**item, "note": "Uncategorised — approved by default"})

        approved_total = round(sum(float(i.get("amount", 0)) for i in approved_items), 2)
        rejected_total = round(sum(float(i.get("amount", 0)) for i in rejected_items), 2)

        return (self._ok(
            step,
            f"Dental: {len(approved_items)} item(s) approved ₹{approved_total}, "
            f"{len(rejected_items)} rejected ₹{rejected_total}. "
            + (f"Excluded: {', '.join(r.get('reason','') for r in rejected_items)}"
               if rejected_items else ""),
            confidence=0.98,
            inputs={"items": len(all_items), "covered_procs": covered, "excluded_procs": excluded},
            outputs={"approved_total": approved_total, "rejected_total": rejected_total},
            rules=["dental_covered_list", "dental_excluded_list"],
            details={"approved_items": approved_items, "rejected_items": rejected_items,
                     "approved_total": approved_total, "rejected_total": rejected_total},
        ), approved_total, approved_items, rejected_items)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 13 – Decision Generation
    # ─────────────────────────────────────────────────────────────────────────
    def step_13_decision_generation(
        self,
        trace: list[StepResult],
        approved_amount: float,
        claim: ClaimInput,
        fraud_score: float,
        approved_items: list[dict],
        rejected_items: list[dict],
    ) -> tuple[StepResult, DecisionType, str | None]:
        step = "Decision Generation"

        hard_failures = [s for s in trace if not s.passed and s.fatal]
        warnings      = [s for s in trace if s.status == StepStatus.WARNING]
        avg_conf      = sum(s.confidence for s in trace) / len(trace) if trace else 1.0

        # Check rejection codes
        per_claim_exc = any(s.details.get("rejection_code") == "PER_CLAIM_EXCEEDED" for s in trace)
        pre_auth_miss = any(s.details.get("rejection_code") == "PRE_AUTH_MISSING" for s in trace)

        # Manual review conditions
        needs_manual = (
            fraud_score >= 0.40
            or any("manual review" in (s.reason or "").lower() for s in trace)
        )

        if hard_failures:
            codes   = [s.details.get("rejection_code", "") for s in hard_failures if s.details.get("rejection_code")]
            reasons = "; ".join(s.reason or "" for s in hard_failures)
            return (self._ok(step, f"Decision: REJECTED. {reasons}", confidence=avg_conf,
                             outputs={"decision": "REJECTED", "codes": codes}),
                    DecisionType.REJECTED, reasons)

        if needs_manual:
            return (self._ok(step, "Decision: MANUAL_REVIEW.", confidence=avg_conf,
                             outputs={"decision": "MANUAL_REVIEW", "fraud_score": fraud_score}),
                    DecisionType.MANUAL_REVIEW,
                    "Manual review required due to fraud signals or high value.")

        # Dental partial
        if rejected_items:
            claimed = claim.claimed_amount or 0
            return (self._ok(step, f"Decision: PARTIAL — ₹{approved_amount:.2f} of ₹{claimed}.",
                             confidence=avg_conf,
                             outputs={"decision": "PARTIAL", "approved": approved_amount}),
                    DecisionType.PARTIAL,
                    f"Partial approval: {len(rejected_items)} item(s) excluded per policy.")

        # General partial (copay/limits reduced amount)
        claimed = claim.claimed_amount or 0
        if claimed > 0 and approved_amount < claimed * 0.99:
            return (self._ok(step, f"Decision: PARTIAL — ₹{approved_amount:.2f} of ₹{claimed}.",
                             confidence=avg_conf),
                    DecisionType.PARTIAL,
                    f"Partial due to policy limits/copay. "
                    + (f"Warnings: {'; '.join(w.reason or '' for w in warnings)}" if warnings else ""))

        return (self._ok(step, f"Decision: APPROVED — ₹{approved_amount:.2f}.",
                         confidence=avg_conf, outputs={"decision": "APPROVED"}),
                DecisionType.APPROVED, None)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 14 – Explanation Generation
    # ─────────────────────────────────────────────────────────────────────────
    def step_14_explanation_generation(
        self,
        claim: ClaimInput,
        decision: Optional[DecisionType],
        approved_amount: float,
        rejection_reason: Optional[str],
        trace: list[StepResult],
        fraud_score: float,
        approved_items: list[dict],
        rejected_items: list[dict],
    ) -> tuple[StepResult, str]:
        step = "Explanation Generation"

        trace_summary = [
            {"step": s.step_name, "status": s.status.value,
             "confidence": s.confidence, "reason": s.reason}
            for s in trace
        ]

        llm_result = self._call_llm_json(
            [
                {"role": "system", "content": (
                    "You are a health insurance adjudicator. Write a clear, empathetic explanation "
                    "for the policyholder. Return JSON with 'explanation'. Under 200 words. "
                    "State: decision, amount, why, what to do next."
                )},
                {"role": "user", "content": json.dumps({
                    "member_id": claim.member_id, "claim_category": claim.claim_category,
                    "claimed_amount": claim.claimed_amount, "approved_amount": approved_amount,
                    "decision": decision.value if decision else None,
                    "rejection_reason": rejection_reason, "fraud_score": fraud_score,
                    "approved_items": approved_items, "rejected_items": rejected_items,
                    "trace_summary": trace_summary,
                }, default=str)},
            ],
            fallback={"explanation": self._fallback_explanation(
                decision, approved_amount, claim, rejection_reason,
                trace, approved_items, rejected_items,
            )},
        )

        explanation = llm_result.get("explanation") or self._fallback_explanation(
            decision, approved_amount, claim, rejection_reason,
            trace, approved_items, rejected_items,
        )

        return (self._ok(step, "Explanation generated.", confidence=0.95,
                         outputs={"explanation_length": len(explanation)}),
                explanation)

    def _fallback_explanation(
        self,
        decision: Optional[DecisionType],
        approved_amount: float,
        claim: ClaimInput,
        rejection_reason: Optional[str],
        trace: list[StepResult],
        approved_items: list[dict] | None = None,
        rejected_items: list[dict] | None = None,
    ) -> str:
        cat     = claim.claim_category or "medical"
        claimed = claim.claimed_amount or 0

        if decision == DecisionType.APPROVED:
            return (f"Your {cat} claim for ₹{claimed} has been APPROVED. "
                    f"₹{approved_amount:.2f} will be reimbursed within the standard timeline.")
        elif decision == DecisionType.PARTIAL:
            excl = ""
            if rejected_items:
                excl = (" The following items were excluded: "
                        + ", ".join(i.get("description", "") for i in rejected_items) + ".")
            return (f"Your {cat} claim for ₹{claimed} has been PARTIALLY APPROVED. "
                    f"₹{approved_amount:.2f} will be reimbursed.{excl} "
                    f"{rejection_reason or ''}")
        elif decision == DecisionType.REJECTED:
            return (f"Your {cat} claim for ₹{claimed} has been REJECTED. "
                    f"Reason: {rejection_reason or 'Policy conditions not met'}. "
                    f"Please contact support if you believe this is in error.")
        elif decision == DecisionType.MANUAL_REVIEW:
            return (f"Your {cat} claim for ₹{claimed} is under MANUAL REVIEW. "
                    f"Our team will contact you within 2–3 business days. "
                    f"Reason: {rejection_reason or 'High-value or complex claim'}.")
        else:
            return (f"Your {cat} claim requires attention. "
                    f"Reason: {rejection_reason or 'Document validation failed'}. "
                    f"Please re-upload the required documents and resubmit.")

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN PIPELINE ENTRY POINT
    # ─────────────────────────────────────────────────────────────────────────
    def run(self, claim: ClaimInput) -> ClaimDecision:
        """Execute the full adjudication pipeline (v3.0)."""
        claim_id         = str(uuid.uuid4())   # Req #17: always UUID
        trace: list[StepResult] = []
        skipped_step:  Optional[str] = None
        fraud_score:   float         = 0.0
        approved_items: list[dict]   = []
        rejected_items: list[dict]   = []
        approved_amount: float       = 0.0
        inferred_amount: Optional[float] = None
        coverage: dict = {}

        def add(r: StepResult) -> StepResult:
            trace.append(r)
            icon = ("✅" if r.passed and r.status not in (StepStatus.COMPONENT_SKIPPED,)
                    else "⏭️" if r.status == StepStatus.COMPONENT_SKIPPED
                    else "⚠️" if r.status == StepStatus.WARNING else "❌")
            print(f"  {icon} [{r.step_name}] {r.reason}")
            return r

        print(f"\n{'='*60}")
        print(f"🏥 Adjudication Pipeline v3.0 — Claim ID: {claim_id}")
        print(f"   Member: {claim.member_id}")
        print(f"{'='*60}")

        # ── Component failure simulation (Req #12, TC011) ────────────────
        _SKIPPABLE = ["Exclusion Check", "Fraud Check"]
        if claim.simulate_component_failure:
            skipped_step = random.choice(_SKIPPABLE)
            print(f"   ⚡ [SIMULATE] Will skip '{skipped_step}'")

        # ── PRE: Build document registry (Req #1) ────────────────────────
        registry = _build_document_registry(
            claim.document_agent_response,
            claim.extra_documents or [],
        )
        print(f"   📄 Documents registered: {len(registry)}")
        for r in registry:
            print(f"      • {r.file_name} → {r.doc_type} (quality: {r.quality})")

        # ── PRE: Merge facts ──────────────────────────────────────────────
        facts = _merge_facts_from_registry(registry)

        # ── PRE: Multi-document category inference (Req #5) ───────────────
        inferred_cat = _infer_category_multi(registry, {})
        if inferred_cat:
            claim.claim_category = inferred_cat
        print(f"   📎 Category: {claim.claim_category or 'UNKNOWN'}")

        inferred_amount = _infer_amount(facts)
        if inferred_amount:
            claim.claimed_amount = inferred_amount
        print(f"   💰 Amount:   ₹{claim.claimed_amount or 0:.2f}")

        inferred_date = _infer_treatment_date(facts)
        if inferred_date:
            claim.treatment_date = inferred_date
        print(f"   📅 Date:     {claim.treatment_date or 'UNKNOWN'}")

        if facts.get("hospital_name") and not claim.hospital_name:
            claim.hospital_name = facts["hospital_name"]
        if facts.get("diagnosis") and not claim.diagnosis:
            claim.diagnosis = facts["diagnosis"]
        print(f"   🏥 Hospital: {claim.hospital_name or 'Not specified'}")

        # ── Early-exit required docs (using fallback before policy fetch) ──
        req_early = (
            _FALLBACK_REQUIRED_DOCS.get((claim.claim_category or "").upper(), [])
        )

        # ── STEP 3A: Wrong Document Detection (TC001) ─────────────────────
        if req_early:
            try:
                r3a = add(self.step_03a_wrong_document_detection(registry, req_early))
                if r3a.fatal and not r3a.passed:
                    return self._build_doc_failure(claim_id, claim, trace, r3a.reason)
            except Exception as e:
                add(self._warn("Wrong Document Detection", f"Error: {e}", confidence=0.7))

        # ── STEP 3B: Unreadable Document Detection (TC002) ────────────────
        try:
            r3b = add(self.step_03b_unreadable_document_detection(registry, req_early))
            if r3b.fatal and not r3b.passed:
                return self._build_doc_failure(claim_id, claim, trace, r3b.reason)
        except Exception as e:
            add(self._warn("Unreadable Document Detection", f"Error: {e}", confidence=0.7))

        # ── STEP 3C: Cross-Document Patient Mismatch (TC003) ──────────────
        try:
            r3c = add(self.step_03c_cross_document_patient_mismatch(registry))
            if r3c.fatal and not r3c.passed:
                return self._build_doc_failure(claim_id, claim, trace, r3c.reason)
        except Exception as e:
            add(self._warn("Cross-Document Patient Mismatch", f"Error: {e}", confidence=0.7))

        print(f"{'='*60}")

        # ── STEP 1: Member Validation ────────────────────────────────────
        member = _fetch_member(claim.member_id)
        try:
            r1 = add(self.step_01_member_validation(claim, member))
        except Exception as e:
            r1 = add(self._fail("Member Validation", f"Error: {e}", fatal=True))
        if r1.fatal and not r1.passed:
            return self._build_decision(claim_id, claim, trace,
                                        DecisionType.REJECTED, 0.0, r1.reason, 0.0, True)

        # ── Fetch policy ──────────────────────────────────────────────────
        policy = _fetch_policy(claim.policy_id) if claim.policy_id else None

        # Refine category + required docs with actual policy (Req #5, #18)
        if policy:
            ref_cat = _infer_category_multi(registry, policy)
            if ref_cat:
                claim.claim_category = ref_cat
        required_docs = (
            _get_required_docs(policy or {}, claim.claim_category)
            if claim.claim_category else req_early
        )

        # ── STEP 3D: Required Document Check (policy-aware) ───────────────
        if required_docs and claim.claim_category:
            try:
                r3d = add(self.step_03d_required_document_check(
                    registry, required_docs, claim.claim_category
                ))
                if r3d.fatal and not r3d.passed:
                    return self._build_doc_failure(claim_id, claim, trace, r3d.reason,
                                                   r3d.details.get("missing", []))
            except Exception as e:
                add(self._warn("Required Document Check", f"Error: {e}", confidence=0.7))

        # ── STEP 2: Policy Validation ─────────────────────────────────────
        try:
            r2 = add(self.step_02_policy_validation(claim, policy))
        except Exception as e:
            r2 = add(self._fail("Policy Validation", f"Error: {e}", fatal=True))
        if r2.fatal and not r2.passed:
            return self._build_decision(claim_id, claim, trace,
                                        DecisionType.REJECTED, 0.0, r2.reason, 0.0, True)

        # ── STEP 4: Document Quality Check ───────────────────────────────
        try:
            add(self.step_04_document_quality_check(registry, facts))
        except Exception as e:
            add(self._warn("Document Quality Check", f"Error: {e}", confidence=0.7))

        # ── STEP 5: OCR + Extraction ──────────────────────────────────────
        try:
            add(self.step_05_ocr_extraction(facts))
        except Exception as e:
            add(self._warn("OCR + Extraction", f"Error: {e}", confidence=0.6))

        # ── STEP 6: Consistency Validation ───────────────────────────────
        try:
            add(self.step_06_consistency_validation(claim, member or {}, facts))
        except Exception as e:
            add(self._warn("Consistency Validation", f"Error: {e}", confidence=0.7))

        # ── STEP 7: Coverage Validation ───────────────────────────────────
        try:
            r7, coverage = self.step_07_coverage_validation(claim, policy or {})
            add(r7)
        except Exception as e:
            r7 = add(self._fail("Coverage Validation", f"Error: {e}", fatal=True))
            coverage = {}
        if r7.fatal and not r7.passed:
            return self._build_decision(claim_id, claim, trace,
                                        DecisionType.REJECTED, 0.0, r7.reason, 0.0, True)

        # ── STEP 8: Waiting Period Check ──────────────────────────────────
        try:
            r8 = add(self.step_08_waiting_period_check(claim, member or {}, policy or {}, facts))
        except Exception as e:
            r8 = add(self._warn("Waiting Period Check", f"Error: {e}", confidence=0.7))
        if r8.fatal and not r8.passed:
            return self._build_decision(claim_id, claim, trace,
                                        DecisionType.REJECTED, 0.0, r8.reason, 0.0, True)

        # ── STEP 9: Exclusion Check (Req #13) ─────────────────────────────
        if skipped_step == "Exclusion Check":
            r9 = add(self._skip("Exclusion Check", "Simulated component failure — skipped."))
        else:
            try:
                r9 = add(self.step_09_exclusion_check(claim, policy or {}, facts))
            except Exception as e:
                r9 = add(self._warn("Exclusion Check", f"Error: {e}", confidence=0.7))
        if r9.fatal and not r9.passed:
            return self._build_decision(claim_id, claim, trace,
                                        DecisionType.REJECTED, 0.0, r9.reason, 0.0, True)

        # ── STEP 10: Pre-Auth Check (Req #6) ──────────────────────────────
        try:
            r10 = add(self.step_10_pre_auth_check(claim, policy or {}, facts))
        except Exception as e:
            r10 = add(self._warn("Pre-Auth Check", f"Error: {e}", confidence=0.7))
        if r10.fatal and not r10.passed:
            return self._build_decision(claim_id, claim, trace,
                                        DecisionType.REJECTED, 0.0, r10.reason, 0.0, True)

        # ── STEP 11: Fraud Check (Req #11) ────────────────────────────────
        if skipped_step == "Fraud Check":
            r11 = add(self._skip("Fraud Check", "Simulated component failure — skipped."))
            fraud_score = 0.0
        else:
            try:
                recent = _fetch_recent_claims(claim.member_id)
                r11, fraud_score = self.step_11_fraud_check(
                    claim, policy or {}, member or {}, facts, recent
                )
                add(r11)
            except Exception as e:
                r11 = add(self._warn("Fraud Check", f"Error: {e}", confidence=0.7))
                fraud_score = 0.0

        # Moderate/high fraud → MANUAL_REVIEW immediately
        if not r11.passed and not r11.fatal and fraud_score >= 0.40:
            return self._build_decision(
                claim_id, claim, trace, DecisionType.MANUAL_REVIEW,
                0.0, r11.reason, fraud_score, True,
            )

        # ── STEP 12B: Dental Line-Item Adjudication (Req #9) ─────────────
        if (claim.claim_category or "").upper() == "DENTAL":
            try:
                r12b, approved_amount, approved_items, rejected_items = \
                    self.step_12b_dental_line_items(claim, policy or {}, registry)
                add(r12b)
                # Set claim amount to full bill for financial calc sub-limit check
                full_dental = approved_amount + sum(
                    float(i.get("amount", 0)) for i in rejected_items
                )
                claim.claimed_amount = claim.claimed_amount or full_dental
            except Exception as e:
                add(self._warn("Dental Line-Item Adjudication", f"Error: {e}", confidence=0.7))
                approved_amount = claim.claimed_amount or 0.0

        # ── STEP 12: Financial Calculation (Req #7 & #8) ─────────────────
        try:
            # For dental, compute financial calc on the approved dental amount (copay=0)
            calc_claim = ClaimInput(**claim.model_dump())
            if (claim.claim_category or "").upper() == "DENTAL":
                calc_claim.claimed_amount = approved_amount
            r12, calc_approved = self.step_12_financial_calculation(
                calc_claim, policy or {}, coverage
            )
            add(r12)
            if r12.fatal and not r12.passed:
                return self._build_decision(claim_id, claim, trace,
                                            DecisionType.REJECTED, 0.0, r12.reason,
                                            fraud_score, True)
            if (claim.claim_category or "").upper() != "DENTAL":
                approved_amount = calc_approved
            # Dental: use line-item approved total (copay_percent=0 for dental in policy)
        except Exception as e:
            add(self._warn("Financial Calculation", f"Error: {e}", confidence=0.6))
            if not approved_amount:
                approved_amount = claim.claimed_amount or 0.0

        # ── STEP 13: Decision Generation ─────────────────────────────────
        try:
            r13, decision, rejection_reason = self.step_13_decision_generation(
                trace, approved_amount, claim, fraud_score, approved_items, rejected_items
            )
            add(r13)
        except Exception as e:
            add(self._warn("Decision Generation", f"Error: {e}"))
            decision, rejection_reason = DecisionType.MANUAL_REVIEW, str(e)

        # ── STEP 14: Explanation Generation ──────────────────────────────
        try:
            r14, explanation = self.step_14_explanation_generation(
                claim, decision, approved_amount, rejection_reason,
                trace, fraud_score, approved_items, rejected_items,
            )
            add(r14)
        except Exception as e:
            add(self._warn("Explanation Generation", f"Error: {e}"))
            explanation = self._fallback_explanation(
                decision, approved_amount, claim, rejection_reason, trace,
                approved_items, rejected_items,
            )

        # ── Build final decision ───────────────────────────────────────────
        avg_conf = round(sum(s.confidence for s in trace) / len(trace), 3) if trace else 0.5
        if skipped_step:
            avg_conf = round(avg_conf * 0.85, 3)   # Req #12: lower confidence

        final = ClaimDecision(
            claim_id=claim_id,                      # Req #17: UUID
            decision=decision,
            document_validation_status=DocumentValidationStatus.OK,
            approved_amount=approved_amount,
            claimed_amount=claim.claimed_amount or 0.0,
            confidence_score=avg_conf,
            fraud_score=round(fraud_score, 3),
            rejection_reason=rejection_reason,
            explanation=explanation,
            trace=trace,
            needs_manual_review=(decision == DecisionType.MANUAL_REVIEW),
            inferred_category=claim.claim_category,
            inferred_amount=inferred_amount,
            inferred_diagnosis=claim.diagnosis,
            approved_items=approved_items,
            rejected_items=rejected_items,
        )

        print(f"\n{'='*60}")
        print(f"📋 FINAL DECISION : {decision.value}")
        print(f"   Category       : {claim.claim_category}")
        print(f"   Claimed        : ₹{claim.claimed_amount or 0:.2f}")
        print(f"   Approved       : ₹{approved_amount:.2f}")
        print(f"   Confidence     : {avg_conf:.2f}")
        print(f"   Fraud Score    : {fraud_score:.2f}")
        if skipped_step:
            print(f"   ⚡ Skipped Step : {skipped_step} (simulate_component_failure)")
        print(f"{'='*60}\n")

        try:
            _save_decision(
                claim_id, final,
                member_id=claim.member_id,
                policy_id=claim.policy_id or "",
                claim_category=claim.claim_category or "",
                treatment_date=claim.treatment_date or date.today(),
                claimed_amount=claim.claimed_amount or 0.0,
            )
        except Exception as e:
            print(f"[Pipeline] DB persist failed (non-fatal): {e}")

        return final

    # ── Decision builders ─────────────────────────────────────────────────────

    def _build_doc_failure(
        self,
        claim_id: str,
        claim: ClaimInput,
        trace: list[StepResult],
        reason: Optional[str],
        missing_documents: list[str] | None = None,
    ) -> ClaimDecision:
        """Early-exit for document validation failures. decision=null."""
        avg_conf = round(sum(s.confidence for s in trace) / len(trace), 3) if trace else 0.0
        return ClaimDecision(
            claim_id=claim_id,
            decision=None,
            document_validation_status=DocumentValidationStatus.DOCUMENT_VALIDATION_FAILED,
            approved_amount=0.0,
            claimed_amount=claim.claimed_amount or 0.0,
            confidence_score=avg_conf,
            fraud_score=0.0,
            rejection_reason=reason,
            explanation=self._fallback_explanation(None, 0.0, claim, reason, trace),
            trace=trace,
            missing_documents=missing_documents or [],
            needs_manual_review=False,
            inferred_category=claim.claim_category,
        )

    def _build_decision(
        self,
        claim_id: str,
        claim: ClaimInput,
        trace: list[StepResult],
        decision: DecisionType,
        approved_amount: float,
        reason: Optional[str],
        fraud_score: float,
        persist: bool,
        missing_documents: list[str] | None = None,
    ) -> ClaimDecision:
        avg_conf = round(sum(s.confidence for s in trace) / len(trace), 3) if trace else 0.5
        explanation = self._fallback_explanation(decision, approved_amount, claim, reason, trace)

        final = ClaimDecision(
            claim_id=claim_id,           # Req #17: UUID
            decision=decision,
            approved_amount=approved_amount,
            claimed_amount=claim.claimed_amount or 0.0,
            confidence_score=avg_conf,
            fraud_score=fraud_score,
            rejection_reason=reason,
            explanation=explanation,
            trace=trace,
            missing_documents=missing_documents or [],
            needs_manual_review=(decision == DecisionType.MANUAL_REVIEW),
            inferred_category=claim.claim_category,
            inferred_amount=claim.claimed_amount,
            inferred_diagnosis=claim.diagnosis,
        )
        if persist:
            try:
                _save_decision(
                    claim_id, final,
                    member_id=claim.member_id,
                    policy_id=claim.policy_id or "",
                    claim_category=claim.claim_category or "",
                    treatment_date=claim.treatment_date or date.today(),
                    claimed_amount=claim.claimed_amount or 0.0,
                )
            except Exception as e:
                print(f"[Pipeline] DB persist failed (non-fatal): {e}")
        return final


# ──────────────────────────────────────────────────────────────────────────────
# CONVENIENCE FUNCTION  (public API — unchanged signature)
# ──────────────────────────────────────────────────────────────────────────────

def adjudicate_claim(
    member_id: str,
    *,
    documents: list[dict] | None = None,
    document_agent_response: dict | None = None,
    extra_documents: list[dict] | None = None,
) -> ClaimDecision:
    """
    Single entry-point for the adjudication pipeline (v3.0).

    Style 1 — unified array (preferred for multi-document claims):
        adjudicate_claim(member_id="EMP001",
                         documents=[prescription_doc, hospital_bill_doc])

    Style 2 — separate args (backward-compatible):
        adjudicate_claim(member_id="EMP001",
                         document_agent_response=prescription_doc,
                         extra_documents=[hospital_bill_doc])
    """
    if documents is not None:
        primary = documents[0] if documents else None
        extras  = documents[1:] if len(documents) > 1 else []
    else:
        primary = document_agent_response
        extras  = extra_documents or []

    claim = ClaimInput(
        member_id=member_id,
        document_agent_response=primary,
        extra_documents=extras,
    )
    return AdjudicationPipeline().run(claim)