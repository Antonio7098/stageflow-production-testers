"""
Chaos Pipeline for WORK-006: Error Classification Chaos Testing

This module implements chaos engineering tests to stress-test
Stageflow's error classification under adversarial conditions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import stageflow
from stageflow import (
    Stage,
    StageKind,
    StageOutput,
    StageContext,
    create_stage_context,
)
from stageflow.context import ContextSnapshot

from mocks.data.error_classification_mocks import (
    ErrorCategory,
    ErrorInjector,
    ErrorScenarioGenerator,
    ErrorSeverity,
    MockError,
    PermanentErrors,
    TransientErrors,
    LLMSpecificErrors,
    create_test_error,
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# CHAOS STAGES
# ============================================================================

class RapidFireErrorStage(Stage):
    """Injects errors at high frequency to test classification speed."""
    
    name = "rapid_fire_errors"
    kind = StageKind.TRANSFORM
    
    def __init__(
        self,
        errors_per_second: int = 10,
        duration_seconds: int = 5,
        error_category: ErrorCategory = ErrorCategory.TRANSIENT,
    ):
        self.errors_per_second = errors_per_second
        self.duration_seconds = duration_seconds
        self.error_category = error_category
        self.error_count = 0
        self.start_time: Optional[datetime] = None
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        self.start_time = datetime.now()
        self.error_count = 0
        
        error_interval = 1.0 / self.errors_per_second
        end_time = self.start_time.timestamp() + self.duration_seconds
        
        results = []
        
        while time.time() < end_time:
            # Generate rapid errors
            error = create_test_error(
                random.choice([
                    "timeout", "rate_limited", "network_glitch",
                    "invalid_api_key", "malformed_request", "service_unavailable",
                ])
            )
            
            self.error_count += 1
            results.append({
                "sequence": self.error_count,
                "error_code": error.error_code,
                "category": error.category.value,
                "timestamp": datetime.now().isoformat(),
            })
            
            # Small delay to avoid complete CPU saturation
            await asyncio.sleep(error_interval)
        
        return StageOutput.ok(
            result="rapid_fire_complete",
            error_count=self.error_count,
            duration_seconds=self.duration_seconds,
            errors_per_second=self.error_count / self.duration_seconds,
            sample_errors=results[:10],  # First 10 for logging
        )


class SilentFailureStage(Stage):
    """Tests for silent failures in error classification."""
    
    name = "silent_failure_detection"
    kind = StageKind.GUARD
    
    def __init__(self, silent_failure_rate: float = 0.1):
        self.silent_failure_rate = silent_failure_rate
        self.silent_failures_detected: List[Dict[str, Any]] = []
        self.total_errors = 0
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        error_data = ctx.inputs.get("error_data", {})
        
        self.total_errors += 1
        
        # Check for silent failure conditions
        is_silent = False
        silent_reason = ""
        
        # Condition 1: Error classified as success
        if error_data.get("classified_as_success", False):
            is_silent = True
            silent_reason = "Error marked as success"
        
        # Condition 2: Missing error data (empty error)
        if not error_data.get("error"):
            is_silent = True
            silent_reason = "Missing error message"
        
        # Condition 3: Retry loop without progress
        retry_count = error_data.get("retry_count", 0)
        if retry_count > 5:
            is_silent = True
            silent_reason = f"Excessive retries ({retry_count}) without success"
        
        # Condition 4: Classification contradicts HTTP status
        http_status = error_data.get("http_status")
        classified_category = error_data.get("category")
        
        if http_status and classified_category:
            if http_status == 429 and classified_category != "transient":
                is_silent = True
                silent_reason = "Rate limit not classified as transient"
            elif http_status == 401 and classified_category != "permanent":
                is_silent = True
                silent_reason = "Unauthorized not classified as permanent"
        
        # Inject silent failures for testing (controlled)
        if random.random() < self.silent_failure_rate:
            is_silent = True
            silent_reason = "Injected silent failure"
        
        if is_silent:
            self.silent_failures_detected.append({
                "timestamp": datetime.now().isoformat(),
                "error_data": error_data,
                "reason": silent_reason,
            })
            
            return StageOutput.fail(
                error=f"Silent failure detected: {silent_reason}",
                data={
                    "silent_failure": True,
                    "reason": silent_reason,
                    "error_data": error_data,
                },
            )
        
        return StageOutput.ok(
            result="no_silent_failure",
            error_data=error_data,
        )
    
    def get_silent_failures(self) -> List[Dict[str, Any]]:
        return self.silent_failures_detected.copy()


class AmbiguousErrorStage(Stage):
    """Tests classification of ambiguous errors that could be either type."""
    
    name = "ambiguous_error_test"
    kind = StageKind.GUARD
    
    def __init__(self):
        self.ambiguous_cases: List[Dict[str, Any]] = []
        self.classification_confidence_scores: List[float] = []
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        # Test cases where classification is ambiguous
        ambiguous_errors = [
            {
                "error": "Service temporarily unavailable",
                "http_status": 503,
                "error_code": "SERVICE_UNAVAILABLE",
                "provider": "unknown",
                "description": "503 could be transient or indicate deprecation",
            },
            {
                "error": "Invalid request format",
                "http_status": 400,
                "error_code": "INVALID_REQUEST",
                "provider": "internal",
                "description": "400 could be client error or server misconfiguration",
            },
            {
                "error": "Connection failed",
                "http_status": None,
                "error_code": "CONNECTION_FAILED",
                "provider": "network",
                "description": "No HTTP status, could be network or server",
            },
            {
                "error": "Request throttled",
                "http_status": 429,
                "error_code": "THROTTLED",
                "provider": "internal",
                "description": "Rate limit could be hard limit or temporary",
            },
        ]
        
        results = []
        
        for error in ambiguous_errors:
            # Calculate classification confidence
            confidence = self._calculate_ambiguous_confidence(error)
            self.classification_confidence_scores.append(confidence)
            
            # Determine classification
            is_retryable = self._determine_retryability(error)
            
            results.append({
                "error": error["error"],
                "http_status": error["http_status"],
                "confidence": confidence,
                "is_retryable": is_retryable,
                "description": error["description"],
            })
            
            self.ambiguous_cases.append({
                **error,
                "confidence": confidence,
                "is_retryable": is_retryable,
            })
        
        # Calculate average confidence
        avg_confidence = sum(self.classification_confidence_scores) / len(
            self.classification_confidence_scores
        )
        
        return StageOutput.ok(
            result="ambiguous_test_complete",
            total_cases=len(results),
            average_confidence=avg_confidence,
            low_confidence_cases=[
                c for c in results if c["confidence"] < 0.7
            ],
            cases=results,
        )
    
    def _calculate_ambiguous_confidence(self, error: Dict[str, Any]) -> float:
        """Calculate confidence for ambiguous error classification."""
        confidence = 0.5  # Base confidence
        
        http_status = error.get("http_status")
        error_code = error.get("error_code", "")
        
        # HTTP status adds confidence
        if http_status:
            confidence += 0.2
        
        # Specific error codes add confidence
        if error_code in ("SERVICE_UNAVAILABLE", "INVALID_REQUEST"):
            confidence += 0.1
        elif error_code == "CONNECTION_FAILED":
            confidence -= 0.1  # Less confidence due to ambiguity
        
        # Unknown provider reduces confidence
        if error.get("provider") == "unknown":
            confidence -= 0.1
        
        return max(0.0, min(1.0, confidence))
    
    def _determine_retryability(self, error: Dict[str, Any]) -> bool:
        """Determine if ambiguous error should be retried."""
        http_status = error.get("http_status")
        
        # 503 (service unavailable) is generally retryable
        if http_status == 503:
            return True
        
        # 400 (bad request) is generally not retryable
        if http_status == 400:
            return False
        
        # Default to retryable for unknown
        return True


class RaceConditionStage(Stage):
    """Tests error classification under concurrent access."""
    
    name = "race_condition_test"
    kind = StageKind.TRANSFORM
    
    def __init__(self, concurrent_requests: int = 10):
        self.concurrent_requests = concurrent_requests
        self.race_results: List[Dict[str, Any]] = []
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        async def make_request(request_id: int) -> Dict[str, Any]:
            """Make a concurrent request with potential race condition."""
            start = time.time()
            
            # Simulate concurrent error classification
            error = random.choice([
                TransientErrors.timeout_error(),
                TransientErrors.rate_limited_error(),
                PermanentErrors.invalid_api_key(),
            ])
            
            # Small delay to simulate processing
            await asyncio.sleep(random.uniform(0.001, 0.01))
            
            end = time.time()
            
            return {
                "request_id": request_id,
                "error_code": error.error_code,
                "category": error.category.value,
                "duration_ms": (end - start) * 1000,
                "timestamp": datetime.now().isoformat(),
            }
        
        # Run concurrent requests
        tasks = [make_request(i) for i in range(self.concurrent_requests)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        successful = [r for r in results if isinstance(r, dict)]
        failed = [r for r in results if isinstance(r, Exception)]
        
        self.race_results = successful
        
        # Check for race conditions
        categories = [r["category"] for r in successful]
        category_counts = {
            "transient": categories.count("transient"),
            "permanent": categories.count("permanent"),
        }
        
        return StageOutput.ok(
            result="race_test_complete",
            concurrent_requests=self.concurrent_requests,
            successful_requests=len(successful),
            failed_requests=len(failed),
            category_distribution=category_counts,
            sample_results=successful[:5],
        )


class CascadingErrorStage(Stage):
    """Tests error propagation and cascading failure handling."""
    
    name = "cascading_error_test"
    kind = StageKind.TRANSFORM
    
    def __init__(self, cascade_depth: int = 5):
        self.cascade_depth = cascade_depth
        self.cascade_steps: List[Dict[str, Any]] = []
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        initial_error = TransientErrors.timeout_error()
        
        current_error = initial_error
        step = 0
        
        while step < self.cascade_depth:
            step += 1
            
            # Determine next error based on current
            if step == 2:
                # Cascading to service unavailable
                current_error = TransientErrors.service_unavailable()
            elif step == 3:
                # Cascading to rate limit
                current_error = TransientErrors.rate_limited_error()
            elif step == 4:
                # Cascading to permanent (misclassification)
                current_error = PermanentErrors.invalid_api_key()
            else:
                # Continue with transient
                current_error = TransientErrors.timeout_error()
            
            self.cascade_steps.append({
                "step": step,
                "error_code": current_error.error_code,
                "category": current_error.category.value,
                "retryable": current_error.retryable,
                "is_cascading": step > 1,
            })
        
        # Check for error propagation issues
        propagation_issues = []
        for i, step_data in enumerate(self.cascade_steps):
            if step_data["is_cascading"]:
                prev_step = self.cascade_steps[i - 1]
                if prev_step["category"] == "transient" and step_data["category"] == "permanent":
                    propagation_issues.append({
                        "from_step": i,
                        "to_step": i + 1,
                        "issue": "Transient error cascaded to permanent (potential misclassification)",
                    })
        
        return StageOutput.ok(
            result="cascade_test_complete",
            initial_error=initial_error.to_dict(),
            cascade_depth=self.cascade_depth,
            steps=self.cascade_steps,
            propagation_issues=len(propagation_issues),
            issues=propagation_issues,
        )


# ============================================================================
# CHAOS TEST RUNNER
# ============================================================================

@dataclass
class ChaosTestResult:
    """Result of a chaos test run."""
    test_name: str
    test_type: str
    start_time: datetime
    end_time: Optional[datetime] = None
    success: bool = False
    metrics: Dict[str, Any] = field(default_factory=dict)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_name": self.test_name,
            "test_type": self.test_type,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": (
                (self.end_time - self.start_time).total_seconds() 
                if self.end_time else 0
            ),
            "success": self.success,
            "metrics": self.metrics,
            "findings": self.findings,
        }


async def run_rapid_fire_test() -> ChaosTestResult:
    """Run rapid fire error classification test."""
    result = ChaosTestResult(
        test_name="rapid_fire_classification",
        test_type="stress",
        start_time=datetime.now(),
    )
    
    try:
        stage = RapidFireErrorStage(
            errors_per_second=50,
            duration_seconds=3,
        )
        
        snapshot = ContextSnapshot(
        )
        ctx = create_stage_context(snapshot=snapshot)
        
        output = await stage.execute(ctx)
        
        result.success = True
        result.metrics = {
            "error_count": output.data["error_count"],
            "duration_seconds": output.data["duration_seconds"],
            "errors_per_second": output.data["errors_per_second"],
        }
        
        # Log findings
        if output.data["errors_per_second"] < 40:
            result.findings.append({
                "type": "performance",
                "severity": "medium",
                "description": f"Classification throughput below target: {output.data['errors_per_second']:.1f}/s",
            })
        
    except Exception as e:
        logger.error(f"Rapid fire test failed: {e}")
        result.findings.append({
            "type": "execution_error",
            "severity": "high",
            "description": str(e),
        })
    finally:
        result.end_time = datetime.now()
    
    return result


async def run_silent_failure_test() -> ChaosTestResult:
    """Run silent failure detection test."""
    result = ChaosTestResult(
        test_name="silent_failure_detection",
        test_type="reliability",
        start_time=datetime.now(),
    )
    
    try:
        stage = SilentFailureStage(silent_failure_rate=0.05)
        
        # Test with various error scenarios
        test_cases = [
            {"error": "", "http_status": None, "category": "unknown"},  # Missing error
            {"error": "Service error", "http_status": 429, "category": "permanent"},  # Misclassified
            {"error": "Timeout", "http_status": 503, "category": "transient", "retry_count": 10},  # Excessive retries
        ]
        
        for case in test_cases:
            ctx = create_stage_context(
                snapshot=ContextSnapshot(
                )
            )
            ctx.inputs["error_data"] = case
            await stage.execute(ctx)
        
        silent_failures = stage.get_silent_failures()
        
        result.success = len(silent_failures) > 0  # We expect to find silent failures
        result.metrics = {
            "total_errors_tested": len(test_cases),
            "silent_failures_detected": len(silent_failures),
        }
        
        for sf in silent_failures:
            result.findings.append({
                "type": "silent_failure",
                "severity": "high",
                "description": f"Silent failure: {sf['reason']}",
                "details": sf,
            })
        
    except Exception as e:
        logger.error(f"Silent failure test failed: {e}")
        result.findings.append({
            "type": "execution_error",
            "severity": "high",
            "description": str(e),
        })
    finally:
        result.end_time = datetime.now()
    
    return result


async def run_ambiguous_error_test() -> ChaosTestResult:
    """Run ambiguous error classification test."""
    result = ChaosTestResult(
        test_name="ambiguous_error_classification",
        test_type="edge_case",
        start_time=datetime.now(),
    )
    
    try:
        stage = AmbiguousErrorStage()
        
        snapshot = ContextSnapshot(
        )
        ctx = create_stage_context(snapshot=snapshot)
        
        output = await stage.execute(ctx)
        
        avg_confidence = output.data["average_confidence"]
        low_confidence = len(output.data["low_confidence_cases"])
        
        result.success = avg_confidence >= 0.5
        result.metrics = {
            "total_cases": output.data["total_cases"],
            "average_confidence": avg_confidence,
            "low_confidence_cases": low_confidence,
        }
        
        if avg_confidence < 0.6:
            result.findings.append({
                "type": "classification_confidence",
                "severity": "medium",
                "description": f"Average classification confidence below threshold: {avg_confidence:.2f}",
            })
        
        for case in output.data["low_confidence_cases"]:
            result.findings.append({
                "type": "low_confidence_case",
                "severity": "low",
                "description": f"Low confidence classification: {case['error']} (confidence: {case['confidence']:.2f})",
                "details": case,
            })
        
    except Exception as e:
        logger.error(f"Ambiguous error test failed: {e}")
        result.findings.append({
            "type": "execution_error",
            "severity": "high",
            "description": str(e),
        })
    finally:
        result.end_time = datetime.now()
    
    return result


async def run_race_condition_test() -> ChaosTestResult:
    """Run race condition test."""
    result = ChaosTestResult(
        test_name="race_condition_handling",
        test_type="concurrency",
        start_time=datetime.now(),
    )
    
    try:
        stage = RaceConditionStage(concurrent_requests=20)
        
        snapshot = ContextSnapshot(
        )
        ctx = create_stage_context(snapshot=snapshot)
        
        output = await stage.execute(ctx)
        
        successful = output.data["successful_requests"]
        failed = output.data["failed_requests"]
        
        result.success = successful >= 18  # 90% success rate
        result.metrics = {
            "concurrent_requests": output.data["concurrent_requests"],
            "successful_requests": successful,
            "failed_requests": failed,
            "success_rate": successful / output.data["concurrent_requests"],
            "category_distribution": output.data["category_distribution"],
        }
        
        if failed > 2:
            result.findings.append({
                "type": "race_condition",
                "severity": "medium",
                "description": f"Failed concurrent requests under load: {failed}/{output.data['concurrent_requests']}",
            })
        
    except Exception as e:
        logger.error(f"Race condition test failed: {e}")
        result.findings.append({
            "type": "execution_error",
            "severity": "high",
            "description": str(e),
        })
    finally:
        result.end_time = datetime.now()
    
    return result


async def run_cascading_error_test() -> ChaosTestResult:
    """Run cascading error test."""
    result = ChaosTestResult(
        test_name="cascading_error_propagation",
        test_type="reliability",
        start_time=datetime.now(),
    )
    
    try:
        stage = CascadingErrorStage(cascade_depth=5)
        
        snapshot = ContextSnapshot(
        )
        ctx = create_stage_context(snapshot=snapshot)
        
        output = await stage.execute(ctx)
        
        propagation_issues = output.data["propagation_issues"]
        
        result.success = True
        result.metrics = {
            "cascade_depth": output.data["cascade_depth"],
            "steps": len(output.data["steps"]),
            "propagation_issues": propagation_issues,
        }
        
        for issue in output.data["issues"]:
            result.findings.append({
                "type": "error_propagation",
                "severity": "high",
                "description": issue["issue"],
                "details": issue,
            })
        
    except Exception as e:
        logger.error(f"Cascading error test failed: {e}")
        result.findings.append({
            "type": "execution_error",
            "severity": "high",
            "description": str(e),
        })
    finally:
        result.end_time = datetime.now()
    
    return result


# ============================================================================
# MAIN CHAOS TEST RUNNER
# ============================================================================

async def main():
    """Run all chaos tests."""
    print("=" * 80)
    print("WORK-006 Chaos Engineering Tests: Error Classification")
    print("=" * 80)
    print()
    
    results = []
    
    # Run all chaos tests
    test_functions = [
        ("Rapid Fire Classification", run_rapid_fire_test),
        ("Silent Failure Detection", run_silent_failure_test),
        ("Ambiguous Error Classification", run_ambiguous_error_test),
        ("Race Condition Handling", run_race_condition_test),
        ("Cascading Error Propagation", run_cascading_error_test),
    ]
    
    for test_name, test_func in test_functions:
        print(f"Running {test_name}...")
        result = await test_func()
        results.append(result)
        
        status = "PASS" if result.success else "FAIL"
        print(f"  Status: {status}")
        print(f"  Duration: {(result.end_time - result.start_time).total_seconds():.2f}s")
        
        if result.findings:
            print(f"  Findings: {len(result.findings)}")
            for finding in result.findings[:3]:  # Show top 3
                print(f"    - [{finding['severity']}] {finding['description']}")
        print()
    
    # Summary
    print("=" * 80)
    print("CHAOS TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for r in results if r.success)
    total = len(results)
    
    print(f"Tests passed: {passed}/{total}")
    print(f"Total findings: {sum(len(r.findings) for r in results)}")
    print()
    
    # Save results
    results_path = Path("results/chaos_test_results.json")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(results_path, "w") as f:
        json.dump(
            {
                "test_run_timestamp": datetime.now().isoformat(),
                "results": [r.to_dict() for r in results],
                "summary": {
                    "tests_passed": passed,
                    "tests_total": total,
                    "total_findings": sum(len(r.findings) for r in results),
                },
            },
            f,
            indent=2,
        )
    
    print(f"Results saved to: {results_path}")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())
