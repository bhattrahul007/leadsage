from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from common.llm.base import BaseLLM

if TYPE_CHECKING:
    from common.config import LLMConfig

logger = logging.getLogger(__name__)


def create_llm(llm_config: LLMConfig, model_name: str, agent_name: str | None = None) -> BaseLLM:
    provider = llm_config.provider
    override = llm_config.get_agent_override(agent_name) if agent_name else None

    logger.debug("Creating LLM: provider=%s model=%s agent=%s", provider, model_name, agent_name)

    if provider == "ollama":
        from common.config import OllamaConfig
        from common.llm.ollama import OllamaLLM

        ollama_cfg = llm_config.ollama
        temperature = (
            override.temperature
            if override and override.temperature is not None
            else ollama_cfg.temperature
        )
        num_predict = (
            override.num_predict
            if override and override.num_predict is not None
            else ollama_cfg.num_predict
        )
        timeout = (
            override.timeout if override and override.timeout is not None else ollama_cfg.timeout
        )
        merged = OllamaConfig(
            base_url=ollama_cfg.base_url,
            temperature=temperature,
            num_predict=num_predict,
            timeout=timeout,
        )
        return OllamaLLM(model_name=model_name, config=merged)

    if provider == "openai_compatible":
        from common.llm.openai_compat import OpenAICompatLLM

        compat_cfg = llm_config.openai_compatible
        timeout = (
            override.timeout if override and override.timeout is not None else compat_cfg.timeout
        )
        temperature = (
            override.temperature
            if override and override.temperature is not None
            else compat_cfg.temperature
        )
        return OpenAICompatLLM(
            model_name=model_name,
            base_url=compat_cfg.base_url,
            api_key=compat_cfg.api_key,
            temperature=temperature,
            timeout=timeout,
        )

    if provider == "openai":
        from common.llm.openai_compat import OpenAICompatLLM

        openai_cfg = llm_config.openai
        api_key = openai_cfg.api_key
        if not api_key:
            raise OSError(
                f"OpenAI API key not found. Set the {openai_cfg.api_key_env!r} environment variable."
            )
        timeout = (
            override.timeout if override and override.timeout is not None else openai_cfg.timeout
        )
        temperature = (
            override.temperature
            if override and override.temperature is not None
            else openai_cfg.temperature
        )
        return OpenAICompatLLM(
            model_name=model_name or openai_cfg.model,
            base_url=None,
            api_key=api_key,
            temperature=temperature,
            timeout=timeout,
        )

    if provider == "groq":
        from common.llm.openai_compat import OpenAICompatLLM

        groq_cfg = llm_config.groq
        api_key = groq_cfg.api_key
        if not api_key:
            raise OSError(
                f"Groq API key not found. Set the {groq_cfg.api_key_env!r} environment variable."
            )
        timeout = (
            override.timeout if override and override.timeout is not None else groq_cfg.timeout
        )
        temperature = (
            override.temperature
            if override and override.temperature is not None
            else groq_cfg.temperature
        )
        return OpenAICompatLLM(
            model_name=model_name,
            base_url=groq_cfg.base_url,
            api_key=api_key,
            temperature=temperature,
            timeout=timeout,
        )

    if provider == "together":
        from common.llm.openai_compat import OpenAICompatLLM

        together_cfg = llm_config.together
        api_key = together_cfg.api_key
        if not api_key:
            raise OSError(
                f"Together AI key not found. Set the {together_cfg.api_key_env!r} environment variable."
            )
        timeout = (
            override.timeout if override and override.timeout is not None else together_cfg.timeout
        )
        temperature = (
            override.temperature
            if override and override.temperature is not None
            else together_cfg.temperature
        )
        return OpenAICompatLLM(
            model_name=model_name,
            base_url=together_cfg.base_url,
            api_key=api_key,
            temperature=temperature,
            timeout=timeout,
        )

    if provider == "anthropic":
        from common.llm.anthropic import AnthropicLLM

        anthropic_cfg = llm_config.anthropic
        api_key = anthropic_cfg.api_key
        if not api_key:
            raise OSError(
                f"Anthropic API key not found. Set the {anthropic_cfg.api_key_env!r} environment variable."
            )
        timeout = (
            override.timeout if override and override.timeout is not None else anthropic_cfg.timeout
        )
        temperature = (
            override.temperature
            if override and override.temperature is not None
            else anthropic_cfg.temperature
        )
        return AnthropicLLM(
            model_name=model_name or anthropic_cfg.model,
            api_key=api_key,
            temperature=temperature,
            timeout=timeout,
        )

    raise ValueError(
        f"Unknown LLM provider: {provider!r}. "
        "Valid options: 'ollama', 'openai', 'openai_compatible', 'groq', 'together', 'anthropic'."
    )
