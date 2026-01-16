"""
Stageflow Stress-Testing: Pipeline Templates

Starter templates for building test pipelines.
"""

from .baseline_pipeline import (
    BaselineConfig,
    create_baseline_pipeline,
    run_baseline_test,
    assert_baseline_success,
    assert_within_timeout,
    assert_output_schema,
)

from .chaos_pipeline import (
    ChaosType,
    ChaosConfig,
    ChaosInterceptor,
    ChaosScenario,
    CHAOS_SCENARIOS,
    create_chaos_pipeline,
    run_chaos_scenario,
    inject_latency,
    inject_error,
    corrupt_output,
)

__all__ = [
    # Baseline
    "BaselineConfig",
    "create_baseline_pipeline",
    "run_baseline_test",
    "assert_baseline_success",
    "assert_within_timeout",
    "assert_output_schema",
    # Chaos
    "ChaosType",
    "ChaosConfig",
    "ChaosInterceptor",
    "ChaosScenario",
    "CHAOS_SCENARIOS",
    "create_chaos_pipeline",
    "run_chaos_scenario",
    "inject_latency",
    "inject_error",
    "corrupt_output",
]
