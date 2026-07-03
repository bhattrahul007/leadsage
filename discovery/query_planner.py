from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from common.schemas.icp_request import IcpDiscoveryQuery


SignalType = Literal[
    "company_profile",
    "technology_stack",
    "hiring_signals",
    "outsourcing_signals",
    "business_events",
    "decision_makers",
]

SearchTypeHint = Literal["web", "news"]


@dataclass
class PlannedQuery:
    """
    A single search query derived from the ICP.

    Attributes
    ----------
    query_string:    The literal string to pass to the search provider.
    signal_type:     What ICP signal this query is designed to surface.
    search_type:     "web" or "news".
    priority:        Execution priority (1 = highest). Lower runs first.
    providers:       Provider slugs to use. Empty list = all registered.
    config_overrides: ``SearchConfig`` field overrides for this query only.
                      E.g. ``{"time_range": "qdr:m", "max_results": 5}``.
    """

    query_string: str
    signal_type: SignalType
    search_type: SearchTypeHint = "web"
    priority: int = 5
    providers: list[str] = field(default_factory=list)
    config_overrides: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"<PlannedQuery [{self.signal_type}|p{self.priority}] {self.query_string!r}>"


@dataclass
class QueryPlan:
    """
    The full set of search queries derived from one ``IcpDiscoveryQuery``.

    Attributes
    ----------
    icp:         The source ICP query.
    queries:     All planned queries, unsorted.
    planned_at:  UTC timestamp of when the plan was built.
    """

    icp: IcpDiscoveryQuery
    queries: list[PlannedQuery]
    planned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def by_priority(self) -> list[PlannedQuery]:
        """Return queries sorted by priority ascending (1 first)."""
        return sorted(self.queries, key=lambda q: q.priority)

    def by_signal(self) -> dict[SignalType, list[PlannedQuery]]:
        """Group queries by their signal type."""
        groups: dict[str, list[PlannedQuery]] = {}
        for q in self.queries:
            groups.setdefault(q.signal_type, []).append(q)
        return groups  # type: ignore[return-value]

    def web_queries(self) -> list[PlannedQuery]:
        return [q for q in self.queries if q.search_type == "web"]

    def news_queries(self) -> list[PlannedQuery]:
        return [q for q in self.queries if q.search_type == "news"]

    def __len__(self) -> int:
        return len(self.queries)

    def __repr__(self) -> str:
        by_type = self.by_signal()
        summary = ", ".join(f"{k}:{len(v)}" for k, v in by_type.items())
        return f"<QueryPlan {len(self.queries)} queries [{summary}]>"


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class QueryPlanner:
    """
    Converts an ``IcpDiscoveryQuery`` into a ``QueryPlan``.

    Each ``build_*`` method corresponds to one signal type. They are all
    independent and safe to override in subclasses.

    Example
    -------
    ::

        planner = QueryPlanner(max_queries_per_signal=3)
        plan    = planner.plan(icp_query)
        print(plan)
        for q in plan.by_priority():
            print(q)
    """

    def __init__(self, max_queries_per_signal: int = 5) -> None:
        self.max_queries_per_signal = max_queries_per_signal

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan(self, icp: IcpDiscoveryQuery) -> QueryPlan:
        """Build a complete QueryPlan from an IcpDiscoveryQuery."""
        queries: list[PlannedQuery] = []

        builders = [
            self.build_company_profile_queries,
            self.build_technology_stack_queries,
            self.build_hiring_signal_queries,
            self.build_outsourcing_signal_queries,
            self.build_business_event_queries,
            self.build_decision_maker_queries,
        ]
        for builder in builders:
            queries.extend(builder(icp))

        return QueryPlan(icp=icp, queries=queries)

    # ------------------------------------------------------------------
    # Signal builders
    # ------------------------------------------------------------------

    def build_company_profile_queries(self, icp: IcpDiscoveryQuery) -> list[PlannedQuery]:
        """
        Broad company discovery queries combining industry, size, and location.
        Priority 1 — the core signal.
        """
        queries: list[PlannedQuery] = []

        industries = icp.target_company.industries or ["software"]
        locations = icp.locations.countries or []
        sizes = icp.target_company.size or []

        size_hints = _size_to_terms(sizes)
        loc_hint = " ".join(locations[:2]) if locations else ""

        for industry in industries[: self.max_queries_per_signal]:
            parts = [industry, "company"]
            if size_hints:
                parts.append(size_hints)
            if loc_hint:
                parts.append(loc_hint)
            # Add maturity/ownership hints
            if icp.target_company.maturity_stage:
                parts.append(_first(icp.target_company.maturity_stage, "").replace("_", " "))
            queries.append(
                PlannedQuery(
                    query_string=" ".join(filter(None, parts)),
                    signal_type="company_profile",
                    priority=1,
                )
            )

        return queries[: self.max_queries_per_signal]

    def build_technology_stack_queries(self, icp: IcpDiscoveryQuery) -> list[PlannedQuery]:
        """
        Find companies confirmed to use specific technologies.
        Priority 2 — strong qualification signal.
        """
        queries: list[PlannedQuery] = []
        techs = icp.technologies.required or icp.technologies.preferred
        industries = icp.target_company.industries or []
        ind_hint = _first(industries, "")

        for tech in techs[: self.max_queries_per_signal]:
            # Generic tech company search
            queries.append(
                PlannedQuery(
                    query_string=_join(
                        f"company using {tech}",
                        ind_hint,
                        "hiring engineers",
                    ),
                    signal_type="technology_stack",
                    priority=2,
                )
            )
            # StackShare / BuiltWith indexed pages
            queries.append(
                PlannedQuery(
                    query_string=f"{tech} {ind_hint} tech stack",
                    signal_type="technology_stack",
                    priority=3,
                    config_overrides={"include_domains": ["stackshare.io", "builtwith.com"]},
                )
            )

        # Migration targets — companies moving away from old tech
        for from_tech, to_tech in zip(
            icp.technologies.migrating_from,
            icp.technologies.migrating_to,
        ):
            queries.append(
                PlannedQuery(
                    query_string=_join(
                        f"migrating from {from_tech} to {to_tech}",
                        ind_hint,
                    ),
                    signal_type="technology_stack",
                    priority=3,
                )
            )

        return queries[: self.max_queries_per_signal]

    def build_hiring_signal_queries(self, icp: IcpDiscoveryQuery) -> list[PlannedQuery]:
        """
        Job posting queries — proxy for team growth and outsourcing need.
        Priority 2 — high-intent signal.
        """
        queries: list[PlannedQuery] = []
        hiring_kws = icp.signals.hiring_signals
        techs = icp.technologies.required or icp.technologies.preferred
        industries = icp.target_company.industries or []
        ind_hint = _first(industries, "")
        locations = icp.locations.countries or []
        loc_hint = _first(locations, "")

        # Generic hiring + tech signal
        for tech in techs[:3]:
            queries.append(
                PlannedQuery(
                    query_string=_join(
                        f"hiring {tech} engineer",
                        ind_hint,
                        loc_hint,
                        "job opening",
                    ),
                    signal_type="hiring_signals",
                    priority=2,
                    config_overrides={
                        "include_domains": [
                            "lever.co",
                            "greenhouse.io",
                            "jobs.ashbyhq.com",
                            "jobs.workable.com",
                        ]
                    },
                )
            )

        # Keyword-driven hiring queries
        for kw in hiring_kws[:2]:
            queries.append(
                PlannedQuery(
                    query_string=_join(kw, ind_hint, loc_hint),
                    signal_type="hiring_signals",
                    priority=3,
                )
            )

        # Project-type signals (e.g. "cloud migration project engineer")
        for ptype in icp.opportunities.project_types[:2]:
            queries.append(
                PlannedQuery(
                    query_string=_join(
                        ptype.replace("_", " "),
                        "engineer hiring",
                        ind_hint,
                    ),
                    signal_type="hiring_signals",
                    priority=3,
                )
            )

        return queries[: self.max_queries_per_signal]

    def build_outsourcing_signal_queries(self, icp: IcpDiscoveryQuery) -> list[PlannedQuery]:
        """
        Find companies showing outsourcing readiness signals.
        Priority 3.
        """
        queries: list[PlannedQuery] = []
        industries = icp.target_company.industries or ["software"]
        ind_hint = _first(industries, "software")
        eng_models = icp.outsource.engagement_models

        queries.append(
            PlannedQuery(
                query_string=_join(
                    ind_hint,
                    "company outsource software development vendor",
                ),
                signal_type="outsourcing_signals",
                priority=3,
            )
        )

        for model in eng_models[:2]:
            queries.append(
                PlannedQuery(
                    query_string=_join(
                        model.replace("_", " "),
                        ind_hint,
                        "company",
                    ),
                    signal_type="outsourcing_signals",
                    priority=4,
                )
            )

        # Contract / temp role signals
        for signal in icp.outsource.outsourcing_signals[:2]:
            queries.append(
                PlannedQuery(
                    query_string=_join(
                        signal.replace("_", " "),
                        ind_hint,
                    ),
                    signal_type="outsourcing_signals",
                    priority=4,
                )
            )

        return queries[: self.max_queries_per_signal]

    def build_business_event_queries(self, icp: IcpDiscoveryQuery) -> list[PlannedQuery]:
        """
        News queries for funding, expansion, M&A, digital transformation events.
        Priority 3 — high recency signal for outsourcing budget availability.
        """
        queries: list[PlannedQuery] = []
        industries = icp.target_company.industries or ["software"]
        ind_hint = _first(industries, "software")
        events = icp.signals.business_events
        locations = icp.locations.countries or []
        loc_hint = _first(locations, "")

        _EVENT_TEMPLATES: dict[str, str] = {
            "funding": "{industry} startup funding Series",
            "merger": "{industry} company merger acquisition",
            "expansion": "{industry} company expansion {location}",
            "new_office": "{industry} company new office {location}",
            "new_product": "{industry} company new product launch",
            "digital_transformation": "digital transformation {industry} {location}",
        }

        for event in events[: self.max_queries_per_signal]:
            template = _EVENT_TEMPLATES.get(event, "{industry} company {event}")
            q = (
                template.replace("{industry}", ind_hint)
                .replace("{location}", loc_hint)
                .replace("{event}", event.replace("_", " "))
                .strip()
            )
            queries.append(
                PlannedQuery(
                    query_string=q,
                    signal_type="business_events",
                    search_type="news",
                    priority=3,
                    config_overrides={"time_range": "qdr:m"},  # last month
                )
            )

        # Always add a generic funding news query for the industry
        queries.append(
            PlannedQuery(
                query_string=_join(ind_hint, "startup funding raised", loc_hint),
                signal_type="business_events",
                search_type="news",
                priority=4,
                config_overrides={"time_range": "qdr:m"},
            )
        )

        return queries[: self.max_queries_per_signal]

    def build_decision_maker_queries(self, icp: IcpDiscoveryQuery) -> list[PlannedQuery]:
        """
        Queries targeting specific buyer persona titles.
        Priority 4 — used after company targets are identified.
        """
        queries: list[PlannedQuery] = []
        titles = icp.buyer_persona.titles
        industries = icp.target_company.industries or []
        ind_hint = _first(industries, "")

        for title in titles[: self.max_queries_per_signal]:
            queries.append(
                PlannedQuery(
                    query_string=_join(
                        f'"{title}"',
                        ind_hint,
                        "company",
                    ),
                    signal_type="decision_makers",
                    priority=4,
                    config_overrides={
                        "include_domains": ["linkedin.com"],
                    },
                )
            )

        # Fallback if no titles — use departments
        if not titles:
            for dept in icp.buyer_persona.departments[:2]:
                queries.append(
                    PlannedQuery(
                        query_string=_join(
                            f"{dept} department head",
                            ind_hint,
                            "company",
                        ),
                        signal_type="decision_makers",
                        priority=5,
                    )
                )

        return queries[: self.max_queries_per_signal]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIZE_TERM_MAP: dict[str, str] = {
    "startup": "startup",
    "mid_market": "mid-size company 100-1000 employees",
    "enterprise": "enterprise large company",
}


def _size_to_terms(sizes: list[str]) -> str:
    terms = [_SIZE_TERM_MAP.get(s, s) for s in sizes]
    return " ".join(dict.fromkeys(terms))  # deduplicate, preserve order


def _first(lst: list, default: str) -> str:
    return lst[0] if lst else default


def _join(*parts: str) -> str:
    """Join non-empty strings with a single space."""
    return " ".join(p.strip() for p in parts if p and p.strip())
