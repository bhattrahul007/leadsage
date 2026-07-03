# Prospector — AI Lead Generation Agent

A production-grade, multi-agent AI system for B2B lead generation. It converts a plain-English Ideal Customer Profile (ICP) description into a ranked, enriched list of companies with decision-maker contacts, technology signals, and personalised outreach copy.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Architecture Overview](#architecture-overview)
3. [Design Patterns](#design-patterns)
4. [Project Structure](#project-structure)
5. [Pipeline Stages](#pipeline-stages)
6. [Agent Network](#agent-network)
7. [REST API](#rest-api)
8. [SSE Live Streaming](#sse-live-streaming)
9. [Celery Distributed Workers](#celery-distributed-workers)
10. [LLM Response Cache](#llm-response-cache)
11. [3-Tier Hierarchical Memory](#3-tier-hierarchical-memory)
12. [Search Providers & Linked Sources](#search-providers--linked-sources)
13. [LLM Providers](#llm-providers)
14. [Crawlers](#crawlers)
15. [Proxy Rotation](#proxy-rotation)
16. [Session Cache](#session-cache)
17. [Database (SQLAlchemy ORM)](#database-sqlalchemy-orm)
18. [Observability](#observability)
19. [Configuration Reference](#configuration-reference)
20. [Quick Start — Local](#quick-start--local)
21. [Docker Compose](#docker-compose)
22. [CI / CD](#ci--cd)
23. [Extending the System](#extending-the-system)

---

## What It Does

```
"Find US fintech SaaS companies with 50-500 employees using Kubernetes,
 actively hiring backend engineers, recently funded — target CTOs"
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          Prospector                                  │
│                                                                      │
│  ICP Parser ──► Query Planner ──► Multi-Engine Search               │
│       ──► Crawl + Cache ──► Enrich ──► Score (LLM) ──► Research    │
│       ──► ICP Refiner ──► Contact Finder ──► Output / API           │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  🔥 Stripe.com   [HOT  0.91]  CTO: John Doe  → "Your K8s migration…"
  🔥 Plaid.com    [HOT  0.87]  CTO: Jane Smith → "Hiring 12 backend…"
  🌤  Brex.com    [WARM 0.54]  VP Eng: …
```

**Output per lead:**
- Company name, domain, description
- ICP relevance score + tier (🔥 Hot / 🌤 Warm / ❄️ Cold)
- Technology stack, hiring signals, outsourcing signals
- Funding / business events
- Decision-maker names, titles, emails, LinkedIn
- Personalised outreach subject lines + opening hooks

---

## Architecture Overview

```
  ┌──────────────────┐    ┌─────────────────────────────────────────┐
  │   main.py (CLI)  │    │          api/app.py  (FastAPI)           │
  └────────┬─────────┘    │  POST /api/v1/runs          (202 async) │
           │               │  POST /api/v1/runs/stream    (SSE live) │
           │               │  GET  /api/v1/runs/{id}/status          │
           │               │  GET  /api/v1/runs/{id}/leads           │
           │               └──────────────────┬──────────────────────┘
           │                                  │
           └──────────────────┬───────────────┘
                              │
                   ┌──────────▼───────────┐
                   │    PipelineService   │
                   └──────────┬───────────┘
                              │
          ┌───────────────────┼──────────────────────┐
          │                   │                       │
  ┌───────▼────────┐  ┌───────▼───────┐  ┌──────────▼──────────┐
  │ AgentFactory   │  │   EventBus    │  │  SummaryBufferWindow │
  │                │  │               │  │  (3-tier memory)     │
  │ IcpParser      │  │ LoggingObs    │  │  L0 deque (in-proc)  │
  │ IcpRefiner     │  │ MetricsObs    │  │  L1 Redis (gzip)     │
  │ LeadScorer     │  │ ConsoleObs    │  │  L2 Postgres (perm.) │
  │ Research       │  │ WebhookObs    │  └──────────────────────┘
  │ ContactFinder  │  │ SseObserver ──┼──► SSE stream per session
  └───────┬────────┘  │ Prometheus    │
          │           └───────────────┘
  ┌───────▼────────┐
  │   CachedLLM    │  ← decorator wraps any BaseLLM
  │  LLMRespCache  │
  │  L1 LRU dict   │  on cache hit → emits LlmCacheHit event
  │  L2 Redis gzip │
  └───────┬────────┘
          │
  ┌───────▼──────────────────────────────┐
  │  BaseLLM: Ollama / OpenAI / Groq /  │
  │           Together / Anthropic       │
  └──────────────────────────────────────┘

  DiscoveryPipeline  (5 stages, all concurrent)
  QueryPlanner → SearchOrchestrator → Merge → CrawlerFactory → LeadEnricher

  ┌──────────────────────────────────────┐
  │   Celery Workers  (Redis broker)     │
  │   run_pipeline task  max_retries=2   │
  │   Fallback: FastAPI BackgroundTasks  │
  └──────────────────────────────────────┘

  ┌──────────────────────────────────────┐
  │   PostgreSQL  (SQLAlchemy 2.x ORM)   │
  │   Read-replica routing               │
  │   pool_size=20  max_overflow=30      │
  └──────────────────────────────────────┘
```

---

## Design Patterns

| Pattern | Where | Why |
|---|---|---|
| **Observer** | `EventBus`, `LoggingObserver`, `MetricsObserver`, `ConsoleObserver`, `WebhookObserver`, `SseObserver`, `PrometheusObserver` | Decouple monitoring, streaming, and metrics from pipeline logic |
| **Decorator** | `CachedLLM` (wraps `BaseLLM`), `ProxiedCrawler` (wraps `BaseCrawler`) | Inject caching / proxy transparently without changing callers |
| **Factory** | `CrawlerFactory`, `AgentFactory`, `ProxyProviderFactory`, `create_llm()` | Dynamic class instantiation without hard imports |
| **Registry** | `@register_search_engine`, `@register_agent`, `@register_proxy_provider` | Auto-register plugins via decorators |
| **Repository** | `SessionRepository`, `LeadRepository`, `CompanyRepository`, etc. | ORM-backed data access with clean interfaces; write vs read replica routing |
| **Strategy** | `BaseCrawler`, `BaseSearchProvider`, `BaseLLM` | Swap implementations without changing callers |
| **3-tier Cache** | `SummaryBufferWindow` (L0 deque / L1 Redis / L2 Postgres), `LLMResponseCache` (L1 LRU / L2 Redis), `LeadCache` (L1 LRU / L2 Redis) | Zero-latency in-process hot path → durable Redis fallback → permanent store |
| **SSE Bridge** | `SseObserver` | `queue.Queue` + `asyncio.run_in_executor` bridges sync pipeline thread → async HTTP SSE stream |

---

## Project Structure

```
prospector/
├── main.py                         # CLI entrypoint
├── config/
│   └── config.json                 # Central configuration file
│
├── agents/                         # AI agent network
│   ├── base.py                     # BaseAgent ABC + _safe_invoke()
│   ├── factory.py                  # AgentFactory + @register_agent
│   ├── icp_parser.py               # NL query → IcpDiscoveryQuery
│   ├── icp_refiner.py              # Feedback loop: hot leads → refined ICP
│   ├── lead_scorer.py              # EnrichedLead → ScoredLead + tier
│   ├── research.py                 # Deep research on hot leads
│   └── contact_finder.py           # Extract decision-maker contacts
│
├── api/                            # FastAPI REST interface
│   ├── app.py                      # Application factory
│   ├── schemas.py                  # Pydantic request/response models
│   └── routes/
│       ├── health.py               # GET /health
│       ├── runs.py                 # POST /runs, GET /runs/{id}/...
│       └── stream.py               # POST /runs/stream (SSE)
│
├── tasks/                          # Celery distributed tasks
│   ├── celery_app.py               # Celery app (Redis broker + backend)
│   └── pipeline_task.py            # run_pipeline task + direct call path
│
├── discovery/
│   ├── pipeline.py                 # 5-stage orchestration pipeline
│   ├── query_planner.py            # ICP → QueryPlan (multi-signal, 6 types)
│   ├── crawler.py                  # CrawledPage, WebCrawler
│   ├── enricher.py                 # Heuristic scoring & signal extraction
│   ├── crawlers/
│   │   ├── base.py                 # BaseCrawler ABC
│   │   ├── factory.py              # CrawlerFactory
│   │   ├── requests_crawler.py     # Lightweight HTTP crawler
│   │   ├── playwright_crawler.py   # JS-rendering headless browser
│   │   └── proxy_crawler.py        # ProxiedCrawler decorator
│   └── retreivers/
│       ├── base.py                 # BaseSearchProvider + SearchConfig
│       ├── registry.py             # @register_search_engine
│       ├── orchestrator.py         # Fan-out concurrent search
│       ├── models.py               # ProviderResponse, SearchSession
│       ├── serper/                 # Google via Serper.dev
│       ├── tavily/                 # Tavily AI search
│       ├── google/                 # Google Custom Search API
│       ├── bing/                   # Bing Web Search API
│       ├── searchapi/              # SearchAPI.io (multi-engine)
│       ├── yc/                     # Y Combinator company directory
│       ├── wellfound/              # Wellfound / AngelList (Serper-backed)
│       ├── github/                 # GitHub organisation search
│       ├── crunchbase/             # Crunchbase company search
│       ├── producthunt/            # Product Hunt launches
│       ├── linkedin/               # LinkedIn company extractor
│       └── jobboards/
│           ├── greenhouse_search.py  # Greenhouse public board API
│           └── lever_search.py       # Lever public postings API
│
├── common/
│   ├── config.py                   # Pydantic AppConfig + load_config()
│   ├── retry.py                    # @retry decorator + exponential backoff
│   ├── ratelimit.py                # Token-bucket RateLimiterRegistry
│   ├── sanitise.py                 # Query injection guard + 2000-char limit
│   ├── secrets.py                  # KeyRing round-robin API key rotation
│   ├── domain.py                   # Bare domain normalisation
│   ├── email_validator.py          # Email regex + disposable domain blocklist
│   ├── logging_config.py           # JSON (prod) / human-readable (dev) logs
│   ├── llm/
│   │   ├── base.py                 # BaseLLM ABC
│   │   ├── factory.py              # create_llm() — provider router
│   │   ├── cached_llm.py           # CachedLLM decorator (L1 LRU + L2 Redis)
│   │   ├── response_cache.py       # LLMResponseCache (SHA-256 keyed)
│   │   ├── ollama.py               # Ollama (local models)
│   │   ├── openai_compat.py        # OpenAI, Groq, Together, vLLM
│   │   └── anthropic.py            # Anthropic Claude
│   ├── context/
│   │   ├── window.py               # SummaryBufferWindow (3-tier memory)
│   │   └── session_context.py      # Process-wide window singleton registry
│   ├── db/                         # SQLAlchemy 2.x ORM layer
│   │   ├── models.py               # All ORM models
│   │   ├── session.py              # Engine setup, db_session / read_session
│   │   └── repositories/
│   │       ├── base.py             # BaseRepository[T]
│   │       ├── sessions.py         # SessionRepository
│   │       ├── leads.py            # LeadRepository
│   │       ├── companies.py        # CompanyRepository, DecisionMakerRepository
│   │       ├── conversations.py    # ConversationRepository
│   │       └── telemetry.py        # AgentRunRepo, CrawlHistoryRepo, etc.
│   ├── events/
│   │   ├── events.py               # 23 typed frozen event dataclasses
│   │   ├── bus.py                  # Thread-safe EventBus (pub/sub)
│   │   ├── observers.py            # Logging, Metrics, Console, Webhook
│   │   └── sse.py                  # SseObserver — EventBus → async SSE
│   ├── metrics/
│   │   └── prometheus_exporter.py  # PrometheusObserver (counters + histograms)
│   ├── proxy/
│   │   ├── base.py                 # BaseProxyProvider ABC
│   │   ├── static.py               # Round-robin static proxy list
│   │   ├── brightdata.py           # BrightData residential proxies
│   │   ├── smartproxy.py           # SmartProxy residential proxies
│   │   └── factory.py              # ProxyProviderFactory + @register
│   ├── session/
│   │   ├── cache.py                # LeadCache (LRU + Redis connection pool)
│   │   ├── memory.py               # MemoryManager (full-text + summary)
│   │   └── manager.py              # SessionManager + conversation history
│   └── schemas/
│       ├── icp_request.py          # IcpDiscoveryQuery (LLM structured output)
│       └── lead_output.py          # ScoredLead, ContactInfo, DecisionMaker
│
├── services/
│   ├── pipeline_service.py         # PipelineService — transport-agnostic orchestrator
│   └── persistence_service.py      # PersistenceService — ORM writes
│
├── docker/
│   ├── app.Dockerfile
│   └── postgres/init.sql           # Schema DDL
├── docker-compose.yml              # postgres, redis, api, worker, monitoring
├── .github/workflows/
│   ├── ci.yml                      # ruff + mypy + bandit
│   └── release.yml                 # Docker Hub + PyPI publish on tag
├── .env.example
└── pyproject.toml
```

---

## Pipeline Stages

```
IcpDiscoveryQuery
      │
      ▼  Stage 1 — PLAN
   QueryPlanner
   Produces PlannedQuery objects across 6 signal types:
   company_profile · technology_stack · hiring_signals
   outsourcing_signals · business_events · decision_makers
      │
      ▼  Stage 2 — SEARCH  (concurrent, ThreadPoolExecutor)
   SearchOrchestrator
   Fans out each query to all configured providers in parallel.
   Rate-limited per provider (token bucket). Deduplicates by URL.
      │
      ▼  Stage 3 — MERGE
   URL deduplication + priority ranking (prefer_domains first)
   Cap at max_urls_to_crawl (default 50)
      │
      ▼  Stage 4 — CRAWL  (concurrent, cache-aware)
   CrawlerFactory → RequestsCrawler or PlaywrightCrawler
   ProxiedCrawler wraps either → transparent IP rotation + retry
   Cache hits served from LeadCache (Redis + LRU) without network
      │
      ▼  Stage 5 — ENRICH  (heuristic, no LLM)
   LeadEnricher scores each page against ICP:
   · Tech score  (0-1): required techs found / total required
   · Hiring score (0-1): job-role keywords / 5
   · Profile score (0-1): industry + location + size match
   · Composite = 0.40·tech + 0.35·hiring + 0.25·profile
   Leads below min_lead_score (0.15) are dropped
```

After the discovery pipeline, three agent passes run:

```
  LLM SCORING → DEEP RESEARCH (hot leads) → CONTACT FINDING
       ↓
  ICP REFINER  (analyses top-5 HOT leads, injects refined signals
                back into ICP for next query round)
```

---

## Agent Network

| Agent | Model Role | Responsibility |
|---|---|---|
| `IcpParserAgent` | `icp_parser` | Parses NL query → `IcpDiscoveryQuery`. Falls back to keyword extraction on LLM failure. |
| `IcpRefinerAgent` | `icp_refiner` | Analyses top-5 HOT leads; injects common tech + industry signals back as preferred criteria. |
| `LeadScorerAgent` | `lead_scorer` | Assigns Hot/Warm/Cold tier + LLM rationale + outreach copy. Falls back to rule-based tier. |
| `ResearchAgent` | `research` | Synthesises multiple crawled pages into a `CompanyProfile` with pitch angle. |
| `ContactFinderAgent` | `contact_finder` | Combines regex extraction + LLM to identify decision-makers. |

All agents inherit from `BaseAgent`:
- `_safe_invoke()` — guarded LLM call with timeout budget; returns fallback on any error
- `_publish()` — emit typed events to the `EventBus`
- Per-agent `temperature` / `num_predict` overrides via config
- Wrapped by `CachedLLM` (transparent L1 LRU + L2 Redis response cache)

---

## REST API

Start the server:

```bash
uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload
# or via docker compose
docker compose up api
```

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Service health (DB + Redis status) |
| `POST` | `/api/v1/runs` | Submit a run (202 Accepted + session ID) |
| `GET` | `/api/v1/runs/{id}/status` | Poll run status + tier counts |
| `GET` | `/api/v1/runs/{id}/leads` | Fetch scored leads (filter by tier) |
| `POST` | `/api/v1/runs/stream` | **Submit + stream every step live (SSE)** |

### Submit a run

```bash
curl -X POST http://localhost:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{
    "query": "US fintech SaaS 50-500 employees Kubernetes, hiring backend engineers",
    "max_leads": 20,
    "providers": ["serper", "tavily"],
    "no_llm_scoring": false
  }'
# → {"session_id": "abc-123", "status": "queued", "status_url": "...", "leads_url": "..."}
```

Dispatch order:
1. **Celery** (if broker reachable) — distributed, retriable, auto-scaled
2. **BackgroundTasks** (FastAPI in-process fallback)

---

## SSE Live Streaming

`POST /api/v1/runs/stream` runs the full pipeline and streams every step as [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events).

```bash
curl -N -X POST http://localhost:8000/api/v1/runs/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "B2B SaaS companies using React and hiring frontend engineers"}'
```

**Stream output:**
```
data: {"type": "PipelineStarted",   "data": {"session_id": "...", "query": "..."}}
data: {"type": "IcpParsed",         "data": {"confidence": 0.91, "industries": [...]}}
data: {"type": "QueryPlanned",      "data": {"query_count": 8, "signal_types": [...]}}
data: {"type": "SearchStarted",     "data": {"provider": "serper", "query_string": "..."}}
data: {"type": "SearchCompleted",   "data": {"provider": "serper", "result_count": 15, "latency_ms": 210}}
data: {"type": "CrawlCompleted",    "data": {"url": "...", "success": true, "latency_ms": 340}}
data: {"type": "LlmCacheHit",       "data": {"model": "gpt-4o-mini", "agent_role": "icp_parser"}}
data: {"type": "ContextCompressed", "data": {"turns_compacted": 10, "summary_preview": "..."}}
data: {"type": "LeadScored",        "data": {"domain": "acme.com", "tier": "hot", "icp_score": 0.91}}
data: {"type": "PipelineCompleted", "data": {"total_leads": 18, "hot_count": 4}}
data: {"type": "done"}
```

**How it works:**

```
Pipeline thread (sync)          HTTP handler (async)
       │                                │
       │  EventBus.publish(event)       │
       │        │                       │
       │        ▼                       │
       │  SseObserver.handle()          │
       │  queue.Queue.put_nowait()      │
       │                                │
       │                         run_in_executor(queue.get)
       │                                │
       │                         yield "data: {...}\n\n"
       │                                │
       │                         SSE response to client
```

The `X-Session-Id` response header carries the session ID so you can also poll `/runs/{id}/status` after the stream ends.

---

## Celery Distributed Workers

```bash
# Start worker (separate terminal or service)
celery -A tasks.celery_app worker --loglevel=info --concurrency=4

# Scale workers
docker compose up --scale worker=4
```

Configuration in `docker-compose.yml` — the `worker` service reuses the same image as `api`. Celery uses Redis as both broker and result backend.

```python
# tasks/celery_app.py
celery_app = Celery(
    "prospector",
    broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1"),
    backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
)
```

The `run_pipeline` task has `max_retries=2` with 30-second countdown. If Celery is not reachable, the API automatically falls back to `BackgroundTasks`.

---

## LLM Response Cache

Every agent is wrapped in `CachedLLM` — a decorator that adds transparent two-tier response caching without changing any agent code.

```
invoke_structured(prompt, schema)
         │
         ▼
  SHA-256(model + "|" + prompt) → cache key
         │
    L1: in-process LRU dict (zero-latency, up to 256 entries)
         │  hit → deserialize + return   ──► emits LlmCacheHit event
         │  miss ↓
    L2: Redis gzip-compressed JSON (survives process restart)
         │  hit → deserialize + populate L1 + return
         │  miss ↓
    LLM backend call (OpenAI / Groq / Ollama / …)
         │
    Store result in L1 + L2 with agent-specific TTL
```

**TTLs by agent role:**

| Agent | TTL | Rationale |
|---|---|---|
| `icp_parser` | 1 hour | Same query → same ICP |
| `lead_scorer` | 24 hours | Same signals → same score |
| `research` | 24 hours | Domain content doesn't change quickly |
| `contact_finder` | 24 hours | Contacts stable |

Enabled via `session.llm_cache_enabled = true` in config. Cache hits are published as `LlmCacheHit` events, visible in SSE streams and Prometheus metrics.

---

## 3-Tier Hierarchical Memory

`SummaryBufferWindow` implements the same context management strategy used by large-scale LLM agent frameworks — keeping recent turns in fast in-process memory, compressing older turns into a rolling summary, and persisting everything to durable storage.

```
Window add(role, content)
         │
         ▼
  L0: in-process deque  (last max_turns turns, full text, zero-latency)
         │
         │  when total_tokens > max_tokens:
         │  compact oldest chunk_size turns via summarizer_fn (or extractive fallback)
         │  → append to rolling_summary
         │  → emit ContextCompressed event  ──► visible in SSE stream
         │
  L1: Redis  (gzip-compressed JSON of buffer + rolling summary, TTL 24h)
         │   persisted after every add()
         │   loaded on first access (survives process restart)
         │
  L2: PostgreSQL  (ConversationRepository, permanent, never evicted)
```

`get_context(budget_tokens)` builds a context string:
1. Prepend rolling summary (`[Context summary] … [Recent conversation]`)
2. Append recent turns newest-first until `budget_tokens` reached

Configure in `config.json → session`:
```json
{
  "context_max_tokens":  6000,
  "context_max_turns":   40,
  "context_chunk_size":  10
}
```

---

## Search Providers & Linked Sources

### Web Search APIs

| Provider | Env Key | Strength |
|---|---|---|
| **Serper** | `SERPER_API_KEY` | Google results, fast, cheap |
| **Tavily** | `TAVILY_API_KEY` | AI-optimised, returns clean text |
| **Google CSE** | `GOOGLE_API_KEY` + `GOOGLE_CX_KEY` | Official Google |
| **Bing** | `BING_SUBSCRIPTION_KEY` | Microsoft index, different coverage |
| **SearchAPI** | `SEARCHAPI_API_KEY` | Multi-engine aggregator |

### Curated & Niche Sources

| Provider | Env Key | Data |
|---|---|---|
| **Y Combinator** | — (public API) | All YC-backed startups with tags, batch, hiring |
| **Wellfound** | — (Serper-backed) | AngelList / Wellfound startup listings |
| **GitHub** | `GITHUB_TOKEN` (optional) | Tech companies via org search |
| **Crunchbase** | `CRUNCHBASE_API_KEY` | Funding stage, employee count, location |
| **Product Hunt** | — (public API) | Recent product launches |
| **LinkedIn** | — (HTML extractor) | Company page signals |
| **Greenhouse** | — (public board API) | Open engineering roles |
| **Lever** | — (public postings API) | Open engineering roles |

### Adding a New Provider

```python
# discovery/retreivers/mysite/mysite_search.py
from discovery.retreivers.base import BaseSearchProvider, SearchResult
from discovery.retreivers.registry import register_search_engine

@register_search_engine("mysite")
class MySiteSearch(BaseSearchProvider):
    name = "mysite"
    env_key = "MYSITE_API_KEY"

    def search(self) -> list[SearchResult]:
        resp = self._request("GET", "https://api.mysite.com/search", params={"q": self.query})
        return [
            self._build_result(rank=i + 1, title=r["name"], href=r["url"], body=r["snippet"])
            for i, r in enumerate(resp.json().get("results", [])[:self.config.max_results])
        ]
```

Then add the module to `discovery/retreivers/__init__.py`.

---

## LLM Providers

| Provider | Config value | Notes |
|---|---|---|
| **Ollama** | `"ollama"` | Local models (no API key). Default. |
| **OpenAI** | `"openai"` | GPT-4o, GPT-4o-mini. Set `OPENAI_API_KEY`. |
| **Groq** | `"groq"` | Fast inference (llama3, mixtral). Set `GROQ_API_KEY`. |
| **Together AI** | `"together"` | Large open models. Set `TOGETHER_API_KEY`. |
| **Anthropic** | `"anthropic"` | Claude 3 family. Set `ANTHROPIC_API_KEY`. |
| **OpenAI-compatible** | `"openai_compatible"` | vLLM, LM Studio, any OpenAI-compatible server. |

### Per-agent model overrides

```json
"llm": {
  "provider": "groq",
  "models": {
    "icp_parser":     "llama-3.1-8b-instant",
    "lead_scorer":    "llama-3.1-70b-versatile",
    "research":       "llama-3.1-70b-versatile",
    "contact_finder": "llama-3.1-8b-instant"
  },
  "per_agent_overrides": {
    "icp_parser": { "temperature": 0.0, "num_predict": 1024 },
    "research":   { "temperature": 0.2, "num_predict": 4096 }
  }
}
```

---

## Crawlers

| Crawler | Best for |
|---|---|
| `requests` (default) | Fast, low overhead, most sites |
| `playwright` | JavaScript-heavy SPAs (install: `uv sync -E playwright && playwright install chromium`) |

```bash
python main.py "..." --crawler playwright
```

`ProxiedCrawler` wraps any crawler transparently. On `403 / 407 / 429 / 503` or cloudflare/captcha detection → quarantines the IP, rotates, retries.

---

## Proxy Rotation

```json
"proxy": {
  "enabled": true,
  "provider": "brightdata",
  "brightdata": {
    "username": "...",
    "password": "...",
    "country": "us",
    "session_rotation": "per_request"
  }
}
```

`--proxy brightdata` at the CLI. Supported: `static` (round-robin list), `brightdata`, `smartproxy`.

---

## Session Cache

```
Request
  │
  ├─► L1: In-process LRU dict (fast, limited size, lru_maxsize: 1024)
  │
  └─► L2: Redis  (durable, shared across processes)
          Pool size: 20 connections
          socket_timeout: 5s, retry_on_timeout: true

Cached objects
  CrawledPage  → gzip-compressed JSON, TTL 24h
  ScoredLead   → gzip-compressed JSON, TTL 7 days
  Session      → gzip-compressed JSON, TTL 7 days
```

---

## Database (SQLAlchemy ORM)

SQLAlchemy 2.x with the repository pattern. All DB access is typed. `db_session()` routes writes to the primary; `read_session()` routes reads to read replicas.

### ORM Models

| Model | Table | Description |
|---|---|---|
| `SessionModel` | `sessions` | Pipeline run metadata |
| `ConversationMessageModel` | `session_conversations` | Multi-turn chat history |
| `SearchQueryModel` | `search_queries` | Every search query issued |
| `CrawlHistoryModel` | `crawl_history` | Every URL crawled |
| `CompanyModel` | `companies` | Deduplicated company profiles |
| `LeadModel` | `leads` | Per-session scored leads |
| `DecisionMakerModel` | `decision_makers` | Contacts normalised by domain |
| `OutreachSuggestionModel` | `outreach_suggestions` | Generated outreach copy |
| `AgentRunModel` | `agent_runs` | LLM call tracking |
| `PipelineMetricModel` | `pipeline_metrics` | Stage timing & throughput |
| `LinkedSourceResultModel` | `linked_source_results` | YC / GitHub / Crunchbase raw data |

### Repository Usage

```python
import common.db as db

db.init_engine(db_url)  # once at startup

with db.db_session() as session:           # write path (primary)
    repo = db.SessionRepository(session)
    repo.create("my-uuid", "Find US fintech…")
    repo.mark_completed("my-uuid", total_leads=42, hot_count=5)

with db.read_session() as session:         # read path (replica)
    leads = db.LeadRepository(session).list_by_session("my-uuid")
```

---

## Observability

### EventBus — 23 Typed Events

```
PipelineStarted    PipelineCompleted   PipelineFailed
IcpParsed          QueryPlanned
SearchStarted      SearchCompleted
CrawlStarted       CrawlCompleted      CrawlFailed
ProxyAcquired      ProxyRotated        ProxyFailed
LeadEnriched       LeadScored          LeadSkipped
CacheHit           CacheMiss
SessionCreated     SessionResumed      MemoryEvicted
ContextCompressed  LlmCacheHit
```

### Observers

| Observer | What it does |
|---|---|
| `ConsoleObserver` | Emoji-annotated progress to stdout (CLI) |
| `LoggingObserver` | Structured log lines at INFO / DEBUG |
| `MetricsObserver` | Rolling counters + latencies (in-process snapshot) |
| `WebhookObserver` | Async HTTP POST to any endpoint (thread pool) |
| `SseObserver` | Bridges EventBus → async SSE generator per session |
| `PrometheusObserver` | Exports counters + histograms; scraped by Prometheus |

### Custom Observer

```python
from common.events.observers import BaseObserver
from common.events.events import LeadScored

class SlackObserver(BaseObserver):
    def subscribes_to(self):
        return [LeadScored]

    def handle(self, event):
        if event.tier == "hot":
            slack.post(f"🔥 Hot lead: {event.domain} score={event.icp_score:.2f}")

bus.subscribe_all(SlackObserver())
```

### Prometheus + Grafana

```bash
docker compose --profile monitoring up
```

Prometheus: `http://localhost:9090`  
Grafana: `http://localhost:3000` (admin / `$GRAFANA_PASSWORD`)

Tracked metrics: lead tier counters, crawl latency histogram, search latency per provider, LLM cache hit rate.

---

## Configuration Reference

Full path: `config/config.json`

### `llm`

```json
{
  "provider": "ollama",
  "models": {
    "icp_parser":     "qwen2.5:3b",
    "lead_scorer":    "qwen2.5:7b",
    "research":       "qwen2.5:7b",
    "contact_finder": "qwen2.5:3b"
  },
  "per_agent_overrides": {
    "icp_parser": { "temperature": 0.0, "num_predict": 1024 },
    "research":   { "temperature": 0.2, "num_predict": 4096 }
  }
}
```

### `pipeline`

```json
{
  "providers": ["serper", "tavily"],
  "crawler_type": "requests",
  "search_workers": 8,
  "crawl_workers": 15,
  "max_urls_to_crawl": 50,
  "pages_per_domain": 2,
  "signal_paths": ["/", "/about", "/careers", "/technology"]
}
```

### `session`

```json
{
  "redis_url": "redis://localhost:6379/0",
  "redis_pool_size": 20,
  "lru_maxsize": 1024,
  "llm_cache_enabled": true,
  "llm_cache_lru_maxsize": 256,
  "context_max_tokens": 6000,
  "context_max_turns": 40,
  "context_chunk_size": 10
}
```

### `scoring`

```json
{
  "hot_threshold": 0.65,
  "warm_threshold": 0.35,
  "llm_enabled": true,
  "research_hot_leads": true,
  "find_contacts": true,
  "max_concurrent_scorers": 8
}
```

---

## Quick Start — Local

### Prerequisites

- Python 3.12+, [uv](https://github.com/astral-sh/uv)
- [Ollama](https://ollama.ai) (or any supported cloud LLM)
- Redis (optional but strongly recommended)

### Install

```bash
git clone https://github.com/your-org/prospector
cd prospector

uv sync                         # installs all prod deps
uv sync -E playwright           # + Playwright (optional)
playwright install chromium     # download browser
```

### Pull models (Ollama)

```bash
ollama pull qwen2.5:3b    # ICP parser, contact finder
ollama pull qwen2.5:7b    # Lead scorer, research
```

### Configure

```bash
cp .env.example .env
echo "SERPER_API_KEY=your_key" >> .env
```

### CLI

```bash
# Interactive
python main.py

# Direct query
python main.py "US fintech SaaS 50-500 employees Kubernetes hiring backend engineers"

# Advanced
python main.py "B2B SaaS using React" \
  --provider serper --provider yc \
  --format json --output output/leads.json \
  --top 30 --crawler playwright

# Skip LLM (fast, heuristic only)
python main.py "fintech companies" --no-llm-scoring --no-research
```

### API server

```bash
uvicorn api.app:app --port 8000 --reload

# Submit async run
curl -X POST http://localhost:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{"query": "US B2B SaaS companies using Kubernetes"}'

# Stream every step live
curl -N -X POST http://localhost:8000/api/v1/runs/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "US B2B SaaS companies using Kubernetes"}'
```

### Celery worker

```bash
# In a separate terminal
celery -A tasks.celery_app worker --loglevel=info
```

### CLI Flags

| Flag | Description |
|---|---|
| `--config PATH` | Custom config file |
| `--output PATH` | Output file path |
| `--top N` | Number of leads to return |
| `--provider NAME` | Search provider (repeatable) |
| `--crawler TYPE` | `requests` or `playwright` |
| `--proxy PROVIDER` | `brightdata`, `smartproxy`, `static`, `none` |
| `--format json\|csv` | Output format |
| `--session-id ID` | Resume existing session |
| `--no-llm-scoring` | Use rule-based tier only |
| `--no-crawl` | Skip crawl stage |
| `--no-research` | Skip deep research on hot leads |

---

## Docker Compose

```bash
cp .env.example .env   # fill in API keys

# Core services (api + worker + postgres + redis)
docker compose up --build

# Scale workers
docker compose up --scale worker=4

# With monitoring (Prometheus + Grafana)
docker compose --profile monitoring up
```

### Services

| Service | Port | Description |
|---|---|---|
| `api` | 8000 | FastAPI REST server |
| `worker` | — | Celery pipeline worker |
| `redis` | 6379 | Cache + Celery broker/backend |
| `postgres` | 5432 | Persistent lead data |
| `prometheus` | 9090 | Metrics scraper (profile: monitoring) |
| `grafana` | 3000 | Dashboards (profile: monitoring) |

---

## CI / CD

### CI (`.github/workflows/ci.yml`)

Runs on every push to `main` / `dev` and all pull requests:

| Job | Tool | Command |
|---|---|---|
| **Lint** | ruff | `uvx ruff check .` + `uvx ruff format --check .` |
| **Type check** | mypy | `uv sync --group dev && uv run mypy common agents discovery services api` |
| **Security** | bandit | `uvx bandit -r common agents discovery services api -ll` |

`select` / `ignore` are driven by `[tool.ruff.lint]` in `pyproject.toml`; the CI does not pass `--select` on the CLI to avoid bypassing the `ignore` list.

### Release (`.github/workflows/release.yml`)

Triggered on `v*` tags:
1. Builds and pushes Docker image to Docker Hub
2. Publishes Python package to PyPI via `uv build`

---

## Extending the System

### New Search Provider
1. Create `discovery/retreivers/<name>/<name>_search.py`
2. Subclass `BaseSearchProvider`, add `@register_search_engine("<name>")`
3. Implement `search() → list[SearchResult]`
4. Import in `discovery/retreivers/__init__.py`

### New LLM Provider
1. Create `common/llm/<name>.py`
2. Subclass `BaseLLM`, implement `invoke()`, `invoke_structured()`, `model_name`
3. Add a branch in `common/llm/factory.py` and config class in `common/config.py`

### New Agent
1. Create `agents/<name>.py`
2. Subclass `BaseAgent`, add `@register_agent("<name>")`
3. Set `required_model_role` → maps to a model in config
4. Implement `run(**kwargs)` with graceful fallback

### New Observer
1. Subclass `BaseObserver`
2. Implement `subscribes_to()` and `handle(event)`
3. Register: `bus.subscribe_all(MyObserver())`

### New Crawler
1. Create `discovery/crawlers/<name>_crawler.py`
2. Subclass `BaseCrawler`, implement `crawl(url) → CrawledPage`
3. Register in `CrawlerFactory`

### New Proxy Provider
1. Create `common/proxy/<name>.py`
2. Subclass `BaseProxyProvider`, add `@register_proxy_provider("<name>")`
3. Implement `get_proxy() → str`