"""
Service mocks for ROUTE-003 dynamic routing under load testing.

This module provides mock services for simulating backend behavior,
latency injection, and failure scenarios.
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional
from datetime import datetime, UTC

logger = logging.getLogger(__name__)


@dataclass
class RoutingMetrics:
    """Metrics tracking for routing under load."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    latency_sum_ms: float = 0.0
    latencies: List[float] = field(default_factory=list)
    route_counts: Dict[str, int] = field(default_factory=dict)
    fallback_count: int = 0
    error_counts: Dict[str, int] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    
    def record_request(
        self,
        latency_ms: float,
        route: str,
        success: bool,
        fallback_used: bool,
        error_code: Optional[str] = None,
    ):
        self.total_requests += 1
        self.latency_sum_ms += latency_ms
        self.latencies.append(latency_ms)
        self.route_counts[route] = self.route_counts.get(route, 0) + 1
        
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
            if error_code:
                self.error_counts[error_code] = self.error_counts.get(error_code, 0) + 1
        
        if fallback_used:
            self.fallback_count += 1
    
    def get_percentile(self, percentile: float) -> float:
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * percentile / 100)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]
    
    def get_summary(self) -> Dict[str, Any]:
        elapsed = time.time() - self.start_time
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "error_rate": self.failed_requests / max(1, self.total_requests),
            "throughput_per_second": self.total_requests / max(0.1, elapsed),
            "p50_latency_ms": self.get_percentile(50),
            "p95_latency_ms": self.get_percentile(95),
            "p99_latency_ms": self.get_percentile(99),
            "avg_latency_ms": self.latency_sum_ms / max(1, self.total_requests),
            "route_counts": self.route_counts,
            "fallback_count": self.fallback_count,
            "error_counts": self.error_counts,
        }


class MockBackendService:
    """Mock backend service that simulates routing targets with configurable behavior."""
    
    def __init__(
        self,
        name: str,
        base_latency_ms: float = 50,
        failure_rate: float = 0.0,
        jitter_ms: int = 10,
    ):
        self.name = name
        self.base_latency_ms = base_latency_ms
        self.failure_rate = failure_rate
        self.jitter_ms = jitter_ms
        self.is_healthy = True
        self.metrics = RoutingMetrics()
    
    async def handle_request(
        self,
        request_id: str,
        route: str,
        priority: int = 5,
        injected_latency_ms: int = 0,
    ) -> Dict[str, Any]:
        """Handle a routing request with simulated latency and potential failure."""
        start_time = time.time()
        
        # Check health
        if not self.is_healthy:
            self.metrics.record_request(
                latency_ms=(time.time() - start_time) * 1000,
                route=route,
                success=False,
                fallback_used=False,
                error_code="SERVICE_UNHEALTHY",
            )
            raise Exception(f"Service {self.name} is unhealthy")
        
        # Check for injected failure
        if random.random() < self.failure_rate:
            self.metrics.record_request(
                latency_ms=(time.time() - start_time) * 1000,
                route=route,
                success=False,
                fallback_used=False,
                error_code="RANDOM_FAILURE",
            )
            raise Exception(f"Random failure in {self.name}")
        
        # Calculate latency
        latency = self.base_latency_ms + random.randint(-self.jitter_ms, self.jitter_ms)
        if injected_latency_ms > 0:
            latency += injected_latency_ms
        
        # Simulate processing
        await asyncio.sleep(latency / 1000)
        
        actual_latency = (time.time() - start_time) * 1000
        self.metrics.record_request(
            latency_ms=actual_latency,
            route=route,
            success=True,
            fallback_used=False,
        )
        
        return {
            "request_id": request_id,
            "route": route,
            "backend": self.name,
            "latency_ms": actual_latency,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    
    def set_failure_rate(self, rate: float):
        self.failure_rate = rate
    
    def set_healthy(self, healthy: bool):
        self.is_healthy = healthy


class LoadGenerator:
    """Generates concurrent load for stress testing."""
    
    def __init__(
        self,
        backends: Dict[str, MockBackendService],
        on_request: Optional[Callable] = None,
    ):
        self.backends = backends
        self.on_request = on_request
        self.metrics = RoutingMetrics()
        self.active_tasks: List[asyncio.Task] = []
    
    async def execute_concurrent_requests(
        self,
        num_requests: int,
        route: str = "standard",
        priority: int = 5,
        max_concurrent: int = 50,
    ) -> List[Dict[str, Any]]:
        """Execute requests concurrently with semaphore limiting."""
        results = []
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def execute_one(request_id: str) -> Dict[str, Any]:
            async with semaphore:
                start_time = time.time()
                try:
                    # Route to appropriate backend
                    backend_name = self._get_backend_for_route(route)
                    backend = self.backends[backend_name]
                    
                    result = await backend.handle_request(
                        request_id=request_id,
                        route=route,
                        priority=priority,
                    )
                    
                    self.metrics.record_request(
                        latency_ms=(time.time() - start_time) * 1000,
                        route=route,
                        success=True,
                        fallback_used=False,
                    )
                    
                    if self.on_request:
                        self.on_request(result)
                    
                    return {"request_id": request_id, "success": True, "result": result}
                    
                except Exception as e:
                    self.metrics.record_request(
                        latency_ms=(time.time() - start_time) * 1000,
                        route=route,
                        success=False,
                        fallback_used=False,
                        error_code=type(e).__name__,
                    )
                    return {"request_id": request_id, "success": False, "error": str(e)}
        
        # Create all tasks
        for i in range(num_requests):
            request_id = f"req-{i:04d}"
            task = asyncio.create_task(execute_one(request_id))
            self.active_tasks.append(task)
        
        # Wait for completion
        results = await asyncio.gather(*self.active_tasks, return_exceptions=True)
        self.active_tasks.clear()
        
        return results
    
    def _get_backend_for_route(self, route: str) -> str:
        """Map route to backend service."""
        route_backend_map = {
            "fast": "fast_backend",
            "standard": "standard_backend",
            "premium": "premium_backend",
            "escalation": "escalation_backend",
            "fallback": "fallback_backend",
        }
        return route_backend_map.get(route, "standard_backend")
    
    def get_metrics(self) -> Dict[str, Any]:
        return self.metrics.get_summary()


class LatencyInjector:
    """Injects artificial latency for chaos testing."""
    
    def __init__(self, base_delay_ms: int = 0, jitter_ms: int = 100):
        self.base_delay_ms = base_delay_ms
        self.jitter_ms = jitter_ms
        self.is_active = False
        self.injected_requests = 0
    
    async def add_latency(self):
        """Add simulated latency to a request."""
        if not self.is_active:
            return
        
        delay = self.base_delay_ms + random.randint(-self.jitter_ms, self.jitter_ms)
        await asyncio.sleep(delay / 1000)
        self.injected_requests += 1
    
    def activate(self, delay_ms: int, jitter_ms: int = 100):
        self.base_delay_ms = delay_ms
        self.jitter_ms = jitter_ms
        self.is_active = True
    
    def deactivate(self):
        self.is_active = False
    
    def reset(self):
        self.injected_requests = 0
        self.is_active = False


class ResourceSimulator:
    """Simulates resource pressure for stress testing."""
    
    def __init__(
        self,
        memory_limit_mb: int = 512,
        cpu_limit_percent: int = 80,
    ):
        self.memory_limit_mb = memory_limit_mb
        self.cpu_limit_percent = cpu_limit_percent
        self.current_memory_mb = 100
        self.current_cpu_percent = 20
        self.is_under_pressure = False
    
    def apply_pressure(self, memory_mb: int, cpu_percent: int):
        """Apply resource pressure."""
        self.current_memory_mb = memory_mb
        self.current_cpu_percent = cpu_percent
        self.is_under_pressure = (
            self.current_memory_mb > self.memory_limit_mb * 0.8 or
            self.current_cpu_percent > self.cpu_limit_percent * 0.8
        )
    
    def release_pressure(self):
        """Release resource pressure."""
        self.current_memory_mb = 100
        self.current_cpu_percent = 20
        self.is_under_pressure = False
    
    def get_status(self) -> Dict[str, Any]:
        return {
            "memory_mb": self.current_memory_mb,
            "memory_limit_mb": self.memory_limit_mb,
            "memory_used_percent": (self.current_memory_mb / self.memory_limit_mb) * 100,
            "cpu_percent": self.current_cpu_percent,
            "cpu_limit_percent": self.cpu_limit_percent,
            "is_under_pressure": self.is_under_pressure,
        }


def create_test_services() -> Dict[str, MockBackendService]:
    """Create a set of backend services for testing."""
    return {
        "fast_backend": MockBackendService(
            name="fast_backend",
            base_latency_ms=20,
            failure_rate=0.01,
            jitter_ms=5,
        ),
        "standard_backend": MockBackendService(
            name="standard_backend",
            base_latency_ms=50,
            failure_rate=0.02,
            jitter_ms=10,
        ),
        "premium_backend": MockBackendService(
            name="premium_backend",
            base_latency_ms=100,
            failure_rate=0.01,
            jitter_ms=20,
        ),
        "escalation_backend": MockBackendService(
            name="escalation_backend",
            base_latency_ms=200,
            failure_rate=0.05,
            jitter_ms=50,
        ),
        "fallback_backend": MockBackendService(
            name="fallback_backend",
            base_latency_ms=80,
            failure_rate=0.10,
            jitter_ms=30,
        ),
    }
