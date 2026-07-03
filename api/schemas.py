from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    query: str = Field(min_length=5, max_length=2000)
    providers: list[str] = Field(default_factory=list)
    max_leads: int = Field(default=20, ge=1, le=200)
    crawler: str = "requests"
    no_crawl: bool = False
    no_llm_scoring: bool = False
    webhook_url: str | None = None


class RunResponse(BaseModel):
    session_id: str
    status: str
    leads_url: str
    status_url: str


class RunStatus(BaseModel):
    session_id: str
    status: str
    total_leads: int
    hot_count: int
    warm_count: int
    cold_count: int


class LeadSummary(BaseModel):
    domain: str
    company_name: str
    lead_tier: str
    icp_relevance_score: float
    tech_stack: list[str]
    company_summary: str
    outreach_subject: str
    source_url: str


class LeadsResponse(BaseModel):
    session_id: str
    total: int
    leads: list[LeadSummary]


class HealthResponse(BaseModel):
    status: str
    db: str
    redis: str
    version: str = "0.3.0"
