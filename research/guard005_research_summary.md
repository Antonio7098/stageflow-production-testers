# GUARD-005 Research Summary: Rate Limiting and Abuse Prevention

**Run ID**: run-2026-01-20-001
**Agent**: claude-3.5-sonnet
**Date**: 2026-01-20

---

## Executive Summary

This research document summarizes the industry context, technical approaches, and key considerations for implementing rate limiting and abuse prevention in the Stageflow framework. Rate limiting is a critical defense mechanism for protecting AI pipelines from abuse, DoS attacks, and resource exhaustion. For LLM-powered agents, additional considerations include token-based limiting (TPM), request concurrency limits, and cost-aware rate management.

---

## 1. Industry Context

### 1.1 Why Rate Limiting Matters

Rate limiting is essential for:
- **System Protection**: Preventing overload from burst traffic
- **Fair Resource Allocation**: Ensuring equitable access across users
- **Cost Control**: Managing LLM API costs (tokens are expensive)
- **Abuse Prevention**: Blocking scraping, credential stuffing, prompt attacks
- **Compliance**: Meeting regulatory requirements (e.g., PCI-DSS, HIPAA)

### 1.2 LLM-Specific Concerns

LLM APIs have unique rate limiting requirements:

| Limit Type | Description | Example |
|------------|-------------|---------|
| RPM | Requests per minute | 1,000 RPM |
| TPM | Tokens per minute | 100,000 TPM |
| TPD | Tokens per day | 1,000,000 TPD |
| Concurrent | Parallel requests | 5 concurrent |
| RPD | Requests per day | Variable |

**Reference**: OpenAI rate limits (https://platform.openai.com/docs/guides/rate-limits)

### 1.3 Regulatory Considerations

- **PCI-DSS**: Requires rate limiting on payment endpoints
- **HIPAA**: Audit logging of rate limit violations
- **GDPR**: Rate limiting as a security measure for personal data

---

## 2. Technical Context

### 2.1 Rate Limiting Algorithms

#### Token Bucket
- **Description**: Tokens added at fixed rate, consumed per request
- **Pros**: Allows burst traffic, simple implementation
- **Cons**: Can exceed limits during bursts

```python
class TokenBucket:
    def __init__(self, rate, capacity):
        self.tokens = capacity
        self.rate = rate
        self.last_update = time.time()
    
    def consume(self, tokens=1):
        now = time.time()
        self.tokens = min(self.capacity, 
                         self.tokens + self.rate * (now - self.last_update))
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
```

#### Leaky Bucket
- **Description**: Requests added to queue, processed at fixed rate
- **Pros**: Smooths traffic, predictable output
- **Cons**: Can cause delays for legitimate users

#### Sliding Window Log
- **Description**: Tracks timestamps of all requests in window
- **Pros**: Precise, no edge effects
- **Cons**: High memory usage for high traffic

#### Sliding Window Counter
- **Description**: Combines fixed window with sliding adjustment
- **Pros**: Memory efficient, accurate at window edges
- **Cons**: Slightly more complex

**Reference**: API7.ai Rate Limiting Guide (https://api7.ai/blog/rate-limiting-guide-algorithms-best-practices)

### 2.2 Distributed Rate Limiting

For multi-instance deployments, rate limiting must be distributed:

- **Redis-based**: Uses INCR + EXPIRE for atomic operations
- **Consistent Hashing**: Distributes load across Redis nodes
- **Local + Distributed Hybrid**: Local cache with periodic sync

```python
# Redis-based rate limiter
async def rate_limit_redis(key, limit, window):
    now = time.time()
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, window)
    count = (await pipe.execute())[0]
    return count <= limit
```

**Reference**: Kong Rate Limiting (https://konghq.com/blog/engineering/how-to-design-a-scalable-rate-limiting-algorithm)

### 2.3 Abuse Prevention Techniques

#### Volumetric Abuse Detection
- **Description**: Adaptive rate limiting based on traffic patterns
- **Cloudflare Approach**: Uses sequence learning and variable order Markov chains

**Reference**: Cloudflare API Shield (https://developers.cloudflare.com/api-shield/security/volumetric-abuse-detection)

#### Bot Detection
- **Signals**: Request patterns, header analysis, behavioral analysis
- **Response**: Gradual blocking, CAPTCHA challenges, rate tier reduction

**Reference**: KrakenD Bot Detection (https://www.krakend.io/docs/throttling/botdetector/)

### 2.4 Circuit Breaker Pattern

The circuit breaker pattern complements rate limiting:

| State | Description |
|-------|-------------|
| CLOSED | Normal operation, requests pass through |
| OPEN | Failure threshold exceeded, requests blocked |
| HALF_OPEN | Testing if service recovered |

**Reference**: AWS Circuit Breaker Pattern (https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/circuit-breaker.html)

---

## 3. Stageflow-Specific Considerations

### 3.1 Integration Points

Rate limiting can be implemented at multiple levels in Stageflow:

1. **Interceptor Level** (per-stage)
   - Apply rate limits before stage execution
   - Use `before()` hook for checking

2. **Pipeline Level** (global)
   - Control overall pipeline throughput
   - Coordinate across multiple stages

3. **Context Level** (per-user)
   - Track usage in ContextSnapshot
   - Propagate rate limit state

### 3.2 Relevant Stage Types

- **GUARD stages**: Policy enforcement points
- **INTERCEPTOR hooks**: Request filtering
- **WORK stages**: External API calls (rate limit handling)

### 3.3 Missing Capabilities

Based on research, Stageflow should consider:

1. **RateLimiter StageKind**: First-class rate limiting stage
2. **Distributed Backend**: Redis-based rate limiting support
3. **Adaptive Limiting**: Dynamic rate adjustment based on system load
4. **Abuse Detection**: Pattern analysis for suspicious activity
5. **Cost Tracking**: Token-based limiting with budget awareness

---

## 4. Hypotheses to Test

| # | Hypothesis | Test Approach |
|---|------------|---------------|
| H1 | Token bucket algorithm prevents burst abuse | Generate burst traffic and verify throttling |
| H2 | Sliding window provides smoother limits than fixed window | Compare behavior at window boundaries |
| H3 | Per-user rate limiting prevents resource exhaustion | Simulate multiple users, verify individual limits |
| H4 | Circuit breaker prevents cascade failures | Inject failures and verify isolation |
| H5 | Distributed rate limiting works across instances | Multi-process testing with shared Redis |
| H6 | Adaptive rate limiting responds to load changes | Increase load and verify automatic adjustment |

---

## 5. Success Criteria

1. **Correctness**: Rate limits are enforced accurately (±5% tolerance)
2. **Performance**: Rate limiting adds <1ms overhead at P95
3. **Reliability**: Handles 10,000 concurrent requests without failure
4. **Recoverability**: Rate limit state survives process restarts
5. **Observability**: Rate limit status visible in traces and metrics

---

## 6. Key References

1. API7.ai Rate Limiting Guide: https://api7.ai/blog/rate-limiting-guide-algorithms-best-practices
2. Kong Rate Limiting: https://konghq.com/blog/engineering/how-to-design-a-scalable-rate-limiting-algorithm
3. OpenAI Rate Limits: https://platform.openai.com/docs/guides/rate-limits
4. Cloudflare Volumetric Abuse Detection: https://developers.cloudflare.com/api-shield/security/volumetric-abuse-detection
5. AWS Circuit Breaker Pattern: https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/circuit-breaker.html
6. Azure Circuit Breaker: https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker
7. Zuplo Rate Limiting Best Practices: https://zuplo.com/learning-center/10-best-practices-for-api-rate-limiting-in-2025
8. Resilience4j Circuit Breaker: https://resilience4j.readme.io/docs/circuitbreaker

---

## 7. Implementation Plan

### Phase 1: Core Rate Limiting
- Token bucket implementation
- Fixed window counter
- Sliding window counter

### Phase 2: Advanced Features
- Distributed rate limiting (Redis)
- Circuit breaker integration
- Adaptive rate limiting

### Phase 3: Abuse Prevention
- Pattern analysis
- Bot detection
- Anomaly scoring

### Phase 4: LLM Integration
- Token-based limiting (TPM)
- Cost-aware rate limiting
- Provider fallback on 429

---

*Document generated by Stageflow Stress-Testing Agent*
