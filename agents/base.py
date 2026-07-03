from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from common.llm.base import BaseLLM
    from common.events.bus import EventBus
    from common.session.manager import Session


class BaseAgent(ABC):
    """
    Abstract base class for all pipeline agents.

    Every agent:
    - Holds a reference to its ``BaseLLM`` instance
    - Optionally holds a reference to the ``EventBus`` for publishing events
    - Has a ``run()`` method with agent-specific arguments
    - Has a ``name`` class attribute for registration

    Fault tolerance
    ---------------
    Agents must catch their own errors and return a sensible fallback.
    They should never let exceptions propagate to the pipeline orchestrator.
    The base class provides ``_safe_invoke()`` for guarded LLM calls.

    Observability
    -------------
    Agents should publish relevant events (``LeadScored``, ``IcpParsed``, etc.)
    to the bus during ``run()``. The bus handles all logging/metrics.
    """

    #: Unique slug for registration. Set this in subclasses.
    name: str = ""

    #: The ``LLMConfig.models`` key this agent reads for its model name.
    required_model_role: str = "lead_scorer"

    def __init__(
        self,
        llm: "BaseLLM",
        bus: "EventBus | None" = None,
        session: "Session | None" = None,
    ) -> None:
        """
        Args:
            llm:     The LLM backend this agent uses.
            bus:     Optional event bus for publishing lifecycle events.
            session: Optional current session context.
        """
        self.llm = llm
        self.bus = bus
        self.session = session

    @abstractmethod
    def run(self, **kwargs: Any) -> Any:
        """
        Execute the agent's task.

        Args:
            **kwargs: Agent-specific arguments.

        Returns:
            Agent-specific output. Should never raise.
        """
        ...

    def _safe_invoke(self, prompt: str, schema, fallback=None):
        """
        Guarded structured LLM call — returns ``fallback`` on any error.

        Args:
            prompt:   The prompt string.
            schema:   Pydantic model class for structured output.
            fallback: Value to return on LLM failure.
        """
        try:
            return self.llm.invoke_structured(prompt, schema)
        except Exception as exc:
            import logging

            logging.getLogger(self.__class__.__name__).warning(
                "LLM call failed (%s: %s)", type(exc).__name__, exc
            )
            return fallback

    def _publish(self, event: Any) -> None:
        """Publish an event if a bus is configured."""
        if self.bus:
            self.bus.publish(event)

    @property
    def session_id(self) -> str:
        return self.session.id if self.session else "no_session"

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} model={self.llm.model_name!r} session={self.session_id!r}>"
        )
