from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Type

if TYPE_CHECKING:
    from pydantic import BaseModel


class BaseLLM(ABC):
    """
    Minimal, backend-agnostic interface for LLM invocations.

    Two methods only:

    ``invoke(prompt)``
        Send a plain text prompt, get a plain text response.

    ``invoke_structured(prompt, schema)``
        Send a prompt and parse the model's response into a Pydantic model.
        Raises ``ValueError`` if the model returns data that cannot be
        coerced into ``schema``.

    Implementations should be thread-safe (used in thread pools).
    """

    @abstractmethod
    def invoke(self, prompt: str) -> str:
        """
        Send ``prompt`` to the model; return its text response.

        Args:
            prompt: Plain text prompt (system + user combined or just user).

        Returns:
            The model's text response as a string.
        """
        ...

    @abstractmethod
    def invoke_structured(self, prompt: str, schema: Type["BaseModel"]) -> "BaseModel":
        """
        Send ``prompt`` and return a validated instance of ``schema``.

        The underlying mechanism (function-calling, JSON mode, etc.) is an
        implementation detail. Callers only see a typed Pydantic object.

        Args:
            prompt: The prompt to send to the model.
            schema: A Pydantic ``BaseModel`` subclass that defines the
                    expected response shape.

        Returns:
            A populated instance of ``schema``.

        Raises:
            ValueError: If the model returns data that cannot be parsed into
                        ``schema`` after all retries are exhausted.
        """
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The model identifier string (e.g. ``'qwen2.5:7b'``, ``'gpt-4o'``)."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} model={self.model_name!r}>"
