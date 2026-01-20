# DAG-009 Research Summary: Stage Timeout and Cancellation Propagation

> **Roadmap Entry**: DAG-009 - Stage timeout and cancellation propagation
> **Priority**: P1
> **Risk Class**: High
> **Research Date**: 2026-01-19
> **Agent**: claude-3.5-sonnet

---

## 1. Industry Context

Stage timeout and cancellation propagation is a critical reliability concern for production AI pipelines. When stages hang, timeout incorrectly, or fail to propagate cancellation signals properly, it can lead to resource leaks, zombie processes, and cascading failures across the entire DAG.

### 1.1 Key Industry Drivers

| Industry | Use Case | Criticality |
|----------|----------|-------------|
| **Finance** | High-frequency fraud detection with strict SLAs (<500ms) | Critical - timeouts must be precise to prevent cascade |
| **Healthcare** | Clinical diagnostic pipelines that must complete or gracefully degrade | Critical - patient safety depends on proper cleanup |
| **Real-time Systems** | Live video/audio processing pipelines | High - latency-sensitive, resource-intensive |
| **Enterprise AI** | Long-running document processing workflows | Medium - cost optimization requires timeout enforcement |

### 1.2 Regulatory Implications

- **SOX Compliance**: Financial pipelines must have audit trails showing all timeouts and cancellations
- **HIPAA**: Healthcare pipelines must properly clean up patient data on cancellation
- **GDPR**: Right-to-be-forgotten requests require proper cleanup of all pipeline state
- **PCI-DSS**: Payment pipelines must have bounded execution times

---

## 2. Technical Context

### 2.1 State of the Art Approaches

#### Python Asyncio Timeout Patterns

Python's asyncio provides several timeout mechanisms:

```python
# Using asyncio.wait_for (Python 3.11+)
async def stage_with_timeout(ctx):
    result = await asyncio.wait_for(
        long_running_operation(ctx),
        timeout=30.0
    )
    return result

# Using asyncio.timeout (Python 3.11+)
async def stage_with_timeout(ctx):
    async with asyncio.timeout(30.0):
        return await long_running_operation(ctx)
```

#### Structured Concurrency (PEP 789)

PEP 789 addresses cancellation propagation issues in async generators:

```python
# Preventing timeout leakage to outer scopes
async def stage_with_cleanup(ctx):
    try:
        async with asyncio.timeout(30.0):
            return await process_with_generator(ctx)
    except TimeoutError:
        await cleanup_partial_work(ctx)
        raise
```

#### Workflow Engine Patterns

Temporal.io cancellation model:
- **Activity Heartbeats**: Activities report progress to prevent premature timeout
- **Cancellation Scopes**: Nested cancellation with proper propagation
- **Deterministic Timeouts**: Wall-time and idle-timeouts with deterministic behavior

### 2.2 Known Failure Modes

| Failure Mode | Description | Impact |
|--------------|-------------|--------|
| **Timeout Leakage** | Timeout from inner operation propagates to outer scope | Pipeline-wide cancellation |
| **Orphaned Tasks** | Cancelled stages leave background tasks running | Resource exhaustion |
| **Silent Failures** | Timeout occurs but error is swallowed | Pipeline hangs indefinitely |
| **Cleanup Failure** | Cancel signal doesn't trigger cleanup code | Data corruption, resource leaks |
| **Race Conditions** | Timeout and completion happen simultaneously | Undefined state |
| **Nested Cancellation** | Cancel signal doesn't propagate to subpipelines | Partial execution, zombie processes |
| **Checkpoint Loss** | Cancelled pipeline loses all checkpoint state | No recovery possible |
| **Timeout Drift** | Multiple stages have inconsistent timeout behavior | Unpredictable pipeline behavior |
| **Stack Overflow** | Deeply nested timeouts cause stack overflow | Process crash |
| **Memory Leak** | Cancelled stages keep references alive | Memory exhaustion |

### 2.3 Academic Research

Key concepts from workflow execution research:

1. **Cancellation Safety**: Ensuring all code paths properly handle cancellation
2. **Timeout Granularity**: Balancing coarse vs fine-grained timeouts
3. **Graceful Degradation**: Continuing partial work after timeout
4. **Resource Cleanup Guarantees**: Using context managers and finally blocks

---

## 3. Stageflow-Specific Context

### 3.1 Current Capabilities

Based on the Stageflow documentation:

1. **TimeoutInterceptor**: Built-in interceptor for per-stage timeouts
   - Default timeout: 30 seconds
   - Configurable via `ctx.data["_timeout_ms"]`
   - Priority: 5 (runs early in interceptor chain)

2. **StageOutput.cancel()**: Graceful cancellation without error
   - Stops the pipeline without raising exception
   - Available for stages that want to cancel execution

3. **PipelineCancellation**: Exception raised when pipeline is cancelled
   - `UnifiedPipelineCancelled` exception with results access

4. **Default Interceptors**: Include timeout handling in the default stack

### 3.2 Known Limitations (From DX Issues)

- **DX-020**: `StageOutput.cancel()` cancels entire pipeline (not just branch)
- No built-in timeout per stagekind (all stages share same timeout config)
- Limited control over timeout behavior (hard timeout vs soft timeout)
- No heartbeat mechanism to prevent premature timeout
- No partial result return on timeout

### 3.3 Relevant Extension Points

- **BaseInterceptor**: Custom timeout implementations
- **Stage.execute()**: Can implement custom timeout logic
- **PipelineContext**: Access to cancellation state

---

## 4. Hypotheses to Test

| # | Hypothesis | Testing Approach |
|---|------------|------------------|
| H1 | TimeoutInterceptor properly cancels stage within configured time | Test with stages that sleep longer than timeout |
| H2 | Cancellation propagates to all parallel branches correctly | Test diamond pattern with cancellation in one branch |
| H3 | Subpipeline cancellation is properly propagated | Test subpipeline spawning with timeout in child |
| H4 | Cleanup handlers are called on timeout | Test cleanup via finally blocks and context managers |
| H5 | Nested timeouts don't cause race conditions | Test deeply nested pipeline timeouts |
| H6 | Timeout during async generator doesn't leak to outer scope | Test stages using async generators with timeouts |
| H7 | Resource cleanup happens on cancellation (files, network) | Test stages with external resources |
| H8 | Partial results are accessible after timeout | Test whether output is available after timeout |
| H9 | Concurrent timeouts don't cause race conditions | Test 50+ parallel stages with individual timeouts |
| H10 | Long-running stage can extend timeout via heartbeat | Test heartbeat pattern to prevent premature timeout |

---

## 5. Success Criteria

### 5.1 Functional Criteria

- [ ] TimeoutInterceptor cancels stage within configured time (+/- 100ms tolerance)
- [ ] Cancellation propagates correctly to all dependent stages
- [ ] Subpipeline timeouts properly cancel child pipelines
- [ ] Cleanup handlers execute on timeout/cancellation
- [ ] Async generator timeouts don't leak to outer scope
- [ ] No resource leaks after cancellation

### 5.2 Performance Criteria

- [ ] Timeout overhead < 1ms for typical stages
- [ ] 1000 concurrent timeouts complete within 5 seconds total
- [ ] No memory growth during timeout stress tests

### 5.3 Reliability Criteria

- [ ] No silent failures during timeout tests
- [ ] Error messages are actionable and include stage name
- [ ] Partial results accessible after timeout
- [ ] No race conditions in concurrent timeout scenarios

---

## 6. Test Scenarios

### 6.1 Baseline Scenarios

1. **Simple Timeout**: Stage exceeds timeout, should be cancelled
2. **No Timeout**: Stage completes before timeout
3. **Exact Timeout**: Stage takes exactly the timeout duration

### 6.2 Propagation Scenarios

1. **Sequential Cancellation**: Stage A times out, Stage B should not run
2. **Parallel Cancellation**: Stage A times out, parallel Stages B,C should be cancelled
3. **Subpipeline Cancellation**: Parent stage times out, child pipeline cancelled
4. **Fan-out/Fan-in Cancellation**: Multiple workers timeout, aggregation handles correctly

### 6.3 Cleanup Scenarios

1. **Resource Cleanup**: File/connection cleanup on timeout
2. **Async Generator Cleanup**: Proper cleanup of async generators
3. **Context Manager Cleanup**: Finally blocks execute correctly

### 6.4 Edge Case Scenarios

1. **Zero Timeout**: Stage immediately times out
2. **Very Long Timeout**: Stage runs much longer than timeout
3. **Concurrent Timeouts**: 100+ stages timeout simultaneously
4. **Timeout During Output**: Timeout happens while writing output
5. **Nested Timeouts**: Inner stage times out while outer stage runs

### 6.5 Chaos Scenarios

1. **Forced Timeout Leakage**: Async generator yields after timeout
2. **Resource Exhaustion**: Many timeouts cause resource exhaustion
3. **Race Condition Injection**: Simultaneous timeout and completion
4. **Slow Cleanup**: Cleanup handler itself times out
5. **Memory Pressure**: Timeout + memory pressure simultaneously

---

## 7. Stageflow API Analysis

### 7.1 TimeoutInterceptor Priority

From interceptors documentation:
- TimeoutInterceptor has priority 5 (runs before circuit breaker, tracing, etc.)
- Lower priority = outer wrapper
- This means timeout applies to entire stage execution including inner interceptors

### 7.2 StageOutput.cancel() Behavior

From DX-020:
- `StageOutput.cancel()` cancels the **entire** pipeline
- Not just the current branch
- No granular branch cancellation

### 7.3 Cancellation State Access

- `ctx.data` contains pipeline state
- No explicit cancellation state exposed to stages
- Cancellation results in `UnifiedPipelineCancelled` exception

---

## 8. References

| # | Source | Relevance |
|---|--------|-----------|
| 1 | PEP 789: Async Generator Cancellation | Understanding timeout leakage |
| 2 | asyncio.timeout documentation | Python timeout patterns |
| 3 | Temporal.io Cancellation | Enterprise cancellation patterns |
| 4 | Stageflow Interceptors Guide | TimeoutInterceptor implementation |
| 5 | Stageflow DX Issues | Known limitations |
| 6 | Airflow Task Timeout | Industry timeout practices |
| 7 | Python Asyncio Best Practices | Task cancellation patterns |

---

## 9. Next Steps

1. Create research summary document
2. Build baseline timeout test pipeline
3. Create propagation test scenarios
4. Build cleanup verification tests
5. Execute chaos and stress tests
6. Log all findings to structured JSON
7. Generate final report with recommendations
