"""
ENRICH-010 Test Pipelines: Metadata Filtering Accuracy

This module implements comprehensive test pipelines for stress-testing
Stageflow's ENRICH stage handling of metadata filtering in RAG/Knowledge
retrieval pipelines.

Pipeline Categories:
1. Baseline Pipeline - Normal filtering operation verification
2. Operator Test Pipeline - Different filter operators (equals, in, contains, etc.)
3. Silent Failure Pipeline - Detection of silent failures (empty results)
4. Edge Case Pipeline - Boundary conditions and unusual metadata
5. Scale Pipeline - Performance under load
6. Schema Variance Pipeline - Handling inconsistent metadata schemas
"""

import asyncio
import json
import logging
import sys
import time
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

from stageflow.context import ContextSnapshot, DocumentEnrichment
from stageflow.stages import StageInputs
from stageflow.testing import create_test_snapshot

from mocks.metadata_filtering_mocks import (
    MetadataFilteringMocks,
    MetadataFilter,
    TestDocument,
    SilentFailureDetector,
    create_test_filter,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


test_results = {
    "total_tests": 0,
    "passed": 0,
    "failed": 0,
    "silent_failures": 0,
    "findings": [],
}


@dataclass
class FilteringTestCase:
    """Definition of a metadata filtering test case."""
    name: str
    description: str
    filter_field: str
    filter_operator: str
    filter_value: Any
    expected_min_results: int
    expected_behavior: str
    test_category: str = "baseline"


@dataclass
class FilteringPipelineResult:
    """Result of a filtering pipeline test execution."""
    test_name: str
    success: bool
    execution_time_ms: float
    documents_filtered: int
    filter_operator: str
    silent_failure: bool
    error_message: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)


class MetadataRetrievalStage(Stage):
    """
    ENRICH stage for retrieving documents with metadata filtering.

    This stage simulates a RAG retrieval stage that filters documents
    based on metadata criteria before returning results.
    """

    name = "metadata_retrieval"
    kind = StageKind.ENRICH

    def __init__(
        self,
        filter_field: str = "category",
        filter_operator: str = "equals",
        filter_value: Any = None,
        enable_silent_failure_detection: bool = True,
    ):
        self.filter_field = filter_field
        self.filter_operator = filter_operator
        self.filter_value = filter_value
        self.enable_silent_failure_detection = enable_silent_failure_detection
        self.mocks = MetadataFilteringMocks()
        self.silent_failure_detector = SilentFailureDetector(self.mocks)
        self.execution_metrics = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute metadata-filtered document retrieval."""
        start_time = time.perf_counter()

        try:
            # Get filter parameters from context or use defaults
            filter_field = ctx.snapshot.metadata.get("filter_field", self.filter_field)
            filter_operator = ctx.snapshot.metadata.get("filter_operator", self.filter_operator)
            filter_value = ctx.snapshot.metadata.get("filter_value", self.filter_value)

            # Handle list values from context
            if isinstance(filter_value, str) and filter_value.startswith("["):
                import ast
                filter_value = ast.literal_eval(filter_value)

            # Create filter
            filter_obj = MetadataFilter(
                field_name=filter_field,
                operator=filter_operator,
                value=filter_value,
                description=f"Test filter: {filter_field} {filter_operator} {filter_value}",
            )

            # Apply filter
            matching_docs, stats = self.mocks.apply_metadata_filter(filter_obj)

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Check for silent failure
            silent_failure = False
            if self.enable_silent_failure_detection and len(matching_docs) == 0:
                silent_failure = True
                logger.warning(f"SILENT FAILURE: Filter returned zero results: {filter_obj.to_dict()}")

            # Convert documents to output format
            documents = [d.to_vector_db_format() for d in matching_docs]

            metrics = {
                "test_name": self.name,
                "timestamp": datetime.now().isoformat(),
                "documents_retrieved": len(documents),
                "total_documents": stats["total_documents"],
                "filter_efficiency": stats["filter_efficiency"],
                "filter_time_ms": stats["filter_time_ms"],
                "filter_field": filter_field,
                "filter_operator": filter_operator,
                "filter_value": str(filter_value),
                "silent_failure": silent_failure,
            }
            self.execution_metrics.append(metrics)

            return StageOutput.ok(
                documents=documents,
                document_count=len(documents),
                filter_stats=stats,
                filter_config={
                    "field": filter_field,
                    "operator": filter_operator,
                    "value": filter_value,
                },
                silent_failure=silent_failure,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.error(f"Metadata retrieval failed: {e}")
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return StageOutput.fail(
                error=f"Metadata retrieval failed: {e}",
                execution_time_ms=execution_time_ms,
            )


class ComplexFilteringStage(Stage):
    """
    ENRICH stage for applying complex multi-condition filters.

    This stage supports combining multiple filters with logical operators.
    """

    name = "complex_filtering"
    kind = StageKind.ENRICH

    def __init__(
        self,
        filters: Optional[List[Dict[str, Any]]] = None,
        logical_operator: str = "and",
        enable_silent_failure_detection: bool = True,
    ):
        self.filters = filters or []
        self.logical_operator = logical_operator
        self.enable_silent_failure_detection = enable_silent_failure_detection
        self.mocks = MetadataFilteringMocks()
        self.execution_metrics = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute complex metadata filtering."""
        start_time = time.perf_counter()

        try:
            # Get filters from context or use defaults
            filter_configs = ctx.snapshot.metadata.get("filters", self.filters)

            # Parse filter configurations
            filter_objects = []
            for f in filter_configs:
                filter_obj = MetadataFilter(
                    field_name=f.get("field", "category"),
                    operator=f.get("operator", "equals"),
                    value=f.get("value"),
                    description=f.get("description", ""),
                )
                filter_objects.append(filter_obj)

            # Apply complex filter
            matching_docs, stats = self.mocks.apply_complex_filter(
                filter_objects, self.logical_operator
            )

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Check for silent failure
            silent_failure = False
            if self.enable_silent_failure_detection and len(matching_docs) == 0:
                silent_failure = True
                logger.warning(f"SILENT FAILURE: Complex filter returned zero results")

            documents = [d.to_vector_db_format() for d in matching_docs]

            metrics = {
                "test_name": self.name,
                "timestamp": datetime.now().isoformat(),
                "documents_retrieved": len(documents),
                "total_documents": stats["total_documents"],
                "filter_count": len(filter_objects),
                "logical_operator": self.logical_operator,
                "filter_time_ms": stats["filter_time_ms"],
                "silent_failure": silent_failure,
            }
            self.execution_metrics.append(metrics)

            return StageOutput.ok(
                documents=documents,
                document_count=len(documents),
                filter_stats=stats,
                filter_config={
                    "filters": [f.to_dict() for f in filter_objects],
                    "logical_operator": self.logical_operator,
                },
                silent_failure=silent_failure,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.error(f"Complex filtering failed: {e}")
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return StageOutput.fail(
                error=f"Complex filtering failed: {e}",
                execution_time_ms=execution_time_ms,
            )


class ValidationStage(Stage):
    """
    GUARD stage for validating filtering results and detecting failures.

    This stage validates filter accuracy, detects silent failures,
    and ensures results meet expected criteria.
    """

    name = "filter_validation"
    kind = StageKind.GUARD

    def __init__(
        self,
        expected_min_results: int = 1,
        validate_results: bool = True,
        detect_silent_failures: bool = True,
    ):
        self.expected_min_results = expected_min_results
        self.validate_results = validate_results
        self.detect_silent_failures = detect_silent_failures
        self.validation_failures = []
        self.validation_warnings = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Validate filtering results."""
        # Get results from metadata_retrieval (baseline pipeline)
        document_count = ctx.inputs.get_from("metadata_retrieval", "document_count", default=0)
        silent_failure = ctx.inputs.get_from("metadata_retrieval", "silent_failure", default=False)
        filter_config = ctx.inputs.get_from("metadata_retrieval", "filter_config", default={})

        # Check if complex_filtering has results (only if it's a declared dependency)
        # This is handled by the pipeline builder, not by runtime checks

        validation_passed = True
        validation_errors = []
        validation_warnings = []

        # Check minimum results
        if document_count < self.expected_min_results:
            if silent_failure and self.detect_silent_failures:
                validation_warnings.append(
                    f"Silent failure detected: zero results returned without error"
                )
            else:
                validation_passed = False
                validation_errors.append(
                    f"Insufficient results: expected >= {self.expected_min_results}, got {document_count}"
                )
                self.validation_failures.append({
                    "type": "insufficient_results",
                    "expected": self.expected_min_results,
                    "actual": document_count,
                })

        # Check for unexpected empty results
        if document_count == 0 and not silent_failure:
            validation_warnings.append(
                "Empty result set returned without explicit silent failure flag"
            )

        # Validate filter configuration
        if self.validate_results and filter_config:
            if "field" in filter_config and not filter_config["field"]:
                validation_warnings.append("Empty filter field configuration")

        if validation_errors:
            return StageOutput.cancel(
                reason="Validation failed",
                data={
                    "validation_errors": validation_errors,
                    "validation_warnings": validation_warnings,
                    "document_count": document_count,
                    "silent_failure": silent_failure,
                    "filter_config": filter_config,
                },
            )

        return StageOutput.ok(
            validation_passed=True,
            document_count=document_count,
            silent_failure=silent_failure,
            validation_warnings=validation_warnings,
        )


class MetricsCollectionStage(Stage):
    """
    WORK stage for collecting and logging test metrics.
    """

    name = "metrics_collection"
    kind = StageKind.WORK

    def __init__(self, test_name: str, result_file: Optional[str] = None):
        self.test_name = test_name
        self.result_file = result_file
        self.metrics = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Collect and log test metrics."""
        # Get metrics from metadata_retrieval (baseline pipeline)
        document_count = ctx.inputs.get_from("metadata_retrieval", "document_count", default=0)
        filter_stats = ctx.inputs.get_from("metadata_retrieval", "filter_stats", default={})
        silent_failure = ctx.inputs.get_from("metadata_retrieval", "silent_failure", default=False)

        # Check if complex_filtering has results (only if it's a declared dependency)
        # This is handled by the pipeline builder, not by runtime checks

        metrics = {
            "test_name": self.test_name,
            "timestamp": datetime.now().isoformat(),
            "documents_retrieved": document_count,
            "filter_time_ms": filter_stats.get("filter_time_ms", 0),
            "filter_efficiency": filter_stats.get("filter_efficiency", 0),
            "silent_failure": silent_failure,
        }

        self.metrics.append(metrics)

        if self.result_file:
            Path(self.result_file).parent.mkdir(parents=True, exist_ok=True)
            with open(self.result_file, "a") as f:
                f.write(json.dumps(metrics) + "\n")

        logger.info(f"Test metrics for {self.test_name}: {json.dumps(metrics, indent=2)}")

        return StageOutput.ok(
            metrics_collected=True,
            test_metrics=metrics,
        )


def create_baseline_pipeline(
    filter_field: str = "category",
    filter_operator: str = "equals",
    filter_value: Any = "technical",
    expected_min_results: int = 1,
    test_name: str = "baseline",
    result_file: Optional[str] = None,
) -> Pipeline:
    """Create a baseline filtering pipeline."""
    pipeline = Pipeline()

    retrieval_stage = MetadataRetrievalStage(
        filter_field=filter_field,
        filter_operator=filter_operator,
        filter_value=filter_value,
    )

    validation_stage = ValidationStage(
        expected_min_results=expected_min_results,
        validate_results=True,
        detect_silent_failures=True,
    )

    metrics_stage = MetricsCollectionStage(
        test_name=test_name,
        result_file=result_file,
    )

    pipeline = pipeline.with_stage("metadata_retrieval", retrieval_stage, StageKind.ENRICH)
    pipeline = pipeline.with_stage(
        "filter_validation", validation_stage, StageKind.GUARD, dependencies=("metadata_retrieval",)
    )
    pipeline = pipeline.with_stage(
        "metrics_collection", metrics_stage, StageKind.WORK,
        dependencies=("metadata_retrieval", "filter_validation")
    )

    return pipeline


def create_complex_filter_pipeline(
    filters: List[Dict[str, Any]],
    logical_operator: str = "and",
    expected_min_results: int = 1,
    test_name: str = "complex_filter",
    result_file: Optional[str] = None,
) -> Pipeline:
    """Create a complex multi-condition filtering pipeline."""
    pipeline = Pipeline()

    filtering_stage = ComplexFilteringStage(
        filters=filters,
        logical_operator=logical_operator,
    )

    validation_stage = ValidationStage(
        expected_min_results=expected_min_results,
        validate_results=True,
        detect_silent_failures=True,
    )

    metrics_stage = MetricsCollectionStage(
        test_name=test_name,
        result_file=result_file,
    )

    pipeline = pipeline.with_stage("complex_filtering", filtering_stage, StageKind.ENRICH)
    pipeline = pipeline.with_stage(
        "filter_validation", validation_stage, StageKind.GUARD, dependencies=("complex_filtering",)
    )
    pipeline = pipeline.with_stage(
        "metrics_collection", metrics_stage, StageKind.WORK,
        dependencies=("complex_filtering", "filter_validation")
    )

    return pipeline


async def run_filtering_test(
    pipeline: Pipeline,
    test_case: FilteringTestCase,
    input_text: str = "",
) -> FilteringPipelineResult:
    """Execute a single filtering pipeline test."""
    test_results["total_tests"] += 1

    start_time = time.perf_counter()

    try:
        snapshot = create_test_snapshot(
            input_text=input_text or _get_default_test_query(),
            metadata={
                "filter_field": test_case.filter_field,
                "filter_operator": test_case.filter_operator,
                "filter_value": test_case.filter_value,
            }
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

        # Extract results
        document_count = 0
        silent_failure = False
        filter_operator = test_case.filter_operator

        for stage_name, stage_result in result.items():
            if hasattr(stage_result, "data"):
                data = stage_result.data or {}
                if "document_count" in data:
                    document_count = data["document_count"]
                if "silent_failure" in data:
                    silent_failure = data["silent_failure"]
                if "filter_config" in data:
                    fc = data["filter_config"]
                    filter_operator = fc.get("operator", filter_operator)

        all_completed = all(
            hasattr(r, "status") and r.status.value in ["ok", "cancel"]
            for r in result.values()
        )

        validation_cancelled = False
        for stage_name, stage_result in result.items():
            if stage_name == "filter_validation":
                if hasattr(stage_result, "status") and stage_result.status.value == "cancel":
                    validation_cancelled = True
                    break

        success = (
            document_count >= test_case.expected_min_results
            and all_completed
            and not validation_cancelled
        )

        if silent_failure:
            test_results["silent_failures"] += 1

        if success:
            test_results["passed"] += 1
        else:
            test_results["failed"] += 1

        return FilteringPipelineResult(
            test_name=test_case.name,
            success=success,
            execution_time_ms=execution_time_ms,
            documents_filtered=document_count,
            filter_operator=filter_operator,
            silent_failure=silent_failure,
            error_message=None,
            metrics={
                "validation_passed": all_completed and not validation_cancelled,
                "expected_min_results": test_case.expected_min_results,
            },
        )

    except Exception as e:
        execution_time_ms = (time.perf_counter() - start_time) * 1000
        test_results["failed"] += 1

        return FilteringPipelineResult(
            test_name=test_case.name,
            success=False,
            execution_time_ms=execution_time_ms,
            documents_filtered=0,
            filter_operator=test_case.filter_operator,
            silent_failure=False,
            error_message=str(e),
        )


def _get_default_test_query() -> str:
    """Generate default test query."""
    return "What are the technical requirements for the system?"


def create_operator_test_cases() -> List[FilteringTestCase]:
    """Create test cases for all filter operators."""
    return [
        FilteringTestCase(
            name="equals_category",
            description="Filter by category equals",
            filter_field="category",
            filter_operator="equals",
            filter_value="technical",
            expected_min_results=10,
            expected_behavior="Documents with category=technical are returned",
            test_category="operator",
        ),
        FilteringTestCase(
            name="equals_status",
            description="Filter by status equals",
            filter_field="status",
            filter_operator="equals",
            filter_value="published",
            expected_min_results=10,
            expected_behavior="Documents with status=published are returned",
            test_category="operator",
        ),
        FilteringTestCase(
            name="in_categories",
            description="Filter by category in list",
            filter_field="category",
            filter_operator="in",
            filter_value=["technical", "engineering"],
            expected_min_results=20,
            expected_behavior="Documents matching any category in list are returned",
            test_category="operator",
        ),
        FilteringTestCase(
            name="in_statuses",
            description="Filter by status in list",
            filter_field="status",
            filter_operator="in",
            filter_value=["approved", "published"],
            expected_min_results=20,
            expected_behavior="Documents matching any status in list are returned",
            test_category="operator",
        ),
        FilteringTestCase(
            name="contains_title",
            description="Filter by title contains substring",
            filter_field="title",
            filter_operator="contains",
            filter_value="Technical",
            expected_min_results=5,
            expected_behavior="Documents with title containing substring are returned",
            test_category="operator",
        ),
        FilteringTestCase(
            name="gt_version",
            description="Filter by version greater than",
            filter_field="version",
            filter_operator="gt",
            filter_value=3,
            expected_min_results=20,
            expected_behavior="Documents with version > 3 are returned",
            test_category="operator",
        ),
        FilteringTestCase(
            name="lt_version",
            description="Filter by version less than",
            filter_field="version",
            filter_operator="lt",
            filter_value=3,
            expected_min_results=20,
            expected_behavior="Documents with version < 3 are returned",
            test_category="operator",
        ),
        FilteringTestCase(
            name="gte_confidence",
            description="Filter by confidence score greater than or equal",
            filter_field="confidence_score",
            filter_operator="gte",
            filter_value=0.85,
            expected_min_results=30,
            expected_behavior="Documents with confidence >= 0.85 are returned",
            test_category="operator",
        ),
        FilteringTestCase(
            name="range_version",
            description="Filter by version in range",
            filter_field="version",
            filter_operator="range",
            filter_value=(2, 4),
            expected_min_results=30,
            expected_behavior="Documents with version between 2 and 4 are returned",
            test_category="operator",
        ),
    ]


def create_edge_case_test_cases() -> List[FilteringTestCase]:
    """Create test cases for edge cases."""
    return [
        FilteringTestCase(
            name="empty_filter_value",
            description="Filter with empty value",
            filter_field="category",
            filter_operator="equals",
            filter_value="",
            expected_min_results=0,
            expected_behavior="No documents match empty filter value",
            test_category="edge_case",
        ),
        FilteringTestCase(
            name="non_existent_category",
            description="Filter by non-existent category",
            filter_field="category",
            filter_operator="equals",
            filter_value="nonexistent_category_xyz",
            expected_min_results=0,
            expected_behavior="No documents match non-existent category",
            test_category="edge_case",
        ),
        FilteringTestCase(
            name="empty_in_list",
            description="Filter with empty in list",
            filter_field="category",
            filter_operator="in",
            filter_value=[],
            expected_min_results=0,
            expected_behavior="No documents match empty in list",
            test_category="edge_case",
        ),
        FilteringTestCase(
            name="invalid_operator",
            description="Filter with invalid operator",
            filter_field="category",
            filter_operator="invalid_operator",
            filter_value="technical",
            expected_min_results=0,
            expected_behavior="Invalid operator should be handled gracefully",
            test_category="edge_case",
        ),
        FilteringTestCase(
            name="multiple_categories_in",
            description="Filter with multiple categories in list",
            filter_field="category",
            filter_operator="in",
            filter_value=["technical", "business", "legal", "medical", "financial"],
            expected_min_results=50,
            expected_behavior="Documents matching any category are returned",
            test_category="edge_case",
        ),
    ]


def create_silent_failure_test_cases() -> List[FilteringTestCase]:
    """Create test cases specifically designed to detect silent failures."""
    return [
        FilteringTestCase(
            name="silent_failure_empty_results",
            description="Filter that returns empty results (should be detected)",
            filter_field="category",
            filter_operator="equals",
            filter_value="totally_fake_category_xyz123",
            expected_min_results=0,
            expected_behavior="Empty results should be detected as silent failure",
            test_category="silent_failure",
        ),
        FilteringTestCase(
            name="silent_failure_malformed_filter",
            description="Malformed filter configuration",
            filter_field="",
            filter_operator="equals",
            filter_value="technical",
            expected_min_results=0,
            expected_behavior="Malformed filter should be handled gracefully",
            test_category="silent_failure",
        ),
    ]


async def run_baseline_tests(
    result_file: str = "results/enrich010_baseline_results.json",
) -> Dict[str, Any]:
    """Run baseline filter operator tests."""
    results_dir = Path(result_file).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    test_cases = create_operator_test_cases()

    all_results = []

    logger.info("=" * 60)
    logger.info("ENRICH-010 Metadata Filtering Baseline Tests")
    logger.info("=" * 60)

    for test_case in test_cases:
        logger.info(f"\nRunning test: {test_case.name}")
        logger.info(f"  Description: {test_case.description}")
        logger.info(f"  Filter: {test_case.filter_field} {test_case.filter_operator} {test_case.filter_value}")

        pipeline = create_baseline_pipeline(
            filter_field=test_case.filter_field,
            filter_operator=test_case.filter_operator,
            filter_value=test_case.filter_value,
            expected_min_results=test_case.expected_min_results,
            test_name=test_case.name,
            result_file=result_file,
        )

        result = await run_filtering_test(pipeline, test_case)

        all_results.append({
            "test_name": result.test_name,
            "success": result.success,
            "execution_time_ms": result.execution_time_ms,
            "documents_filtered": result.documents_filtered,
            "filter_operator": result.filter_operator,
            "silent_failure": result.silent_failure,
            "error": result.error_message,
            "metrics": result.metrics,
        })

        logger.info(f"  Result: {'PASS' if result.success else 'FAIL'}")
        logger.info(f"  Documents: {result.documents_filtered}")
        logger.info(f"  Silent Failure: {result.silent_failure}")
        if result.error_message:
            logger.info(f"  Error: {result.error_message}")

    with open(result_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "summary": {
                    "total_tests": test_results["total_tests"],
                    "passed": test_results["passed"],
                    "failed": test_results["failed"],
                    "silent_failures": test_results["silent_failures"],
                },
                "results": all_results,
            },
            f,
            indent=2,
        )

    logger.info("\n" + "=" * 60)
    logger.info("Baseline Test Summary")
    logger.info("=" * 60)
    logger.info(f"Total Tests: {test_results['total_tests']}")
    logger.info(f"Passed: {test_results['passed']}")
    logger.info(f"Failed: {test_results['failed']}")
    logger.info(f"Silent Failures: {test_results['silent_failures']}")
    logger.info(f"Results saved to: {result_file}")

    return {
        "summary": test_results,
        "results": all_results,
    }


async def run_edge_case_tests(
    result_file: str = "results/enrich010_edge_cases.json",
) -> Dict[str, Any]:
    """Run edge case tests for metadata filtering."""
    results_dir = Path(result_file).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    test_cases = create_edge_case_test_cases()

    all_results = []

    logger.info("=" * 60)
    logger.info("ENRICH-010 Edge Case Tests")
    logger.info("=" * 60)

    for test_case in test_cases:
        logger.info(f"\nRunning test: {test_case.name}")
        logger.info(f"  Description: {test_case.description}")

        pipeline = create_baseline_pipeline(
            filter_field=test_case.filter_field,
            filter_operator=test_case.filter_operator,
            filter_value=test_case.filter_value,
            expected_min_results=test_case.expected_min_results,
            test_name=test_case.name,
            result_file=result_file,
        )

        result = await run_filtering_test(pipeline, test_case)

        all_results.append({
            "test_name": result.test_name,
            "success": result.success,
            "execution_time_ms": result.execution_time_ms,
            "documents_filtered": result.documents_filtered,
            "silent_failure": result.silent_failure,
            "error": result.error_message,
        })

        logger.info(f"  Result: {'PASS' if result.success else 'FAIL'}")
        logger.info(f"  Documents: {result.documents_filtered}")

    with open(result_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "results": all_results,
            },
            f,
            indent=2,
        )

    return {"results": all_results}


async def run_complex_filter_tests(
    result_file: str = "results/enrich010_complex_filters.json",
) -> Dict[str, Any]:
    """Run complex multi-condition filter tests."""
    results_dir = Path(result_file).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    complex_tests = [
        {
            "name": "and_filter_technical_published",
            "filters": [
                {"field": "category", "operator": "in", "value": ["technical", "engineering"]},
                {"field": "status", "operator": "equals", "value": "published"},
            ],
            "logical_operator": "and",
            "expected_min": 5,
        },
        {
            "name": "or_filter_multiple_statuses",
            "filters": [
                {"field": "status", "operator": "equals", "value": "published"},
                {"field": "status", "operator": "equals", "value": "approved"},
            ],
            "logical_operator": "or",
            "expected_min": 10,
        },
        {
            "name": "and_filter_high_priority",
            "filters": [
                {"field": "priority", "operator": "in", "value": ["high", "critical"]},
                {"field": "confidence_score", "operator": "gte", "value": 0.85},
            ],
            "logical_operator": "and",
            "expected_min": 5,
        },
    ]

    all_results = []

    logger.info("=" * 60)
    logger.info("ENRICH-010 Complex Filter Tests")
    logger.info("=" * 60)

    for test in complex_tests:
        logger.info(f"\nRunning test: {test['name']}")
        logger.info(f"  Filters: {test['filters']}")
        logger.info(f"  Operator: {test['logical_operator']}")

        pipeline = create_complex_filter_pipeline(
            filters=test["filters"],
            logical_operator=test["logical_operator"],
            expected_min_results=test["expected_min"],
            test_name=test["name"],
            result_file=result_file,
        )

        test_case = FilteringTestCase(
            name=test["name"],
            description=f"Complex filter with {test['logical_operator']}",
            filter_field="",
            filter_operator="complex",
            filter_value=str(test["filters"]),
            expected_min_results=test["expected_min"],
            expected_behavior=f"Complex filter should return expected results",
        )

        result = await run_filtering_test(pipeline, test_case)

        all_results.append({
            "test_name": result.test_name,
            "success": result.success,
            "execution_time_ms": result.execution_time_ms,
            "documents_filtered": result.documents_filtered,
            "silent_failure": result.silent_failure,
            "error": result.error_message,
        })

        logger.info(f"  Result: {'PASS' if result.success else 'FAIL'}")
        logger.info(f"  Documents: {result.documents_filtered}")

    with open(result_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "results": all_results,
            },
            f,
            indent=2,
        )

    return {"results": all_results}


async def run_all_enrich010_tests(
    base_dir: str = "results",
) -> Dict[str, Any]:
    """Run all ENRICH-010 metadata filtering tests."""
    base_path = Path(base_dir) / "enrich010"
    base_path.mkdir(parents=True, exist_ok=True)

    (base_path / "logs").mkdir(exist_ok=True)

    baseline_results = await run_baseline_tests(
        result_file=str(base_path / "baseline_results.json"),
    )

    edge_case_results = await run_edge_case_tests(
        result_file=str(base_path / "edge_case_results.json"),
    )

    complex_filter_results = await run_complex_filter_tests(
        result_file=str(base_path / "complex_filter_results.json"),
    )

    return {
        "baseline": baseline_results,
        "edge_cases": edge_case_results,
        "complex_filters": complex_filter_results,
        "output_dir": str(base_path),
    }


if __name__ == "__main__":
    asyncio.run(run_all_enrich010_tests())
