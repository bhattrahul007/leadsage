from typing import Literal

from pydantic import BaseModel, Field


class KeywordIntent(BaseModel):
    required: list[str] = Field(default_factory=list, description="Keywords that must be present")
    optional: list[str] = Field(default_factory=list, description="Keywords that are nice to have")
    excluded: list[str] = Field(
        default_factory=list, description="Keywords that disqualify a result"
    )


class RangeFilter(BaseModel):
    min: int | None = None
    max: int | None = None


class LocationFilter(BaseModel):
    countries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    cities: list[str] = Field(default_factory=list)


CompanySize = Literal["startup", "mid_market", "enterprise"]

Ownership = Literal["private", "public", "government"]

CompanyMaturityStage = Literal["early_stage", "growth_stage", "mature", "fortune_500"]


class CompanyIntent(BaseModel):
    industries: list[str] = Field(
        default_factory=list, description="Target industries e.g. fintech, healthcare"
    )
    size: list[CompanySize] = Field(default_factory=list, description="Company size categories")
    ownership: list[Ownership] = Field(default_factory=list, description="Ownership structure")
    employee_range: RangeFilter | None = None
    revenue_range: RangeFilter | None = None
    maturity_stage: list[CompanyMaturityStage] = Field(default_factory=list)


OutsourcingLikelihood = Literal["low", "medium", "high", "none"]

EngagementModel = Literal[
    "staff_augmentation",
    "dedicated_developers",
    "managed_services",
    "offshore_development",
    "nearshore_development",
    "consulting",
    "project_based",
]

OutsourcingSignal = Literal[
    "uses_external_vendors",
    "has_outsourcing_history",
    "works_with_consultancies",
    "contract_roles_open",
    "temporary_engineers_needed",
    "rapid_team_scaling",
    "cost_reduction",
    "digital_transformation",
    "new_project_launch",
    "engineering_capacity_gap",
    "distributed_engineering_team",
    "offshore_team_present",
    "vendor_manager_present",
]


class OutsourcingIntent(BaseModel):
    likelihood: OutsourcingLikelihood | None = Field(
        None, description="How likely is this company to outsource"
    )
    engagement_models: list[EngagementModel] = Field(default_factory=list)
    outsourcing_signals: list[OutsourcingSignal] = Field(default_factory=list)
    known_vendors: list[str] = Field(
        default_factory=list, description="Known vendors or agencies already used"
    )
    preferred_locations: LocationFilter | None = None
    contract_keywords: KeywordIntent | None = None


class TechnologyIntent(BaseModel):
    required: list[str] = Field(
        default_factory=list, description="Technologies that must be in use"
    )
    preferred: list[str] = Field(default_factory=list, description="Technologies that are a plus")
    excluded: list[str] = Field(
        default_factory=list, description="Technologies that disqualify a result"
    )
    migrating_from: list[str] = Field(default_factory=list)
    migrating_to: list[str] = Field(default_factory=list)


ProjectType = Literal[
    "new_product_development",
    "legacy_modernization",
    "cloud_migration",
    "mobile_app_development",
    "web_application",
    "ai_ml",
    "data_engineering",
    "devops",
    "cybersecurity",
    "erp_implementation",
    "automation",
    "staff_augmentation",
    "erp_crm",
    "security",
    "unknown",
]

ProjectComplexity = Literal["small", "medium", "large", "enterprise"]


class ProjectIntent(BaseModel):
    project_types: list[ProjectType] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    complexity: ProjectComplexity | None = None


OutsourcingBusinessEvent = Literal[
    "funding",
    "merger",
    "expansion",
    "new_office",
    "new_product",
    "digital_transformation",
]

OutsourcingPainPoint = Literal[
    "engineering_shortage",
    "slow_delivery",
    "high_engineering_cost",
    "scaling_team",
    "legacy_system",
]


class OutsourcingSignals(BaseModel):
    hiring_signals: list[str] = Field(
        default_factory=list,
        description="Job postings or role signals indicating outsourcing need",
    )
    technology_changes: list[str] = Field(default_factory=list)
    business_events: list[OutsourcingBusinessEvent] = Field(default_factory=list)
    pain_points: list[OutsourcingPainPoint] = Field(default_factory=list)


Department = Literal["engineering", "technology", "procurement", "digital", "innovation"]


class BuyerPersona(BaseModel):
    titles: list[str] = Field(
        default_factory=list,
        description="Job titles of decision makers e.g. CTO, VP Engineering",
    )
    departments: list[Department] = Field(default_factory=list)
    personas: list[str] = Field(
        default_factory=list,
        description="Persona archetypes e.g. technical buyer, economic buyer",
    )


ServiceModelType = Literal[
    "software_development",
    "staff_augmentation",
    "dedicated_team",
    "cloud_services",
    "devops",
    "data_engineering",
    "ai_ml",
    "qa_testing",
    "maintenance_support",
    "consulting",
]


class ServiceModel(BaseModel):
    models: list[ServiceModelType] = Field(
        default_factory=list,
        description="Engagement or service models relevant to this query",
    )


DiscoveryFocusType = Literal[
    "find_companies",
    "find_projects",
    "find_outsourcing_need",
    "find_decision_makers",
    "find_technology_change",
    "find_hiring_growth",
]


class DiscoveryIntent(BaseModel):
    focus: DiscoveryFocusType = Field(description="Primary intent of the discovery query")
    result_limit: int = Field(default=50, gt=0, le=500)


class IcpDiscoveryQuery(BaseModel):
    original_query: str = Field(description="The raw input query from the user")
    target_company: CompanyIntent
    locations: LocationFilter
    opportunities: ProjectIntent
    signals: OutsourcingSignals
    technologies: TechnologyIntent
    buyer_persona: BuyerPersona
    discovery: DiscoveryIntent
    engagement: ServiceModel
    outsource: OutsourcingIntent
    keywords: KeywordIntent
    missing_information: list[str] = Field(
        default_factory=list,
        description="Fields the LLM could not infer from the query",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score for the parsed query")
