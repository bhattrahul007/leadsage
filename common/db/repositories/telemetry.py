from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common.db.models import AgentRunModel, CrawlHistoryModel, PipelineMetricModel, SearchQueryModel
from common.db.repositories.base import BaseRepository


class AgentRunRepository(BaseRepository[AgentRunModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(AgentRunModel, db)

    def log_run(
        self,
        session_id: str,
        agent_name: str,
        model_name: str | None = None,
        provider: str | None = None,
        latency_ms: float = 0.0,
        success: bool = True,
        fallback_used: bool = False,
        error: str | None = None,
        input_summary: str | None = None,
        output_summary: str | None = None,
        prompt_tokens: int = 0,
        output_tokens: int = 0,
    ) -> AgentRunModel:
        record = AgentRunModel(
            session_id=session_id,
            agent_name=agent_name,
            model_name=model_name,
            provider=provider,
            latency_ms=latency_ms,
            success=success,
            fallback_used=fallback_used,
            error=error,
            input_summary=input_summary,
            output_summary=output_summary,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
        )
        return self.add(record)

    def get_session_stats(self, session_id: str) -> dict:
        stmt = (
            select(
                AgentRunModel.agent_name,
                func.count().label("runs"),
                func.avg(AgentRunModel.latency_ms).label("avg_latency_ms"),
                func.sum(AgentRunModel.prompt_tokens).label("total_prompt_tokens"),
                func.sum(AgentRunModel.output_tokens).label("total_output_tokens"),
            )
            .where(AgentRunModel.session_id == session_id)
            .group_by(AgentRunModel.agent_name)
        )
        rows = self._db.execute(stmt).all()
        return {
            row.agent_name: {
                "runs": row.runs,
                "avg_latency_ms": round(row.avg_latency_ms or 0, 1),
                "total_prompt_tokens": row.total_prompt_tokens or 0,
                "total_output_tokens": row.total_output_tokens or 0,
            }
            for row in rows
        }


class SearchQueryRepository(BaseRepository[SearchQueryModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(SearchQueryModel, db)

    def log_query(
        self,
        session_id: str,
        query_string: str,
        provider: str,
        signal_type: str | None = None,
        search_type: str = "web",
        result_count: int = 0,
        latency_ms: float = 0.0,
        success: bool = True,
        error: str | None = None,
    ) -> SearchQueryModel:
        record = SearchQueryModel(
            session_id=session_id,
            query_string=query_string,
            provider=provider,
            signal_type=signal_type,
            search_type=search_type,
            result_count=result_count,
            latency_ms=latency_ms,
            success=success,
            error=error,
        )
        return self.add(record)


class CrawlHistoryRepository(BaseRepository[CrawlHistoryModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(CrawlHistoryModel, db)

    def log_crawl(
        self,
        session_id: str,
        url: str,
        domain: str | None = None,
        success: bool = True,
        status_code: int | None = None,
        latency_ms: float = 0.0,
        word_count: int = 0,
        from_cache: bool = False,
        crawler_type: str = "requests",
        proxy_used: bool = False,
        proxy_provider: str | None = None,
        error: str | None = None,
    ) -> CrawlHistoryModel:
        record = CrawlHistoryModel(
            session_id=session_id,
            url=url,
            domain=domain,
            success=success,
            status_code=status_code,
            latency_ms=latency_ms,
            word_count=word_count,
            from_cache=from_cache,
            crawler_type=crawler_type,
            proxy_used=proxy_used,
            proxy_provider=proxy_provider,
            error=error,
        )
        return self.add(record)


class PipelineMetricRepository(BaseRepository[PipelineMetricModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(PipelineMetricModel, db)

    def log_stage(
        self,
        session_id: str,
        stage: str,
        items_in: int = 0,
        items_out: int = 0,
        error_count: int = 0,
        latency_ms: float = 0.0,
        cache_hits: int = 0,
        cache_misses: int = 0,
    ) -> PipelineMetricModel:
        record = PipelineMetricModel(
            session_id=session_id,
            stage=stage,
            items_in=items_in,
            items_out=items_out,
            error_count=error_count,
            latency_ms=latency_ms,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
        )
        return self.add(record)
