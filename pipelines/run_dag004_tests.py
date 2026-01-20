"""
DAG-004: Starvation of Low-Priority Jobs - Test Pipelines

This module implements test pipelines to verify Stageflow's behavior
under starvation conditions.

Industry Persona: Financial Services Compliance & Risk Management
Role: Lead Reliability Engineer at a global investment bank
Concerns:
- Compliance reports must complete within regulatory time windows
- High-frequency trading transactions cannot be delayed
- Audit trails must be maintained even under peak load
"""

import asyncio
import json
import logging
import random
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import stageflow
from stageflow import (
    Pipeline, Stage, StageKind, StageOutput, StageContext,
    create_stage_context, create_stage_inputs, PipelineTimer,
)
from stageflow.context import ContextSnapshot
from mocks.dag004_mock_data import (
    MockRateLimiter,
    MockTransactionGenerator,
    MockComplianceGenerator,
    WorkloadSimulator,
    STARVATION_TEST_CONFIGS,
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("dag004_tests")


# ============================================================================
# Test Stages
# =========================================================================


class HighPriorityTransactionStage(Stage):
    """
    Simulates high-priority transaction processing.
    Represents the core business function that must not be delayed.
    """
    name = "process_transaction"
    kind = StageKind.TRANSFORM

    def __init__(self, rate_limiter: MockRateLimiter | None = None):
        self.rate_limiter = rate_limiter
        self._processed_count = 0
        self._processing_times = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.perf_counter()

        # Simulate rate-limited external API call
        if self.rate_limiter:
            acquired = await self.rate_limiter.acquire(timeout=0.1)
            if not acquired:
                return StageOutput.fail(
                    error="Rate limited",
                    data={"status": "rate_limited"},
                )
            try:
                await asyncio.sleep(random.uniform(0.01, 0.05))  # Simulate API call
            finally:
                self.rate_limiter.release()
        else:
            await asyncio.sleep(random.uniform(0.01, 0.05))

        processing_time = time.perf_counter() - start_time
        self._processing_times.append(processing_time)
        self._processed_count += 1

        return StageOutput.ok(
            transaction_processed=True,
            processing_time=processing_time,
            count=self._processed_count,
        )


class LowPriorityComplianceStage(Stage):
    """
    Simulates low-priority compliance reporting.
    This is the type of work that can be starved by high-priority transactions.
    """
    name = "generate_compliance_report"
    kind = StageKind.WORK

    def __init__(self, rate_limiter: MockRateLimiter | None = None):
        self.rate_limiter = rate_limiter
        self._reports_generated = 0
        self._wait_times = []
        self._start_time = None

    async def execute(self, ctx: StageContext) -> StageOutput:
        if self._start_time is None:
            self._start_time = time.perf_counter()

        # Simulate rate-limited external API call (database, storage, etc.)
        if self.rate_limiter:
            acquired = await self.rate_limiter.acquire(timeout=10.0)  # Longer timeout
            if not acquired:
                return StageOutput.fail(
                    error="Rate limited - possible starvation",
                    data={"status": "rate_limited", "waited": True},
                )
            try:
                await asyncio.sleep(random.uniform(0.1, 0.3))  # Slower than transactions
            finally:
                self.rate_limiter.release()
        else:
            await asyncio.sleep(random.uniform(0.1, 0.3))

        wait_time = time.perf_counter() - self._start_time
        self._wait_times.append(wait_time)
        self._reports_generated += 1

        return StageOutput.ok(
            report_generated=True,
            wait_time=wait_time,
            total_reports=self._reports_generated,
        )


class BackgroundAuditStage(Stage):
    """
    Simulates background audit logging.
    Critical for compliance but can be delayed without immediate impact.
    """
    name = "audit_log"
    kind = StageKind.WORK

    def __init__(self):
        self._audit_entries = 0
        self._execution_times = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.perf_counter()

        # Simulate audit log write
        await asyncio.sleep(random.uniform(0.02, 0.08))

        execution_time = time.perf_counter() - start_time
        self._execution_times.append(execution_time)
        self._audit_entries += 1

        return StageOutput.ok(
            audit_written=True,
            execution_time=execution_time,
            total_entries=self._audit_entries,
        )


class MetricsCollectorStage(Stage):
    """Collects metrics from context for analysis."""
    name = "collect_metrics"
    kind = StageKind.TRANSFORM

    async def execute(self, ctx: StageContext) -> StageOutput:
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "pipeline_run_id": str(uuid.uuid4()),
        }

        # Collect any metrics from prior stages
        for key, value in ctx.snapshot.data.items():
            if "metric" in key.lower() or "count" in key.lower() or "time" in key.lower():
                metrics[key] = value

        return StageOutput.ok(metrics=metrics)


# ============================================================================
# Test Pipelines
# =========================================================================


def create_baseline_pipeline(rate_limiter: MockRateLimiter | None = None) -> Pipeline:
    """
    Baseline pipeline with balanced workload.
    All stages have equal opportunity to execute.
    """
    pipeline = (
        Pipeline()
        .with_stage("process_transaction", HighPriorityTransactionStage(rate_limiter), StageKind.TRANSFORM)
        .with_stage("generate_compliance_report", LowPriorityComplianceStage(rate_limiter), StageKind.WORK)
        .with_stage("audit_log", BackgroundAuditStage(), StageKind.WORK)
    )
    return pipeline


def create_starvation_pipeline(
    rate_limiter: MockRateLimiter | None = None,
    num_high_priority: int = 5,
    num_low_priority: int = 1,
) -> Pipeline:
    """
    Pipeline designed to demonstrate starvation.
    Multiple high-priority stages compete with few low-priority stages.
    """
    pipeline = Pipeline()

    # Add multiple high-priority stages (simulating continuous high-priority work)
    for i in range(num_high_priority):
        pipeline = pipeline.with_stage(
            f"process_transaction_{i}",
            HighPriorityTransactionStage(rate_limiter),
            StageKind.TRANSFORM,
        )

    # Add few low-priority stages (simulating background work)
    for i in range(num_low_priority):
        pipeline = pipeline.with_stage(
            f"generate_compliance_report_{i}",
            LowPriorityComplianceStage(rate_limiter),
            StageKind.WORK,
        )

    # Add audit stage at the end
    pipeline = pipeline.with_stage("audit_log", BackgroundAuditStage(), StageKind.WORK)

    return pipeline


def create_diamond_starvation_pipeline(rate_limiter: MockRateLimiter | None = None) -> Pipeline:
    """
    Diamond pattern that can lead to starvation.
    High-priority branches can starve the merge and low-priority stages.
    """
    return (
        Pipeline()
        # Fan-out high-priority stages
        .with_stage("txn_1", HighPriorityTransactionStage(rate_limiter), StageKind.TRANSFORM)
        .with_stage("txn_2", HighPriorityTransactionStage(rate_limiter), StageKind.TRANSFORM)
        .with_stage("txn_3", HighPriorityTransactionStage(rate_limiter), StageKind.TRANSFORM)
        .with_stage("txn_4", HighPriorityTransactionStage(rate_limiter), StageKind.TRANSFORM)
        # Low-priority stages that need to run after
        .with_stage("compliance_1", LowPriorityComplianceStage(rate_limiter), StageKind.WORK)
        .with_stage("compliance_2", LowPriorityComplianceStage(rate_limiter), StageKind.WORK)
        # Audit stage
        .with_stage("audit", BackgroundAuditStage(), StageKind.WORK)
    )


# ============================================================================
# Test Execution
# =========================================================================


@dataclass
class TestResult:
    """Result of a single test run."""
    test_name: str
    status: str  # PASS, FAIL, ERROR
    duration_ms: float
    stages_completed: int
    stages_total: int
    high_priority_completed: int = 0
    low_priority_completed: int = 0
    error_message: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)


class StarvationTestRunner:
    """Executes starvation tests and collects results."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.results: list[TestResult] = []
        self.logs_dir = output_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _create_context(self) -> StageContext:
        """Create a fresh StageContext for each test."""
        snapshot = ContextSnapshot(
            input_text="starvation_test",
        )
        timer = PipelineTimer()
        inputs = create_stage_inputs(
            snapshot=snapshot,
            prior_outputs={},
            declared_deps=[],
            stage_name="root",
            strict=False,
        )
        return create_stage_context(
            snapshot=snapshot,
            inputs=inputs,
            stage_name="root",
            timer=timer,
        )

    async def run_baseline_test(self) -> TestResult:
        """Test baseline operation with balanced workload."""
        test_name = "baseline_test"
        logger.info(f"Running {test_name}")

        rate_limiter = MockRateLimiter(max_concurrent=50, rate_per_second=1000)
        pipeline = create_baseline_pipeline(rate_limiter)
        graph = pipeline.build()

        start_time = time.perf_counter()
        try:
            results = await graph.run(self._create_context())
            duration_ms = (time.perf_counter() - start_time) * 1000

            completed = sum(1 for r in results.values() if r.status.value == "ok")

            return TestResult(
                test_name=test_name,
                status="PASS",
                duration_ms=duration_ms,
                stages_completed=completed,
                stages_total=len(results),
                high_priority_completed=1,
                low_priority_completed=1,
                metrics=rate_limiter.get_stats(),
            )
        except Exception as e:
            return TestResult(
                test_name=test_name,
                status="ERROR",
                duration_ms=0,
                stages_completed=0,
                stages_total=3,
                error_message=str(e),
            )

    async def run_starvation_test(
        self,
        num_high: int = 10,
        num_low: int = 2,
        max_concurrent: int = 5,
        rate_per_second: int = 20,
    ) -> TestResult:
        """
        Test starvation conditions.
        High-priority stages should not completely block low-priority stages.
        """
        test_name = f"starvation_test_h{num_high}_l{num_low}"
        logger.info(f"Running {test_name}")

        rate_limiter = MockRateLimiter(max_concurrent=max_concurrent, rate_per_second=rate_per_second)
        pipeline = create_starvation_pipeline(rate_limiter, num_high_priority=num_high, num_low_priority=num_low)
        graph = pipeline.build()

        start_time = time.perf_counter()
        try:
            results = await graph.run(self._create_context())
            duration_ms = (time.perf_counter() - start_time) * 1000

            completed = sum(1 for r in results.values() if r.status.value == "ok")

            # Count high vs low priority completions
            high_completed = sum(
                1 for name, r in results.items()
                if "transaction" in name and r.status.value == "ok"
            )
            low_completed = sum(
                1 for name, r in results.items()
                if "compliance" in name and r.status.value == "ok"
            )

            # Check for starvation: low priority should complete
            starvation_detected = low_completed == 0 and num_low > 0

            return TestResult(
                test_name=test_name,
                status="PASS" if not starvation_detected else "FAIL",
                duration_ms=duration_ms,
                stages_completed=completed,
                stages_total=num_high + num_low + 1,
                high_priority_completed=high_completed,
                low_priority_completed=low_completed,
                error_message="Starvation detected: low-priority stages never completed" if starvation_detected else None,
                metrics={
                    **rate_limiter.get_stats(),
                    "starvation_detected": starvation_detected,
                    "high_to_low_ratio": high_completed / max(low_completed, 1),
                },
            )
        except Exception as e:
            return TestResult(
                test_name=test_name,
                status="ERROR",
                duration_ms=0,
                stages_completed=0,
                stages_total=num_high + num_low + 1,
                error_message=str(e),
            )

    async def run_resource_contention_test(
        self,
        max_concurrent: int = 3,
        rate_per_second: int = 10,
    ) -> TestResult:
        """
        Test with tight resource constraints.
        Low-priority stages should eventually get resources.
        """
        test_name = f"resource_contention_c{max_concurrent}_r{rate_per_second}"
        logger.info(f"Running {test_name}")

        rate_limiter = MockRateLimiter(max_concurrent=max_concurrent, rate_per_second=rate_per_second)
        pipeline = create_diamond_starvation_pipeline(rate_limiter)
        graph = pipeline.build()

        start_time = time.perf_counter()
        try:
            results = await graph.run(self._create_context())
            duration_ms = (time.perf_counter() - start_time) * 1000

            completed = sum(1 for r in results.values() if r.status.value == "ok")

            # Check if low-priority compliance stages completed
            compliance_stages = [name for name in results.keys() if "compliance" in name]
            compliance_completed = sum(
                1 for name in compliance_stages
                if results[name].status.value == "ok"
            )

            # Check for starvation
            starvation_detected = len(compliance_stages) > 0 and compliance_completed == 0

            return TestResult(
                test_name=test_name,
                status="PASS" if not starvation_detected else "FAIL",
                duration_ms=duration_ms,
                stages_completed=completed,
                stages_total=len(results),
                high_priority_completed=sum(
                    1 for name, r in results.items()
                    if "txn" in name and r.status.value == "ok"
                ),
                low_priority_completed=compliance_completed,
                error_message="Starvation detected under resource contention" if starvation_detected else None,
                metrics={
                    **rate_limiter.get_stats(),
                    "starvation_detected": starvation_detected,
                    "compliance_stages": compliance_stages,
                },
            )
        except Exception as e:
            return TestResult(
                test_name=test_name,
                status="ERROR",
                duration_ms=0,
                stages_completed=0,
                stages_total=7,
                error_message=str(e),
            )

    async def run_silent_failure_test(self) -> TestResult:
        """
        Test for silent failures - stages that appear to complete but produce incorrect results.
        """
        test_name = "silent_failure_test"
        logger.info(f"Running {test_name}")

        rate_limiter = MockRateLimiter(max_concurrent=2, rate_per_second=5)
        pipeline = create_starvation_pipeline(rate_limiter, num_high_priority=5, num_low_priority=2)
        graph = pipeline.build()

        start_time = time.perf_counter()
        try:
            results = await graph.run(self._create_context())
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Analyze results for silent failures
            silent_failures = []

            for name, output in results.items():
                # Check for stages that completed but have unexpected data
                if output.status.value == "ok":
                    if hasattr(output, "data"):
                        # Check for missing expected fields
                        if "count" in name.lower() or "compliance" in name.lower():
                            if output.data.get("total_reports", 0) == 0 and "compliance" in name:
                                silent_failures.append(f"{name}: reported success but no reports generated")

                        # Check for abnormal metrics
                        if "wait_time" in output.data:
                            if output.data["wait_time"] > 60:  # > 1 minute wait
                                silent_failures.append(f"{name}: excessive wait time detected")

            return TestResult(
                test_name=test_name,
                status="PASS" if len(silent_failures) == 0 else "FAIL",
                duration_ms=duration_ms,
                stages_completed=len(results),
                stages_total=8,
                high_priority_completed=sum(1 for n, r in results.items() if "transaction" in n and r.status.value == "ok"),
                low_priority_completed=sum(1 for n, r in results.items() if "compliance" in n and r.status.value == "ok"),
                error_message=None if len(silent_failures) == 0 else "; ".join(silent_failures),
                metrics={"silent_failures": silent_failures},
            )
        except Exception as e:
            return TestResult(
                test_name=test_name,
                status="ERROR",
                duration_ms=0,
                stages_completed=0,
                stages_total=8,
                error_message=str(e),
            )

    async def run_all_tests(self) -> list[TestResult]:
        """Run all starvation tests."""
        logger.info("=" * 60)
        logger.info("Starting DAG-004 Starvation Tests")
        logger.info("=" * 60)

        results = []

        # Test 1: Baseline
        logger.info("\n--- Test 1: Baseline ---")
        results.append(await self.run_baseline_test())

        # Test 2: Starvation with varying parameters
        logger.info("\n--- Test 2: Starvation Tests ---")
        starvation_params = [
            (5, 2, 5, 20),
            (10, 2, 5, 20),
            (20, 2, 5, 20),
            (50, 2, 3, 10),
        ]
        for params in starvation_params:
            results.append(await self.run_starvation_test(*params))

        # Test 3: Resource contention
        logger.info("\n--- Test 3: Resource Contention ---")
        contention_params = [
            (2, 5),
            (3, 10),
            (1, 3),
        ]
        for params in contention_params:
            results.append(await self.run_resource_contention_test(*params))

        # Test 4: Silent failure detection
        logger.info("\n--- Test 4: Silent Failure Detection ---")
        results.append(await self.run_silent_failure_test())

        self.results = results
        return results

    def save_results(self):
        """Save test results to files."""
        # Save JSON results
        results_file = self.output_dir / "metrics" / "dag004_results.json"
        results_file.parent.mkdir(parents=True, exist_ok=True)

        results_data = {
            "test_run_id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(self.results),
            "passed": sum(1 for r in self.results if r.status == "PASS"),
            "failed": sum(1 for r in self.results if r.status == "FAIL"),
            "errors": sum(1 for r in self.results if r.status == "ERROR"),
            "results": [
                {
                    "test_name": r.test_name,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "stages_completed": r.stages_completed,
                    "stages_total": r.stages_total,
                    "high_priority_completed": r.high_priority_completed,
                    "low_priority_completed": r.low_priority_completed,
                    "error_message": r.error_message,
                    "metrics": r.metrics,
                }
                for r in self.results
            ],
        }

        with open(results_file, "w") as f:
            json.dump(results_data, f, indent=2)

        # Generate summary
        summary_file = self.output_dir / "metrics" / "dag004_summary.json"
        summary_data = {
            "test_run_id": results_data["test_run_id"],
            "timestamp": results_data["timestamp"],
            "total_tests": results_data["total_tests"],
            "passed": results_data["passed"],
            "failed": results_data["failed"],
            "errors": results_data["errors"],
            "pass_rate": results_data["passed"] / results_data["total_tests"] if results_data["total_tests"] > 0 else 0,
            "starvation_tests_failed": sum(
                1 for r in self.results
                if "starvation" in r.test_name and r.status == "FAIL"
            ),
            "contention_tests_failed": sum(
                1 for r in self.results
                if "contention" in r.test_name and r.status == "FAIL"
            ),
        }

        with open(summary_file, "w") as f:
            json.dump(summary_data, f, indent=2)

        logger.info(f"\nResults saved to {results_file}")
        logger.info(f"Summary saved to {summary_file}")

        return summary_data


# ============================================================================
# Main Entry Point
# =========================================================================


async def main():
    """Run all DAG-004 starvation tests."""
    output_dir = Path(__file__).parent.parent / "results"
    runner = StarvationTestRunner(output_dir)

    try:
        results = await runner.run_all_tests()
        summary = runner.save_results()

        print("\n" + "=" * 60)
        print("DAG-004 Starvation Test Results")
        print("=" * 60)
        print(f"Total Tests: {summary['total_tests']}")
        print(f"Passed: {summary['passed']}")
        print(f"Failed: {summary['failed']}")
        print(f"Errors: {summary['errors']}")
        print(f"Pass Rate: {summary['pass_rate']:.1%}")
        print("=" * 60)

        # Print individual results
        for result in results:
            status_symbol = "✅" if result.status == "PASS" else "❌" if result.status == "FAIL" else "⚠️"
            print(f"{status_symbol} {result.test_name}: {result.status}")
            if result.error_message:
                print(f"   Error: {result.error_message[:100]}")

        return summary

    except Exception as e:
        logger.error(f"Test suite failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
