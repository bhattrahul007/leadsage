from __future__ import annotations

import logging

from pydantic import BaseModel

from common.llm.base import BaseLLM

logger = logging.getLogger(__name__)


class OpenAICompatLLM(BaseLLM):
    """
    LangChain-backed OpenAI / OpenAI-compatible implementation.

    Example (Ollama /v1 endpoint)::

        llm = OpenAICompatLLM(
            model_name="qwen2.5:7b",
            base_url="http://localhost:11434/v1",
            api_key="ollama",
        )

    Example (OpenAI)::

        llm = OpenAICompatLLM(
            model_name="gpt-4o-mini",
            base_url=None,
            api_key=os.environ["OPENAI_API_KEY"],
        )
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None,
        api_key: str | None,
        temperature: float = 0.1,
        timeout: int = 60,
    ) -> None:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise ImportError(
                "langchain-openai is required. Install: uv add langchain-openai"
            ) from exc

        self._model_name = model_name
        kwargs: dict = dict(
            model=model_name,
            temperature=temperature,
            timeout=timeout,
        )
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key

        self._llm = ChatOpenAI(**kwargs)
        logger.debug("OpenAICompatLLM ready: model=%s base_url=%s", model_name, base_url)

    @property
    def model_name(self) -> str:
        return self._model_name

    def invoke(self, prompt: str) -> str:
        response = self._llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else response
        return content if isinstance(content, str) else str(content)

    def invoke_structured(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        from typing import cast

        structured = self._llm.with_structured_output(schema)
        result = structured.invoke(prompt)
        if result is None:
            raise ValueError(
                f"Model {self._model_name!r} returned None for schema {schema.__name__!r}"
            )
        if isinstance(result, dict):
            return schema.model_validate(result)
        return cast(BaseModel, result)
