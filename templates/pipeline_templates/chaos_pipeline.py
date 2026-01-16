"""
Stageflow Stress-Testing: Chaos Pipeline Template

A template for creating chaos engineering test pipelines.
Injects controlled failures to test resilience.
"""

import asyncio
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ChaosType(Enum):
    """Types of chaos that can be injected."""
    LATENCY = "latency"
    ERROR = "error"
    TIMEOUT = "timeout"
    CORRUPT_OUTPUT = "corrupt_output"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    NETWORK_PARTITION = "network_partition"


@dataclass
class ChaosConfig:
    """Configuration for chaos injection."""
    
    # Which chaos types to enable
    enabled_chaos: list[ChaosType] = field(default_factory=lambda: [
        ChaosType.LATENCY,
        ChaosType.ERROR,
    ])
    
    # Probability of chaos occurring (0.0 to 1.0)
    chaos_probability: float = 0.1
    
    # Latency injection settings
    latency_min_ms: int = 100
    latency_max_ms: int = 5000
    
    # Error injection settings
    error_types: list[str] = field(default_factory=lambda: [
        "ConnectionError",
        "TimeoutError",
        "ValueError",
        "RuntimeError",
    ])
    
    # Timeout settings
    timeout_probability: float = 0.05
    
    # Output corruption settings
    corruption_types: list[str] = field(default_factory=lambda: [
        "missing_field",
        "wrong_type",
        "truncated",
        "duplicated",
    ])


# =============================================================================
# Chaos Injection Functions
# =============================================================================

async def inject_latency(config: ChaosConfig) -> None:
    """Inject artificial latency."""
    delay_ms = random.randint(config.latency_min_ms, config.latency_max_ms)
    await asyncio.sleep(delay_ms / 1000)


def inject_error(config: ChaosConfig) -> None:
    """Raise a random error."""
    error_type = random.choice(config.error_types)
    error_classes = {
        "ConnectionError": ConnectionError,
        "TimeoutError": TimeoutError,
        "ValueError": ValueError,
        "RuntimeError": RuntimeError,
    }
    error_class = error_classes.get(error_type, RuntimeError)
    raise error_class(f"Chaos injection: {error_type}")


def corrupt_output(data: dict[str, Any], config: ChaosConfig) -> dict[str, Any]:
    """Corrupt the output data in various ways."""
    corruption = random.choice(config.corruption_types)
    corrupted = data.copy()
    
    if corruption == "missing_field" and corrupted:
        key = random.choice(list(corrupted.keys()))
        del corrupted[key]
    
    elif corruption == "wrong_type":
        if corrupted:
            key = random.choice(list(corrupted.keys()))
            corrupted[key] = "CORRUPTED_TYPE"
    
    elif corruption == "truncated":
        # Truncate string values
        for key, value in corrupted.items():
            if isinstance(value, str) and len(value) > 5:
                corrupted[key] = value[:5]
    
    elif corruption == "duplicated":
        # Duplicate a field with wrong name
        if corrupted:
            key = random.choice(list(corrupted.keys()))
            corrupted[f"{key}_duplicate"] = corrupted[key]
    
    return corrupted


# =============================================================================
# Chaos Interceptor
# =============================================================================

class ChaosInterceptor:
    """
    Interceptor that injects chaos into pipeline execution.
    
    Use this with Stageflow's interceptor system to inject
    controlled failures at various points in the pipeline.
    """
    
    def __init__(self, config: ChaosConfig):
        self.config = config
        self.chaos_events: list[dict[str, Any]] = []
    
    def should_inject_chaos(self) -> bool:
        """Determine if chaos should be injected."""
        return random.random() < self.config.chaos_probability
    
    def select_chaos_type(self) -> ChaosType:
        """Select which type of chaos to inject."""
        return random.choice(self.config.enabled_chaos)
    
    async def before_stage(self, stage_name: str, context: Any) -> None:
        """Called before each stage executes."""
        if not self.should_inject_chaos():
            return
        
        chaos_type = self.select_chaos_type()
        
        event = {
            "stage": stage_name,
            "chaos_type": chaos_type.value,
            "phase": "before",
        }
        
        if chaos_type == ChaosType.LATENCY:
            await inject_latency(self.config)
            event["injected"] = True
        
        elif chaos_type == ChaosType.ERROR:
            event["injected"] = True
            self.chaos_events.append(event)
            inject_error(self.config)
        
        elif chaos_type == ChaosType.TIMEOUT:
            # Simulate a very long delay that will likely timeout
            event["injected"] = True
            await asyncio.sleep(300)  # 5 minutes
        
        self.chaos_events.append(event)
    
    def after_stage(self, stage_name: str, output: Any) -> Any:
        """Called after each stage executes."""
        if not self.should_inject_chaos():
            return output
        
        chaos_type = self.select_chaos_type()
        
        if chaos_type == ChaosType.CORRUPT_OUTPUT and isinstance(output, dict):
            event = {
                "stage": stage_name,
                "chaos_type": chaos_type.value,
                "phase": "after",
                "injected": True,
            }
            self.chaos_events.append(event)
            return corrupt_output(output, self.config)
        
        return output
    
    def get_chaos_report(self) -> dict[str, Any]:
        """Get a report of all chaos events that occurred."""
        return {
            "total_events": len(self.chaos_events),
            "events": self.chaos_events,
            "by_type": self._count_by_type(),
            "by_stage": self._count_by_stage(),
        }
    
    def _count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self.chaos_events:
            chaos_type = event.get("chaos_type", "unknown")
            counts[chaos_type] = counts.get(chaos_type, 0) + 1
        return counts
    
    def _count_by_stage(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self.chaos_events:
            stage = event.get("stage", "unknown")
            counts[stage] = counts.get(stage, 0) + 1
        return counts


# =============================================================================
# Chaos Pipeline Builder
# =============================================================================

def create_chaos_pipeline(
    base_pipeline: Any,
    chaos_config: ChaosConfig,
) -> tuple[Any, ChaosInterceptor]:
    """
    Wrap a base pipeline with chaos injection.
    
    Args:
        base_pipeline: The pipeline to wrap
        chaos_config: Chaos configuration
        
    Returns:
        Tuple of (wrapped_pipeline, chaos_interceptor)
    """
    interceptor = ChaosInterceptor(chaos_config)
    
    # TODO: Implement using actual Stageflow API
    # wrapped = base_pipeline.with_interceptor(interceptor)
    # return wrapped, interceptor
    
    raise NotImplementedError("Implement using actual Stageflow API")


# =============================================================================
# Chaos Test Scenarios
# =============================================================================

@dataclass
class ChaosScenario:
    """Definition of a chaos test scenario."""
    name: str
    description: str
    config: ChaosConfig
    expected_behavior: str
    success_criteria: Callable[[dict[str, Any]], bool]


# Pre-defined chaos scenarios
CHAOS_SCENARIOS = [
    ChaosScenario(
        name="high_latency",
        description="Inject high latency to test timeout handling",
        config=ChaosConfig(
            enabled_chaos=[ChaosType.LATENCY],
            chaos_probability=0.5,
            latency_min_ms=1000,
            latency_max_ms=10000,
        ),
        expected_behavior="Pipeline should timeout gracefully or complete within extended timeout",
        success_criteria=lambda r: r.get("success") or r.get("error", {}).get("type") == "TimeoutError",
    ),
    ChaosScenario(
        name="intermittent_errors",
        description="Inject random errors to test retry logic",
        config=ChaosConfig(
            enabled_chaos=[ChaosType.ERROR],
            chaos_probability=0.3,
        ),
        expected_behavior="Pipeline should retry and eventually succeed, or fail gracefully",
        success_criteria=lambda r: True,  # Any outcome is valid for this test
    ),
    ChaosScenario(
        name="output_corruption",
        description="Corrupt stage outputs to test validation",
        config=ChaosConfig(
            enabled_chaos=[ChaosType.CORRUPT_OUTPUT],
            chaos_probability=0.2,
        ),
        expected_behavior="Pipeline should detect corruption via contract validation",
        success_criteria=lambda r: not r.get("success") or "validation" in str(r.get("error", "")),
    ),
    ChaosScenario(
        name="mixed_chaos",
        description="All chaos types enabled at low probability",
        config=ChaosConfig(
            enabled_chaos=list(ChaosType),
            chaos_probability=0.1,
        ),
        expected_behavior="Pipeline should handle various failure modes",
        success_criteria=lambda r: True,
    ),
]


async def run_chaos_scenario(
    scenario: ChaosScenario,
    pipeline_factory: Callable[[], Any],
    input_data: dict[str, Any],
    iterations: int = 10,
) -> dict[str, Any]:
    """
    Run a chaos scenario multiple times and collect results.
    
    Args:
        scenario: The chaos scenario to run
        pipeline_factory: Function that creates a fresh pipeline
        input_data: Input data for the pipeline
        iterations: Number of times to run the scenario
        
    Returns:
        Aggregated results from all iterations
    """
    results = {
        "scenario": scenario.name,
        "iterations": iterations,
        "successes": 0,
        "failures": 0,
        "chaos_events": [],
        "individual_results": [],
    }
    
    for i in range(iterations):
        pipeline = pipeline_factory()
        wrapped, interceptor = create_chaos_pipeline(pipeline, scenario.config)
        
        try:
            # TODO: Execute pipeline
            # output = await wrapped.execute(input_data)
            # result = {"success": True, "output": output}
            raise NotImplementedError()
        except Exception as e:
            result = {"success": False, "error": {"type": type(e).__name__, "message": str(e)}}
        
        # Check success criteria
        if scenario.success_criteria(result):
            results["successes"] += 1
        else:
            results["failures"] += 1
        
        results["chaos_events"].extend(interceptor.chaos_events)
        results["individual_results"].append(result)
    
    return results


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    print("Chaos Pipeline Template")
    print("=" * 50)
    print("\nAvailable chaos scenarios:")
    for scenario in CHAOS_SCENARIOS:
        print(f"\n  {scenario.name}:")
        print(f"    {scenario.description}")
        print(f"    Expected: {scenario.expected_behavior}")
    
    print("\nNOTE: Implement using actual Stageflow API")
