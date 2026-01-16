"""
Stageflow Stress-Testing: Custom Assertions

Domain-specific assertions for stress testing.
"""

from typing import Any


# =============================================================================
# Correctness Assertions
# =============================================================================

def assert_output_matches_contract(output: dict[str, Any], contract: type) -> None:
    """Assert that output matches the expected contract/schema."""
    try:
        # Assuming Pydantic model
        contract.model_validate(output)
    except Exception as e:
        raise AssertionError(f"Output does not match contract: {e}")


def assert_deterministic_output(
    outputs: list[dict[str, Any]],
    key: str | None = None,
) -> None:
    """Assert that multiple runs produce the same output."""
    if not outputs:
        return
    
    if key:
        values = [o.get(key) for o in outputs]
    else:
        values = outputs
    
    first = values[0]
    for i, value in enumerate(values[1:], 2):
        assert value == first, f"Output {i} differs from output 1"


def assert_no_hallucination(
    output: str,
    source_documents: list[str],
    threshold: float = 0.9,
) -> None:
    """Assert that output is grounded in source documents."""
    # Simplified check - in practice, use embedding similarity or NLI
    output_lower = output.lower()
    grounded_words = 0
    total_words = len(output_lower.split())
    
    for doc in source_documents:
        doc_lower = doc.lower()
        for word in output_lower.split():
            if len(word) > 3 and word in doc_lower:
                grounded_words += 1
    
    grounding_ratio = grounded_words / max(total_words, 1)
    assert grounding_ratio >= threshold, (
        f"Output grounding ratio {grounding_ratio:.2%} below threshold {threshold:.2%}"
    )


# =============================================================================
# Reliability Assertions
# =============================================================================

def assert_graceful_degradation(
    result: dict[str, Any],
    expected_fallback: str | None = None,
) -> None:
    """Assert that failure resulted in graceful degradation."""
    assert "error" in result or "fallback_used" in result, (
        "Expected either error handling or fallback usage"
    )
    
    if expected_fallback and "fallback_used" in result:
        assert result["fallback_used"] == expected_fallback, (
            f"Expected fallback '{expected_fallback}', got '{result['fallback_used']}'"
        )


def assert_retry_behavior(
    attempts: list[dict[str, Any]],
    max_retries: int,
    backoff_factor: float = 2.0,
) -> None:
    """Assert correct retry behavior with backoff."""
    assert len(attempts) <= max_retries + 1, (
        f"Too many attempts: {len(attempts)} > {max_retries + 1}"
    )
    
    # Check backoff timing
    for i in range(1, len(attempts)):
        prev_time = attempts[i - 1].get("timestamp", 0)
        curr_time = attempts[i].get("timestamp", 0)
        expected_delay = backoff_factor ** (i - 1)
        actual_delay = curr_time - prev_time
        
        # Allow 20% tolerance
        assert actual_delay >= expected_delay * 0.8, (
            f"Retry {i} delay {actual_delay}s less than expected {expected_delay}s"
        )


def assert_circuit_breaker_triggered(
    results: list[dict[str, Any]],
    failure_threshold: int,
) -> None:
    """Assert that circuit breaker was triggered after threshold failures."""
    consecutive_failures = 0
    circuit_open = False
    
    for result in results:
        if result.get("success"):
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if consecutive_failures >= failure_threshold:
                circuit_open = True
                break
    
    assert circuit_open, (
        f"Circuit breaker not triggered after {failure_threshold} failures"
    )


def assert_idempotent(
    first_result: dict[str, Any],
    second_result: dict[str, Any],
    ignore_keys: list[str] | None = None,
) -> None:
    """Assert that repeated execution produces same result (idempotency)."""
    ignore = set(ignore_keys or ["timestamp", "execution_id", "duration_ms"])
    
    def filter_dict(d: dict) -> dict:
        return {k: v for k, v in d.items() if k not in ignore}
    
    filtered_first = filter_dict(first_result)
    filtered_second = filter_dict(second_result)
    
    assert filtered_first == filtered_second, (
        "Results differ between executions (not idempotent)"
    )


# =============================================================================
# Performance Assertions
# =============================================================================

def assert_latency_percentile(
    latencies: list[float],
    percentile: int,
    max_ms: float,
) -> None:
    """Assert that a latency percentile is within bounds."""
    if not latencies:
        return
    
    sorted_latencies = sorted(latencies)
    idx = int(len(sorted_latencies) * percentile / 100)
    actual = sorted_latencies[min(idx, len(sorted_latencies) - 1)]
    
    assert actual <= max_ms, (
        f"P{percentile} latency {actual}ms exceeds max {max_ms}ms"
    )


def assert_throughput(
    operations: int,
    duration_seconds: float,
    min_ops_per_second: float,
) -> None:
    """Assert minimum throughput."""
    if duration_seconds <= 0:
        return
    
    actual_ops = operations / duration_seconds
    assert actual_ops >= min_ops_per_second, (
        f"Throughput {actual_ops:.2f} ops/s below minimum {min_ops_per_second} ops/s"
    )


def assert_memory_bounded(
    memory_samples: list[float],
    max_mb: float,
) -> None:
    """Assert memory usage stays within bounds."""
    if not memory_samples:
        return
    
    max_observed = max(memory_samples)
    assert max_observed <= max_mb, (
        f"Memory usage {max_observed}MB exceeds max {max_mb}MB"
    )


def assert_no_memory_leak(
    memory_samples: list[float],
    max_growth_rate: float = 0.1,
) -> None:
    """Assert memory doesn't grow unboundedly (potential leak)."""
    if len(memory_samples) < 10:
        return
    
    # Compare first and last quarters
    quarter = len(memory_samples) // 4
    first_quarter_avg = sum(memory_samples[:quarter]) / quarter
    last_quarter_avg = sum(memory_samples[-quarter:]) / quarter
    
    if first_quarter_avg > 0:
        growth_rate = (last_quarter_avg - first_quarter_avg) / first_quarter_avg
        assert growth_rate <= max_growth_rate, (
            f"Memory growth rate {growth_rate:.2%} exceeds max {max_growth_rate:.2%}"
        )


# =============================================================================
# Security Assertions
# =============================================================================

def assert_no_pii_leak(
    output: str,
    pii_patterns: list[str] | None = None,
) -> None:
    """Assert that output doesn't contain PII patterns."""
    import re
    
    default_patterns = [
        r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
        r"\b\d{16}\b",  # Credit card
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email
        r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",  # Phone
    ]
    
    patterns = pii_patterns or default_patterns
    
    for pattern in patterns:
        matches = re.findall(pattern, output)
        assert not matches, f"PII detected in output: {matches[:3]}..."


def assert_injection_blocked(
    result: dict[str, Any],
    injection_payload: str,
) -> None:
    """Assert that an injection attempt was blocked."""
    output = str(result.get("output", ""))
    
    # Check that the injection didn't execute
    dangerous_indicators = [
        "admin mode",
        "system override",
        "all user data",
        "secrets",
        "DROP TABLE",
    ]
    
    for indicator in dangerous_indicators:
        assert indicator.lower() not in output.lower(), (
            f"Injection may have succeeded: '{indicator}' found in output"
        )


def assert_tenant_isolation(
    tenant_a_data: dict[str, Any],
    tenant_b_result: dict[str, Any],
) -> None:
    """Assert that tenant A's data doesn't appear in tenant B's results."""
    # Serialize tenant A's sensitive data
    sensitive_values = []
    
    def extract_values(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                extract_values(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                extract_values(v, f"{path}[{i}]")
        elif isinstance(obj, str) and len(obj) > 5:
            sensitive_values.append(obj)
    
    extract_values(tenant_a_data)
    
    # Check tenant B's result doesn't contain any
    result_str = str(tenant_b_result)
    for value in sensitive_values:
        assert value not in result_str, (
            f"Tenant isolation breach: '{value[:20]}...' found in other tenant's result"
        )


# =============================================================================
# Observability Assertions
# =============================================================================

def assert_trace_complete(
    trace: dict[str, Any],
    expected_stages: list[str],
) -> None:
    """Assert that trace contains all expected stages."""
    spans = trace.get("spans", [])
    stage_names = {span.get("name") for span in spans}
    
    for stage in expected_stages:
        assert stage in stage_names, f"Missing stage in trace: {stage}"


def assert_correlation_id_propagated(
    trace: dict[str, Any],
) -> None:
    """Assert that correlation ID is present in all spans."""
    correlation_id = trace.get("correlation_id")
    assert correlation_id, "Missing correlation ID in trace"
    
    for span in trace.get("spans", []):
        span_correlation = span.get("correlation_id")
        assert span_correlation == correlation_id, (
            f"Correlation ID mismatch in span {span.get('name')}"
        )


def assert_error_attributed(
    error_event: dict[str, Any],
    required_fields: list[str] | None = None,
) -> None:
    """Assert that error has proper attribution."""
    required = required_fields or [
        "error_type",
        "error_message",
        "stage_name",
        "timestamp",
    ]
    
    for field in required:
        assert field in error_event, f"Missing error attribution field: {field}"


# =============================================================================
# Data Integrity Assertions
# =============================================================================

def assert_no_data_corruption(
    input_data: dict[str, Any],
    output_data: dict[str, Any],
    preserved_keys: list[str],
) -> None:
    """Assert that specified keys are preserved without corruption."""
    for key in preserved_keys:
        input_value = input_data.get(key)
        output_value = output_data.get(key)
        
        assert input_value == output_value, (
            f"Data corruption in key '{key}': {input_value} != {output_value}"
        )


def assert_ordering_preserved(
    input_items: list[Any],
    output_items: list[Any],
    key: str | None = None,
) -> None:
    """Assert that ordering is preserved through processing."""
    if key:
        input_order = [item.get(key) for item in input_items]
        output_order = [item.get(key) for item in output_items]
    else:
        input_order = input_items
        output_order = output_items
    
    assert input_order == output_order, "Ordering not preserved"


def assert_atomic_update(
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    expected_changes: dict[str, Any],
) -> None:
    """Assert that an update was atomic (all or nothing)."""
    # Check all expected changes were applied
    for key, expected_value in expected_changes.items():
        actual_value = after_state.get(key)
        assert actual_value == expected_value, (
            f"Atomic update incomplete: {key} = {actual_value}, expected {expected_value}"
        )
    
    # Check no unexpected changes
    unchanged_keys = set(before_state.keys()) - set(expected_changes.keys())
    for key in unchanged_keys:
        assert before_state.get(key) == after_state.get(key), (
            f"Unexpected change in key '{key}'"
        )
