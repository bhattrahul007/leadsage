from __future__ import annotations


from dataclasses import dataclass, field
from datetime import datetime, timezone

from common.schemas.icp_request import IcpDiscoveryQuery
from common.email_validator import filter_valid
from discovery.retreivers.base import SearchResult
from discovery.crawler import CrawledPage


_FUNDING_KWS = frozenset(
    {
        "series a",
        "series b",
        "series c",
        "seed round",
        "funding round",
        "raised $",
        "raised funding",
        "venture capital",
        "vc backed",
        "investors led",
        "pre-ipo",
    }
)

_OUTSOURCING_KWS = frozenset(
    {
        "staff augmentation",
        "dedicated team",
        "outsource",
        "outsourcing",
        "managed services",
        "contract developers",
        "vendor",
        "offshore",
        "nearshore",
        "third-party",
        "agency partner",
        "software partner",
        "external team",
    }
)

_HIRING_ROLE_KWS = frozenset(
    {
        "software engineer",
        "backend engineer",
        "frontend engineer",
        "full stack",
        "devops engineer",
        "platform engineer",
        "sre",
        "data engineer",
        "ml engineer",
        "mobile engineer",
        "cloud architect",
        "solutions architect",
        "engineering manager",
        "cto",
        "vp engineering",
        "head of engineering",
        "chief technology officer",
    }
)

_BUSINESS_EVENT_KWS = frozenset(
    {
        "digital transformation",
        "modernization",
        "cloud migration",
        "new product",
        "launched",
        "expansion",
        "new office",
        "acquired",
        "merger",
        "acquisition",
        "partnership",
    }
)

_SIZE_KWS: dict[str, list[str]] = {
    "startup": ["startup", "founded", "early stage", "seed"],
    "mid_market": ["mid-size", "scale-up", "100 employees", "500 employees", "series"],
    "enterprise": ["enterprise", "fortune", "10,000 employees", "global company"],
}


@dataclass
class ScoreBreakdown:
    """Component scores that sum into the final relevance score."""

    technology: float = 0.0  # 0–1: tech stack match
    hiring: float = 0.0  # 0–1: hiring signal strength
    profile: float = 0.0  # 0–1: industry/size/location match
    composite: float = 0.0  # weighted final score


@dataclass
class EnrichedLead:
    """
    A scored, enriched company lead produced by the enricher.

    Attributes
    ----------
    domain:               Company domain (primary key).
    company_name:         Best-guess company name.
    source_url:           The crawled URL this came from.
    search_result:        The original search result that led to this URL.
    industry_signals:     Industry keywords found in the page.
    tech_stack:           Technologies detected.
    hiring_signals:       Job-related role keywords found.
    outsourcing_signals:  Outsourcing readiness keywords found.
    business_events:      Funding/expansion keywords found.
    decision_maker_hints: Titles/names that look like decision makers.
    score:                Full score breakdown.
    icp_relevance_score:  Final composite score (0.0–1.0). Use this to rank.
    evidence:             Short text snippets supporting the score.
    emails:               Email addresses found on the page.
    phone_numbers:        Phone numbers found on the page.
    linkedin_url:         LinkedIn company page URL if detected.
    github_url:           GitHub org URL if detected.
    twitter_url:          Twitter/X URL if detected.
    crunchbase_url:       Crunchbase URL if detected.
    angellist_url:        AngelList URL if detected.
    """

    domain: str
    company_name: str
    source_url: str
    search_result: SearchResult

    industry_signals: list[str] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    hiring_signals: list[str] = field(default_factory=list)
    outsourcing_signals: list[str] = field(default_factory=list)
    business_events: list[str] = field(default_factory=list)
    decision_maker_hints: list[str] = field(default_factory=list)
    score: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    icp_relevance_score: float = 0.0
    evidence: list[str] = field(default_factory=list)

    # Contact info — populated from the crawled page's ExtractedMeta
    emails: list[str] = field(default_factory=list)
    phone_numbers: list[str] = field(default_factory=list)
    linkedin_url: str | None = None
    github_url: str | None = None
    twitter_url: str | None = None
    crunchbase_url: str | None = None
    angellist_url: str | None = None

    def __repr__(self) -> str:
        return (
            f"<EnrichedLead {self.domain!r} "
            f"score={self.icp_relevance_score:.2f} "
            f"tech={self.tech_stack[:3]}>"
        )


@dataclass
class EnricherConfig:
    """
    Configuration for ``LeadEnricher``.

    Attributes
    ----------
    min_score:   Filter out leads with composite score below this threshold.
    weights:     Weight tuple (technology, hiring, profile) — must sum to 1.0.
    max_evidence_snippets:  Max evidence text snippets per lead.
    snippet_window:         Character window around matched keyword.
    """

    min_score: float = 0.15
    weights: tuple[float, float, float] = (0.40, 0.35, 0.25)
    max_evidence_snippets: int = 5
    snippet_window: int = 120

    def __post_init__(self) -> None:
        total = sum(self.weights)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"weights must sum to 1.0, got {total}")


class LeadEnricher:
    """
    Scores and enriches a ``CrawledPage`` + ``SearchResult`` pair against
    the ``IcpDiscoveryQuery`` to produce an ``EnrichedLead``.

    Example
    -------
    ::

        enricher = LeadEnricher(icp, EnricherConfig(min_score=0.2))
        leads = enricher.enrich_many(list(zip(crawled_pages, search_results)))
        leads.sort(key=lambda l: -l.icp_relevance_score)
    """

    def __init__(
        self,
        icp: IcpDiscoveryQuery,
        config: EnricherConfig | None = None,
    ) -> None:
        self.icp = icp
        self.config = config or EnricherConfig()
        # Override weights dynamically from ICP intent
        self.config = EnricherConfig(
            min_score=self.config.min_score,
            weights=_compute_weights(icp),
            max_evidence_snippets=self.config.max_evidence_snippets,
            snippet_window=self.config.snippet_window,
        )
        self._icp_techs = _lower_set(icp.technologies.required + icp.technologies.preferred)
        self._icp_industries = _lower_set(icp.target_company.industries)
        self._icp_locations = _lower_set(
            icp.locations.countries + icp.locations.cities + icp.locations.regions
        )
        self._icp_titles = _lower_set(icp.buyer_persona.titles)

    def enrich(
        self,
        page: CrawledPage,
        search_result: SearchResult,
    ) -> EnrichedLead | None:
        """
        Enrich one crawled page.

        Returns ``None`` if the page failed to crawl or scored below
        ``config.min_score``.
        """
        if not page.success or not page.text_content:
            return None

        text_lower = page.text_content.lower()
        cfg = self.config

        # ── Extract signals ────────────────────────────────────────────
        tech_stack = self._extract_tech(page, text_lower)
        hiring = self._extract_hiring(text_lower)
        outsourcing = self._extract_outsourcing(text_lower)
        biz_events = self._extract_business_events(text_lower)
        dm_hints = self._extract_decision_makers(text_lower)
        industries = self._extract_industries(text_lower)

        # ── Score ──────────────────────────────────────────────────────
        tech_score = self._score_tech(tech_stack)
        hiring_score = self._score_hiring(hiring)
        profile_score = self._score_profile(industries, text_lower)

        w = cfg.weights
        composite = w[0] * tech_score + w[1] * hiring_score + w[2] * profile_score

        # Apply freshness multiplier based on search result date
        freshness = _freshness_multiplier(
            (search_result.get("metadata") or {}).get("published_date")
        )
        composite = min(1.0, composite * freshness)

        if composite < cfg.min_score:
            return None

        # ── Evidence ───────────────────────────────────────────────────
        evidence_kws = list(self._icp_techs)[:3] + list(self._icp_industries)[:2] + hiring[:2]
        evidence = _extract_evidence(
            page.text_content,
            evidence_kws,
            window=cfg.snippet_window,
            max_snippets=cfg.max_evidence_snippets,
        )

        social = page.meta.social_links
        return EnrichedLead(
            domain=page.domain,
            company_name=_infer_company_name(page),
            source_url=page.final_url or page.url,
            search_result=search_result,
            industry_signals=industries,
            tech_stack=tech_stack,
            hiring_signals=hiring,
            outsourcing_signals=outsourcing,
            business_events=biz_events,
            decision_maker_hints=dm_hints,
            score=ScoreBreakdown(
                technology=tech_score,
                hiring=hiring_score,
                profile=profile_score,
                composite=composite,
            ),
            icp_relevance_score=round(composite, 4),
            evidence=evidence,
            # Contact info from crawled page
            emails=filter_valid(page.meta.emails),
            phone_numbers=page.meta.phone_numbers,
            linkedin_url=social.get("linkedin"),
            github_url=social.get("github"),
            twitter_url=social.get("twitter"),
            crunchbase_url=social.get("crunchbase"),
            angellist_url=social.get("angellist"),
        )

    def enrich_many(
        self,
        pairs: list[tuple[CrawledPage, SearchResult]],
    ) -> list[EnrichedLead]:
        """
        Enrich a list of (CrawledPage, SearchResult) pairs.
        Returns only non-None results, sorted by relevance score descending.
        """
        leads: list[EnrichedLead] = []
        for page, result in pairs:
            lead = self.enrich(page, result)
            if lead is not None:
                leads.append(lead)
        leads.sort(key=lambda l: -l.icp_relevance_score)
        return leads

    def _extract_tech(self, page: CrawledPage, text_lower: str) -> list[str]:
        # Combine crawler-detected tech with a text scan for ICP-required tech
        detected = set(page.meta.tech_signals)
        for tech in self._icp_techs:
            if tech in text_lower:
                detected.add(tech)
        return sorted(detected)

    def _extract_hiring(self, text_lower: str) -> list[str]:
        return sorted({kw for kw in _HIRING_ROLE_KWS if kw in text_lower})

    def _extract_outsourcing(self, text_lower: str) -> list[str]:
        return sorted({kw for kw in _OUTSOURCING_KWS if kw in text_lower})

    def _extract_business_events(self, text_lower: str) -> list[str]:
        return sorted({kw for kw in _FUNDING_KWS | _BUSINESS_EVENT_KWS if kw in text_lower})

    def _extract_decision_makers(self, text_lower: str) -> list[str]:
        hits = {kw for kw in self._icp_titles if kw in text_lower}
        # Fix: parenthesise the "cto"/"vp" check to avoid operator-precedence bug
        hits |= {kw for kw in _HIRING_ROLE_KWS if kw in text_lower and ("cto" in kw or "vp" in kw)}
        return sorted(hits)

    def _extract_industries(self, text_lower: str) -> list[str]:
        return sorted({ind for ind in self._icp_industries if ind in text_lower})

    def _score_tech(self, detected: list[str]) -> float:
        if not self._icp_techs:
            return 0.5  # no tech requirement = neutral
        required_hits = len(set(detected) & self._icp_techs)
        return min(1.0, required_hits / max(len(self._icp_techs), 1))

    def _score_hiring(self, hiring_signals: list[str]) -> float:
        if not hiring_signals:
            return 0.0
        # Scale up to 5 signals = full score
        return min(1.0, len(hiring_signals) / 5)

    def _score_profile(self, industries: list[str], text_lower: str) -> float:
        score = 0.0
        total = 0.0

        # Industry match (weight 0.5)
        if self._icp_industries:
            total += 0.5
            if industries:
                score += 0.5 * (
                    len(set(industries) & self._icp_industries) / len(self._icp_industries)
                )

        # Location match (weight 0.3)
        if self._icp_locations:
            total += 0.3
            for loc in self._icp_locations:
                if loc in text_lower:
                    score += 0.3
                    break

        # Size match (weight 0.2)
        icp_sizes = self.icp.target_company.size
        if icp_sizes:
            total += 0.2
            for size in icp_sizes:
                kws = _SIZE_KWS.get(size, [])
                if any(kw in text_lower for kw in kws):
                    score += 0.2
                    break

        return min(1.0, score / total) if total > 0 else 0.5


def _lower_set(items: list[str]) -> frozenset[str]:
    return frozenset(i.lower() for i in items if i)


def _infer_company_name(page: CrawledPage) -> str:
    """Best-effort company name extraction."""
    # Try JSON-LD Organization
    for item in page.meta.json_ld:
        if item.get("@type") in ("Organization", "Corporation"):
            name = item.get("name") or item.get("legalName")
            if name:
                return name

    # OG site name
    if page.meta.og_site_name:
        return page.meta.og_site_name

    # Title heuristic: "Acme Corp | Software" → "Acme Corp"
    title = page.title
    for sep in (" | ", " - ", " – ", " — ", " :: "):
        if sep in title:
            return title.split(sep)[0].strip()

    return title.strip() or page.domain


def _compute_weights(icp: IcpDiscoveryQuery) -> tuple[float, float, float]:
    """Dynamic scoring weights based on the dominant ICP signal type."""
    if icp.technologies.required:
        return (0.50, 0.30, 0.20)  # tech-heavy ICP
    if icp.signals.hiring_signals:
        return (0.25, 0.50, 0.25)  # hiring-focused
    if icp.target_company.industries:
        return (0.30, 0.25, 0.45)  # industry-focused
    return (0.40, 0.35, 0.25)  # balanced default


def _freshness_multiplier(published_date: str | None) -> float:
    """Time-decay factor: recent pages score higher."""
    if not published_date:
        return 0.85  # unknown date — slight penalty
    try:
        date = datetime.fromisoformat(published_date.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - date).days
        if age_days < 30:
            return 1.0
        if age_days < 90:
            return 0.9
        if age_days < 365:
            return 0.75
        return 0.5
    except Exception:
        return 0.85


def _extract_evidence(
    text: str,
    keywords: list[str],
    window: int,
    max_snippets: int,
) -> list[str]:
    """
    Extract short text snippets (±window chars) around matched keywords.
    """
    text_lower = text.lower()
    snippets: list[str] = []
    seen_positions: set[int] = set()

    for kw in keywords:
        idx = text_lower.find(kw)
        if idx == -1:
            continue
        # Avoid overlapping snippets (within window chars of each other)
        if any(abs(idx - p) < window for p in seen_positions):
            continue
        seen_positions.add(idx)
        start = max(0, idx - window // 2)
        end = min(len(text), idx + len(kw) + window // 2)
        snippet = text[start:end].replace("\n", " ").strip()
        if snippet:
            snippets.append(f"...{snippet}...")
        if len(snippets) >= max_snippets:
            break

    return snippets
