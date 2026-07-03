from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from common.llm.base import BaseLLM

if TYPE_CHECKING:
    from common.config import LLMConfig

logger = logging.getLogger(__name__)


def create_llm(llm_config: "LLMConfig", model_name: str) -> BaseLLM:
    """
    Instantiate the appropriate ``BaseLLM`` backend from config.

    Args:
        llm_config:  The ``LLMConfig`` section of ``AppConfig``.
        model_name:  The model identifier to use (e.g. ``'qwen2.5:7b'``).

    Returns:
        A ready-to-use ``BaseLLM`` instance.

    Raises:
        ImportError:  If the required backend library is not installed.
        ValueError:   If ``llm_config.provider`` is not a known value.

    Examples::

        from common.config import load_config
        from common.llm import create_llm

        cfg = load_config()

        # Use the model configured for ICP parsing
        icp_llm = create_llm(cfg.llm, cfg.llm.models.icp_parser)

        # Use the model configured for lead scoring
        scorer_llm = create_llm(cfg.llm, cfg.llm.models.lead_scorer)
    """
    provider = llm_config.provider
    logger.debug("Creating LLM: provider=%s model=%s", provider, model_name)

    if provider == "ollama":
        from common.llm.ollama import OllamaLLM

        return OllamaLLM(model_name=model_name, config=llm_config.ollama)

    if provider == "openai_compatible":
        from common.llm.openai_compat import OpenAICompatLLM

        cfg = llm_config.openai_compatible
        return OpenAICompatLLM(
            model_name=model_name,
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            temperature=cfg.temperature,
            timeout=cfg.timeout,
        )

    if provider == "openai":
        from common.llm.openai_compat import OpenAICompatLLM

        cfg = llm_config.openai
        api_key = cfg.api_key  # reads from env
        if not api_key:
            raise EnvironmentError(
                f"OpenAI API key not found. Set the {cfg.api_key_env!r} environment variable."
            )
        return OpenAICompatLLM(
            model_name=model_name,
            base_url=None,  # use default OpenAI endpoint
            api_key=api_key,
            temperature=cfg.temperature,
            timeout=cfg.timeout,
        )

    raise ValueError(
        f"Unknown LLM provider: {provider!r}. "
        "Valid options: 'ollama', 'openai', 'openai_compatible'."
    )
