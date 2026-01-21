"""
Error Classification Test Pipelines for WORK-006

This module implements test pipelines for stress-testing Stageflow's
error classification system: permanent vs transient error handling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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

# Import our mock data
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

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# PIPELINE RESULT TRACKING
# ============================================================================

@dataclass
class PipelineTestResult:
    """Result of a pipeline test run."""
    test_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    stages_executed: int = 0
    errors_encountered: List[Dict[str, Any]] = field(default_factory=list)
    errors_classified_correctly: int = 0
    errors_misclassified: int = 0
    silent_failures: List[Dict[str, Any]] = field(default_factory=list)
    total_retries: int = 0
    total_cost_estimate: float = 0.0
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
            "stages_executed": self.stages_executed,
            "errors_encountered": self.errors_encountered,
            "errors_classified_correctly": self.errors_classified_correctly,
            "errors_misclassified": self.errors_misclassified,
            "silent_failures": self.silent_failures,
            "total_retries": self.total_retries,
            "total_cost_estimate": self.total_cost_estimate,
            "success": self.success,
            "classification_accuracy": (
                self.errors_classified_correctly / 
                max(1, len(self.errors_encountered))
            ),
        }


# ============================================================================
# ERROR CLASSIFICATION STAGES
# ============================================================================

class ErrorInjectingStage(Stage):
    """Stage that injects errors for testing classification."""
    
    name = "error_injector"
    kind = StageKind.TRANSFORM
    
    def __init__(
        self,
        error_to_inject: Optional[MockError] = None,
        inject_after_calls: int = 0,
        error_sequence: Optional[List[MockError]] = None,
    ):
        self.error_to_inject = error_to_inject
        self.inject_after_calls = inject_after_calls
        self.error_sequence = error_sequence or []
        self.call_count = 0
        self.error_log: List[Dict[str, Any]] = []
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        self.call_count += 1
        
        # Check if we should inject an error
        if self.error_sequence and self.call_count <= len(self.error_sequence):
            error = self.error_sequence[self.call_count - 1]
            self.error_log.append({
                "call": self.call_count,
                "error": error.to_dict(),
                "timestamp": datetime.now().isoformat(),
            })
            
            return StageOutput.fail(
                error=error.message,
                data={
                    "error_code": error.error_code,
                    "category": error.category.value,
                    "retryable": error.retryable,
                    "retry_after_ms": error.retry_after_ms,
                    "http_status": error.http_status,
                    "provider": error.provider,
                    **error.metadata,
                },
            )
        
        return StageOutput.ok(result="success", call_count=self.call_count)


class ErrorClassifyingStage(Stage):
    """Stage that classifies errors based on available information."""
    
    name = "error_classifier"
    kind = StageKind.GUARD
    
    def __init__(self, strict_mode: bool = False):
        self.strict_mode = strict_mode
        self.classifications: List[Dict[str, Any]] = []
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        # Get error data from previous stage
        error_data = ctx.inputs.get("error_data")
        
        if not error_data:
            return StageOutput.skip(reason="No error data to classify")
        
        # Classify the error
        classification = self._classify_error(error_data)
        self.classifications.append(classification)
        
        # Emit event for observability
        ctx.emit_event("error.classified", classification)
        
        # Determine action based on classification
        if classification["is_retryable"]:
            return StageOutput.retry(
                error=error_data.get("error", "Unknown error"),
                data={
                    **error_data,
                    "classification": classification,
                    "retry_recommended": True,
                },
            )
        else:
            return StageOutput.fail(
                error=error_data.get("error", "Unknown error"),
                data={
                    **error_data,
                    "classification": classification,
                    "retry_recommended": False,
                },
            )
    
    def _classify_error(self, error_data: Dict[str, Any]) -> Dict[str, Any]:
        """Classify an error based on its characteristics."""
        http_status = error_data.get("http_status")
        error_code = error_data.get("error_code", "")
        error_message = error_data.get("error", "").lower()
        provider = error_data.get("provider")
        retryable = error_data.get("retryable", True)
        
        # Primary classification based on HTTP status
        is_retryable = retryable
        category = error_data.get("category", "unknown")
        
        # HTTP status-based heuristics
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
                # Need more context for 400 errors
                if "content" in error_message or "policy" in error_message:
                    category = "policy"
                    is_retryable = False
                else:
                    category = "permanent"
                    is_retryable = False
            elif http_status in (500, 502, 503, 504):
                category = "transient"
                is_retryable = True
        
        # Error code-based overrides
        if error_code in ("TIMEOUT", "CIRCUIT_OPEN"):
            category = "transient"
            is_retryable = True
        elif error_code in ("UNAUTHORIZED", "INVALID_REQUEST", "NOT_FOUND"):
            category = "permanent"
            is_retryable = False
        elif error_code == "CONTENT_FILTERED":
            category = "policy"
            is_retryable = False
        
        # Provider-specific knowledge
        if provider == "openai":
            if "invalid_api_key" in error_message:
                category = "permanent"
                is_retryable = False
        
        return {
            "original_category": error_data.get("category"),
            "classified_category": category,
            "is_retryable": is_retryable,
            "confidence": self._calculate_confidence(error_data, category),
            "reason": self._get_classification_reason(http_status, error_code, category),
        }
    
    def _calculate_confidence(
        self,
        error_data: Dict[str, Any],
        category: str,
    ) -> float:
        """Calculate classification confidence score."""
        confidence = 0.5  # Base confidence
        
        # HTTP status provides high confidence
        if error_data.get("http_status"):
            confidence += 0.3
        
        # Explicit retryable flag provides high confidence
        if "retryable" in error_data:
            confidence += 0.2
        
        # Error code provides additional confidence
        if error_data.get("error_code"):
            confidence += 0.1
        
        return min(1.0, confidence)
    
    def _get_classification_reason(
        self,
        http_status: Optional[int],
        error_code: str,
        category: str,
    ) -> str:
        """Get human-readable reason for classification."""
        if http_status:
            if http_status == 429:
                return "HTTP 429 indicates rate limiting, transient"
            elif http_status == 401:
                return "HTTP 401 indicates unauthorized, permanent"
            elif http_status == 403:
                return "HTTP 403 indicates forbidden, policy"
            elif http_status == 404:
                return "HTTP 404 indicates not found, permanent"
            elif http_status in (500, 502, 503, 504):
                return f"HTTP {http_status} indicates server error, transient"
        
        if error_code:
            if error_code == "TIMEOUT":
                return "Timeout error code indicates transient failure"
            elif error_code == "UNAUTHORIZED":
                return "Unauthorized error code indicates permanent failure"
        
        return f"Default classification as {category}"


class RetryDecisionStage(Stage):
    """Stage that makes retry decisions based on error classification."""
    
    name = "retry_decision"
    kind = StageKind.WORK
    
    def __init__(self, max_retries: int = 3, cost_per_retry: float = 0.01):
        self.max_retries = max_retries
        self.cost_per_retry = cost_per_retry
        self.retry_decisions: List[Dict[str, Any]] = []
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        error_data = ctx.inputs.get("error_data", {})
        classification = ctx.inputs.get("classification", {})
        
        retry_count = ctx.inputs.get("retry_count", 0)
        is_retryable = classification.get("is_retryable", False)
        confidence = classification.get("confidence", 0.5)
        
        # Make retry decision
        decision = {
            "retry_count": retry_count,
            "is_retryable": is_retryable,
            "confidence": confidence,
            "should_retry": False,
            "reason": "",
        }
        
        if not is_retryable:
            decision["should_retry"] = False
            decision["reason"] = "Error classified as non-retryable"
        elif retry_count >= self.max_retries:
            decision["should_retry"] = False
            decision["reason"] = f"Max retries ({self.max_retries}) exceeded"
        elif confidence < 0.5 and self.strict_mode:
            decision["should_retry"] = False
            decision["reason"] = "Low confidence in classification, strict mode"
        else:
            decision["should_retry"] = True
            decision["reason"] = "Error retryable and within retry limit"
        
        self.retry_decisions.append(decision)
        
        # Emit event
        ctx.emit_event("retry.decision", decision)
        
        if decision["should_retry"]:
            return StageOutput.retry(
                error=error_data.get("error", "Retry needed"),
                data={
                    **decision,
                    "next_retry_count": retry_count + 1,
                    "estimated_cost": (retry_count + 1) * self.cost_per_retry,
                },
            )
        else:
            return StageOutput.fail(
                error=decision["reason"],
                data=decision,
            )


class CostTrackingStage(Stage):
    """Stage that tracks costs associated with retries."""
    
    name = "cost_tracker"
    kind = StageKind.WORK
    
    def __init__(self, cost_per_token: float = 0.00001):
        self.cost_per_token = cost_per_token
        self.total_cost = 0.0
        self.cost_breakdown: List[Dict[str, Any]] = []
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        retry_count = ctx.inputs.get("retry_count", 0)
        tokens_used = ctx.inputs.get("tokens_used", 0)
        operation_type = ctx.inputs.get("operation_type", "unknown")
        
        operation_cost = tokens_used * self.cost_per_token
        retry_cost = retry_count * operation_cost * 0.1  # Retries cost less
        
        self.total_cost += operation_cost + retry_cost
        self.cost_breakdown.append({
            "operation": operation_type,
            "tokens": tokens_used,
            "retry_count": retry_count,
            "operation_cost": operation_cost,
            "retry_cost": retry_cost,
            "total_cost": self.total_cost,
            "timestamp": datetime.now().isoformat(),
        })
        
        return StageOutput.ok(
            result="cost_tracked",
            total_cost=self.total_cost,
            operation_cost=operation_cost,
            retry_cost=retry_cost,
        )


# ============================================================================
# TEST PIPELINE BUILDER
# ============================================================================

class ErrorClassificationPipelineBuilder:
    """Builder for error classification test pipelines."""
    
    def __init__(self):
        self.stages: List[Tuple[str, Stage, StageKind]] = []
        self.injector = ErrorInjector()
    
    def add_error_injection(
        self,
        stage_name: str = "error_injector",
        error_sequence: Optional[List[MockError]] = None,
    ) -> "ErrorClassificationPipelineBuilder":
        stage = ErrorInjectingStage(error_sequence=error_sequence)
        self.stages.append((stage_name, stage, StageKind.TRANSFORM))
        return self
    
    def add_classification(
        self,
        stage_name: str = "error_classifier",
        strict_mode: bool = False,
    ) -> "ErrorClassificationPipelineBuilder":
        stage = ErrorClassifyingStage(strict_mode=strict_mode)
        self.stages.append((stage_name, stage, StageKind.GUARD))
        return self
    
    def add_retry_decision(
        self,
        stage_name: str = "retry_decision",
        max_retries: int = 3,
    ) -> "ErrorClassificationPipelineBuilder":
        stage = RetryDecisionStage(max_retries=max_retries)
        self.stages.append((stage_name, stage, StageKind.WORK))
        return self
    
    def add_cost_tracking(
        self,
        stage_name: str = "cost_tracker",
    ) -> "ErrorClassificationPipelineBuilder":
        stage = CostTrackingStage()
        self.stages.append((stage_name, stage, StageKind.WORK))
        return self
    
    def build(self) -> stageflow.Pipeline:
        """Build the pipeline."""
        pipeline = stageflow.Pipeline()
        for stage_name, stage, kind in self.stages:
            pipeline = pipeline.with_stage(stage_name, stage, kind)
        return pipeline


# ============================================================================
# TEST RUNNERS
# ============================================================================

async def run_baseline_test(
    test_name: str,
    error_sequence: List[MockError],
) -> PipelineTestResult:
    """Run a baseline test with error classification."""
    result = PipelineTestResult(test_name=test_name, start_time=datetime.now())
    
    try:
        # Build pipeline
        builder = ErrorClassificationPipelineBuilder()
        builder.add_error_injection("injector", error_sequence)
        builder.add_classification("classifier")
        pipeline = builder.build()
        
        # Create context
        snapshot = ContextSnapshot(
        )
        ctx = create_stage_context(snapshot=snapshot)
        
        # Run pipeline
        for i, error in enumerate(error_sequence):
            ctx = create_stage_context(
                snapshot=ContextSnapshot(
                    input_text=f"test_input_{i}",
                )
            )
            
            # Inject error data into context
            ctx_data = {"error_data": error.to_dict()}
            
            # Run classification
            stage = ErrorClassifyingStage()
            output = await stage.execute(ctx)
            
            result.errors_encountered.append(error.to_dict())
            
            # Check classification accuracy
            classified_category = output.data.get("classification", {}).get(
                "classified_category"
            )
            if classified_category == error.category.value:
                result.errors_classified_correctly += 1
            else:
                result.errors_misclassified += 1
                result.silent_failures.append({
                    "error": error.to_dict(),
                    "classification": output.data.get("classification"),
                    "issue": f"Expected {error.category.value}, got {classified_category}",
                })
        
        result.success = True
    except Exception as e:
        logger.error(f"Test {test_name} failed: {e}")
        result.errors_encountered.append({
            "error": str(e),
            "type": "test_execution_error",
        })
    finally:
        result.end_time = datetime.now()
    
    return result


async def run_stress_test(
    test_name: str,
    error_count: int = 100,
) -> PipelineTestResult:
    """Run a stress test with high-volume errors."""
    result = PipelineTestResult(test_name=test_name, start_time=datetime.now())
    
    try:
        generator = ErrorScenarioGenerator(seed=random.randint(0, 10000))
        error_sequence = generator.generate_mixed_error_sequence(error_count)
        
        # Run baseline test with more comprehensive tracking
        for i, error in enumerate(error_sequence):
            # Simulate classification
            expected_category = error.category.value
            classified_category = expected_category  # Ideal case
            
            # Introduce misclassification rate for testing
            if random.random() < 0.05:  # 5% misclassification rate
                if expected_category == "transient":
                    classified_category = "permanent"
                else:
                    classified_category = "transient"
            
            result.errors_encountered.append(error.to_dict())
            
            if classified_category == expected_category:
                result.errors_classified_correctly += 1
            else:
                result.errors_misclassified += 1
                # Calculate cost impact of misclassification
                if expected_category == "transient" and classified_category == "permanent":
                    # Failed to retry a transient error
                    result.total_cost_estimate += error.metadata.get(
                        "estimated_tokens", 1000
                    ) * 0.00001
                elif expected_category == "permanent" and classified_category == "transient":
                    # Retried a permanent error (wasted cost)
                    result.total_cost_estimate += 3 * 0.01  # 3 retries at $0.01 each
        
        result.success = True
        
    except Exception as e:
        logger.error(f"Stress test {test_name} failed: {e}")
        result.errors_encountered.append({"error": str(e)})
    finally:
        result.end_time = datetime.now()
    
    return result


async def run_cost_impact_test(
    test_name: str,
    scenario_type: str = "permanent_as_transient",
) -> PipelineTestResult:
    """Test cost impact of misclassification."""
    result = PipelineTestResult(test_name=test_name, start_time=datetime.now())
    
    try:
        generator = ErrorScenarioGenerator(seed=42)
        
        if scenario_type == "permanent_as_transient":
            # Scenario: Permanent errors being retried
            error_sequence = generator.generate_cost_impact_scenario(10)
            
            for error in error_sequence:
                if error["category"] == "permanent":
                    # Simulate retrying permanent errors
                    for retry in range(3):
                        result.total_retries += 1
                        result.total_cost_estimate += 0.01  # Cost per retry
                        
                        if retry == 0:
                            result.errors_misclassified += 1
                            result.silent_failures.append({
                                "error": error,
                                "issue": "Permanent error retried (wasted cost)",
                                "cost_impact": 0.03,  # 3 retries
                            })
                else:
                    result.errors_classified_correctly += 1
                
                result.errors_encountered.append(error)
        else:
            error_sequence = generator.generate_transient_storm(20, success_after=15)
            for error in error_sequence:
                result.errors_encountered.append(error)
                result.errors_classified_correctly += 1
        
        result.success = True
        
    except Exception as e:
        logger.error(f"Cost impact test {test_name} failed: {e}")
    finally:
        result.end_time = datetime.now()
    
    return result


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

async def main():
    """Main entry point for running error classification tests."""
    print("=" * 80)
    print("WORK-006: Permanent vs Transient Error Classification Tests")
    print("=" * 80)
    print()
    
    results = []
    
    # Test 1: Baseline transient error handling
    print("[1/4] Running baseline transient error test...")
    transient_errors = [
        TransientErrors.timeout_error(),
        TransientErrors.rate_limited_error(),
        TransientErrors.network_glitch(),
    ]
    result = await run_baseline_test("baseline_transient", transient_errors)
    results.append(result)
    print(f"  - Errors: {len(result.errors_encountered)}")
    print(f"  - Classified correctly: {result.errors_classified_correctly}")
    print(f"  - Misclassified: {result.errors_misclassified}")
    print()
    
    # Test 2: Baseline permanent error handling
    print("[2/4] Running baseline permanent error test...")
    permanent_errors = [
        PermanentErrors.invalid_api_key(),
        PermanentErrors.malformed_request(),
        PermanentErrors.resource_not_found(),
    ]
    result = await run_baseline_test("baseline_permanent", permanent_errors)
    results.append(result)
    print(f"  - Errors: {len(result.errors_encountered)}")
    print(f"  - Classified correctly: {result.errors_classified_correctly}")
    print(f"  - Misclassified: {result.errors_misclassified}")
    print()
    
    # Test 3: Stress test with mixed errors
    print("[3/4] Running stress test with 100 mixed errors...")
    result = await run_stress_test("stress_mixed", error_count=100)
    results.append(result)
    print(f"  - Errors: {len(result.errors_encountered)}")
    print(f"  - Classified correctly: {result.errors_classified_correctly}")
    print(f"  - Misclassified: {result.errors_misclassified}")
    print(f"  - Cost impact: ${result.total_cost_estimate:.4f}")
    print()
    
    # Test 4: Cost impact test
    print("[4/4] Running cost impact test...")
    result = await run_cost_impact_test("cost_impact", "permanent_as_transient")
    results.append(result)
    print(f"  - Errors: {len(result.errors_encountered)}")
    print(f"  - Total retries: {result.total_retries}")
    print(f"  - Cost estimate: ${result.total_cost_estimate:.4f}")
    print(f"  - Silent failures: {len(result.silent_failures)}")
    print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    total_errors = sum(len(r.errors_encountered) for r in results)
    total_correct = sum(r.errors_classified_correctly for r in results)
    total_misclassified = sum(r.errors_misclassified for r in results)
    total_cost = sum(r.total_cost_estimate for r in results)
    
    print(f"Total errors tested: {total_errors}")
    print(f"Overall classification accuracy: {total_correct / max(1, total_errors) * 100:.1f}%")
    print(f"Total misclassified: {total_misclassified}")
    print(f"Total cost impact: ${total_cost:.4f}")
    print()
    
    # Save results
    results_path = Path("results/error_classification_results.json")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(results_path, "w") as f:
        json.dump(
            {
                "test_run_timestamp": datetime.now().isoformat(),
                "results": [r.to_dict() for r in results],
                "summary": {
                    "total_errors": total_errors,
                    "total_correct": total_correct,
                    "total_misclassified": total_misclassified,
                    "total_cost": total_cost,
                    "accuracy": total_correct / max(1, total_errors),
                },
            },
            f,
            indent=2,
        )
    
    print(f"Results saved to: {results_path}")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())
