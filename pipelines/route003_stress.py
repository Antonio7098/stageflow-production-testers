"""
Stress pipeline for ROUTE-003: Dynamic routing under load.

Tests ROUTE stage performance under high concurrent load, measuring
latency degradation, throughput limits, and behavior under stress.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import asyncio
import time
import uuid
import json
import logging
import random
from collections import defaultdict
from statistics import mean, median, p50, p95, p99, stdev

from stageflow import (
    Pipeline,
    StageContext,
    StageKind,
    StageOutput,
    PipelineState,
    ContextSnapshot,
)

import sys
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])
from mocks.route003_mock_data import (
    RouteType,
    RoutingRequest,
    LoadLevel,
    LoadScenario,
    LOAD_SCENARIOS,
    CONCURRENCY_SCENARIOS,
    LATENCY_SCENARIOS,
    PRIORITY_SCENARIOS,
    create_concurrent_test_batch,
    PerformanceMetrics,
    RESOURCE_CONSTRAINTS,
)
from pipelines.route003_baseline import SimpleRouterStage, MetricsCollectorStage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class StressTestResult:
    """Result of a stress test run."""
    load_level: str
    concurrent_requests: int
    total_requests: int
    successful_requests: int
    failed_requests: int
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    mean_latency_ms: float
    throughput_per_second: float
    error_rate: float
    route_distribution: Dict[str, int]
    errors: List[Dict[str, Any]] = field(default_factory=list)


class StressRouterStage:
    """
    ROUTE stage for stress testing with configurable latency.
    """
    name = "stress_router"
    kind = StageKind.ROUTE

    def __init__(self, base_latency_ms: float = 5.0, latency_jitter_ms: float = 2.0):
        self.base_latency_ms = base_latency_ms
        self.latency_jitter_ms = latency_jitter_ms
        self.request_count = 0

    async def execute(self, ctx: StageContext) -> StageOutput:
        self.request_count += 1

        # Simulate processing delay
        latency = self.base_latency_ms + random.uniform(-self.latency_jitter_ms, self.latency_jitter_ms)
        await asyncio.sleep(latency / 1000)

        input_text = ctx.snapshot.input_text or ""
        priority = ctx.snapshot.priority or 5

        # Determine route
        route = RouteType.STANDARD_PATH.value
        confidence = 0.7

        if "weather" in input_text.lower() or "time" in input_text.lower():
            route = RouteType.FAST_PATH.value
            confidence = 0.9
        elif "enterprise" in input_text.lower() or "upgrade" in input_text.lower():
            route = RouteType.PREMIUM_PATH.value
            confidence = 0.9
        elif "broken" in input_text.lower() or priority >= 8:
            route = RouteType.ESCALATION.value
            confidence = 0.95

        return StageOutput.ok(
            route=route,
            confidence=confidence,
            priority=priority,
            request_number=self.request_count,
            processing_latency_ms=latency,
        )


class LoadGeneratorStage:
    """
    WORK stage that generates load for stress testing.
    """
    name = "load_generator"
    kind = StageKind.WORK

    def __init__(self, target_concurrent: int):
        self.target_concurrent = target_concurrent
        self.generated_count = 0

    async def execute(self, ctx: StageContext) -> StageOutput:
        self.generated_count = self.target_concurrent
        return StageOutput.ok(
            load_generated=self.generated_count,
            target_concurrent=self.target_concurrent,
        )


class ConcurrentBatcherStage:
    """
    TRANSFORM stage that batches concurrent requests.
    """
    name = "concurrent_batcher"
    kind = StageKind.TRANSFORM

    def __init__(self, batch_size: int = 10):
        self.batch_size = batch_size
        self.batch_count = 0

    async def execute(self, ctx: StageContext) -> StageOutput:
        input_text = ctx.snapshot.input_text or ""
        priority = ctx.snapshot.priority or 5

        # Generate batch of concurrent requests
        batch = create_concurrent_test_batch(
            num_requests=self.batch_size,
            base_text=input_text or "concurrent request",
        )

        self.batch_count += 1

        return StageOutput.ok(
            batch=batch,
            batch_size=len(batch),
            batch_number=self.batch_count,
        )


class LatencyTrackerStage:
    """
    GUARD stage that tracks latency distribution.
    """
    name = "latency_tracker"
    kind = StageKind.GUARD

    def __init__(self, latency_threshold_ms: float = 100.0):
        self.latency_threshold_ms = latency_threshold_ms
        self.latencies: List[float] = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        processing_latency = ctx.inputs.get_from("stress_router", "processing_latency_ms", default=0.0)

        if processing_latency > self.latency_threshold_ms:
            return StageOutput.cancel(
                reason=f"Latency exceeded threshold: {processing_latency}ms > {self.latency_threshold_ms}ms",
                data={
                    "latency_ms": processing_latency,
                    "threshold_ms": self.latency_threshold_ms,
                }
            )

        self.latencies.append(processing_latency)

        return StageOutput.ok(
            latency_valid=True,
            latency_ms=processing_latency,
        )


def calculate_latency_percentile(latencies: List[float], percentile: float) -> float:
    """Calculate a latency percentile."""
    if not latencies:
        return 0.0
    sorted_latencies = sorted(latencies)
    index = int(len(sorted_latencies) * percentile / 100)
    return sorted_latencies[min(index, len(sorted_latencies) - 1)]


async def run_stress_test(
    load_scenario: LoadScenario,
    router_latency_ms: float = 5.0,
) -> StressTestResult:
    """Run a stress test at a specific load level."""
    logger.info(f"Running stress test: {load_scenario.name} ({load_scenario.concurrent_requests} concurrent)")

    # Create pipeline with stress router
    pipeline = Pipeline(name=f"route003_stress_{load_scenario.id}")
    router_stage = StressRouterStage(base_latency_ms=router_latency_ms)
    pipeline.with_stage("stress_router", router_stage, StageKind.ROUTE)

    results: List[Dict[str, Any]] = []
    latencies: List[float] = []
    route_distribution: Dict[str, int] = defaultdict(int)
    errors: List[Dict[str, Any]] = []
    lock = asyncio.Lock()

    async def execute_request(request_id: int, priority: int = 5) -> Dict[str, Any]:
        """Execute a single routing request."""
        start_time = time.time()

        # Create context
        snapshot = ContextSnapshot(
            input_text=f"Stress test request {request_id}",
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            topology="route003_stress_test",
            execution_mode="test",
            priority=priority,
        )

        state = PipelineState(snapshot=snapshot)

        try:
            async for stage_name, event, data in pipeline.run(state):
                if event == "stage_error":
                    raise Exception(f"Stage error in {stage_name}: {data}")

            # Extract results
            final_output = state.output
            route_output = final_output.get("stress_router", {}).get("route") if final_output else None
            confidence = final_output.get("stress_router", {}).get("confidence") if final_output else 0.0
            processing_latency = final_output.get("stress_router", {}).get("processing_latency_ms") if final_output else 0.0

            end_time = time.time()
            latency_ms = (end_time - start_time) * 1000

            result = {
                "request_id": request_id,
                "success": True,
                "route": route_output,
                "confidence": confidence,
                "latency_ms": latency_ms,
                "processing_latency_ms": processing_latency,
            }

            async with lock:
                latencies.append(latency_ms)
                if route_output:
                    route_distribution[route_output] += 1
                results.append(result)

            return result

        except Exception as e:
            async with lock:
                errors.append({
                    "request_id": request_id,
                    "error": str(e),
                    "timestamp": time.time(),
                })
                results.append({
                    "request_id": request_id,
                    "success": False,
                    "error": str(e),
                })

            return {"request_id": request_id, "success": False, "error": str(e)}

    # Execute concurrent requests
    start_time = time.time()

    # Create tasks with staggered start for ramp-up
    tasks = []
    ramp_up_delay = load_scenario.ramp_up_ms / load_scenario.concurrent_requests if load_scenario.concurrent_requests > 0 else 0

    for i in range(load_scenario.concurrent_requests):
        priority = (i % 10) + 1  # Varied priorities
        task = asyncio.create_task(execute_request(i, priority))
        tasks.append(task)

        # Stagger starts for ramp-up
        if ramp_up_delay > 0:
            await asyncio.sleep(ramp_up_delay / 1000)

    # Wait for all tasks with timeout
    timeout_seconds = load_scenario.duration_seconds + 10
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning(f"Stress test timed out after {timeout_seconds} seconds")
        # Cancel remaining tasks
        for task in tasks:
            if not task.done():
                task.cancel()

    end_time = time.time()
    total_duration = end_time - start_time

    # Calculate metrics
    successful = sum(1 for r in results if r.get("success"))
    failed = len(results) - successful

    p50_lat = calculate_latency_percentile(latencies, 50)
    p95_lat = calculate_latency_percentile(latencies, 95)
    p99_lat = calculate_latency_percentile(latencies, 99)
    mean_lat = mean(latencies) if latencies else 0.0

    throughput = successful / total_duration if total_duration > 0 else 0.0
    error_rate = failed / len(results) if results else 0.0

    return StressTestResult(
        load_level=load_scenario.id,
        concurrent_requests=load_scenario.concurrent_requests,
        total_requests=len(results),
        successful_requests=successful,
        failed_requests=failed,
        p50_latency_ms=p50_lat,
        p95_latency_ms=p95_lat,
        p99_latency_ms=p99_lat,
        mean_latency_ms=mean_lat,
        throughput_per_second=throughput,
        error_rate=error_rate,
        route_distribution=dict(route_distribution),
        errors=errors,
    )


async def run_all_stress_tests() -> Dict[str, Any]:
    """Run stress tests at all load levels."""
    results = {}
    start_time = time.time()

    logger.info("Starting ROUTE-003 stress tests at all load levels")

    # Test each load level
    for load_level, scenario in LOAD_SCENARIOS.items():
        result = await run_stress_test(scenario, router_latency_ms=5.0)
        results[load_level.value] = {
            "load_level": load_level.value,
            "concurrent_requests": result.concurrent_requests,
            "total_requests": result.total_requests,
            "successful": result.successful_requests,
            "failed": result.failed_requests,
            "p50_latency_ms": result.p50_latency_ms,
            "p95_latency_ms": result.p95_latency_ms,
            "p99_latency_ms": result.p99_latency_ms,
            "mean_latency_ms": result.mean_latency_ms,
            "throughput_per_second": result.throughput_per_second,
            "error_rate": result.error_rate,
            "route_distribution": result.route_distribution,
        }

        logger.info(f"  {load_level.value}: {result.successful_requests}/{result.total_requests} successful, "
                   f"P95 latency: {result.p95_latency_ms:.2f}ms, "
                   f"Throughput: {result.throughput_per_second:.2f} req/s")

    end_time = time.time()

    return {
        "total_duration_seconds": end_time - start_time,
        "load_level_results": results,
    }


async def run_scalability_test() -> Dict[str, Any]:
    """Test scalability by increasing concurrent requests."""
    logger.info("Running scalability test")

    test_results = []
    concurrent_levels = [1, 5, 10, 20, 50, 100]

    for level in concurrent_levels:
        scenario = LoadScenario(
            id=f"scale-{level}",
            name=f"Scalability test {level} concurrent",
            concurrent_requests=level,
            duration_seconds=30,
            ramp_up_ms=level * 10,
            target_throughput=level * 10,
            description=f"Testing with {level} concurrent requests",
        )

        result = await run_stress_test(scenario, router_latency_ms=5.0)
        test_results.append({
            "concurrent_level": level,
            "p95_latency_ms": result.p95_latency_ms,
            "throughput": result.throughput_per_second,
            "error_rate": result.error_rate,
        })

        logger.info(f"  Level {level}: P95 latency={result.p95_latency_ms:.2f}ms, "
                   f"throughput={result.throughput_per_second:.2f} req/s")

    # Calculate scalability metrics
    baseline_p95 = test_results[0]["p95_latency_ms"] if test_results else 0
    for result in test_results:
        result["latency_degradation"] = (
            result["p95_latency_ms"] / baseline_p95 if baseline_p95 > 0 else 0
        )

    return {
        "scalability_results": test_results,
        "baseline_p95_latency_ms": baseline_p95,
    }


async def run_priority_stress_test() -> Dict[str, Any]:
    """Test priority handling under stress."""
    logger.info("Running priority stress test")

    # Create scenarios with different priorities
    priority_results: Dict[int, List[Dict[str, Any]]] = defaultdict(list)

    for priority in range(1, 11):
        scenario = LoadScenario(
            id=f"priority-{priority}",
            name=f"Priority {priority} test",
            concurrent_requests=20,
            duration_seconds=30,
            ramp_up_ms=500,
            target_throughput=200.0,
            description=f"Testing priority {priority}",
        )

        result = await run_stress_test(scenario, router_latency_ms=5.0)
        priority_results[priority] = result.route_distribution

        logger.info(f"  Priority {priority}: route distribution = {dict(result.route_distribution)}")

    return {
        "priority_results": {k: dict(v) for k, v in priority_results.items()},
    }


if __name__ == "__main__":
    import json

    # Run stress tests
    stress_results = asyncio.run(run_all_stress_tests())

    # Run scalability test
    scalability_results = asyncio.run(run_scalability_test())

    # Run priority test
    priority_results = asyncio.run(run_priority_stress_test())

    # Output results
    print("\n" + "="*60)
    print("ROUTE-003 Stress Test Results")
    print("="*60)

    print("\n--- Load Level Results ---")
    for level, data in stress_results["load_level_results"].items():
        print(f"{level}: P95={data['p95_latency_ms']:.2f}ms, "
              f"throughput={data['throughput_per_second']:.2f} req/s, "
              f"error_rate={data['error_rate']*100:.2f}%")

    print("\n--- Scalability Results ---")
    for result in scalability_results["scalability_results"]:
        print(f"Level {result['concurrent_level']}: "
              f"P95 latency={result['p95_latency_ms']:.2f}ms, "
              f"latency degradation={result['latency_degradation']:.2f}x")

    print("="*60)
