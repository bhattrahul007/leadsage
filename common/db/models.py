from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def _now():
    return datetime.now(UTC)


class SessionModel(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    query = Column(Text, nullable=False)
    parsed_icp = Column(JSONB, default=dict)
    status = Column(String, nullable=False, default="created")
    created_at = Column(DateTime(timezone=True), default=_now, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now()
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    total_leads = Column(Integer, default=0)
    hot_count = Column(Integer, default=0)
    warm_count = Column(Integer, default=0)
    cold_count = Column(Integer, default=0)
    pipeline_ms = Column(Float, default=0.0)
    provider_count = Column(Integer, default=0)
    crawled_count = Column(Integer, default=0)
    search_results_count = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSONB, default=dict)

    conversations = relationship(
        "ConversationMessageModel", back_populates="session", cascade="all, delete-orphan"
    )
    leads = relationship("LeadModel", back_populates="session", cascade="all, delete-orphan")
    search_queries = relationship(
        "SearchQueryModel", back_populates="session", cascade="all, delete-orphan"
    )
    crawl_history = relationship(
        "CrawlHistoryModel", back_populates="session", cascade="all, delete-orphan"
    )
    agent_runs = relationship(
        "AgentRunModel", back_populates="session", cascade="all, delete-orphan"
    )
    pipeline_metrics = relationship(
        "PipelineMetricModel", back_populates="session", cascade="all, delete-orphan"
    )
    linked_results = relationship(
        "LinkedSourceResultModel", back_populates="session", cascade="all, delete-orphan"
    )


class ConversationMessageModel(Base):
    __tablename__ = "session_conversations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    tokens = Column(Integer, default=0)
    agent_name = Column(String, nullable=True)
    model_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, server_default=func.now())

    session = relationship("SessionModel", back_populates="conversations")


class SearchQueryModel(Base):
    __tablename__ = "search_queries"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"))
    query_string = Column(Text, nullable=False)
    signal_type = Column(String, nullable=True)
    search_type = Column(String, default="web")
    provider = Column(String, nullable=False)
    result_count = Column(Integer, default=0)
    latency_ms = Column(Float, default=0.0)
    success = Column(Boolean, default=True)
    error = Column(Text, nullable=True)
    executed_at = Column(DateTime(timezone=True), default=_now, server_default=func.now())

    session = relationship("SessionModel", back_populates="search_queries")


class CrawlHistoryModel(Base):
    __tablename__ = "crawl_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"))
    url = Column(Text, nullable=False)
    domain = Column(String, nullable=True)
    success = Column(Boolean, default=True)
    status_code = Column(Integer, nullable=True)
    latency_ms = Column(Float, default=0.0)
    word_count = Column(Integer, default=0)
    from_cache = Column(Boolean, default=False)
    crawler_type = Column(String, default="requests")
    proxy_used = Column(Boolean, default=False)
    proxy_provider = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    crawled_at = Column(DateTime(timezone=True), default=_now, server_default=func.now())

    session = relationship("SessionModel", back_populates="crawl_history")


class CompanyModel(Base):
    __tablename__ = "companies"

    domain = Column(String, primary_key=True)
    company_name = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    founding_year = Column(Integer, nullable=True)
    employee_range = Column(String, nullable=True)
    revenue_range = Column(String, nullable=True)
    headquarters = Column(String, nullable=True)
    website = Column(String, nullable=True)
    linkedin_url = Column(String, nullable=True)
    twitter_url = Column(String, nullable=True)
    github_url = Column(String, nullable=True)
    crunchbase_url = Column(String, nullable=True)
    angellist_url = Column(String, nullable=True)
    yc_batch = Column(String, nullable=True)
    is_yc_company = Column(Boolean, default=False)
    funding_stage = Column(String, nullable=True)
    total_funding_usd = Column(BigInteger, nullable=True)
    last_funding_at = Column(Date, nullable=True)
    tech_stack = Column(JSONB, default=list)
    industry_tags = Column(JSONB, default=list)
    sic_codes = Column(JSONB, default=list)
    business_model = Column(String, nullable=True)
    ownership = Column(String, default="private")
    maturity_stage = Column(String, nullable=True)
    source_urls = Column(JSONB, default=list)
    discovered_at = Column(DateTime(timezone=True), default=_now, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now()
    )

    leads = relationship("LeadModel", back_populates="company")
    decision_makers = relationship(
        "DecisionMakerModel", back_populates="company", cascade="all, delete-orphan"
    )


class LeadModel(Base):
    __tablename__ = "leads"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"))
    domain = Column(
        String, ForeignKey("companies.domain", ondelete="SET NULL", use_alter=True), nullable=True
    )
    company_name = Column(String, nullable=True)
    lead_tier = Column(String, nullable=True)
    icp_relevance_score = Column(Float, nullable=True)
    tech_score = Column(Float, default=0.0)
    hiring_score = Column(Float, default=0.0)
    profile_score = Column(Float, default=0.0)
    tech_stack = Column(JSONB, default=list)
    hiring_signals = Column(JSONB, default=list)
    outsourcing_signals = Column(JSONB, default=list)
    business_events = Column(JSONB, default=list)
    industry_signals = Column(JSONB, default=list)
    company_summary = Column(Text, nullable=True)
    why_this_lead = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    source_provider = Column(String, nullable=True)
    evidence = Column(JSONB, default=list)
    llm_scored = Column(Boolean, default=False)
    llm_model_used = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, server_default=func.now())

    __table_args__ = (UniqueConstraint("session_id", "domain", name="uq_lead_session_domain"),)

    session = relationship("SessionModel", back_populates="leads")
    company = relationship("CompanyModel", back_populates="leads", foreign_keys=[domain])
    outreach_suggestions = relationship(
        "OutreachSuggestionModel", back_populates="lead", cascade="all, delete-orphan"
    )


class DecisionMakerModel(Base):
    __tablename__ = "decision_makers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    domain = Column(String, ForeignKey("companies.domain", ondelete="CASCADE"))
    session_id = Column(String, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    full_name = Column(String, nullable=True)
    title = Column(String, nullable=False)
    department = Column(String, nullable=True)
    seniority = Column(String, nullable=True)
    email = Column(String, nullable=True)
    linkedin_url = Column(String, nullable=True)
    twitter_url = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    confidence = Column(Float, default=0.5)
    source = Column(String, default="llm_extraction")
    verified = Column(Boolean, default=False)
    discovered_at = Column(DateTime(timezone=True), default=_now, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("domain", "email", name="uq_dm_domain_email"),
        UniqueConstraint("domain", "linkedin_url", name="uq_dm_domain_linkedin"),
    )

    company = relationship("CompanyModel", back_populates="decision_makers")


class OutreachSuggestionModel(Base):
    __tablename__ = "outreach_suggestions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    lead_id = Column(BigInteger, ForeignKey("leads.id", ondelete="CASCADE"))
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"))
    domain = Column(String, nullable=False)
    channel = Column(String, default="linkedin")
    subject_line = Column(Text, nullable=True)
    opening_hook = Column(Text, nullable=True)
    key_talking_points = Column(JSONB, default=list)
    personalization = Column(JSONB, default=list)
    created_at = Column(DateTime(timezone=True), default=_now, server_default=func.now())

    lead = relationship("LeadModel", back_populates="outreach_suggestions")


class AgentRunModel(Base):
    __tablename__ = "agent_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_name = Column(String, nullable=False)
    model_name = Column(String, nullable=True)
    provider = Column(String, nullable=True)
    prompt_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    latency_ms = Column(Float, default=0.0)
    success = Column(Boolean, default=True)
    fallback_used = Column(Boolean, default=False)
    error = Column(Text, nullable=True)
    input_summary = Column(Text, nullable=True)
    output_summary = Column(Text, nullable=True)
    executed_at = Column(DateTime(timezone=True), default=_now, server_default=func.now())

    session = relationship("SessionModel", back_populates="agent_runs")


class PipelineMetricModel(Base):
    __tablename__ = "pipeline_metrics"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"))
    stage = Column(String, nullable=False)
    items_in = Column(Integer, default=0)
    items_out = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    latency_ms = Column(Float, default=0.0)
    cache_hits = Column(Integer, default=0)
    cache_misses = Column(Integer, default=0)
    recorded_at = Column(DateTime(timezone=True), default=_now, server_default=func.now())

    session = relationship("SessionModel", back_populates="pipeline_metrics")


class LinkedSourceResultModel(Base):
    __tablename__ = "linked_source_results"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"))
    source = Column(String, nullable=False)
    external_id = Column(String, nullable=True)
    domain = Column(String, nullable=True)
    company_name = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    founded_year = Column(Integer, nullable=True)
    tags = Column(JSONB, default=list)
    location = Column(String, nullable=True)
    funding_info = Column(JSONB, default=dict)
    raw_data = Column(JSONB, default=dict)
    result_url = Column(Text, nullable=True)
    fetched_at = Column(DateTime(timezone=True), default=_now, server_default=func.now())

    session = relationship("SessionModel", back_populates="linked_results")
