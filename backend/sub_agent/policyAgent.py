from __future__ import annotations
from pathlib import Path
import json
import json
import os
from datetime import date
from enum import Enum
from typing import Any, Optional

import psycopg2
import psycopg2.extras
from pydantic import BaseModel, Field

import sub_agent.llm

from collections import Counter
from difflib import SequenceMatcher
from document_agent.document_identifier import DocumentType

class StepStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"

class ClaimInput(BaseModel):
    member_id: str
    document_agent_response: list[dict[str, Any]] = Field(default_factory=list)
    claim_category: str

class CheckResult(BaseModel):

    check_name: str

    status: StepStatus

    passed: bool
    
    confidence: float = 1.0

    details: dict[str, Any] = Field(
        default_factory=dict
    )

class StepResult(BaseModel):
    step_name: str
    status: StepStatus
    passed: bool
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    fatal: bool = False
    checks: list[CheckResult] = Field(
        default_factory=list
    )

class MemberData(BaseModel):
    member_id: str
    name: str
    policy_id: str
    relationship: Optional[str] = None
    join_date: Optional[date] = None
    primary_member_id: str | None = None

class PolicyData(BaseModel):
    policy_id: str

    policy_name: str
    insurer_name: str

    policy_start_date: date | None = None
    policy_end_date: date | None = None

    coverage: dict = Field(default_factory=dict)

    waiting_periods: dict = Field(default_factory=dict)

    exclusions: dict = Field(default_factory=dict)

    pre_authorization: dict = Field(default_factory=dict)

    submission_rules: dict = Field(default_factory=dict)

    document_requirements: dict = Field(default_factory=dict)

    fraud_thresholds: dict = Field(default_factory=dict)

class DocumentValidationOutput(BaseModel):
    uploaded_document_types: list[str] = Field(default_factory=list)

    inferred_claim_category: str | None = None

    patient_name: str | None = None
    hospital_name: str | None = None

    missing_document_types: list[str] = Field(default_factory=list)

    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    validation_passed: bool = False

class CoverageValidationOutput(BaseModel):

    relationship_covered: bool = True

    waiting_period_passed: bool = True

    specific_waiting_period_passed: bool = True

    submission_window_passed: bool = True

    minimum_amount_passed: bool = True

    exclusion_found: bool = False

    rejection_reasons: list[str] = Field(
        default_factory=list
    )

class FinancialValidationOutput(BaseModel):

    claimed_amount: float = 0.0

    eligible_amount: float = 0.0

    approved_amount: float = 0.0

    annual_limit_remaining: float = 0.0

    family_limit_remaining: float = 0.0

    per_claim_limit_applied: bool = False

    annual_limit_applied: bool = False

    family_floater_limit_applied: bool = False

    rejection_reasons: list[str] = Field(
        default_factory=list
    )
      
class FraudValidationOutput(BaseModel):

    fraud_score: float = 0.0

    monthly_claims_count: int = 0

    same_day_claims_count: int = 0

    manual_review_required: bool = False

    warnings: list[str] = Field(
        default_factory=list
    )
    
class DecisionType(str, Enum):
    APPROVED      = "APPROVED"
    PARTIALLY_APPROVED       = "PARTIALLY_APPROVED"           # was PARTIALLY_APPROVED (Req #15)
    REJECTED      = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    
class DecisionOutput(BaseModel):

    decision: DecisionType

    claimed_amount: float

    approved_amount: float

    fraud_score: float

    needs_manual_review: bool = False

    explanation: str = ""        
        
class BaseAgent:
    def __init__(self):
        try:
            self._llm = sub_agent.llm.LLMClient()
        except Exception:
            self._llm = None

    def _db_connect(self):
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "claims"),
            user=os.getenv("DB_USER", "admin"),
            password=os.getenv("DB_PASSWORD", "admin"),
        )
        
    def check_pass(
    self,
    check_name: str,
    confidence: float = 1.0,
    details: dict | None = None
) -> CheckResult:

        return CheckResult(
            check_name=check_name,
            status=StepStatus.PASSED,
            passed=True,
            confidence=confidence,
            details=details or {}
        )


    def check_fail(
        self,
        check_name: str,
        confidence: float = 0.0,
        details: dict | None = None
    ) -> CheckResult:

        return CheckResult(
            check_name=check_name,
            status=StepStatus.FAILED,
            passed=False,
            confidence=confidence,
            details=details or {}
        )


    def check_warn(
        self,
        check_name: str,
        confidence: float = 0.8,
        details: dict | None = None
    ) -> CheckResult:

        return CheckResult(
            check_name=check_name,
            status=StepStatus.WARNING,
            passed=True,
            confidence=confidence,
            details=details or {}
        )

    def fetch_one(self, query: str, values: tuple):
        conn = None

        try:
            conn = self._db_connect()

            with conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                cur.execute(query, values)
                row = cur.fetchone()

            return dict(row) if row else None

        except Exception as exc:
            raise RuntimeError(f"Database query failed: {exc}")

        finally:
            if conn:
                conn.close()

    def ok(
        self,
        step: str,
        reason: str,
        details: dict | None = None,
        confidence: float = 1.0,
        checks: list[CheckResult] | None = None,
    ):
        return StepResult(
            step_name=step,
            status=StepStatus.PASSED,
            passed=True,
            confidence=confidence,
            reason=reason,
            details=details or {},
            checks=checks or [],
        )   

    def fail(
        self,
        step: str,
        reason: str,
        details: dict | None = None,
        confidence: float = 0.0,
        checks: list[CheckResult] | None = None,
    ):
        return StepResult(
            step_name=step,
            status=StepStatus.FAILED,
            passed=False,
            confidence=confidence,
            reason=reason,
            details=details or {},
            fatal=True,
            checks=checks or [],
        )

class MemberValidationAgent(BaseAgent):

    STEP_NAME = "Member Validation"

    def validate(
        self,
        member_id: str
    ) -> tuple[StepResult, Optional[MemberData]]:
        try:
            checks = []
            if not member_id:
                return (
                    self.fail(
                        self.STEP_NAME,
                        "Member ID is required."
                    ),
                    None
                )
                
            checks.append(
                self.check_pass(
                    "Member Input Check"
                )
            )
            
            member = self.fetch_one(
        """
        SELECT
            member_id,
            name,
            policy_id,
            relationship,
            join_date,
            primary_member_id
        FROM members
        WHERE member_id = %s
        """,
        (member_id,)
    )

            if not member:
                return (
                    self.fail(
                        self.STEP_NAME,
                        f"Member '{member_id}' not found."
                    ),
                    None
                )
                
            checks.append(
                self.check_pass(
                    "Member DB Check"
                )
            )

            if not member.get("policy_id"):
                return (
                    self.fail(
                        self.STEP_NAME,
                        f"Member '{member_id}' has no assigned policy."
                    ),
                    None
                )

            checks.append(
                self.check_pass(
                "Member Policy Check",
            )
            )
            if not member.get("name"):
                return (
                    self.fail(
                        self.STEP_NAME,
                        f"Member '{member_id}' has invalid profile data."
                    ),
                    None
                )
            
            checks.append(
                self.check_pass(
                "Member Name Check",
                )
            )
            member_data = MemberData(**member)

            return (
                self.ok(
                    self.STEP_NAME,
                    "Member validation passed.",
                    details={
                        "member_id": member_data.member_id,
                        "name": member_data.name,
                        "policy_id": member_data.policy_id,
                        "relationship": member_data.relationship,
                        "join_date": str(member_data.join_date)
                        if member_data.join_date
                        else None,
                    },
                    checks=checks
                ),
                member_data
            )
        except Exception as exc:
            raise RuntimeError(f"Database query failed: {exc}")
    
class PolicyAgent(BaseAgent):

    STEP_NAME = "Policy Validation"

    def validate(
        self,
        policy_id: str
    ) -> tuple[StepResult, PolicyData | None]:
        checks = []
        try:
            
            policy = self.fetch_one(
                """
                SELECT *
                FROM policies
                WHERE policy_id = %s
                """,
                (policy_id,)
            )

        except Exception as exc:

            return (
                self._fail(
                    self.STEP_NAME,
                    f"Database error: {exc}"
                ),
                None
            )

        if not policy:

            return (
                self._fail(
                    self.STEP_NAME,
                    f"Policy '{policy_id}' not found."
                ),
                None
            )

        checks.append(
            self.check_pass(
                "Policy DB Check"
            )
        )

        today = date.today()

        start_date = policy.get(
            "policy_start_date"
        )

        end_date = policy.get(
            "policy_end_date"
        )

        if start_date and today < start_date:

            return (
                self._fail(
                    self.STEP_NAME,
                    "Policy not yet active."
                ),
                None
            )
            
        checks.append(
            self.check_pass(
                "Policy Start Date Check"
            )
        )

        if end_date and today > end_date:

            return (
                self._fail(
                    self.STEP_NAME,
                    "Policy expired."
                ),
                None
            )

        checks.append(
            self.check_pass(
                "Policy End Date Check"
            )
        )

        renewal_status = (
            policy.get("renewal_status")
        )

        if renewal_status:

            if renewal_status.upper() in (
                "EXPIRED",
                "TERMINATED"
            ):

                return (
                    self._fail(
                        self.STEP_NAME,
                        f"Policy status is "
                        f"{renewal_status}."
                    ),
                    None
                )
                
        checks.append(
            self.check_pass(
                "Policy Renewal Status Check"
            )
        )

        policy_data = PolicyData(
            policy_id=policy["policy_id"],
            policy_name=policy["policy_name"],
            insurer_name=policy["insurer_name"],
            policy_start_date=policy["policy_start_date"],
            policy_end_date=policy["policy_end_date"],
            coverage=policy.get("coverage") or {},
            waiting_periods=policy.get("waiting_periods") or {},
            exclusions=policy.get("exclusions") or {},
            pre_authorization=policy.get("pre_authorization") or {},
            submission_rules=policy.get("submission_rules") or {},
            document_requirements=policy.get("document_requirements") or {},
            fraud_thresholds=policy.get("fraud_thresholds") or {}
        )
        
        checks.append(
            self.check_pass(
                "Policy Data Check"
            )
        )

        return (
            self.ok(
                self.STEP_NAME,
                "Policy validated successfully.",
                details={
                    "policy_id": policy_data.policy_id,
                    "policy_name": policy_data.policy_name,
                    "insurer_name": policy_data.insurer_name
                },
                checks=checks
            ),
            policy_data
        )

class DocumentValidationAgent(BaseAgent):

    def __init__(self):
        super().__init__()

    def _normalize(self, value: str | None) -> str:
        if not value:
            return ""

        return (
            value.upper()
            .replace(".", "")
            .replace(",", "")
            .replace("-", "")
            .strip()
        )

    def _similar(self, a: str, b: str) -> float:
        return SequenceMatcher(
            None,
            self._normalize(a),
            self._normalize(b)
        ).ratio()

    def validate(
        self,
        documents: list[dict],
        member_name: str,
        claim_category: str,
        policy: PolicyData
    ) -> tuple[StepResult, DocumentValidationOutput]:
        checks = []
        step = "Document Validation"

        output = DocumentValidationOutput(
            inferred_claim_category=claim_category
        )

        if not documents:
            return (
                self.fail(
                    step,
                    "No documents uploaded."
                ),
                output
            )

        policy_category = (
            policy.document_requirements
            .get(claim_category)
        )
        
        checks.append(
            self.check_pass(
                "Document Uploads Check"
            )
        )

        if not policy_category:

            return (
                self.fail(
                    step,
                    f"Unsupported claim category '{claim_category}'."
                ),
                output
            )
            
        checks.append(
            self.check_pass(
                "Claim Category Check"
            )
        )

        uploaded_types = []
        patient_names = []
        hospital_names = []

        for doc in documents:

            extracted = doc["document"]

            doc_type = extracted.get(
                "document_type",
                "UNKNOWN"
            )

            uploaded_types.append(doc_type)

            confidence = extracted.get(
                "confidence",
                0
            )

            if confidence < 0.40:

                output.issues.append(
                    f"{doc_type} unreadable "
                    f"(confidence={confidence})"
                )

            elif confidence < 0.70:

                output.warnings.append(
                    f"{doc_type} low extraction confidence "
                    f"(confidence={confidence})"
                )
                
            checks.append(
                self.check_pass(
                    f"{doc_type} Document Confidence Check"
                )
            )

            patient_name = extracted.get(
                "patient_name"
            )

            if patient_name:
                patient_names.append(patient_name)

            hospital_name = extracted.get(
                "hospital_name"
            )

            if hospital_name:
                hospital_names.append(hospital_name)

        output.uploaded_document_types = uploaded_types

        uploaded_set = set(uploaded_types)

        required_documents = set(
            policy_category.get(
                "required",
                []
            )
        )

        for required_doc in required_documents:

            if required_doc not in uploaded_set:

                output.missing_document_types.append(
                    required_doc
                )

        if patient_names:

            output.patient_name = patient_names[0]

            master_patient = patient_names[0]

            for patient in patient_names[1:]:

                if (
                    self._similar(
                        master_patient,
                        patient
                    ) < 0.80
                ):

                    output.issues.append(
                        f"Patient mismatch detected: "
                        f"'{master_patient}' vs '{patient}'"
                    )

        if output.patient_name:

            if (
                self._similar(
                    member_name,
                    output.patient_name
                ) < 0.80
            ):

                output.issues.append(
                    f"Document patient "
                    f"'{output.patient_name}' "
                    f"does not match member "
                    f"'{member_name}'"
                )
                
        checks.append(
            self.check_pass(
                "Patient Name Check"
            )
        )

        if hospital_names:

            output.hospital_name = hospital_names[0]

            master_hospital = hospital_names[0]

            for hospital in hospital_names[1:]:

                if (
                    self._similar(
                        master_hospital,
                        hospital
                    ) < 0.75
                ):

                    output.warnings.append(
                        f"Hospital mismatch detected: "
                        f"'{master_hospital}' vs '{hospital}'"
                    )
        if not hospital_name and claim_category != "PRESCRIPTION":
            output.issues.append(
                f"Hospital Name not Found"
            )
            
        checks.append(
            self.check_pass(
                "Hospital Name Check"
            )
        )

        duplicate_counter = Counter(
            uploaded_types
        )

        for doc_type, count in duplicate_counter.items():

            if count > 1:

                output.warnings.append(
                    f"Duplicate document uploaded: "
                    f"{doc_type}"
                )
                
        checks.append(
            self.check_pass(
                "Duplicate Document Check"
            )
        )

        if output.missing_document_types:

            output.issues.append(
                "Missing required documents: "
                + ", ".join(
                    output.missing_document_types
                )
            )

        checks.append(
            self.check_pass(
                "Missing Documents Check"
            )
        )
        
        output.validation_passed = (
            len(output.issues) == 0
        )

        if output.validation_passed:

            return (
                self.ok(
                    step,
                    "All documents validated successfully.",
                    details={
                        "claim_category": claim_category,
                        "document_count": len(documents),
                        "uploaded_document_types": uploaded_types,
                        "patient_name": output.patient_name,
                        "hospital_name": output.hospital_name,
                        "warnings": output.warnings
                    },
                    checks=checks
                ),
                output
            )

        return (
            self.fail(
                step,
                "; ".join(output.issues),
                details={
                    "claim_category": claim_category,
                    "missing_documents": output.missing_document_types,
                    "issues": output.issues,
                    "warnings": output.warnings,
                    "uploaded_document_types": uploaded_types
                }
            ),
            output
        )

class CoverageAgent(BaseAgent):

    def __init__(self):
        super().__init__()

    def validate(
        self,
        member: MemberData,
        policy: PolicyData,
        documents: list[dict],
        document_data: DocumentValidationOutput,
        claim_category: str
    ) -> tuple[StepResult, CoverageValidationOutput]:
        checks = []
        step = "Coverage Validation"

        output = CoverageValidationOutput()

        treatment_date = None
        diagnosis = None
        claimed_amount = 0.0

        for doc in documents:

            extracted = doc["document"]

            if not treatment_date:

                value = extracted.get("date")

                if value:

                    try:
                        treatment_date = date.fromisoformat(
                            value
                        )
                    except Exception:
                        pass
                

            if not diagnosis:

                diagnosis = extracted.get(
                    "diagnosis"
                )

            amount = extracted.get(
                "total_amount"
            )

            if amount:

                try:
                    claimed_amount = max(
                        claimed_amount,
                        float(amount)
                    )
                except Exception:
                    pass
            

            if (
                not amount
                and extracted.get("line_items")
            ):

                total = 0.0

                for item in extracted[
                    "line_items"
                ]:

                    value = item.get(
                        "amount"
                    )

                    if value:

                        total += float(
                            value
                        )

                claimed_amount = max(
                    claimed_amount,
                    total
                )
                
        checks.append(
            self.check_pass(
                "Items Claimed Amount Check"
            )
        )

        family_floater = (
            policy.coverage.get(
                "family_floater",
                {}
            )
        )

        covered_relationships = (
            family_floater.get(
                "covered_relationships",
                []
            )
        )

        if (
            member.relationship
            and covered_relationships
            and member.relationship
            not in covered_relationships
        ):

            output.relationship_covered = False

            output.rejection_reasons.append(
                f"Relationship "
                f"'{member.relationship}' "
                f"is not covered."
            )
            
        checks.append(
            self.check_pass(
                "Relationship Check"
            )
        )

        if (
            treatment_date
            and member.join_date
        ):

            days_since_join = (
                treatment_date -
                member.join_date
            ).days

            initial_waiting = (
                policy.waiting_periods.get(
                    "initial_waiting_period_days",
                    0
                )
            )

            if (
                days_since_join
                < initial_waiting
            ):

                output.waiting_period_passed = False

                output.rejection_reasons.append(
                    f"Initial waiting period "
                    f"of {initial_waiting} "
                    f"days not completed."
                )
            if treatment_date < member.join_date:

                output.rejection_reasons.append(
                    "Treatment date occurs before member enrollment date."
                )

                return (
                    self.fail(
                        step,
                        "Treatment date occurs before member enrollment date."
                    ),
                    output
                )
                
        checks.append(
            self.check_pass(
                "Treatment Date Check"
            )
        )

        if (
            diagnosis
            and treatment_date
            and member.join_date
        ):

            diagnosis_lower = (
                diagnosis.lower()
            )

            days_since_join = (
                treatment_date -
                member.join_date
            ).days

            conditions = (
                policy.waiting_periods.get(
                    "specific_conditions",
                    {}
                )
            )

            for (
                condition,
                waiting_days
            ) in conditions.items():

                if (
                    condition.lower()
                    in diagnosis_lower
                ):

                    if (
                        days_since_join
                        < waiting_days
                    ):

                        output.specific_waiting_period_passed = False

                        output.rejection_reasons.append(
                            f"Condition "
                            f"'{condition}' "
                            f"requires "
                            f"{waiting_days} "
                            f"days waiting period."
                        )

        checks.append(
            self.check_pass(
                "Specific Waiting Period Check"
            )
        )
        
        if diagnosis:

            diagnosis_lower = (
                diagnosis.lower()
            )

            exclusions = (
                policy.exclusions.get(
                    "conditions",
                    []
                )
            )

            for exclusion in exclusions:

                if (
                    exclusion.lower()
                    in diagnosis_lower
                ):

                    output.exclusion_found = True

                    output.rejection_reasons.append(
                        f"Excluded condition: "
                        f"{exclusion}"
                    )
        
        checks.append(
            self.check_pass(
                "Exclusion Check"
            )
        )

        minimum_amount = (
            policy.submission_rules.get(
                "minimum_claim_amount",
                0
            )
        )

        if (
            claimed_amount
            and claimed_amount
            < minimum_amount
        ):

            output.minimum_amount_passed = False

            output.rejection_reasons.append(
                f"Claim amount "
                f"{claimed_amount} "
                f"is below minimum "
                f"allowed amount "
                f"{minimum_amount}."
            )
            
        checks.append(
            self.check_pass(
                "Minimum Amount Check"
            )
        )

        if treatment_date:

            deadline = (
                policy.submission_rules.get(
                    "deadline_days_from_treatment",
                    30
                )
            )

            submission_gap = (
                date.today() -
                treatment_date
            ).days

            if submission_gap > deadline:

                output.submission_window_passed = False

                output.rejection_reasons.append(
                    f"Claim submitted "
                    f"after allowed "
                    f"{deadline} day limit."
                )
                
        checks.append(
            self.check_pass(
                "Submission Window Check"
            )
        )

        passed = (
            len(
                output.rejection_reasons
            )
            == 0
        )

        if passed:

            return (
                self.ok(
                    step,
                    "Coverage validation passed.",
                    details={
                        "claim_category":
                            claim_category,
                        "diagnosis":
                            diagnosis,
                        "claimed_amount":
                            claimed_amount,
                        "treatment_date":
                            str(
                                treatment_date
                            )
                    },
                    checks=checks
                ),
                output
            )

        return (
            self.fail(
                step,
                "; ".join(
                    output.rejection_reasons
                ),
                details={
                    "claim_category":
                        claim_category,
                    "rejection_reasons":
                        output.rejection_reasons
                }
            ),
            output
        )

class FinancialAgent(BaseAgent):

    def __init__(self):
        super().__init__()

    def _extract_claimed_amount(
        self,
        documents: list[dict]
    ) -> float:

        claimed_amount = 0.0

        for doc in documents:

            extracted = doc["document"]

            total_amount = extracted.get(
                "total_amount"
            )

            if total_amount:

                claimed_amount = max(
                    claimed_amount,
                    float(total_amount)
                )

                continue

            line_items = extracted.get(
                "line_items",
                []
            )

            if line_items:

                total = 0.0

                for item in line_items:

                    amount = item.get(
                        "amount"
                    )

                    if amount:

                        total += float(
                            amount
                        )

                claimed_amount = max(
                    claimed_amount,
                    total
                )

        return claimed_amount

    def _get_annual_usage(
        self,
        member_id: str
    ) -> float:

        result = self.fetch_one(
            """
            SELECT
                COALESCE(
                    SUM(cd.approved_amount),
                    0
                ) AS used_amount
            FROM claim_decisions cd
            JOIN claims c
                ON c.claim_id = cd.claim_id
            WHERE c.member_id = %s
            AND EXTRACT(
                YEAR FROM c.created_at
            ) = EXTRACT(
                YEAR FROM CURRENT_DATE
            )
            """,
            (member_id,)
        )

        if not result:
            return 0.0

        return float(
            result.get(
                "used_amount",
                0
            )
        )

    def _get_family_floater_usage(
        self,
        member: MemberData
    ) -> float:

        primary_member_id = (
            member.primary_member_id
            or member.member_id
        )

        result = self.fetch_one(
            """
            SELECT
                COALESCE(
                    SUM(cd.approved_amount),
                    0
                ) AS used_amount
            FROM claim_decisions cd
            JOIN claims c
                ON c.claim_id = cd.claim_id
            JOIN members m
                ON m.member_id = c.member_id
            WHERE
                m.primary_member_id = %s
                OR
                m.member_id = %s
            """,
            (
                primary_member_id,
                primary_member_id
            )
        )

        if not result:
            return 0.0

        return float(
            result.get(
                "used_amount",
                0
            )
        )

    def validate(
        self,
        member: MemberData,
        policy: PolicyData,
        documents: list[dict]
    ) -> tuple[
        StepResult,
        FinancialValidationOutput
    ]:
        checks = []
        step = "Financial Validation"

        output = FinancialValidationOutput()

        claimed_amount = (
            self._extract_claimed_amount(
                documents
            )
        )

        output.claimed_amount = (
            claimed_amount
        )

        if claimed_amount <= 0:

            output.rejection_reasons.append(
                "Unable to determine claim amount."
            )

            return (
                self.fail(
                    step,
                    "Unable to determine claim amount."
                ),
                output
            )
            
        checks.append(
            self.check_pass(
                "Claimed Amount Check"
            )
        )

        approved_amount = claimed_amount

        per_claim_limit = (
            policy.coverage.get(
                "per_claim_limit",
                approved_amount
            )
        )

        if approved_amount > per_claim_limit:

            approved_amount = (
                per_claim_limit
            )

            output.per_claim_limit_applied = (
                True
            )
            
        checks.append(
            self.check_pass(
                "Per Claim Limit Check"
            )
        )

        annual_limit = (
            policy.coverage.get(
                "annual_opd_limit",
                approved_amount
            )
        )

        annual_used = (
            self._get_annual_usage(
                member.member_id
            )
        )

        annual_remaining = max(
            0,
            annual_limit - annual_used
        )

        output.annual_limit_remaining = (
            annual_remaining
        )

        if approved_amount > annual_remaining:

            approved_amount = (
                annual_remaining
            )

            output.annual_limit_applied = (
                True
            )

        checks.append(
            self.check_pass(
                "Annual Limit Check"
            )
        )
        
        family_limit = (
            policy.coverage
            .get(
                "family_floater",
                {}
            )
            .get(
                "combined_limit",
                approved_amount
            )
        )

        family_used = (
            self._get_family_floater_usage(
                member
            )
        )

        family_remaining = max(
            0,
            family_limit - family_used
        )

        output.family_limit_remaining = (
            family_remaining
        )

        if approved_amount > family_remaining:

            approved_amount = (
                family_remaining
            )

            output.family_floater_limit_applied = (
                True
            )
            
        checks.append(
            self.check_pass(
                "Family Floater Limit Check"
            )
        )

        output.eligible_amount = (
            claimed_amount
        )

        output.approved_amount = (
            approved_amount
        )

        if approved_amount <= 0:

            output.rejection_reasons.append(
                "No remaining coverage available."
            )

            return (
                self.fail(
                    step,
                    "No remaining coverage available.",
                    details={
                        "claimed_amount":
                            claimed_amount,
                        "annual_remaining":
                            annual_remaining,
                        "family_remaining":
                            family_remaining
                    },
                ),
                output
            )

        return (
            self.ok(
                step,
                "Financial validation passed.",
                details={
                    "claimed_amount":
                        claimed_amount,
                    "approved_amount":
                        approved_amount,
                    "annual_remaining":
                        annual_remaining,
                    "family_remaining":
                        family_remaining,
                    "per_claim_limit":
                        per_claim_limit
                },
                checks=checks
            ),
            output
        )

class FraudAgent(BaseAgent):

    def __init__(self):
        super().__init__()

    def _get_monthly_claims(
        self,
        member_id: str
    ) -> int:

        result = self.fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM claims
            WHERE member_id = %s
            AND created_at >= (
                CURRENT_DATE - INTERVAL '30 days'
            )
            """,
            (member_id,)
        )

        return int(
            result.get("total", 0)
        ) if result else 0

    def _get_same_day_claims(
        self,
        member_id: str,
        treatment_date: date | None
    ) -> int:

        if not treatment_date:
            return 0

        result = self.fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM claims
            WHERE member_id = %s
            AND treatment_date = %s
            """,
            (
                member_id,
                treatment_date
            )
        )

        return int(
            result.get("total", 0)
        ) if result else 0

    def _extract_treatment_date(
        self,
        documents: list[dict]
    ) -> date | None:

        for doc in documents:

            value = (
                doc["document"]
                .get("date")
            )

            if not value:
                continue

            try:
                return date.fromisoformat(
                    value
                )

            except Exception:
                pass

        return None

    def validate(
        self,
        member: MemberData,
        policy: PolicyData,
        documents: list[dict],
        financial_output: FinancialValidationOutput
    ) -> tuple[
        StepResult,
        FraudValidationOutput
    ]:
        checks = []
        step = "Fraud Validation"

        output = FraudValidationOutput()

        thresholds = (
            policy.fraud_thresholds
        )

        treatment_date = (
            self._extract_treatment_date(
                documents
            )
        )

        monthly_claims = (
            self._get_monthly_claims(
                member.member_id
            )
        )

        output.monthly_claims_count = (
            monthly_claims
        )

        monthly_limit = (
            thresholds.get(
                "monthly_claims_limit",
                999
            )
        )

        if monthly_claims > monthly_limit:

            output.fraud_score += 0.30

            output.warnings.append(
                f"Monthly claim count "
                f"({monthly_claims}) "
                f"exceeds limit "
                f"({monthly_limit})."
            )

        checks.append(
            self.check_pass(
                "Monthly Claim Count Check"
            )
        )
        
        same_day_claims = (
            self._get_same_day_claims(
                member.member_id,
                treatment_date
            )
        )

        output.same_day_claims_count = (
            same_day_claims
        )

        same_day_limit = (
            thresholds.get(
                "same_day_claims_limit",
                999
            )
        )

        if same_day_claims > same_day_limit:

            output.fraud_score += 0.25

            output.warnings.append(
                f"Same-day claim count "
                f"({same_day_claims}) "
                f"exceeds limit "
                f"({same_day_limit})."
            )
            
        checks.append(
            self.check_pass(
                "Same-day Claim Count Check"
            )
        )

        high_value_threshold = (
            thresholds.get(
                "high_value_claim_threshold",
                999999999
            )
        )

        if (
            financial_output.claimed_amount
            > high_value_threshold
        ):

            output.fraud_score += 0.20

            output.warnings.append(
                f"High-value claim "
                f"detected "
                f"(₹{financial_output.claimed_amount})."
            )
            
        checks.append(
            self.check_pass(
                "High-value Claim Check"
            )
        )

        manual_review_threshold = (
            thresholds.get(
                "auto_manual_review_above",
                999999999
            )
        )

        if (
            financial_output.claimed_amount
            > manual_review_threshold
        ):

            output.manual_review_required = (
                True
            )

            output.warnings.append(
                f"Claim amount "
                f"exceeds manual review "
                f"threshold "
                f"(₹{manual_review_threshold})."
            )

        checks.append(
            self.check_pass(
                "Manual Review Check"
            )
        )
        
        fraud_score_threshold = (
            thresholds.get(
                "fraud_score_manual_review_threshold",
                0.8
            )
        )

        if (
            output.fraud_score
            >= fraud_score_threshold
        ):

            output.manual_review_required = (
                True
            )

            output.warnings.append(
                f"Fraud score "
                f"({output.fraud_score:.2f}) "
                f"exceeds review threshold."
            )

        checks.append(
            self.check_pass(
                "Fraud Score Check"
            )
        )
        
        output.fraud_score = min(
            output.fraud_score,
            1.0
        )

        return (
            self.ok(
                step,
                "Fraud validation completed.",
                details={
                    "fraud_score":
                        output.fraud_score,
                    "monthly_claims":
                        output.monthly_claims_count,
                    "same_day_claims":
                        output.same_day_claims_count,
                    "manual_review":
                        output.manual_review_required,
                    "warnings":
                        output.warnings
                },
                checks=checks
            ),
            output
        )

class ClaimRepository(BaseAgent):

    def create_claim(
        self,
        member: MemberData,
        policy: PolicyData,
        documents: list[dict],
        document_output: DocumentValidationOutput,
        financial_output: FinancialValidationOutput
    ) -> str:
        
        treatment_date = None

        for doc in documents:

            value = (
                doc["document"]
                .get("date")
            )

            if value:

                try:
                    treatment_date = (
                        date.fromisoformat(
                            value
                        )
                    )
                    break

                except Exception:
                    pass

        result = self.fetch_one(
            """
            INSERT INTO claims (
                member_id,
                policy_id,
                claim_category,
                treatment_date,
                submission_date,
                claimed_amount,
                claim_status,
                confidence_score,
                fraud_score
            )
            VALUES (
                %s,%s,%s,%s,
                CURRENT_DATE,
                %s,
                %s,
                %s,
                %s
            )
            RETURNING claim_id
            """,
            (
                member.member_id,
                policy.policy_id,
                document_output.inferred_claim_category,
                treatment_date,
                financial_output.claimed_amount,
                "PROCESSING",
                1.0,
                0.0
            )
        )

        return str(
            result["claim_id"]
        )
        
class DecisionAgent(BaseAgent):

    def __init__(self):
        super().__init__()

    def _generate_explanation(
        self,
        decision: DecisionType,
        financial_output: FinancialValidationOutput,
        fraud_output: FraudValidationOutput,
        coverage_output: CoverageValidationOutput
    ) -> str:

        prompt = f"""
You are an insurance claim explanation assistant.

Return ONLY valid JSON.

Format:

{{
    "explanation":"string"
}}

Claim Decision:
{decision.value}

Claimed Amount:
{financial_output.claimed_amount}

Approved Amount:
{financial_output.approved_amount}

Coverage Validation Issues:
{coverage_output.rejection_reasons}

Fraud Warnings:
{fraud_output.warnings}

Rules:

- Write for a customer.
- Keep under 80 words.
- Do not mention internal systems.
- If PARTIALLY_APPROVED, explain why amount was reduced.
- If REJECTED, explain the rejection reason.
- If MANUAL_REVIEW, explain that additional review is required.
- If APPROVED, confirm approval amount.
"""

        messages = [
            {
                "role": "system",
                "content": prompt
            }
        ]

        response = self._llm.call_llm_json(
            messages,
            {
                "explanation":
                "Decision processed successfully."
            }
        )

        return response.get(
            "explanation",
            "Decision processed successfully."
        )

    def validate(
        self,
        coverage_result: StepResult,
        coverage_output: CoverageValidationOutput,
        financial_result: StepResult,
        financial_output: FinancialValidationOutput,
        fraud_result: StepResult,
        fraud_output: FraudValidationOutput
    ) -> tuple[
        StepResult,
        DecisionOutput
    ]:
        checks = []
        step = "Decision"

        decision = None

        if not coverage_result.passed:

            decision = DecisionType.REJECTED

        elif not financial_result.passed:

            decision = DecisionType.REJECTED

        elif fraud_output.manual_review_required:

            decision = (
                DecisionType.MANUAL_REVIEW
            )

        elif (
            financial_output.approved_amount
            <
            financial_output.claimed_amount
        ):

            decision = (
                DecisionType.PARTIALLY_APPROVED
            )

        else:

            decision = (
                DecisionType.APPROVED
            )

        checks.append(
            self.check_pass(
                "Decision Check"
            )
        )
        
        explanation = (
            self._generate_explanation(
                decision,
                financial_output,
                fraud_output,
                coverage_output
            )
        )

        output = DecisionOutput(
            decision=decision,
            claimed_amount=
                financial_output.claimed_amount,
            approved_amount=
                financial_output.approved_amount,
            fraud_score=
                fraud_output.fraud_score,
            needs_manual_review=
                fraud_output.manual_review_required,
            explanation=explanation
        )
        
        checks.append(
            self.check_pass(
                "Explanation Check"
            )
        )

        return (
            self.ok(
                step,
                f"Final decision: "
                f"{decision.value}",
                details=output.model_dump(),
                checks=checks
            ),
            output
        )

class ClaimProcessingPipeline:

    def __init__(
        self,
        member_id: str,
        claim_category: str,
        output_dir: str
    ):
        self._llm = sub_agent.llm.LLMClient()
        self.member_id = member_id
        self.claim_category = claim_category
        self.output_dir = Path(output_dir)

        self.response = {}

        self.member = None
        self.policy = None
        self.documents = None

        self.member_result = None
        self.policy_result = None
        self.document_result = None
        self.coverage_result = None
        self.finance_result = None
        self.fraud_result = None
        self.decision_result = None

        self.document_output = None
        self.coverage_output = None
        self.finance_output = None
        self.fraud_output = None
        self.decision_output = None

    def run(self):
        try:
            self._validate_member()
            self._validate_policy()
            self._load_documents()
            print("Document Validation")
            self._validate_documents()
            self._validate_coverage()
            self._validate_finance()
            self._validate_fraud()
            self._make_decision()
            self._save_output()
        except Exception as e:
            self.response["error"] = str(e)
            self._generate_message()
        return self.response

    # ---------------------------------------------------
    # Member Validation
    # ---------------------------------------------------
    def _validate_member(self):

        agent = MemberValidationAgent()

        self.member_result, self.member = agent.validate(
            self.member_id
        )

        self.response["member"] = (
            self.member.model_dump(mode='json')
            if self.member else {}
        )

        self.response["member_result"] = (
            self.member_result.model_dump(mode='json')
            if self.member_result else {}
        )

    # ---------------------------------------------------
    # Policy Validation
    # ---------------------------------------------------
    def _validate_policy(self):

        if not self.member:
            return

        agent = PolicyAgent()

        self.policy_result, self.policy = agent.validate(
            policy_id=self.member.policy_id
        )

        self.response["policy"] = (
            self.policy.model_dump(mode='json')
            if self.policy else {}
        )

        self.response["policy_result"] = (
            self.policy_result.model_dump(mode='json')
            if self.policy_result else {}
        )

    # ---------------------------------------------------
    # Load Documents
    # ---------------------------------------------------
    def _load_documents(self):

        document_dir = Path(
            f"./documents/{self.member_id}"
        )

        if not document_dir.exists():
            document_requirements = (
                self.response
                    .get("policy", {})
                    .get("document_requirements", {})
            )

            if self.claim_category not in document_requirements:
                raise ValueError(
                    f"No document requirements configured "
                    f"for claim category '{self.claim_category}'"
                )

            req_doc = document_requirements[self.claim_category]

            if not req_doc:     
                    raise FileNotFoundError(
                        f"{document_dir} not found. The Require Documents are {req_doc}"
                    )

        documents = []

        for file in document_dir.glob("*.json"):

            with open(
                file,
                "r",
                encoding="utf-8"
            ) as f:

                payload = json.load(f)

                documents.append(
                    payload.get("data", payload)
                )

        self.documents = documents

    # ---------------------------------------------------
    # Document Validation
    # ---------------------------------------------------
    def _validate_documents(self):

        agent = DocumentValidationAgent()

        self.document_result, self.document_output = (
            agent.validate(
                documents=self.documents,
                member_name=self.member.name,
                policy=self.policy,
                claim_category=self.claim_category
            )
        )

        self.response["document"] = (
            self.document_output.model_dump(mode='json')
            if self.document_output else {}
        )

        self.response["document_result"] = (
            self.document_result.model_dump(mode='json')
            if self.document_result else {}
        )

    # ---------------------------------------------------
    # Coverage Validation
    # ---------------------------------------------------
    def _validate_coverage(self):

        agent = CoverageAgent()

        self.coverage_result, self.coverage_output = (
            agent.validate(
                member=self.member,
                policy=self.policy,
                documents=self.documents,
                document_data=self.document_output,
                claim_category=self.claim_category
            )
        )

        self.response["coverage"] = (
            self.coverage_output.model_dump(mode='json')
            if self.coverage_output else {}
        )

        self.response["coverage_result"] = (
            self.coverage_result.model_dump(mode='json')
            if self.coverage_result else {}
        )

    # ---------------------------------------------------
    # Financial Validation
    # ---------------------------------------------------
    def _validate_finance(self):

        agent = FinancialAgent()

        self.finance_result, self.finance_output = (
            agent.validate(
                member=self.member,
                policy=self.policy,
                documents=self.documents
            )
        )

        self.response["finance"] = (
            self.finance_output.model_dump(mode='json')
            if self.finance_output else {}
        )

        self.response["finance_result"] = (
            self.finance_result.model_dump(mode='json')
            if self.finance_result else {}
        )

    # ---------------------------------------------------
    # Fraud Validation
    # ---------------------------------------------------
    def _validate_fraud(self):

        agent = FraudAgent()

        self.fraud_result, self.fraud_output = (
            agent.validate(
                member=self.member,
                policy=self.policy,
                documents=self.documents,
                financial_output=self.finance_output
            )
        )

        self.response["fraud"] = (
            self.fraud_output.model_dump(mode='json')
            if self.fraud_output else {}
        )

        self.response["fraud_result"] = (
            self.fraud_result.model_dump(mode='json')
            if self.fraud_result else {}
        )

    # ---------------------------------------------------
    # Decision Engine
    # ---------------------------------------------------
    def _make_decision(self):

        agent = DecisionAgent()

        self.decision_result, self.decision_output = (
            agent.validate(
                coverage_result=self.coverage_result,
                coverage_output=self.coverage_output,
                financial_result=self.finance_result,
                financial_output=self.finance_output,
                fraud_result=self.fraud_result,
                fraud_output=self.fraud_output
            )
        )

        self.response["decision"] = (
            self.decision_output.model_dump(mode='json')
            if self.decision_output else {}
        )

        self.response["decision_result"] = (
            self.decision_result.model_dump(mode='json')
            if self.decision_result else {}
        )

    # ---------------------------------------------------
    # Save Output
    # ---------------------------------------------------
    def _save_output(self):

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        output_file = (
            self.output_dir /
            f"claim_{self.member_id}.json"
        )

        with open(output_file, "w") as f:
            json.dump(
                self.response,
                f,
                indent=4,
                default=str
            )

        print(f"Output saved to {output_file}")

    def _generate_message(self):
        messages = [
    {
        "role": "system",
        "content": """
You are a Health Insurance Claim Assistant.

Your job is to explain claim processing errors in simple language.

Rules:

- Explain the actual error.
- Do not give generic IT troubleshooting steps.
- Do not mention system configuration.
- Do not mention administrators.
- Do not invent causes.
- Use only the information provided.
- Keep the response under 50 words.
- If the error is caused by missing or invalid claim data, explain exactly which data is missing or invalid.
- If the error is unclear, state that the claim could not be processed and mention the reported error.
"""
    },
    {
        "role": "user",
        "content": f"""
Claim Processing Error:

{self.response["error"]}
"""
    }
]
        response = self._llm.call_llm(
            messages)
        
        print(response)
        self.response["error_message"] = response
        return response
        
if __name__ == "__main__":
    pipeline = ClaimProcessingPipeline(
        member_id="EMP001",
        claim_category="CONSULTATION",
        output_dir="./output"
    )
    result = pipeline.run()
    print(result)

# if __name__ == "__main__":
    
#     response = {}
#     member_id = "EMP001"
#     claim_category = "CONSULTATION"
    
#     claim = ClaimInput(
#         member_id=member_id,
#         claim_category=claim_category
#     )

#     member_agent = MemberValidationAgent()

#     result, member = member_agent.validate(member_id)
    
#     response["member"] = member.model_dump() if member else {}
#     response["member_result"] = result.model_dump() if result else {}

#     if member:
#         print(f"MEMBER {'-'*60}")
#         print(member.model_dump())
    
#     print(f"RESULT {'-'*60}")
#     print(result.model_dump())
    
#     # Policy Validation
#     policy_agent = PolicyAgent()
#     result, policy = policy_agent.validate(policy_id=member.policy_id)
    
#     if policy:
#         print(f"POLICY {'-'*60}")
#         print(policy.model_dump())
    
#     print(f"POLICY RESULT{'-'*60}")
#     print(result.model_dump())
    
#     response["policy"] = policy.model_dump() if policy else {}
#     response["policy_result"] = result.model_dump() if result else {}
    
#     # Docuemnt
#     document_agent = DocumentValidationAgent()
    
#     document_dir = Path(
#         f"./documents/{member_id}"
#     )
#     documents = []

#     if not document_dir.exists():
#         raise FileNotFoundError(
#             f"{document_dir} not found"
#         )

#     for file in document_dir.glob("*.json"):

#         with open(
#             file,
#             "r",
#             encoding="utf-8"
#         ) as f:

#             payload = json.load(f)

#             if "data" in payload:
#                 documents.append(
#                     payload["data"]
#                 )
#             else:
#                 documents.append(
#                     payload
#                 )
    
#     claim.document_agent_response = documents

#     if member :
#         result, document = document_agent.validate(documents=documents, member_name=member.name,policy=policy,claim_category=claim_category)

#     if document:
#         print(f"Document {'-'*60}")
#         print(document.model_dump())
        
#     print(f"Document Result {'-'*60}")
#     print(result.model_dump())
    
#     response["document"] = document.model_dump() if document else {}
#     response["document_result"] = result.model_dump() if result else {}
    
#     coverage_agent = CoverageAgent()
#     coverage_result, coverage_output = (
#     coverage_agent.validate(
#         member=member,
#         policy=policy,
#         documents=documents,
#         document_data=document,
#         claim_category=claim_category
#         )
#     )
#     if coverage_output:
#         print(f"Coverage {'-'*60}")
#         print(coverage_output.model_dump())

#     print(f"Coverage Result {'-'*60}")
#     print(coverage_result.model_dump())  
          
#     response["coverage"] = coverage_output.model_dump() if coverage_output else {}
#     response["coverage_result"] = coverage_result.model_dump() if coverage_result else {}
    
#     finance_agent  = FinancialAgent()
#     finance_result, finance_output = finance_agent.validate(
#         member=member,
#         policy=policy,
#         documents=documents
#     )
#     if finance_output:
#         print(f"Finance {'-'*60}")
#         print(finance_output.model_dump())

#     print(f"Finance Result {'-'*60}")
#     print(finance_result.model_dump())
    
#     response["finance"] = finance_output.model_dump() if finance_output else {}
#     response["finance_result"] = finance_result.model_dump() if finance_result else {}
    
#     fraud_agent = FraudAgent()

#     fraud_result, fraud_output = (
#         fraud_agent.validate(
#             member=member,
#             policy=policy,
#             documents=documents,
#             financial_output=finance_output
#         )
#     )
#     if fraud_output:
#         print(f"Fraud{'-'*60}")
#         print(fraud_output.model_dump())

#     print(f"Fraud Result{'-'*60}")
#     print(fraud_result.model_dump())
    
#     response["fraud"] = fraud_output.model_dump() if fraud_output else {}
#     response["fraud_result"] = fraud_result.model_dump() if fraud_result else {}
    
#     decision_agent = DecisionAgent()
#     decision_result, decision_output = (
#         decision_agent.validate(
#             coverage_result= coverage_result,
#             coverage_output= coverage_output,
#             financial_result= finance_result,
#             financial_output= finance_output,
#             fraud_result= fraud_result,
#             fraud_output= fraud_output
#         )
#     )
    
#     if decision_output:
#         print(f"Decision {'-'*60}")
#         print(decision_output.model_dump())

#     print(f"Decision Result {'-'*60}")
#     print(decision_result.model_dump())
    
#     response["decision"] = decision_output.model_dump() if decision_output else {}
#     response["decision_result"] = decision_result.model_dump() if decision_result else {}
#     path = r"C:\Users\hs250\vscode\BTP\Plum Assignment - 12-04-2026\backend\output"
#     with open(f"{path}/claim_{member_id}.json", "w") as f:
#         json.dump(
#             response,
#             f,
#             indent=4,
#             default=str
#         )