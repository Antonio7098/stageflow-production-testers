"""
Stageflow Stress-Testing: Test Utilities

Shared test utilities, fixtures, and assertions.
"""

from .assertions import (
    # Correctness
    assert_output_matches_contract,
    assert_deterministic_output,
    assert_no_hallucination,
    # Reliability
    assert_graceful_degradation,
    assert_retry_behavior,
    assert_circuit_breaker_triggered,
    assert_idempotent,
    # Performance
    assert_latency_percentile,
    assert_throughput,
    assert_memory_bounded,
    assert_no_memory_leak,
    # Security
    assert_no_pii_leak,
    assert_injection_blocked,
    assert_tenant_isolation,
    # Observability
    assert_trace_complete,
    assert_correlation_id_propagated,
    assert_error_attributed,
    # Data Integrity
    assert_no_data_corruption,
    assert_ordering_preserved,
    assert_atomic_update,
)

__all__ = [
    # Correctness
    "assert_output_matches_contract",
    "assert_deterministic_output",
    "assert_no_hallucination",
    # Reliability
    "assert_graceful_degradation",
    "assert_retry_behavior",
    "assert_circuit_breaker_triggered",
    "assert_idempotent",
    # Performance
    "assert_latency_percentile",
    "assert_throughput",
    "assert_memory_bounded",
    "assert_no_memory_leak",
    # Security
    "assert_no_pii_leak",
    "assert_injection_blocked",
    "assert_tenant_isolation",
    # Observability
    "assert_trace_complete",
    "assert_correlation_id_propagated",
    "assert_error_attributed",
    # Data Integrity
    "assert_no_data_corruption",
    "assert_ordering_preserved",
    "assert_atomic_update",
]
