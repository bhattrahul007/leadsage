from __future__ import annotations

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
    """
    Creates ``BaseAgent`` instances from ``AppConfig``.

    The factory:
    1. Looks up the agent class in the registry.
    2. Reads the model name from ``config.llm.models.<required_model_role>``.
    3. Creates the LLM backend via ``create_llm()``.
    4. Injects ``bus`` and ``session`` as optional deps.

    Example::

        from agents.factory import AgentFactory

        icp_agent = AgentFactory.create("icp_parser", config, bus=bus, session=s)
        scorer    = AgentFactory.create("lead_scorer", config, bus=bus, session=s)
    """

    @staticmethod
    def _ensure_registered() -> None:
        """Import all built-in agents to trigger their decorators."""
        from agents import icp_parser  # noqa: F401
        from agents import lead_scorer  # noqa: F401
        from agents import research  # noqa: F401
        from agents import contact_finder  # noqa: F401

    @classmethod
    def create(
        cls,
        agent_name: str,
        config: "AppConfig",
        bus: "EventBus | None" = None,
        session: "Session | None" = None,
        **extra_kwargs: Any,
    ) -> BaseAgent:
        """
        Instantiate an agent by name.

        Args:
            agent_name:   Registry slug, e.g. ``"icp_parser"``.
            config:       Full ``AppConfig`` for LLM config lookup.
            bus:          Optional ``EventBus`` for event publishing.
            session:      Optional current ``Session``.
            **extra_kwargs: Passed to the agent constructor.

        Returns:
            A ready-to-use ``BaseAgent`` instance.

        Raises:
            ValueError: If ``agent_name`` is not registered.
        """
        cls._ensure_registered()

        if agent_name not in _AGENT_REGISTRY:
            available = ", ".join(sorted(_AGENT_REGISTRY))
            raise ValueError(f"Unknown agent: {agent_name!r}. Available: [{available}]")

        agent_cls = _AGENT_REGISTRY[agent_name]

        # Resolve model name from config
        model_role = agent_cls.required_model_role
        model_name = getattr(config.llm.models, model_role, config.llm.models.lead_scorer)

        from common.llm import create_llm

        llm = create_llm(config.llm, model_name, agent_name=agent_name)

        logger.debug(
            "Creating agent %s with model=%s role=%s",
            agent_name,
            model_name,
            model_role,
        )
        return agent_cls(llm=llm, bus=bus, session=session, **extra_kwargs)

    @classmethod
    def registered(cls) -> list[str]:
        cls._ensure_registered()
        return sorted(_AGENT_REGISTRY)
