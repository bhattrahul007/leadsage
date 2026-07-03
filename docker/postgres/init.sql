CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";


CREATE TABLE IF NOT EXISTS sessions (
    id                TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    query             TEXT NOT NULL,
    parsed_icp        JSONB DEFAULT '{}',
    status            TEXT NOT NULL DEFAULT 'created',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at      TIMESTAMPTZ,
    total_leads       INTEGER DEFAULT 0,
    hot_count         INTEGER DEFAULT 0,
    warm_count        INTEGER DEFAULT 0,
    cold_count        INTEGER DEFAULT 0,
    pipeline_ms       FLOAT DEFAULT 0,
    provider_count    INTEGER DEFAULT 0,
    crawled_count     INTEGER DEFAULT 0,
    search_results_count INTEGER DEFAULT 0,
    error             TEXT,
    metadata          JSONB DEFAULT '{}'
);


CREATE TABLE IF NOT EXISTS session_conversations (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,
    tokens      INTEGER DEFAULT 0,
    agent_name  TEXT,
    model_name  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conv_session ON session_conversations(session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS search_queries (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    query_string    TEXT NOT NULL,
    signal_type     TEXT,
    search_type     TEXT DEFAULT 'web',
    provider        TEXT NOT NULL,
    result_count    INTEGER DEFAULT 0,
    latency_ms      FLOAT DEFAULT 0,
    success         BOOLEAN DEFAULT TRUE,
    error           TEXT,
    executed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sq_session ON search_queries(session_id);
CREATE INDEX IF NOT EXISTS idx_sq_provider ON search_queries(provider);
CREATE INDEX IF NOT EXISTS idx_sq_signal ON search_queries(signal_type);

CREATE TABLE IF NOT EXISTS crawl_history (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    url             TEXT NOT NULL,
    domain          TEXT,
    success         BOOLEAN DEFAULT TRUE,
    status_code     INTEGER,
    latency_ms      FLOAT DEFAULT 0,
    word_count      INTEGER DEFAULT 0,
    from_cache      BOOLEAN DEFAULT FALSE,
    crawler_type    TEXT DEFAULT 'requests',
    proxy_used      BOOLEAN DEFAULT FALSE,
    proxy_provider  TEXT,
    error           TEXT,
    crawled_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ch_session ON crawl_history(session_id);
CREATE INDEX IF NOT EXISTS idx_ch_domain ON crawl_history(domain);
CREATE INDEX IF NOT EXISTS idx_ch_success ON crawl_history(success, crawled_at DESC);


CREATE TABLE IF NOT EXISTS companies (
    domain              TEXT PRIMARY KEY,
    company_name        TEXT,
    description         TEXT,
    founding_year       INTEGER,
    employee_range      TEXT,
    revenue_range       TEXT,
    headquarters        TEXT,
    website             TEXT,
    linkedin_url        TEXT,
    twitter_url         TEXT,
    github_url          TEXT,
    crunchbase_url      TEXT,
    angellist_url       TEXT,
    yc_batch            TEXT,
    is_yc_company       BOOLEAN DEFAULT FALSE,
    funding_stage       TEXT,
    total_funding_usd   BIGINT,
    last_funding_at     DATE,
    tech_stack          JSONB DEFAULT '[]',
    industry_tags       JSONB DEFAULT '[]',
    sic_codes           JSONB DEFAULT '[]',
    business_model      TEXT,
    ownership           TEXT DEFAULT 'private',
    maturity_stage      TEXT,
    source_urls         JSONB DEFAULT '[]',
    discovered_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_companies_name ON companies USING gin(to_tsvector('english', coalesce(company_name, '')));
CREATE INDEX IF NOT EXISTS idx_companies_tech ON companies USING gin(tech_stack);
CREATE INDEX IF NOT EXISTS idx_companies_industry ON companies USING gin(industry_tags);


CREATE TABLE IF NOT EXISTS leads (
    id                      BIGSERIAL PRIMARY KEY,
    session_id              TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    domain                  TEXT NOT NULL,
    company_name            TEXT,
    lead_tier               TEXT,
    icp_relevance_score     FLOAT,
    tech_score              FLOAT DEFAULT 0,
    hiring_score            FLOAT DEFAULT 0,
    profile_score           FLOAT DEFAULT 0,
    tech_stack              JSONB DEFAULT '[]',
    hiring_signals          JSONB DEFAULT '[]',
    outsourcing_signals     JSONB DEFAULT '[]',
    business_events         JSONB DEFAULT '[]',
    industry_signals        JSONB DEFAULT '[]',
    company_summary         TEXT,
    why_this_lead           TEXT,
    source_url              TEXT,
    source_provider         TEXT,
    evidence                JSONB DEFAULT '[]',
    llm_scored              BOOLEAN DEFAULT FALSE,
    llm_model_used          TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(session_id, domain),
    FOREIGN KEY (domain) REFERENCES companies(domain) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS idx_leads_session ON leads(session_id);
CREATE INDEX IF NOT EXISTS idx_leads_tier ON leads(lead_tier);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(icp_relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(domain);
CREATE INDEX IF NOT EXISTS idx_leads_provider ON leads(source_provider);

CREATE TABLE IF NOT EXISTS decision_makers (
    id              BIGSERIAL PRIMARY KEY,
    domain          TEXT REFERENCES companies(domain) ON DELETE CASCADE,
    session_id      TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    full_name       TEXT,
    title           TEXT NOT NULL,
    department      TEXT,
    seniority       TEXT,
    email           TEXT,
    linkedin_url    TEXT,
    twitter_url     TEXT,
    phone           TEXT,
    confidence      FLOAT DEFAULT 0.5,
    source          TEXT DEFAULT 'llm_extraction',
    verified        BOOLEAN DEFAULT FALSE,
    discovered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(domain, email),
    UNIQUE(domain, linkedin_url)
);

CREATE INDEX IF NOT EXISTS idx_dm_domain ON decision_makers(domain);
CREATE INDEX IF NOT EXISTS idx_dm_title ON decision_makers USING gin(to_tsvector('english', coalesce(title, '')));
CREATE INDEX IF NOT EXISTS idx_dm_session ON decision_makers(session_id);

CREATE TABLE IF NOT EXISTS outreach_suggestions (
    id                  BIGSERIAL PRIMARY KEY,
    lead_id             BIGINT REFERENCES leads(id) ON DELETE CASCADE,
    session_id          TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    domain              TEXT NOT NULL,
    channel             TEXT DEFAULT 'linkedin',
    subject_line        TEXT,
    opening_hook        TEXT,
    key_talking_points  JSONB DEFAULT '[]',
    personalization     JSONB DEFAULT '[]',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outreach_lead ON outreach_suggestions(lead_id);
CREATE INDEX IF NOT EXISTS idx_outreach_session ON outreach_suggestions(session_id);


CREATE TABLE IF NOT EXISTS agent_runs (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    agent_name      TEXT NOT NULL,
    model_name      TEXT,
    provider        TEXT,
    prompt_tokens   INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    latency_ms      FLOAT DEFAULT 0,
    success         BOOLEAN DEFAULT TRUE,
    fallback_used   BOOLEAN DEFAULT FALSE,
    error           TEXT,
    input_summary   TEXT,
    output_summary  TEXT,
    executed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent ON agent_runs(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_runs_model ON agent_runs(model_name);


CREATE TABLE IF NOT EXISTS pipeline_metrics (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    stage           TEXT NOT NULL,
    items_in        INTEGER DEFAULT 0,
    items_out       INTEGER DEFAULT 0,
    error_count     INTEGER DEFAULT 0,
    latency_ms      FLOAT DEFAULT 0,
    cache_hits      INTEGER DEFAULT 0,
    cache_misses    INTEGER DEFAULT 0,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pm_session ON pipeline_metrics(session_id);
CREATE INDEX IF NOT EXISTS idx_pm_stage ON pipeline_metrics(stage);

CREATE TABLE IF NOT EXISTS linked_source_results (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    source          TEXT NOT NULL,
    external_id     TEXT,
    domain          TEXT,
    company_name    TEXT,
    description     TEXT,
    founded_year    INTEGER,
    tags            JSONB DEFAULT '[]',
    location        TEXT,
    funding_info    JSONB DEFAULT '{}',
    raw_data        JSONB DEFAULT '{}',
    result_url      TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lsr_session ON linked_source_results(session_id);
CREATE INDEX IF NOT EXISTS idx_lsr_source ON linked_source_results(source);
CREATE INDEX IF NOT EXISTS idx_lsr_domain ON linked_source_results(domain);

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sessions_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ──────────────────────────────────────────────────────────────────
-- VIEWS
-- ──────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_session_summary AS
SELECT
    s.id,
    s.query,
    s.status,
    s.created_at,
    s.completed_at,
    s.total_leads,
    s.hot_count,
    s.warm_count,
    s.cold_count,
    s.pipeline_ms,
    COUNT(DISTINCT sq.id)   AS search_queries_issued,
    COUNT(DISTINCT ch.id)   AS urls_crawled,
    COUNT(DISTINCT ar.id)   AS agent_runs,
    COALESCE(SUM(ar.latency_ms), 0) AS total_llm_ms
FROM sessions s
LEFT JOIN search_queries sq ON sq.session_id = s.id
LEFT JOIN crawl_history ch ON ch.session_id = s.id
LEFT JOIN agent_runs ar ON ar.session_id = s.id
GROUP BY s.id;

CREATE OR REPLACE VIEW v_top_leads AS
SELECT
    l.session_id,
    l.domain,
    l.company_name,
    l.lead_tier,
    l.icp_relevance_score,
    c.tech_stack,
    c.linkedin_url,
    c.yc_batch,
    c.funding_stage,
    COUNT(dm.id) AS decision_maker_count
FROM leads l
LEFT JOIN companies c ON c.domain = l.domain
LEFT JOIN decision_makers dm ON dm.domain = l.domain
GROUP BY l.id, l.session_id, l.domain, l.company_name, l.lead_tier,
         l.icp_relevance_score, c.tech_stack, c.linkedin_url,
         c.yc_batch, c.funding_stage
ORDER BY l.icp_relevance_score DESC;