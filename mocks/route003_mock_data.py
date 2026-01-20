"""
Mock data for ROUTE-003: Dynamic routing under load testing.

This module provides mock routing scenarios, load profiles, and failure injection
data for stress-testing Stageflow's dynamic routing under concurrent load.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import uuid
import time
import asyncio


class RouteType(Enum):
    """Enum representing different route targets for testing."""
    FAST_PATH = "fast"
    STANDARD_PATH = "standard"
    PREMIUM_PATH = "premium"
    ESCALATION = "escalation"
    FALLBACK = "fallback"
    ERROR = "error"


class LoadLevel(Enum):
    """Load levels for stress testing."""
    BASELINE = 1
    LIGHT = 10
    MODERATE = 50
    HEAVY = 100
    EXTREME = 200


@dataclass
class LoadScenario:
    """Represents a load testing scenario."""
    id: str
    name: str
    concurrent_requests: int
    duration_seconds: int
    ramp_up_ms: int
    target_throughput: float
    description: str


@dataclass
class RoutingRequest:
    """Represents a single routing request for testing."""
    id: str
    input_text: str
    priority: int
    timestamp: float
    expected_route: RouteType
    context_factors: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutingOutcome:
    """Expected routing outcome for validation."""
    route: RouteType
    latency_ms: float
    success: bool
    fallback_used: bool
    error_code: Optional[str] = None


@dataclass
class FailureInjection:
    """Represents a failure injection point."""
    id: str
    failure_type: str
    target_component: str
    trigger_after_requests: int
    duration_ms: int
    params: Dict[str, Any] = field(default_factory=dict)


# Load scenarios for different stress levels
LOAD_SCENARIOS = {
    LoadLevel.BASELINE: LoadScenario(
        id="load-baseline",
        name="Single Request Baseline",
        concurrent_requests=1,
        duration_seconds=30,
        ramp_up_ms=0,
        target_throughput=10.0,
        description="Single request to establish baseline metrics",
    ),
    LoadLevel.LIGHT: LoadScenario(
        id="load-light",
        name="Light Load (10 concurrent)",
        concurrent_requests=10,
        duration_seconds=60,
        ramp_up_ms=1000,
        target_throughput=100.0,
        description="Normal operation range",
    ),
    LoadLevel.MODERATE: LoadScenario(
        id="load-moderate",
        name="Moderate Load (50 concurrent)",
        concurrent_requests=50,
        duration_seconds=60,
        ramp_up_ms=2000,
        target_throughput=500.0,
        description="Peak expected load",
    ),
    LoadLevel.HEAVY: LoadScenario(
        id="load-heavy",
        name="Heavy Load (100 concurrent)",
        concurrent_requests=100,
        duration_seconds=60,
        ramp_up_ms=3000,
        target_throughput=1000.0,
        description="Stress testing range",
    ),
    LoadLevel.EXTREME: LoadScenario(
        id="load-extreme",
        name="Extreme Load (200 concurrent)",
        concurrent_requests=200,
        duration_seconds=30,
        ramp_up_ms=5000,
        target_throughput=1500.0,
        description="Burst/spike simulation",
    ),
}

# Happy path scenarios - clear routing under normal conditions
HAPPY_PATH_SCENARIOS = [
    RoutingRequest(
        id="route-001",
        input_text="I need help with my account login",
        priority=5,
        timestamp=0.0,
        expected_route=RouteType.STANDARD_PATH,
        context_factors={"intent": "login_help", "urgency": "medium"},
    ),
    RoutingRequest(
        id="route-002",
        input_text="What's the weather today?",
        priority=3,
        timestamp=0.0,
        expected_route=RouteType.FAST_PATH,
        context_factors={"intent": "general_query", "complexity": "low"},
    ),
    RoutingRequest(
        id="route-003",
        input_text="I want to upgrade to enterprise plan",
        priority=7,
        timestamp=0.0,
        expected_route=RouteType.PREMIUM_PATH,
        context_factors={"intent": "sales", "value": "high"},
    ),
    RoutingRequest(
        id="route-004",
        input_text="The system is completely broken and nothing works",
        priority=9,
        timestamp=0.0,
        expected_route=RouteType.ESCALATION,
        context_factors={"intent": "critical_issue", "severity": "high"},
    ),
]

# Concurrency stress scenarios - designed to trigger race conditions
CONCURRENCY_SCENARIOS = [
    RoutingRequest(
        id=f"conc-{i:03d}",
        input_text=f"Request {i} with standard priority",
        priority=5,
        timestamp=time.time(),
        expected_route=RouteType.STANDARD_PATH,
        context_factors={"scenario": "concurrency_test", "index": i},
    )
    for i in range(50)
]

# Latency stress scenarios - designed to test routing under delayed responses
LATENCY_SCENARIOS = [
    RoutingRequest(
        id=f"lat-{i:03d}",
        input_text=f"Query {i} requiring routing decision",
        priority=5,
        timestamp=time.time(),
        expected_route=RouteType.STANDARD_PATH,
        context_factors={"scenario": "latency_test", "index": i},
    )
    for i in range(100)
]

# Fallback scenarios - testing fallback path under load
FALLBACK_SCENARIOS = [
    RoutingRequest(
        id=f"fallback-{i:03d}",
        input_text=f"Request {i} that may need fallback",
        priority=5,
        timestamp=time.time(),
        expected_route=RouteType.STANDARD_PATH,
        context_factors={"scenario": "fallback_test", "index": i, "require_fallback": i % 5 == 0},
    )
    for i in range(100)
]

# Failure injection scenarios
FAILURE_INJECTION_SCENARIOS = [
    FailureInjection(
        id="fail-llm-timeout",
        failure_type="latency",
        target_component="llm_router",
        trigger_after_requests=10,
        duration_ms=5000,
        params={"delay_ms": 2000, "jitter_ms": 500},
    ),
    FailureInjection(
        id="fail-backend-error",
        failure_type="error",
        target_component="standard_handler",
        trigger_after_requests=20,
        duration_ms=3000,
        params={"error_rate": 1.0, "error_code": "SERVICE_UNAVAILABLE"},
    ),
    FailureInjection(
        id="fail-memory-pressure",
        failure_type="resource",
        target_component="routing_cache",
        trigger_after_requests=30,
        duration_ms=5000,
        params={"memory_limit_percent": 90},
    ),
]

# Edge cases - boundary conditions
EDGE_CASE_SCENARIOS = [
    RoutingRequest(
        id="edge-empty",
        input_text="",
        priority=1,
        timestamp=0.0,
        expected_route=RouteType.FAST_PATH,
        context_factors={"edge_case": "empty_input"},
    ),
    RoutingRequest(
        id="edge-max-length",
        input_text="x" * 10000,
        priority=5,
        timestamp=0.0,
        expected_route=RouteType.STANDARD_PATH,
        context_factors={"edge_case": "max_length_input"},
    ),
    RoutingRequest(
        id="edge-null-char",
        input_text="Hello\x00World",
        priority=5,
        timestamp=0.0,
        expected_route=RouteType.FAST_PATH,
        context_factors={"edge_case": "null_characters"},
    ),
    RoutingRequest(
        id="edge-unicode",
        input_text="你好世界 Привет мир 🌍",
        priority=5,
        timestamp=0.0,
        expected_route=RouteType.STANDARD_PATH,
        context_factors={"edge_case": "unicode_input"},
    ),
]

# Race condition scenarios - designed to trigger concurrent access issues
RACE_CONDITION_SCENARIOS = [
    RoutingRequest(
        id=f"race-{i:03d}",
        input_text=f"Race test request {i} updating shared routing state",
        priority=5,
        timestamp=0.0,
        expected_route=RouteType.STANDARD_PATH,
        context_factors={
            "scenario": "race_condition",
            "index": i,
            "shared_state_update": True,
        },
    )
    for i in range(100)
]

# Priority inversion scenarios
PRIORITY_SCENARIOS = [
    RoutingRequest(
        id=f"priority-{i:03d}",
        input_text=f"Priority {i % 10} request",
        priority=i % 10,
        timestamp=0.0,
        expected_route=RouteType.STANDARD_PATH,
        context_factors={"scenario": "priority_test", "base_priority": i % 10},
    )
    for i in range(200)
]


# Golden outputs for baseline validation
GOLDEN_OUTPUTS = {
    scenario.id: RoutingOutcome(
        route=scenario.expected_route,
        latency_ms=50.0,
        success=True,
        fallback_used=False,
    )
    for scenario in HAPPY_PATH_SCENARIOS
}


# Resource constraints for stress testing
RESOURCE_CONSTRAINTS = {
    "memory_mb": 512,
    "cpu_percent": 80,
    "max_concurrent_connections": 100,
    "queue_size": 1000,
    "timeout_ms": 5000,
}


@dataclass
class PerformanceMetrics:
    """Metrics for routing performance evaluation."""
    scenario_id: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    throughput_per_second: float
    error_rate: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "throughput_per_second": self.throughput_per_second,
            "error_rate": self.error_rate,
        }


def create_mock_routing_context(
    request: RoutingRequest,
    load_level: LoadLevel = LoadLevel.BASELINE,
) -> Dict[str, Any]:
    """Create a mock context for routing based on request and load level."""
    return {
        "input_text": request.input_text,
        "session_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "topology": "routing_load_test",
        "execution_mode": "test",
        "priority": request.priority,
        "load_level": load_level.value,
        "context_factors": request.context_factors,
        "routing_metadata": {
            "request_id": request.id,
            "scenario": "load_test",
            "timestamp": request.timestamp,
        },
    }


def create_concurrent_test_batch(
    num_requests: int,
    base_text: str = "Concurrent test request",
) -> List[RoutingRequest]:
    """Create a batch of concurrent routing requests."""
    requests = []
    base_time = time.time()
    for i in range(num_requests):
        requests.append(
            RoutingRequest(
                id=f"batch-{i:04d}",
                input_text=f"{base_text} {i}",
                priority=5,
                timestamp=base_time + (i * 0.001),  # 1ms apart
                expected_route=RouteType.STANDARD_PATH,
                context_factors={"batch_index": i, "total_in_batch": num_requests},
            )
        )
    return requests


async def simulate_load_generator(
    scenario: LoadScenario,
    on_request: callable,
    on_failure: Optional[callable] = None,
) -> List[Dict[str, Any]]:
    """Simulate load generation for a scenario."""
    results = []
    active_tasks = []
    
    async def execute_request(request: RoutingRequest):
        try:
            result = await on_request(request)
            results.append({"request_id": request.id, "success": True, "result": result})
        except Exception as e:
            results.append({"request_id": request.id, "success": False, "error": str(e)})
            if on_failure:
                on_failure(e)
    
    # Create all concurrent tasks
    for _ in range(scenario.concurrent_requests):
        request = RoutingRequest(
            id=str(uuid.uuid4()),
            input_text="Load test request",
            priority=5,
            timestamp=time.time(),
            expected_route=RouteType.STANDARD_PATH,
        )
        task = asyncio.create_task(execute_request(request))
        active_tasks.append(task)
    
    # Wait for completion with timeout
    try:
        await asyncio.wait_for(asyncio.gather(*active_tasks), timeout=scenario.duration_seconds)
    except asyncio.TimeoutError:
        pass  # Some tasks may still be running
    
    return results
