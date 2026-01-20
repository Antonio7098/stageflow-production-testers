"""
Chaos pipeline for ROUTE-003: Dynamic routing under load.

Injects failures and edge cases to test ROUTE stage resilience:
- Latency injection
- Error responses
- Resource pressure
- Race conditions
- Network partitions
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import asyncio
import time
import uuid
import json
import logging
import random
from enum import Enum
from collections import defaultdict

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
    FailureInjection,
    FAILURE_INJECTION_SCENARIOS,
    EDGE_CASE_SCENARIOS,
    RACE_CONDITION_SCENARIOS,
)
from pipelines.route003_baseline import SimpleRouterStage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FailureType(Enum):
    """Types of failures to inject."""
    LATENCY_SPIKE = "latency"
    ERROR_RESPONSE = "error"
    RESOURCE_PRESSURE = "resource"
    NULL_RESPONSE = "null"
    TIMEOUT = "timeout"
    ROUTE_CONFUSION = "confusion"


@dataclass
class ChaosTestResult:
    """Result of a chaos test run."""
    test_name: str
    failure_type: str
    total_requests: int
    successful_requests: int
    fallback_activations: int
    errors: List[Dict[str, Any]]
    routes_taken: Dict[str, int]
    recovery_time_ms: Optional[float] = None
    silent_failures: List[Dict[str, Any]] = field(default_factory=list)


class ChaosRouterStage:
    """
    ROUTE stage with configurable failure injection.
    Used to test system behavior under various failure scenarios.
    """
    name = "chaos_router"
    kind = StageKind.ROUTE

    def __init__(self, failure_injection: Optional[FailureInjection] = None):
        self.failure_injection = failure_injection
        self.request_count = 0
        self.active_failures: List[Dict[str, Any]] = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        self.request_count += 1
        input_text = ctx.snapshot.input_text or ""
        priority = ctx.snapshot.priority or 5

        # Check if failure should be triggered
        if self._should_inject_failure():
            return self._handle_failure(ctx)

        # Normal routing logic
        return await self._normal_routing(input_text, priority)

    def _should_inject_failure(self) -> bool:
        """Determine if failure should be injected."""
        if not self.failure_injection:
            return False

        if self.request_count < self.failure_injection.trigger_after_requests:
            return False

        elapsed = time.time() - (self.active_failures[-1]["start_time"] if self.active_failures else 0)
        if elapsed > self.failure_injection.duration_ms / 1000:
            return False

        return True

    def _handle_failure(self, ctx: StageContext) -> StageOutput:
        """Handle injected failure."""
        failure_type = self.failure_injection.failure_type

        if failure_type == "latency":
            # Simulate latency spike
            delay_ms = self.failure_injection.params.get("delay_ms", 2000)
            time.sleep(delay_ms / 1000)
            return StageOutput.ok(
                route=RouteType.STANDARD_PATH.value,
                confidence=0.5,
                failure_injected=True,
                failure_type="latency",
                latency_delay_ms=delay_ms,
            )

        elif failure_type == "error":
            # Return error response
            error_code = self.failure_injection.params.get("error_code", "SERVICE_UNAVAILABLE")
            return StageOutput.fail(
                error=f"Simulated failure: {error_code}",
                data={
                    "failure_injected": True,
                    "failure_type": "error",
                    "error_code": error_code,
                }
            )

        elif failure_type == "resource":
            # Simulate resource pressure
            memory_limit = self.failure_injection.params.get("memory_limit_percent", 90)
            return StageOutput.ok(
                route=RouteType.FALLBACK.value,
                confidence=0.3,
                failure_injected=True,
                failure_type="resource",
                memory_usage_percent=memory_limit,
                fallback_reason="resource_pressure",
            )

        return StageOutput.ok(
            route=RouteType.STANDARD_PATH.value,
            confidence=0.5,
        )

    async def _normal_routing(self, input_text: str, priority: int) -> StageOutput:
        """Perform normal routing decision."""
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
        )


class FallbackRouterStage:
    """
    ROUTE stage with robust fallback handling.
    """
    name = "fallback_router"
    kind = StageKind.ROUTE

    def __init__(self, max_fallback_depth: int = 3):
        self.max_fallback_depth = max_fallback_depth
        self.fallback_count = 0
        self.request_count = 0

    async def execute(self, ctx: StageContext) -> StageOutput:
        self.request_count += 1
        input_text = ctx.snapshot.input_text or ""
        priority = ctx.snapshot.priority or 5

        # Check for failure from previous stages
        previous_error = ctx.inputs.get_from("chaos_router", "error", default=None)
        failure_injected = ctx.inputs.get_from("chaos_router", "failure_injected", default=False)
        failure_type = ctx.inputs.get_from("chaos_router", "failure_type", default=None)

        # Handle failures with fallback
        if failure_injected:
            return self._handle_with_fallback(failure_type, priority)

        # Normal routing
        return self._normal_routing(input_text, priority)

    def _handle_with_fallback(self, failure_type: Optional[str], priority: int) -> StageOutput:
        """Handle routing with fallback activation."""
        self.fallback_count += 1

        if failure_type == "error":
            return StageOutput.ok(
                route=RouteType.FALLBACK.value,
                confidence=0.7,
                fallback_activated=True,
                fallback_reason=f"primary_error_{failure_type}",
                fallback_depth=1,
                primary_failure_type=failure_type,
            )

        if failure_type == "resource":
            return StageOutput.ok(
                route=RouteType.FALLBACK.value,
                confidence=0.6,
                fallback_activated=True,
                fallback_reason="resource_pressure",
                fallback_depth=1,
            )

        return StageOutput.ok(
            route=RouteType.STANDARD_PATH.value,
            confidence=0.5,
            fallback_activated=False,
        )

    def _normal_routing(self, input_text: str, priority: int) -> StageOutput:
        """Normal routing logic."""
        route = RouteType.STANDARD_PATH.value
        confidence = 0.8

        if "weather" in input_text.lower():
            route = RouteType.FAST_PATH.value
            confidence = 0.95
        elif "enterprise" in input_text.lower():
            route = RouteType.PREMIUM_PATH.value
            confidence = 0.95
        elif "broken" in input_text.lower() or priority >= 8:
            route = RouteType.ESCALATION.value
            confidence = 0.95

        return StageOutput.ok(
            route=route,
            confidence=confidence,
            priority=priority,
            fallback_activated=False,
        )


class SilentFailureDetectorStage:
    """
    GUARD stage that detects silent failures.
    """
    name = "silent_failure_detector"
    kind = StageKind.GUARD

    def __init__(self, expected_route: str):
        self.expected_route = expected_route
        self.silent_failures: List[Dict[str, Any]] = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        route = ctx.inputs.get_from("fallback_router", "route", default="unknown")
        confidence = ctx.inputs.get_from("fallback_router", "confidence", default=0.0)
        fallback_activated = ctx.inputs.get_from("fallback_router", "fallback_activated", default=False)

        # Check for silent failures
        issues = []

        # Issue 1: Route doesn't match expected but no error was raised
        if route != self.expected_route and not fallback_activated:
            issues.append("route_mismatch_without_fallback")

        # Issue 2: Very low confidence with success
        if confidence < 0.3:
            issues.append("low_confidence_success")

        # Issue 3: Missing required output fields
        if route is None or route == "unknown":
            issues.append("missing_route_output")

        if issues:
            return StageOutput.cancel(
                reason=f"Silent failure detected: {', '.join(issues)}",
                data={
                    "silent_failure": True,
                    "issues": issues,
                    "actual_route": route,
                    "expected_route": self.expected_route,
                    "confidence": confidence,
                }
            )

        return StageOutput.ok(
            silent_failure_check_passed=True,
            route=route,
            confidence=confidence,
        )


class LatencyInjectionStage:
    """
    TRANSFORM stage that injects latency spikes.
    """
    name = "latency_injector"
    kind = StageKind.TRANSFORM

    def __init__(self, inject_after_n: int = 5, spike_duration_ms: int = 1000):
        self.inject_after_n = inject_after_n
        self.spike_duration_ms = spike_duration_ms
        self.request_count = 0

    async def execute(self, ctx: StageContext) -> StageOutput:
        self.request_count += 1

        # Inject latency spike
        if self.request_count > self.inject_after_n:
            await asyncio.sleep(self.spike_duration_ms / 1000)
            return StageOutput.ok(
                latency_injected=True,
                spike_duration_ms=self.spike_duration_ms,
                request_number=self.request_count,
            )

        return StageOutput.ok(
            latency_injected=False,
            request_number=self.request_count,
        )


class ErrorResponseStage:
    """
    WORK stage that simulates error responses.
    """
    name = "error_simulator"
    kind = StageKind.WORK

    def __init__(self, error_rate: float = 0.1):
        self.error_rate = error_rate
        self.error_count = 0

    async def execute(self, ctx: StageContext) -> StageOutput:
        if random.random() < self.error_rate:
            self.error_count += 1
            return StageOutput.fail(
                error="Simulated transient error",
                data={
                    "error_type": "transient",
                    "error_count": self.error_count,
                }
            )

        return StageOutput.ok(
            no_error=True,
            error_count=self.error_count,
        )


async def run_chaos_test(
    test_name: str,
    failure_type: FailureType,
    num_requests: int = 50,
) -> ChaosTestResult:
    """Run a chaos test with a specific failure type."""
    logger.info(f"Running chaos test: {test_name} ({failure_type.value})")

    results: List[Dict[str, Any]] = []
    routes_taken: Dict[str, int] = defaultdict(int)
    fallback_activations = 0
    errors: List[Dict[str, Any]] = []
    silent_failures: List[Dict[str, Any]] = []
    lock = asyncio.Lock()

    async def execute_with_chaos(request_id: int):
        """Execute a request with chaos injection."""
        start_time = time.time()

        # Create context
        snapshot = ContextSnapshot(
            input_text=f"Chaos test request {request_id}",
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            topology="route003_chaos_test",
            execution_mode="test",
            priority=5,
        )

        state = PipelineState(snapshot=snapshot)

        try:
            # Simple routing with potential failure
            router = ChaosRouterStage()

            # Inject failure based on type
            if failure_type == FailureType.LATENCY_SPIKE and request_id >= 10:
                await asyncio.sleep(0.5)  # 500ms delay

            if failure_type == FailureType.ERROR_RESPONSE and request_id % 5 == 0:
                raise Exception("Simulated routing error")

            if failure_type == FailureType.NULL_RESPONSE and request_id % 7 == 0:
                # Return null route - potential silent failure
                route = None
                confidence = None
                result = {
                    "request_id": request_id,
                    "success": True,  # Claimed success but no valid route!
                    "route": None,
                    "confidence": None,
                }
                async with lock:
                    results.append(result)
                    if result.get("route"):
                        routes_taken[result["route"]] += 1
                    else:
                        silent_failures.append({
                            "request_id": request_id,
                            "pattern": "null_route_output",
                            "description": "Route returned null without error",
                        })
                return result

            # Normal routing
            ctx = StageContext(snapshot=snapshot)
            output = await router.execute(ctx)

            if output.status == "ok":
                route = output.data.get("route", RouteType.STANDARD_PATH.value)
                confidence = output.data.get("confidence", 0.5)
                result = {
                    "request_id": request_id,
                    "success": True,
                    "route": route,
                    "confidence": confidence,
                }
            else:
                # Handle fallback
                result = {
                    "request_id": request_id,
                    "success": False,
                    "error": output.data.get("error", "Unknown error"),
                    "fallback_may_trigger": True,
                }
                async with lock:
                    errors.append(result)

            async with lock:
                results.append(result)
                if result.get("route"):
                    routes_taken[result["route"]] += 1
                if result.get("fallback_activated"):
                    fallback_activations += 1

            return result

        except Exception as e:
            async with lock:
                errors.append({
                    "request_id": request_id,
                    "error": str(e),
                })
                results.append({
                    "request_id": request_id,
                    "success": False,
                    "error": str(e),
                })
            return {"request_id": request_id, "success": False, "error": str(e)}

    # Execute concurrent requests
    start_time = time.time()
    tasks = [execute_with_chaos(i) for i in range(num_requests)]
    await asyncio.gather(*tasks)
    end_time = time.time()

    successful = sum(1 for r in results if r.get("success"))
    failed = len(results) - successful

    return ChaosTestResult(
        test_name=test_name,
        failure_type=failure_type.value,
        total_requests=num_requests,
        successful_requests=successful,
        fallback_activations=fallback_activations,
        errors=errors,
        routes_taken=dict(routes_taken),
        silent_failures=silent_failures,
    )


async def run_edge_case_tests() -> Dict[str, Any]:
    """Run edge case tests."""
    logger.info("Running edge case tests")

    edge_case_results = []

    for scenario in EDGE_CASE_SCENARIOS:
        result = await run_chaos_test(
            test_name=f"edge_case_{scenario.id}",
            failure_type=FailureType.NULL_RESPONSE,
            num_requests=1,
        )

        edge_case_results.append({
            "scenario_id": scenario.id,
            "input_text": scenario.input_text,
            "expected_route": scenario.expected_route.value,
            "result": {
                "success": result.successful_requests > 0,
                "routes_taken": result.routes_taken,
                "silent_failures": result.silent_failures,
            }
        })

        logger.info(f"  Edge case {scenario.id}: "
                   f"routes={result.routes_taken}, "
                   f"silent_failures={len(result.silent_failures)}")

    return {"edge_case_results": edge_case_results}


async def run_race_condition_test() -> Dict[str, Any]:
    """Test for race conditions in concurrent routing."""
    logger.info("Running race condition test")

    # Test with shared state modification
    shared_state = {"routes": []}
    lock = asyncio.Lock()
    results: List[Dict[str, Any]] = []

    async def concurrent_router(request_id: int):
        """Concurrent routing with shared state."""
        nonlocal shared_state

        # Simulate routing decision
        route = f"route_{request_id % 3}"

        # Race condition: concurrent modification of shared state
        async with lock:
            shared_state["routes"].append((request_id, route))

        # Small delay to increase race window
        await asyncio.sleep(random.uniform(0.001, 0.005))

        # Check for inconsistencies
        async with lock:
            if len(shared_state["routes"]) != len(set(r[1] for r in shared_state["routes"])):
                pass  # Potential race

        results.append({
            "request_id": request_id,
            "route": route,
            "shared_state_size": len(shared_state["routes"]),
        })

    # Execute concurrent requests
    num_requests = 100
    tasks = [concurrent_router(i) for i in range(num_requests)]
    await asyncio.gather(*tasks)

    # Analyze results
    routes = [r["route"] for r in results]
    route_counts = {}
    for route in routes:
        route_counts[route] = route_counts.get(route, 0) + 1

    return {
        "race_condition_test": {
            "total_requests": num_requests,
            "route_distribution": route_counts,
            "shared_state_size": len(shared_state["routes"]),
            "potential_races": len(shared_state["routes"]) - len(set(r[1] for r in shared_state["routes"])),
        }
    }


async def run_all_chaos_tests() -> Dict[str, Any]:
    """Run all chaos tests."""
    results = {}
    start_time = time.time()

    logger.info("Starting ROUTE-003 chaos tests")

    # Test each failure type
    for failure_type in FailureType:
        test_name = f"chaos_{failure_type.value}"
        result = await run_chaos_test(test_name, failure_type, num_requests=50)
        results[failure_type.value] = {
            "test_name": result.test_name,
            "total_requests": result.total_requests,
            "successful": result.successful_requests,
            "failed": result.failed_requests,
            "fallback_activations": result.fallback_activations,
            "routes_taken": result.routes_taken,
            "silent_failures_count": len(result.silent_failures),
        }

        logger.info(f"  {failure_type.value}: "
                   f"{result.successful_requests}/{result.total_requests} successful, "
                   f"fallbacks={result.fallback_activations}, "
                   f"silent_failures={len(result.silent_failures)}")

    # Run edge case tests
    edge_results = await run_edge_case_tests()
    results["edge_cases"] = edge_results

    # Run race condition test
    race_results = await run_race_condition_test()
    results["race_condition"] = race_results

    end_time = time.time()

    return {
        "total_duration_seconds": end_time - start_time,
        "chaos_test_results": results,
    }


if __name__ == "__main__":
    import json

    # Run chaos tests
    chaos_results = asyncio.run(run_all_chaos_tests())

    print("\n" + "="*60)
    print("ROUTE-003 Chaos Test Results")
    print("="*60)

    for test_type, data in chaos_results["chaos_test_results"].items():
        if test_type in ["edge_cases", "race_condition"]:
            continue

        print(f"\n{test_type}:")
        print(f"  Successful: {data['successful']}/{data['total_requests']}")
        print(f"  Fallback activations: {data['fallback_activations']}")
        print(f"  Silent failures: {data['silent_failures_count']}")
        print(f"  Route distribution: {data['routes_taken']}")

    if "race_condition" in chaos_results["chaos_test_results"]:
        race_data = chaos_results["chaos_test_results"]["race_condition"]["race_condition_test"]
        print(f"\nRace condition test:")
        print(f"  Potential races: {race_data['potential_races']}")

    print("="*60)
