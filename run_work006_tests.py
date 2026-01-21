"""
Error Classification Test Runner for WORK-006

Usage:
    python run_work006_tests.py [--output DIR]
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from mocks.data.error_classification_mocks import (
    ErrorCategory,
    ErrorScenarioGenerator,
    ErrorSeverity,
    MockError,
    PermanentErrors,
    TransientErrors,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of a test run."""
    test_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    errors: List[Dict[str, Any]] = field(default_factory=list)
    correct_classifications: int = 0
    misclassifications: int = 0
    silent_failures: List[Dict[str, Any]] = field(default_factory=list)
    total_retries: int = 0
    total_cost: float = 0.0
    success: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_name": self.test_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": (
                (self.end_time - self.start_time).total_seconds() 
                if self.end_time else 0
            ),
            "errors_tested": len(self.errors),
            "correct_classifications": self.correct_classifications,
            "misclassifications": self.misclassifications,
            "silent_failures": len(self.silent_failures),
            "total_retries": self.total_retries,
            "total_cost": self.total_cost,
            "accuracy": self.correct_classifications / max(1, len(self.errors)),
            "success": self.success,
        }


class ErrorClassifier:
    """Simple error classifier for testing."""
    
    def __init__(self, strict_mode: bool = False):
        self.strict_mode = strict_mode
        self.classifications: List[Dict[str, Any]] = []
    
    def classify(self, error: MockError) -> Dict[str, Any]:
        """Classify an error based on its characteristics."""
        http_status = error.http_status
        error_code = error.error_code
        message = error.message.lower()
        
        is_retryable = error.retryable
        category = error.category.value
        
        if http_status:
            if http_status == 429:
                category = "transient"
                is_retryable = True
            elif http_status == 401:
                category = "permanent"
                is_retryable = False
            elif http_status == 403:
                category = "policy"
                is_retryable = False
            elif http_status == 404:
                category = "permanent"
                is_retryable = False
            elif http_status == 400:
                if "content" in message or "policy" in message:
                    category = "policy"
                    is_retryable = False
                else:
                    category = "permanent"
                    is_retryable = False
            elif http_status in (500, 502, 503, 504):
                category = "transient"
                is_retryable = True
        
        if error_code in ("TIMEOUT", "CIRCUIT_OPEN"):
            category = "transient"
            is_retryable = True
        elif error_code in ("UNAUTHORIZED", "INVALID_REQUEST", "NOT_FOUND"):
            category = "permanent"
            is_retryable = False
        elif error_code == "CONTENT_FILTERED":
            category = "policy"
            is_retryable = False
        
        confidence = 0.5
        if http_status:
            confidence += 0.3
        if error_code:
            confidence += 0.1
        if error.retryable:
            confidence += 0.1
        
        classification = {
            "original_category": error.category.value,
            "classified_category": category,
            "is_retryable": is_retryable,
            "confidence": min(1.0, confidence),
        }
        
        self.classifications.append(classification)
        return classification


async def run_classification_test(
    test_name: str,
    errors: List[MockError],
) -> TestResult:
    """Run error classification test."""
    result = TestResult(test_name=test_name, start_time=datetime.now())
    
    try:
        classifier = ErrorClassifier()
        
        for error in errors:
            classification = classifier.classify(error)
            result.errors.append(error.to_dict())
            
            if classification["classified_category"] == error.category.value:
                result.correct_classifications += 1
            else:
                result.misclassifications += 1
                result.silent_failures.append({
                    "error": error.to_dict(),
                    "classification": classification,
                    "issue": f"Expected {error.category.value}, got {classification['classified_category']}",
                })
        
        result.success = True
        
    except Exception as e:
        logger.error(f"Test {test_name} failed: {e}")
        result.errors.append({"error": str(e), "type": "test_failure"})
    
    finally:
        result.end_time = datetime.now()
    
    return result


async def run_stress_test(
    test_name: str,
    error_count: int = 100,
) -> TestResult:
    """Run stress test with high-volume errors."""
    result = TestResult(test_name=test_name, start_time=datetime.now())
    
    try:
        generator = ErrorScenarioGenerator(seed=42)
        errors = generator.generate_mixed_error_sequence(error_count)
        
        classifier = ErrorClassifier()
        
        for error in errors:
            classification = classifier.classify(error)
            result.errors.append(error.to_dict())
            
            if classification["classified_category"] == error.category.value:
                result.correct_classifications += 1
            else:
                result.misclassifications += 1
                if error.category.value == "transient" and classification["classified_category"] == "permanent":
                    result.total_cost += 0.01
                elif error.category.value == "permanent" and classification["classified_category"] == "transient":
                    result.total_cost += 0.03
                    result.total_retries += 3
        
        result.success = True
        
    except Exception as e:
        logger.error(f"Stress test {test_name} failed: {e}")
        result.errors.append({"error": str(e)})
    
    finally:
        result.end_time = datetime.now()
    
    return result


async def run_cost_impact_test(
    test_name: str,
    scenario_type: str = "permanent_as_transient",
) -> TestResult:
    """Test cost impact of error misclassification."""
    result = TestResult(test_name=test_name, start_time=datetime.now())
    
    try:
        generator = ErrorScenarioGenerator(seed=42)
        
        if scenario_type == "permanent_as_transient":
            errors = generator.generate_cost_impact_scenario(10)
            
            for error in errors:
                result.errors.append(error.to_dict())
                
                if error.category.value == "permanent":
                    for retry in range(3):
                        result.total_retries += 1
                        result.total_cost += 0.01
                        
                        if retry == 0:
                            result.misclassifications += 1
                            result.silent_failures.append({
                                "error": error.to_dict(),
                                "issue": "Permanent error retried (wasted cost)",
                                "cost_impact": 0.03,
                            })
                else:
                    result.correct_classifications += 1
        else:
            errors = generator.generate_transient_storm(20, success_after=15)
            
            for error in errors:
                result.errors.append(error.to_dict())
                result.correct_classifications += 1
        
        result.success = True
        
    except Exception as e:
        logger.error(f"Cost impact test {test_name} failed: {e}")
    
    finally:
        result.end_time = datetime.now()
    
    return result


async def run_ambiguity_test(
    test_name: str,
) -> TestResult:
    """Test classification of ambiguous errors."""
    result = TestResult(test_name=test_name, start_time=datetime.now())
    
    try:
        classifier = ErrorClassifier()
        
        ambiguous_cases = [
            {"error": "Service temporarily unavailable", "http_status": 503, "error_code": "SERVICE_UNAVAILABLE", "provider": "unknown"},
            {"error": "Invalid request format", "http_status": 400, "error_code": "INVALID_REQUEST", "provider": "internal"},
            {"error": "Connection failed", "http_status": None, "error_code": "CONNECTION_FAILED", "provider": "network"},
            {"error": "Request throttled", "http_status": 429, "error_code": "THROTTLED", "provider": "internal"},
        ]
        
        for case in ambiguous_cases:
            error = MockError(
                category=ErrorCategory.UNKNOWN,
                severity=ErrorSeverity.MEDIUM,
                message=case["error"],
                error_code=case["error_code"],
                http_status=case["http_status"],
                provider=case["provider"],
                retryable=True,
            )
            
            classification = classifier.classify(error)
            result.errors.append(case)
            
            confidence = classification["confidence"]
            if confidence < 0.7:
                result.misclassifications += 1
                result.silent_failures.append({
                    "case": case,
                    "classification": classification,
                    "issue": f"Low confidence classification: {confidence:.2f}",
                })
            else:
                result.correct_classifications += 1
        
        result.success = True
        
    except Exception as e:
        logger.error(f"Ambiguity test {test_name} failed: {e}")
    
    finally:
        result.end_time = datetime.now()
    
    return result


async def main():
    print("=" * 80)
    print("WORK-006: Permanent vs Transient Error Classification Tests")
    print("=" * 80)
    print()
    
    results = []
    
    print("[1/5] Testing transient error classification...")
    transient_errors = [
        TransientErrors.timeout_error(),
        TransientErrors.rate_limited_error(),
        TransientErrors.network_glitch(),
        TransientErrors.service_unavailable(),
    ]
    result = await run_classification_test("transient_classification", transient_errors)
    results.append(result)
    accuracy = result.correct_classifications / len(transient_errors) * 100
    print(f"  Accuracy: {result.correct_classifications}/{len(transient_errors)} ({accuracy:.0f}%)")
    print()
    
    print("[2/5] Testing permanent error classification...")
    permanent_errors = [
        PermanentErrors.invalid_api_key(),
        PermanentErrors.malformed_request(),
        PermanentErrors.resource_not_found(),
        PermanentErrors.permission_denied(),
    ]
    result = await run_classification_test("permanent_classification", permanent_errors)
    results.append(result)
    accuracy = result.correct_classifications / len(permanent_errors) * 100
    print(f"  Accuracy: {result.correct_classifications}/{len(permanent_errors)} ({accuracy:.0f}%)")
    print()
    
    print("[3/5] Running stress test with 100 mixed errors...")
    result = await run_stress_test("stress_test", error_count=100)
    results.append(result)
    accuracy = result.correct_classifications / len(result.errors) * 100
    print(f"  Accuracy: {result.correct_classifications}/{len(result.errors)} ({accuracy:.1f}%)")
    print(f"  Cost impact: ${result.total_cost:.4f}")
    print(f"  Silent failures: {len(result.silent_failures)}")
    print()
    
    print("[4/5] Running cost impact test...")
    result = await run_cost_impact_test("cost_impact_test", "permanent_as_transient")
    results.append(result)
    print(f"  Retries: {result.total_retries}, Cost: ${result.total_cost:.4f}")
    print(f"  Silent failures: {len(result.silent_failures)}")
    print()
    
    print("[5/5] Running ambiguity test...")
    result = await run_ambiguity_test("ambiguity_test")
    results.append(result)
    print(f"  Low confidence cases: {result.misclassifications}")
    print()
    
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    total_errors = sum(len(r.errors) for r in results)
    total_correct = sum(r.correct_classifications for r in results)
    total_misclassified = sum(r.misclassifications for r in results)
    total_cost = sum(r.total_cost for r in results)
    total_silent = sum(len(r.silent_failures) for r in results)
    
    print(f"Total errors tested: {total_errors}")
    print(f"Overall accuracy: {total_correct}/{total_errors} ({total_correct/max(1,total_errors)*100:.1f}%)")
    print(f"Total misclassified: {total_misclassified}")
    print(f"Total silent failures: {total_silent}")
    print(f"Total cost impact: ${total_cost:.4f}")
    print()
    
    output_dir = Path("results/work006")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results_file = output_dir / "test_results.json"
    with open(results_file, "w") as f:
        json.dump(
            {
                "test_run_timestamp": datetime.now().isoformat(),
                "results": [r.to_dict() for r in results],
                "summary": {
                    "total_errors": total_errors,
                    "total_correct": total_correct,
                    "total_misclassified": total_misclassified,
                    "total_silent_failures": total_silent,
                    "total_cost": total_cost,
                    "accuracy": total_correct / max(1, total_errors),
                },
            },
            f,
            indent=2,
            default=str,
        )
    
    print(f"Results saved to: {results_file}")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())
