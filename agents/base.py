from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from common.llm.base import BaseLLM
    from common.events.bus import EventBus
    from common.session.manager import Session


class BaseAgent(ABC):
    """Abstract base for all pipeline agents.

    Subclasses set ``name`` (registry slug) and ``required_model_role``,
    implement ``run()``, and use ``_safe_invoke()`` for guarded LLM calls.
    """

    name: str = ""
    required_model_role: str = "lead_scorer"

    def __init__(
        self,
        llm: "BaseLLM",
        bus: "EventBus | None" = None,
        session: "Session | None" = None,
        timeout_budget_s: int | None = None,
    ) -> None:
        self.llm = llm
        self.bus = bus
        self.session = session
        self._timeout_budget_s = timeout_budget_s

    @abstractmethod
    def run(self, **kwargs: Any) -> Any:
        """Execute the agent's task. Should never raise."""
        ...

    def _safe_invoke(self, prompt: str, schema, fallback=None):
        """Guarded structured LLM call — returns ``fallback`` on any error."""
        import logging
        import concurrent.futures

        budget = self._timeout_budget_s
        try:
            if budget:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(self.llm.invoke_structured, prompt, schema)
                    return future.result(timeout=budget)
            return self.llm.invoke_structured(prompt, schema)
        except concurrent.futures.TimeoutError:
            logging.getLogger(self.__class__.__name__).warning(
                "LLM budget exceeded (%ds) — using fallback.", budget
            )
            return fallback
        except Exception as exc:
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
