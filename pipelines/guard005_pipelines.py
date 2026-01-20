"""
GUARD-005 Test Pipelines: Rate Limiting and Abuse Prevention

This module contains test pipelines for stress-testing rate limiting
and abuse prevention in Stageflow's GUARD stage architecture.

Pipelines:
1. Baseline Pipeline - Normal operation with benign inputs
2. Stress Pipeline - High load, concurrent execution testing
3. Chaos Pipeline - Failure injection and edge cases
4. Adversarial Pipeline - Security and abuse pattern testing
5. Recovery Pipeline - Failure recovery and rollback testing
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from enum import Enum
import hashlib

from stageflow import Pipeline, StageContext, StageKind, StageOutput, StageInputs, PipelineTimer
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow.auth import AuthContext

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


class RateLimitAlgorithm(Enum):
    """Rate limiting algorithm types."""
    TOKEN_BUCKET = "token_bucket"
    LEAKY_BUCKET = "leaky_bucket"
    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW_LOG = "sliding_window_log"
    SLIDING_WINDOW_COUNTER = "sliding_window_counter"


class RateLimitResult(Enum):
    """Result of rate limit check."""
    ALLOWED = "allowed"
    DENIED = "denied"
    THROTTLED = "throttled"


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET
    requests_per_window: int = 60
    window_seconds: int = 60
    burst_size: int = 10
    token_refill_rate: float = 1.0
    token_capacity: int = 100


@dataclass
class RateLimitEntry:
    """Entry for tracking rate limit state."""
    key: str
    count: int
    window_start: float
    tokens: float
    last_access: float


@dataclass
class TestResult:
    """Result of a single test case."""
    test_id: str
    category: str
    description: str
    expected_result: str
    actual_result: str
    passed: bool
    latency_ms: float
    error: Optional[str] = None


@dataclass
class PipelineTestResult:
    """Aggregated results for a test pipeline."""
    pipeline_name: str
    total_tests: int
    passed: int
    failed: int
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    silent_failures: list[str]
    test_results: list[TestResult]
    timestamp: str


class InMemoryRateLimiter:
    """In-memory rate limiter with multiple algorithm support."""

    def __init__(self, config: RateLimitConfig):
        self._config = config
        self._entries: dict[str, RateLimitEntry] = {}
        self._lock = asyncio.Lock()

    def _create_key(self, identifier: str, window_start: float) -> str:
        """Create rate limit key."""
        return f"{identifier}:{int(window_start)}"

    async def check_rate_limit(self, identifier: str) -> tuple[RateLimitResult, dict]:
        """Check and update rate limit for identifier."""
        now = time.time()
        key = self._create_key(now, self._config.window_seconds)

        async with self._lock:
            if key not in self._entries:
                self._entries[key] = RateLimitEntry(
                    key=key,
                    count=0,
                    window_start=now,
                    tokens=self._config.token_capacity,
                    last_access=now,
                )

            entry = self._entries[key]

            if now - entry.window_start > self._config.window_seconds:
                entry = RateLimitEntry(
                    key=key,
                    count=0,
                    window_start=now,
                    tokens=self._config.token_capacity,
                    last_access=now,
                )
                self._entries[key] = entry

            entry.count += 1
            entry.last_access = now

            remaining = self._config.requests_per_window - entry.count

            if entry.count > self._config.requests_per_window:
                return RateLimitResult.DENIED, {
                    "limit": self._config.requests_per_window,
                    "remaining": 0,
                    "reset_after": self._config.window_seconds - (now - entry.window_start),
                    "retry_after": 1,
                }

            return RateLimitResult.ALLOWED, {
                "limit": self._config.requests_per_window,
                "remaining": remaining,
                "reset_after": self._config.window_seconds - (now - entry.window_start),
            }

    def get_stats(self) -> dict:
        """Get limiter statistics."""
        return {
            "active_entries": len(self._entries),
            "config": {
                "algorithm": self._config.algorithm.value,
                "requests_per_window": self._config.requests_per_window,
                "window_seconds": self._config.window_seconds,
            },
        }

    def reset(self):
        """Reset limiter state."""
        self._entries.clear()


class TokenBucketRateLimiter:
    """Token bucket rate limiter implementation."""

    def __init__(self, rate: float, capacity: int, initial_tokens: Optional[int] = None):
        self._rate = rate
        self._capacity = capacity
        self._tokens = initial_tokens if initial_tokens is not None else capacity
        self._last_update = time.time()
        self._lock = asyncio.Lock()

    async def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens."""
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_update
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_update = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def get_remaining(self) -> float:
        """Get remaining tokens."""
        return self._tokens

    def reset(self):
        """Reset limiter state."""
        self._tokens = self._capacity
        self._last_update = time.time()


class SlidingWindowRateLimiter:
    """Sliding window rate limiter implementation."""

    def __init__(self, limit: int, window_seconds: int):
        self._limit = limit
        self._window = window_seconds
        self._timestamps: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> tuple[bool, int]:
        """Check if request is allowed."""
        async with self._lock:
            now = time.time()
            if key not in self._timestamps:
                self._timestamps[key] = []

            window_start = now - self._window
            self._timestamps[key] = [
                ts for ts in self._timestamps[key] if ts > window_start
            ]

            if len(self._timestamps[key]) < self._limit:
                self._timestamps[key].append(now)
                return True, self._limit - len(self._timestamps[key])

            return False, 0

    def reset(self, key: Optional[str] = None):
        """Reset limiter state."""
        if key:
            self._timestamps.pop(key, None)
        else:
            self._timestamps.clear()


class RateLimitGuardStage:
    """GUARD stage that enforces rate limiting."""

    name = "rate_limit_guard"
    kind = StageKind.GUARD

    def __init__(
        self,
        limiter: Optional[InMemoryRateLimiter] = None,
        config: Optional[RateLimitConfig] = None,
        user_identifier_field: str = "user_id",
        ip_identifier_field: str = "ip_address",
    ):
        self._limiter = limiter or InMemoryRateLimiter(config or RateLimitConfig())
        self._user_field = user_identifier_field
        self._ip_field = ip_identifier_field
        self._stats = {
            "checks": 0,
            "allowed": 0,
            "denied": 0,
            "errors": 0,
        }

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute rate limit check."""
        self._stats["checks"] += 1

        try:
            identifier = self._get_identifier(ctx)
            result, rate_info = await self._limiter.check_rate_limit(identifier)

            if result == RateLimitResult.DENIED:
                self._stats["denied"] += 1
                return StageOutput.cancel(
                    reason=f"Rate limit exceeded: {rate_info.get('retry_after', 1)}s",
                    data={
                        "rate_limited": True,
                        "limit": rate_info.get("limit"),
                        "remaining": rate_info.get("remaining", 0),
                        "retry_after": rate_info.get("retry_after", 1),
                        "reset_after": rate_info.get("reset_after", 0),
                        "identifier": identifier,
                    },
                )

            self._stats["allowed"] += 1
            return StageOutput.ok(
                rate_limited=False,
                limit=rate_info.get("limit"),
                remaining=rate_info.get("remaining", 0),
                identifier=identifier,
            )

        except Exception as e:
            self._stats["errors"] += 1
            return StageOutput.fail(
                error=f"Rate limit check failed: {e}",
                data={"error_type": type(e).__name__},
            )

    def _get_identifier(self, ctx: StageContext) -> str:
        """Get unique identifier for rate limiting."""
        snapshot = ctx.snapshot

        user_id = getattr(snapshot, self._user_field, None)
        if user_id:
            return f"user:{user_id}"

        extensions = snapshot.extensions or {}
        ip_address = extensions.get(self._ip_field)
        if ip_address:
            return f"ip:{ip_address}"

        pipeline_id = str(snapshot.pipeline_run_id or uuid.uuid4())
        return f"anonymous:{pipeline_id[:8]}"

    def get_stats(self) -> dict:
        """Get stage statistics."""
        return self._stats

    def get_limiter_stats(self) -> dict:
        """Get limiter statistics."""
        return self._limiter.get_stats()


class AdaptiveRateLimiter:
    """Adaptive rate limiter that adjusts based on system load."""

    def __init__(self, base_limit: int, window_seconds: int):
        self._base_limit = base_limit
        self._window = window_seconds
        self._current_limit = base_limit
        self._load_factor = 1.0
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> tuple[bool, int]:
        """Check if request is allowed based on adaptive limits."""
        async with self._lock:
            now = time.time()
            window_start = now - self._window
            self._timestamps = [ts for ts in self._timestamps if ts > window_start]

            effective_limit = int(self._base_limit * self._load_factor)

            if len(self._timestamps) < effective_limit:
                self._timestamps.append(now)
                remaining = effective_limit - len(self._timestamps)
                return True, remaining

            return False, 0

    def update_load_factor(self, factor: float):
        """Update load factor for adaptive rate limiting."""
        self._load_factor = max(0.1, min(2.0, factor))

    def reset(self):
        """Reset limiter state."""
        self._timestamps.clear()
        self._load_factor = 1.0


class TokenTrackingStage:
    """Stage that tracks LLM token usage for rate limiting."""

    name = "token_tracker"
    kind = StageKind.GUARD

    def __init__(self, tpm_limit: int = 100000, tpd_limit: int = 1000000):
        self._tpm_limit = tpm_limit
        self._tpd_limit = tpd_limit
        self._token_usage: dict[str, list[tuple[float, int]]] = {}
        self._lock = asyncio.Lock()

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Track token usage and check limits."""
        user_id = str(ctx.snapshot.user_id or "anonymous")
        input_text = ctx.snapshot.input_text or ""
        input_tokens = len(input_text) // 4

        async with self._lock:
            now = time.time()

            if user_id not in self._token_usage:
                self._token_usage[user_id] = []

            minute_window = now - 60
            day_window = now - 86400

            self._token_usage[user_id] = [
                (ts, tokens) for ts, tokens in self._token_usage[user_id]
                if ts > minute_window or ts > day_window
            ]

            minute_tokens = sum(
                tokens for ts, tokens in self._token_usage[user_id] if ts > minute_window
            )
            day_tokens = sum(
                tokens for ts, tokens in self._token_usage[user_id] if ts > day_window
            )

            minute_remaining = self._tpm_limit - minute_tokens
            day_remaining = self._tpd_limit - day_tokens

            if minute_tokens > self._tpm_limit:
                return StageOutput.cancel(
                    reason="Token per minute limit exceeded",
                    data={
                        "token_limited": True,
                        "limit_type": "tpm",
                        "limit": self._tpm_limit,
                        "used": minute_tokens,
                        "remaining": minute_remaining,
                        "retry_after": 60,
                    },
                )

            if day_tokens > self._tpd_limit:
                return StageOutput.cancel(
                    reason="Token per day limit exceeded",
                    data={
                        "token_limited": True,
                        "limit_type": "tpd",
                        "limit": self._tpd_limit,
                        "used": day_tokens,
                        "remaining": day_remaining,
                        "retry_after": 86400,
                    },
                )

            self._token_usage[user_id].append((now, input_tokens))

            return StageOutput.ok(
                token_limited=False,
                tpm_limit=self._tpm_limit,
                tpm_used=minute_tokens,
                tpm_remaining=minute_remaining,
                tpd_limit=self._tpd_limit,
                tpd_used=day_tokens,
                tpd_remaining=day_remaining,
            )

    def get_stats(self) -> dict:
        """Get stage statistics."""
        return {
            "tracked_users": len(self._token_usage),
            "tpm_limit": self._tpm_limit,
            "tpd_limit": self._tpd_limit,
        }


class CircuitBreakerStage:
    """Circuit breaker stage for failure isolation."""

    name = "circuit_breaker"
    kind = StageKind.GUARD

    class CircuitState(Enum):
        CLOSED = "closed"
        OPEN = "open"
        HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        success_threshold: int = 3,
        timeout_seconds: float = 30.0,
    ):
        self._state = self.CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._failure_threshold = failure_threshold
        self._success_threshold = success_threshold
        self._timeout = timeout_seconds
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute circuit breaker check."""
        async with self._lock:
            now = time.time()

            if self._state == self.CircuitState.OPEN:
                if now - self._last_failure_time > self._timeout:
                    self._state = self.CircuitState.HALF_OPEN
                    self._success_count = 0
                    self._failure_count = 0
                else:
                    return StageOutput.cancel(
                        reason="Circuit breaker is open",
                        data={
                            "circuit_open": True,
                            "retry_after": self._timeout - (now - self._last_failure_time),
                        },
                    )

            return StageOutput.ok(circuit_closed=True)

    def record_failure(self):
        """Record a failure for circuit breaker."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._failure_count >= self._failure_threshold:
            self._state = self.CircuitState.OPEN

    def record_success(self):
        """Record a success for circuit breaker."""
        self._success_count += 1

        if self._state == self.CircuitState.HALF_OPEN:
            if self._success_count >= self._success_threshold:
                self._state = self.CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0

    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "failure_threshold": self._failure_threshold,
            "timeout_seconds": self._timeout,
        }

    def reset(self):
        """Reset circuit breaker state."""
        self._state = self.CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None


class MockLLMStage:
    """Mock LLM stage for testing without actual API calls."""

    name = "mock_llm"
    kind = StageKind.TRANSFORM

    def __init__(self, base_latency_ms: float = 10.0, variance_ms: float = 5.0):
        self._base_latency = base_latency_ms
        self._variance = variance_ms
        self._call_count = 0

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute mock LLM call."""
        self._call_count += 1
        input_text = ctx.snapshot.input_text or ""

        latency = self._base_latency + (hash(input_text) % 1000) / 100.0 * self._variance
        await asyncio.sleep(latency / 1000.0)

        response = f"Mock response to: {input_text[:50]}"
        return StageOutput.ok(
            response=response,
            model="mock-llm",
            input_tokens=len(input_text),
            output_tokens=len(response),
            latency_ms=latency,
        )

    def get_stats(self) -> dict:
        """Get stage statistics."""
        return {"calls": self._call_count}


def create_baseline_pipeline() -> Pipeline:
    """Create baseline pipeline for normal operation testing."""
    rate_limit_config = RateLimitConfig(
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        requests_per_window=100,
        window_seconds=60,
        token_capacity=100,
        token_refill_rate=1.67,
    )

    rate_limiter = InMemoryRateLimiter(rate_limit_config)
    rate_limit_stage = RateLimitGuardStage(limiter=rate_limiter)
    llm_stage = MockLLMStage()

    return (
        Pipeline()
        .with_stage("rate_limit", rate_limit_stage, StageKind.GUARD)
        .with_stage("llm", llm_stage, StageKind.TRANSFORM, dependencies=("rate_limit",))
    )


def create_stress_pipeline() -> Pipeline:
    """Create pipeline for high-load stress testing."""
    rate_limit_config = RateLimitConfig(
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW_COUNTER,
        requests_per_window=1000,
        window_seconds=60,
        burst_size=100,
    )

    rate_limiter = InMemoryRateLimiter(rate_limit_config)
    rate_limit_stage = RateLimitGuardStage(limiter=rate_limiter)
    llm_stage = MockLLMStage(base_latency_ms=5.0)

    return (
        Pipeline()
        .with_stage("rate_limit", rate_limit_stage, StageKind.GUARD)
        .with_stage("llm", llm_stage, StageKind.TRANSFORM, dependencies=("rate_limit",))
    )


def create_token_tracking_pipeline() -> Pipeline:
    """Create pipeline for token-based rate limiting."""
    token_tracker = TokenTrackingStage(tpm_limit=5000, tpd_limit=50000)
    llm_stage = MockLLMStage()

    return (
        Pipeline()
        .with_stage("token_tracker", token_tracker, StageKind.GUARD)
        .with_stage("llm", llm_stage, StageKind.TRANSFORM, dependencies=("token_tracker",))
    )


def create_circuit_breaker_pipeline() -> Pipeline:
    """Create pipeline for circuit breaker testing."""
    circuit_breaker = CircuitBreakerStage(
        failure_threshold=3,
        success_threshold=2,
        timeout_seconds=5.0,
    )
    rate_limit_stage = RateLimitGuardStage()
    llm_stage = MockLLMStage()

    return (
        Pipeline()
        .with_stage("circuit_breaker", circuit_breaker, StageKind.GUARD)
        .with_stage("rate_limit", rate_limit_stage, StageKind.GUARD, dependencies=("circuit_breaker",))
        .with_stage("llm", llm_stage, StageKind.TRANSFORM, dependencies=("rate_limit",))
    )


def create_adaptive_pipeline() -> Pipeline:
    """Create pipeline for adaptive rate limiting testing."""
    adaptive_limiter = AdaptiveRateLimiter(base_limit=100, window_seconds=60)
    rate_limit_stage = RateLimitGuardStage()
    llm_stage = MockLLMStage()

    return (
        Pipeline()
        .with_stage("rate_limit", rate_limit_stage, StageKind.GUARD)
        .with_stage("llm", llm_stage, StageKind.TRANSFORM, dependencies=("rate_limit",))
    )


if __name__ == "__main__":
    print("GUARD-005 Rate Limiting Pipelines Module")
    print("Available pipeline creation functions:")
    print("  - create_baseline_pipeline()")
    print("  - create_stress_pipeline()")
    print("  - create_token_tracking_pipeline()")
    print("  - create_circuit_breaker_pipeline()")
    print("  - create_adaptive_pipeline()")
