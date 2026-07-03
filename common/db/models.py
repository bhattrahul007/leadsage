from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_icp: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default="created")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_leads: Mapped[int] = mapped_column(Integer, default=0)
    hot_count: Mapped[int] = mapped_column(Integer, default=0)
    warm_count: Mapped[int] = mapped_column(Integer, default=0)
    cold_count: Mapped[int] = mapped_column(Integer, default=0)
    pipeline_ms: Mapped[float] = mapped_column(Float, default=0.0)
    provider_count: Mapped[int] = mapped_column(Integer, default=0)
    crawled_count: Mapped[int] = mapped_column(Integer, default=0)
    search_results_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)

    conversations: Mapped[list[ConversationMessageModel]] = relationship(
        "ConversationMessageModel", back_populates="session", cascade="all, delete-orphan"
    )
    leads: Mapped[list[LeadModel]] = relationship(
        "LeadModel", back_populates="session", cascade="all, delete-orphan"
    )
    search_queries: Mapped[list[SearchQueryModel]] = relationship(
        "SearchQueryModel", back_populates="session", cascade="all, delete-orphan"
    )
    crawl_history: Mapped[list[CrawlHistoryModel]] = relationship(
        "CrawlHistoryModel", back_populates="session", cascade="all, delete-orphan"
    )
    agent_runs: Mapped[list[AgentRunModel]] = relationship(
        "AgentRunModel", back_populates="session", cascade="all, delete-orphan"
    )
    pipeline_metrics: Mapped[list[PipelineMetricModel]] = relationship(
        "PipelineMetricModel", back_populates="session", cascade="all, delete-orphan"
    )
    linked_results: Mapped[list[LinkedSourceResultModel]] = relationship(
        "LinkedSourceResultModel", back_populates="session", cascade="all, delete-orphan"
    )


class ConversationMessageModel(Base):
    __tablename__ = "session_conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    agent_name: Mapped[str | None] = mapped_column(String, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    session: Mapped[SessionModel] = relationship("SessionModel", back_populates="conversations")


class SearchQueryModel(Base):
    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sessions.id", ondelete="CASCADE")
    )
    query_string: Mapped[str] = mapped_column(Text, nullable=False)
    signal_type: Mapped[str | None] = mapped_column(String, nullable=True)
    search_type: Mapped[str] = mapped_column(String, default="web")
    provider: Mapped[str] = mapped_column(String, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    session: Mapped[SessionModel] = relationship("SessionModel", back_populates="search_queries")


class CrawlHistoryModel(Base):
    __tablename__ = "crawl_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sessions.id", ondelete="CASCADE")
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(String, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False)
    crawler_type: Mapped[str] = mapped_column(String, default="requests")
    proxy_used: Mapped[bool] = mapped_column(Boolean, default=False)
    proxy_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    session: Mapped[SessionModel] = relationship("SessionModel", back_populates="crawl_history")


class CompanyModel(Base):
    __tablename__ = "companies"

    domain: Mapped[str] = mapped_column(String, primary_key=True)
    company_name: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    founding_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employee_range: Mapped[str | None] = mapped_column(String, nullable=True)
    revenue_range: Mapped[str | None] = mapped_column(String, nullable=True)
    headquarters: Mapped[str | None] = mapped_column(String, nullable=True)
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String, nullable=True)
    twitter_url: Mapped[str | None] = mapped_column(String, nullable=True)
    github_url: Mapped[str | None] = mapped_column(String, nullable=True)
    crunchbase_url: Mapped[str | None] = mapped_column(String, nullable=True)
    angellist_url: Mapped[str | None] = mapped_column(String, nullable=True)
    yc_batch: Mapped[str | None] = mapped_column(String, nullable=True)
    is_yc_company: Mapped[bool] = mapped_column(Boolean, default=False)
    funding_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    total_funding_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_funding_at: Mapped[Any] = mapped_column(Date, nullable=True)
    tech_stack: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    industry_tags: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    sic_codes: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    business_model: Mapped[str | None] = mapped_column(String, nullable=True)
    ownership: Mapped[str] = mapped_column(String, default="private")
    maturity_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    source_urls: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now()
    )

    leads: Mapped[list[LeadModel]] = relationship("LeadModel", back_populates="company")
    decision_makers: Mapped[list[DecisionMakerModel]] = relationship(
        "DecisionMakerModel", back_populates="company", cascade="all, delete-orphan"
    )


class LeadModel(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sessions.id", ondelete="CASCADE")
    )
    domain: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("companies.domain", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    company_name: Mapped[str | None] = mapped_column(String, nullable=True)
    lead_tier: Mapped[str | None] = mapped_column(String, nullable=True)
    icp_relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    tech_score: Mapped[float] = mapped_column(Float, default=0.0)
    hiring_score: Mapped[float] = mapped_column(Float, default=0.0)
    profile_score: Mapped[float] = mapped_column(Float, default=0.0)
    tech_stack: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    hiring_signals: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    outsourcing_signals: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    business_events: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    industry_signals: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    company_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_this_lead: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    llm_scored: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_model_used: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("session_id", "domain", name="uq_lead_session_domain"),)

    session: Mapped[SessionModel | None] = relationship("SessionModel", back_populates="leads")
    company: Mapped[CompanyModel | None] = relationship(
        "CompanyModel", back_populates="leads", foreign_keys=[domain]
    )
    outreach_suggestions: Mapped[list[OutreachSuggestionModel]] = relationship(
        "OutreachSuggestionModel", back_populates="lead", cascade="all, delete-orphan"
    )


class DecisionMakerModel(Base):
    __tablename__ = "decision_makers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    domain: Mapped[str | None] = mapped_column(
        String, ForeignKey("companies.domain", ondelete="CASCADE")
    )
    session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    department: Mapped[str | None] = mapped_column(String, nullable=True)
    seniority: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String, nullable=True)
    twitter_url: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[str] = mapped_column(String, default="llm_extraction")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("domain", "email", name="uq_dm_domain_email"),
        UniqueConstraint("domain", "linkedin_url", name="uq_dm_domain_linkedin"),
    )

    company: Mapped[CompanyModel | None] = relationship(
        "CompanyModel", back_populates="decision_makers"
    )


class OutreachSuggestionModel(Base):
    __tablename__ = "outreach_suggestions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lead_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="CASCADE")
    )
    session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sessions.id", ondelete="CASCADE")
    )
    domain: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str] = mapped_column(String, default="linkedin")
    subject_line: Mapped[str | None] = mapped_column(Text, nullable=True)
    opening_hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_talking_points: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    personalization: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    lead: Mapped[LeadModel | None] = relationship(
        "LeadModel", back_populates="outreach_suggestions"
    )


class AgentRunModel(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sessions.id", ondelete="CASCADE")
    )
    agent_name: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    session: Mapped[SessionModel | None] = relationship("SessionModel", back_populates="agent_runs")


class PipelineMetricModel(Base):
    __tablename__ = "pipeline_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sessions.id", ondelete="CASCADE")
    )
    stage: Mapped[str] = mapped_column(String, nullable=False)
    items_in: Mapped[int] = mapped_column(Integer, default=0)
    items_out: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    cache_hits: Mapped[int] = mapped_column(Integer, default=0)
    cache_misses: Mapped[int] = mapped_column(Integer, default=0)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    session: Mapped[SessionModel | None] = relationship(
        "SessionModel", back_populates="pipeline_metrics"
    )


class LinkedSourceResultModel(Base):
    __tablename__ = "linked_source_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sessions.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    domain: Mapped[str | None] = mapped_column(String, nullable=True)
    company_name: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    founded_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    funding_info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    session: Mapped[SessionModel | None] = relationship(
        "SessionModel", back_populates="linked_results"
    )
