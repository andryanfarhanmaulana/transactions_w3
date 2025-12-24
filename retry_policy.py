from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Type, TypeVar


LOG = logging.getLogger(__name__)
T = TypeVar("T")
E = TypeVar("E", bound=BaseException)


@dataclass(frozen=True)
class RetryPolicy:
    """Simple configurable retry policy for Web3 transaction operations.

    This utility provides a small, self-contained way to retry transient
    failures such as temporary network issues or nonce mismatches when
    interacting with Web3 providers.

    Example
    -------
    >>> from transactions_w3.retry_policy import RetryPolicy
    >>> policy = RetryPolicy(max_attempts=3, backoff_seconds=1.0)
    >>> result = policy.run(lambda: web3.eth.get_block("latest"))

    The policy is intentionally minimal and independent so it can be used
    across the codebase without introducing new runtime dependencies.
    """

    max_attempts: int = 3
    backoff_seconds: float = 0.5
    max_backoff_seconds: Optional[float] = None
    retry_exceptions: Iterable[Type[BaseException]] = (Exception,)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must be >= 0")
        if self.max_backoff_seconds is not None and self.max_backoff_seconds < 0:
            raise ValueError("max_backoff_seconds must be >= 0 when provided")

    def _should_retry_for(self, exc: BaseException) -> bool:
        """Return True if the exception type is configured as retriable."""

        return any(isinstance(exc, exc_type) for exc_type in self.retry_exceptions)

    def _sleep_for_attempt(self, attempt_index: int) -> None:
        """Sleep using a simple exponential backoff based on the attempt index.

        The first failure sleeps for ``backoff_seconds``, the second for roughly
        ``2 * backoff_seconds``, and so on, up to ``max_backoff_seconds``.
        """

        delay = self.backoff_seconds * (2 ** attempt_index)
        if self.max_backoff_seconds is not None:
            delay = min(delay, self.max_backoff_seconds)

        if delay <= 0:
            return

        LOG.debug("RetryPolicy sleeping for %.3f seconds before next attempt", delay)
        time.sleep(delay)

    def run(self, func: Callable[[], T]) -> T:
        """Execute ``func`` with retries according to the policy.

        Parameters
        ----------
        func:
            Zero-argument callable to execute.

        Returns
        -------
        T
            The value returned by ``func`` on a successful attempt.

        Raises
        ------
        BaseException
            Re-raises the last encountered exception if all attempts fail,
            or immediately raises if the exception is not configured as
            retriable.
        """

        last_exc: Optional[BaseException] = None

        for attempt in range(self.max_attempts):
            try:
                LOG.debug("RetryPolicy attempt %d of %d", attempt + 1, self.max_attempts)
                return func()
            except BaseException as exc:  # noqa: BLE001
                last_exc = exc

                if not self._should_retry_for(exc):
                    LOG.debug(
                        "RetryPolicy not retrying exception of type %s: %s",
                        type(exc).__name__,
                        exc,
                    )
                    raise

                is_last_attempt = attempt == self.max_attempts - 1
                if is_last_attempt:
                    LOG.warning(
                        "RetryPolicy exhausted %d attempts, raising last exception %s: %s",
                        self.max_attempts,
                        type(exc).__name__,
                        exc,
                    )
                    raise

                LOG.info(
                    "RetryPolicy caught retriable exception %s on attempt %d/%d: %s",
                    type(exc).__name__,
                    attempt + 1,
                    self.max_attempts,
                    exc,
                )
                self._sleep_for_attempt(attempt)

        # Defensive: loop always either returns or raises.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("RetryPolicy.run exited without result or exception")


def with_retry(policy: Optional[RetryPolicy] = None) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to apply a :class:`RetryPolicy` to a function.

    If no policy is provided, a default :class:`RetryPolicy` is used.

    Example
    -------
    >>> from web3 import Web3
    >>> from transactions_w3.retry_policy import with_retry, RetryPolicy
    >>>
    >>> policy = RetryPolicy(max_attempts=5, backoff_seconds=0.25)
    >>>
    >>> @with_retry(policy)
    ... def send_raw_transaction(w3: Web3, raw_tx: bytes) -> bytes:
    ...     return w3.eth.send_raw_transaction(raw_tx)
    """

    effective_policy = policy or RetryPolicy()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args, **kwargs) -> T:  # type: ignore[override]
            return effective_policy.run(lambda: func(*args, **kwargs))

        # Help with debugging and logging
        wrapper.__name__ = getattr(func, "__name__", "wrapped_with_retry")
        wrapper.__doc__ = func.__doc__
        wrapper.__qualname__ = getattr(func, "__qualname__", wrapper.__name__)
        return wrapper

    return decorator
