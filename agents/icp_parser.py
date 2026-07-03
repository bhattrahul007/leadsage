from __future__ import annotations

import logging
from typing import Any

from agents.base import BaseAgent
from agents.factory import register_agent
from common.schemas.icp_request import CompanySize, IcpDiscoveryQuery

logger = logging.getLogger(__name__)

_PARSER_SYSTEM_PROMPT = """
You are an expert B2B sales intelligence analyst specialising in technology outsourcing.

Your job is to parse a natural language lead generation query into a fully structured
ICP (Ideal Customer Profile) discovery request.

Extract all relevant details across every dimension:
- Company: industries, size, ownership, maturity stage, employee range
- Location: countries, regions, cities
- Technologies: required stack, preferred, excluded, migration direction
- Hiring signals: roles being hired, volume
- Business events: funding, expansion, M&A, digital transformation
- Outsourcing intent: engagement models, pain points, known vendors
- Buyer persona: decision-maker titles, departments
- Project types: what kind of work they need done

Rules:
- Leave lists EMPTY (not null) if information is not present in the query.
- Set `confidence` between 0.0 and 1.0 based on how much detail you could extract.
- `missing_information` should list fields that would make this query more precise.
- `original_query` must be the exact input string unchanged.
""".strip()


@register_agent("icp_parser")
class IcpParserAgent(BaseAgent):
    """
    Converts a raw query string → ``IcpDiscoveryQuery`` via LLM structured output.

    Always returns a valid ``IcpDiscoveryQuery`` — never raises.
    Falls back to keyword-based parsing on LLM failure.

    Example::

        agent = IcpParserAgent(llm, bus=bus)
        icp = agent.parse("Find EU fintech companies using React, targeting CTOs")
    """

    name = "icp_parser"
    required_model_role = "icp_parser"

    def run(self, *args: Any, **kwargs: Any) -> IcpDiscoveryQuery:
        """Alias so the agent works with ``AgentFactory.create().run()``."""
        query: str = args[0] if args else str(kwargs.get("query", ""))
        return self.parse(query)

    def parse(self, query: str) -> IcpDiscoveryQuery:
        """
        Parse ``query`` into a structured ``IcpDiscoveryQuery``.

        Args:
            query: Natural language lead generation intent.

        Returns:
            A populated ``IcpDiscoveryQuery`` (never None).
        """
        prompt = f"{_PARSER_SYSTEM_PROMPT}\n\nUser query:\n{query}"

        try:
            from typing import cast as _cast

            result = _cast(IcpDiscoveryQuery, self.llm.invoke_structured(prompt, IcpDiscoveryQuery))
            logger.info(
                "ICP parsed [model=%s confidence=%.2f]: %s…",
                self.llm.model_name,
                result.confidence,
                query[:60],
            )
            # Publish event
            from common.events.events import IcpParsed

            self._publish(
                IcpParsed(
                    session_id=self.session_id,
                    query=query,
                    confidence=result.confidence,
                    industries=result.target_company.industries[:5],
                    technologies=result.technologies.required[:5],
                )
            )
            return result

        except Exception as exc:
            logger.warning(
                "LLM ICP parse failed (%s: %s) — falling back to keyword parser.",
                type(exc).__name__,
                exc,
            )
            return _keyword_fallback(query)


_LOCATION_KWS: list[str] = [
    "us",
    "usa",
    "united states",
    "uk",
    "united kingdom",
    "india",
    "europe",
    "canada",
    "australia",
    "germany",
    "france",
    "singapore",
    "uae",
    "middle east",
    "latam",
]

_TECH_KWS: list[str] = [
    "kubernetes",
    "k8s",
    "docker",
    "terraform",
    "aws",
    "gcp",
    "azure",
    "react",
    "vue",
    "angular",
    "next.js",
    "nextjs",
    "python",
    "golang",
    "go",
    "rust",
    "java",
    "node.js",
    "nodejs",
    "fastapi",
    "django",
    "flask",
    "rails",
    "spring",
    "postgresql",
    "mysql",
    "mongodb",
    "redis",
    "kafka",
    "elasticsearch",
    "snowflake",
    "databricks",
    "airflow",
    "spark",
    "dbt",
    "pytorch",
    "tensorflow",
    "openai",
    "langchain",
    "llm",
    "typescript",
    "graphql",
    "tailwind",
    "flutter",
    "react native",
]

_TITLE_KWS: list[str] = [
    "cto",
    "vp engineering",
    "vp of engineering",
    "head of engineering",
    "chief technology officer",
    "cpo",
    "coo",
    "ciso",
    "engineering manager",
    "director of engineering",
    "head of product",
    "vp product",
]

_SIZE_KWS: dict[CompanySize, list[str]] = {
    "startup": ["startup", "seed", "early stage", "series a"],
    "mid_market": [
        "mid-market",
        "scale-up",
        "series b",
        "series c",
        "100 employees",
        "500 employees",
        "50-500",
    ],
    "enterprise": [
        "enterprise",
        "fortune 500",
        "large company",
        "10000 employees",
        "publicly traded",
    ],
}

_INDUSTRY_KWS: list[str] = [
    "saas",
    "fintech",
    "healthtech",
    "edtech",
    "proptech",
    "insurtech",
    "martech",
    "ecommerce",
    "logistics",
    "supply chain",
    "hr tech",
    "legaltech",
    "cybersecurity",
    "gaming",
    "media",
    "retail",
    "healthcare",
    "finance",
    "banking",
    "real estate",
    "manufacturing",
]


def _keyword_fallback(query: str) -> IcpDiscoveryQuery:
    """
    Lightweight keyword-based ICP parser — runs when the LLM is unavailable.

    Extracts signals by scanning the query string against curated lookup tables.
    Lower fidelity than LLM parsing but never fails.
    """
    from common.schemas.icp_request import (
        BuyerPersona,
        CompanyIntent,
        DiscoveryIntent,
        KeywordIntent,
        LocationFilter,
        OutsourcingIntent,
        OutsourcingSignals,
        ProjectIntent,
        ServiceModel,
        TechnologyIntent,
    )

    q = query.lower()

    countries = [loc for loc in _LOCATION_KWS if loc in q]
    techs = [t for t in _TECH_KWS if t in q]
    titles = [t for t in _TITLE_KWS if t in q]
    industries = [i for i in _INDUSTRY_KWS if i in q]

    sizes: list[CompanySize] = []
    for size, kws in _SIZE_KWS.items():
        if any(kw in q for kw in kws):
            sizes.append(size)

    # Simple required keywords from meaningful words (exclude stopwords)
    _STOP = {"find", "the", "and", "for", "with", "that", "are", "in", "of", "a", "an"}
    required_kws = [w for w in q.split() if len(w) > 3 and w not in _STOP][:8]

    confidence = min(
        0.3
        + (0.1 if techs else 0)
        + (0.1 if titles else 0)
        + (0.1 if industries else 0)
        + (0.05 if countries else 0),
        0.6,
    )

    return IcpDiscoveryQuery(
        original_query=query,
        target_company=CompanyIntent(
            industries=industries,
            size=sizes,
        ),
        locations=LocationFilter(countries=countries),
        opportunities=ProjectIntent(project_types=[]),
        signals=OutsourcingSignals(),
        technologies=TechnologyIntent(required=techs),
        buyer_persona=BuyerPersona(titles=titles),
        discovery=DiscoveryIntent(focus="find_companies"),
        engagement=ServiceModel(models=[]),
        outsource=OutsourcingIntent(),
        keywords=KeywordIntent(required=required_kws),
        missing_information=[
            "LLM unavailable — keyword fallback used. Results may be less precise."
        ],
        confidence=confidence,
    )
