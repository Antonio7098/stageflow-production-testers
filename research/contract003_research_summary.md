# CONTRACT-003 Research Summary: Partial Output Handling on Stage Failure

**Run ID**: contract003-2026-01-19-001
**Agent**: claude-3.5-sonnet
**Date**: 2026-01-19
**Focus**: Stage contract enforcement and partial output handling on failure

## Research Objective

Stress-test Stageflow's ability to handle partial outputs when stages fail during pipeline execution. This includes understanding:
- What happens to outputs from already-completed stages when a downstream stage fails
- Whether partial results are accessible after pipeline failure
- The contract enforcement guarantees when stages fail at different points in the DAG

## Key Findings from Web Research

### 1. Industry Patterns for Partial Output Handling

**AWS Step Functions Redrive** ([AWS Blog](https://aws.amazon.com/blogs/compute/introducing-aws-step-functions-redrive-a-new-way-to-restart-workflows/)):
- Allows restarting failed workflow executions from their point of failure
- Skips unnecessary workflow steps, reducing cost of redriving failed workflows
- Distinguishes between "failed" and "completed" states for each step

**Temporal.io Durable Execution** ([Temporal Blog](https://temporal.io/blog/durable-execution-in-distributed-systems-increasing-observability)):
- Automatic checkpointing of workflow state
- Replay capability from last checkpoint
- Activities have built-in support for timeouts and retries
- Distinguishes between different failure types (timeout, cancellation, application error)

**Saga Pattern with Compensations** ([Workflow Core](https://github.com/danielgerlag/workflow-core)):
- Each step has a corresponding compensation action
- On failure, compensations run in reverse order to undo partial work
- Enables distributed transactions across multiple services

**Checkpoint-Based Recovery** ([Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/tutorials/workflows/checkpointing-and-resuming)):
- File-based checkpoint storage for workflow state
- List and resume from specific checkpoints
- Iteration-based checkpoint summaries

### 2. Key Concepts and Terminology

| Term | Description |
|------|-------------|
| **Partial Results** | Outputs from stages that completed before a failure occurred |
| **Checkpoint** | Saved state allowing resumption of execution |
| **Compensation** | Action to undo/rollback previous operations |
| **Durable Execution** | Execution that survives process crashes and restarts |
| **Redrive** | Restarting a failed workflow from its failure point |

### 3. Failure Handling Strategies

**Strategy 1: Stop on First Failure (Fail Fast)**
- Pipeline stops immediately when any stage fails
- No partial results accessible (except for stages that completed before the failure)
- Simple to implement, but may waste work already completed

**Strategy 2: Continue with Fallbacks**
- Failed stages are replaced with fallback values
- Downstream stages continue executing with fallback data
- Requires defining fallbacks for each stage

**Strategy 3: Compensating Transactions (Saga Pattern)**
- On failure, run compensation actions to undo previous steps
- Ensures system consistency but requires implementing compensations
- Common in distributed systems

**Strategy 4: Checkpoint and Resume**
- Periodically save pipeline state to persistent storage
- On failure, resume from last checkpoint
- Minimizes reprocessing but adds complexity

## Stageflow-Specific Context

### From `stageflow-docs/api/pipeline.md`:

**UnifiedPipelineCancelled Exception:**
```python
except UnifiedPipelineCancelled as e:
    print(f"Cancelled by {e.stage}: {e.reason}")
    partial_results = e.results  # Partial results from completed stages
```

**StageExecutionError Exception:**
```python
except StageExecutionError as e:
    print(f"Stage '{e.stage}' failed: {e.original}")
    print(f"Recoverable: {e.recoverable}")
```

**Key Observation:** `UnifiedPipelineCancelled` includes partial results, but `StageExecutionError` does not explicitly mention partial results.

### From `stageflow-docs/guides/pipelines.md`:

**Error Handling Section:**
- When a stage fails, the pipeline stops and raises `StageExecutionError`
- When a stage returns `StageOutput.cancel()`, the pipeline stops gracefully with partial results

### From `stageflow-docs/advanced/errors.md`:

**Partial Results Pattern:**
```python
async def execute(self, ctx: StageContext) -> StageOutput:
    results = []
    errors = []
    
    for item in items:
        try:
            result = await self.process(item)
            results.append(result)
        except Exception as e:
            errors.append({"item": item, "error": str(e)})
    
    # Return partial success
    return StageOutput.ok(
        results=results,
        errors=errors,
        partial=len(errors) > 0,
    )
```

### Key Questions for Stageflow

1. **Contract Enforcement**: When a stage fails, what guarantees exist about partial outputs?
2. **Error Accessibility**: Are partial results accessible in `StageExecutionError`?
3. **Parallel Branch Handling**: What happens when one parallel branch fails?
4. **Cancel vs Fail**: Why does `cancel()` provide partial results but `fail()` may not?
5. **Recovery Mechanism**: Is there a way to resume a failed pipeline from partial state?

## Hypotheses to Test

### H1: Fail() Does Not Preserve Partial Results
**Hypothesis**: When a stage returns `StageOutput.fail()`, the pipeline raises `StageExecutionError` without providing access to partial results from completed stages.

**Test**: Create a pipeline where Stage A completes, then Stage B fails. Verify if partial results from Stage A are accessible.

### H2: Cancel() Preserves Partial Results
**Hypothesis**: When a stage returns `StageOutput.cancel()`, the `UnifiedPipelineCancelled` exception provides access to partial results via `e.results`.

**Test**: Create a pipeline where Stage A completes, then Stage B cancels. Verify that `e.results` contains Stage A's output.

### H3: Parallel Branch Isolation
**Hypothesis**: In a fan-out pattern, if one parallel branch fails, other branches that completed successfully preserve their outputs.

**Test**: Create a diamond pattern where A → [B, C] → D. If B fails after C completes, verify if C's output is preserved.

### H4: Fan-In Dependency Loss
**Hypothesis**: When a fan-in stage depends on multiple stages, failure of any upstream stage prevents the fan-in from running, but completed upstream outputs may still be accessible.

**Test**: Create A → B, A → C → D. If B fails but C completes, verify if D can access C's output (even though D won't run).

### H5: Graceful Degradation Pattern
**Hypothesis**: Stages can implement partial success patterns by returning `StageOutput.ok(partial=True, results=..., errors=...)` to signal partial completion.

**Test**: Create a stage that processes multiple items and returns partial success with errors list.

### H6: Exception Information Loss
**Hypothesis**: `StageExecutionError` lacks a `results` field, making it impossible to determine which stages completed before the failure.

**Test**: Check `StageExecutionError` attributes to confirm presence/absence of partial results.

## Test Scenarios

### Scenario 1: Simple Sequential Failure
```
[A] → [B] → [C]
```
- A completes, B fails
- Expected: Access to A's output after B fails?

### Scenario 2: Parallel Branch Failure
```
      ┌→ [B]
[A] ──┤
      └→ [C]
```
- A completes, B and C run in parallel
- B fails, C completes
- Expected: Access to A and C's outputs after B fails?

### Scenario 3: Diamond Pattern
```
      ┌→ [B] ─┐
[A] ──┤       ├→ [D]
      └→ [C] ─┘
```
- A completes, B and C run in parallel
- B fails, C completes, D won't run
- Expected: Access to A and C's outputs?

### Scenario 4: Fan-In Failure
```
[A] ──┐
[B] ──┼→ [D]
[C] ──┘
```
- A, B, C complete, D runs
- D fails
- Expected: Access to A, B, C outputs?

### Scenario 5: Cancel vs Fail Comparison
```
[A] → [B] → [C]
```
- Compare behavior when B returns `fail()` vs `cancel()`
- Expected: Different exception types, different result accessibility

### Scenario 6: Nested Pipeline Failure
- Test partial output handling in subpipeline scenarios

## Success Criteria

1. All test scenarios execute without crashes
2. Clear documentation of partial result accessibility for each failure type
3. Identification of any silent failures or data loss
4. Recommendations for improving partial output handling
5. Comparison with industry best practices (AWS Step Functions, Temporal.io)

## References

- [AWS Step Functions Redrive](https://aws.amazon.com/blogs/compute/introducing-aws-step-functions-redrive-a-new-way-to-restart-workflows/)
- [Temporal Durable Execution](https://temporal.io/blog/durable-execution-in-distributed-systems-increasing-observability)
- [Temporal Error Handling](https://temporal.io/blog/error-handling-in-distributed-systems)
- [Workflow Core Saga Pattern](https://github.com/danielgerlag/workflow-core)
- [Microsoft Agent Framework Checkpointing](https://learn.microsoft.com/en-us/agent-framework/tutorials/workflows/checkpointing-and-resuming)
- [AWS Step Functions Error Handling](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)
- [Prefect Idempotent Pipelines](https://www.prefect.io/blog/the-importance-of-idempotent-data-pipelines-for-resilience)
