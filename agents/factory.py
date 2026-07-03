import logging
from typing import TYPE_CHECKING, Any

from agents.base import BaseAgent

if TYPE_CHECKING:
    from common.config import AppConfig
    from common.events.bus import EventBus
    from common.session.manager import Session

logger = logging.getLogger(__name__)

_AGENT_REGISTRY: dict[str, type[BaseAgent]] = {}


def register_agent(name: str):
    """Class decorator to register an agent under ``name``."""

    def decorator(cls: type[BaseAgent]) -> type[BaseAgent]:
        cls.name = name
        _AGENT_REGISTRY[name] = cls
        logger.debug("Registered agent: %s → %s", name, cls.__name__)
        return cls

    return decorator


class AgentFactory:
    """Creates ``BaseAgent`` instances from ``AppConfig``."""

    @staticmethod
    def _ensure_registered() -> None:
        from agents import (
            contact_finder,  # noqa: F401
            icp_parser,  # noqa: F401
            icp_refiner,  # noqa: F401
            lead_scorer,  # noqa: F401
            research,  # noqa: F401
        )

    @classmethod
    def create(
        cls,
        agent_name: str,
        config: "AppConfig",
        bus: "EventBus | None" = None,
        session: "Session | None" = None,
        **extra_kwargs: Any,
    ) -> BaseAgent:
        """Instantiate an agent by name, injecting LLM, cache, bus, and session."""
        cls._ensure_registered()

        if agent_name not in _AGENT_REGISTRY:
            available = ", ".join(sorted(_AGENT_REGISTRY))
            raise ValueError(f"Unknown agent: {agent_name!r}. Available: [{available}]")

        agent_cls = _AGENT_REGISTRY[agent_name]
        model_role = agent_cls.required_model_role
        model_name = getattr(config.llm.models, model_role, config.llm.models.lead_scorer)

        from common.llm import create_llm

        llm = create_llm(config.llm, model_name, agent_name=agent_name)

        if config.session.llm_cache_enabled:
            try:
                from common.llm.cached_llm import CachedLLM
                from common.llm.response_cache import LLMResponseCache

                resp_cache = LLMResponseCache(lru_maxsize=config.session.llm_cache_lru_maxsize)

                def _on_hit(model: str) -> None:
                    if bus:
                        from common.events.events import LlmCacheHit

                        bus.publish(
                            LlmCacheHit(
                                session_id=session.id if session else "no_session",
                                model=model,
                                agent_role=agent_name,
                            )
                        )

                llm = CachedLLM.for_agent(llm, resp_cache, agent_name, on_cache_hit=_on_hit)
            except Exception:
                pass

        override = config.llm.get_agent_override(agent_name)
        if override.timeout_budget_s and "timeout_budget_s" not in extra_kwargs:
            extra_kwargs["timeout_budget_s"] = override.timeout_budget_s

        logger.debug("Creating agent %s model=%s role=%s", agent_name, model_name, model_role)
        return agent_cls(llm=llm, bus=bus, session=session, **extra_kwargs)

    @classmethod
    def registered(cls) -> list[str]:
        cls._ensure_registered()
        return sorted(_AGENT_REGISTRY)
