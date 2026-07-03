from __future__ import annotations

import logging
from typing import Type

from pydantic import BaseModel

from common.llm.base import BaseLLM

logger = logging.getLogger(__name__)


class OllamaLLM(BaseLLM):
    """
    LangChain-backed Ollama implementation.

    Requires ``langchain-ollama`` to be installed::

        uv add langchain-ollama

    Example::

        from common.config import OllamaConfig
        from common.llm.ollama import OllamaLLM

        llm = OllamaLLM("qwen2.5:7b", OllamaConfig())
        text   = llm.invoke("Explain staff augmentation in one sentence.")
        parsed = llm.invoke_structured(prompt, MyPydanticSchema)
    """

    def __init__(self, model_name: str, config) -> None:
        """
        Args:
            model_name: Ollama model tag, e.g. ``'qwen2.5:3b'``.
            config:     ``OllamaConfig`` instance from ``common.config``.
        """
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise ImportError(
                "langchain-ollama is required. Install: uv add langchain-ollama"
            ) from exc

        self._model_name = model_name
        self._llm = ChatOllama(
            model=model_name,
            base_url=config.base_url,
            temperature=config.temperature,
            num_predict=config.num_predict,
        )
        logger.debug("OllamaLLM ready: model=%s base_url=%s", model_name, config.base_url)

    @property
    def model_name(self) -> str:
        return self._model_name

    def invoke(self, prompt: str) -> str:
        response = self._llm.invoke(prompt)
        return response.content if hasattr(response, "content") else str(response)

    def invoke_structured(self, prompt: str, schema: Type[BaseModel]) -> BaseModel:
        structured = self._llm.with_structured_output(schema)
        result = structured.invoke(prompt)
        if result is None:
            raise ValueError(
                f"Ollama model {self._model_name!r} returned None for schema {schema.__name__!r}"
            )
        return result
