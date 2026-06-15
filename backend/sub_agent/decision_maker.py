"""
decision_maker.py
=================
Automated AI Adjudication Pipeline for Health Insurance Claims.

Architecture  (document-driven — no user-supplied claim fields)
─────────────────────────────────────────────────────────────────
The caller provides ONLY:
    • member_id
    • document_agent_response   (raw JSON from DocumentAgent)

Everything else — claim_category, claimed_amount, treatment_date,
hospital_name, policy_id — is derived automatically from the member
record and the extracted document data.

Pipeline Steps (in order):
  1.  Member Validation        – Verify member exists and is active
  2.  Policy Validation        – Check policy is active and within dates
  3.  Document Verification    – Confirm required docs are uploaded
  4.  Document Quality Check   – Score document readability / confidence
  5.  OCR + Extraction         – Parse & normalise extracted doc data
  6.  Consistency Validation   – Cross-check member names, dates, amounts
  7.  Coverage Validation      – Confirm treatment category is covered
  8.  Waiting Period Check     – Apply policy waiting-period rules
  9.  Exclusion Check          – Detect excluded conditions/procedures
  10. Pre-Auth Check           – Flag procedures needing prior approval
  11. Fraud Check              – Deterministic heuristic scoring + LLM explanation
  12. Financial Calculation    – Compute approved amount after limits/copay
  13. Decision Generation      – Emit APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW
  14. Explanation Generation   – Human-readable explanation + full audit trace
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

import dotenv
import psycopg2
import psycopg2.extras
import pydantic
from pydantic import BaseModel, Field

import sub_agent.llm as llm_module

dotenv.load_dotenv()

# ──────────────────────────────────────────────────────────────────────────────
# ENUMS & BASE MODELS
# ──────────────────────────────────────────────────────────────────────────────

class DecisionType(str, Enum):
    APPROVED            = "APPROVED"
    PARTIALLY_APPROVED  = "PARTIALLY_APPROVED"
    REJECTED            = "REJECTED"
    PENDING_DOCUMENTS   = "PENDING_DOCUMENTS"
    MANUAL_REVIEW       = "MANUAL_REVIEW"


class StepStatus(str, Enum):
    PASSED  = "PASSED"
    FAILED  = "FAILED"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"


class StepResult(BaseModel):
    """Result from a single pipeline step."""
    step_name:        str
    status:           StepStatus
    passed:           bool
    confidence:       float = Field(ge=0.0, le=1.0, default=1.0)
    reason:           Optional[str] = None
    details:          dict[str, Any] = Field(default_factory=dict)
    fatal:            bool = False          # if True, pipeline halts


class ClaimDecision(BaseModel):
    """Final output of the adjudication pipeline."""
    claim_id:           str
    decision:           DecisionType
    approved_amount:    float = 0.0
    claimed_amount:     float = 0.0
    confidence_score:   float = 0.0
    fraud_score:        float = 0.0
    rejection_reason:   Optional[str] = None
    missing_documents:  list[str] = Field(default_factory=list)
    explanation:        str = ""
    trace:              list[StepResult] = Field(default_factory=list)
    needs_manual_review:bool = False
    created_at:         datetime = Field(default_factory=datetime.utcnow)
    # Derived fields for transparency
    inferred_category:  Optional[str] = None
    inferred_amount:    Optional[float] = None
    inferred_diagnosis: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────
# DOCUMENT-TYPE → CLAIM-CATEGORY MAP
# ──────────────────────────────────────────────────────────────────────────────
# Issue #2: Category must be inferred from document_type, not user-provided.

CATEGORY_MAP: dict[str, str] = {
    # Pharmacy
    "PHARMACY_BILL":         "PHARMACY",
    "MEDICINE_BILL":         "PHARMACY",
    "DRUG_INVOICE":          "PHARMACY",
    # Consultation
    "PRESCRIPTION":          "CONSULTATION",
    "DOCTOR_CONSULTATION":   "CONSULTATION",
    "OPD_RECEIPT":           "CONSULTATION",
    # Diagnostic / Lab
    "LAB_REPORT":            "DIAGNOSTIC",
    "DIAGNOSTIC_REPORT":     "DIAGNOSTIC",
    "PATHOLOGY_REPORT":      "DIAGNOSTIC",
    "RADIOLOGY_REPORT":      "DIAGNOSTIC",
    # Dental
    "DENTAL_REPORT":         "DENTAL",
    "DENTAL_BILL":           "DENTAL",
    "DENTAL_INVOICE":        "DENTAL",
    # Vision
    "VISION_REPORT":         "VISION",
    "EYE_REPORT":            "VISION",
    "OPTOMETRY_REPORT":      "VISION",
    # Alternative
    "AYURVEDA_REPORT":       "ALTERNATIVE_MEDICINE",
    "HOMEOPATHY_REPORT":     "ALTERNATIVE_MEDICINE",
    # Hospital
    "HOSPITAL_BILL":         "CONSULTATION",
    "DISCHARGE_SUMMARY":     "CONSULTATION",
}

# Required documents per inferred category (Issue #6)
REQUIRED_DOCS_BY_CATEGORY: dict[str, list[str]] = {
    "PHARMACY":             ["PRESCRIPTION", "PHARMACY_BILL"],
    "CONSULTATION":         ["PRESCRIPTION", "HOSPITAL_BILL"],
    "DIAGNOSTIC":           ["PRESCRIPTION", "LAB_REPORT", "HOSPITAL_BILL"],
    "DENTAL":               ["HOSPITAL_BILL"],
    "VISION":               ["PRESCRIPTION", "HOSPITAL_BILL"],
    "ALTERNATIVE_MEDICINE": ["PRESCRIPTION", "HOSPITAL_BILL"],
}


# ──────────────────────────────────────────────────────────────────────────────
# CLAIM INPUT MODEL  (simplified — Issue #1)
# ──────────────────────────────────────────────────────────────────────────────

class ClaimInput(BaseModel):
    """
    Minimal input — only member_id and the raw document agent response.
    All other fields are DERIVED by the pipeline.
    """
    member_id:              str
    # Raw document agent response (from /extract endpoint)
    document_agent_response: Optional[dict[str, Any]] = None
    # Additional documents if multiple files submitted
    extra_documents:        list[dict[str, Any]] = Field(default_factory=list)

    # ── DERIVED (populated by the pipeline, NOT by the caller) ──
    policy_id:              Optional[str] = None
    claim_category:         Optional[str] = None
    claimed_amount:         Optional[float] = None
    treatment_date:         Optional[date] = None
    submission_date:        date = Field(default_factory=date.today)
    hospital_name:          Optional[str] = None
    diagnosis:              Optional[str] = None


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
    """Fetch member row — includes policy_id for auto-lookup."""
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
    """Issue #5: Query network_hospitals TABLE, not policy JSON."""
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


def _save_decision(claim_id: str, decision: ClaimDecision,
                   member_id: str, policy_id: str,
                   claim_category: str, treatment_date: date,
                   claimed_amount: float) -> bool:
    """Persist claim + decision to database."""
    try:
        conn = _db_connect()
        with conn.cursor() as cur:
            # Upsert claim record
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
                    claim_id,
                    member_id,
                    policy_id,
                    claim_category,
                    treatment_date,
                    date.today(),
                    claimed_amount,
                    decision.decision.value,
                    round(decision.confidence_score, 2),
                    round(decision.fraud_score, 2),
                ),
            )

            # Save decision
            cur.execute(
                """INSERT INTO claim_decisions
                     (claim_id, decision, approved_amount,
                      confidence_score, rejection_reason, explanation, trace)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    claim_id,
                    decision.decision.value,
                    round(decision.approved_amount, 2),
                    round(decision.confidence_score, 2),
                    decision.rejection_reason,
                    decision.explanation,
                    psycopg2.extras.Json([s.model_dump() for s in decision.trace]),
                ),
            )

            # Save each trace step
            for step in decision.trace:
                cur.execute(
                    """INSERT INTO claim_trace_steps
                         (claim_id, step_name, step_status,
                          confidence_score, output_data, reason)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (
                        claim_id,
                        step.step_name,
                        step.status.value,
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
# EXTRACTION HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _extract_facts(doc_agent_response: dict | None,
                   extra_documents: list[dict] | None = None) -> dict[str, Any]:
    """
    Parse the DocumentAgent response into a canonical fact dict.
    This replaces the old step_05_ocr_extraction as a pre-processing stage.
    """
    facts: dict[str, Any] = {
        "patient_name":       None,
        "doctor_name":        None,
        "date":               None,
        "total_amount":       None,
        "line_items":         [],
        "medicines":          [],
        "tests_ordered":      [],
        "diagnosis":          None,
        "hospital_name":      None,
        "document_type":      None,
        "doctor_registration": None,
        "confidence":         0.0,
    }

    source = {}
    if doc_agent_response:
        data = doc_agent_response.get("data", {})
        source = data.get("document", {})
        facts["document_type"] = (
            data.get("classification", {}).get("document_type")
            or source.get("document_type")
        )
        # Capture classification confidence
        cls_conf = data.get("classification", {}).get("confidence", 0)
        doc_conf = source.get("confidence", 0)
        facts["confidence"] = max(float(cls_conf or 0), float(doc_conf or 0))

    # Map all known fields
    for field in ["patient_name", "doctor_name", "date", "total_amount",
                  "line_items", "medicines", "tests_ordered", "diagnosis",
                  "hospital_name", "doctor_registration"]:
        val = source.get(field)
        if val is not None:
            facts[field] = val

    # Derive total_amount from line_items if missing
    if not facts["total_amount"] and facts["line_items"]:
        total = sum(
            float(item.get("amount", 0))
            for item in facts["line_items"]
            if item.get("amount") is not None
        )
        if total > 0:
            facts["total_amount"] = round(total, 2)

    # Merge extra documents (if multiple files uploaded)
    if extra_documents:
        for doc in extra_documents:
            d = doc.get("data", doc)
            src = d.get("document", d)
            for field in ["patient_name", "doctor_name", "diagnosis", "hospital_name"]:
                if not facts[field] and src.get(field):
                    facts[field] = src[field]
            for item in src.get("line_items", []):
                facts["line_items"].append(item)
            for med in src.get("medicines", []):
                if med not in facts["medicines"]:
                    facts["medicines"].append(med)
            for test in src.get("tests_ordered", []):
                if test not in facts["tests_ordered"]:
                    facts["tests_ordered"].append(test)

    return facts


def _infer_category(document_type: str | None) -> str | None:
    """Issue #2: Infer claim category from document type."""
    if not document_type:
        return None
    return CATEGORY_MAP.get(document_type.upper())


def _infer_amount(facts: dict) -> float | None:
    """Derive claimed_amount from extracted document data."""
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
    """Derive treatment_date from extracted document date."""
    date_str = facts.get("date")
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        # Try other common formats
        for fmt in ["%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"]:
            try:
                return datetime.strptime(str(date_str), fmt).date()
            except (ValueError, TypeError):
                continue
    return None


# ──────────────────────────────────────────────────────────────────────────────
# ADJUDICATION PIPELINE
# ──────────────────────────────────────────────────────────────────────────────

class AdjudicationPipeline:
    """
    Runs 14 sequential validation+decision steps for a single claim.

    The pipeline is now fully document-driven:
        process_claim(member_id, document_agent_response) → ClaimDecision

    All claim metadata (category, amount, date, hospital) is derived
    from the document agent response and the member's DB record.
    """

    def __init__(self):
        try:
            self._llm = llm_module.LLMClient()
        except Exception:
            self._llm = None
            print("[Pipeline] LLM client unavailable – LLM steps will be skipped.")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _ok(self, step: str, reason: str = "Passed", confidence: float = 1.0,
            details: dict | None = None, fatal: bool = False) -> StepResult:
        return StepResult(
            step_name=step, status=StepStatus.PASSED, passed=True,
            confidence=confidence, reason=reason,
            details=details or {}, fatal=fatal,
        )

    def _fail(self, step: str, reason: str, confidence: float = 0.0,
              details: dict | None = None, fatal: bool = True) -> StepResult:
        return StepResult(
            step_name=step, status=StepStatus.FAILED, passed=False,
            confidence=confidence, reason=reason,
            details=details or {}, fatal=fatal,
        )

    def _warn(self, step: str, reason: str, confidence: float = 0.8,
              details: dict | None = None) -> StepResult:
        return StepResult(
            step_name=step, status=StepStatus.WARNING, passed=True,
            confidence=confidence, reason=reason,
            details=details or {}, fatal=False,
        )

    def _call_llm_json(self, messages: list[dict], fallback: dict) -> dict:
        """Calls LLM and parses JSON; returns fallback on any error."""
        if self._llm is None:
            return fallback
        try:
            raw = self._llm.call_llm(
                messages, temperature=0.0,
                response_format={"type": "json_object"},
            )
            return json.loads(raw) if raw else fallback
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
            return self._fail(step, f"Member '{claim.member_id}' not found in the system.")

        # Auto-derive policy_id from member record (Issue #1)
        member_policy = member.get("policy_id")
        if not member_policy:
            return self._fail(
                step,
                f"Member '{claim.member_id}' has no policy_id assigned in the database.",
            )

        # Set derived policy_id on claim
        claim.policy_id = str(member_policy)

        return self._ok(
            step,
            f"Member '{member['name']}' (ID: {claim.member_id}) is active under "
            f"policy '{claim.policy_id}'.",
            details={
                "name": member["name"],
                "relationship": member.get("relationship"),
                "join_date": str(member.get("join_date", "")),
                "policy_id": claim.policy_id,
            },
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
            return self._fail(
                step, f"Policy renewal status is '{renewal}' — not ACTIVE.",
                details={"renewal_status": renewal},
            )

        today = date.today()
        start = policy.get("policy_start_date")
        end   = policy.get("policy_end_date")

        if start and isinstance(start, date) and today < start:
            return self._fail(step, f"Policy has not started yet (starts {start}).")

        if end and isinstance(end, date) and today > end:
            return self._fail(step, f"Policy has expired (ended {end}).")

        # Check submission deadline (use treatment_date if available)
        rules       = policy.get("submission_rules") or {}
        deadline_d  = int(rules.get("deadline_days_from_treatment", 30))

        if claim.treatment_date:
            latest_sub  = claim.treatment_date + timedelta(days=deadline_d)
            if claim.submission_date > latest_sub:
                return self._fail(
                    step,
                    f"Claim submitted {claim.submission_date} is beyond the {deadline_d}-day "
                    f"deadline from treatment date {claim.treatment_date} (deadline: {latest_sub}).",
                    details={"deadline": str(latest_sub)},
                )

        # Minimum claim amount
        min_amt = float(rules.get("minimum_claim_amount", 0))
        if claim.claimed_amount is not None and claim.claimed_amount < min_amt:
            return self._fail(
                step,
                f"Claimed amount ₹{claim.claimed_amount} is below the minimum ₹{min_amt}.",
                details={"minimum": min_amt, "claimed": claim.claimed_amount},
            )

        return self._ok(
            step,
            f"Policy '{claim.policy_id}' is ACTIVE and valid.",
            details={
                "insurer": policy.get("insurer_name", ""),
                "start": str(start), "end": str(end),
            },
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3 – Document Verification  (Issue #6 — category-aware)
    # ─────────────────────────────────────────────────────────────────────────
    def step_03_document_verification(
        self, claim: ClaimInput, policy: dict, uploaded_types: set[str]
    ) -> StepResult:
        """
        Issue #6: Document requirements now depend on the inferred category.
        Category is inferred FIRST, then required docs are determined.
        Falls back to policy document_requirements if available.
        """
        step = "Document Verification"
        category = (claim.claim_category or "").upper()

        if not category:
            return self._warn(
                step,
                "Claim category could not be inferred — cannot validate required documents.",
                confidence=0.6,
                details={"uploaded": list(uploaded_types)},
            )

        # Try policy-level document_requirements first, fall back to hardcoded map
        doc_reqs: dict = policy.get("document_requirements") or {}
        policy_reqs = doc_reqs.get(category, {})
        required_docs: list[str] = policy_reqs.get("required", [])

        if not required_docs:
            required_docs = REQUIRED_DOCS_BY_CATEGORY.get(category, [])

        # Normalise uploaded types for matching
        normalised_uploaded = {t.upper().replace(" ", "_") for t in uploaded_types}

        # Also consider aliases (PHARMACY_BILL → PHARMACY_BILL, MEDICINE_BILL → PHARMACY_BILL)
        alias_map = {
            "MEDICINE_BILL": "PHARMACY_BILL",
            "DRUG_INVOICE": "PHARMACY_BILL",
            "DOCTOR_CONSULTATION": "PRESCRIPTION",
            "OPD_RECEIPT": "HOSPITAL_BILL",
        }
        expanded = set(normalised_uploaded)
        for t in normalised_uploaded:
            if t in alias_map:
                expanded.add(alias_map[t])
            # Reverse: if alias maps to something we have
            for alias, canonical in alias_map.items():
                if canonical == t:
                    expanded.add(alias)

        missing = [r for r in required_docs if r.upper() not in expanded]

        if missing:
            return self._fail(
                step,
                f"Missing required document(s) for {category} claim: {', '.join(missing)}. "
                f"Please upload: {', '.join(missing)}.",
                details={"required": required_docs, "uploaded": list(uploaded_types), "missing": missing},
            )

        return self._ok(
            step,
            f"All required documents for {category} are present.",
            details={"required": required_docs, "uploaded": list(uploaded_types)},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 4 – Document Quality Check
    # ─────────────────────────────────────────────────────────────────────────
    def step_04_document_quality_check(
        self, facts: dict
    ) -> StepResult:
        step = "Document Quality Check"
        scores: list[float] = []
        issues: list[str]   = []

        conf = facts.get("confidence")
        if conf is not None and float(conf) > 0:
            scores.append(float(conf))

        if not scores:
            return self._warn(
                step,
                "No quality/confidence scores available — proceeding with reduced confidence.",
                confidence=0.7,
                details={"scores": []},
            )

        avg_score = sum(scores) / len(scores)

        # Check for missing critical fields
        if not facts.get("date"):
            issues.append("Document date is missing")
        if not facts.get("total_amount") and not facts.get("line_items"):
            issues.append("No amount/line items found in document")
        if not facts.get("patient_name"):
            issues.append("Patient name not extracted")

        if avg_score < 0.5:
            return self._fail(
                step,
                f"Document quality too low (avg confidence: {avg_score:.2f}). "
                f"Issues: {'; '.join(issues) or 'Low OCR confidence'}.",
                confidence=avg_score,
                details={"avg_confidence": avg_score, "issues": issues},
                fatal=False,   # degrade confidence, don't halt
            )

        if avg_score < 0.75 or issues:
            return self._warn(
                step,
                f"Document quality acceptable but reduced (avg confidence: {avg_score:.2f}). "
                f"Issues: {'; '.join(issues) or 'None'}.",
                confidence=avg_score,
                details={"avg_confidence": avg_score, "issues": issues},
            )

        return self._ok(
            step,
            f"Document quality is good (avg confidence: {avg_score:.2f}).",
            confidence=avg_score,
            details={"avg_confidence": avg_score, "issues": issues},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 5 – OCR + Extraction  (now validates the pre-extracted facts)
    # ─────────────────────────────────────────────────────────────────────────
    def step_05_ocr_extraction(
        self, facts: dict
    ) -> StepResult:
        """Validate that extraction produced sufficient data."""
        step = "OCR + Extraction"

        missing_fields = [f for f in ["patient_name", "date"] if not facts.get(f)]

        if missing_fields:
            return self._warn(
                step,
                f"Extraction incomplete — missing: {', '.join(missing_fields)}. "
                "Proceeding with available data.",
                confidence=0.75,
                details={"extracted": facts, "missing_fields": missing_fields},
            )

        return self._ok(
            step,
            f"Extracted data from {facts.get('document_type', 'document')} "
            f"for patient '{facts.get('patient_name')}'.",
            confidence=0.95,
            details={"extracted": facts},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 6 – Consistency Validation
    # ─────────────────────────────────────────────────────────────────────────
    def step_06_consistency_validation(
        self, claim: ClaimInput, member: dict, facts: dict
    ) -> StepResult:
        step = "Consistency Validation"
        issues: list[str] = []

        # Name fuzzy-match (allow partial)
        ext_name   = (facts.get("patient_name") or "").lower().strip()
        member_name = member.get("name", "").lower().strip()
        if ext_name and member_name:
            # Accept if either name is a substring of the other
            if ext_name not in member_name and member_name not in ext_name:
                # Try word-level overlap
                ext_words    = set(ext_name.split())
                member_words = set(member_name.split())
                overlap = ext_words & member_words
                if not overlap:
                    issues.append(
                        f"Patient name on document ('{facts['patient_name']}') "
                        f"does not match member name ('{member['name']}')."
                    )

        # Date sanity: document date should be reasonable
        if claim.treatment_date:
            doc_date = claim.treatment_date
            today = date.today()
            if doc_date > today:
                issues.append(f"Treatment date {doc_date} is in the future.")
            elif (today - doc_date).days > 365:
                issues.append(f"Treatment date {doc_date} is more than a year old.")

        # Amount sanity: check for unreasonable amounts
        if claim.claimed_amount is not None:
            if claim.claimed_amount <= 0:
                issues.append(f"Claimed amount ₹{claim.claimed_amount} is zero or negative.")
            elif claim.claimed_amount > 500000:
                issues.append(f"Claimed amount ₹{claim.claimed_amount} is unusually high for OPD.")

        if not issues:
            return self._ok(step, "All document fields are consistent with claim data.",
                            details={"checks": ["name", "date", "amount"]})

        # Soft fail — warn, reduce confidence
        return self._warn(
            step,
            "Consistency issues found: " + " | ".join(issues),
            confidence=0.70,
            details={"issues": issues},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 7 – Coverage Validation
    # ─────────────────────────────────────────────────────────────────────────
    def step_07_coverage_validation(
        self, claim: ClaimInput, policy: dict
    ) -> tuple[StepResult, dict]:
        """Returns (StepResult, coverage_config) for the inferred category."""
        step = "Coverage Validation"
        opd: dict = policy.get("opd_categories") or {}
        category  = (claim.claim_category or "").lower()

        if not category:
            return (
                self._fail(
                    step,
                    "Claim category could not be inferred from documents — cannot validate coverage.",
                    details={"available_categories": list(opd.keys())},
                ),
                {},
            )

        coverage = opd.get(category)
        if not coverage:
            return (
                self._fail(
                    step,
                    f"Claim category '{claim.claim_category}' is not covered under this policy.",
                    details={"available_categories": list(opd.keys())},
                ),
                {},
            )

        if not coverage.get("covered", False):
            return (
                self._fail(
                    step,
                    f"Category '{claim.claim_category}' exists but is marked as NOT covered.",
                    details=coverage,
                ),
                {},
            )

        sub_limit = float(coverage.get("sub_limit", 0))
        if claim.claimed_amount and claim.claimed_amount > sub_limit and sub_limit > 0:
            return (
                self._warn(
                    step,
                    f"Claimed amount ₹{claim.claimed_amount} exceeds sub-limit ₹{sub_limit} "
                    f"for '{claim.claim_category}'. Will apply capping.",
                    confidence=0.9,
                    details={"sub_limit": sub_limit, "claimed": claim.claimed_amount,
                             "capped_to": sub_limit},
                ),
                coverage,
            )

        return (
            self._ok(
                step,
                f"'{claim.claim_category}' is covered with sub-limit ₹{sub_limit}.",
                details=coverage,
            ),
            coverage,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 8 – Waiting Period Check
    # ─────────────────────────────────────────────────────────────────────────
    def step_08_waiting_period_check(
        self, claim: ClaimInput, member: dict, policy: dict, facts: dict
    ) -> StepResult:
        step = "Waiting Period Check"
        wp: dict = policy.get("waiting_periods") or {}

        join_date_raw = member.get("join_date")
        if not join_date_raw:
            return self._warn(step, "Member join date unknown — skipping waiting period check.",
                              confidence=0.8)

        join_date = join_date_raw if isinstance(join_date_raw, date) else \
                    datetime.strptime(str(join_date_raw), "%Y-%m-%d").date()

        reference_date = claim.treatment_date or date.today()
        days_since_join = (reference_date - join_date).days

        # Initial waiting period
        initial_wp = int(wp.get("initial_waiting_period_days", 30))
        if days_since_join < initial_wp:
            return self._fail(
                step,
                f"Initial waiting period of {initial_wp} days not fulfilled. "
                f"Member joined {join_date}, treatment on {reference_date} "
                f"({days_since_join} days — need {initial_wp}).",
                details={"join_date": str(join_date), "days_since_join": days_since_join,
                         "initial_wp": initial_wp},
            )

        # Specific condition waiting periods — use heuristics + diagnosis
        medicines_text = ", ".join(facts.get("medicines") or [])
        diagnosis      = facts.get("diagnosis") or claim.diagnosis or ""

        specific_wp: dict = wp.get("specific_conditions", {})
        triggered_conditions: list[str] = []

        if medicines_text or diagnosis:
            keywords_map = {
                "diabetes":          ["metformin", "insulin", "glipizide", "januvia", "glucophage"],
                "hypertension":      ["amlodipine", "lisinopril", "losartan", "atenolol", "telma"],
                "thyroid_disorders": ["thyroxine", "eltroxin", "thyronorm", "levothyroxine"],
                "mental_health":     ["sertraline", "fluoxetine", "alprazolam", "clonazepam"],
                "hernia":            ["hernia"],
                "cataract":          ["cataract", "phacoemulsification"],
                "maternity":         ["maternity", "obstetric", "pregnancy"],
            }
            combined_text = (medicines_text + " " + diagnosis).lower()
            for condition, kws in keywords_map.items():
                if any(kw in combined_text for kw in kws):
                    triggered_conditions.append(condition)

        wp_violations: list[str] = []
        for condition in triggered_conditions:
            required_days = int(specific_wp.get(condition, 0))
            if required_days and days_since_join < required_days:
                wp_violations.append(
                    f"{condition.replace('_',' ').title()}: requires {required_days} days "
                    f"(currently {days_since_join} days)."
                )

        if wp_violations:
            return self._fail(
                step,
                f"Waiting period not fulfilled for: {'; '.join(wp_violations)}",
                details={
                    "join_date": str(join_date),
                    "days_since_join": days_since_join,
                    "violations": wp_violations,
                    "triggered_conditions": triggered_conditions,
                },
            )

        return self._ok(
            step,
            f"Waiting period check passed. Member has been active for {days_since_join} days.",
            details={"days_since_join": days_since_join, "initial_wp": initial_wp,
                     "triggered_conditions": triggered_conditions},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 9 – Exclusion Check  (Issue #4 — diagnosis-based, not medicine matching)
    # ─────────────────────────────────────────────────────────────────────────
    def step_09_exclusion_check(
        self, claim: ClaimInput, policy: dict, facts: dict
    ) -> StepResult:
        """
        Issue #4: Exclusion check now follows:
            Document → Diagnosis Extraction (via LLM) → Medical Condition
            → Policy Exclusion Check

        Instead of naive substring matching on medicine names.
        """
        step = "Exclusion Check"
        exclusions: dict = policy.get("exclusions") or {}
        opd: dict        = policy.get("opd_categories") or {}

        general_excl   = [e.lower() for e in exclusions.get("conditions", [])]
        dental_excl    = [e.lower() for e in exclusions.get("dental_exclusions", [])]
        vision_excl    = [e.lower() for e in exclusions.get("vision_exclusions", [])]

        category = (claim.claim_category or "").lower()

        # Category-specific exclusions
        excl_procedures = []
        excl_items      = []
        if category == "dental":
            excl_procedures = [e.lower() for e in opd.get("dental", {}).get("excluded_procedures", [])]
        if category == "vision":
            excl_items = [e.lower() for e in opd.get("vision", {}).get("excluded_items", [])]

        all_exclusions = general_excl + dental_excl + vision_excl + excl_procedures + excl_items

        # ── STEP 1: Extract diagnosis from medicines/documents using LLM ──
        medicines_text = ", ".join(facts.get("medicines") or [])
        line_item_text = ", ".join(
            item.get("description", "") for item in (facts.get("line_items") or [])
        )
        doc_diagnosis = facts.get("diagnosis") or claim.diagnosis or ""

        # Use LLM to infer medical conditions from medicines and line items
        inferred_conditions: list[str] = []
        if medicines_text or line_item_text or doc_diagnosis:
            llm_prompt = [
                {
                    "role": "system",
                    "content": (
                        "You are a medical expert. Given the following medicines, line items, "
                        "and any diagnosis from a medical document, infer the most likely "
                        "medical conditions being treated. "
                        "Return JSON with a single key 'conditions' — a list of medical "
                        "condition strings (e.g. ['Fever', 'Ear infection', 'Nerve pain']). "
                        "Be specific about conditions, not just symptoms."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "medicines": facts.get("medicines", []),
                        "line_items": [item.get("description", "") for item in (facts.get("line_items") or [])],
                        "diagnosis_from_document": doc_diagnosis,
                    }),
                },
            ]

            llm_result = self._call_llm_json(
                llm_prompt,
                fallback={"conditions": [doc_diagnosis] if doc_diagnosis else []},
            )
            inferred_conditions = llm_result.get("conditions", [])

        # ── STEP 2: Check inferred conditions against policy exclusions ──
        triggered: list[str] = []
        for condition in inferred_conditions:
            condition_lower = condition.lower()
            for excl in all_exclusions:
                # Check if any significant word (>4 chars) from the exclusion
                # matches the inferred condition
                excl_words = [w for w in excl.split() if len(w) > 3]
                if any(w in condition_lower for w in excl_words):
                    triggered.append(f"{condition} (matches exclusion: '{excl}')")
                    break
                # Also check reverse — condition words in exclusion
                cond_words = [w for w in condition_lower.split() if len(w) > 3]
                if any(w in excl for w in cond_words):
                    triggered.append(f"{condition} (matches exclusion: '{excl}')")
                    break

        if triggered:
            return self._fail(
                step,
                f"Claim contains excluded conditions: {', '.join(triggered)}.",
                details={
                    "excluded_found": triggered,
                    "inferred_conditions": inferred_conditions,
                    "all_exclusions_checked": all_exclusions,
                },
            )

        return self._ok(
            step,
            "No excluded conditions or procedures detected.",
            details={
                "exclusions_checked": len(all_exclusions),
                "inferred_conditions": inferred_conditions,
            },
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 10 – Pre-Auth Check
    # ─────────────────────────────────────────────────────────────────────────
    def step_10_pre_auth_check(
        self, claim: ClaimInput, policy: dict, facts: dict
    ) -> StepResult:
        step = "Pre-Auth Check"
        pre_auth: dict = policy.get("pre_authorization") or {}
        required_for: list[str] = [r.lower() for r in pre_auth.get("required_for", [])]

        category = (claim.claim_category or "").lower()
        opd_cat  = (policy.get("opd_categories") or {}).get(category, {})

        needs_pre_auth = False
        reason_pa      = ""

        # Explicit flag in OPD category
        if opd_cat.get("requires_pre_auth"):
            needs_pre_auth = True
            reason_pa = f"{claim.claim_category} requires pre-authorization per policy."

        # High-value diagnostic test threshold
        threshold = float(opd_cat.get("pre_auth_threshold", float("inf")))
        if claim.claimed_amount and claim.claimed_amount > threshold:
            needs_pre_auth = True
            reason_pa = (f"Claimed amount ₹{claim.claimed_amount} exceeds "
                         f"pre-auth threshold ₹{threshold}.")

        # High-value tests (MRI / CT / PET)
        high_val_tests = [t.lower() for t in opd_cat.get("high_value_tests_requiring_pre_auth", [])]
        tests_text = " ".join(facts.get("tests_ordered") or []).lower()
        matched_tests = [t for t in high_val_tests if t in tests_text]
        if matched_tests:
            needs_pre_auth = True
            reason_pa = f"High-value tests requiring pre-auth detected: {', '.join(matched_tests)}."

        if needs_pre_auth:
            return self._warn(
                step,
                f"Pre-authorization required. {reason_pa} Flagging for manual review.",
                confidence=0.75,
                details={"requires_pre_auth": True, "reason": reason_pa},
            )

        return self._ok(
            step,
            "No pre-authorization required for this claim.",
            details={"requires_pre_auth": False},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 11 – Fraud Check  (Issue #3 — deterministic-first, LLM explains)
    # ─────────────────────────────────────────────────────────────────────────
    def step_11_fraud_check(
        self,
        claim: ClaimInput,
        policy: dict,
        member: dict,
        facts: dict,
        recent_claims: list[dict],
    ) -> tuple[StepResult, float]:
        """
        Issue #3: Deterministic heuristic signals generate the fraud_score.
        LLM only EXPLAINS the score — it does NOT decide.

        Signals:
            1. same_day_claims
            2. duplicate_bills
            3. amount_spike
            4. monthly_abuse
            5. hospital_risk (non-network)
        """
        step = "Fraud Check"
        thresholds: dict = policy.get("fraud_thresholds") or {}

        same_day_limit  = int(thresholds.get("same_day_claims_limit", 2))
        monthly_limit   = int(thresholds.get("monthly_claims_limit", 6))
        high_value_thr  = float(thresholds.get("high_value_claim_threshold", 25000))
        manual_review_thr = float(thresholds.get("fraud_score_manual_review_threshold", 0.80))
        auto_manual_above = float(thresholds.get("auto_manual_review_above", 25000))

        signals:     list[dict[str, Any]] = []
        fraud_score: float                = 0.0

        # ── Signal 1: Same-day claims ──
        same_day = [
            c for c in recent_claims
            if str(c.get("treatment_date", "")) == str(claim.treatment_date or "")
        ]
        if len(same_day) >= same_day_limit:
            signals.append({
                "signal": "same_day_claims",
                "description": f"Member has {len(same_day)} claims on the same day (limit: {same_day_limit})",
                "weight": 0.30,
            })
            fraud_score += 0.30

        # ── Signal 2: Duplicate bills ──
        if claim.claimed_amount:
            duplicate_amounts = [
                c for c in recent_claims
                if abs(float(c.get("claimed_amount", 0) or 0) - claim.claimed_amount) < 1.0
            ]
            if len(duplicate_amounts) >= 1:
                signals.append({
                    "signal": "duplicate_bills",
                    "description": f"Found {len(duplicate_amounts)} recent claim(s) with identical amount ₹{claim.claimed_amount}",
                    "weight": 0.25,
                })
                fraud_score += 0.25

        # ── Signal 3: Amount spike ──
        if claim.claimed_amount and claim.claimed_amount > high_value_thr:
            signals.append({
                "signal": "amount_spike",
                "description": f"High-value claim ₹{claim.claimed_amount} exceeds threshold ₹{high_value_thr}",
                "weight": 0.20,
            })
            fraud_score += 0.20

        # ── Signal 4: Monthly abuse (policy_abuse) ──
        if len(recent_claims) >= monthly_limit:
            signals.append({
                "signal": "monthly_abuse",
                "description": f"Member has {len(recent_claims)} claims in 30 days (limit: {monthly_limit})",
                "weight": 0.25,
            })
            fraud_score += 0.25

        # ── Signal 5: Hospital risk (non-network) ──
        hospital = (facts.get("hospital_name") or claim.hospital_name or "").strip()
        if hospital and claim.policy_id:
            network_hospitals = _fetch_network_hospitals(claim.policy_id)
            nh_lower = [h.lower() for h in network_hospitals]
            if hospital.lower() not in nh_lower:
                # Not in network — minor risk signal
                signals.append({
                    "signal": "hospital_risk",
                    "description": f"Hospital '{hospital}' is not in the network hospital list",
                    "weight": 0.10,
                })
                fraud_score += 0.10

        # Cap at 1.0
        fraud_score = round(min(fraud_score, 1.0), 3)

        # ── LLM explains the score (does NOT decide) ──
        llm_explanation = ""
        if signals and self._llm:
            llm_prompt = [
                {
                    "role": "system",
                    "content": (
                        "You are a health insurance fraud analyst. "
                        "Given the following deterministic fraud signals and their scores, "
                        "write a brief explanation of the fraud risk assessment. "
                        "Return JSON with key 'explanation' (string, max 100 words). "
                        "Do NOT change the fraud score — only explain it."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "fraud_score": fraud_score,
                        "signals": signals,
                        "member_id": claim.member_id,
                        "claimed_amount": claim.claimed_amount,
                    }, default=str),
                },
            ]
            llm_result = self._call_llm_json(
                llm_prompt,
                fallback={"explanation": "Fraud score computed from deterministic signals."},
            )
            llm_explanation = llm_result.get("explanation", "")

        details = {
            "fraud_score":         fraud_score,
            "signals":             signals,
            "llm_explanation":     llm_explanation,
            "recent_claims_count": len(recent_claims),
        }

        if fraud_score >= manual_review_thr:
            return (
                self._fail(
                    step,
                    f"High fraud risk detected (score: {fraud_score:.2f}). "
                    f"Signals: {'; '.join(s['description'] for s in signals)}",
                    confidence=1 - fraud_score,
                    details=details,
                    fatal=False,   # route to manual review, not hard reject
                ),
                fraud_score,
            )

        if fraud_score >= 0.5 or (claim.claimed_amount and claim.claimed_amount > auto_manual_above):
            return (
                self._warn(
                    step,
                    f"Moderate fraud risk (score: {fraud_score:.2f}). Flagged for manual review.",
                    confidence=1 - fraud_score,
                    details=details,
                ),
                fraud_score,
            )

        return (
            self._ok(
                step,
                f"No significant fraud indicators. Fraud score: {fraud_score:.2f}.",
                confidence=1 - fraud_score,
                details=details,
            ),
            fraud_score,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 12 – Financial Calculation  (Issue #5 — network hospitals from DB)
    # ─────────────────────────────────────────────────────────────────────────
    def step_12_financial_calculation(
        self, claim: ClaimInput, policy: dict, coverage: dict
    ) -> tuple[StepResult, float]:
        """Returns (StepResult, approved_amount)."""
        step = "Financial Calculation"

        overall_coverage: dict = policy.get("coverage") or {}
        sum_insured = float(overall_coverage.get("sum_insured_per_employee", float("inf")))
        opd_limit   = float(overall_coverage.get("annual_opd_limit", float("inf")))
        per_claim   = float(overall_coverage.get("per_claim_limit", float("inf")))

        sub_limit   = float(coverage.get("sub_limit", float("inf")))
        copay_pct   = float(coverage.get("copay_percent", 0))

        base_amount = claim.claimed_amount or 0.0

        calc_log: list[str] = []

        # 1. Apply sub-limit cap
        if base_amount > sub_limit:
            base_amount = sub_limit
            calc_log.append(f"Capped at sub-limit: ₹{sub_limit}")

        # 2. Per-claim limit
        if base_amount > per_claim:
            base_amount = per_claim
            calc_log.append(f"Capped at per-claim limit: ₹{per_claim}")

        # 3. Network hospital discount (Issue #5 — queried from DB)
        hospital = (claim.hospital_name or "").lower()
        discount_pct = float(coverage.get("network_discount_percent", 0))

        if hospital and claim.policy_id and discount_pct > 0:
            network_hospitals = _fetch_network_hospitals(claim.policy_id)
            nh_lower = [h.lower() for h in network_hospitals]
            if any(h in hospital or hospital in h for h in nh_lower):
                discount = base_amount * (discount_pct / 100)
                base_amount += discount  # network discount is a BENEFIT
                calc_log.append(f"Network hospital benefit applied ({discount_pct}%): +₹{discount:.2f}")

        # 4. Co-pay deduction
        copay_amount = base_amount * (copay_pct / 100)
        approved     = base_amount - copay_amount
        if copay_pct > 0:
            calc_log.append(f"Co-pay {copay_pct}%: -₹{copay_amount:.2f}")

        # 5. Overall OPD limit sanity
        if approved > opd_limit:
            approved = opd_limit
            calc_log.append(f"Capped at annual OPD limit: ₹{opd_limit}")

        # 6. Sum-insured cap
        if approved > sum_insured:
            approved = sum_insured
            calc_log.append(f"Capped at sum insured: ₹{sum_insured}")

        approved = round(approved, 2)

        return (
            self._ok(
                step,
                f"Approved amount: ₹{approved:.2f} (claimed: ₹{claim.claimed_amount}). " +
                "; ".join(calc_log),
                confidence=0.98,
                details={
                    "claimed_amount":    claim.claimed_amount,
                    "approved_amount":   approved,
                    "sub_limit":         sub_limit,
                    "per_claim_limit":   per_claim,
                    "copay_percent":     copay_pct,
                    "copay_amount":      round(copay_amount, 2),
                    "calculation_steps": calc_log,
                },
            ),
            approved,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 13 – Decision Generation
    # ─────────────────────────────────────────────────────────────────────────
    def step_13_decision_generation(
        self,
        trace: list[StepResult],
        approved_amount: float,
        claim: ClaimInput,
        fraud_score: float,
    ) -> tuple[StepResult, DecisionType, str]:
        """Returns (StepResult, decision, rejection_reason)."""
        step = "Decision Generation"

        hard_failures    = [s for s in trace if not s.passed and s.fatal]
        soft_failures    = [s for s in trace if not s.passed and not s.fatal]
        warnings         = [s for s in trace if s.status == StepStatus.WARNING]
        avg_confidence   = (
            sum(s.confidence for s in trace) / len(trace) if trace else 1.0
        )

        needs_manual = (
            fraud_score >= 0.5
            or (claim.claimed_amount and claim.claimed_amount > 25000)
            or any("pre-auth" in (s.reason or "").lower() for s in trace)
        )

        # Determine decision
        if hard_failures:
            reasons = "; ".join(s.reason or "" for s in hard_failures)
            decision = DecisionType.REJECTED
            return (
                self._ok(step, f"Decision: REJECTED. Reason(s): {reasons}",
                         confidence=avg_confidence),
                decision,
                reasons,
            )

        if needs_manual:
            decision = DecisionType.MANUAL_REVIEW
            return (
                self._ok(step, "Decision: MANUAL_REVIEW — high-value or flagged claim.",
                         confidence=avg_confidence),
                decision,
                "Manual review required due to fraud risk, pre-auth requirement, or high value.",
            )

        claimed = claim.claimed_amount or 0
        if claimed > 0 and approved_amount < claimed * 0.99:
            decision = DecisionType.PARTIALLY_APPROVED
            return (
                self._ok(
                    step,
                    f"Decision: PARTIALLY_APPROVED — ₹{approved_amount:.2f} approved "
                    f"of ₹{claimed} claimed.",
                    confidence=avg_confidence,
                ),
                decision,
                f"Partial approval due to policy limits/copay. "
                f"Warnings: {'; '.join(w.reason or '' for w in warnings)}",
            )

        decision = DecisionType.APPROVED
        return (
            self._ok(step, f"Decision: APPROVED — ₹{approved_amount:.2f} approved.",
                     confidence=avg_confidence),
            decision,
            None,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 14 – Explanation Generation
    # ─────────────────────────────────────────────────────────────────────────
    def step_14_explanation_generation(
        self,
        claim: ClaimInput,
        decision: DecisionType,
        approved_amount: float,
        rejection_reason: Optional[str],
        trace: list[StepResult],
        fraud_score: float,
    ) -> tuple[StepResult, str]:
        step = "Explanation Generation"

        # Build structured summary for LLM
        trace_summary = [
            {
                "step":       s.step_name,
                "status":     s.status.value,
                "confidence": s.confidence,
                "reason":     s.reason,
            }
            for s in trace
        ]

        prompt = [
            {
                "role": "system",
                "content": (
                    "You are a health insurance claims adjudicator. "
                    "Generate a clear, empathetic, and factual explanation of the claim decision "
                    "for the policyholder. Return JSON with a single key 'explanation' (string). "
                    "The explanation must: "
                    "1) State the final decision and approved amount. "
                    "2) Summarise why. "
                    "3) Mention any steps that reduced confidence or caused partial approval. "
                    "4) Be actionable — tell the member what to do next if anything is needed. "
                    "Keep it under 200 words."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "member_id":        claim.member_id,
                    "claim_category":   claim.claim_category,
                    "claimed_amount":   claim.claimed_amount,
                    "approved_amount":  approved_amount,
                    "decision":         decision.value,
                    "rejection_reason": rejection_reason,
                    "fraud_score":      fraud_score,
                    "trace_summary":    trace_summary,
                }, default=str),
            },
        ]

        llm_result = self._call_llm_json(
            prompt,
            fallback={"explanation": self._fallback_explanation(
                decision, approved_amount, claim, rejection_reason, trace
            )},
        )

        explanation = llm_result.get("explanation") or self._fallback_explanation(
            decision, approved_amount, claim, rejection_reason, trace
        )

        return (
            self._ok(
                step,
                "Explanation generated successfully.",
                confidence=0.95,
                details={"explanation_length": len(explanation)},
            ),
            explanation,
        )

    def _fallback_explanation(
        self,
        decision: DecisionType,
        approved_amount: float,
        claim: ClaimInput,
        rejection_reason: Optional[str],
        trace: list[StepResult],
    ) -> str:
        """Rule-based explanation when LLM is unavailable."""
        category = claim.claim_category or "medical"
        claimed  = claim.claimed_amount or 0

        if decision == DecisionType.APPROVED:
            return (
                f"Your {category} claim for ₹{claimed} has been "
                f"APPROVED. An amount of ₹{approved_amount:.2f} will be reimbursed to you "
                f"within the standard processing timeline."
            )
        elif decision == DecisionType.PARTIALLY_APPROVED:
            return (
                f"Your {category} claim for ₹{claimed} has been "
                f"PARTIALLY APPROVED. ₹{approved_amount:.2f} will be reimbursed. "
                f"The remaining amount could not be approved due to policy limits or co-pay rules. "
                f"{rejection_reason or ''}"
            )
        elif decision == DecisionType.REJECTED:
            return (
                f"Your {category} claim for ₹{claimed} has been "
                f"REJECTED. Reason: {rejection_reason or 'Policy conditions not met'}. "
                f"Please contact support if you believe this is in error."
            )
        elif decision == DecisionType.PENDING_DOCUMENTS:
            return (
                f"Your {category} claim for ₹{claimed} requires "
                f"additional documents. Reason: {rejection_reason or 'Missing required documents'}. "
                f"Please upload the missing documents and resubmit."
            )
        else:  # MANUAL_REVIEW
            return (
                f"Your {category} claim for ₹{claimed} has been "
                f"flagged for MANUAL REVIEW. Our team will contact you within 2-3 business days. "
                f"Reason: {rejection_reason or 'High-value or complex claim'}."
            )

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN PIPELINE ENTRY POINT
    # ─────────────────────────────────────────────────────────────────────────
    def run(self, claim: ClaimInput) -> ClaimDecision:
        """
        Execute all 14 adjudication steps sequentially.

        The pipeline is fully document-driven:
            1. Extract facts from document_agent_response
            2. Infer category, amount, date, hospital
            3. Look up member → derive policy_id
            4. Fetch policy → run all checks
        """
        claim_id = str(uuid.uuid4())
        trace: list[StepResult] = []

        def add(result: StepResult) -> StepResult:
            trace.append(result)
            status_icon = "✅" if result.passed else ("⚠️" if result.status == StepStatus.WARNING else "❌")
            print(f"  {status_icon} [{result.step_name}] {result.reason}")
            return result

        print(f"\n{'='*60}")
        print(f"🏥 Adjudication Pipeline — Claim ID: {claim_id}")
        print(f"   Member: {claim.member_id}")
        print(f"{'='*60}")

        # ── PRE-PROCESSING: Extract facts & infer claim fields ────────────
        facts = _extract_facts(claim.document_agent_response, claim.extra_documents)

        # Infer claim category from document type (Issue #2)
        inferred_category = _infer_category(facts.get("document_type"))
        if inferred_category:
            claim.claim_category = inferred_category
        print(f"   📎 Inferred Category: {claim.claim_category or 'UNKNOWN'}")

        # Infer amount from documents (Issue #1)
        inferred_amount = _infer_amount(facts)
        if inferred_amount:
            claim.claimed_amount = inferred_amount
        print(f"   💰 Inferred Amount:   ₹{claim.claimed_amount or 0:.2f}")

        # Infer treatment date from documents (Issue #1)
        inferred_date = _infer_treatment_date(facts)
        if inferred_date:
            claim.treatment_date = inferred_date
        print(f"   📅 Inferred Date:     {claim.treatment_date or 'UNKNOWN'}")

        # Infer hospital name from documents
        if facts.get("hospital_name"):
            claim.hospital_name = facts["hospital_name"]

        # Infer diagnosis
        if facts.get("diagnosis"):
            claim.diagnosis = facts["diagnosis"]

        # Collect uploaded document types for verification
        # Include the primary document type AND all extra-document types
        uploaded_types: set[str] = set()
        if facts.get("document_type"):
            uploaded_types.add(facts["document_type"].upper())

        # ── Scan extra_documents for their document_type ──────────────────
        for extra in (claim.extra_documents or []):
            # Support both raw DocumentAgent response shapes:
            #   { "data": { "classification": { "document_type": ... } } }
            #   { "data": { "document": { "document_type": ... } } }
            #   { "document_type": ... }   (already-unwrapped)
            d = extra.get("data", extra)
            dtype = (
                d.get("classification", {}).get("document_type")
                or d.get("document", {}).get("document_type")
                or d.get("document_type")
            )
            if dtype:
                uploaded_types.add(dtype.upper())

        print(f"   📄 Uploaded Doc Types: {', '.join(uploaded_types) or 'None'}")
        print(f"   🏥 Hospital:          {claim.hospital_name or 'Not specified'}")
        print(f"{'='*60}")

        # ── STEP 1: Member Validation + auto-derive policy_id ─────────────
        member = _fetch_member(claim.member_id)
        try:
            r1 = add(self.step_01_member_validation(claim, member))
        except Exception as e:
            r1 = add(self._fail("Member Validation", f"Unexpected error: {e}", fatal=True))

        if r1.fatal and not r1.passed:
            return self._build_decision(claim_id, claim, trace, DecisionType.REJECTED,
                                        0.0, r1.reason, 0.0, True)

        # ── Fetch policy using member's policy_id ─────────────────────────
        policy = _fetch_policy(claim.policy_id) if claim.policy_id else None

        # ── STEP 2: Policy Validation ────────────────────────────────────
        try:
            r2 = add(self.step_02_policy_validation(claim, policy))
        except Exception as e:
            r2 = add(self._fail("Policy Validation", f"Unexpected error: {e}", fatal=True))

        if r2.fatal and not r2.passed:
            return self._build_decision(claim_id, claim, trace, DecisionType.REJECTED,
                                        0.0, r2.reason, 0.0, True)

        # ── STEP 3: Document Verification (category-aware — Issue #6) ────
        try:
            r3 = add(self.step_03_document_verification(claim, policy or {}, uploaded_types))
        except Exception as e:
            r3 = add(self._fail("Document Verification", f"Unexpected error: {e}", fatal=True))

        if r3.fatal and not r3.passed:
            missing = r3.details.get("missing", [])
            return self._build_decision(
                claim_id, claim, trace, DecisionType.PENDING_DOCUMENTS,
                0.0, r3.reason, 0.0, False,
                missing_documents=missing,
            )

        # ── STEP 4: Document Quality Check ──────────────────────────────
        try:
            r4 = add(self.step_04_document_quality_check(facts))
        except Exception as e:
            r4 = add(self._warn("Document Quality Check", f"Quality check error: {e}", confidence=0.7))

        # ── STEP 5: OCR + Extraction ─────────────────────────────────────
        try:
            r5 = add(self.step_05_ocr_extraction(facts))
        except Exception as e:
            r5 = add(self._warn("OCR + Extraction", f"Extraction error: {e}", confidence=0.6))

        # ── STEP 6: Consistency Validation ──────────────────────────────
        try:
            r6 = add(self.step_06_consistency_validation(claim, member or {}, facts))
        except Exception as e:
            r6 = add(self._warn("Consistency Validation", f"Consistency check error: {e}", confidence=0.7))

        # ── STEP 7: Coverage Validation ──────────────────────────────────
        try:
            r7, coverage = self.step_07_coverage_validation(claim, policy or {})
            add(r7)
        except Exception as e:
            r7 = add(self._fail("Coverage Validation", f"Coverage check error: {e}", fatal=True))
            coverage = {}

        if r7.fatal and not r7.passed:
            return self._build_decision(claim_id, claim, trace, DecisionType.REJECTED,
                                        0.0, r7.reason, 0.0, True)

        # ── STEP 8: Waiting Period Check ─────────────────────────────────
        try:
            r8 = add(self.step_08_waiting_period_check(claim, member or {}, policy or {}, facts))
        except Exception as e:
            r8 = add(self._warn("Waiting Period Check", f"Waiting period check error: {e}", confidence=0.7))

        if r8.fatal and not r8.passed:
            return self._build_decision(claim_id, claim, trace, DecisionType.REJECTED,
                                        0.0, r8.reason, 0.0, True)

        # ── STEP 9: Exclusion Check (diagnosis-based — Issue #4) ─────────
        try:
            r9 = add(self.step_09_exclusion_check(claim, policy or {}, facts))
        except Exception as e:
            r9 = add(self._warn("Exclusion Check", f"Exclusion check error: {e}", confidence=0.7))

        if r9.fatal and not r9.passed:
            return self._build_decision(claim_id, claim, trace, DecisionType.REJECTED,
                                        0.0, r9.reason, 0.0, True)

        # ── STEP 10: Pre-Auth Check ──────────────────────────────────────
        try:
            r10 = add(self.step_10_pre_auth_check(claim, policy or {}, facts))
        except Exception as e:
            r10 = add(self._warn("Pre-Auth Check", f"Pre-auth check error: {e}", confidence=0.7))

        # ── STEP 11: Fraud Check (deterministic — Issue #3) ──────────────
        try:
            recent_claims = _fetch_recent_claims(claim.member_id)
            r11, fraud_score = self.step_11_fraud_check(
                claim, policy or {}, member or {}, facts, recent_claims
            )
            add(r11)
        except Exception as e:
            r11 = add(self._warn("Fraud Check", f"Fraud check error: {e}", confidence=0.7))
            fraud_score = 0.0

        # ── STEP 12: Financial Calculation (network from DB — Issue #5) ──
        try:
            r12, approved_amount = self.step_12_financial_calculation(claim, policy or {}, coverage)
            add(r12)
        except Exception as e:
            add(self._warn("Financial Calculation", f"Calculation error: {e}", confidence=0.6))
            approved_amount = 0.0

        # ── STEP 13: Decision Generation ─────────────────────────────────
        try:
            r13, decision, rejection_reason = self.step_13_decision_generation(
                trace, approved_amount, claim, fraud_score
            )
            add(r13)
        except Exception as e:
            add(self._warn("Decision Generation", f"Decision generation error: {e}"))
            decision, rejection_reason = DecisionType.MANUAL_REVIEW, str(e)

        # ── STEP 14: Explanation Generation ──────────────────────────────
        try:
            r14, explanation = self.step_14_explanation_generation(
                claim, decision, approved_amount, rejection_reason, trace, fraud_score
            )
            add(r14)
        except Exception as e:
            add(self._warn("Explanation Generation", f"Explanation error: {e}"))
            explanation = self._fallback_explanation(decision, approved_amount, claim, rejection_reason, trace)

        # ── Build & persist final decision ───────────────────────────────
        avg_conf = round(sum(s.confidence for s in trace) / len(trace), 3) if trace else 0.5
        needs_manual = decision in (DecisionType.MANUAL_REVIEW,)

        final = ClaimDecision(
            claim_id=claim.member_id,
            decision=decision,
            approved_amount=approved_amount,
            claimed_amount=claim.claimed_amount or 0.0,
            confidence_score=avg_conf,
            fraud_score=round(fraud_score, 3),
            rejection_reason=rejection_reason,
            explanation=explanation,
            trace=trace,
            needs_manual_review=needs_manual,
            inferred_category=claim.claim_category,
            inferred_amount=inferred_amount,
            inferred_diagnosis=claim.diagnosis,
        )

        print(f"\n{'='*60}")
        print(f"📋 FINAL DECISION : {decision.value}")
        print(f"   Category       : {claim.claim_category}")
        print(f"   Claimed Amount : ₹{claim.claimed_amount or 0:.2f}")
        print(f"   Approved Amount: ₹{approved_amount:.2f}")
        print(f"   Confidence     : {avg_conf:.2f}")
        print(f"   Fraud Score    : {fraud_score:.2f}")
        print(f"{'='*60}\n")

        # Attempt to persist to DB (non-blocking)
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
            claim_id=claim.member_id,
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
# CONVENIENCE FUNCTION  (Issue #1 — simplified API)
# ──────────────────────────────────────────────────────────────────────────────

def adjudicate_claim(
    member_id: str,
    *,
    # ── NEW: pass all DocumentAgent responses as a single flat list ──────────
    # documents[0] = primary doc, documents[1:] = extra docs
    documents: list[dict] | None = None,
    # ── OLD (backward-compat): individual args still work ───────────────────
    document_agent_response: dict | None = None,
    extra_documents: list[dict] | None = None,
) -> ClaimDecision:
    """
    Single entry-point for the adjudication pipeline.

    Supports two calling styles (pick one):

    Style 1 — unified array (preferred for multi-document claims):
        adjudicate_claim(
            member_id="EMP001",
            documents=[prescription_doc, hospital_bill_doc, lab_report_doc],
        )
        • documents[0]  → primary DocumentAgent response
        • documents[1:] → extra documents (all types collected for verification)

    Style 2 — separate args (backward-compatible):
        adjudicate_claim(
            member_id="EMP001",
            document_agent_response=prescription_doc,
            extra_documents=[hospital_bill_doc],
        )

    Parameters
    ----------
    member_id               : ID of the claimant (e.g. "EMP001")
    documents               : All DocumentAgent responses as a flat list (Style 1)
    document_agent_response : Primary document response (Style 2)
    extra_documents         : Additional document responses (Style 2)

    Returns
    -------
    ClaimDecision — the full adjudication result with trace.

    Notes
    -----
    The caller does NOT provide:
        • policy_id       → derived from member's DB record
        • claim_category  → inferred from document_type via CATEGORY_MAP
        • claimed_amount  → extracted from document line items / total
        • treatment_date  → extracted from document date
        • hospital_name   → extracted from document data
    """
    # Resolve which calling style was used
    if documents is not None:
        # Style 1: flat array — split into primary + extras
        primary = documents[0] if documents else None
        extras  = documents[1:] if len(documents) > 1 else []
    else:
        # Style 2: backward-compat
        primary = document_agent_response
        extras  = extra_documents or []

    claim = ClaimInput(
        member_id=member_id,
        document_agent_response=primary,
        extra_documents=extras,
    )
    pipeline = AdjudicationPipeline()
    return pipeline.run(claim)