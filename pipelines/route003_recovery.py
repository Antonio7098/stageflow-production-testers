"""
Recovery pipeline for ROUTE-003: Dynamic routing under load.

Tests recovery from failures, circuit breaker behavior, and graceful degradation.
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
from datetime import datetime
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
    FAILURE_INJECTION_SCENARIOS,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RecoveryState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5  # Failures before opening
    success_threshold: int = 3  # Successes needed to close
    timeout_ms: int = 5000  # Time before trying half-open
    monitoring_window_ms: int = 10000


@dataclass
class RecoveryTestResult:
    """Result of a recovery test."""
    test_name: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    circuit_breaker_state_changes: List[Dict[str, Any]]
    recovery_time_ms: Optional[float]
    graceful_degradation_activations: int
    cascading_failures: int


class CircuitBreakerRouterStage:
    """
    ROUTE stage with circuit breaker pattern for resilience.
    """
    name = "circuit_breaker_router"
    kind = StageKind.ROUTE

    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        self.config = config or CircuitBreakerConfig()
        self.state = RecoveryState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.state_history: List[Dict[str, Any]] = []
        self.last_failure_time: Optional[float] = None
        self.request_count = 0

    def _record_state_change(self, old_state: RecoveryState, new_state: RecoveryState):
        """Record a state change for analysis."""
        self.state_history.append({
            "timestamp": time.time(),
            "from_state": old_state.value,
            "to_state": new_state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
        })

    def _transition_to(self, new_state: RecoveryState):
        """Transition to a new state."""
        old_state = self.state
        if old_state != new_state:
            self._record_state_change(old_state, new_state)
            self.state = new_state
            logger.info(f"Circuit breaker: {old_state.value} -> {new_state.value}")

    async def execute(self, ctx: StageContext) -> StageOutput:
        self.request_count += 1
        input_text = ctx.snapshot.input_text or ""
        priority = ctx.snapshot.priority or 5

        # Check circuit breaker state
        if self.state == RecoveryState.OPEN:
            # Check if timeout has elapsed
            if self.last_failure_time:
                elapsed = (time.time() - self.last_failure_time) * 1000
                if elapsed >= self.config.timeout_ms:
                    self._transition_to(RecoveryState.HALF_OPEN)
                else:
                    return StageOutput.cancel(
                        reason="Circuit breaker open",
                        data={
                            "circuit_breaker": "open",
                            "retry_after_ms": self.config.timeout_ms - elapsed,
                        }
                    )

        # Simulate potential failure
        should_fail = random.random() < 0.1  # 10% failure rate

        if self.state == RecoveryState.HALF_OPEN:
            # In half-open, allow limited requests
            if self.success_count >= self.config.success_threshold:
                self._transition_to(RecoveryState.CLOSED)
                self.failure_count = 0
            elif should_fail:
                self.failure_count += 1
                self.last_failure_time = time.time()
                self.success_count = 0
                self._transition_to(RecoveryState.OPEN)
                return StageOutput.cancel(
                    reason="Circuit breaker half-open test failed",
                    data={"circuit_breaker": "half_open_failed"}
                )
            else:
                self.success_count += 1

        # Normal operation
        if should_fail and self.state == RecoveryState.CLOSED:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.config.failure_threshold:
                self._transition_to(RecoveryState.OPEN)

            return StageOutput.fail(
                error="Simulated routing failure",
                data={
                    "circuit_breaker": self.state.value,
                    "failure_count": self.failure_count,
                }
            )

        # Success path
        if self.state == RecoveryState.CLOSED:
            self.success_count = max(0, self.success_count - 1)  # Decay failures slowly

        # Make routing decision
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
            circuit_breaker_state=self.state.value,
            request_number=self.request_count,
        )


class GracefulDegradationStage:
    """
    ROUTE stage with graceful degradation capabilities.
    Falls back to simpler routing when complex routing fails.
    """
    name = "graceful_degradation_router"
    kind = StageKind.ROUTE

    def __init__(self, degradation_threshold: float = 0.8):
        self.degradation_threshold = degradation_threshold
        self.primary_failures = 0
        self.degradation_activations = 0
        self.request_count = 0

    async def execute(self, ctx: StageContext) -> StageOutput:
        self.request_count += 1
        input_text = ctx.snapshot.input_text or ""
        priority = ctx.snapshot.priority or 5

        # Check for previous stage failures
        previous_error = ctx.inputs.get_from("circuit_breaker_router", "error", default=None)
        circuit_state = ctx.inputs.get_from("circuit_breaker_router", "circuit_breaker_state", default="closed")

        # Handle degraded mode
        if previous_error or circuit_state == "open":
            self.degradation_activations += 1
            return self._degraded_routing(input_text, priority)

        # Normal routing
        return self._normal_routing(input_text, priority)

    def _normal_routing(self, input_text: str, priority: int) -> StageOutput:
        """Full routing logic."""
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
            routing_mode="normal",
            primary_routing=True,
        )

    def _degraded_routing(self, input_text: str, priority: int) -> StageOutput:
        """Simplified routing for degraded mode."""
        # Simple priority-based routing
        if priority >= 8:
            route = RouteType.ESCALATION.value
        elif "weather" in input_text.lower():
            route = RouteType.FAST_PATH.value
        else:
            route = RouteType.STANDARD_PATH.value

        return StageOutput.ok(
            route=route,
            confidence=0.6,
            routing_mode="degraded",
            primary_routing=False,
            degradation_reason="primary_unavailable",
        )


class CascadingFailureDetectorStage:
    """
    GUARD stage that detects cascading failures.
    """
    name = "cascading_failure_detector"
    kind = StageKind.GUARD

    def __init__(self, cascade_threshold: int = 3):
        self.cascade_threshold = cascade_threshold
        self.failure_chain: List[Dict[str, Any]] = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        circuit_error = ctx.inputs.get_from("circuit_breaker_router", "error", default=None)
        degradation_mode = ctx.inputs.get_from("graceful_degradation_router", "routing_mode", default="normal")
        degradation_activations = ctx.inputs.get_from("graceful_degradation_router", "degradation_activations", default=0)

        # Check for cascading failures
        self.failure_chain.append({
            "timestamp": time.time(),
            "circuit_error": circuit_error is not None,
            "degradation_mode": degradation_mode,
        })

        # Detect cascade pattern
        recent_failures = sum(
            1 for f in self.failure_chain[-10:]
            if f["circuit_error"] or f["degradation_mode"] == "degraded"
        )

        if recent_failures >= self.cascade_threshold:
            return StageOutput.cancel(
                reason="Cascading failure detected",
                data={
                    "cascading_failure": True,
                    "recent_failures": recent_failures,
                    "cascade_threshold": self.cascade_threshold,
                }
            )

        return StageOutput.ok(
            cascading_check_passed=True,
            recent_failure_count=recent_failures,
        )


class RecoveryMetricsStage:
    """
    WORK stage for tracking recovery metrics.
    """
    name = "recovery_metrics"
    kind = StageKind.WORK

    def __init__(self, metrics_list: List[Dict[str, Any]]):
        self.metrics_list = metrics_list

    async def execute(self, ctx: StageContext) -> StageOutput:
        circuit_state = ctx.inputs.get_from("circuit_breaker_router", "circuit_breaker_state", default="closed")
        routing_mode = ctx.inputs.get_from("graceful_degradation_router", "routing_mode", default="normal")

        self.metrics_list.append({
            "timestamp": time.time(),
            "circuit_state": circuit_state,
            "routing_mode": routing_mode,
        })

        return StageOutput.ok(
            metrics_collected=True,
            circuit_state=circuit_state,
            routing_mode=routing_mode,
        )


async def run_circuit_breaker_test() -> Dict[str, Any]:
    """Test circuit breaker behavior."""
    logger.info("Running circuit breaker test")

    config = CircuitBreakerConfig(
        failure_threshold=5,
        success_threshold=3,
        timeout_ms=1000,
    )

    router = CircuitBreakerRouterStage(config=config)
    results: List[Dict[str, Any]] = []
    start_time = time.time()

    async def execute_request(request_id: int):
        """Execute a single request through the circuit breaker."""
        snapshot = ContextSnapshot(
            input_text=f"CB test request {request_id}",
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            topology="route003_circuit_breaker_test",
            execution_mode="test",
            priority=5,
        )

        ctx = StageContext(snapshot=snapshot)
        output = await router.execute(ctx)

        return {
            "request_id": request_id,
            "status": output.status,
            "route": output.data.get("route") if output.status == "ok" else None,
            "error": output.data.get("error") if output.status == "fail" else None,
            "circuit_state": output.data.get("circuit_breaker_state"),
            "timestamp": time.time(),
        }

    # Run test sequence
    # Phase 1: Normal operation
    logger.info("  Phase 1: Normal operation")
    for i in range(10):
        result = await execute_request(i)
        results.append(result)

    # Phase 2: Induce failures to open circuit
    logger.info("  Phase 2: Inducing failures")
    for i in range(10, 20):
        result = await execute_request(i)
        results.append(result)

    # Phase 3: Circuit should be open
    open_results = [r for r in results if r.get("circuit_state") == "open"]
    logger.info(f"  Circuit opened after {len(open_results)} requests in failure state")

    # Phase 4: Wait for timeout and recovery
    logger.info("  Phase 4: Waiting for recovery")
    await asyncio.sleep(1.5)  # Wait for timeout

    # Phase 5: Recovery attempts
    logger.info("  Phase 5: Recovery attempts")
    for i in range(20, 35):
        result = await execute_request(i)
        results.append(result)

    end_time = time.time()

    # Analyze results
    state_changes = router.state_history
    closed_count = sum(1 for r in results if r.get("circuit_state") == "closed")
    open_count = sum(1 for r in results if r.get("circuit_state") == "open")
    half_open_count = sum(1 for r in results if r.get("circuit_state") == "half_open")

    return {
        "test_name": "circuit_breaker",
        "total_requests": len(results),
        "successful": sum(1 for r in results if r["status"] == "ok"),
        "failed": sum(1 for r in results if r["status"] == "fail"),
        "cancelled": sum(1 for r in results if r["status"] == "cancel"),
        "state_distribution": {
            "closed": closed_count,
            "open": open_count,
            "half_open": half_open_count,
        },
        "state_changes": state_changes,
        "duration_seconds": end_time - start_time,
    }


async def run_graceful_degradation_test() -> Dict[str, Any]:
    """Test graceful degradation behavior."""
    logger.info("Running graceful degradation test")

    config = CircuitBreakerConfig(failure_threshold=3, timeout_ms=500)
    router = CircuitBreakerRouterStage(config=config)
    degrader = GracefulDegradationStage()

    results: List[Dict[str, Any]] = []
    degradation_count = 0
    start_time = time.time()

    async def execute_request(request_id: int):
        """Execute request through graceful degradation path."""
        nonlocal degradation_count

        snapshot = ContextSnapshot(
            input_text=f"Degradation test request {request_id}",
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            topology="route003_graceful_degradation_test",
            execution_mode="test",
            priority=5,
        )

        ctx = StageContext(snapshot=snapshot)

        # Execute circuit breaker
        cb_output = await router.execute(ctx)

        # Create fake context for degrader
        class FakeInputs:
            def get_from(self, stage, key, default=None):
                if stage == "circuit_breaker_router":
                    if key == "error":
                        return cb_output.data.get("error")
                    if key == "circuit_breaker_state":
                        return cb_output.data.get("circuit_breaker_state")
                return default

        ctx.inputs = FakeInputs()

        # Execute degrader
        gd_output = await degrader.execute(ctx)

        if gd_output.data.get("routing_mode") == "degraded":
            degradation_count += 1

        return {
            "request_id": request_id,
            "cb_status": cb_output.status,
            "gd_mode": gd_output.data.get("routing_mode"),
            "route": gd_output.data.get("route"),
            "confidence": gd_output.data.get("confidence"),
        }

    # Run test sequence
    # Phase 1: Normal operation
    for i in range(10):
        result = await execute_request(i)
        results.append(result)

    # Phase 2: Induce failures
    for i in range(10, 25):
        result = await execute_request(i)
        results.append(result)

    end_time = time.time()

    normal_mode = sum(1 for r in results if r["gd_mode"] == "normal")
    degraded_mode = sum(1 for r in results if r["gd_mode"] == "degraded")

    return {
        "test_name": "graceful_degradation",
        "total_requests": len(results),
        "normal_mode": normal_mode,
        "degraded_mode": degraded_mode,
        "degradation_rate": degraded_mode / len(results) if results else 0,
        "duration_seconds": end_time - start_time,
    }


async def run_recovery_test() -> Dict[str, Any]:
    """Test full recovery scenario."""
    logger.info("Running full recovery test")

    config = CircuitBreakerConfig(
        failure_threshold=5,
        success_threshold=3,
        timeout_ms=1000,
    )
    router = CircuitBreakerRouterStage(config=config)
    degrader = GracefulDegradationStage()
    detector = CascadingFailureDetectorStage(cascade_threshold=5)

    results: List[Dict[str, Any]] = []
    state_transitions = []
    start_time = time.time()

    async def execute_request(request_id: int):
        """Execute full request with recovery."""
        snapshot = ContextSnapshot(
            input_text=f"Recovery test request {request_id}",
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            topology="route003_recovery_test",
            execution_mode="test",
            priority=5,
        )

        ctx = StageContext(snapshot=snapshot)

        # Execute circuit breaker
        cb_output = await router.execute(ctx)

        # Record state transition
        current_state = cb_output.data.get("circuit_breaker_state")
        if state_transitions and state_transitions[-1] != current_state:
            state_transitions.append(current_state)

        # Create fake inputs for degrader
        class FakeInputs:
            def get_from(self, stage, key, default=None):
                if stage == "circuit_breaker_router":
                    if key == "error":
                        return cb_output.data.get("error")
                    if key == "circuit_breaker_state":
                        return cb_output.data.get("circuit_breaker_state")
                return default

        ctx.inputs = FakeInputs()

        # Execute degrader
        gd_output = await degrader.execute(ctx)

        return {
            "request_id": request_id,
            "cb_state": cb_output.data.get("circuit_breaker_state"),
            "gd_mode": gd_output.data.get("routing_mode"),
            "route": gd_output.data.get("route"),
            "status": cb_output.status,
        }

    # Run test sequence
    # Phase 1: Normal (requests 0-9)
    for i in range(10):
        results.append(await execute_request(i))

    # Phase 2: High failure rate (requests 10-24)
    for i in range(10, 25):
        results.append(await execute_request(i))

    # Phase 3: Recovery (requests 25-40)
    for i in range(25, 41):
        results.append(await execute_request(i))

    end_time = time.time()

    # Analyze
    phases = {
        "normal": results[0:10],
        "failure": results[10:25],
        "recovery": results[25:41],
    }

    phase_stats = {}
    for phase_name, phase_results in phases.items():
        states = {}
        for r in phase_results:
            state = r.get("cb_state", "unknown")
            states[state] = states.get(state, 0) + 1
        phase_stats[phase_name] = states

    return {
        "test_name": "full_recovery",
        "total_requests": len(results),
        "phase_statistics": phase_stats,
        "state_transitions": state_transitions,
        "duration_seconds": end_time - start_time,
    }


async def run_all_recovery_tests() -> Dict[str, Any]:
    """Run all recovery tests."""
    results = {}
    start_time = time.time()

    logger.info("Starting ROUTE-003 recovery tests")

    # Circuit breaker test
    cb_results = await run_circuit_breaker_test()
    results["circuit_breaker"] = cb_results
    logger.info(f"  Circuit breaker: {cb_results['successful']}/{cb_results['total_requests']} successful")

    # Graceful degradation test
    gd_results = await run_graceful_degradation_test()
    results["graceful_degradation"] = gd_results
    logger.info(f"  Graceful degradation: {gd_results['normal_mode']} normal, {gd_results['degraded_mode']} degraded")

    # Full recovery test
    rec_results = await run_recovery_test()
    results["full_recovery"] = rec_results
    logger.info(f"  Full recovery: {rec_results['phase_statistics']}")

    end_time = time.time()

    return {
        "total_duration_seconds": end_time - start_time,
        "recovery_test_results": results,
    }


if __name__ == "__main__":
    import json

    # Run recovery tests
    recovery_results = asyncio.run(run_all_recovery_tests())

    print("\n" + "="*60)
    print("ROUTE-003 Recovery Test Results")
    print("="*60)

    for test_name, data in recovery_results["recovery_test_results"].items():
        print(f"\n{test_name}:")
        if test_name == "circuit_breaker":
            print(f"  Total: {data['total_requests']}")
            print(f"  Successful: {data['successful']}")
            print(f"  State distribution: {data['state_distribution']}")
        elif test_name == "graceful_degradation":
            print(f"  Normal mode: {data['normal_mode']}")
            print(f"  Degraded mode: {data['degraded_mode']}")
        elif test_name == "full_recovery":
            print(f"  Phase statistics: {data['phase_statistics']}")

    print("="*60)
