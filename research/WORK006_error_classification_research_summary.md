# WORK-006 Research Summary: Permanent vs Transient Error Classification

**Date**: 2026-01-20
**Agent**: Claude 3.5 Sonnet
**Mission**: Stageflow Reliability Engineer - Error Classification Stress Testing

## Executive Summary

This research investigates the classification of errors in Stageflow pipelines, specifically distinguishing between **permanent errors** (failures that won't succeed on retry) and **transient errors** (temporary failures that may succeed on retry). The goal is to stress-test Stageflow's error classification system and identify gaps in handling, detection, and recovery patterns.

## Key Findings from Web Research

### 1. Industry Context

**Current Challenges**:
- LLM APIs experience unpredictable failures including rate limits (429), timeouts (504), and server errors (500/502/503)
- Traditional retry strategies often treat all errors as retryable, leading to "retry storms" and cost overruns
- Missing error classification results in wasted tokens and degraded user experience

**Real-World Impact** (from research):
- OpenAI's 12-day launch event caused significant API uptime issues across providers
- Rate limiting and downtime are "common issues with LLMs in production" (Vellum AI)
- "Stop using 'Retries' as a catch-all for AI Agent reliability" - Carolina Bessega, LinkedIn 2026

### 2. Technical Approaches

**Error Classification Taxonomies Found**:

1. **SHIELDA Framework** (CSIRO Data61, 2025):
   - 36 exception types across 12 agent artifacts
   - Phase-aware classification: Reasoning/Planning vs Execution phases
   - Three orthogonal handling dimensions: local handling, flow control, state recovery
   - Key insight: Exceptions often span multiple phases, requiring cross-phase recovery

2. **Failure Modes in LLM Systems** (Vinay 2025):
   - 15 hidden failure modes including:
     - Multi-step reasoning drift
     - Latent inconsistency
     - Context-boundary degradation
     - Incorrect tool invocation
     - Version drift
     - Cost-driven performance collapse

3. **Google Cloud SRE for LLM Apps** (2025):
   - Four error categories:
     - **Transient**: Timeouts, rate limits, network glitches
     - **Permanent**: Invalid API keys, malformed requests, 4xx errors
     - **Systemic**: Database outages, circuit breaker open, memory exhaustion
     - **Policy**: Content violations, unauthorized actions

### 3. Retry Strategy Best Practices

**From Research**:
- Exponential backoff with jitter for transient errors
- Circuit breaker pattern to prevent cascade failures
- Dead letter queues (DLQ) for permanent failures
- Cost-aware retry limits to prevent budget overruns
- Fallback strategies for degraded but functional operation

**Critical Insight**: "In production, we're realizing that 'stuck' usually falls into different categories - retry isn't a strategy, it's just a waste of tokens" - LinkedIn 2026

## Stageflow-Specific Context

### Stageflow Error Taxonomy (from `stageflow-docs/advanced/errors.md`)

**StageOutput Types**:
1. `StageOutput.ok()` - Success
2. `StageOutput.retry()` - Retryable error (transient)
3. `StageOutput.fail()` - Permanent error
4. `StageOutput.skip()` - Conditional skip
5. `StageOutput.cancel()` - Pipeline cancellation

**Error Categories**:
- **Transient Errors**: Provider timeouts, rate limits, network glitches, temporary service unavailability
- **Permanent Errors**: Invalid API key, malformed request, resource not found, permission denied
- **Logic Errors**: Missing inputs, invalid state transitions, duplicate output keys, type mismatches
- **Systemic Errors**: Database outage, circuit breaker open, memory exhaustion, disk full
- **Policy Errors**: Content policy violation, cross-tenant access, unauthorized action

### Error Codes Reference

| Code | Category | Retryable |
|------|----------|-----------|
| `TIMEOUT` | Transient | Yes |
| `CIRCUIT_OPEN` | Systemic | Yes |
| `RATE_LIMITED` | Transient | Yes |
| `INVALID_INPUT` | Permanent | No |
| `NOT_FOUND` | Permanent | No |
| `UNAUTHORIZED` | Policy | No |
| `UNKNOWN` | Unknown | No |

## Identified Gaps and Hypotheses

### Hypotheses to Test

1. **H1**: Stageflow's `StageOutput.retry()` vs `StageOutput.fail()` distinction is not consistently applied across stage implementations
2. **H2**: Missing error classification heuristics for LLM-specific errors (hallucination vs timeout vs rate limit)
3. **H3**: No automatic retry vs fail decision based on error patterns or provider metadata
4. **H4**: Silent failures occur when transient errors are misclassified as permanent
5. **H5**: Resource waste from retrying permanent errors (cost impact)
6. **H6**: Missing dead letter queue patterns for permanent error handling

### Risk Categories

1. **Classification Risk**: Wrong error classification leads to inappropriate handling
2. **Detection Risk**: Errors are not properly detected or logged
3. **Recovery Risk**: Appropriate recovery actions are not triggered
4. **Observability Risk**: Errors are not visible for debugging and analysis

## Success Criteria

1. ✅ Comprehensive test coverage for all error categories
2. ✅ Silent failure detection for misclassified errors
3. ✅ Cost impact measurement of retry strategies
4. ✅ Provider metadata integration for classification
5. ✅ Recovery pipeline demonstration
6. ✅ DX evaluation of error handling APIs

## Research References

1. SHIELDA: Structured Handling of Exceptions in LLM-Driven Agentic Workflows (arXiv:2508.07935)
2. Failure Modes in LLM Systems: A System-Level Taxonomy (arXiv:2511.19933)
3. Building Bulletproof LLM Applications: Google Cloud SRE Best Practices (2025)
4. Retries, fallbacks, and circuit breakers in LLM apps (Portkey, 2025)
5. Error Recovery in AI Agents: Graceful Degradation and Retry Strategies (Dev.to, 2026)
6. Beyond Retries: Structured Repair for AI Agent Reliability (LinkedIn, 2026)

## Next Steps

1. Create error classification mock data with representative error scenarios
2. Build baseline pipeline with error injection
3. Implement chaos pipeline with error classification testing
4. Execute stress tests for high-volume error scenarios
5. Analyze logs and metrics for classification accuracy
6. Document findings and recommendations

---

*Research completed for Phase 1 of WORK-006 mission*
