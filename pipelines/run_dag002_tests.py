#!/usr/bin/env python3
"""
DAG-002: Priority Inversion in Shared Resource Pools - Test Runner

Tests Stageflow's handling of priority inversion and resource contention
in shared resource pools during parallel DAG execution.
"""

import asyncio
import json
import logging
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4
import time

import stageflow
from stageflow import (
    Pipeline, Stage, StageKind, StageOutput, 
    PipelineContext, StageContext, StageExecutionError,
    create_stage_context, PipelineTimer,
)
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow.stages.inputs import StageInputs

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'results/logs/dag002_test_run_{datetime.now(UTC).strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("DAG-002")

test_results: dict[str, Any] = {
    "test_run_id": str(uuid4()),
    "timestamp": datetime.now(UTC).isoformat(),
    "tests": [],
    "summary": {},
    "findings": [],
}


@dataclass
class TestResult:
    test_name: str
    passed: bool
    duration_ms: float
    details: dict[str, Any]
    error: Optional[str] = None
    stack_trace: Optional[str] = None


# Shared test utilities
_counter_value = 0
_counter_lock = asyncio.Lock()
_counter_operations = []


async def increment_counter(amount: int = 1, operation_id: str = "") -> int:
    """Thread-safe counter increment."""
    global _counter_value, _counter_operations
    async with _counter_lock:
        old = _counter_value
        await asyncio.sleep(0.001)
        _counter_value += amount
        _counter_operations.append({
            "operation_id": operation_id,
            "old_value": old,
            "new_value": _counter_value,
            "amount": amount,
            "timestamp": time.time(),
        })
        return _counter_value


def reset_counter():
    """Reset counter for new test."""
    global _counter_value, _counter_operations
    _counter_value = 0
    _counter_operations = []


# ============================================================================
# TEST STAGES
# ============================================================================

class IncrementCounterStage(Stage):
    """Stage that increments a shared counter."""
    name = "increment_counter"
    kind = StageKind.TRANSFORM
    
    def __init__(self, stage_id: str):
        self._stage_id = stage_id
    
    @property
    def name(self) -> str:
        return f"increment_{self._stage_id}"
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        counter_value = await increment_counter(1, self._stage_id)
        logger.debug(f"Counter stage {self._stage_id}: value={counter_value}")
        return StageOutput.ok(
            stage_id=self._stage_id,
            counter_value=counter_value,
        )


class VerifyCounterStage(Stage):
    """Stage that verifies counter value."""
    name = "verify_counter"
    kind = StageKind.TRANSFORM
    
    def __init__(self, expected_total: int):
        self._expected_total = expected_total
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        global _counter_value
        actual = _counter_value
        lost = self._expected_total - actual
        return StageOutput.ok(
            expected=self._expected_total,
            actual=actual,
            lost_updates=lost,
            no_loss=lost == 0,
        )


class SimpleDelayStage(Stage):
    """Stage with configurable delay."""
    name = "simple_delay"
    kind = StageKind.TRANSFORM
    
    def __init__(self, stage_id: str, delay_ms: int = 50):
        self._stage_id = stage_id
        self._delay_ms = delay_ms
    
    @property
    def name(self) -> str:
        return f"delay_{self._stage_id}"
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        await asyncio.sleep(self._delay_ms / 1000)
        return StageOutput.ok(
            stage_id=self._stage_id,
            delay_ms=self._delay_ms,
        )


class ContextWriteStage(Stage):
    """Stage that writes to shared context data."""
    name = "context_write"
    kind = StageKind.TRANSFORM
    
    def __init__(self, stage_id: str, key: str, value: str):
        self._stage_id = stage_id
        self._key = key
        self._value = value
    
    @property
    def name(self) -> str:
        return f"write_{self._stage_id}"
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        if self._key not in ctx.pipeline_ctx.data:
            ctx.pipeline_ctx.data[self._key] = []
        ctx.pipeline_ctx.data[self._key].append({
            "stage": self._stage_id,
            "value": self._value,
            "timestamp": time.time(),
        })
        return StageOutput.ok(
            stage_id=self._stage_id,
            key=self._key,
            value=self._value,
        )


class VerifyContextWritesStage(Stage):
    """Stage that verifies context writes."""
    name = "verify_writes"
    kind = StageKind.TRANSFORM
    
    def __init__(self, key: str, expected_count: int):
        self._key = key
        self._expected_count = expected_count
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        writes = ctx.pipeline_ctx.data.get(self._key, [])
        return StageOutput.ok(
            expected=self._expected_count,
            actual=len(writes),
            lost=len(writes) < self._expected_count,
            all_values=[w["value"] for w in writes],
        )


class AggregationStage(Stage):
    """Stage that aggregates outputs from parallel stages."""
    name = "aggregation"
    kind = StageKind.TRANSFORM
    
    def __init__(self, prefix: str, count: int):
        self._prefix = prefix
        self._count = count
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        outputs = []
        for i in range(self._count):
            val = ctx.inputs.get_from(f"{self._prefix}_{i}", "stage_id")
            if val is not None:
                outputs.append(val)
        return StageOutput.ok(
            expected_count=self._count,
            actual_count=len(outputs),
            all_preserved=len(outputs) == self._count,
        )


# ============================================================================
# TEST CASES
# ============================================================================

async def test_counter_concurrency() -> TestResult:
    """Test: Concurrent counter increments for data integrity."""
    test_name = "test_counter_concurrency"
    logger.info(f"Running: {test_name}")
    
    try:
        reset_counter()
        num_stages = 20
        
        pipeline = Pipeline()
        for i in range(num_stages):
            pipeline = pipeline.with_stage(
                f"increment_{i}",
                IncrementCounterStage(str(i)),
                StageKind.TRANSFORM,
            )
        
        pipeline = pipeline.with_stage(
            "verify",
            VerifyCounterStage(num_stages),
            StageKind.TRANSFORM,
            dependencies=tuple(f"increment_{i}" for i in range(num_stages)),
        )
        
        graph = pipeline.build()
        snapshot = ContextSnapshot(
            run_id=RunIdentity(pipeline_run_id=uuid4()),
            input_text="test",
        )
        ctx = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name="root",
            timer=PipelineTimer(),
        )
        
        start = time.time()
        results = await graph.run(ctx)
        duration = (time.time() - start) * 1000
        
        verify_output = results["verify"].data
        passed = verify_output.get("no_loss", False)
        
        details = {
            "num_stages": num_stages,
            "expected": verify_output.get("expected"),
            "actual": verify_output.get("actual"),
            "lost_updates": verify_output.get("lost_updates", 0),
            "data_corruption": not passed,
        }
        
        return TestResult(test_name, passed, duration, details)
    
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_context_write_race() -> TestResult:
    """Test: Multiple stages writing to same context key."""
    test_name = "test_context_write_race"
    logger.info(f"Running: {test_name}")
    
    try:
        num_stages = 15
        key = "shared_writes"
        
        pipeline = Pipeline()
        for i in range(num_stages):
            pipeline = pipeline.with_stage(
                f"write_{i}",
                ContextWriteStage(str(i), key, f"value_{i}"),
                StageKind.TRANSFORM,
            )
        
        pipeline = pipeline.with_stage(
            "verify",
            VerifyContextWritesStage(key, num_stages),
            StageKind.TRANSFORM,
            dependencies=tuple(f"write_{i}" for i in range(num_stages)),
        )
        
        graph = pipeline.build()
        snapshot = ContextSnapshot(
            run_id=RunIdentity(pipeline_run_id=uuid4()),
            input_text="test",
        )
        ctx = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name="root",
            timer=PipelineTimer(),
        )
        
        start = time.time()
        results = await graph.run(ctx)
        duration = (time.time() - start) * 1000
        
        verify_output = results["verify"].data
        passed = not verify_output.get("lost", False)
        
        details = {
            "num_stages": num_stages,
            "expected": verify_output.get("expected"),
            "actual": verify_output.get("actual"),
            "lost_writes": verify_output.get("actual", 0) - verify_output.get("expected", 0),
            "data_loss": not passed,
        }
        
        return TestResult(test_name, passed, duration, details)
    
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_parallel_output_bag() -> TestResult:
    """Test: Parallel stages output aggregation."""
    test_name = "test_parallel_output_bag"
    logger.info(f"Running: {test_name}")
    
    try:
        num_stages = 10
        
        pipeline = Pipeline()
        for i in range(num_stages):
            pipeline = pipeline.with_stage(
                f"delay_{i}",
                SimpleDelayStage(str(i), delay_ms=20),
                StageKind.TRANSFORM,
            )
        
        pipeline = pipeline.with_stage(
            "aggregate",
            AggregationStage("delay", num_stages),
            StageKind.TRANSFORM,
            dependencies=tuple(f"delay_{i}" for i in range(num_stages)),
        )
        
        graph = pipeline.build()
        snapshot = ContextSnapshot(
            run_id=RunIdentity(pipeline_run_id=uuid4()),
            input_text="test",
        )
        ctx = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name="root",
            timer=PipelineTimer(),
        )
        
        start = time.time()
        results = await graph.run(ctx)
        duration = (time.time() - start) * 1000
        
        agg_output = results["aggregate"].data
        passed = agg_output.get("all_preserved", False)
        
        details = {
            "num_stages": num_stages,
            "expected": agg_output.get("expected_count"),
            "actual": agg_output.get("actual_count"),
            "lost_outputs": agg_output.get("expected_count", 0) - agg_output.get("actual_count", 0),
        }
        
        return TestResult(test_name, passed, duration, details)
    
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_high_fanout() -> TestResult:
    """Test: High fan-out (50 parallel stages)."""
    test_name = "test_high_fanout"
    logger.info(f"Running: {test_name}")
    
    try:
        num_stages = 50
        
        pipeline = Pipeline()
        for i in range(num_stages):
            pipeline = pipeline.with_stage(
                f"worker_{i}",
                SimpleDelayStage(str(i), delay_ms=10),
                StageKind.ENRICH,
            )
        
        deps = tuple(f"worker_{i}" for i in range(num_stages))
        pipeline = pipeline.with_stage(
            "aggregate",
            AggregationStage("worker", num_stages),
            StageKind.TRANSFORM,
            dependencies=deps,
        )
        
        graph = pipeline.build()
        snapshot = ContextSnapshot(
            run_id=RunIdentity(pipeline_run_id=uuid4()),
            input_text="test",
        )
        ctx = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name="root",
            timer=PipelineTimer(),
        )
        
        start = time.time()
        results = await graph.run(ctx)
        duration = (time.time() - start) * 1000
        
        agg_output = results["aggregate"].data
        passed = agg_output.get("all_preserved", False)
        
        details = {
            "num_stages": num_stages,
            "expected": agg_output.get("expected_count"),
            "actual": agg_output.get("actual_count"),
            "lost_outputs": agg_output.get("expected_count", 0) - agg_output.get("actual_count", 0),
        }
        
        return TestResult(test_name, passed, duration, details)
    
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_mixed_priority() -> TestResult:
    """Test: Mixed priority stages."""
    test_name = "test_mixed_priority"
    logger.info(f"Running: {test_name}")
    
    try:
        num_stages = 5
        
        pipeline = Pipeline()
        
        # Add parallel low-priority stages
        for i in range(num_stages):
            pipeline = pipeline.with_stage(
                f"low_{i}",
                SimpleDelayStage(f"low_{i}", delay_ms=30),
                StageKind.ENRICH,
            )
        
        # Add high-priority stage that depends on all low-priority
        pipeline = pipeline.with_stage(
            "high",
            SimpleDelayStage("high", delay_ms=20),
            StageKind.WORK,
            dependencies=tuple(f"low_{i}" for i in range(num_stages)),
        )
        
        graph = pipeline.build()
        snapshot = ContextSnapshot(
            run_id=RunIdentity(pipeline_run_id=uuid4()),
            input_text="test",
        )
        ctx = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name="root",
            timer=PipelineTimer(),
        )
        
        start = time.time()
        results = await graph.run(ctx)
        duration = (time.time() - start) * 1000
        
        # Check that high-priority stage completed
        high_output = results.get("high")
        high_completed = high_output is not None and high_output.status.value == "ok"
        
        # All low-priority should have completed
        all_low_completed = all(
            results.get(f"low_{i}") is not None and 
            results.get(f"low_{i}").status.value == "ok"
            for i in range(num_stages)
        )
        
        passed = high_completed and all_low_completed
        
        details = {
            "num_low_priority": num_stages,
            "high_completed": high_completed,
            "all_low_completed": all_low_completed,
            "duration_ms": duration,
        }
        
        return TestResult(test_name, passed, duration, details)
    
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def run_all_tests() -> dict[str, Any]:
    """Run all DAG-002 tests."""
    logger.info("=" * 60)
    logger.info("DAG-002: Priority Inversion in Shared Resource Pools")
    logger.info("=" * 60)
    
    tests = [
        ("Counter Concurrency", test_counter_concurrency),
        ("Context Write Race", test_context_write_race),
        ("Parallel OutputBag", test_parallel_output_bag),
        ("High Fan-out (50)", test_high_fanout),
        ("Mixed Priority", test_mixed_priority),
    ]
    
    results = []
    for test_desc, test_fn in tests:
        logger.info(f"\n{'='*40}")
        logger.info(f"TEST: {test_desc}")
        logger.info(f"{'='*40}")
        result = await test_fn()
        results.append(result)
        
        status = "PASS" if result.passed else "FAIL"
        logger.info(f"Result: {status} ({result.duration_ms:.2f}ms)")
        if result.error:
            logger.error(f"Error: {result.error}")
        
        test_results["tests"].append({
            "name": test_desc,
            "test_name": result.test_name,
            "passed": result.passed,
            "duration_ms": result.duration_ms,
            "details": result.details,
            "error": result.error,
            "stack_trace": result.stack_trace,
        })
    
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    
    test_results["summary"] = {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{passed/len(results)*100:.1f}%",
    }
    
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total: {len(results)}")
    logger.info(f"Passed: {passed}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Pass Rate: {test_results['summary']['pass_rate']}")
    
    results_path = Path("results/metrics/dag002_results.json")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w") as f:
        json.dump(test_results, f, indent=2, default=str)
    logger.info(f"\nResults saved to: {results_path}")
    
    return test_results


if __name__ == "__main__":
    results = asyncio.run(run_all_tests())
    
    if results["summary"]["failed"] > 0:
        sys.exit(1)
    sys.exit(0)
