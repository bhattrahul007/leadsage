from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import functools
import logging
import random
import time
from typing import Any, Literal, TypeVar, cast

_F = TypeVar("_F", bound=Callable[..., Any])

logger = logging.getLogger(__name__)

JitterStrategy = Literal["none", "full", "equal"]


def _compute_wait(
    attempt: int,
    backoff: float,
    base: float,
    max_wait: float,
    jitter: JitterStrategy,
) -> float:
    """
    Compute sleep duration before the next attempt.

    Strategies
    ----------
    ``"none"``
        Pure exponential: ``min(max_wait, backoff * base ** attempt)``
    ``"full"``
        Full jitter (AWS recommended): uniform random in ``[0, cap]``
        Maximises spread — best when many clients retry simultaneously.
    ``"equal"``
        Equal jitter: ``cap/2 + uniform(0, cap/2)``
        Guarantees some minimum wait while still spreading load.
    """
    cap = min(max_wait, backoff * (base**attempt))

    if jitter == "full":
        return random.uniform(0.0, cap)
    if jitter == "equal":
        return cap / 2.0 + random.uniform(0.0, cap / 2.0)
    return cap


@dataclass
class RetryState:
    """
    Snapshot of one retry attempt, passed to ``on_retry`` and ``on_exhausted``.

    Attributes
    ----------
    func_name:       Name of the function being retried.
    attempt:         Current 1-indexed attempt number (1 = first retry, not initial call).
    max_attempts:    Total attempts allowed (including the original call).
    last_exception:  The exception that triggered this retry.
    elapsed_ms:      Milliseconds elapsed since the first call.
    next_wait:       Seconds the decorator will sleep before the next attempt.
                     Always 0.0 when passed to ``on_exhausted``.
    """

    func_name: str
    attempt: int
    max_attempts: int
    last_exception: Exception
    elapsed_ms: float
    next_wait: float = 0.0

    @property
    def retries_left(self) -> int:
        """Remaining attempts after this one."""
        return self.max_attempts - self.attempt


@dataclass
class RetryConfig:
    """
    Declarative configuration for the retry decorator.

    Parameters
    ----------
    max_attempts:
        Total number of calls allowed (1 = no retry, 3 = 1 original + 2 retries).
    backoff:
        Multiplier for the exponential wait formula.
        Wait = ``min(max_wait, backoff * base ** retry_index)``.
    base:
        Exponential base (default 2.0 → doubly-exponential).
    max_wait:
        Hard ceiling on any single sleep in seconds.
    jitter:
        Jitter strategy — "none", "full", or "equal".
    exceptions:
        Exception types that trigger a retry. Any other exception propagates
        immediately. Defaults to ``(Exception,)`` — retry everything.
    predicate:
        Optional callable ``(exc) -> bool``. When provided it is AND-combined
        with ``exceptions``: both must match for a retry to occur.
        Use for fine-grained control, e.g. only retry HTTP 5xx not 4xx.
    on_retry:
        Called after each failed attempt before sleeping.
        Receives a ``RetryState`` snapshot.
    on_exhausted:
        Called once when all attempts are exhausted, before re-raising.
        Receives a ``RetryState`` snapshot with ``next_wait=0.0``.
    reraise:
        If True (default), re-raise the last exception when attempts are
        exhausted. If False, return ``None`` instead.
    logger:
        Optional ``logging.Logger`` to use for built-in warning/error messages.
        When None, the module-level logger is used.
    """

    max_attempts: int = 3
    backoff: float = 1.0
    base: float = 2.0
    max_wait: float = 60.0
    jitter: JitterStrategy = "equal"
    exceptions: tuple[type[Exception], ...] = field(default_factory=lambda: (Exception,))
    predicate: Callable[[Exception], bool] | None = None
    on_retry: Callable[[RetryState], None] | None = None
    on_exhausted: Callable[[RetryState], None] | None = None
    reraise: bool = True
    logger: logging.Logger | None = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.backoff <= 0:
            raise ValueError("backoff must be > 0")
        if self.base <= 0:
            raise ValueError("base must be > 0")
        if self.max_wait <= 0:
            raise ValueError("max_wait must be > 0")
        if self.jitter not in ("none", "full", "equal"):
            raise ValueError("jitter must be 'none', 'full', or 'equal'")

    @property
    def _log(self) -> logging.Logger:
        return self.logger or logger


def _should_retry(exc: Exception, cfg: RetryConfig) -> bool:
    """Return True if ``exc`` matches the retry policy."""
    if not isinstance(exc, cfg.exceptions):
        return False
    if cfg.predicate is not None and not cfg.predicate(exc):
        return False
    return True


def _execute_with_retry(func: Callable, cfg: RetryConfig, args, kwargs) -> Any:
    """
    Inner retry loop — separated from the decorator wrapper for testability.
    """
    start = time.perf_counter()
    last_exc: Exception

    for attempt in range(cfg.max_attempts):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc

            if not _should_retry(exc, cfg):
                raise

            retry_number = attempt + 1
            elapsed = (time.perf_counter() - start) * 1000

            if retry_number >= cfg.max_attempts:
                state = RetryState(
                    func_name=func.__name__,
                    attempt=retry_number,
                    max_attempts=cfg.max_attempts,
                    last_exception=exc,
                    elapsed_ms=elapsed,
                    next_wait=0.0,
                )
                if cfg.on_exhausted:
                    cfg.on_exhausted(state)
                cfg._log.error(
                    "[retry] %s exhausted after %d/%d attempts (%.0fms total): %s",
                    func.__name__,
                    retry_number,
                    cfg.max_attempts,
                    elapsed,
                    exc,
                )
                break

            wait = _compute_wait(
                attempt=attempt,
                backoff=cfg.backoff,
                base=cfg.base,
                max_wait=cfg.max_wait,
                jitter=cfg.jitter,
            )
            state = RetryState(
                func_name=func.__name__,
                attempt=retry_number,
                max_attempts=cfg.max_attempts,
                last_exception=exc,
                elapsed_ms=elapsed,
                next_wait=wait,
            )
            if cfg.on_retry:
                cfg.on_retry(state)
            cfg._log.warning(
                "[retry] %s attempt %d/%d failed (%s). Sleeping %.2fs.",
                func.__name__,
                retry_number,
                cfg.max_attempts,
                exc,
                wait,
            )
            time.sleep(wait)

    if cfg.reraise:
        raise last_exc
    return None


def retry(
    _func: _F | None = None,
    *,
    max_attempts: int = 3,
    backoff: float = 1.0,
    base: float = 2.0,
    max_wait: float = 60.0,
    jitter: JitterStrategy = "equal",
    exceptions: Sequence[type[Exception]] | type[Exception] = (Exception,),
    predicate: Callable[[Exception], bool] | None = None,
    on_retry: Callable[[RetryState], None] | None = None,
    on_exhausted: Callable[[RetryState], None] | None = None,
    reraise: bool = True,
    logger: logging.Logger | None = None,
) -> Any:
    """
    Retry decorator with exponential backoff and jitter.

    Can be used as a bare decorator or with keyword arguments:

    ::

        @retry
        def f(): ...

        @retry(max_attempts=5, jitter="full", exceptions=(IOError,))
        def f(): ...

    Parameters
    ----------
    max_attempts:
        Total calls allowed (1 = no retry).
    backoff:
        Base multiplier for exponential wait (seconds).
    base:
        Exponent base. Default 2.0 = wait doubles each retry.
    max_wait:
        Hard cap on any single sleep duration in seconds.
    jitter:
        "none"  — pure exponential (no randomisation)
        "full"  — uniform random in [0, cap] (best for thundering herd)
        "equal" — cap/2 + uniform(0, cap/2) (default, balanced)
    exceptions:
        Exception type(s) to catch and retry. Anything else propagates immediately.
    predicate:
        Additional callable gate: ``(exc) -> bool``. Retry only when True.
        AND-combined with ``exceptions``.
    on_retry:
        Callback invoked after each failed attempt before sleeping.
        Receives a :class:`RetryState` snapshot.
    on_exhausted:
        Callback invoked once when retries are exhausted.
        Receives a :class:`RetryState` snapshot.
    reraise:
        Re-raise the last exception when exhausted (True by default).
        Set False to silently return None instead.
    logger:
        Custom logger instance. Falls back to the module logger.
    """
    exc_tuple: tuple[type[Exception], ...] = (
        (exceptions,) if isinstance(exceptions, type) else tuple(exceptions)
    )
    cfg = RetryConfig(
        max_attempts=max_attempts,
        backoff=backoff,
        base=base,
        max_wait=max_wait,
        jitter=jitter,
        exceptions=exc_tuple,
        predicate=predicate,
        on_retry=on_retry,
        on_exhausted=on_exhausted,
        reraise=reraise,
        logger=logger,
    )

    def decorator(func: _F) -> _F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return _execute_with_retry(func, cfg, args, kwargs)

        setattr(wrapper, "__retry_config__", cfg)
        return cast(_F, wrapper)

    if _func is not None:
        return decorator(_func)
    return decorator


def retry_with_config(cfg: RetryConfig) -> Callable[[_F], _F]:
    """
    Build a retry decorator from a pre-built :class:`RetryConfig`.

    Useful when config is constructed at module level and reused across
    multiple functions:

    ::

        _http_retry = retry_with_config(RetryConfig(
            max_attempts=4,
            jitter="full",
            exceptions=(requests.Timeout, requests.HTTPError),
        ))

        @_http_retry
        def call_provider_a(): ...

        @_http_retry
        def call_provider_b(): ...
    """

    def decorator(func: _F) -> _F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return _execute_with_retry(func, cfg, args, kwargs)

        setattr(wrapper, "__retry_config__", cfg)
        return cast(_F, wrapper)

    return decorator
