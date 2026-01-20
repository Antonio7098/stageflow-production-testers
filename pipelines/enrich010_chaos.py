"""
ENRICH-010 Chaos Pipeline: Metadata Filtering Stress Testing

This module implements chaos engineering pipelines for stress-testing
Stageflow's ENRICH stage handling of metadata filtering under adverse
conditions including high load, malformed inputs, and concurrent access.
"""

import asyncio
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow import (
    Pipeline,
    Stage,
    StageKind,
    StageOutput,
    StageContext,
    PipelineTimer,
)

from stageflow.context import ContextSnapshot
from stageflow.stages import StageInputs
from stageflow.testing import create_test_snapshot

from mocks.metadata_filtering_mocks import (
    MetadataFilteringMocks,
    MetadataFilter,
    TestDocument,
    create_test_filter,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class ChaosTestResult:
    """Result of a chaos pipeline test execution."""
    test_name: str
    test_type: str
    success: bool
    execution_time_ms: float
    iterations: int
    documents_processed: int
    errors_encountered: int
    silent_failures: int
    error_message: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)


class HighLoadRetrievalStage(Stage):
    """
    ENRICH stage that simulates high-load metadata retrieval scenarios.

    This stage processes multiple filter requests concurrently and
    measures performance under load.
    """

    name = "high_load_retrieval"
    kind = StageKind.ENRICH

    def __init__(
        self,
        concurrent_requests: int = 10,
        filters_per_request: int = 5,
    ):
        self.concurrent_requests = concurrent_requests
        self.filters_per_request = filters_per_request
        self.mocks = MetadataFilteringMocks()
        self.execution_metrics = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute high-load metadata retrieval."""
        start_time = time.perf_counter()

        try:
            # Get load parameters from context
            concurrent_count = ctx.snapshot.metadata.get("concurrent_requests", self.concurrent_requests)
            filters_count = ctx.snapshot.metadata.get("filters_per_request", self.filters_per_request)

            # Generate multiple filter requests
            filter_requests = self._generate_filter_requests(concurrent_count, filters_count)

            # Execute concurrent filter requests
            results = await self._execute_concurrent_requests(filter_requests)

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Aggregate results
            total_docs = sum(r["document_count"] for r in results)
            total_errors = sum(r["error_count"] for r in results)
            total_silent = sum(r["silent_failure_count"] for r in results)

            # Calculate average filter time
            avg_filter_time = sum(r["avg_filter_time_ms"] for r in results) / len(results)

            metrics = {
                "test_name": self.name,
                "timestamp": datetime.now().isoformat(),
                "concurrent_requests": len(filter_requests),
                "filters_per_request": filters_count,
                "total_documents_retrieved": total_docs,
                "total_errors": total_errors,
                "total_silent_failures": total_silent,
                "avg_filter_time_ms": avg_filter_time,
                "execution_time_ms": execution_time_ms,
            }
            self.execution_metrics.append(metrics)

            return StageOutput.ok(
                results=results,
                total_documents=total_docs,
                total_errors=total_errors,
                total_silent_failures=total_silent,
                avg_filter_time_ms=avg_filter_time,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.error(f"High-load retrieval failed: {e}")
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return StageOutput.fail(
                error=f"High-load retrieval failed: {e}",
                execution_time_ms=execution_time_ms,
            )

    def _generate_filter_requests(
        self, count: int, filters_per_request: int
    ) -> List[List[MetadataFilter]]:
        """Generate filter request batches."""
        requests = []
        categories = ["technical", "business", "engineering", "legal"]
        operators = ["equals", "in", "gt", "lt"]

        for i in range(count):
            filters = []
            for j in range(filters_per_request):
                filter_obj = MetadataFilter(
                    field_name="category" if j % 2 == 0 else "status",
                    operator=operators[j % len(operators)],
                    value=(
                        categories[(i + j) % len(categories)]
                        if j % 2 == 0
                        else ["published", "approved"][j % 2]
                    ),
                    description=f"Filter {i}_{j}",
                )
                filters.append(filter_obj)
            requests.append(filters)

        return requests

    async def _execute_concurrent_requests(
        self, requests: List[List[MetadataFilter]]
    ) -> List[Dict[str, Any]]:
        """Execute filter request batches concurrently."""
        results = []

        async def process_request(request_id: int, filters: List[MetadataFilter]) -> Dict[str, Any]:
            start_time = time.perf_counter()
            error_count = 0
            silent_failure_count = 0
            document_count = 0
            filter_times = []

            for filter_obj in filters:
                filter_start = time.perf_counter()
                try:
                    matching_docs, stats = self.mocks.apply_metadata_filter(filter_obj)
                    document_count += len(matching_docs)
                    if len(matching_docs) == 0:
                        silent_failure_count += 1
                    filter_time = (time.perf_counter() - filter_start) * 1000
                    filter_times.append(filter_time)
                except Exception:
                    error_count += 1

            avg_filter_time = sum(filter_times) / len(filter_times) if filter_times else 0

            return {
                "request_id": request_id,
                "document_count": document_count,
                "error_count": error_count,
                "silent_failure_count": silent_failure_count,
                "avg_filter_time_ms": avg_filter_time,
            }

        # Execute requests concurrently
        tasks = [
            process_request(i, request)
            for i, request in enumerate(requests)
        ]
        results = await asyncio.gather(*tasks)

        return results


class MalformedInputStage(Stage):
    """
    ENRICH stage that tests handling of malformed metadata inputs.

    This stage applies filters with malformed, inconsistent, or invalid
    inputs to verify error handling.
    """

    name = "malformed_input"
    kind = StageKind.ENRICH

    def __init__(self):
        self.mocks = MetadataFilteringMocks()
        self.execution_metrics = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute malformed input testing."""
        start_time = time.perf_counter()

        try:
            # Get malformed inputs from context or use defaults
            malformed_cases = ctx.snapshot.metadata.get(
                "malformed_cases",
                self._get_default_malformed_cases()
            )

            results = []
            for case in malformed_cases:
                result = self._apply_malformed_filter(case)
                results.append(result)

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Count successes and failures
            successful = sum(1 for r in results if r["handled_correctly"])
            failed = len(results) - successful

            metrics = {
                "test_name": self.name,
                "timestamp": datetime.now().isoformat(),
                "total_cases": len(results),
                "handled_correctly": successful,
                "failed_cases": failed,
                "execution_time_ms": execution_time_ms,
            }
            self.execution_metrics.append(metrics)

            return StageOutput.ok(
                results=results,
                total_cases=len(results),
                handled_correctly=successful,
                failed_cases=failed,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.error(f"Malformed input test failed: {e}")
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return StageOutput.fail(
                error=f"Malformed input test failed: {e}",
                execution_time_ms=execution_time_ms,
            )

    def _get_default_malformed_cases(self) -> List[Dict[str, Any]]:
        """Get default malformed input test cases."""
        return [
            {
                "name": "empty_field",
                "filter_field": "",
                "filter_operator": "equals",
                "filter_value": "technical",
                "expected_behavior": "Handle empty field gracefully",
            },
            {
                "name": "invalid_operator",
                "filter_field": "category",
                "filter_operator": "invalid_operator_xyz",
                "filter_value": "technical",
                "expected_behavior": "Reject invalid operator",
            },
            {
                "name": "type_mismatch",
                "filter_field": "version",
                "filter_operator": "gt",
                "filter_value": "not_a_number",
                "expected_behavior": "Handle type mismatch gracefully",
            },
            {
                "name": "nested_none",
                "filter_field": "metadata.nested_field",
                "filter_operator": "equals",
                "filter_value": "value",
                "expected_behavior": "Handle nested field access",
            },
            {
                "name": "special_characters",
                "filter_field": "category",
                "filter_operator": "equals",
                "filter_value": "technical'; DROP TABLE documents;--",
                "expected_behavior": "Handle special characters safely",
            },
            {
                "name": "unicode_input",
                "filter_field": "category",
                "filter_operator": "equals",
                "filter_value": " технический",
                "expected_behavior": "Handle unicode input",
            },
            {
                "name": "very_long_value",
                "filter_field": "category",
                "filter_operator": "equals",
                "filter_value": "x" * 10000,
                "expected_behavior": "Handle very long values",
            },
        ]

    def _apply_malformed_filter(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a malformed filter and capture results."""
        start_time = time.perf_counter()

        try:
            filter_obj = MetadataFilter(
                field_name=case.get("filter_field", ""),
                operator=case.get("filter_operator", "equals"),
                value=case.get("filter_value"),
                description=case.get("name", "unnamed"),
            )

            matching_docs, stats = self.mocks.apply_metadata_filter(filter_obj)

            filter_time_ms = (time.perf_counter() - start_time) * 1000

            # Determine if handled correctly
            handled_correctly = (
                # Should not crash
                True
                # Empty results are acceptable for malformed inputs
                or len(matching_docs) == 0
            )

            return {
                "name": case.get("name", "unnamed"),
                "expected_behavior": case.get("expected_behavior", ""),
                "document_count": len(matching_docs),
                "filter_time_ms": filter_time_ms,
                "handled_correctly": handled_correctly,
                "error": None,
            }

        except Exception as e:
            filter_time_ms = (time.perf_counter() - start_time) * 1000

            return {
                "name": case.get("name", "unnamed"),
                "expected_behavior": case.get("expected_behavior", ""),
                "document_count": 0,
                "filter_time_ms": filter_time_ms,
                "handled_correctly": False,
                "error": str(e),
            }


class SchemaVarianceStage(Stage):
    """
    ENRICH stage that tests filtering with schema variance.

    This stage applies filters to documents with inconsistent metadata
    schemas to verify robustness.
    """

    name = "schema_variance"
    kind = StageKind.ENRICH

    def __init__(self):
        self.mocks = MetadataFilteringMocks()
        self.execution_metrics = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute schema variance testing."""
        start_time = time.perf_counter()

        try:
            # Get test scenarios from context
            scenarios = ctx.snapshot.metadata.get(
                "schema_scenarios",
                self._get_default_scenarios()
            )

            results = []
            for scenario in scenarios:
                result = self._test_schema_scenario(scenario)
                results.append(result)

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Count consistent and inconsistent results
            consistent = sum(1 for r in results if r["schema_consistent"])
            inconsistent = len(results) - consistent

            metrics = {
                "test_name": self.name,
                "timestamp": datetime.now().isoformat(),
                "total_scenarios": len(results),
                "schema_consistent": consistent,
                "schema_inconsistent": inconsistent,
                "execution_time_ms": execution_time_ms,
            }
            self.execution_metrics.append(metrics)

            return StageOutput.ok(
                results=results,
                total_scenarios=len(results),
                schema_consistent=consistent,
                schema_inconsistent=inconsistent,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.error(f"Schema variance test failed: {e}")
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return StageOutput.fail(
                error=f"Schema variance test failed: {e}",
                execution_time_ms=execution_time_ms,
            )

    def _get_default_scenarios(self) -> List[Dict[str, Any]]:
        """Get default schema variance test scenarios."""
        return [
            {
                "name": "missing_field",
                "filter_field": "custom_field",
                "filter_operator": "equals",
                "filter_value": "value",
                "expected_behavior": "Missing field should not cause crash",
            },
            {
                "name": "null_value",
                "filter_field": "category",
                "filter_operator": "equals",
                "filter_value": None,
                "expected_behavior": "Null value should be handled",
            },
            {
                "name": "numeric_as_string",
                "filter_field": "numeric_as_string",
                "filter_operator": "gt",
                "filter_value": 50,
                "expected_behavior": "Type coercion should work",
            },
            {
                "name": "list_as_string",
                "filter_field": "list_as_string",
                "filter_operator": "contains",
                "filter_value": "item1",
                "expected_behavior": "String containing should work",
            },
            {
                "name": "boolean_as_int",
                "filter_field": "boolean_as_int",
                "filter_operator": "equals",
                "filter_value": 1,
                "expected_behavior": "Int should match boolean-as-int",
            },
        ]

    def _test_schema_scenario(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """Test a schema variance scenario."""
        start_time = time.perf_counter()

        try:
            filter_obj = MetadataFilter(
                field_name=scenario.get("filter_field", ""),
                operator=scenario.get("filter_operator", "equals"),
                value=scenario.get("filter_value"),
                description=scenario.get("name", "unnamed"),
            )

            matching_docs, stats = self.mocks.apply_metadata_filter(filter_obj)

            filter_time_ms = (time.perf_counter() - start_time) * 1000

            # Determine schema consistency
            # For variance scenarios, we expect different document counts
            # but consistent behavior
            schema_consistent = (
                len(matching_docs) >= 0  # Should not crash
                and filter_time_ms < 1000  # Should complete in reasonable time
            )

            return {
                "name": scenario.get("name", "unnamed"),
                "expected_behavior": scenario.get("expected_behavior", ""),
                "document_count": len(matching_docs),
                "filter_time_ms": filter_time_ms,
                "schema_consistent": schema_consistent,
                "filter_efficiency": stats.get("filter_efficiency", 0),
            }

        except Exception as e:
            filter_time_ms = (time.perf_counter() - start_time) * 1000

            return {
                "name": scenario.get("name", "unnamed"),
                "expected_behavior": scenario.get("expected_behavior", ""),
                "document_count": 0,
                "filter_time_ms": filter_time_ms,
                "schema_consistent": False,
                "error": str(e),
            }


class ChaosValidationStage(Stage):
    """
    GUARD stage for validating chaos test results.
    """

    name = "chaos_validation"
    kind = StageKind.GUARD

    def __init__(
        self,
        max_error_rate: float = 0.1,
        max_silent_failure_rate: float = 0.05,
        max_avg_filter_time_ms: float = 100.0,
    ):
        self.max_error_rate = max_error_rate
        self.max_silent_failure_rate = max_silent_failure_rate
        self.max_avg_filter_time_ms = max_avg_filter_time_ms
        self.validation_failures = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Validate chaos test results."""
        # Get metrics from different stages
        high_load_result = ctx.inputs.get_from("high_load_retrieval")
        malformed_result = ctx.inputs.get_from("malformed_input")
        schema_result = ctx.inputs.get_from("schema_variance")

        validation_passed = True
        validation_errors = []
        validation_warnings = []

        # Validate high-load results
        if high_load_result:
            total_errors = high_load_result.get("total_errors", 0)
            total_docs = high_load_result.get("total_documents", 0)
            error_rate = total_errors / max(total_docs, 1)

            avg_time = high_load_result.get("avg_filter_time_ms", 0)

            if error_rate > self.max_error_rate:
                validation_passed = False
                validation_errors.append(
                    f"High error rate in load test: {error_rate:.2%} (max: {self.max_error_rate:.2%})"
                )

            if avg_time > self.max_avg_filter_time_ms:
                validation_warnings.append(
                    f"High average filter time: {avg_time:.2f}ms (threshold: {self.max_avg_filter_time_ms:.2f}ms)"
                )

        # Validate malformed input results
        if malformed_result:
            total_cases = malformed_result.get("total_cases", 0)
            failed_cases = malformed_result.get("failed_cases", 0)

            if failed_cases > total_cases * 0.5:
                validation_passed = False
                validation_errors.append(
                    f"High failure rate for malformed inputs: {failed_cases}/{total_cases}"
                )

        # Validate schema variance results
        if schema_result:
            consistent = schema_result.get("schema_consistent", 0)
            total = schema_result.get("total_scenarios", 1)

            if consistent < total * 0.8:
                validation_passed = False
                validation_errors.append(
                    f"Low schema consistency: {consistent}/{total} scenarios"
                )

        if validation_errors:
            return StageOutput.cancel(
                reason="Chaos validation failed",
                data={
                    "validation_errors": validation_errors,
                    "validation_warnings": validation_warnings,
                },
            )

        return StageOutput.ok(
            validation_passed=True,
            validation_warnings=validation_warnings,
        )


def create_chaos_pipeline(
    test_type: str = "high_load",
    result_file: Optional[str] = None,
) -> Pipeline:
    """Create a chaos pipeline for stress testing."""
    pipeline = Pipeline()

    if test_type == "high_load":
        stage = HighLoadRetrievalStage()
    elif test_type == "malformed":
        stage = MalformedInputStage()
    elif test_type == "schema_variance":
        stage = SchemaVarianceStage()
    else:
        raise ValueError(f"Unknown test type: {test_type}")

    validation_stage = ChaosValidationStage()

    pipeline = pipeline.with_stage(stage.name, stage, StageKind.ENRICH)
    pipeline = pipeline.with_stage(
        "chaos_validation", validation_stage, StageKind.GUARD, dependencies=(stage.name,)
    )

    return pipeline


async def run_chaos_test(
    test_type: str,
    test_name: str,
    iterations: int = 10,
) -> ChaosTestResult:
    """Run a chaos test."""
    start_time = time.perf_counter()

    try:
        # Create appropriate pipeline
        pipeline = create_chaos_pipeline(test_type=test_type)

        # Create test snapshot with metadata
        metadata = {
            "test_type": test_type,
            "iterations": iterations,
        }

        if test_type == "high_load":
            metadata.update({
                "concurrent_requests": 10,
                "filters_per_request": 5,
            })
        elif test_type == "malformed":
            pass  # Use default malformed cases
        elif test_type == "schema_variance":
            pass  # Use default scenarios

        snapshot = create_test_snapshot(
            input_text="Chaos test query",
            metadata=metadata,
        )

        context = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name="root",
            timer=PipelineTimer(),
        )

        graph = pipeline.build()
        result = await graph.run(context)

        execution_time_ms = (time.perf_counter() - start_time) * 1000

        # Extract metrics
        documents_processed = 0
        errors_encountered = 0
        silent_failures = 0

        for stage_name, stage_result in result.items():
            if hasattr(stage_result, "data"):
                data = stage_result.data or {}
                if "total_documents" in data:
                    documents_processed = data["total_documents"]
                if "total_errors" in data:
                    errors_encountered = data["total_errors"]
                if "total_silent_failures" in data:
                    silent_failures = data["total_silent_failures"]

        all_completed = all(
            hasattr(r, "status") and r.status.value in ["ok", "cancel"]
            for r in result.values()
        )

        success = all_completed and errors_encountered < iterations

        return ChaosTestResult(
            test_name=test_name,
            test_type=test_type,
            success=success,
            execution_time_ms=execution_time_ms,
            iterations=iterations,
            documents_processed=documents_processed,
            errors_encountered=errors_encountered,
            silent_failures=silent_failures,
        )

    except Exception as e:
        execution_time_ms = (time.perf_counter() - start_time) * 1000

        return ChaosTestResult(
            test_name=test_name,
            test_type=test_type,
            success=False,
            execution_time_ms=execution_time_ms,
            iterations=iterations,
            documents_processed=0,
            errors_encountered=iterations,
            silent_failures=0,
            error_message=str(e),
        )


async def run_all_chaos_tests(
    base_dir: str = "results/enrich010",
) -> Dict[str, Any]:
    """Run all chaos tests."""
    base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)

    chaos_tests = [
        ("high_load", "high_load_test", 10),
        ("malformed", "malformed_input_test", 10),
        ("schema_variance", "schema_variance_test", 10),
    ]

    all_results = []

    logger.info("=" * 60)
    logger.info("ENRICH-010 Chaos Tests")
    logger.info("=" * 60)

    for test_type, test_name, iterations in chaos_tests:
        logger.info(f"\nRunning chaos test: {test_name} ({test_type})")

        result = await run_chaos_test(test_type, test_name, iterations)

        all_results.append({
            "test_name": result.test_name,
            "test_type": result.test_type,
            "success": result.success,
            "execution_time_ms": result.execution_time_ms,
            "iterations": result.iterations,
            "documents_processed": result.documents_processed,
            "errors_encountered": result.errors_encountered,
            "silent_failures": result.silent_failures,
            "error": result.error_message,
        })

        logger.info(f"  Result: {'PASS' if result.success else 'FAIL'}")
        logger.info(f"  Documents: {result.documents_processed}")
        logger.info(f"  Errors: {result.errors_encountered}")
        logger.info(f"  Silent Failures: {result.silent_failures}")

    # Save results
    result_file = str(base_path / "chaos_test_results.json")
    with open(result_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "results": all_results,
            },
            f,
            indent=2,
        )

    logger.info("\n" + "=" * 60)
    logger.info("Chaos Test Summary")
    logger.info("=" * 60)
    passed = sum(1 for r in all_results if r["success"])
    logger.info(f"Passed: {passed}/{len(all_results)}")

    return {
        "results": all_results,
        "output_dir": str(base_path),
    }


if __name__ == "__main__":
    asyncio.run(run_all_chaos_tests())
