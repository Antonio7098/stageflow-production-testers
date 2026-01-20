"""
Simplified baseline pipeline for ROUTE-003: Dynamic routing under load.

Uses correct Stageflow API based on documentation examples.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import asyncio
import time
import uuid
import logging
import random
from enum import Enum

from stageflow import (
    Pipeline,
    StageContext,
    StageKind,
    StageOutput,
    StageGraph,
    StageInputs,
    PipelineTimer,
    create_test_snapshot,
    create_test_stage_context,
)
from stageflow.context import ContextSnapshot, RunIdentity

import sys
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])
from mocks.route003_mock_data import (
    RouteType,
    RoutingRequest,
    HAPPY_PATH_SCENARIOS,
    EDGE_CASE_SCENARIOS,
    GOLDEN_OUTPUTS,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SimpleRouterStage:
    """
    Simple ROUTE stage for baseline testing.
    Makes routing decisions based on input text patterns.
    """
    name = "simple_router"
    kind = StageKind.ROUTE

    ROUTE_PATTERNS = {
        RouteType.FAST_PATH: ["weather", "time", "hello", "hi"],
        RouteType.PREMIUM_PATH: ["enterprise", "upgrade", "business", "vip"],
        RouteType.ESCALATION: ["broken", "critical", "urgent", "emergency", "complaint"],
        RouteType.STANDARD_PATH: [],
    }

    async def execute(self, ctx: StageContext) -> StageOutput:
        input_text = ctx.snapshot.input_text or ""
        # Priority is stored in metadata for testing
        priority = ctx.snapshot.metadata.get("priority", 5) if ctx.snapshot.metadata else 5

        route = RouteType.STANDARD_PATH.value
        confidence = 0.5

        for route_type, patterns in self.ROUTE_PATTERNS.items():
            if route_type == RouteType.STANDARD_PATH:
                continue
            if any(pattern in input_text.lower() for pattern in patterns):
                route = route_type.value
                confidence = 0.95
                break

        if priority >= 8:
            route = RouteType.ESCALATION.value
            confidence = max(confidence, 0.9)

        return StageOutput.ok(
            route=route,
            confidence=confidence,
            priority=priority,
        )


class FallbackRouterStage:
    """ROUTE stage with fallback support."""
    name = "fallback_router"
    kind = StageKind.ROUTE

    def __init__(self, fail_primary_after: int = 0):
        self.request_count = 0
        self.fail_primary_after = fail_primary_after

    async def execute(self, ctx: StageContext) -> StageOutput:
        self.request_count += 1
        input_text = ctx.snapshot.input_text or ""
        priority = ctx.snapshot.metadata.get("priority", 5) if ctx.snapshot.metadata else 5

        if use_fallback:
            return StageOutput.ok(
                route=RouteType.FALLBACK.value,
                confidence=0.8,
                fallback_triggered=True,
            )

        if "test fallback" in input_text.lower():
            return StageOutput.ok(
                route=RouteType.FALLBACK.value,
                confidence=0.7,
                fallback_triggered=False,
            )

        return StageOutput.ok(
            route=RouteType.STANDARD_PATH.value,
            confidence=0.9,
            fallback_triggered=False,
        )


class ResponseValidatorStage:
    """GUARD stage for validating routing outcomes."""
    name = "response_validator"
    kind = StageKind.GUARD

    def __init__(self, expected_route: Optional[str] = None):
        self.expected_route = expected_route

    async def execute(self, ctx: StageContext) -> StageOutput:
        route_output = ctx.inputs.get_from("simple_router", "route", default="unknown")
        confidence = ctx.inputs.get_from("simple_router", "confidence", default=0.0)

        if self.expected_route and route_output != self.expected_route:
            return StageOutput.cancel(
                reason=f"Unexpected route: {route_output}",
                data={"unexpected_route": route_output, "expected_route": self.expected_route}
            )

        if confidence < 0.5:
            return StageOutput.cancel(
                reason=f"Low confidence: {confidence}",
                data={"confidence": confidence}
            )

        return StageOutput.ok(validation_passed=True, route=route_output, confidence=confidence)


def create_baseline_pipeline() -> Pipeline:
    """Create the baseline routing pipeline."""
    return Pipeline().with_stage(
        "simple_router", SimpleRouterStage(), StageKind.ROUTE
    )


def create_fallback_pipeline(fail_primary_after: int = 0) -> Pipeline:
    """Create pipeline with fallback routing."""
    fallback_stage = FallbackRouterStage(fail_primary_after=fail_primary_after)
    return Pipeline().with_stage(
        "fallback_router", fallback_stage, StageKind.ROUTE
    )


async def run_single_test(
    scenario: RoutingRequest,
    expected_route: RouteType,
    pipeline: Pipeline,
) -> Dict[str, Any]:
    """Run a single routing test."""
    start_time = time.time()

    # Create context snapshot with priority in metadata
    snapshot = create_test_snapshot(
        input_text=scenario.input_text,
        user_id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        topology="route003_baseline",
        execution_mode="test",
    )
    # Store priority in metadata
    snapshot.metadata["priority"] = scenario.priority

    try:
        # Build and run pipeline
        graph = pipeline.build()
        ctx = create_test_stage_context(snapshot=snapshot)
        results = await graph.run(ctx)

        end_time = time.time()
        latency_ms = (end_time - start_time) * 1000

        # Extract results - results is a dict of StageOutput objects
        router_output = results.get("simple_router") or results.get("fallback_router")
        if router_output:
            route = router_output.data.get("route")
            confidence = router_output.data.get("confidence")
        else:
            route = None
            confidence = None

        success = route == expected_route.value

        return {
            "scenario_id": scenario.id,
            "success": success,
            "expected_route": expected_route.value,
            "actual_route": route,
            "confidence": confidence,
            "latency_ms": latency_ms,
            "error": None if success else f"Route mismatch: expected {expected_route.value}, got {route}",
        }

    except Exception as e:
        return {
            "scenario_id": scenario.id,
            "success": False,
            "expected_route": expected_route.value,
            "actual_route": None,
            "confidence": None,
            "latency_ms": None,
            "error": str(e),
        }


async def run_baseline_tests() -> Dict[str, Any]:
    """Run all baseline routing tests."""
    pipeline = create_baseline_pipeline()
    results = []
    start_time = time.time()

    logger.info("Starting ROUTE-003 baseline tests")

    for scenario in HAPPY_PATH_SCENARIOS:
        result = await run_single_test(scenario, scenario.expected_route, pipeline)
        results.append(result)
        logger.info(f"Test {scenario.id}: {'PASS' if result['success'] else 'FAIL'}")

    for scenario in EDGE_CASE_SCENARIOS:
        result = await run_single_test(scenario, scenario.expected_route, pipeline)
        results.append(result)
        logger.info(f"Edge case {scenario.id}: {'PASS' if result['success'] else 'FAIL'}")

    end_time = time.time()
    passed = sum(1 for r in results if r["success"])
    failed = len(results) - passed

    return {
        "total_tests": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": passed / len(results) if results else 0,
        "total_duration_seconds": end_time - start_time,
        "results": results,
    }


async def run_concurrent_test(num_concurrent: int = 10) -> Dict[str, Any]:
    """Run concurrent baseline tests."""
    logger.info(f"Running concurrent test with {num_concurrent} requests")

    pipeline = create_baseline_pipeline()
    results = []
    lock = asyncio.Lock()

    async def run_test(index: int):
        scenario = HAPPY_PATH_SCENARIOS[index % len(HAPPY_PATH_SCENARIOS)]
        result = await run_single_test(scenario, scenario.expected_route, pipeline)
        async with lock:
            results.append(result)

    start_time = time.time()
    tasks = [run_test(i) for i in range(num_concurrent)]
    await asyncio.gather(*tasks)
    end_time = time.time()

    routes_taken = {}
    for r in results:
        if r.get("actual_route"):
            routes_taken[r["actual_route"]] = routes_taken.get(r["actual_route"], 0) + 1

    passed = sum(1 for r in results if r["success"])

    return {
        "concurrent_requests": num_concurrent,
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": passed / num_concurrent,
        "total_duration_seconds": end_time - start_time,
        "route_distribution": routes_taken,
        "results": results,
    }


if __name__ == "__main__":
    baseline_results = asyncio.run(run_baseline_tests())
    concurrent_results = asyncio.run(run_concurrent_test(num_concurrent=10))

    print("\n" + "=" * 60)
    print("ROUTE-003 Baseline Test Results")
    print("=" * 60)
    print(f"Baseline: {baseline_results['passed']}/{baseline_results['total_tests']} passed")
    print(f"Concurrent: {concurrent_results['passed']}/{concurrent_results['concurrent_requests']} passed")
    print(f"Route distribution: {concurrent_results['route_distribution']}")
    print("=" * 60)
