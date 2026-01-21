# WORK-006: Permanent vs Transient Error Classification - Final Report

**Date**: 2026-01-20  
**Agent**: Claude 3.5 Sonnet  
**Roadmap Entry**: WORK-006 - Permanent vs transient error classification  
**Priority**: P1 | **Risk**: High

---

## Executive Summary

This report documents the comprehensive stress-testing of Stageflow's error classification system, specifically focusing on the distinction between permanent errors (failures that won't succeed on retry) and transient errors (temporary failures that may succeed on retry).

**Key Results**:
- **Overall Classification Accuracy**: 85.9% (122/142 errors correctly classified)
- **Silent Failures Detected**: 20 (primarily cost-impact scenarios)
- **Total Cost Impact of Misclassification**: $0.60 (estimated from 60 wasted retries)
- **Critical Finding**: Permanent errors are being retried silently, causing direct cost impact

---

## 1. Research Summary

### 1.1 Industry Context

Research revealed that error classification in AI/LLM systems is a critical challenge:

- **Real-world problem**: LLM APIs experience unpredictable failures including rate limits (429), timeouts (504), and server errors (500/502/503)
- **Cost impact**: Traditional retry strategies treat all errors as retryable, leading to "retry storms" and significant cost overruns
- **Industry trend**: "Stop using 'Retries' as a catch-all for AI Agent reliability" - practitioners are moving toward intelligent, context-aware retry strategies

### 1.2 Stageflow Error Taxonomy

From `stageflow-docs/advanced/errors.md`, Stageflow provides:

| Category | Examples | Retryable |
|----------|----------|-----------|
| **Transient** | Timeouts, rate limits, network glitches | Yes |
| **Permanent** | Invalid API key, malformed request, not found | No |
| **Logic** | Missing inputs, invalid state, type mismatches | No |
| **Systemic** | Database outage, circuit breaker open | Yes (with conditions) |
| **Policy** | Content violations, unauthorized actions | No |

### 1.3 Key Research References

1. **SHIELDA Framework** (CSIRO Data61, 2025): 36 exception types across 12 agent artifacts with phase-aware classification
2. **Failure Modes in LLM Systems** (Vinay 2025): 15 hidden failure modes including reasoning drift and context-boundary degradation
3. **Google Cloud SRE for LLM Apps**: Four-category error taxonomy with retry strategies

---

## 2. Test Results

### 2.1 Test Coverage

| Test | Errors | Correct | Accuracy | Silent Failures | Cost Impact |
|------|--------|---------|----------|-----------------|-------------|
| Transient Classification | 4 | 4 | 100% | 0 | $0.00 |
| Permanent Classification | 4 | 4 | 100% | 0 | $0.00 |
| Stress Test (100 mixed) | 100 | 100 | 100% | 0 | $0.00 |
| Cost Impact Test | 34 | 14 | 41.2% | 20 | $0.60 |
| **Total** | **142** | **122** | **85.9%** | **20** | **$0.60** |

### 2.2 Key Findings

#### Finding 1: Silent Failures in Permanent Error Retries (BUG-077)
**Severity**: High  
**Issue**: When permanent errors are misclassified as transient, the retry mechanism silently consumes resources.

**Reproduction**: In the cost impact test, 20 permanent errors (invalid_api_key, context_length_exceeded) were retried 3 times each, wasting $0.60 in estimated API costs.

**Impact**:
- Direct cost impact from wasted API calls
- Increased latency from unnecessary retry delays
- Obscured debugging due to lack of visibility

**Recommendation**: Implement automatic detection of known permanent error patterns and add circuit breaker for repeated retries.

#### Finding 2: Error Classification Intelligence Enhancement (IMP-106)
**Priority**: P1  
**Issue**: Current error classification relies heavily on HTTP status codes and explicit retryable flags.

**Context**: 20 misclassifications out of 142 errors (85.9% accuracy), primarily in cost impact scenarios.

**Recommendation**: Implement ML-based error classification that considers historical patterns, provider-specific knowledge, and contextual signals beyond HTTP status codes.

#### Finding 3: Error Classification API Discoverability (DX-072)
**Severity**: Medium  
**Issue**: Classification heuristics are distributed across multiple stage implementations.

**Impact**: Developers must implement error classification logic repeatedly, leading to inconsistent handling patterns.

**Recommendation**: Provide a built-in ErrorClassifier utility that can be reused across stages.

#### Strength: StageOutput Error Taxonomy Design (STR-091)
The StageOutput design with explicit status types (ok, fail, retry, skip, cancel) provides a clear foundation for error classification and handling.

---

## 3. Error Classification Analysis

### 3.1 Classification Heuristics

The error classifier uses the following heuristics:

1. **HTTP Status-based Classification**:
   - 429 (Rate Limited) → Transient
   - 401 (Unauthorized) → Permanent
   - 403 (Forbidden) → Policy
   - 404 (Not Found) → Permanent
   - 400 (Bad Request) → Permanent/Policy based on message
   - 500/502/503/504 → Transient

2. **Error Code Overrides**:
   - TIMEOUT, CIRCUIT_OPEN → Transient
   - UNAUTHORIZED, INVALID_REQUEST, NOT_FOUND → Permanent
   - CONTENT_FILTERED → Policy

3. **Confidence Scoring**:
   - Base confidence: 0.5
   - HTTP status present: +0.3
   - Explicit retryable flag: +0.2
   - Error code present: +0.1

### 3.2 Ambiguous Error Cases

The following error types present classification challenges:

| Error | HTTP Status | Confidence | Challenge |
|-------|-------------|------------|-----------|
| "Service temporarily unavailable" | 503 | 0.7 | Could indicate deprecation |
| "Invalid request format" | 400 | 0.7 | Could be client or server issue |
| "Connection failed" | None | 0.4 | No HTTP status to guide classification |
| "Request throttled" | 429 | 0.8 | Could be hard or soft limit |

---

## 4. Cost Impact Analysis

### 4.1 Retry Cost Model

| Error Type | Retries Wasted | Cost per Retry | Total Cost |
|------------|----------------|----------------|------------|
| Permanent as Transient | 3 per error × 20 errors | $0.01 | $0.60 |

### 4.2 Production Impact Projection

If 20% of errors in production are permanent errors misclassified as transient:

- **Daily API calls**: 100,000
- **Misclassified errors**: 20,000
- **Retries per error**: 3
- **Total wasted retries**: 60,000
- **Cost per retry**: $0.01
- **Daily waste**: $600
- **Monthly waste**: $18,000

---

## 5. Recommendations

### 5.1 Immediate Actions

1. **Add Known Permanent Error Patterns**:
   - Implement automatic detection for 401, 403, 404 errors
   - Add explicit handling for INVALID_API_KEY and CONTEXT_LENGTH_EXCEEDED

2. **Circuit Breaker for Retries**:
   - Implement circuit breaker that trips after N repeated retries of similar errors
   - Add visibility into retry decisions through logging and events

3. **Cost-Aware Retry Limits**:
   - Add maximum retry budget per pipeline run
   - Alert when retry costs exceed threshold

### 5.2 Medium-Term Improvements

1. **Provider-Specific Knowledge Base**:
   - Document error patterns for each LLM provider (OpenAI, Anthropic, Groq)
   - Create extensible classification rules

2. **Error Classification Utility**:
   - Provide reusable ErrorClassifier component
   - Include provider-specific heuristics out of the box

3. **Enhanced Observability**:
   - Emit events for error classification decisions
   - Track classification accuracy over time
   - Alert on high misclassification rates

### 5.3 Long-Term Vision

1. **ML-Based Classification**:
   - Train models on historical error patterns
   - Incorporate provider-specific knowledge
   - Adaptive classification based on feedback

2. **Cost-Optimized Retry Strategies**:
   - Model retry costs vs success probability
   - Make optimal retry decisions automatically
   - Balance between reliability and cost

---

## 6. Artifacts Produced

| Artifact | Location | Description |
|----------|----------|-------------|
| Research Summary | `research/WORK006_error_classification_research_summary.md` | Comprehensive research findings |
| Mock Data | `mocks/data/error_classification_mocks.py` | Error scenarios and generators |
| Test Pipelines | `pipelines/error_classification_pipelines.py` | Baseline test pipelines |
| Chaos Pipeline | `pipelines/error_classification_chaos.py` | Chaos engineering tests |
| Test Runner | `run_work006_tests.py` | Main test execution script |
| Results | `results/work006/test_results.json` | Test execution results |

---

## 7. Conclusion

WORK-006 stress-testing revealed both strengths and gaps in Stageflow's error classification system:

**Strengths**:
- Clear StageOutput taxonomy with explicit status types
- Well-documented error code reference table
- Foundation for retry vs fail decisions

**Gaps**:
- Silent failures when permanent errors are retried
- No built-in error classification utility
- Limited provider-specific knowledge
- No cost-aware retry limits

**Overall Assessment**: Stageflow provides a solid foundation for error classification, but production deployments require additional investment in intelligent classification, cost-aware retry strategies, and enhanced observability to prevent silent failures and optimize costs.

---

## References

1. SHIELDA: Structured Handling of Exceptions in LLM-Driven Agentic Workflows (arXiv:2508.07935)
2. Failure Modes in LLM Systems: A System-Level Taxonomy (arXiv:2511.19933)
3. Building Bulletproof LLM Applications: Google Cloud SRE Best Practices (2025)
4. Stageflow Documentation: `stageflow-docs/advanced/errors.md`
5. Stageflow API Reference: `stageflow-docs/api/core.md`
6. Stageflow Interceptors: `stageflow-docs/api/interceptors.md`

---

*Report generated by Stageflow Reliability Engineer Agent*
*Mission: WORK-006 - Permanent vs Transient Error Classification*
