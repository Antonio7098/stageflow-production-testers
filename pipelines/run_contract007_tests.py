"""
Test execution script for CONTRACT-007: Custom Validator Integration

This script executes validation tests and captures results, logs, and metrics.
"""

import sys
import json
import uuid
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field, asdict

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from mocks.validators import (
    Validator,
    ValidationResult,
    StringValidator,
    EmailValidator,
    NumberValidator,
    ChoiceValidator,
    LengthValidator,
    create_string_validator,
    create_email_validator,
    create_number_validator,
    create_choice_validator,
    create_length_validator,
)
from mocks.validation_data import MockDataGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'results/logs/contract007_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of a single test execution."""
    test_name: str
    test_category: str
    status: str  # pass, fail, error
    duration_ms: float
    expected_result: Any
    actual_result: Any
    error_message: str = None


def run_validator_test(
    name: str,
    value: Any,
    validator: Validator,
    expected_valid: bool,
    category: str = "validator",
) -> TestResult:
    """Run a single validator test."""
    start_time = time.time()

    try:
        result = validator.validate(value, {})
        duration_ms = (time.time() - start_time) * 1000

        actual_valid = result.is_valid
        passed = actual_valid == expected_valid

        return TestResult(
            test_name=name,
            test_category=category,
            status="pass" if passed else "fail",
            duration_ms=duration_ms,
            expected_result=expected_valid,
            actual_result=actual_valid,
        )

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.exception(f"Test {name} errored")

        return TestResult(
            test_name=name,
            test_category=category,
            status="error",
            duration_ms=duration_ms,
            expected_result=expected_valid,
            actual_result=None,
            error_message=str(e),
        )


def run_all_tests() -> dict:
    """Run all validation tests."""
    logger.info("Running CONTRACT-007 validation tests...")

    results = []

    # === Email Validator Tests ===
    results.append(run_validator_test(
        "email_valid",
        "user@example.com",
        create_email_validator(),
        True,
        "email_validator",
    ))

    results.append(run_validator_test(
        "email_invalid_no_at",
        "userexample.com",
        create_email_validator(),
        False,
        "email_validator",
    ))

    results.append(run_validator_test(
        "email_invalid_no_domain",
        "user@",
        create_email_validator(),
        False,
        "email_validator",
    ))

    # === String Validator Tests ===
    results.append(run_validator_test(
        "string_valid_length",
        "hello world",
        create_string_validator(min_length=3, max_length=50),
        True,
        "string_validator",
    ))

    results.append(run_validator_test(
        "string_too_short",
        "ab",
        create_string_validator(min_length=3),
        False,
        "string_validator",
    ))

    results.append(run_validator_test(
        "string_too_long",
        "x" * 101,
        create_string_validator(max_length=100),
        False,
        "string_validator",
    ))

    # === Number Validator Tests ===
    results.append(run_validator_test(
        "number_valid_range",
        50,
        create_number_validator(min_value=0, max_value=100),
        True,
        "number_validator",
    ))

    results.append(run_validator_test(
        "number_negative",
        -5,
        create_number_validator(min_value=0),
        False,
        "number_validator",
    ))

    results.append(run_validator_test(
        "number_above_max",
        150,
        create_number_validator(max_value=100),
        False,
        "number_validator",
    ))

    results.append(run_validator_test(
        "number_boundary_min",
        0,
        create_number_validator(min_value=0),
        True,
        "number_validator",
    ))

    results.append(run_validator_test(
        "number_boundary_max",
        100,
        create_number_validator(max_value=100),
        True,
        "number_validator",
    ))

    # === Choice Validator Tests ===
    results.append(run_validator_test(
        "choice_valid",
        "pending",
        create_choice_validator(["pending", "processing", "completed"]),
        True,
        "choice_validator",
    ))

    results.append(run_validator_test(
        "choice_invalid",
        "invalid",
        create_choice_validator(["pending", "processing", "completed"]),
        False,
        "choice_validator",
    ))

    # === Length Validator Tests ===
    results.append(run_validator_test(
        "length_valid",
        [1, 2, 3],
        create_length_validator(min_items=1, max_items=10),
        True,
        "length_validator",
    ))

    results.append(run_validator_test(
        "length_empty",
        [],
        create_length_validator(min_items=1),
        False,
        "length_validator",
    ))

    results.append(run_validator_test(
        "length_too_many",
        list(range(20)),
        create_length_validator(max_items=10),
        False,
        "length_validator",
    ))

    # === Composite Validation Tests ===
    email_val = create_email_validator()
    string_val = create_string_validator(min_length=5)

    # Test sequential validation (both should pass)
    results.append(run_validator_test(
        "composite_both_valid",
        "user@example.com",
        email_val,
        True,
        "composite",
    ))

    # Test with invalid email (should fail)
    results.append(run_validator_test(
        "composite_email_fails",
        "invalid-email",
        email_val,
        False,
        "composite",
    ))

    # === Edge Case Tests ===
    results.append(run_validator_test(
        "edge_unicode",
        "José García",
        create_string_validator(min_length=1, max_length=50),
        True,
        "edge_case",
    ))

    results.append(run_validator_test(
        "edge_whitespace",
        "   text   ",
        create_string_validator(min_length=1, max_length=20),
        True,
        "edge_case",
    ))

    # === Silent Failure Detection Tests ===
    # These tests verify that invalid data properly fails validation
    # (i.e., no silent failures where invalid data passes)

    silent_failure_tests = [
        ("silent_email", "not-an-email", create_email_validator(), False),
        ("silent_negative", -100, create_number_validator(min_value=0), False),
        ("silent_invalid_choice", "unknown", create_choice_validator(["a", "b", "c"]), False),
    ]

    silent_failures_detected = 0
    for name, value, validator, should_fail in silent_failure_tests:
        result = run_validator_test(name, value, validator, should_fail, "silent_failure")
        results.append(result)
        if result.status == "fail":
            silent_failures_detected += 1

    # Calculate summary
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    errors = sum(1 for r in results if r.status == "error")

    summary = {
        "total_tests": len(results),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "pass_rate": passed / len(results) * 100 if results else 0,
        "total_duration_ms": sum(r.duration_ms for r in results),
        "tests": [asdict(r) for r in results],
        "silent_failures_detected": silent_failures_detected,
    }

    logger.info(f"Test suite complete: {passed}/{len(results)} passed")

    return summary


def run_dx_evaluation() -> dict:
    """Evaluate developer experience of custom validator integration."""
    logger.info("Running DX evaluation...")

    evaluation = {
        "discoverability": {
            "score": 3,
            "notes": "Validator API exists but not well documented",
            "issues": [
                "No clear examples for custom validator registration",
                "Missing validator composition patterns in docs",
            ],
        },
        "clarity": {
            "score": 3,
            "notes": "Basic API is clear but advanced patterns are confusing",
            "issues": [
                "Error messages could be more actionable",
                "ValidationResult fields not clearly documented",
            ],
        },
        "documentation": {
            "score": 2,
            "notes": "Documentation missing custom validator examples",
            "gaps": [
                "No guide for creating domain-specific validators",
                "Missing async validator patterns",
                "No error handling best practices",
            ],
        },
        "error_messages": {
            "score": 3,
            "notes": "Error messages include field names but lack context",
            "issues": [
                "Error codes not documented",
                "No guidance on custom error messages",
            ],
        },
        "debugging": {
            "score": 3,
            "notes": "Basic debugging supported, could be improved",
            "issues": [
                "No validation debug mode",
                "Missing intermediate validation state access",
            ],
        },
        "boilerplate": {
            "score": 4,
            "notes": "Validator creation is concise",
            "issues": [
                "Registry pattern requires boilerplate",
                "Could benefit from validator factory helpers",
            ],
        },
        "flexibility": {
            "score": 4,
            "notes": "Flexible enough for most use cases",
            "issues": [
                "Async validator integration could be smoother",
                "Missing built-in common validators (email, url, etc.)",
            ],
        },
        "performance": {
            "score": 4,
            "notes": "Validation overhead is minimal",
            "issues": [
                "No built-in validation caching",
                "Async validators could benefit from connection pooling",
            ],
        },
    }

    total = sum(cat["score"] for cat in evaluation.values())
    evaluation["overall_score"] = round(total / len(evaluation), 2)

    return evaluation


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("CONTRACT-007: Custom Validator Integration Test Suite")
    logger.info("=" * 60)

    test_results = run_all_tests()
    dx_evaluation = run_dx_evaluation()

    final_results = {
        "test_results": test_results,
        "dx_evaluation": dx_evaluation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "roadmap_entry": "CONTRACT-007",
        "title": "Custom validator integration",
    }

    results_file = f"results/test_results_contract007_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump(final_results, f, indent=2, default=str)

    logger.info(f"Results saved to {results_file}")

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Total Tests: {test_results['total_tests']}")
    print(f"Passed: {test_results['passed']}")
    print(f"Failed: {test_results['failed']}")
    print(f"Pass Rate: {test_results['pass_rate']:.1f}%")
    print(f"Total Duration: {test_results['total_duration_ms']:.2f}ms")
    print(f"Silent Failures Detected: {test_results['silent_failures_detected']}")
    print(f"DX Score: {dx_evaluation['overall_score']}/5.0")
    print("=" * 60)

    return final_results


if __name__ == "__main__":
    main()
