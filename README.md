# AI Lead Generation Agent

A production-grade, multi-agent AI system for B2B lead generation. It converts a plain-English Ideal Customer Profile (ICP) description into a ranked, enriched list of companies with decision-maker contacts, technology signals, and personalised outreach copy.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Architecture Overview](#architecture-overview)
3. [Design Patterns](#design-patterns)
4. [Project Structure](#project-structure)
5. [Pipeline Stages](#pipeline-stages)
6. [Agent Network](#agent-network)
7. [Search Providers & Linked Sources](#search-providers--linked-sources)
8. [LLM Providers](#llm-providers)
9. [Embedding Model](#embedding-model)
10. [Crawlers](#crawlers)
11. [Proxy Rotation](#proxy-rotation)
12. [Caching & Memory](#caching--memory)
13. [Session & Conversation History](#session--conversation-history)
14. [Database (SQLAlchemy ORM)](#database-sqlalchemy-orm)
15. [Observability](#observability)
16. [Configuration Reference](#configuration-reference)
17. [Quick Start — Local](#quick-start--local)
18. [Docker Compose](#docker-compose)
19. [Extending the System](#extending-the-system)
20. [Performance Notes](#performance-notes)

---

## What It Does

```
"Find US fintech SaaS companies with 50-500 employees using Kubernetes,
 actively hiring backend engineers, recently funded — target CTOs"
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        AI Lead Agent                                │
│                                                                     │
│  ICP Parser ─► Query Planner ─► Multi-Engine Search                │
│       ─► Crawl + Cache ─► Enrich ─► Score (LLM) ─► Research       │
│       ─► Contact Finder ─► Output (JSON / CSV)                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  🔥 Stripe.com   [HOT  0.91]  CTO: John Doe  →  "Your K8s migration…"
  🔥 Plaid.com    [HOT  0.87]  CTO: Jane Smith →  "Hiring 12 backend…"
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
┌────────────────────────────────────────────────────────────────────────────┐
│                              main.py  (CLI)                                │
└────────────────────────┬───────────────────────────────────────────────────┘
                         │
           ┌─────────────▼──────────────┐
           │     Common Infrastructure   │
           │  ┌──────────────────────┐   │
           │  │  AppConfig (Pydantic) │   │
           │  └──────────────────────┘   │
           │  ┌──────────────────────┐   │
           │  │  EventBus (Observer) │   │
           │  └──────────────────────┘   │
           │  ┌──────────────────────┐   │
           │  │  LeadCache (Redis+LRU)│  │
           │  └──────────────────────┘   │
           │  ┌──────────────────────┐   │
           │  │  MemoryManager        │  │
           │  └──────────────────────┘   │
           │  ┌──────────────────────┐   │
           │  │  SessionManager       │  │
           │  └──────────────────────┘   │
           │  ┌──────────────────────┐   │
           │  │  SQLAlchemy ORM       │  │
           │  └──────────────────────┘   │
           └─────────────┬──────────────┘
                         │
         ┌───────────────▼───────────────┐
         │        Agent Network           │
         │  ┌─────────────────────────┐  │
         │  │  IcpParserAgent         │  │
         │  │  LeadScorerAgent        │  │
         │  │  ResearchAgent          │  │
         │  │  ContactFinderAgent     │  │
         │  └─────────────────────────┘  │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │        Discovery Pipeline      │
         │  1. QueryPlanner               │
         │  2. SearchOrchestrator         │
         │     ├── Serper / Google / Bing │
         │     ├── Tavily / SearchAPI     │
         │     ├── YC Company Directory  │
         │     ├── GitHub Orgs           │
         │     └── Crunchbase            │
         │  3. Merge & Dedup             │
         │  4. CrawlerFactory            │
         │     ├── RequestsCrawler       │
         │     └── PlaywrightCrawler     │
         │  5. LeadEnricher (heuristic)  │
         └───────────────────────────────┘
```

---

## Design Patterns

| Pattern | Where | Why |
|---|---|---|
| **Observer** | `EventBus`, `LoggingObserver`, `MetricsObserver`, `ConsoleObserver`, `WebhookObserver` | Decouple monitoring from pipeline logic |
| **Factory** | `CrawlerFactory`, `AgentFactory`, `ProxyProviderFactory` | Dynamic class instantiation without hard imports |
| **Registry** | `@register_search_engine`, `@register_agent`, `@register_proxy_provider` | Auto-register plugins via decorators |
| **Decorator** | `ProxiedCrawler` | Wrap any crawler with transparent proxy + retry logic |
| **Repository** | `SessionRepository`, `LeadRepository`, `CompanyRepository`, etc. | ORM-backed data access layer with clean interfaces |
| **Strategy** | `BaseCrawler`, `BaseSearchProvider`, `BaseLLM` | Swap implementations without changing callers |
| **Two-tier Cache** | `LeadCache` (LRU L1 + Redis L2) | Fast in-process cache + durable Redis fallback |

---

## Project Structure

```
llm/
├── main.py                         # CLI entrypoint
├── config/
│   └── config.json                 # Central configuration file
│
├── agents/                         # AI agent network
│   ├── base.py                     # BaseAgent ABC
│   ├── factory.py                  # AgentFactory + @register_agent
│   ├── icp_parser.py               # NL query → IcpDiscoveryQuery
│   ├── lead_scorer.py              # Enriched lead → ScoredLead + tier
│   ├── research.py                 # Deep research on hot leads
│   └── contact_finder.py           # Extract decision-maker contacts
│
├── discovery/
│   ├── pipeline.py                 # 5-stage orchestration pipeline
│   ├── query_planner.py            # ICP → QueryPlan (multi-signal)
│   ├── crawler.py                  # CrawledPage, WebCrawler
│   ├── enricher.py                 # Heuristic scoring & signal extraction
│   ├── crawlers/
│   │   ├── base.py                 # BaseCrawler ABC
│   │   ├── factory.py              # CrawlerFactory
│   │   ├── requests_crawler.py     # Lightweight HTTP crawler
│   │   ├── playwright_crawler.py   # JS-rendering headless browser
│   │   └── proxy_crawler.py        # ProxiedCrawler decorator
│   └── retreivers/
│       ├── base.py                 # BaseSearchProvider ABC + SearchConfig
│       ├── registry.py             # @register_search_engine + get_provider()
│       ├── orchestrator.py         # Fan-out to multiple providers concurrently
│       ├── models.py               # ProviderResponse, SearchSession
│       ├── serper/                 # Google via Serper.dev
│       ├── tavily/                 # Tavily AI search
│       ├── google/                 # Google Custom Search API
│       ├── bing/                   # Bing Web Search API
│       ├── searchapi/              # SearchAPI.io
│       ├── yc/                     # Y Combinator company directory
│       ├── github/                 # GitHub organisation search
│       └── crunchbase/             # Crunchbase company search
│
├── common/
│   ├── config.py                   # Pydantic AppConfig + load_config()
│   ├── retry.py                    # RetryConfig + @retry_with_config
│   ├── llm/
│   │   ├── base.py                 # BaseLLM ABC
│   │   ├── factory.py              # create_llm() — provider router
│   │   ├── ollama.py               # Ollama (local models)
│   │   ├── openai_compat.py        # OpenAI, Groq, Together, vLLM
│   │   └── anthropic.py            # Anthropic Claude
│   ├── db/                         # SQLAlchemy ORM layer
│   │   ├── models.py               # All ORM models
│   │   ├── session.py              # Engine setup, db_session() context manager
│   │   └── repositories/
│   │       ├── sessions.py         # SessionRepository
│   │       ├── leads.py            # LeadRepository
│   │       ├── companies.py        # CompanyRepository, DecisionMakerRepository
│   │       ├── conversations.py    # ConversationRepository
│   │       └── telemetry.py        # AgentRunRepo, CrawlHistoryRepo, etc.
│   ├── events/
│   │   ├── events.py               # 24 typed frozen event dataclasses
│   │   ├── bus.py                  # Thread-safe EventBus
│   │   └── observers.py            # Logging, Metrics, Console, Webhook
│   ├── proxy/
│   │   ├── base.py                 # BaseProxyProvider ABC
│   │   ├── static.py               # Round-robin static proxy list
│   │   ├── brightdata.py           # BrightData residential proxies
│   │   ├── smartproxy.py           # SmartProxy residential proxies
│   │   └── factory.py              # ProxyProviderFactory + @register
│   ├── session/
│   │   ├── cache.py                # LeadCache (LRU + Redis, connection pool)
│   │   ├── memory.py               # MemoryManager (full-text + summary)
│   │   └── manager.py              # SessionManager + conversation history
│   └── schemas/
│       ├── icp_request.py          # IcpDiscoveryQuery schema (LLM output)
│       └── lead_output.py          # ScoredLead, ContactInfo, DecisionMaker
│
├── docker/
│   ├── app.Dockerfile
│   ├── postgres/
│   │   └── init.sql                # Schema: sessions, leads, companies, etc.
│   └── prometheus/
│       └── prometheus.yml
├── docker-compose.yml
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
   Produces up to 30 PlannedQuery objects across 6 signal types:
   company_profile · technology_stack · hiring_signals
   outsourcing_signals · business_events · decision_makers
      │
      ▼  Stage 2 — SEARCH  (concurrent, ThreadPoolExecutor)
   SearchOrchestrator
   Fans out each query to all configured providers in parallel.
   Deduplicates by URL, merges metadata.
      │
      ▼  Stage 3 — MERGE
   URL deduplication + priority ranking (prefer_domains first)
   Cap at max_urls_to_crawl (default 50)
      │
      ▼  Stage 4 — CRAWL  (concurrent, cache-aware)
   CrawlerFactory → RequestsCrawler or PlaywrightCrawler
   ProxiedCrawler wraps either → transparent IP rotation + retry
   Successful pages cached in LeadCache (Redis + LRU) for 24h
      │
      ▼  Stage 5 — ENRICH  (heuristic)
   LeadEnricher scores each page against ICP:
   · Tech score (0-1): required techs found / total required
   · Hiring score (0-1): job-role keywords / 5
   · Profile score (0-1): industry + location + size match
   · Composite = 0.40·tech + 0.35·hiring + 0.25·profile
   Leads below min_lead_score (0.15) are dropped
```

After the pipeline, three agent passes run concurrently:

```
  LLM SCORING  →  DEEP RESEARCH (hot leads)  →  CONTACT FINDING
```

---

## Agent Network

| Agent | Model Role | Responsibility |
|---|---|---|
| `IcpParserAgent` | `icp_parser` | Parses NL query → `IcpDiscoveryQuery`. Falls back to keyword extraction on LLM failure. |
| `LeadScorerAgent` | `lead_scorer` | Assigns Hot/Warm/Cold tier + LLM rationale. Falls back to rule-based tier. |
| `ResearchAgent` | `research` | Synthesises multiple crawled pages into a `CompanyProfile` with pitch angle. |
| `ContactFinderAgent` | `contact_finder` | Combines regex extraction + LLM to identify decision-makers. |

All agents inherit from `BaseAgent` which provides:
- `_safe_invoke()` — guarded LLM call that returns a fallback on any error
- `_publish()` — emit typed events to the `EventBus`
- Agent-specific override of `temperature` / `num_predict` via `per_agent_overrides` in config

---

## Search Providers & Linked Sources

### Web Search APIs (set at least one API key)

| Provider | Key | Strength |
|---|---|---|
| **Serper** | `SERPER_API_KEY` | Google results, fast, cheap |
| **Tavily** | `TAVILY_API_KEY` | AI-optimised, returns clean text |
| **Google CSE** | `GOOGLE_API_KEY` + `GOOGLE_CX_KEY` | Official Google |
| **Bing** | `BING_SUBSCRIPTION_KEY` | Microsoft index, different coverage |
| **SearchAPI** | `SEARCHAPI_API_KEY` | Multi-engine aggregator |

### Linked Sources (curated directories)

| Provider | Key | Data |
|---|---|---|
| **Y Combinator** | None (public API) | All YC-backed startups with tags, batch, hiring status |
| **GitHub** | `GITHUB_TOKEN` (optional) | Tech companies via org search |
| **Crunchbase** | `CRUNCHBASE_API_KEY` | Funding stage, employee count, location |

Enable linked sources in `config.json`:

```json
"pipeline": {
  "linked_sources": {
    "enabled": true,
    "yc":          { "enabled": true,  "max_results": 20 },
    "github":      { "enabled": false, "max_results": 10 },
    "crunchbase":  { "enabled": false, "max_results": 15 }
  }
}
```

### Adding a New Search Provider

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
        items = resp.json().get("results", [])
        return [
            self._build_result(rank=i+1, title=r["name"], href=r["url"], body=r["snippet"])
            for i, r in enumerate(items[:self.config.max_results])
        ]
```

Then add the import to `discovery/retreivers/__init__.py`:

```python
"discovery.retreivers.mysite.mysite_search",
```

---

## LLM Providers

Configure `"provider"` in `config.json` under `"llm"`:

| Provider | Value | Notes |
|---|---|---|
| **Ollama** | `"ollama"` | Local models (no API key). Default. |
| **OpenAI** | `"openai"` | GPT-4o, GPT-4o-mini. Set `OPENAI_API_KEY`. |
| **Groq** | `"groq"` | Fast inference (llama3, mixtral). Set `GROQ_API_KEY`. |
| **Together AI** | `"together"` | Large open models. Set `TOGETHER_API_KEY`. |
| **Anthropic** | `"anthropic"` | Claude 3 family. Set `ANTHROPIC_API_KEY`. |
| **OpenAI-compatible** | `"openai_compatible"` | vLLM, LM Studio, any OpenAI-compatible server. |

### Per-agent model overrides

Each agent can use a different model and generation parameters:

```json
"llm": {
  "provider": "groq",
  "models": {
    "icp_parser":     "llama-3.1-8b-instant",
    "lead_scorer":    "llama-3.1-70b-versatile",
    "research":       "llama-3.1-70b-versatile",
    "contact_finder": "llama-3.1-8b-instant",
    "outreach":       "llama-3.1-70b-versatile"
  },
  "per_agent_overrides": {
    "icp_parser":  { "temperature": 0.0, "num_predict": 1024 },
    "research":    { "temperature": 0.2, "num_predict": 4096 }
  }
}
```

---

## Embedding Model

Used for optional semantic deduplication and memory search.

```json
"embedding": {
  "enabled": true,
  "provider": "ollama",
  "model": "nomic-embed-text",
  "dimensions": 768,
  "cache_embeddings": true,
  "similarity_threshold": 0.8
}
```

Supports `"ollama"` (local) and `"openai"` (`text-embedding-3-small`).

---

## Crawlers

| Crawler | Key | Best for |
|---|---|---|
| `requests` | — | Fast, low overhead, most sites |
| `playwright` | `uv pip install -e ".[playwright]"` then `playwright install chromium` | JavaScript-heavy SPAs |

Switch via `--crawler playwright` or in `config.json`:

```json
"pipeline": { "crawler_type": "playwright" }
```

### ProxiedCrawler (Decorator Pattern)

When a proxy is enabled, `CrawlerFactory.create_with_proxy()` wraps any crawler transparently. The decorator:

1. Intercepts the request
2. Routes it through the active proxy
3. On `403 / 407 / 429 / 503` or cloudflare/captcha strings → quarantines IP, rotates, retries

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

Override at runtime: `--proxy brightdata`

Supported providers: `static` (round-robin list), `brightdata`, `smartproxy`.

---

## Caching & Memory

### Two-tier LeadCache

```
Request
  │
  ├─► L1: In-process LRU dict (fast, limited size)
  │       lru_maxsize: 1024 entries
  │
  └─► L2: Redis (durable, shared across processes)
          Pool size: 20 connections
          socket_timeout: 5s, retry_on_timeout: true

Cached objects
  CrawledPage  →  gzip-compressed JSON, TTL 24h
  ScoredLead   →  gzip-compressed JSON, TTL 7 days
  Session      →  gzip-compressed JSON, TTL 7 days
```

### MemoryManager (long-running sessions)

```
Full-text (heavy)
  L1 LRU: 128 entries in-process (auto-evict old pages)
  L2 Redis: 24h TTL (reload on demand)

Summaries (lightweight, LLM output)
  L1 LRU: 1024 entries in-process
  L2 Redis: 7-day TTL
```

Configure in `config.json` → `session`:

```json
"session": {
  "redis_pool_size":             20,
  "lru_maxsize":                 1024,
  "memory_lru_text_maxsize":     128,
  "memory_lru_summary_maxsize":  1024,
  "crawl_cache_ttl":             86400,
  "lead_cache_ttl":              604800
}
```

---

## Session & Conversation History

Every pipeline run creates a `Session` identified by a UUID. Sessions can be resumed with `--session-id <id>`.

### Conversation history

`SessionManager` tracks multi-turn conversation history (stored in Redis + optionally Postgres):

```python
sess_mgr.add_conversation_turn(session.id, "user", "Find fintech companies in the UK")
sess_mgr.add_conversation_turn(session.id, "assistant", "Parsed ICP: industries=[fintech], locations=[UK]…")

history = sess_mgr.get_conversation_history(session.id, last_n=10)
context = sess_mgr.get_conversation_context(session.id, last_n=10)
```

Config:
```json
"session": {
  "conversation_history_limit": 50,
  "conversation_ttl": 2592000
}
```

---

## Database (SQLAlchemy ORM)

The system uses **SQLAlchemy 2.x** with the repository pattern. All database access goes through typed repository classes — no raw SQL in application code.

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

db.init_engine()  # once at startup

with db.db_session() as session:
    # Sessions
    sess_repo = db.SessionRepository(session)
    record = sess_repo.create("my-uuid", "Find US fintech companies")
    sess_repo.mark_completed("my-uuid", total_leads=42, hot_count=5)

    # Leads
    lead_repo = db.LeadRepository(session)
    lead_repo.upsert("my-uuid", "stripe.com", lead_tier="hot", icp_relevance_score=0.91)

    # Companies
    company_repo = db.CompanyRepository(session)
    company_repo.upsert("stripe.com", company_name="Stripe", is_yc_company=True, yc_batch="S09")

    # Decision makers
    dm_repo = db.DecisionMakerRepository(session)
    dm_repo.upsert("stripe.com", title="CTO", email="cto@stripe.com", confidence=0.9)

    # Conversations
    conv_repo = db.ConversationRepository(session)
    conv_repo.add_message("my-uuid", "user", "Find fintech companies")
    history = conv_repo.get_history("my-uuid", last_n=10)
```

### Setup

The database schema is automatically created by `init_engine()` via `Base.metadata.create_all()`. For production use, generate Alembic migrations:

```bash
alembic init alembic
alembic revision --autogenerate -m "initial"
alembic upgrade head
```

---

## Observability

### EventBus (Observer Pattern)

24 typed, frozen event dataclasses cover every pipeline action:

```
PipelineStarted  QueryPlanned  SearchStarted  SearchCompleted
CrawlStarted     CrawlCompleted  CrawlFailed
ProxyAcquired    ProxyRotated    ProxyFailed
LeadEnriched     LeadScored      LeadSkipped
CacheHit         CacheMiss
SessionCreated   SessionResumed
IcpParsed        MemoryEvicted   PipelineFailed  PipelineCompleted
```

### Built-in Observers

| Observer | What it does |
|---|---|
| `ConsoleObserver` | Emoji-annotated progress to stdout |
| `LoggingObserver` | Structured log lines at INFO / WARNING |
| `MetricsObserver` | In-process rolling counters and latencies |
| `WebhookObserver` | Async HTTP POST to any endpoint |

### Custom Observer

```python
from common.events.bus import EventBus
from common.events.events import LeadScored

class SlackObserver:
    def on_event(self, event):
        if isinstance(event, LeadScored) and event.tier == "hot":
            slack.post(f"🔥 Hot lead: {event.domain} score={event.icp_score:.2f}")

bus.subscribe_all(SlackObserver())
```

### Prometheus + Grafana

```bash
docker compose --profile monitoring up
```

Prometheus: `http://localhost:9090`  
Grafana: `http://localhost:3000` (admin / `$GRAFANA_PASSWORD`)

---

## Configuration Reference

Full path: `config/config.json`

### `llm`

```json
{
  "provider": "ollama",                    // ollama | openai | groq | together | anthropic | openai_compatible
  "models": {
    "icp_parser":     "qwen2.5:3b",        // model per agent role
    "lead_scorer":    "qwen2.5:7b",
    "research":       "qwen2.5:7b",
    "contact_finder": "qwen2.5:3b",
    "outreach":       "qwen2.5:7b",
    "embedder":       "nomic-embed-text"
  },
  "per_agent_overrides": {                 // optional per-agent param overrides
    "icp_parser":  { "temperature": 0.0, "num_predict": 1024 },
    "research":    { "temperature": 0.2, "num_predict": 4096 }
  },
  "ollama":             { "base_url": "http://localhost:11434", "timeout": 120 },
  "openai":             { "api_key_env": "OPENAI_API_KEY", "model": "gpt-4o-mini" },
  "groq":               { "api_key_env": "GROQ_API_KEY" },
  "together":           { "api_key_env": "TOGETHER_API_KEY" },
  "anthropic":          { "api_key_env": "ANTHROPIC_API_KEY", "model": "claude-3-haiku-20240307" }
}
```

### `embedding`

```json
{
  "enabled": false,
  "provider": "ollama",          // ollama | openai
  "model": "nomic-embed-text",
  "dimensions": 768,
  "cache_embeddings": true,
  "similarity_threshold": 0.8
}
```

### `pipeline`

```json
{
  "providers": ["serper", "tavily"],    // empty = all registered
  "crawler_type": "requests",           // requests | playwright
  "search_workers": 8,
  "crawl_workers": 15,
  "max_urls_to_crawl": 50,
  "search_cache_ttl": 3600,
  "linked_sources": {
    "enabled": true,
    "yc":         { "enabled": true,  "max_results": 20 },
    "github":     { "enabled": false, "max_results": 10 },
    "crunchbase": { "enabled": false, "max_results": 15 }
  }
}
```

### `session`

```json
{
  "redis_url": "redis://localhost:6379/0",
  "redis_pool_size": 20,
  "lru_maxsize": 1024,
  "memory_lru_text_maxsize": 128,
  "memory_lru_summary_maxsize": 1024,
  "conversation_history_limit": 50
}
```

---

## Quick Start — Local

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- [Ollama](https://ollama.ai) (or any supported LLM provider)
- Redis (optional but recommended)

### Install

```bash
git clone https://github.com/your-org/lead-agent
cd lead-agent

uv venv && source .venv/bin/activate
uv pip install -e .
# For OpenAI/Groq/Together:
uv pip install -e ".[openai]"
# For Playwright:
uv pip install -e ".[playwright]" && playwright install chromium
```

### Pull a model (Ollama)

```bash
ollama pull qwen2.5:3b    # ICP parser, contact finder
ollama pull qwen2.5:7b    # Lead scorer, research, outreach
```

### Configure

```bash
cp .env.example .env
# Set at least one search provider key
echo "SERPER_API_KEY=your_key" >> .env
```

Or set in `config/config.json` directly.

### Run

```bash
# Interactive mode
python main.py

# With a query
python main.py "US fintech SaaS 50-500 employees Kubernetes hiring backend engineers"

# With specific providers and format
python main.py "B2B SaaS companies using React" \
  --provider serper --provider yc \
  --format json \
  --output output/leads.json \
  --top 30

# Playwright for JS-heavy sites
python main.py "Enterprise companies using Salesforce" --crawler playwright

# Skip LLM scoring (faster, rule-based only)
python main.py "fintech companies" --no-llm-scoring

# Resume a previous session
python main.py --session-id abc123-...
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
cp .env.example .env
# Fill in your API keys in .env

# Build and run (core services)
docker compose up --build

# Run a query
docker compose run --rm app python main.py \
  "US B2B SaaS companies using Kubernetes, hiring engineers"

# With monitoring stack
docker compose --profile monitoring up

# Check Redis
docker compose exec redis redis-cli ping

# Check Postgres
docker compose exec postgres psql -U leads -c "\dt"
```

### Services

| Service | Port | Description |
|---|---|---|
| `redis` | 6379 | Cache + session storage |
| `postgres` | 5432 | Persistent lead data |
| `app` | — | Pipeline runner |
| `prometheus` | 9090 | Metrics scraper (profile: monitoring) |
| `grafana` | 3000 | Dashboards (profile: monitoring) |

### Memory limits

| Service | RAM cap |
|---|---|
| redis | 512 MB (allkeys-lru eviction) |
| postgres | 512 MB |
| app | 2 GB |
| prometheus | 256 MB |
| grafana | 256 MB |

---

## Extending the System

### New Search Provider

1. Create `discovery/retreivers/<name>/<name>_search.py`
2. Subclass `BaseSearchProvider`, add `@register_search_engine("<name>")`
3. Implement `search() -> list[SearchResult]`
4. Add the module path to `discovery/retreivers/__init__.py`

### New LLM Provider

1. Create `common/llm/<name>.py`
2. Subclass `BaseLLM`, implement `invoke()`, `invoke_structured()`, `model_name`
3. Add a branch in `common/llm/factory.py`
4. Add the provider config class in `common/config.py`

### New Agent

1. Create `agents/<name>.py`
2. Subclass `BaseAgent`, add `@register_agent("<name>")`
3. Set `required_model_role` to map to a model in config
4. Implement `run(**kwargs)` with graceful fallback

### New Crawler

1. Create `discovery/crawlers/<name>_crawler.py`
2. Subclass `BaseCrawler`, implement `crawl(url) -> CrawledPage`
3. Register via `CrawlerFactory.register("<type>", MyCrawler)`

### New Proxy Provider

1. Create `common/proxy/<name>.py`
2. Subclass `BaseProxyProvider`, add `@register_proxy_provider("<name>")`
3. Implement `get_proxy() -> str`

---

## Performance Notes

### Response Time

| Stage | Typical latency | Bottleneck |
|---|---|---|
| ICP parsing | 1-3 s | LLM (faster with Groq ~0.3s) |
| Search (5 providers × 5 queries) | 2-5 s | Network, parallel execution |
| Crawl (50 pages, 15 workers) | 5-20 s | Network I/O |
| Enrich | < 1 s | CPU (heuristic) |
| LLM scoring (20 leads, 8 workers) | 10-30 s | LLM |
| Deep research (5 hot leads) | 5-15 s | LLM |
| **Total** | **~30-60 s** | LLM calls |

**Speed-up options:**

- Use **Groq** (`llama-3.1-8b-instant`) for 10–20× faster LLM calls
- Enable Redis cache — repeat queries near-instant
- Use `--no-research` to skip deep research
- Reduce `max_urls_to_crawl` and `max_results_per_query`
- Use `--no-llm-scoring` for pure heuristic scoring

### Recommended configs

**Fast / dev:**
```json
{ "provider": "groq", "pipeline": { "max_urls_to_crawl": 20, "crawl_workers": 10 } }
```

**High quality:**
```json
{ "provider": "openai", "models": { "lead_scorer": "gpt-4o", "research": "gpt-4o" } }
```

**Fully local (no API keys):**
```json
{ "provider": "ollama", "pipeline": { "providers": ["yc"] } }
```