CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    query        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'created',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    total_leads  INTEGER DEFAULT 0,
    hot_count    INTEGER DEFAULT 0,
    warm_count   INTEGER DEFAULT 0,
    cold_count   INTEGER DEFAULT 0,
    pipeline_ms  FLOAT DEFAULT 0,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    id                    SERIAL PRIMARY KEY,
    session_id            TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    domain                TEXT NOT NULL,
    company_name          TEXT,
    lead_tier             TEXT,
    icp_relevance_score   FLOAT,
    tech_stack            JSONB DEFAULT '[]',
    hiring_signals        JSONB DEFAULT '[]',
    outsourcing_signals   JSONB DEFAULT '[]',
    business_events       JSONB DEFAULT '[]',
    company_summary       TEXT,
    why_this_lead         TEXT,
    contact_emails        JSONB DEFAULT '[]',
    linkedin_url          TEXT,
    decision_makers       JSONB DEFAULT '[]',
    outreach_suggestions  JSONB DEFAULT '[]',
    source_url            TEXT,
    evidence              JSONB DEFAULT '[]',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(session_id, domain)
);

CREATE INDEX IF NOT EXISTS idx_leads_session_id ON leads(session_id);
CREATE INDEX IF NOT EXISTS idx_leads_tier ON leads(lead_tier);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(icp_relevance_score DESC);