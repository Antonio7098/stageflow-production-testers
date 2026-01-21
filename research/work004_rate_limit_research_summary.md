# Rate Limit Handling (429 Responses) - Research Summary

## WORK-004: Stageflow Reliability Engineering Mission

**Agent**: Claude 3.5 Sonnet  
**Date**: 2026-01-20  
**Priority**: P1  
**Risk**: High

---

## 1. Executive Summary

Rate limiting is a critical reliability concern for LLM-powered applications, particularly when using high-throughput providers like Groq. This research establishes the foundation for stress-testing Stageflow's rate limit handling capabilities, focusing on HTTP 429 responses and their proper management within the Stageflow orchestration framework.

**Key Findings:**
- Rate limits apply at organization level (not per-user) for most LLM providers
- Exponential backoff with jitter is the industry-standard retry strategy
- Proper 429 handling requires respecting `Retry-After` headers
- Silent failures in rate limit handling can cascade into system-wide issues
- Circuit breaker patterns should complement rate limit handling

---

## 2. Industry Context

### 2.1 LLM Provider Rate Limits

| Provider | Rate Limit Types | Typical Limits | Retry Strategy |
|----------|------------------|----------------|----------------|
| **Groq** | RPM + TPM per model | Free tier: 30 RPM, 14K TPM | Exponential backoff |
| **OpenAI** | RPM + TPM + RPD | Tier-based (varies) | Retry-After header |
| **Anthropic** | TPM + RPD | Tier-based | Exponential backoff |

**Groq-Specific Context:**
- Rate limits apply at organization level, not individual users
- Limits vary by model (Llama 3.1 8B has different limits than larger models)
- Tier-based progression from Free → Dev → Enterprise
- 429 errors should trigger exponential backoff implementation

### 2.2 Rate Limit Error Anatomy

```json
{
  "error": {
    "message": "Rate limit exceeded",
    "type": "rate_limit_error",
    "code": 429
  },
  "headers": {
    "Retry-After": "60",
    "X-RateLimit-Limit": "100",
    "X-RateLimit-Remaining": "0",
    "X-RateLimit-Reset": "1699900000"
  }
}
```

---

## 3. Technical Context

### 3.1 Retry Strategies

#### Exponential Backoff with Jitter
```python
import asyncio
import random

async def retry_with_backoff(attempt: int, base_delay: float = 1.0) -> float:
    """Calculate delay with exponential backoff and jitter."""
    delay = base_delay * (2 ** attempt)
    jitter = random.uniform(0, delay * 0.1)  # 0-10% jitter
    return delay + jitter
```

**Key Principles:**
- Start with base delay (1 second recommended)
- Double delay on each attempt (exponential)
- Add random jitter to prevent thundering herd
- Cap maximum delay (60 seconds typical)
- Respect Retry-After header when available

#### Circuit Breaker Pattern
```
CLOSED → (failure_threshold exceeded) → OPEN → (timeout) → HALF_OPEN → (success) → CLOSED
                                                                   → (failure) → OPEN
```

**Benefits:**
- Prevents cascading failures
- Allows services to recover
- Fails fast when downstream is unhealthy

### 3.2 Rate Limiting Algorithms

| Algorithm | Description | Use Case |
|-----------|-------------|----------|
| **Token Bucket** | Tokens added at fixed rate, consumed per request | Burst tolerance |
| **Leaky Bucket** | Fixed-rate processing queue | Smoothing traffic |
| **Sliding Window** | Rolling time window counts | Fine-grained limits |
| **Fixed Window** | Count per time period | Simple enforcement |

### 3.3 HTTP 429 Response Handling

**Required Actions:**
1. Parse `Retry-After` header (seconds until reset)
2. Extract rate limit metadata (limit, remaining, reset)
3. Implement backoff strategy
4. Log rate limit events for observability
5. Consider circuit breaker integration

---

## 4. Stageflow-Specific Context

### 4.1 Existing Interceptor Support

Stageflow provides built-in interceptor infrastructure for cross-cutting concerns:

```python
from stageflow import BaseInterceptor, InterceptorResult, ErrorAction

class RateLimitInterceptor(BaseInterceptor):
    name = "rate_limit"
    priority = 15  # After circuit breaker, before tracing
```

**Relevant Built-in Interceptors:**
- `CircuitBreakerInterceptor` - Prevents cascading failures
- `TimeoutInterceptor` - Enforces per-stage timeouts
- `LoggingInterceptor` - Structured logging

### 4.2 Error Handling Integration

From `stageflow-docs/advanced/errors.md`:
- **Transient Errors**: Rate limits are classified as transient
- **Retry Action**: `StageOutput.retry()` signals retryable failures
- **Error Codes**: `RATE_LIMITED` code indicates retryable error

### 4.3 StageOutput Patterns for Rate Limits

```python
from stageflow import StageOutput

async def execute(self, ctx) -> StageOutput:
    try:
        result = await self.llm_client.chat(messages)
        return StageOutput.ok(result=result)
    except RateLimitError as e:
        retry_after = e.retry_after_ms or 1000
        return StageOutput.retry(
            error="Rate limited, please retry",
            data={"retry_after_ms": retry_after, "retryable": True}
        )
```

---

## 5. Best Practices from Industry

### 5.1 OpenAI Rate Limit Guidelines

From OpenAI's official documentation:
1. Implement exponential backoff with jitter
2. Start with 1-second base delay
3. Maximum 5-10 retry attempts
4. Handle both HTTP 429 and explicit rate limit errors
5. Use request queuing for parallel processing

### 5.2 Google Cloud IAM Retry Strategy

- Idempotent operations: Safe to retry
- Non-idempotent: Requires careful handling
- Use `Retry-After` header when present
- Exponential backoff with 1-32 second base delays

### 5.3 AI Gateway Patterns

Modern AI gateways implement:
- Token-based rate limiting per model/user
- Automatic fallback to backup providers
- Request queuing and prioritization
- Comprehensive observability

---

## 6. Hypotheses to Test

### H1: Rate Limit Detection
**Hypothesis**: Stageflow correctly identifies and classifies 429 responses as transient errors.

**Test**: Inject 429 responses from mock LLM provider and verify error classification.

### H2: Retry Behavior
**Hypothesis**: Stages implementing retry logic handle rate limits gracefully.

**Test**: Configure retry with exponential backoff and verify eventual success.

### H3: Circuit Breaker Integration
**Hypothesis**: Circuit breaker prevents cascading failures during extended rate limiting.

**Test**: Simulate sustained rate limits and verify circuit breaker state transitions.

### H4: Silent Failure Detection
**Hypothesis**: Rate limit handling does not silently drop requests.

**Test**: Verify all requests are either completed or properly failed with error propagation.

### H5: Concurrent Request Handling
**Hypothesis**: Multiple concurrent rate-limited requests are handled correctly.

**Test**: Simulate burst of requests that exceed rate limits and verify graceful handling.

---

## 7. Success Criteria

| Criterion | Metric | Target |
|-----------|--------|--------|
| **Detection Accuracy** | 429 responses correctly identified | 100% |
| **Retry Success Rate** | Requests eventually succeed after backoff | >95% |
| **Error Propagation** | Failures correctly reported to pipeline | 100% |
| **Latency Impact** | P95 latency under rate limit conditions | <5s |
| **Resource Efficiency** | No resource leaks during sustained rate limits | Zero leaks |
| **Silent Failures** | All failures detected and logged | Zero silent failures |

---

## 8. References

### Web Sources
1. Groq Community - Rate Limit Handling: https://community.groq.com/t/how-do-i-handle-rate-limits/482
2. OpenAI Rate Limits Documentation: https://platform.openai.com/docs/guides/rate-limits
3. OpenAI Cookbook - Handling Rate Limits: https://cookbook.openai.com/examples/how_to_handle_rate_limits
4. Anthropic Rate Limits: https://docs.anthropic.com/en/api/rate-limits
5. Postman Blog - HTTP 429: https://blog.postman.com/http-error-429/
6. Google Cloud Retry Strategy: https://docs.cloud.google.com/iam/docs/retry-strategy
7. Orq.ai - AI Gateway Retries: https://docs.orq.ai/docs/ai-gateway-retries

### Stageflow Documentation
1. Interceptors Guide: `stageflow-docs/guides/interceptors.md`
2. Error Handling: `stageflow-docs/advanced/errors.md`
3. Core Types: `stageflow-docs/api/core.md`
4. Mission Brief: `docs/roadmap/mission-brief.md`

### Code References
1. Python asyncio retries: https://dev-kit.io/blog/python/python-asyncio-retries-rate-limited
2. Tenacity retry library: https://tenacity.readthedocs.io/
3. Resilience4j patterns: https://resilience4j.readme.io/

---

## 9. Document Version

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-20 | Initial research summary |

---

*Generated for Stageflow Reliability Engineering Mission - WORK-004*
