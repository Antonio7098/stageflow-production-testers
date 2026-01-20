---

# CONTRACT-003 - Partial Output Handling on Stage Failure

> **Run ID**: contract003-2026-01-19-001  
> **Agent**: claude-3.5-sonnet  
> **Stageflow Version**: 0.5.1 (installed)  
> **Date**: 2026-01-19  
> **Status**: COMPLETED

---

## Executive Summary

CONTRACT-003 focused on stress-testing Stageflow's ability to handle partial outputs when stages fail during pipeline execution. The testing revealed a fundamental asymmetry in how Stageflow handles partial results between `StageOutput.fail()` and `StageOutput.cancel()` scenarios.

**Key Findings:**
- 2 bugs identified (StageExecutionError lacks partial results, parallel branch output loss)
- 2 DX issues documented (inconsistent partial result handling, missing documentation)
- 2 improvements suggested (checkpoint/resume capability, Saga pattern support)
- 1 strength identified (UnifiedPipelineCancelled correctly preserves partial results)

### Key Metrics

| Metric | Value |
|--------|-------|
| Total Findings | 7 |
| Bugs Found | 2 |
| DX Issues | 2 |
| Improvements | 2 |
| Strengths | 1 |

### Verdict

**RELIABILITY GAP** - Stageflow's partial output handling is inconsistent:
- `StageOutput.cancel()` correctly preserves partial results via `UnifiedPipelineCancelled.results`
- `StageOutput.fail()` via `StageExecutionError` provides NO partial results access
- This creates a reliability gap where work from completed stages is lost on failure

---

## 1. Research Summary

### 1.1 Industry Context

Partial output handling is critical for production pipelines where:

| Industry | Use Case | Impact of Partial Output Loss |
|----------|----------|------------------------------|
| **Finance** | Multi-step trading pipelines | Lost trades, reconciliation issues |
| **Healthcare** | Diagnostic imaging pipelines | Expensive re-scans required |
| **E-Commerce** | Order fulfillment pipelines | Incomplete orders, customer complaints |
| **Data Engineering** | ETL pipelines | Data inconsistency, reprocessing costs |

### 1.2 Technical Context

**Industry Standard Approaches:**
- AWS Step Functions: `redrive` for restarting from failure point
- Temporal.io: Durable execution with automatic checkpointing
- Workflow Core: Saga pattern with compensation actions
- Azure Durable Functions: Event sourcing for replay

**Stageflow Current Behavior:**
- `StageOutput.cancel()` → `UnifiedPipelineCancelled` with `results` dict
- `StageOutput.fail()` → `StageExecutionError` with NO results field

### 1.3 Key Hypotheses Tested

| # | Hypothesis | Status |
|---|------------|--------|
| H1 | `StageExecutionError` lacks partial results | **CONFIRMED** |
| H2 | `UnifiedPipelineCancelled` preserves partial results | **CONFIRMED** |
| H3 | Parallel branch outputs are lost on single branch failure | **CONFIRMED** |
| H4 | Documentation gap exists for partial output handling | **CONFIRMED** |

---

## 2. Findings

### 2.1 Bugs Identified

#### BUG-020: StageExecutionError lacks partial results field

**Type**: Reliability | **Severity**: Medium | **Component**: `StageExecutionError`

**Description**: When a stage fails with `StageOutput.fail()`, the `StageExecutionError` exception does not provide access to partial results from already-completed stages.

**Expected Behavior**: `StageExecutionError` should include a `results` field similar to `UnifiedPipelineCancelled` for consistency.

**Actual Behavior**: `StageExecutionError` only has `stage`, `original`, and `recoverable` attributes - no partial results.

**Impact**: Developers cannot recover partial pipeline state after failures.

**Recommendation**: Add `results` field to `StageExecutionError` with completed stage outputs.

---

#### BUG-021: Parallel branch outputs lost on single branch failure

**Type**: Reliability | **Severity**: High | **Component**: `StageGraph` executor

**Description**: In fan-out patterns (A → [B, C]), if B fails but C completes successfully, C's output is not preserved when `StageExecutionError` is raised.

**Expected Behavior**: All completed stage outputs should be accessible regardless of which branch fails.

**Actual Behavior**: `StageExecutionError` does not include any stage outputs.

**Impact**: Work from successful parallel branches is lost when any branch fails.

**Recommendation**: Add `outputs` field to `StageExecutionError` with all completed stage results.

---

### 2.2 DX Issues

#### DX-025: Inconsistent partial result handling between fail and cancel

**Severity**: Medium | **Component**: Error handling

**Description**: `StageOutput.cancel()` provides partial results via `UnifiedPipelineCancelled.results`, but `StageOutput.fail()` via `StageExecutionError` does not. This inconsistency creates confusion about when partial results are available.

**Impact**: Developers must handle two different exception patterns with different data availability.

**Recommendation**: Document the behavior difference clearly or unify the exception interfaces.

---

#### DX-026: Missing documentation on partial output handling

**Severity**: Low | **Component**: Error handling guide

**Description**: The error handling guide does not document what happens to stage outputs when a pipeline fails.

**Recommendation**: Add section documenting partial output handling for each exception type.

---

### 2.3 Strengths

#### STR-042: UnifiedPipelineCancelled preserves partial results

**Component**: `UnifiedPipelineCancelled`

**Description**: When a stage returns `StageOutput.cancel()`, the pipeline gracefully stops and `UnifiedPipelineCancelled` includes a `results` dict with all completed stage outputs.

**Evidence**: Pipeline A → B where B cancels provides `e.results` containing A's output.

**Impact**: High - This enables graceful degradation patterns.

---

### 2.4 Improvements Suggested

#### IMP-040: Add checkpoint and resume capability

**Priority**: P1 | **Category**: Core

**Description**: Stageflow should provide a checkpoint mechanism to save pipeline state periodically, enabling recovery from failures without reprocessing completed stages.

**Rationale**: AWS Step Functions redrive and Temporal.io durable execution provide checkpoint-based recovery.

**Roleplay Perspective**: "As a healthcare systems architect, I need to resume diagnostic pipelines after failures without reprocessing expensive imaging analysis."

---

#### IMP-041: Saga pattern support for compensation actions

**Priority**: P2 | **Category**: Plus Package

**Description**: Stageflow should support Saga pattern with compensation actions that run in reverse order when a pipeline fails, enabling distributed transaction semantics.

**Roleplay Perspective**: "As a financial systems architect, I need to roll back transfers when downstream validation fails."

---

## 3. Recommendations

### Immediate Actions (P0)

| # | Recommendation | Effort | Impact |
|---|----------------|--------|--------|
| 1 | Document partial output behavior for `fail()` vs `cancel()` | Low | High |
| 2 | Add `results` field to `StageExecutionError` | Medium | High |

### Short-Term Improvements (P1)

| # | Recommendation | Effort | Impact |
|---|----------------|--------|--------|
| 1 | Implement checkpoint-based recovery | High | High |
| 2 | Add `outputs` field to capture completed stage results | Medium | High |

### Long-Term Considerations (P2)

| # | Recommendation | Effort | Impact |
|---|----------------|--------|--------|
| 1 | Add Saga pattern support with compensations | High | Medium |
| 2 | Add `redrive` capability for resuming from failure point | High | Medium |

---

## 4. Developer Experience Evaluation

### DX Scores

| Category | Score | Notes |
|----------|-------|-------|
| **Discoverability** | 3/5 | Cancel partial results are discoverable via exception |
| **Clarity** | 2/5 | Inconsistent behavior between fail/cancel |
| **Documentation** | 2/5 | Missing partial output handling docs |
| **Error Messages** | 3/5 | Clear error messages but incomplete exception data |
| **Debugging** | 2/5 | Cannot see partial outputs after failure |

**Overall DX Score**: 2.4/5.0

---

## 5. Conclusion

CONTRACT-003 identified a **critical reliability gap** in Stageflow's partial output handling:

1. **Good**: `StageOutput.cancel()` correctly preserves partial results
2. **Gap**: `StageOutput.fail()` loses all partial outputs
3. **Risk**: Parallel branch outputs are lost on any branch failure

The framework should consider:
- Adding `results` field to `StageExecutionError`
- Documenting the behavior difference
- Implementing checkpoint/resume for production reliability

---

*CONTRACT-003 completed 2026-01-19*
