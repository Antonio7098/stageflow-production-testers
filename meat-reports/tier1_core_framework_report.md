# Tier 1 Final Report: Core Framework Reliability

## Scope

Tier 1 covers Stageflow’s core primitives: context/state management (CORE-*), DAG execution and scheduling (DAG-*), and stage contract enforcement (CONTRACT-*). This meta-report synthesizes the results of all Tier 1 missions that have produced final reports so far, primarily:

- `DAG-009` – Timeout and cancellation propagation (@stageflow-production-testers/FINAL_REPORT.md)
- `CONTRACT-003` – Partial output handling on stage failure (@stageflow-production-testers/results/CONTRACT003_REPORT.md)

Other CORE/DAG/CONTRACT entries have been marked completed and exercised in code, but the two missions above provide the deepest, end-to-end stress tests and expose the main reliability gaps.

---

## 1. Context & State Management (CORE)

### 1.1 Current Guarantees

From the broader codebase and usage patterns referenced in the reports:

- **Context immutability**: Context snapshots are treated as immutable; stages work on copies, which is critical for parallel fan-out.
- **Cross-tenant isolation**: Context/data is namespaced per run, supporting multi-tenant isolation assumptions in CORE-010.
- **OutputBag semantics**: Parallel outputs are accumulated in an `OutputBag`-like structure, giving a single view over fan-out results.

These properties are relied on by higher tiers (e.g. ENRICH/ROUTE/GUARD missions) and were not contradicted by any Tier 1 report.

### 1.2 Gaps Highlighted by DAG-009

DAG-009 (	`Stage timeout and cancellation propagation`)
(@stageflow-production-testers/FINAL_REPORT.md#11-190) exposed a structural mismatch between pipeline-level and stage-level context APIs:

- **PipelineContext** (used by `graph.run()`):
  - Has: `data`, `artifacts`, `correlation_id`.
  - Missing: `timer` handle.
- **StageContext** (visible inside `stage.execute()`):
  - Has: `timer`, `snapshot`, `inputs`.
  - Missing: a convenient `data` attribute.

Consequences:

- Stages that expect `ctx.timer` fail when run via the pipeline graph because the timer is not exposed on `PipelineContext`.
- Timeout tests depending on the built-in `TimeoutInterceptor` could not be executed as designed: **only 1/10 tests passed**, the rest were blocked by missing context attributes.

This shows that **context APIs are not yet unified**; downstream stages cannot reason about timeouts consistently across direct stage execution and orchestrated graph runs.

### 1.3 Reliability Implications

- **Timeout behavior is underspecified**: Default 30s timeout exists, but its enforcement and observability differ depending on how a pipeline is invoked.
- **Cancellation semantics leak abstractions**: Stages must know which context flavor they are running under to use timers correctly.

### 1.4 Recommended Actions

1. **Unify context interfaces**
   - Either: make `PipelineContext` a thin wrapper over `StageContext` exposing `timer` and other timing controls.
   - Or: introduce a common base interface implemented by both, and guarantee that timeout-related attributes are always present.

2. **End-to-end timeout tests**
   - Re-run DAG-009 once context unification lands and ensure full coverage:
     - Simple timeouts.
     - Parallel branch timeouts.
     - Nested subpipeline timeouts.
     - Async generator timeouts (no leakage).

3. **Document timeout contract**
   - Explicitly state for users:
     - Where timeouts are configured (interceptors vs. data fields).
     - What guarantees exist on cancellation and cleanup.

---

## 2. DAG Execution & Scheduling (DAG)

### 2.1 What Works

Across DAG missions (as reflected in FINAL_REPORT and downstream tier reports):

- **Fan-out / fan-in** patterns execute correctly for happy-path scenarios.
- **Deadlock / livelock / starvation**: Earlier DAG-* entries are marked completed; no evidence of regressions appears in Tier 2 reports that heavily exercise parallelism (e.g. ROUTE-003, TRANSFORM-008).
- **Priority and resource contention**: DAG-005/DAG-010 are completed and no Tier 2 mission reported race conditions or starvation under their tested loads.

### 2.2 Timeout & Cancellation Semantics (DAG-009)

DAG-009 is the primary source of truth for failure behavior:

- **TimeoutInterceptor** exists but could not be fully verified due to context issues.
- **StageOutput.cancel()** semantics:
  - Cancels the **entire pipeline**, not just a branch.
  - Preserves partial outputs via `UnifiedPipelineCancelled.results`.

Reliability assessment:

- For a **single-cancellation policy** (any stage may abort the entire run), current behavior is coherent.
- For **branch-level cancellation** (cancel one branch, continue others), the current semantics are too coarse.

### 2.3 Recommended Actions

1. **Clarify cancellation scope**
   - Define whether `StageOutput.cancel()` is always pipeline-wide or can be scoped per branch.
   - If branch-scoped cancellation is needed, introduce a separate output mode (e.g. `cancel_branch`) rather than overloading `cancel()`.

2. **Upgrade tests once context is fixed**
   - Re-run and extend DAG-009 scenarios once the timer issue is resolved.

3. **Improve developer-facing documentation**
   - Add a section to the DAG guide explaining: 
     - How `StageOutput.cancel()` interacts with DAG topology.
     - How partial results are exposed when cancellation occurs.

---

## 3. Stage Contract Enforcement (CONTRACT)

### 3.1 Asymmetric Partial Output Handling (CONTRACT-003)

CONTRACT-003 (@stageflow-production-testers/results/CONTRACT003_REPORT.md#13-229) is the most important Tier 1 contract mission to date. It surfaces a **fundamental asymmetry** between `fail()` and `cancel()` paths:

- **On cancel** (`StageOutput.cancel()`):
  - Pipeline raises `UnifiedPipelineCancelled`.
  - `e.results` contains all completed stage outputs (excellent for graceful degradation).

- **On fail** (`StageOutput.fail()`):
  - Pipeline raises `StageExecutionError`.
  - Exception has `stage`, `original`, and `recoverable` but **no partial results field**.
  - In fan-out patterns, outputs from successful branches are lost.

This leads to two concrete bugs:

1. **BUG-020** – `StageExecutionError` lacks `results`/`outputs`.
2. **BUG-021** – In parallel branches, successful branch outputs are dropped when any sibling fails.

### 3.2 Reliability & DX Impact

- **Reliability gap**: Work that has already been completed successfully is discarded on failure, making recovery, compensation, and redrive flows more complex than necessary.
- **Inconsistent mental model**: Developers must handle two exception types with different data availability even though both represent “pipeline terminated early.”

### 3.3 Recommended Actions

1. **Unify exception payloads**
   - Add a `results` (or `outputs`) field to `StageExecutionError` mirroring `UnifiedPipelineCancelled`.
   - Ensure it contains all successfully completed stage outputs at the time of failure.

2. **Preserve parallel branch results**
   - Guarantee that, in A → [B, C] fan-out patterns, if B fails and C succeeds, C’s output is always accessible through the failure exception.

3. **Document partial-output semantics**
   - Update error-handling docs to explain:
     - What data is available on cancellation vs. failure.
     - How to inspect `results` to implement Saga-like compensation or checkpoint/resume behavior.

4. **Longer-term: Checkpoint & Saga support**
   - CONTRACT-003 recommends adding:
     - **Checkpoint/resume**: periodic state snapshots enabling redrive from failure point.
     - **Saga pattern support**: per-stage compensation actions to roll back side effects in distributed workflows.

---

## 4. Overall Tier 1 Assessment

### 4.1 Strengths

- **Solid foundational abstractions**: Context snapshots, immutable data flow, and clear Stage/StageOutput contracts underpin all higher tiers.
- **DAG engine correctness in happy paths**: Fan-out/fan-in, deep DAGs, and priority scheduling work reliably in the scenarios that have been exercised.
- **Graceful cancellation path**: `StageOutput.cancel()` plus `UnifiedPipelineCancelled.results` provide a strong base for graceful degradation.

### 4.2 Risks & Open Gaps

- **Timeout and cancellation semantics are not fully validated** due to context API mismatches.
- **Partial results are lost on failure**, creating a gap relative to cancellation behavior and to industry-standard workflow engines.
- **Context interfaces are fragmented**, forcing stages to be aware of how they’re invoked.

### 4.3 Recommended Next Missions for Tier 1

1. **CORE/DAG Context Unification Mission**
   - Goal: Align `PipelineContext` and `StageContext` so all timeout and data attributes are consistently available.
   - Success: DAG-009 re-run with 10/10 tests passing.

2. **CONTRACT Partial-Results Mission**
   - Goal: Extend `StageExecutionError` to carry `results`, and verify parallel branch output preservation.
   - Success: New CONTRACT mission confirming parity between `fail()` and `cancel()` in terms of observability.

3. **Checkpoint/Redrive Prototype**
   - Goal: Add a minimal checkpoint/resume mechanism and validate it on a small multi-stage pipeline.

**Verdict for Tier 1:** The core architecture is sound and already supports the more demanding Tier 2 missions, but **context unification and partial-output handling must be treated as Tier 1 blockers** before calling core framework reliability production-ready.
