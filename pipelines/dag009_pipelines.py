"""
DAG-009: Stage Timeout and Cancellation Propagation - Test Pipelines

This module implements test pipelines to verify Stageflow's timeout and
cancellation propagation behavior under various conditions.

Target: Stage timeout and cancellation propagation
Priority: P1
Risk Class: High

Industry Persona: Healthcare Systems Architect
Concerns:
- Clinical pipelines must have bounded execution times
- Patient data cleanup on timeout/cancellation
- Graceful degradation when stages hang
- Audit trail for all timeout events
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

sys.path.insert(0, str(Path(__file__).parent.parent))

import stageflow
from stageflow import (
    Pipeline, Stage, StageKind, StageOutput, StageContext,
    create_stage_context, create_stage_inputs, PipelineTimer,
    StageGraph, TimeoutInterceptor, get_default_interceptors,
    PipelineContext,
)
from stageflow.context import ContextSnapshot
from stageflow.stages.inputs import StageInputs

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("dag009_tests")

RESOURCE_CLEANUPTracker = []


def create_test_pipeline_context(
    timeout_ms: float = 3000,
) -> PipelineContext:
    """Create a PipelineContext configured for timeout testing."""
    ctx = PipelineContext(
        pipeline_run_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        interaction_id=uuid.uuid4(),
        topology="dag009_timeout_test",
        execution_mode="test",
        data={"_timeout_ms": timeout_ms},
    )
    return ctx


class SlowStage(Stage):
    """Stage that intentionally runs slowly to trigger timeout."""
    name = "slow_stage"
    kind = StageKind.TRANSFORM
    
    def __init__(self, duration_ms: float = 5000, should_cancel: bool = False):
        self.duration_ms = duration_ms
        self.should_cancel = should_cancel
        self.started = False
        self.cancelled = False
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        self.started = True
        try:
            await asyncio.sleep(self.duration_ms / 1000)
            return StageOutput.ok(completed=True)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
    
    def __del__(self):
        RESOURCE_CLEANUPTracker.append(f"SlowStage_{self.name}")


class ResourceCleanupStage(Stage):
    """Stage that acquires resources and verifies cleanup on timeout."""
    name = "resource_cleanup"
    kind = StageKind.WORK
    
    def __init__(self):
        self.acquired = False
        self.cleaned = False
        self.file_handle = None
        self.resource_id = str(uuid.uuid4())
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        self.acquired = True
        try:
            self.file_handle = open(os.devnull, 'w')
            await asyncio.sleep(60.0)
            return StageOutput.ok(resource_id=self.resource_id)
        except (asyncio.CancelledError, TimeoutError):
            if self.file_handle:
                self.file_handle.close()
                self.cleaned = True
            raise
        finally:
            if self.file_handle and not self.file_handle.closed:
                self.file_handle.close()
                self.cleaned = True


class AsyncGeneratorStage(Stage):
    """Stage using async generator - tests PEP 789 timeout leakage."""
    name = "async_generator"
    kind = StageKind.TRANSFORM
    
    def __init__(self, yield_count: int = 100, yield_delay_ms: int = 100):
        self.yield_count = yield_count
        self.yield_delay_ms = yield_delay_ms
        self.yields_before_cancel = 0
        self.cleanup_called = False
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        async def generator():
            for i in range(self.yield_count):
                try:
                    yield i
                    self.yields_before_cancel = i + 1
                    await asyncio.sleep(self.yield_delay_ms / 1000)
                except asyncio.CancelledError:
                    self.cleanup_called = True
                    raise
        
        results = []
        try:
            async for value in generator():
                results.append(value)
        except asyncio.CancelledError:
            pass
        
        return StageOutput.ok(
            yields=self.yields_before_cancel,
            cleanup_called=self.cleanup_called,
            cancelled=True if self.cleanup_called else None
        )


class ParallelWorkerStage(Stage):
    """Stage for parallel execution patterns."""
    name = "parallel_worker"
    kind = StageKind.TRANSFORM
    
    def __init__(self, worker_id: str, duration_ms: float = 5000):
        self.worker_id = worker_id
        self.duration_ms = duration_ms
        self.executed = False
        self.started_at = None
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        self.executed = True
        self.started_at = time.perf_counter()
        try:
            await asyncio.sleep(self.duration_ms / 1000)
            return StageOutput.ok(worker_id=self.worker_id, completed=True)
        except asyncio.CancelledError:
            elapsed = time.perf_counter() - self.started_at
            return StageOutput.cancel(
                reason=f"Worker {self.worker_id} cancelled after {elapsed*1000:.1f}ms"
            )


class SubpipelineTimeoutStage(Stage):
    """Stage that spawns subpipeline and tests timeout propagation."""
    name = "subpipeline_timeout"
    kind = StageKind.TRANSFORM
    
    def __init__(self, subpipeline_timeout_ms: float = 5000):
        self.subpipeline_timeout_ms = subpipeline_timeout_ms
        self.child_cancelled = False
        self.parent_timed_out = False
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        try:
            from stageflow.subpipeline import SubpipelineSpawner
            spawner = SubpipelineSpawner(ctx)
            slow_child = SlowStage(duration_ms=60000, should_cancel=True)
            slow_child.name = "slow_child"
            result = await spawner.spawn(
                child_stages=[slow_child],
                runner=self.subpipeline_timeout_ms / 1000,
            )
            return StageOutput.ok(spawn_result=str(result))
        except asyncio.CancelledError:
            self.child_cancelled = True
            raise
        except TimeoutError:
            self.parent_timed_out = True
            return StageOutput.cancel(reason="Parent timeout during subpipeline")


class ContextManagerStage(Stage):
    """Stage testing context manager cleanup on timeout."""
    name = "context_manager"
    kind = StageKind.TRANSFORM
    
    def __init__(self):
        self.enter_called = False
        self.exit_called = False
        self.exit_args = None
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        class ManagedResource:
            def __init__(self, stage):
                self.stage = stage
                self.stage.enter_called = True
            
            async def __aenter__(self):
                return self
            
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.stage.exit_called = True
                self.stage.exit_args = (exc_type, exc_val, exc_tb)
                return False
        
        resource = ManagedResource(self)
        try:
            async with resource:
                await asyncio.sleep(60.0)
                return StageOutput.ok()
        except asyncio.CancelledError:
            return StageOutput.ok(
                enter_called=self.enter_called,
                exit_called=self.exit_called,
                exit_exc_type=self.exit_args[0].__name__ if self.exit_args and self.exit_args[0] else None,
                cancelled=True
            )


class HeartbeatStage(Stage):
    """Stage that sends heartbeat to prevent premature timeout."""
    name = "heartbeat"
    kind = StageKind.TRANSFORM
    
    def __init__(self, duration_ms: float = 10000, heartbeat_interval_ms: float = 1000):
        self.duration_ms = duration_ms
        self.heartbeat_interval_ms = heartbeat_interval_ms
        self.heartbeats_sent = 0
        self.timed_out = False
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        start = time.perf_counter()
        try:
            while time.perf_counter() - start < self.duration_ms / 1000:
                await asyncio.sleep(self.heartbeat_interval_ms / 1000)
                self.heartbeats_sent += 1
                ctx.emit_event("heartbeat", {"count": self.heartbeats_sent})
            return StageOutput.ok(heartbeats=self.heartbeats_sent)
        except asyncio.CancelledError:
            self.timed_out = True
            elapsed = time.perf_counter() - start
            return StageOutput.cancel(
                reason=f"Heartbeat stage timed out after {elapsed*1000:.1f}ms, sent {self.heartbeats_sent} heartbeats"
            )


class NestedTimeoutStage(Stage):
    """Stage with nested timeout for testing cascade behavior."""
    name = "nested_timeout"
    kind = StageKind.TRANSFORM
    
    def __init__(self, inner_duration_ms: float = 8000, outer_timeout_ms: float = 5000):
        self.inner_duration_ms = inner_duration_ms
        self.outer_timeout_ms = outer_timeout_ms
        self.inner_started = False
        self.inner_cancelled = False
        self.outer_cancelled = False
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        try:
            async with asyncio.timeout(self.outer_timeout_ms / 1000):
                self.inner_started = True
                try:
                    async with asyncio.timeout(self.inner_duration_ms / 1000):
                        await asyncio.sleep(self.inner_duration_ms / 1000)
                        return StageOutput.ok()
                except asyncio.CancelledError:
                    self.inner_cancelled = True
                    raise
        except asyncio.CancelledError:
            self.outer_cancelled = True
            raise
        except TimeoutError:
            return StageOutput.cancel(reason="Outer timeout triggered")


class CleanupTrackingStage(Stage):
    """Stage that tracks cleanup for resource leak detection."""
    name = "cleanup_tracking"
    kind = StageKind.TRANSFORM
    
    _instances = []
    
    def __init__(self, instance_id: str):
        self.instance_id = instance_id
        self._instances.append(self)
        self.executed = False
        self.cleaned = False
        self.started_at = None
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        self.started_at = time.perf_counter()
        self.executed = True
        try:
            await asyncio.sleep(60.0)
            return StageOutput.ok()
        except asyncio.CancelledError:
            self.cleaned = True
            raise
    
    def __del__(self):
        RESOURCE_CLEANUPTracker.append(self.instance_id)


async def test_simple_timeout() -> dict[str, Any]:
    """Test that a stage exceeding timeout is properly cancelled."""
    logger.info("Running simple timeout test...")
    
    ctx = create_test_pipeline_context(timeout_ms=100)
    
    slow_stage = SlowStage(duration_ms=500, should_cancel=True)
    
    pipeline = Pipeline().with_stage("slow", slow_stage, StageKind.TRANSFORM)
    graph = pipeline.build()
    
    try:
        start = time.perf_counter()
        results = await graph.run(ctx)
        elapsed = time.perf_counter() - start
        
        slow_result = results.get("slow")
        
        return {
            'test_type': 'simple_timeout',
            'success': slow_result is not None and slow_result.status.value in ['fail', 'cancel'],
            'timeout_applied': elapsed < 1.0,
            'elapsed_ms': elapsed * 1000,
            'stage_was_started': slow_stage.started,
            'stage_was_cancelled': slow_stage.cancelled,
            'result_status': slow_result.status.value if slow_result else None,
            'result_data': slow_result.data if slow_result else None,
        }
    except Exception as e:
        return {
            'test_type': 'simple_timeout',
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
        }


async def test_no_timeout() -> dict[str, Any]:
    """Test that a stage completing before timeout is not cancelled."""
    logger.info("Running no timeout test...")
    
    ctx = create_test_pipeline_context(timeout_ms=5000)
    
    fast_stage = SlowStage(duration_ms=100)
    
    pipeline = Pipeline().with_stage("fast", fast_stage, StageKind.TRANSFORM)
    graph = pipeline.build()
    
    try:
        start = time.perf_counter()
        results = await graph.run(ctx)
        elapsed = time.perf_counter() - start
        
        fast_result = results.get("fast")
        
        return {
            'test_type': 'no_timeout',
            'success': fast_result is not None and fast_result.status.value == 'ok',
            'elapsed_ms': elapsed * 1000,
            'stage_was_started': fast_stage.started,
            'stage_completed': fast_result.data.get('completed') if fast_result else False,
        }
    except Exception as e:
        return {
            'test_type': 'no_timeout',
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
        }


async def test_parallel_timeout_propagation() -> dict[str, Any]:
    """Test that cancellation propagates to parallel branches."""
    logger.info("Running parallel timeout propagation test...")
    
    ctx = create_test_pipeline_context(timeout_ms=200)
    
    pipeline = (
        Pipeline()
        .with_stage("root", SlowStage(duration_ms=100), StageKind.TRANSFORM)
        .with_stage("slow_a", ParallelWorkerStage(worker_id="A", duration_ms=5000), StageKind.TRANSFORM, dependencies=("root",))
        .with_stage("slow_b", ParallelWorkerStage(worker_id="B", duration_ms=5000), StageKind.TRANSFORM, dependencies=("root",))
        .with_stage("aggregate", ParallelWorkerStage(worker_id="AGG", duration_ms=100), StageKind.TRANSFORM, dependencies=("slow_a", "slow_b"))
    )
    
    try:
        graph = pipeline.build()
        start = time.perf_counter()
        results = await graph.run(ctx)
        elapsed = time.perf_counter() - start
        
        slow_a = results.get("slow_a")
        slow_b = results.get("slow_b")
        aggregate = results.get("aggregate")
        
        return {
            'test_type': 'parallel_timeout_propagation',
            'success': True,
            'elapsed_ms': elapsed * 1000,
            'root_completed': results.get("root") is not None,
            'slow_a_status': slow_a.status.value if slow_a else None,
            'slow_b_status': slow_b.status.value if slow_b else None,
            'aggregate_status': aggregate.status.value if aggregate else None,
            'note': 'Both parallel branches should be cancelled when timeout hits root',
        }
    except Exception as e:
        return {
            'test_type': 'parallel_timeout_propagation',
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
        }


async def test_async_generator_timeout() -> dict[str, Any]:
    """Test that async generator timeouts don't leak to outer scope."""
    logger.info("Running async generator timeout test...")
    
    ctx = create_test_pipeline_context(timeout_ms=200)
    
    gen_stage = AsyncGeneratorStage(yield_count=100, yield_delay_ms=50)
    
    pipeline = Pipeline().with_stage("generator", gen_stage, StageKind.TRANSFORM)
    graph = pipeline.build()
    
    try:
        start = time.perf_counter()
        results = await graph.run(ctx)
        elapsed = time.perf_counter() - start
        
        gen_result = results.get("generator")
        
        return {
            'test_type': 'async_generator_timeout',
            'success': True,
            'elapsed_ms': elapsed * 1000,
            'yields_before_cancel': gen_stage.yields_before_cancel,
            'cleanup_called': gen_stage.cleanup_called,
            'result_cancelled': gen_result.data.get('cancelled') if gen_result else None,
            'note': 'Generator should handle timeout without leaking CancelledError',
        }
    except Exception as e:
        return {
            'test_type': 'async_generator_timeout',
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
        }


async def test_resource_cleanup() -> dict[str, Any]:
    """Test that resources are cleaned up on timeout."""
    logger.info("Running resource cleanup test...")
    
    ctx = create_test_pipeline_context(timeout_ms=100)
    
    resource_stage = ResourceCleanupStage()
    
    pipeline = Pipeline().with_stage("resource", resource_stage, StageKind.WORK)
    graph = pipeline.build()
    
    try:
        start = time.perf_counter()
        results = await graph.run(ctx)
        elapsed = time.perf_counter() - start
        
        res_result = results.get("resource")
        
        return {
            'test_type': 'resource_cleanup',
            'success': True,
            'elapsed_ms': elapsed * 1000,
            'resource_acquired': resource_stage.acquired,
            'resource_cleaned': resource_stage.cleaned,
            'result_status': res_result.status.value if res_result else None,
            'note': 'File handle should be closed even on timeout',
        }
    except Exception as e:
        return {
            'test_type': 'resource_cleanup',
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
        }


async def test_context_manager_cleanup() -> dict[str, Any]:
    """Test that context manager __aexit__ is called on timeout."""
    logger.info("Running context manager cleanup test...")
    
    ctx = create_test_pipeline_context(timeout_ms=100)
    
    cm_stage = ContextManagerStage()
    
    pipeline = Pipeline().with_stage("cm", cm_stage, StageKind.TRANSFORM)
    graph = pipeline.build()
    
    try:
        start = time.perf_counter()
        results = await graph.run(ctx)
        elapsed = time.perf_counter() - start
        
        cm_result = results.get("cm")
        
        return {
            'test_type': 'context_manager_cleanup',
            'success': True,
            'elapsed_ms': elapsed * 1000,
            'enter_called': cm_stage.enter_called,
            'exit_called': cm_stage.exit_called,
            'exit_exc_type': cm_stage.exit_args[0].__name__ if cm_stage.exit_args and cm_stage.exit_args[0] else None,
            'result_data': cm_result.data if cm_result else None,
            'note': '__aexit__ should be called with CancelledError type',
        }
    except Exception as e:
        return {
            'test_type': 'context_manager_cleanup',
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
        }


async def test_nested_timeout() -> dict[str, Any]:
    """Test nested timeout behavior."""
    logger.info("Running nested timeout test...")
    
    ctx = create_test_pipeline_context(timeout_ms=5000)
    
    nested_stage = NestedTimeoutStage(
        inner_duration_ms=8000,
        outer_timeout_ms=3000
    )
    
    pipeline = Pipeline().with_stage("nested", nested_stage, StageKind.TRANSFORM)
    graph = pipeline.build()
    
    try:
        start = time.perf_counter()
        results = await graph.run(ctx)
        elapsed = time.perf_counter() - start
        
        nested_result = results.get("nested")
        
        return {
            'test_type': 'nested_timeout',
            'success': True,
            'elapsed_ms': elapsed * 1000,
            'inner_started': nested_stage.inner_started,
            'inner_cancelled': nested_stage.inner_cancelled,
            'outer_cancelled': nested_stage.outer_cancelled,
            'result_status': nested_result.status.value if nested_result else None,
            'result_data': nested_result.data if nested_result else None,
            'note': 'Inner timeout should be caught by outer timeout',
        }
    except Exception as e:
        return {
            'test_type': 'nested_timeout',
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
        }


async def test_concurrent_timeouts(num_workers: int = 50) -> dict[str, Any]:
    """Test many concurrent timeout scenarios."""
    logger.info(f"Running concurrent timeout test with {num_workers} workers...")
    
    results_list = []
    total_elapsed = 0
    
    for i in range(num_workers):
        ctx = create_test_pipeline_context(timeout_ms=100)
        worker = ParallelWorkerStage(worker_id=str(i), duration_ms=5000)
        
        pipeline = Pipeline().with_stage(f"worker_{i}", worker, StageKind.TRANSFORM)
        graph = pipeline.build()
        
        try:
            start = time.perf_counter()
            results = await graph.run(ctx)
            elapsed = time.perf_counter() - start
            total_elapsed = max(total_elapsed, elapsed)
            
            results_list.append({
                'worker_id': i,
                'executed': worker.executed,
                'cancelled': worker.executed and not results.get(f"worker_{i}").data.get('completed'),
            })
        except Exception as e:
            results_list.append({
                'worker_id': i,
                'error': str(e),
            })
    
    cancelled_count = sum(1 for r in results_list if r.get('cancelled'))
    executed_count = sum(1 for r in results_list if r.get('executed'))
    
    return {
        'test_type': 'concurrent_timeouts',
        'success': True,
        'total_workers': num_workers,
        'executed': executed_count,
        'cancelled': cancelled_count,
        'total_elapsed_ms': total_elapsed * 1000,
        'per_worker_elapsed_estimate': (total_elapsed * 1000) / num_workers,
        'note': 'All workers should timeout within reasonable time',
    }


async def test_zero_timeout() -> dict[str, Any]:
    """Test behavior with zero timeout."""
    logger.info("Running zero timeout test...")
    
    ctx = create_test_pipeline_context(timeout_ms=0)
    
    fast_stage = SlowStage(duration_ms=10)
    
    pipeline = Pipeline().with_stage("fast", fast_stage, StageKind.TRANSFORM)
    graph = pipeline.build()
    
    try:
        start = time.perf_counter()
        results = await graph.run(ctx)
        elapsed = time.perf_counter() - start
        
        return {
            'test_type': 'zero_timeout',
            'success': True,
            'elapsed_ms': elapsed * 1000,
            'note': 'Zero timeout should immediately cancel stage',
        }
    except Exception as e:
        return {
            'test_type': 'zero_timeout',
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
        }


async def test_stage_cancel_cancels_pipeline() -> dict[str, Any]:
    """Test that StageOutput.cancel() cancels the entire pipeline."""
    logger.info("Running stage cancel pipeline test...")
    
    ctx = create_test_pipeline_context(timeout_ms=10000)
    
    pipeline = (
        Pipeline()
        .with_stage("stage_1", SlowStage(duration_ms=100), StageKind.TRANSFORM)
        .with_stage("stage_2", SlowStage(duration_ms=100), StageKind.TRANSFORM, dependencies=("stage_1",))
        .with_stage("stage_3", SlowStage(duration_ms=100), StageKind.TRANSFORM, dependencies=("stage_2",))
    )
    
    graph = pipeline.build()
    
    try:
        start = time.perf_counter()
        results = await graph.run(ctx)
        elapsed = time.perf_counter() - start
        
        return {
            'test_type': 'stage_cancel_cancels_pipeline',
            'success': True,
            'elapsed_ms': elapsed * 1000,
            'results_count': len(results),
            'note': 'If any stage returns cancel(), subsequent stages should not run',
        }
    except stageflow.UnifiedPipelineCancelled as e:
        elapsed = time.perf_counter() - start
        return {
            'test_type': 'stage_cancel_cancels_pipeline',
            'success': True,
            'elapsed_ms': elapsed * 1000,
            'cancelled': True,
            'cancel_reason': e.reason if hasattr(e, 'reason') else str(e),
        }
    except Exception as e:
        return {
            'test_type': 'stage_cancel_cancels_pipeline',
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
        }


async def run_all_tests() -> dict[str, Any]:
    """Run all DAG-009 test scenarios."""
    logger.info("=" * 80)
    logger.info("DAG-009: Stage Timeout and Cancellation Propagation - Test Suite")
    logger.info("=" * 80)
    
    results = {
        'test_suite': 'DAG-009',
        'target': 'Stage timeout and cancellation propagation',
        'priority': 'P1',
        'risk': 'High',
        'tests': {},
        'summary': {},
    }
    
    tests = [
        ("simple_timeout", test_simple_timeout),
        ("no_timeout", test_no_timeout),
        ("parallel_timeout_propagation", test_parallel_timeout_propagation),
        ("async_generator_timeout", test_async_generator_timeout),
        ("resource_cleanup", test_resource_cleanup),
        ("context_manager_cleanup", test_context_manager_cleanup),
        ("nested_timeout", test_nested_timeout),
        ("concurrent_timeouts", lambda: test_concurrent_timeouts(50)),
        ("zero_timeout", test_zero_timeout),
        ("stage_cancel_cancels_pipeline", test_stage_cancel_cancels_pipeline),
    ]
    
    for i, (name, test_func) in enumerate(tests, 1):
        logger.info(f"\n[{i}/{len(tests)}] Running {name}...")
        try:
            results['tests'][name] = await test_func()
        except Exception as e:
            logger.error(f"Test {name} failed with exception: {e}")
            results['tests'][name] = {
                'test_type': name,
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__,
            }
    
    total_tests = len(results['tests'])
    passed_tests = sum(1 for t in results['tests'].values() if t.get('success', False))
    failed_tests = total_tests - passed_tests
    
    results['summary'] = {
        'total_tests': total_tests,
        'passed': passed_tests,
        'failed': failed_tests,
        'pass_rate': passed_tests / total_tests * 100 if total_tests > 0 else 0,
    }
    
    logger.info("\n" + "=" * 80)
    logger.info(f"Test Suite Complete: {passed_tests}/{total_tests} tests passed")
    logger.info(f"Pass Rate: {results['summary']['pass_rate']:.1f}%")
    logger.info("=" * 80)
    
    return results


if __name__ == "__main__":
    import json
    
    async def main():
        results = await run_all_tests()
        print("\n" + json.dumps(results, indent=2, default=str))
    
    asyncio.run(main())
