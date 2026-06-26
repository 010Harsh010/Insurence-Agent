# Insurance Claims Backend — Architecture Documentation

> System Design Diagrams for the OPD Claims Adjudication Platform

---

## 1. Claim Processing Pipeline

The end-to-end claim processing flow from user chat request through the agent orchestrator, the seven-step adjudication pipeline, database persistence, and response delivery.

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant Flask as Flask API
    participant Orch as AgentOrchestrator
    participant Greet as GreetingAgent
    participant Guard as GuardrailAgent
    participant Router as RouterAgent
    participant Pipeline as ClaimProcessingPipeline
    participant MemberV as MemberValidationAgent
    participant PolicyV as PolicyAgent
    participant DocV as DocumentValidationAgent
    participant CovV as CoverageAgent
    participant FinV as FinancialAgent
    participant FraudV as FraudAgent
    participant DecV as DecisionAgent
    participant LLM as Groq LLM
    participant DB as PostgreSQL
    participant Prom as Prometheus

    Client->>Flask: GET /chat?query=...&member_id=...&claim_category=...
    activate Flask
    Note over Flask,Prom: PHASE 1 — Request Instrumentation
    Flask->>Prom: ACTIVE_REQUESTS.inc()
    Flask->>Flask: record request.start_time

    Flask->>Orch: orchestrator.run(query, member_id, category)
    activate Orch

    Note over Orch,LLM: PHASE 2 — Pre-routing Classification
    Orch->>Greet: greeting_agent.run(query)
    activate Greet
    Greet->>LLM: Classify: is_greeting? (temp=0.0, json_object)
    LLM-->>Greet: {"is_greeting": false}
    Greet-->>Orch: GreetingResponse(is_greeting=false)
    deactivate Greet

    Orch->>Guard: guardrail_agent.run(query)
    activate Guard
    Guard->>LLM: Security check: allowed? (temp=0.0, json_object)
    LLM-->>Guard: {"allowed": true}
    Guard-->>Orch: GuardrailResponse(allowed=true)
    deactivate Guard

    Orch->>Router: router_agent.route(query)
    activate Router
    Router->>LLM: Classify intent (json_object)
    LLM-->>Router: {"route": "CLAIM_PROCESSING"}
    Router-->>Orch: RouterResponse(route=CLAIM_PROCESSING)
    deactivate Router

    Note over Orch,DB: PHASE 3 — Pipeline Initialization
    Orch->>Pipeline: ClaimProcessingPipeline(member_id, category, output_dir)
    activate Pipeline
    Pipeline->>Pipeline: Initialize state, TraceRepository, DecisionRepository

    Note over Pipeline,DB: PHASE 4 — Member Validation
    Pipeline->>Prom: AGENT_DURATION.labels("member_validation").time()
    Pipeline->>MemberV: validate(member_id)
    activate MemberV
    MemberV->>DB: SELECT member_id, name, policy_id FROM members WHERE member_id = ?
    DB-->>MemberV: member row
    MemberV->>MemberV: Check: member exists, has policy, has name
    MemberV-->>Pipeline: (StepResult.PASSED, MemberData)
    deactivate MemberV
    Pipeline->>Pipeline: _fail_early(member_result) → false, continue

    Note over Pipeline,DB: PHASE 5 — Policy Validation
    Pipeline->>Prom: AGENT_DURATION.labels("policy_validation").time()
    Pipeline->>PolicyV: validate(policy_id)
    activate PolicyV
    PolicyV->>DB: SELECT * FROM policies WHERE policy_id = ?
    DB-->>PolicyV: policy row (JSONB coverage, exclusions, thresholds...)
    PolicyV->>PolicyV: Check: exists, start/end dates, renewal_status
    PolicyV-->>Pipeline: (StepResult.PASSED, PolicyData)
    deactivate PolicyV
    Pipeline->>Pipeline: _fail_early(policy_result) → false, continue

    Note over Pipeline,DB: PHASE 6 — Document Load & Validation
    Pipeline->>Prom: AGENT_DURATION.labels("document_validation").time()
    Pipeline->>Pipeline: _load_documents() — glob ./documents/{member_id}/*.json
    Pipeline->>DocV: validate(documents, member_name, policy, category)
    activate DocV
    DocV->>DocV: Check required docs from policy.document_requirements
    DocV->>DocV: Check confidence thresholds (< 0.40 = unreadable)
    DocV->>DocV: SequenceMatcher: patient name cross-check (>= 0.80)
    DocV->>DocV: Check patient vs member name match
    DocV->>DocV: Detect duplicate doc types
    DocV-->>Pipeline: (StepResult.PASSED, DocumentValidationOutput)
    deactivate DocV
    Pipeline->>Pipeline: _fail_early(document_result, document_output) → false

    Note over Pipeline,DB: PHASE 7 — Claim Record Creation
    Pipeline->>Prom: AGENT_DURATION.labels("claim_creation").time()
    Pipeline->>DB: INSERT INTO claims (...) VALUES (...) RETURNING claim_id
    DB-->>Pipeline: claim_id (UUID)
    Pipeline->>DB: INSERT INTO claim_trace_steps (claim_id, step_name, ...)
    Pipeline->>DB: INSERT INTO claim_documents (claim_id, doc_type, extracted_data, ...)

    Note over Pipeline,DB: PHASE 8 — Coverage Validation
    Pipeline->>Prom: AGENT_DURATION.labels("coverage_validation").time()
    Pipeline->>CovV: validate(member, policy, documents, doc_data, category)
    activate CovV
    CovV->>CovV: Extract treatment_date, diagnosis, claimed_amount from docs
    CovV->>CovV: Check relationship coverage
    CovV->>CovV: Check initial waiting period
    CovV->>CovV: Check treatment_date >= join_date
    CovV->>DB: SELECT opd_categories FROM policies (for DIAGNOSTIC pre-auth)
    CovV->>CovV: Check pre-authorization (high-value tests > threshold)
    CovV->>CovV: Check specific condition waiting periods
    CovV->>CovV: Check exclusions (keyword match on diagnosis/tests)
    CovV->>CovV: Check minimum claim amount
    CovV->>CovV: Check submission window deadline
    CovV-->>Pipeline: (StepResult, CoverageValidationOutput)
    deactivate CovV
    Pipeline->>DB: INSERT INTO claim_trace_steps

    Note over Pipeline,DB: PHASE 9 — Financial Validation
    Pipeline->>Prom: AGENT_DURATION.labels("financial_validation").time()
    Pipeline->>FinV: validate(member, policy, documents, doc_data, category)
    activate FinV
    FinV->>FinV: Extract claimed_amount from docs (max of total_amount or sum line_items)
    FinV->>DB: SELECT hospital_name FROM hospitals WHERE is_network_hospital = true
    FinV->>FinV: Apply network discount if hospital matches
    FinV->>DB: SELECT opd_categories FROM policies (category rules)
    FinV->>FinV: Apply co-pay deduction
    FinV->>FinV: Subtract excluded line items (excluded_procedures match)
    FinV->>FinV: Cap at per_claim_limit
    FinV->>FinV: Cap at category sub_limit
    FinV->>DB: SELECT SUM(approved_amount) FROM claim_decisions (annual usage)
    FinV->>FinV: Cap at remaining annual OPD limit
    FinV->>DB: SELECT SUM(approved_amount) for all family members (floater usage)
    FinV->>FinV: Cap at remaining family floater limit
    FinV-->>Pipeline: (StepResult, FinancialValidationOutput)
    deactivate FinV
    Pipeline->>DB: INSERT INTO claim_trace_steps

    Note over Pipeline,DB: PHASE 10 — Fraud Detection
    Pipeline->>Prom: AGENT_DURATION.labels("fraud_validation").time()
    Pipeline->>FraudV: validate(member, policy, documents, financial_output)
    activate FraudV
    FraudV->>DB: SELECT COUNT(*) FROM claims WHERE member_id = ? AND last 30 days
    FraudV->>FraudV: monthly_claims >= limit? → fraud_score += 0.30
    FraudV->>DB: SELECT COUNT(*) FROM claims WHERE treatment_date = ?
    FraudV->>FraudV: same_day_claims >= limit? → fraud_score += 0.25, manual_review
    FraudV->>FraudV: claimed_amount > high_value_threshold? → fraud_score += 0.20
    FraudV->>FraudV: amount > auto_manual_review_above? → manual_review
    FraudV->>FraudV: fraud_score >= threshold? → manual_review
    FraudV-->>Pipeline: (StepResult.PASSED, FraudValidationOutput)
    deactivate FraudV
    Pipeline->>DB: INSERT INTO claim_trace_steps

    Note over Pipeline,LLM: PHASE 11 — Decision Engine
    Pipeline->>Prom: AGENT_DURATION.labels("decision_engine").time()
    Pipeline->>DecV: validate(coverage, financial, fraud results + outputs)
    activate DecV
    DecV->>DecV: Determine: REJECTED / MANUAL_REVIEW / PARTIAL / APPROVED
    DecV->>LLM: Generate customer explanation (< 80 words, json_object)
    LLM-->>DecV: {"explanation": "..."}
    DecV->>DecV: Build financial_breakdown table
    DecV-->>Pipeline: (StepResult, DecisionOutput)
    deactivate DecV
    Pipeline->>DB: INSERT INTO claim_decisions (decision, amount, explanation, trace)
    Pipeline->>DB: INSERT INTO claim_trace_steps

    Note over Pipeline,Prom: PHASE 12 — Persistence & Metrics
    Pipeline->>DB: UPDATE claims SET claim_status = ?, fraud_score = ?
    Pipeline->>Pipeline: Save JSON to ./output/claim_{member_id}.json
    Pipeline->>Prom: CLAIM_PROCESSING_TIME.observe(elapsed)
    Pipeline->>Prom: CLAIMS_PROCESSED.labels(decision).inc()

    Pipeline-->>Orch: response dict
    deactivate Pipeline

    Orch-->>Flask: response
    deactivate Orch

    Note over Flask: PHASE 13 — Response Formatting
    Flask->>Flask: response_cleaner() → {ui: {type: "decision", message: ...}}
    Flask->>Prom: REQUEST_COUNT.labels().inc()
    Flask->>Prom: REQUEST_LATENCY.labels().observe()
    Flask->>Prom: ACTIVE_REQUESTS.dec()
    Flask-->>Client: {status: 200, data: {ui: {...}, data: {...}}}
    deactivate Flask
```

---

## 2. Document Upload Pipeline

The complete flow when a user uploads a medical document (PDF, image) through the `/upload` endpoint — parsing, classification, extraction, quality check, and storage.

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant Flask as Flask API
    participant DocAgent as DocumentAgent
    participant Quality as QualityAgent
    participant Docling as Docling Loader
    participant LLM as Groq LLM
    participant FS as Filesystem
    participant Prom as Prometheus

    Client->>Flask: POST /upload (multipart file + member_id)
    activate Flask

    Note over Flask: PHASE 1 — Input Validation
    Flask->>Flask: Validate member_id is present
    Flask->>Flask: Validate file is present and filename is not empty

    alt Missing member_id
        Flask-->>Client: 400 {"error": "member_id is required"}
    end

    alt No file selected
        Flask-->>Client: 400 {"error": "No file selected"}
    end

    Flask->>Prom: record start time

    Note over Flask,FS: PHASE 2 — File Persistence
    Flask->>FS: os.makedirs("documents/{member_id}", exist_ok=True)
    Flask->>FS: file.save("documents/{member_id}/{filename}")

    Flask->>DocAgent: process_document(filepath)
    activate DocAgent

    Note over DocAgent,Quality: PHASE 3 — Quality Assessment (Images Only)
    DocAgent->>DocAgent: Check file extension

    alt File is NOT .pdf (image file)
        DocAgent->>Quality: QualityAgent().check(filepath)
        activate Quality
        Quality->>Quality: cv2.imread(path)
        Quality->>Quality: Convert to grayscale

        Note over Quality: Scoring Algorithm
        Quality->>Quality: _blur_score: Laplacian variance → 10-100
        Quality->>Quality: _contrast_score: std deviation → 10-100
        Quality->>Quality: _brightness_score: mean intensity → 20-100
        Quality->>Quality: _resolution_score: pixel count → 10-100
        Quality->>Quality: Weighted: blur×0.40 + contrast×0.20 + brightness×0.10 + resolution×0.30

        Quality-->>DocAgent: QualityResult(score, quality, blur, contrast, brightness, resolution)
        deactivate Quality

        alt quality == "POOR" OR score < 70
            DocAgent-->>Flask: ValueError("Document quality is Poor")
            Flask->>Prom: DOCUMENT_UPLOAD_FAILED.inc()
            Flask-->>Client: 500 {"error": "Document quality is Poor..."}
        end
    end

    Note over DocAgent,LLM: PHASE 4 — Document Parsing
    DocAgent->>Docling: DoclingLoader(file_path, export_type=MARKDOWN)
    activate Docling
    Docling->>Docling: Parse PDF/image → structured content
    Docling-->>DocAgent: markdown text
    deactivate Docling

    Note over DocAgent,LLM: PHASE 5 — Document Classification
    DocAgent->>LLM: Classify document type (PRESCRIPTION / HOSPITAL_BILL / PHARMACY_BILL / LAB_REPORT / DIAGNOSTIC_REPORT / DISCHARGE_SUMMARY / DENTAL_REPORT / UNKNOWN)
    activate LLM
    LLM-->>DocAgent: {"document_type": "...", "confidence": 0.95, "reasoning": "..."}
    deactivate LLM
    DocAgent->>DocAgent: DocumentClassification.model_validate(response)
    DocAgent->>Prom: DOCUMENTS_PROCESSED.labels(doc_type).inc()

    Note over DocAgent,LLM: PHASE 6 — Structured Field Extraction
    DocAgent->>LLM: Extract fields: patient_name, doctor_name, diagnosis, hospital, date, total_amount, medicines, line_items, tests_ordered
    activate LLM
    LLM-->>DocAgent: ExtractedDocument JSON
    deactivate LLM
    DocAgent->>DocAgent: ExtractedDocument.model_validate(response)

    Note over DocAgent: PHASE 7 — Field Validation
    DocAgent->>DocAgent: Lookup REQUIRED_FIELDS for document_type
    DocAgent->>DocAgent: Check each required field is non-null and non-empty

    alt Missing required fields
        DocAgent-->>Flask: ValueError("Required Fields Missing: [...]")
        Flask->>Prom: DOCUMENT_UPLOAD_FAILED.inc()
        Flask-->>Client: 500 {"error": "Required Fields Missing: [...]"}
    end

    DocAgent-->>Flask: {classification, document, markdown, Quality?}
    deactivate DocAgent

    Note over Flask,FS: PHASE 8 — Result Persistence
    Flask->>FS: Write {filename}.json (structured extraction result)
    Flask->>FS: Write {filename}.md (raw markdown)
    Flask->>Prom: SUCCESS_DOCUMENT_UPLOADED.inc()
    Flask->>Prom: DOCUMENT_PROCESS_LATENCY.observe(elapsed)

    Flask-->>Client: 200 {filename, path, markdown_path, message}
    deactivate Flask
```

---

## 3. Document Extraction Pipeline

Detailed internal flow of the `DocumentAgent.process_document()` method — from raw file to structured, validated medical document data.

```mermaid
sequenceDiagram
    autonumber
    participant Caller
    participant DocAgent as DocumentAgent
    participant QA as QualityAgent
    participant CV as OpenCV
    participant DL as Docling Loader
    participant LLM as Groq LLM
    participant Val as Field Validator

    Caller->>DocAgent: process_document(filepath)
    activate DocAgent

    Note over DocAgent,CV: STAGE 1 — Image Quality Gate
    DocAgent->>DocAgent: suffix = Path(path).suffix.lower()

    alt suffix != ".pdf"
        DocAgent->>QA: check(image_path)
        activate QA

        QA->>CV: cv2.imread(image_path)
        CV-->>QA: numpy array (BGR)
        QA->>CV: cv2.cvtColor(image, COLOR_BGR2GRAY)
        CV-->>QA: grayscale array

        par Compute All Scores
            QA->>QA: _blur_score(gray) — Laplacian variance thresholds
            QA->>QA: _contrast_score(gray) — std deviation thresholds
            QA->>QA: _brightness_score(gray) — mean intensity range
            QA->>QA: _resolution_score(w, h) — megapixel thresholds
        end

        QA->>QA: final = blur*0.4 + contrast*0.2 + brightness*0.1 + resolution*0.3
        QA->>QA: Classify: >= 75 → GOOD, >= 50 → OK, else → POOR

        QA-->>DocAgent: QualityResult
        deactivate QA

        alt score < 70 OR quality == "POOR"
            DocAgent-->>Caller: raise ValueError("Document quality is Poor")
        end
    end

    Note over DocAgent,DL: STAGE 2 — Document to Markdown
    DocAgent->>DL: DoclingLoader(file_path=absolute_path, export_type=MARKDOWN)
    activate DL
    DL->>DL: Internal OCR + layout analysis
    DL-->>DocAgent: List[Document] with page_content
    deactivate DL
    DocAgent->>DocAgent: Join all page_content with double newlines

    Note over DocAgent,LLM: STAGE 3 — Classification
    DocAgent->>DocAgent: Build classification prompt with markdown content
    DocAgent->>LLM: "Classify this medical document" → 8 possible types
    activate LLM
    LLM-->>DocAgent: raw text response
    deactivate LLM
    DocAgent->>DocAgent: parse_llm_response() — strip ```json``` if present
    DocAgent->>DocAgent: DocumentClassification.model_validate()

    Note over DocAgent,LLM: STAGE 4 — Field Extraction
    DocAgent->>DocAgent: Build extraction prompt with doc_type + EXTRACTION_RULES
    Note right of DocAgent: Rules: no hallucination, ISO dates, float amounts, separate medicines/tests
    DocAgent->>LLM: "Extract fields from this {document_type}"
    activate LLM
    LLM-->>DocAgent: raw text response
    deactivate LLM
    DocAgent->>DocAgent: parse_llm_response()
    DocAgent->>DocAgent: ExtractedDocument.model_validate()

    Note over DocAgent,Val: STAGE 5 — Required Field Validation
    DocAgent->>Val: validate_document(extracted)
    activate Val
    Val->>Val: Lookup REQUIRED_FIELDS[document_type]
    Note right of Val: HOSPITAL_BILL → [hospital_name, date]
    Note right of Val: PRESCRIPTION → [patient_name, diagnosis]
    Note right of Val: LAB_REPORT → [patient_name, hospital, tests, date]
    Val->>Val: Check each field: not None, not empty string, not empty list
    Val-->>DocAgent: ValidationResult(is_valid, missing_fields)
    deactivate Val

    alt not is_valid
        DocAgent-->>Caller: raise ValueError("Required Fields Missing: [...]")
    end

    Note over DocAgent: STAGE 6 — Package Result
    DocAgent->>DocAgent: Build result dict with classification, document, markdown
    alt quality_result exists
        DocAgent->>DocAgent: Attach Quality scores to result
    end

    DocAgent-->>Caller: {classification, document, markdown, Quality?}
    deactivate DocAgent
```

---

## 4. Question Answering Pipeline

The text-to-SQL flow for natural-language questions about policies, claims, and members — from user query through schema awareness, SQL generation, validation, execution, and result formatting.

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant Flask as Flask API
    participant Orch as AgentOrchestrator
    participant Greet as GreetingAgent
    participant Guard as GuardrailAgent
    participant Router as RouterAgent
    participant SQL as PostgreSQLQueryAgent
    participant LLM as Groq LLM
    participant DB as PostgreSQL
    participant Prom as Prometheus

    Client->>Flask: GET /chat?query="What are my recent claims?"&member_id=EMP001
    activate Flask
    Flask->>Prom: ACTIVE_REQUESTS.inc()
    Flask->>Orch: orchestrator.run(query, member_id, "")
    activate Orch

    Note over Orch,LLM: PHASE 1 — Intent Classification
    Orch->>Greet: run(query)
    Greet->>LLM: is_greeting? (temp=0.0)
    LLM-->>Greet: {"is_greeting": false}
    Greet-->>Orch: not a greeting

    Orch->>Guard: run(query)
    Guard->>LLM: allowed? (temp=0.0)
    LLM-->>Guard: {"allowed": true}
    Guard-->>Orch: allowed

    Orch->>Router: route(query)
    Router->>LLM: classify intent
    LLM-->>Router: {"route": "QUESTION_ANSWERING"}
    Router-->>Orch: RouteType.QUESTION_ANSWERING

    Note over Orch,DB: PHASE 2 — Schema Introspection (on init)
    Note right of SQL: Already loaded during __init__
    Orch->>SQL: run(query)
    activate SQL

    Note over SQL,DB: PHASE 3 — Schema Design Construction
    SQL->>SQL: _create_schema_design()
    SQL->>SQL: Build text repr of all tables, columns, types, PKs, FKs
    SQL->>SQL: Append column descriptions from schema_metadata
    SQL->>SQL: Append relationship map

    Note over SQL,LLM: PHASE 4 — SQL Generation
    SQL->>LLM: "You are an expert PostgreSQL Text-to-SQL agent" + full schema + user query
    activate LLM
    Note right of LLM: Rules: valid PostgreSQL, only schema tables/columns, proper joins, no markdown
    LLM-->>SQL: Generated SQL string
    deactivate LLM

    Note over SQL: PHASE 5 — SQL Validation
    SQL->>SQL: _validate_sql(sql_query)
    SQL->>SQL: Strip ```sql``` markdown if present
    SQL->>SQL: Verify query starts with SELECT (only reads allowed)

    alt Query is not SELECT
        SQL-->>Orch: raise ValueError("Only SELECT queries are allowed")
        Orch-->>Flask: {status: 500, message: "..."}
        Flask-->>Client: 500 error
    end

    Note over SQL,DB: PHASE 6 — Query Execution
    SQL->>DB: psycopg2.connect()
    activate DB
    SQL->>DB: cursor.execute(validated_sql)
    DB-->>SQL: result rows + column descriptions
    deactivate DB
    SQL->>SQL: Build pandas DataFrame from results
    SQL->>SQL: Convert to list of dicts (orient="records")

    SQL-->>Orch: {query, sql, row_count, data: [...]}
    deactivate SQL

    Note over Orch,Flask: PHASE 7 — Response Assembly
    Orch-->>Flask: Response["Answer"] = {query, sql, row_count, data}
    deactivate Orch

    Flask->>Flask: response_cleaner() → {ui: {type: "answer", message: data}}
    Flask->>Prom: REQUEST_COUNT, REQUEST_LATENCY, ACTIVE_REQUESTS
    Flask-->>Client: {status: 200, data: {ui: {type: "answer", message: [...]}, data: ...}}
    deactivate Flask
```

---

## 5. Decision Making Pipeline

The internal decision engine that aggregates coverage, financial, and fraud validation results into a final claim adjudication decision with an LLM-generated explanation.

```mermaid
sequenceDiagram
    autonumber
    participant Pipeline as ClaimProcessingPipeline
    participant DecAgent as DecisionAgent
    participant LLM as Groq LLM
    participant DecRepo as DecisionRepository
    participant ClaimRepo as ClaimRepository
    participant DB as PostgreSQL
    participant Prom as Prometheus

    Note over Pipeline: Inputs already computed by prior agents
    Pipeline->>Prom: AGENT_DURATION.labels("decision_engine").time()

    Pipeline->>DecAgent: validate(coverage_result, coverage_output, financial_result, financial_output, fraud_result, fraud_output)
    activate DecAgent

    Note over DecAgent: PHASE 1 — Decision Tree Evaluation

    alt coverage_result.passed == false
        DecAgent->>DecAgent: decision = REJECTED
        Note right of DecAgent: Coverage failures: exclusions, waiting periods, pre-auth missing
    else financial_result.passed == false
        DecAgent->>DecAgent: decision = REJECTED
        Note right of DecAgent: Financial failure: no remaining coverage (approved = 0)
    else fraud_output.manual_review_required == true
        DecAgent->>DecAgent: decision = MANUAL_REVIEW
        Note right of DecAgent: Fraud signals: same-day claims, high-value, score threshold
    else approved_amount < claimed_amount
        DecAgent->>DecAgent: decision = PARTIALLY_APPROVED
        Note right of DecAgent: Partial: limits, co-pay, sub-limits reduced the amount
    else All checks passed
        DecAgent->>DecAgent: decision = APPROVED
        Note right of DecAgent: Full amount approved
    end

    Note over DecAgent,LLM: PHASE 2 — Explanation Generation
    DecAgent->>LLM: Generate customer-facing explanation (json_object)
    activate LLM
    Note right of LLM: Input: decision, claimed/approved amounts, coverage issues, fraud warnings, finance breakdown
    Note right of LLM: Rules: < 80 words, no internal systems, customer-friendly
    LLM-->>DecAgent: {"explanation": "Your claim for Rs 5000 has been partially approved..."}
    deactivate LLM

    alt LLM fails
        DecAgent->>DecAgent: Use fallback: "Decision processed successfully."
    end

    Note over DecAgent: PHASE 3 — Financial Breakdown Assembly
    DecAgent->>DecAgent: Build breakdown: Network Discount, Copay, Sub-limit, Per-claim, Annual, Family
    DecAgent->>DecAgent: Append excluded line items from reduct_items

    DecAgent->>DecAgent: Create DecisionOutput(decision, amounts, fraud_score, explanation, breakdown)

    DecAgent-->>Pipeline: (StepResult.PASSED, DecisionOutput)
    deactivate DecAgent

    Note over Pipeline,DB: PHASE 4 — Decision Persistence
    Pipeline->>DecRepo: save_decision(claim_id, decision_output, trace)
    activate DecRepo
    DecRepo->>DB: INSERT INTO claim_decisions (claim_id, decision, approved_amount, confidence_score, rejection_reason, explanation, trace)
    DB-->>DecRepo: committed
    deactivate DecRepo

    Pipeline->>DB: INSERT INTO claim_trace_steps (claim_id, "Decision", status, confidence, output_data)

    Note over Pipeline,DB: PHASE 5 — Claim Record Update
    Pipeline->>ClaimRepo: update_claim(claim_id, decision_output)
    activate ClaimRepo
    ClaimRepo->>DB: UPDATE claims SET claim_status = ?, claimed_amount = ?, fraud_score = ? WHERE claim_id = ?
    DB-->>ClaimRepo: updated
    deactivate ClaimRepo

    Pipeline->>Pipeline: _save_output() → write JSON to ./output/claim_{member_id}.json

    Note over Pipeline,Prom: PHASE 6 — Metrics
    Pipeline->>Prom: CLAIMS_PROCESSED.labels(decision).inc()
    Pipeline->>Prom: CLAIM_PROCESSING_TIME.observe(total_elapsed)
```

---

## 6. Database Interaction Flow

Complete view of all database operations across the system — schema initialization, policy ingestion, claim lifecycle, and query support.

```mermaid
sequenceDiagram
    autonumber
    participant App as Flask App Startup
    participant DBMgr as Database Manager
    participant Loader as PolicyLoader
    participant Pipeline as ClaimProcessingPipeline
    participant MemberV as MemberValidationAgent
    participant PolicyV as PolicyAgent
    participant ClaimRepo as ClaimRepository
    participant FinV as FinancialAgent
    participant FraudV as FraudAgent
    participant TraceRepo as TraceRepository
    participant DecRepo as DecisionRepository
    participant SQLAgent as Text-to-SQL Agent
    participant DB as PostgreSQL

    Note over App,DB: PHASE 1 — Application Startup
    App->>DBMgr: Database().initialize_schema()
    activate DBMgr
    DBMgr->>DB: Execute db/schema.sql (CREATE TABLE IF NOT EXISTS ... × 9 tables)
    DB-->>DBMgr: schema created
    DBMgr->>DB: Load db/metadata.json → INSERT INTO schema_metadata (upsert)
    DB-->>DBMgr: metadata loaded
    deactivate DBMgr

    Note over Loader,DB: PHASE 2 — Policy Data Ingestion (via /addPolicy)
    Loader->>DB: INSERT INTO policies (policy_id, ..., coverage JSONB, exclusions JSONB, ...)
    Note right of DB: ON CONFLICT (policy_id) DO UPDATE
    Loader->>DB: INSERT INTO members (member_id, policy_id, name, ...) × N members
    Note right of DB: ON CONFLICT (member_id) DO UPDATE
    Loader->>DB: INSERT INTO network_hospitals (hospital_name, policy_id) × N
    Loader->>DB: INSERT INTO hospitals (hospital_name, is_network_hospital=TRUE) × N
    DB-->>Loader: committed

    Note over Pipeline,DB: PHASE 3 — Claim Processing Reads
    MemberV->>DB: SELECT member_id, name, policy_id, relationship, join_date FROM members
    DB-->>MemberV: member row or NULL

    PolicyV->>DB: SELECT * FROM policies WHERE policy_id = ?
    DB-->>PolicyV: policy row with all JSONB fields

    Note over Pipeline,DB: PHASE 4 — Claim Record Creation
    ClaimRepo->>DB: INSERT INTO claims (member_id, policy_id, claim_category, treatment_date, claimed_amount, claim_status='PROCESSING') RETURNING claim_id
    DB-->>ClaimRepo: claim_id UUID

    ClaimRepo->>DB: INSERT INTO claim_documents (claim_id, document_type, file_name, extraction_status, quality_score, extracted_data) × N docs
    DB-->>ClaimRepo: document_id UUIDs

    Note over Pipeline,DB: PHASE 5 — Financial Lookups
    FinV->>DB: SELECT SUM(approved_amount) FROM claim_decisions JOIN claims WHERE member_id = ? AND current year
    DB-->>FinV: annual_used amount

    FinV->>DB: SELECT SUM(approved_amount) FROM claim_decisions JOIN claims JOIN members WHERE primary_member_id = ?
    DB-->>FinV: family_used amount

    FinV->>DB: SELECT hospital_name FROM hospitals WHERE is_network_hospital = true
    DB-->>FinV: network hospital list

    FinV->>DB: SELECT opd_categories FROM policies WHERE policy_id = ?
    DB-->>FinV: category rules JSONB

    Note over Pipeline,DB: PHASE 6 — Fraud Lookups
    FraudV->>DB: SELECT COUNT(*) FROM claims WHERE member_id = ? AND last 30 days
    DB-->>FraudV: monthly_count

    FraudV->>DB: SELECT COUNT(*) FROM claims WHERE member_id = ? AND treatment_date = ?
    DB-->>FraudV: same_day_count

    Note over Pipeline,DB: PHASE 7 — Trace & Decision Writes
    TraceRepo->>DB: INSERT INTO claim_trace_steps (claim_id, step_name, step_status, confidence_score, input_data, output_data, reason) × 5-7 steps
    DB-->>TraceRepo: trace_id UUIDs

    DecRepo->>DB: INSERT INTO claim_decisions (claim_id, decision, approved_amount, confidence_score, rejection_reason, explanation, trace JSONB)
    DB-->>DecRepo: decision_id UUID

    ClaimRepo->>DB: UPDATE claims SET claim_status = ?, claimed_amount = ?, confidence_score = ?, fraud_score = ? WHERE claim_id = ?
    DB-->>ClaimRepo: updated

    Note over SQLAgent,DB: PHASE 8 — Text-to-SQL Reads
    SQLAgent->>DB: SELECT table_name FROM information_schema.tables (schema introspection)
    SQLAgent->>DB: SELECT column_name, data_type FROM information_schema.columns (per table)
    SQLAgent->>DB: SELECT constraint info for PKs and FKs
    SQLAgent->>DB: SELECT table_name, column_name, description FROM schema_metadata
    DB-->>SQLAgent: full schema representation

    SQLAgent->>DB: Execute generated SELECT query
    DB-->>SQLAgent: result rows
```

---

## 7. Authentication Flow

The admin authentication middleware protecting sensitive endpoints — policy management, claim updates, and database resets.

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant Flask as Flask API
    participant Auth as admin_auth Middleware
    participant Env as Environment
    participant Handler as Route Handler
    participant DB as PostgreSQL

    Note over Client,DB: SCENARIO 1 — Missing Password Header
    Client->>Flask: POST /addPolicy (no X-Admin-Password header)
    activate Flask
    Flask->>Auth: @admin_auth decorator intercepts
    activate Auth
    Auth->>Auth: password = request.headers.get("X-Admin-Password")
    Auth->>Auth: password is None

    Auth-->>Flask: 400 {"success": false, "message": "Password is required"}
    deactivate Auth
    Flask-->>Client: 400 Bad Request
    deactivate Flask

    Note over Client,DB: SCENARIO 2 — Wrong Password
    Client->>Flask: POST /addPolicy (X-Admin-Password: wrong_password)
    activate Flask
    Flask->>Auth: @admin_auth decorator intercepts
    activate Auth
    Auth->>Auth: password = "wrong_password"
    Auth->>Env: os.getenv("ADMIN_PASSWORD")
    Env-->>Auth: "mysecretpassword"
    Auth->>Auth: "wrong_password" != "mysecretpassword"

    Auth-->>Flask: 401 {"success": false, "message": "Unauthorized"}
    deactivate Auth
    Flask-->>Client: 401 Unauthorized
    deactivate Flask

    Note over Client,DB: SCENARIO 3 — Successful Authentication
    Client->>Flask: POST /addPolicy (X-Admin-Password: mysecretpassword)
    activate Flask
    Flask->>Auth: @admin_auth decorator intercepts
    activate Auth
    Auth->>Auth: password = "mysecretpassword"
    Auth->>Env: os.getenv("ADMIN_PASSWORD")
    Env-->>Auth: "mysecretpassword"
    Auth->>Auth: password matches ✓

    Auth->>Handler: Execute addPolicy()
    deactivate Auth
    activate Handler
    Handler->>Handler: Parse policy JSON from body or file upload
    Handler->>DB: PolicyLoader.load_policy_file(policy)
    DB-->>Handler: success
    Handler-->>Flask: 200 {"success": true, "message": "Policy added successfully"}
    deactivate Handler
    Flask-->>Client: 200 OK
    deactivate Flask

    Note over Client,DB: Protected Endpoints
    Note right of Client: POST /addPolicy — Add/update policy data
    Note right of Client: POST /updateClaim — Manual approve/reject decisions
    Note right of Client: POST /resetDB — Drop and recreate all tables
```

---

## 8. Error Handling Flow

How errors propagate through the system — from individual agent failures to pipeline-level exceptions, LLM-generated user messages, metric recording, and graceful degradation.

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant Flask as Flask API
    participant Pipeline as ClaimProcessingPipeline
    participant Agent as Any Validation Agent
    participant FailEarly as _fail_early()
    participant MsgGen as _generate_message()
    participant LLM as Groq LLM
    participant DB as PostgreSQL
    participant Prom as Prometheus

    Note over Client,Prom: PATH A — Agent Validation Failure (Expected)
    Client->>Flask: GET /chat (claim request)
    Flask->>Pipeline: run()
    activate Pipeline

    Pipeline->>Agent: validate(...)
    activate Agent
    Agent->>DB: query member/policy/claims
    DB-->>Agent: data (or empty)
    Agent->>Agent: Validation check fails
    Agent-->>Pipeline: (StepResult(status=FAILED, fatal=true, reason="Policy expired"), output)
    deactivate Agent

    Pipeline->>FailEarly: _fail_early(step_result, output_model)
    activate FailEarly
    FailEarly->>FailEarly: step_result.passed == false → collect issues
    FailEarly->>FailEarly: Gather from: step_result.reason
    FailEarly->>FailEarly: Gather from: output.issues (if exists)
    FailEarly->>FailEarly: Gather from: output.missing_document_types (if exists)
    FailEarly->>FailEarly: Gather from: output.rejection_reasons (if exists)
    FailEarly->>FailEarly: Store: response["error_step"], response["error_issues"]

    FailEarly->>MsgGen: _generate_message()
    activate MsgGen
    MsgGen->>LLM: "Explain this error to the customer in simple language"
    activate LLM
    Note right of LLM: System: Health Insurance Claim Assistant
    Note right of LLM: Rules: explain ALL issues, no IT jargon, < 80 words
    LLM-->>MsgGen: "Your policy has expired. Please contact your HR department..."
    deactivate LLM
    MsgGen->>MsgGen: response["error_message"] = LLM output
    MsgGen-->>FailEarly: message set
    deactivate MsgGen

    FailEarly-->>Pipeline: return true (abort pipeline)
    deactivate FailEarly

    Pipeline-->>Flask: partial response with error_message
    deactivate Pipeline

    Flask->>Flask: response_cleaner() → {ui: {type: "error", message: "..."}}
    Flask-->>Client: {status: 200, data: {ui: {type: "error", message: "Your policy has expired..."}}}

    Note over Client,Prom: PATH B — Unexpected Exception
    Client->>Flask: GET /chat (claim request)
    Flask->>Pipeline: run()
    activate Pipeline

    Pipeline->>Agent: validate(...)
    activate Agent
    Agent->>DB: query
    DB-->>Agent: connection error / timeout
    Agent-->>Pipeline: raise RuntimeError("Database query failed: ...")
    deactivate Agent

    Note over Pipeline,Prom: Exception caught by try/except in run()
    Pipeline->>Pipeline: response["error"] = str(exception)
    Pipeline->>Pipeline: response["error_issues"] = [str(exception)]
    Pipeline->>Prom: CLAIM_PIPELINE_ERROR.inc()

    Pipeline->>MsgGen: _generate_message()
    activate MsgGen
    MsgGen->>LLM: Explain error to customer
    LLM-->>MsgGen: "We encountered an issue processing your claim..."
    MsgGen-->>Pipeline: error_message set
    deactivate MsgGen

    Note over Pipeline,Prom: Finally block always executes
    Pipeline->>Prom: CLAIM_PROCESSING_TIME.observe(elapsed)

    alt response has decision
        Pipeline->>Prom: CLAIMS_PROCESSED.labels(decision).inc()
    end

    Pipeline-->>Flask: response with error
    deactivate Pipeline
    Flask-->>Client: {status: 200, data: {ui: {type: "error", message: "..."}}}

    Note over Client,Prom: PATH C — LLM Failure (Graceful Degradation)
    Note over LLM: LLM API is down or returns invalid JSON

    Pipeline->>Agent: validate(...)
    Agent->>LLM: call_llm_json(messages)
    activate LLM
    LLM-->>Agent: Exception or empty response
    deactivate LLM

    alt call_llm_json fails
        Note right of Agent: Returns fallback dict {} — agent continues with defaults
    end

    alt call_llm fails
        Note right of Agent: Returns None — caller handles gracefully
    end

    alt GuardrailAgent LLM fails
        Note right of Agent: Defaults to GuardrailResponse(allowed=false) — fail-closed
    end

    alt GreetingAgent LLM fails
        Note right of Agent: Defaults to GreetingResponse(is_greeting=false) — continues pipeline
    end

    Note over Client,Prom: PATH D — Flask-Level Exception
    Client->>Flask: GET /chat
    activate Flask

    alt Orchestrator throws
        Flask->>Flask: except Exception as e
        Flask-->>Client: {status: 500, message: "An error occurred: {error}"}
    end

    Flask->>Prom: REQUEST_COUNT.labels(method, path, status).inc()
    Flask->>Prom: REQUEST_LATENCY.labels(method, path).observe(elapsed)
    Flask->>Prom: ACTIVE_REQUESTS.dec()
    deactivate Flask
```

---

## Index of Database Tables Referenced

| Table | Primary Operations | Referenced By |
|---|---|---|
| `policies` | SELECT, INSERT/UPSERT | PolicyAgent, CoverageAgent, FinancialAgent, PolicyLoader |
| `members` | SELECT, INSERT/UPSERT | MemberValidationAgent, FinancialAgent, PolicyLoader |
| `hospitals` | SELECT, INSERT/UPSERT | FinancialAgent, PolicyLoader |
| `network_hospitals` | SELECT, INSERT | FinancialAgent, PolicyLoader |
| `claims` | INSERT, UPDATE, SELECT | ClaimRepository, FraudAgent, FinancialAgent |
| `claim_documents` | INSERT | ClaimRepository |
| `claim_decisions` | INSERT, UPDATE, SELECT | DecisionRepository, FinancialAgent, DataIngestion |
| `claim_trace_steps` | INSERT | TraceRepository |
| `schema_metadata` | SELECT, INSERT | DatabaseManager, Text-to-SQL Agent |

---

## Prometheus Metrics Map

| Metric | Type | Emitted By | Labels |
|---|---|---|---|
| `http_requests_total` | Counter | Flask after_request | method, endpoint, status |
| `http_request_duration_seconds` | Histogram | Flask after_request | method, endpoint |
| `active_requests` | Gauge | Flask before/after_request | — |
| `claims_processed_total` | Counter | Pipeline finally block | decision |
| `claim_processing_seconds` | Histogram | Pipeline finally block | — |
| `claim_pipeline_error_total` | Counter | Pipeline except block | — |
| `agent_duration_seconds` | Histogram | Pipeline per-agent wrapper | agent |
| `documents_processed_total` | Counter | DocumentAgent._classify | type |
| `document_process_duration_seconds` | Histogram | Flask /upload | — |
| `document_uploaded_total` | Counter | Flask /upload success | — |
| `document_upload_failed_total` | Counter | Flask /upload error | — |
| `llm_calls_total` | Counter | LLMClient.call_llm/call_llm_json | — |
| `llm_duration_seconds` | Histogram | LLMClient.call_llm/call_llm_json | — |
