from __future__ import annotations

import importlib
import logging

logger = logging.getLogger(__name__)

_PROVIDERS = [
    "discovery.retreivers.serper.serper_search",
    "discovery.retreivers.tavily.tavily_search",
    "discovery.retreivers.google.google_search",
    "discovery.retreivers.bing.bing_search",
    "discovery.retreivers.searchapi.searchapi_search",
    "discovery.retreivers.yc.yc_search",
    "discovery.retreivers.github.github_search",
    "discovery.retreivers.crunchbase.crunchbase_search",
    "discovery.retreivers.producthunt.ph_search",
    "discovery.retreivers.jobboards.lever_search",
    "discovery.retreivers.jobboards.greenhouse_search",
    "discovery.retreivers.wellfound.wellfound_search",
]

for _module_path in _PROVIDERS:
    try:
        importlib.import_module(_module_path)
    except ImportError as _exc:
        logger.debug("Optional search provider not loaded (%s): %s", _module_path, _exc)
    except Exception as _exc:
        logger.warning("Search provider registration failed (%s): %s", _module_path, _exc)
