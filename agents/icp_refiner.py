from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from agents.base import BaseAgent
from agents.factory import register_agent

if TYPE_CHECKING:
    from common.schemas.icp_request import IcpDiscoveryQuery
    from common.schemas.lead_output import ScoredLead


@register_agent("icp_refiner")
class IcpRefinerAgent(BaseAgent):
    """
    Feedback loop agent: injects common signals from HOT leads
    back into the ICP to tighten subsequent discovery rounds.

    Example::

        refiner = AgentFactory.create("icp_refiner", cfg)
        refined_icp = refiner.refine(icp, hot_leads)
    """

    name = "icp_refiner"
    required_model_role = "icp_parser"

    def run(self, **kwargs: Any) -> Any:
        return self.refine(kwargs["icp"], kwargs["hot_leads"])

    def refine(
        self,
        icp: IcpDiscoveryQuery,
        hot_leads: list[ScoredLead],
    ) -> IcpDiscoveryQuery:
        """
        Enrich ``icp`` with common signals extracted from ``hot_leads``.

        Adds frequently-appearing tech and industry terms that are not
        already required. Returns the same ``icp`` object (mutated in-place).
        """
        if not hot_leads:
            return icp

        # Top 5 common tech not yet required
        tech_counts = Counter(t for lead in hot_leads for t in lead.tech_stack)
        required_lower = {t.lower() for t in icp.technologies.required}
        new_tech = [t for t, _ in tech_counts.most_common(5) if t.lower() not in required_lower]
        if new_tech:
            icp.technologies.preferred = list(set(icp.technologies.preferred + new_tech))

        # Infer industry if ICP had none
        if not icp.target_company.industries:
            ind_counts = Counter(
                ind for lead in hot_leads for ind in getattr(lead, "industry_signals", [])
            )
            top_industries = [ind for ind, _ in ind_counts.most_common(3)]
            icp.target_company.industries = top_industries

        return icp
