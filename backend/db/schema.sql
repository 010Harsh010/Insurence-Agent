CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- POLICIES
-- =====================================================

CREATE TABLE IF NOT EXISTS policies (
    policy_id VARCHAR(50) PRIMARY KEY,

    policy_name VARCHAR(255) NOT NULL,
    insurer_name VARCHAR(255) NOT NULL,

    company_name VARCHAR(255) NOT NULL,
    employee_count INT,

    policy_start_date DATE,
    policy_end_date DATE,

    renewal_status VARCHAR(50),

    coverage JSONB,
    opd_categories JSONB,
    waiting_periods JSONB,
    exclusions JSONB,
    pre_authorization JSONB,
    submission_rules JSONB,
    document_requirements JSONB,
    fraud_thresholds JSONB,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- MEMBERS
-- =====================================================

CREATE TABLE IF NOT EXISTS members (
    member_id VARCHAR(50) PRIMARY KEY,

    policy_id VARCHAR(50) NOT NULL,

    primary_member_id VARCHAR(50),

    name VARCHAR(255) NOT NULL,

    date_of_birth DATE,
    gender VARCHAR(10),

    relationship VARCHAR(50),

    join_date DATE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_member_policy
        FOREIGN KEY (policy_id)
        REFERENCES policies(policy_id),

    CONSTRAINT fk_primary_member
        FOREIGN KEY (primary_member_id)
        REFERENCES members(member_id)
);

-- =====================================================
-- HOSPITALS
-- =====================================================

CREATE TABLE IF NOT EXISTS hospitals (
    hospital_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    hospital_name VARCHAR(255) UNIQUE NOT NULL,

    is_network_hospital BOOLEAN DEFAULT FALSE,

    address TEXT,
    city VARCHAR(100),
    state VARCHAR(100),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- CLAIMS
-- =====================================================

CREATE TABLE IF NOT EXISTS claims (
    claim_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    member_id VARCHAR(50) NOT NULL,
    policy_id VARCHAR(50) NOT NULL,

    hospital_id UUID,

    claim_category VARCHAR(100),

    treatment_date DATE,
    submission_date DATE,

    claimed_amount NUMERIC(12,2),

    claim_status VARCHAR(50),

    confidence_score NUMERIC(4,2),
    fraud_score NUMERIC(4,2),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_claim_member
        FOREIGN KEY (member_id)
        REFERENCES members(member_id),

    CONSTRAINT fk_claim_policy
        FOREIGN KEY (policy_id)
        REFERENCES policies(policy_id),

    CONSTRAINT fk_claim_hospital
        FOREIGN KEY (hospital_id)
        REFERENCES hospitals(hospital_id)
);

-- =====================================================
-- CLAIM DOCUMENTS
-- =====================================================

CREATE TABLE IF NOT EXISTS claim_documents (
    document_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    claim_id UUID NOT NULL,

    document_type VARCHAR(100),

    file_name VARCHAR(255),
    storage_url TEXT,

    extraction_status VARCHAR(50),

    quality_score NUMERIC(4,2),

    extracted_data JSONB,

    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_document_claim
        FOREIGN KEY (claim_id)
        REFERENCES claims(claim_id)
        ON DELETE CASCADE
);

-- =====================================================
-- CLAIM DECISIONS
-- =====================================================

CREATE TABLE IF NOT EXISTS claim_decisions (
    decision_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    claim_id UUID NOT NULL,

    decision VARCHAR(50),

    approved_amount NUMERIC(12,2),

    confidence_score NUMERIC(4,2),

    rejection_reason TEXT,

    explanation TEXT,

    trace JSONB,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_decision_claim
        FOREIGN KEY (claim_id)
        REFERENCES claims(claim_id)
        ON DELETE CASCADE
);

-- =====================================================
-- NETWORK HOSPITALS
-- =====================================================

CREATE TABLE IF NOT EXISTS network_hospitals (
    hospital_name VARCHAR(255) PRIMARY KEY,

    policy_id VARCHAR(50) NOT NULL,

    CONSTRAINT fk_network_policy
        FOREIGN KEY (policy_id)
        REFERENCES policies(policy_id)
        ON DELETE CASCADE
);

-- =====================================================
-- CLAIM TRACE STEPS
-- =====================================================

CREATE TABLE IF NOT EXISTS claim_trace_steps (
    trace_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    claim_id UUID NOT NULL,

    step_name VARCHAR(255) NOT NULL,

    step_status VARCHAR(50) NOT NULL,

    confidence_score NUMERIC(4,2),

    input_data JSONB,
    output_data JSONB,

    reason TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_trace_claim
        FOREIGN KEY (claim_id)
        REFERENCES claims(claim_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS schema_metadata (
    id SERIAL PRIMARY KEY,

    table_name VARCHAR(255) NOT NULL,
    column_name VARCHAR(255),

    description TEXT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_schema_metadata
    UNIQUE(table_name, column_name)
);

CREATE INDEX IF NOT EXISTS idx_schema_metadata_table
ON schema_metadata(table_name);

CREATE INDEX IF NOT EXISTS idx_schema_metadata_column
ON schema_metadata(column_name);
-- =====================================================
-- INDEXES
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_members_policy
ON members(policy_id);

CREATE INDEX IF NOT EXISTS idx_members_primary
ON members(primary_member_id);

CREATE INDEX IF NOT EXISTS idx_claims_member
ON claims(member_id);

CREATE INDEX IF NOT EXISTS idx_claims_policy
ON claims(policy_id);

CREATE INDEX IF NOT EXISTS idx_claims_hospital
ON claims(hospital_id);

CREATE INDEX IF NOT EXISTS idx_claims_status
ON claims(claim_status);

CREATE INDEX IF NOT EXISTS idx_documents_claim
ON claim_documents(claim_id);

CREATE INDEX IF NOT EXISTS idx_decisions_claim
ON claim_decisions(claim_id);

CREATE INDEX IF NOT EXISTS idx_trace_claim
ON claim_trace_steps(claim_id);

CREATE INDEX IF NOT EXISTS idx_network_policy
ON network_hospitals(policy_id);