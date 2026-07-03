from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from common.llm.base import BaseLLM

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AnthropicLLM(BaseLLM):
    def __init__(
        self,
        model_name: str,
        api_key: str,
        temperature: float = 0.1,
        timeout: int = 60,
    ) -> None:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise ImportError(
                "langchain-anthropic is required. Install it with: "
                "uv pip install langchain-anthropic"
            ) from exc

        from pydantic import SecretStr

        self._model_name = model_name
        self._llm = ChatAnthropic(
            model=model_name,
            api_key=SecretStr(api_key),
            temperature=temperature,
            timeout=timeout,
        )

    def invoke(self, prompt: str) -> str:
        from langchain_core.messages import HumanMessage

        response = self._llm.invoke([HumanMessage(content=prompt)])
        content = response.content
        return content if isinstance(content, str) else str(content)

    def invoke_structured(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        from typing import cast

        from langchain_core.messages import HumanMessage

        structured = self._llm.with_structured_output(schema)
        result = structured.invoke([HumanMessage(content=prompt)])
        if isinstance(result, dict):
            return schema.model_validate(result)
        return cast(BaseModel, result)

    @property
    def model_name(self) -> str:
        return self._model_name
