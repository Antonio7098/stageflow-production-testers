"""
Rate Limit Mock Service for Stageflow Stress-Testing

Provides configurable mock LLM service that simulates rate limiting behavior
for testing Stageflow's rate limit handling capabilities.
"""

import asyncio
import time
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from datetime import datetime


class RateLimitAlgorithm(Enum):
    """Rate limiting algorithm types."""
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"


class RateLimitError(Exception):
    """Exception raised when rate limit is exceeded."""
    
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after_ms: int = 1000,
        limit: int = 0,
        remaining: int = 0,
        reset_at: Optional[datetime] = None,
        algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET
    ):
        self.message = message
        self.retry_after_ms = retry_after_ms
        self.limit = limit
        self.remaining = remaining
        self.reset_at = reset_at or datetime.now()
        self.algorithm = algorithm
        super().__init__(self.message)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting behavior."""
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET
    requests_per_minute: int = 60
    tokens_per_minute: int = 100000
    burst_size: int = 10
    base_delay_ms: int = 1000
    max_retries: int = 5
    jitter_percent: float = 0.1  # 10% jitter
    respect_retry_after: bool = True


@dataclass
class RequestRecord:
    """Record of a request for rate limiting."""
    timestamp: float
    tokens: int
    succeeded: bool
    retry_count: int = 0


@dataclass
class MockLLMResponse:
    """Mock LLM response structure."""
    content: str
    model: str
    provider: str = "groq"
    input_tokens: int = 0
    output_tokens: int = 0
    request_id: str = ""
    latency_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "request_id": self.request_id,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp.isoformat(),
        }


class TokenBucketRateLimiter:
    """Token bucket rate limiter implementation."""
    
    def __init__(self, rate_per_minute: int, burst_size: int):
        self.rate_per_minute = rate_per_minute
        self.burst_size = burst_size
        self.tokens = burst_size
        self.last_update = time.time()
        self._lock = asyncio.Lock()
    
    async def consume(self, tokens: int = 1) -> float:
        """Consume tokens, return wait time if rate limited."""
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            
            # Add tokens based on elapsed time
            tokens_added = elapsed * (self.rate_per_minute / 60)
            self.tokens = min(self.burst_size, self.tokens + tokens_added)
            self.last_update = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return 0.0
            
            # Calculate wait time for required tokens
            needed = tokens - self.tokens
            wait_time = (needed / self.rate_per_minute) * 60
            return wait_time
    
    def get_remaining(self) -> int:
        """Get remaining tokens."""
        return int(self.tokens)
    
    def get_limit(self) -> int:
        """Get maximum tokens (burst size)."""
        return self.burst_size


class SlidingWindowRateLimiter:
    """Sliding window rate limiter implementation."""
    
    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: list[float] = []
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> tuple[bool, float]:
        """Try to acquire a slot. Returns (success, wait_time)."""
        async with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds
            
            # Remove expired requests
            self.requests = [t for t in self.requests if t > cutoff]
            
            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                return True, 0.0
            
            # Calculate wait time until oldest request expires
            wait_time = self.requests[0] - cutoff
            return False, wait_time
    
    def get_remaining(self) -> int:
        """Get remaining requests in window."""
        now = time.time()
        cutoff = now - self.window_seconds
        return max(0, self.max_requests - len([t for t in self.requests if t > cutoff]))
    
    def get_limit(self) -> int:
        """Get maximum requests per window."""
        return self.max_requests


class MockRateLimitedLLMService:
    """
    Mock LLM service with configurable rate limiting.
    
    Simulates Groq API rate limiting behavior for testing Stageflow pipelines.
    """
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()
        self._request_limiter = SlidingWindowRateLimiter(
            max_requests=self.config.requests_per_minute,
            window_seconds=60
        )
        self._token_limiter = TokenBucketRateLimiter(
            rate_per_minute=self.config.tokens_per_minute,
            burst_size=self.config.burst_size * 1000  # Scale for tokens
        )
        self._request_history: list[RequestRecord] = []
        self._total_requests = 0
        self._total_rate_limits = 0
        self._lock = asyncio.Lock()
        
        # Response templates
        self._responses = [
            "The rate limit handling pattern involves exponential backoff.",
            "Implementing circuit breakers prevents cascading failures.",
            "Rate limiting is essential for reliable LLM integrations.",
            "The Retry-After header should guide backoff duration.",
            "Jitter helps prevent thundering herd problems.",
        ]
    
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "llama-3.1-8b-instant",
        max_tokens: int = 100
    ) -> MockLLMResponse:
        """
        Mock chat completion with rate limiting.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model identifier
            max_tokens: Maximum tokens to generate
            
        Returns:
            MockLLMResponse with generated content
            
        Raises:
            RateLimitError: When rate limit is exceeded
        """
        start_time = time.time()
        self._total_requests += 1
        
        # Estimate token usage
        estimated_tokens = sum(len(m.get("content", "")) for m in messages)
        estimated_tokens += max_tokens
        
        # Check rate limits
        async with self._lock:
            request_allowed, request_wait = await self._request_limiter.acquire()
            if not request_allowed:
                self._total_rate_limits += 1
                raise RateLimitError(
                    message=f"Rate limit exceeded: requests per minute",
                    retry_after_ms=int(request_wait * 1000),
                    limit=self._request_limiter.get_limit(),
                    remaining=0,
                    algorithm=self.config.algorithm
                )
        
        token_wait = await self._token_limiter.consume(estimated_tokens)
        if token_wait > 0:
            self._total_rate_limits += 1
            raise RateLimitError(
                message=f"Rate limit exceeded: tokens per minute",
                retry_after_ms=int(token_wait * 1000),
                limit=self._token_limiter.get_limit(),
                remaining=self._token_limiter.get_remaining(),
                algorithm=self.config.algorithm
            )
        
        # Generate mock response
        latency_ms = (time.time() - start_time) * 1000
        content = random.choice(self._responses)
        
        # Record successful request
        async with self._lock:
            self._request_history.append(RequestRecord(
                timestamp=start_time,
                tokens=estimated_tokens,
                succeeded=True,
                retry_count=0
            ))
        
        return MockLLMResponse(
            content=content,
            model=model,
            provider="groq",
            input_tokens=estimated_tokens,
            output_tokens=len(content.split()),
            request_id=f"req_{self._total_requests:08d}",
            latency_ms=latency_ms
        )
    
    async def chat_with_retry(
        self,
        messages: list[dict[str, str]],
        model: str = "llama-3.1-8b-instant",
        max_tokens: int = 100,
        max_retries: Optional[int] = None
    ) -> MockLLMResponse:
        """
        Chat completion with automatic retry on rate limit.
        
        Implements exponential backoff with jitter.
        
        Args:
            messages: List of message dicts
            model: Model identifier
            max_tokens: Maximum tokens to generate
            max_retries: Override for max retry attempts
            
        Returns:
            MockLLMResponse on success
            
        Raises:
            RateLimitError: After max retries exceeded
        """
        max_retries = max_retries or self.config.max_retries
        
        for attempt in range(max_retries + 1):
            try:
                return await self.chat(messages, model, max_tokens)
            except RateLimitError as e:
                if attempt >= max_retries:
                    raise
                
                # Calculate backoff with jitter
                base_delay = self.config.base_delay_ms / 1000
                delay = base_delay * (2 ** attempt)
                jitter = delay * self.config.jitter_percent * random.random()
                wait_time = delay + jitter
                
                # Respect Retry-After if available
                if self.config.respect_retry_after and e.retry_after_ms > 0:
                    wait_time = max(wait_time, e.retry_after_ms / 1000)
                
                await asyncio.sleep(wait_time)
        
        raise RateLimitError("Max retries exceeded")
    
    def get_stats(self) -> dict[str, Any]:
        """Get service statistics."""
        return {
            "total_requests": self._total_requests,
            "total_rate_limits": self._total_rate_limits,
            "rate_limit_ratio": (
                self._total_rate_limits / self._total_requests 
                if self._total_requests > 0 else 0
            ),
            "config": {
                "algorithm": self.config.algorithm.value,
                "rpm": self.config.requests_per_minute,
                "tpm": self.config.tokens_per_minute,
                "burst": self.config.burst_size,
                "base_delay_ms": self.config.base_delay_ms,
            }
        }
    
    def reset_stats(self):
        """Reset service statistics."""
        self._total_requests = 0
        self._total_rate_limits = 0
        self._request_history.clear()


def create_rate_limited_service(
    rpm: int = 60,
    tpm: int = 100000,
    burst: int = 10,
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET
) -> MockRateLimitedLLMService:
    """Factory function to create configured rate-limited service."""
    config = RateLimitConfig(
        algorithm=algorithm,
        requests_per_minute=rpm,
        tokens_per_minute=tpm,
        burst_size=burst,
        base_delay_ms=1000,
        max_retries=5
    )
    return MockRateLimitedLLMService(config)


# Example usage and test
if __name__ == "__main__":
    async def test_service():
        service = create_rate_limited_service(rpm=5, burst=2)
        
        print("Testing rate-limited mock service...")
        print(f"Config: {service.get_stats()['config']}")
        print()
        
        for i in range(10):
            try:
                response = await service.chat([{"role": "user", "content": "Hello"}])
                print(f"Request {i+1}: SUCCESS - '{response.content[:50]}...'")
            except RateLimitError as e:
                print(f"Request {i+1}: RATE LIMITED - retry_after={e.retry_after_ms}ms")
        
        print()
        print(f"Final stats: {service.get_stats()}")
    
    asyncio.run(test_service())
