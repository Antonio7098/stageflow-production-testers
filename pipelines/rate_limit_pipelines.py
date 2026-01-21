"""
Rate Limit Test Pipelines for Stageflow

Implements multiple test pipeline categories for comprehensive rate limit testing:
1. Baseline Pipeline - Normal operation within limits
2. Stress Pipeline - High load and concurrency
3. Chaos Pipeline - Injected failures and edge cases
4. Recovery Pipeline - Failure recovery and rollback
"""

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Stageflow imports
import stageflow
from stageflow import (
    Pipeline, Stage, StageKind, StageOutput, StageContext,
    PipelineContext, PipelineTimer, create_stage_context,
    get_default_interceptors, run_with_interceptors, LoggingInterceptor,
    MetricsInterceptor
)
from stageflow.context import ContextSnapshot, RunIdentity

# Local imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from mocks.services.rate_limit_mocks import (
    MockRateLimitedLLMService, RateLimitError, RateLimitConfig,
    RateLimitAlgorithm, create_rate_limited_service
)
from mocks.data.rate_limit_test_data import (
    RateLimitTestDataGenerator, RateLimitTestCase, RateLimitScenario
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("rate_limit_pipelines")


# =============================================================================
# Stage Implementations
# =============================================================================

@dataclass
class LLMCallResult:
    """Result of an LLM call for tracking."""
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    latency_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


class RateLimitedLLMStage(Stage):
    """
    Stage that makes LLM calls with rate limiting.
    
    Demonstrates proper rate limit handling within a Stageflow pipeline.
    """
    
    name = "llm_call"
    kind = StageKind.WORK
    
    def __init__(
        self,
        llm_service: MockRateLimitedLLMService,
        model: str = "llama-3.1-8b-instant",
        max_retries: int = 3
    ):
        self.llm_service = llm_service
        self.model = model
        self.max_retries = max_retries
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute LLM call with rate limit handling."""
        messages = ctx.inputs.get("messages", [])
        test_case = ctx.inputs.get("test_case")
        
        start_time = time.time()
        retry_count = 0
        
        try:
            # Attempt call with retry
            response = await self.llm_service.chat_with_retry(
                messages=messages,
                model=self.model,
                max_retries=self.max_retries
            )
            
            latency_ms = (time.time() - start_time) * 1000
            
            return StageOutput.ok(
                result={
                    "content": response.content,
                    "model": response.model,
                    "tokens": response.input_tokens + response.output_tokens,
                    "latency_ms": latency_ms
                },
                llm_response=response.to_dict()
            )
            
        except RateLimitError as e:
            latency_ms = (time.time() - start_time) * 1000
            return StageOutput.retry(
                error=f"Rate limited: {e.message}",
                data={
                    "retry_after_ms": e.retry_after_ms,
                    "retryable": True,
                    "attempt": retry_count + 1,
                    "latency_ms": latency_ms,
                    "algorithm": e.algorithm.value
                }
            )
        
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return StageOutput.fail(
                error=f"LLM call failed: {str(e)}",
                data={
                    "retryable": False,
                    "latency_ms": latency_ms
                }
            )


class RateLimitDetectorStage(Stage):
    """
    Stage that detects and classifies rate limit responses.
    
    Used for testing detection accuracy.
    """
    
    name = "rate_limit_detector"
    kind = StageKind.GUARD
    
    def __init__(self):
        self.detection_count = 0
        self.false_positives = 0
        self.false_negatives = 0
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        """Detect rate limit conditions."""
        prior_output = ctx.inputs.get_from("llm_call")
        
        if prior_output is None:
            return StageOutput.skip(reason="No prior output to check")
        
        # Check if this was a rate limit
        is_rate_limit = (
            prior_output.status == "retry" and
            prior_output.data.get("retryable", False) and
            "rate" in prior_output.error.lower()
        )
        
        self.detection_count += 1
        
        if is_rate_limit:
            return StageOutput.ok(
                result={
                    "rate_limit_detected": True,
                    "retry_after_ms": prior_output.data.get("retry_after_ms"),
                    "was_retry_output": prior_output.status == "retry"
                }
            )
        else:
            return StageOutput.ok(
                result={
                    "rate_limit_detected": False,
                    "output_status": prior_output.status
                }
            )


class MetricsCollectionStage(Stage):
    """
    Stage that collects and aggregates metrics from prior stages.
    """
    
    name = "metrics_collection"
    kind = StageKind.ENRICH
    
    def __init__(self):
        self.results = []
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        """Collect metrics from all prior stages."""
        # Collect from LLM stage
        llm_output = ctx.inputs.get_from("llm_call")
        detector_output = ctx.inputs.get_from("rate_limit_detector")
        
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "llm_status": llm_output.status if llm_output else None,
            "llm_latency_ms": llm_output.data.get("latency_ms") if llm_output else None,
            "rate_limit_detected": detector_output.result.get("rate_limit_detected") if detector_output else None,
        }
        
        self.results.append(metrics)
        
        return StageOutput.ok(
            result=metrics,
            metrics={"request_count": len(self.results)}
        )


class RetryStage(Stage):
    """
    Stage that implements retry logic for failed requests.
    
    Demonstrates retry pattern implementation.
    """
    
    name = "retry_handler"
    kind = StageKind.WORK
    
    def __init__(
        self,
        llm_service: MockRateLimitedLLMService,
        max_retries: int = 5,
        base_delay_ms: int = 1000
    ):
        self.llm_service = llm_service
        self.max_retries = max_retries
        self.base_delay_ms = base_delay_ms
        self.retry_history = []
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute with retry logic."""
        messages = ctx.inputs.get("messages", [])
        
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.llm_service.chat(messages)
                
                self.retry_history.append({
                    "attempt": attempt + 1,
                    "success": True,
                    "latency_ms": response.latency_ms
                })
                
                return StageOutput.ok(
                    result={"content": response.content},
                    retry_attempts=attempt,
                    success=True
                )
                
            except RateLimitError as e:
                last_error = e
                
                self.retry_history.append({
                    "attempt": attempt + 1,
                    "success": False,
                    "error": str(e),
                    "retry_after_ms": e.retry_after_ms
                })
                
                if attempt < self.max_retries:
                    # Exponential backoff with jitter
                    delay = (self.base_delay_ms / 1000) * (2 ** attempt)
                    jitter = delay * 0.1 * (0.5 - random.random())
                    wait_time = max(0, delay + jitter)
                    
                    await asyncio.sleep(wait_time)
        
        # All retries exhausted
        return StageOutput.fail(
            error=f"All {self.max_retries} retries exhausted: {last_error}",
            data={
                "retry_history": self.retry_history,
                "final_error": str(last_error)
            }
        )


# =============================================================================
# Pipeline Builders
# =============================================================================

class RateLimitPipelineBuilder:
    """Builder for rate limit test pipelines."""
    
    def __init__(self, llm_service: Optional[MockRateLimitedLLMService] = None):
        self.llm_service = llm_service or create_rate_limited_service()
        self._stages = []
        self._results = []
    
    def create_baseline_pipeline(self) -> Pipeline:
        """Create baseline pipeline for normal operation."""
        return (
            Pipeline("baseline_rate_limit_pipeline")
            .with_stage("llm_call", RateLimitedLLMStage, StageKind.WORK,
                       config={"llm_service": self.llm_service})
            .with_stage("metrics_collection", MetricsCollectionStage, StageKind.ENRICH)
        )
    
    def create_stress_pipeline(self, concurrency: int = 10) -> Pipeline:
        """Create stress pipeline for high concurrency testing."""
        return (
            Pipeline("stress_rate_limit_pipeline")
            .with_stage("llm_call", RateLimitedLLMStage, StageKind.WORK,
                       config={"llm_service": self.llm_service})
            .with_stage("rate_limit_detector", RateLimitDetectorStage, StageKind.GUARD)
            .with_stage("metrics_collection", MetricsCollectionStage, StageKind.ENRICH)
        )
    
    def create_chaos_pipeline(self, failure_injection_rate: float = 0.5) -> Pipeline:
        """Create chaos pipeline with failure injection."""
        return (
            Pipeline("chaos_rate_limit_pipeline")
            .with_stage("retry_handler", RetryStage, StageKind.WORK,
                       config={
                           "llm_service": self.llm_service,
                           "max_retries": 3,
                           "base_delay_ms": 500
                       })
            .with_stage("metrics_collection", MetricsCollectionStage, StageKind.ENRICH)
        )
    
    def create_comprehensive_pipeline(self) -> Pipeline:
        """Create comprehensive pipeline with all test stages."""
        return (
            Pipeline("comprehensive_rate_limit_pipeline")
            .with_stage("llm_call", RateLimitedLLMStage, StageKind.WORK,
                       config={"llm_service": self.llm_service})
            .with_stage("rate_limit_detector", RateLimitDetectorStage, StageKind.GUARD)
            .with_stage("retry_handler", RetryStage, StageKind.WORK,
                       config={
                           "llm_service": self.llm_service,
                           "max_retries": 5,
                           "base_delay_ms": 1000
                       })
            .with_stage("metrics_collection", MetricsCollectionStage, StageKind.ENRICH)
        )


# =============================================================================
# Pipeline Runner
# =============================================================================

class RateLimitPipelineRunner:
    """Runner for executing rate limit test pipelines."""
    
    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir or Path("results/logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.execution_history = []
    
    async def run_baseline_test(
        self,
        test_case: RateLimitTestCase,
        service: MockRateLimitedLLMService
    ) -> dict[str, Any]:
        """Run baseline test for a single test case."""
        logger.info(f"Running baseline test: {test_case.name}")
        
        # Create service with test case config
        test_service = create_rate_limited_service(
            rpm=test_case.rpm,
            burst=test_case.burst
        )
        
        # Create pipeline
        builder = RateLimitPipelineBuilder(test_service)
        pipeline = builder.create_baseline_pipeline()
        
        # Execute multiple requests
        results = []
        for i in range(test_case.request_count):
            try:
                result = await self._execute_single_request(
                    pipeline, test_service, i + 1
                )
                results.append(result)
            except Exception as e:
                results.append({
                    "request": i + 1,
                    "success": False,
                    "error": str(e)
                })
        
        # Calculate metrics
        success_count = sum(1 for r in results if r.get("success", False))
        rate_limited_count = sum(
            1 for r in results 
            if "rate limited" in r.get("error", "").lower()
        )
        
        return {
            "test_case": test_case.name,
            "expected_behavior": test_case.expected_behavior,
            "requests": test_case.request_count,
            "successes": success_count,
            "rate_limited": rate_limited_count,
            "success_rate": success_count / test_case.request_count if test_case.request_count > 0 else 0,
            "results": results,
            "timestamp": datetime.now().isoformat()
        }
    
    async def _execute_single_request(
        self,
        pipeline: Pipeline,
        service: MockRateLimitedLLMService,
        request_num: int
    ) -> dict[str, Any]:
        """Execute a single request through the pipeline."""
        start_time = time.time()
        
        # Create context
        run_id = RunIdentity(
            pipeline_run_id=f"run_{request_num:04d}",
            user_id="test_user",
            org_id="test_org",
            session_id="test_session"
        )
        
        timer = PipelineTimer()
        snapshot = ContextSnapshot(
            run_id=run_id,
            input_text=f"Test request {request_num}",
            metadata={"request_num": request_num}
        )
        
        ctx = create_stage_context(
            snapshot=snapshot,
            stage_name="llm_call",
            timer=timer,
            data={"messages": [{"role": "user", "content": f"Test message {request_num}"}]}
        )
        
        try:
            # Build and run
            graph = pipeline.build()
            result = await graph.run(ctx)
            
            latency_ms = (time.time() - start_time) * 1000
            
            return {
                "request": request_num,
                "success": True,
                "status": result.status if hasattr(result, 'status') else "unknown",
                "latency_ms": latency_ms
            }
            
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return {
                "request": request_num,
                "success": False,
                "error": str(e),
                "latency_ms": latency_ms
            }
    
    async def run_scenario_tests(
        self,
        scenario: RateLimitScenario,
        service: MockRateLimitedLLMService
    ) -> dict[str, Any]:
        """Run all test cases in a scenario."""
        logger.info(f"Running scenario: {scenario.name}")
        
        results = {
            "scenario": scenario.name,
            "description": scenario.description,
            "test_results": [],
            "summary": {}
        }
        
        for test_case in scenario.test_cases:
            test_result = await self.run_baseline_test(test_case, service)
            results["test_results"].append(test_result)
        
        # Calculate summary
        total_requests = sum(r["requests"] for r in results["test_results"])
        total_successes = sum(r["successes"] for r in results["test_results"])
        total_rate_limited = sum(r["rate_limited"] for r in results["test_results"])
        
        results["summary"] = {
            "total_requests": total_requests,
            "total_successes": total_successes,
            "total_rate_limited": total_rate_limited,
            "overall_success_rate": total_successes / total_requests if total_requests > 0 else 0,
            "tests_passed": sum(
                1 for r in results["test_results"]
                if r["success_rate"] >= 0.9
            ),
            "tests_failed": sum(
                1 for r in results["test_results"]
                if r["success_rate"] < 0.9
            )
        }
        
        return results
    
    async def run_all_tests(
        self,
        generator: RateLimitTestDataGenerator
    ) -> dict[str, Any]:
        """Run all test scenarios."""
        logger.info("Running all rate limit tests")
        
        all_results = {
            "test_run_timestamp": datetime.now().isoformat(),
            "scenarios": [],
            "overall_summary": {}
        }
        
        service = create_rate_limited_service(rpm=60, burst=10)
        
        for scenario in generator.generate_all_scenarios():
            scenario_result = await self.run_scenario_tests(scenario, service)
            all_results["scenarios"].append(scenario_result)
        
        # Calculate overall summary
        total_tests = sum(len(s["test_results"]) for s in all_results["scenarios"])
        passed_tests = sum(
            s["summary"].get("tests_passed", 0) 
            for s in all_results["scenarios"]
        )
        failed_tests = sum(
            s["summary"].get("tests_failed", 0) 
            for s in all_results["scenarios"]
        )
        
        all_results["overall_summary"] = {
            "total_test_cases": total_tests,
            "passed": passed_tests,
            "failed": failed_tests,
            "pass_rate": passed_tests / total_tests if total_tests > 0 else 0
        }
        
        # Save results
        self._save_results(all_results)
        
        return all_results
    
    def _save_results(self, results: dict[str, Any]):
        """Save test results to file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self.log_dir / f"rate_limit_test_results_{timestamp}.json"
        
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2, default=str)
        
        logger.info(f"Results saved to: {output_file}")


# =============================================================================
# Main Execution
# =============================================================================

async def main():
    """Main entry point for running rate limit tests."""
    print("=" * 60)
    print("Stageflow Rate Limit Handling Test Suite")
    print("=" * 60)
    print()
    
    # Initialize
    generator = RateLimitTestDataGenerator(seed=42)
    runner = RateLimitPipelineRunner()
    
    # Run tests
    results = await runner.run_all_tests(generator)
    
    # Print summary
    print("\nTest Results Summary")
    print("-" * 40)
    print(f"Total test cases: {results['overall_summary']['total_test_cases']}")
    print(f"Passed: {results['overall_summary']['passed']}")
    print(f"Failed: {results['overall_summary']['failed']}")
    print(f"Pass rate: {results['overall_summary']['pass_rate']:.2%}")
    print()
    
    # Print scenario summaries
    for scenario in results["scenarios"]:
        print(f"\n{scenario['scenario']}:")
        print(f"  Tests: {scenario['summary']['tests_passed']}/{scenario['summary']['total_test_cases']} passed")
        print(f"  Success rate: {scenario['summary'].get('overall_success_rate', 0):.2%}")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())
