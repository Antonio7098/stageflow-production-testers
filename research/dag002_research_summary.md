# DAG-002: Priority Inversion in Shared Resource Pools - Research Summary

## Mission Parameters

| Field | Value |
|-------|-------|
| **Roadmap Entry ID** | DAG-002 |
| **Title** | Priority inversion in shared resource pools |
| **Priority** | P0 |
| **Risk Class** | Severe |
| **Section** | 1.2 DAG Execution & Scheduling |

## 1. Web Research Findings

### 1.1 Industry Context

Priority inversion is a well-documented scheduling problem in concurrent systems where a high-priority task is indirectly delayed by a lower-priority task. This can lead to catastrophic failures in real-time systems.

**Key Findings from Research:**

1. **Definition**: Priority inversion occurs when a low-priority task causes the execution of a higher-priority task to be delayed. The possibility of priority inversions complicates the analysis of systems that use priority-based scheduling.

2. **Historical Incident**: The Mars Pathfinder mission experienced a severe priority inversion issue that caused repeated system resets. This was famously resolved by implementing priority inheritance on the mutex that was causing the inversion.

3. **Common Scenarios**:
   - Shared resource access (mutexes, semaphores, database connections)
   - External API rate limits
   - I/O operations with blocking waits
   - Thread pool exhaustion

4. **Solutions**:
   - Priority Inheritance Protocol (PIP): Temporarily elevates the priority of a low-priority task holding a lock to prevent medium-priority tasks from preempting it
   - Priority Ceiling Protocol: Assigns a ceiling priority to each resource
   - Avoiding shared resources entirely when possible

### 1.2 Technical Context

**Mechanisms of Priority Inversion:**

1. **Basic Scenario**:
   - Task L (low priority) acquires a resource
   - Task H (high priority) requests the same resource, blocks
   - Task M (medium priority) preempts L and runs
   - H is blocked until L releases the resource
   - M runs instead of H → Priority inversion

2. **Unbounded Priority Inversion**:
   - Without mitigation, inversion can last indefinitely
   - High-priority task waits for medium-priority task to complete
   - Medium-priority task runs while holding no lock for H

3. **Stageflow-Specific Concerns**:

   Based on the mission brief and web research:

   - **Shared Tool Pools**: ENRICH stages may saturate shared tool pools
   - **API Rate Limits**: Multiple stages competing for rate-limited external APIs
   - **OutputBag Concurrency**: High fan-out DAGs with concurrent stage writes
   - **ContextSnapshot Contention**: Multiple stages accessing shared context data
   - **Subpipeline Resource Contention**: Child pipelines competing for parent resources

### 1.3 Stageflow Architecture Relevance

**Relevant Stageflow Components:**

1. **Pipeline Execution Model**:
   - DAG-based stage execution
   - Parallel execution of independent stages
   - OutputBag for collecting stage results

2. **Context System**:
   - PipelineContext: Shared across all stages
   - ContextSnapshot: Immutable input state
   - StageInputs: Filtered view of upstream outputs

3. **Resource Sharing Points**:
   - `ctx.data` dict: Shared mutable state in PipelineContext
   - OutputBag: Append-only but concurrent writes
   - External API calls via ports (LLM, STT, TTS)
   - Subpipeline spawning via fork()

## 2. Hypotheses to Test

### Hypothesis 1: OutputBag Race Condition

**Description**: When multiple parallel ENRICH stages write to the OutputBag simultaneously, later writes may overwrite earlier writes due to lack of atomic merge operations.

**Test Scenario**:
- Create a pipeline with a root stage and 5+ parallel ENRICH stages
- All stages write to the same key in their outputs
- Verify that all outputs are correctly captured

**Expected Result**: All stage outputs should be preserved; no data loss

### Hypothesis 2: Shared Resource Pool Saturation

**Description**: High-priority WORK stages (e.g., emergency service shutoff) are blocked because lower-priority ENRICH stages have saturated a shared resource pool (e.g., API rate limits).

**Test Scenario**:
- Create a pipeline with low-priority ENRICH stages that exhaust a simulated rate limit
- Add a high-priority WORK stage that needs the same resource
- Measure the delay experienced by the high-priority stage

**Expected Result**: High-priority stage should not be significantly delayed by low-priority stages

### Hypothesis 3: Context Data Corruption

**Description**: Multiple stages writing to `ctx.data` dict may cause inconsistent state due to non-atomic operations.

**Test Scenario**:
- Create stages that increment counters in ctx.data
- Run multiple iterations with parallel execution
- Verify final counter values match expected results

**Expected Result**: Counter increments should be atomic and consistent

### Hypothesis 4: Subpipeline Resource Contention

**Description**: When multiple subpipelines are spawned concurrently, they may compete for parent context resources causing delays.

**Test Scenario**:
- Create a parent pipeline that spawns multiple child pipelines
- All children try to access shared parent data simultaneously
- Measure completion times and verify isolation

**Expected Result**: Children should not interfere with each other; isolation should be maintained

### Hypothesis 5: Silent Failure in Priority Enforcement

**Description**: Priority inversion may occur silently without raising errors, making it hard to detect in production.

**Test Scenario**:
- Build a pipeline designed to trigger priority inversion
- Instrument with detailed timing metrics
- Verify that high-priority stages complete within expected time bounds

**Expected Result**: No silent violations of priority expectations

## 3. Success Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| OutputBag data integrity | 100% preservation | All parallel stage outputs captured |
| High-priority latency | <500ms additional delay | P95 latency for priority stages |
| Context consistency | Zero corruption | Counter value validation |
| Resource isolation | Complete isolation | Child pipeline independence |
| Silent failure detection | 100% detection | Metrics correlation with logs |

## 4. Test Pipeline Categories

### 4.1 Baseline Pipeline
- Simple linear pipeline with 3-4 stages
- Verifies basic functionality
- Establishes timing baseline

### 4.2 Concurrency Stress Pipeline
- Fan-out pattern with 10+ parallel stages
- Tests OutputBag and context contention
- High fan-out width stress test

### 4.3 Resource Contention Pipeline
- Multiple stages competing for simulated rate-limited resource
- Tests priority inversion detection
- Variable execution times

### 4.4 Subpipeline Pipeline
- Parent spawns multiple children
- Tests isolation and resource management
- Nested execution stress test

### 4.5 Recovery Pipeline
- Tests failure recovery with concurrent stages
- Verifies state consistency after errors
- Cancellation propagation

## 5. Environment Simulation

### 5.1 Mock Components

1. **RateLimitedResource**:
   - Simulates external API with rate limits
   - Tracks usage per priority level
   - Configurable limit and refill rate

2. **SharedCounter**:
   - Thread-safe counter for context testing
   - Records all increments for validation
   - Supports batching and atomic operations

3. **PriorityScheduler**:
   - Mock scheduler with priority queuing
   - Implements priority inheritance simulation
   - Tracks scheduling decisions

### 5.2 Test Data

1. **Happy Path Inputs**:
   - Normal, expected inputs for all stage types
   - Varying payload sizes
   - Mixed stage kinds

2. **Edge Cases**:
   - Many parallel stages (10, 20, 50)
   - Stages with very short/long execution times
   - Simultaneous completion windows

3. **Adversarial Inputs**:
   - Malformed data triggering retries
   - Resource exhaustion scenarios
   - Cancellation during execution

## 6. Identified Risks

### 6.1 High Risk
- **OutputBag race condition**: Can cause silent data loss
- **Rate limit priority inversion**: High-priority tasks blocked by low-priority

### 6.2 Medium Risk
- **Context data corruption**: State inconsistency in shared dict
- **Subpipeline resource contention**: Performance degradation

### 6.3 Low Risk
- **Documentation gaps**: Missing priority-related API documentation
- **Testing complexity**: Hard to reproduce in isolation

## 7. Stageflow-Specific Context

### 7.1 Relevant Documentation Sections

- `guides/pipelines.md`: Pipeline building and DAG patterns
- `guides/context.md`: Context system and data flow
- `api/context.md`: Context API reference
- `api/pipeline.md`: Pipeline execution
- `advanced/subpipelines.md`: Subpipeline spawning

### 7.2 Key APIs to Test

1. `PipelineContext.fork()`: Child context creation
2. `OutputBag.write()`: Stage output storage
3. `PipelineContext.data`: Shared mutable state
4. `StageGraph.run()`: DAG execution

### 7.3 Known Limitations

From documentation and mission brief:
- No built-in priority scheduling mechanism
- OutputBag lacks atomic merge for parallel writes
- Context data dict is mutable without locks

## 8. Research References

1. Priority Inversion - Wikipedia: https://en.wikipedia.org/wiki/Priority_inversion
2. Priority Inheritance - Wikipedia: https://en.wikipedia.org/wiki/Priority_inheritance
3. Priority Inheritance Protocols (IEEE): https://www3.nd.edu/~dwang5/courses/spring18/papers/real-time/pip.pdf
4. Mars Pathfinder Case Study: Real-time systems priority inversion
5. FreeRTOS Priority Inheritance: https://freertos.org/Real-time-embedded-RTOS-mutexes.html

---

*Research completed: 2026-01-19*
*Agent: claude-3.5-sonnet*
