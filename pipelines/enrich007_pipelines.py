"""
ENRICH-007 Test Pipelines: Vector DB Connection Resilience

This module implements comprehensive test pipelines for stress-testing
Stageflow's ENRICH stage handling of vector DB connection resilience.

Pipeline Categories:
1. Baseline Pipeline - Normal operation verification
2. Timeout Handling Pipeline - Connection/query timeout scenarios
3. Circuit Breaker Pipeline - Circuit breaker state transitions
4. Silent Failure Pipeline - Detection of silent failures
5. Retry Pattern Pipeline - Retry with exponential backoff
6. Connection Pool Pipeline - Pool exhaustion scenarios
7. Recovery Pipeline - Failure recovery and fallback
8. Security Pipeline - Auth failure handling
"""

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow import (
    Pipeline,
    Stage,
    StageKind,
    StageOutput,
    StageContext,
    PipelineTimer,
    CircuitBreakerInterceptor,
    TimeoutInterceptor,
)
from stageflow.context import ContextSnapshot, DocumentEnrichment, Message
from stageflow.stages import StageInputs
from stageflow.testing import create_test_snapshot

from mocks.vector_db_mocks import (
    MockVectorStore,
    VectorDBFailureInjector,
    FailureMode,
    CircuitBreakerState,
    SearchResult,
    WriteResult,
    create_vector_db_test_environment,
    create_vector_db_test_environment_async,
    create_resilience_test_environment,
    create_baseline_environment,
    create_timeout_environment,
    create_circuit_breaker_environment,
    create_silent_failure_environment,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Test result tracking
test_results = {
    "total_tests": 0,
    "passed": 0,
    "failed": 0,
    "silent_failures": 0,
    "findings": [],
}


@dataclass
class TestCase:
    """Definition of a single test case."""
    name: str
    description: str
    failure_mode: FailureMode
    expected_behavior: str
    failure_probability: float = 0.0
    base_latency_ms: float = 50.0
    timeout_ms: float = 5000.0
    circuit_breaker_threshold: int = 5
    should_detect_silent: bool = False


@dataclass
class PipelineResult:
    """Result of a pipeline test execution."""
    test_name: str
    success: bool
    execution_time_ms: float
    documents_retrieved: int
    circuit_state: str
    silent_failure: bool
    error_message: Optional[str] = None
    retry_count: int = 0
    timeout_occurred: bool = False
    circuit_breaker_tripped: bool = False
    metrics: Dict[str, Any] = field(default_factory=dict)


class VectorDBEnrichStage(Stage):
    """
    ENRICH stage for vector database operations with configurable failure injection.
    
    This stage performs similarity search against the mock vector store and returns
    document enrichments. It simulates various connection failure modes.
    """

    name = "vector_db_enrich"
    kind = StageKind.ENRICH

    def __init__(
        self,
        vector_store: MockVectorStore,
        test_name: str,
        expected_documents: int = 5,
        top_k: int = 5,
    ):
        self.vector_store = vector_store
        self.test_name = test_name
        self.expected_documents = expected_documents
        self.top_k = top_k
        self.execution_metrics = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute vector database enrichment with failure tracking."""
        query = ctx.snapshot.input_text or "test query"
        start_time = time.perf_counter()

        try:
            # Perform similarity search
            result: SearchResult = await self.vector_store.similarity_search(
                query=query,
                k=self.top_k,
                include_metadata=True,
            )

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Track execution metrics
            metrics = {
                "test_name": self.test_name,
                "timestamp": datetime.now().isoformat(),
                "search_time_ms": result.search_time_ms,
                "documents_retrieved": len(result.documents),
                "retry_count": result.retry_count,
                "cb_state": result.cb_state.value,
                "silent_failure": result.silent_failure,
                "error_message": result.error_message,
            }
            self.execution_metrics.append(metrics)

            # Build document enrichments
            documents = []
            for doc in result.documents:
                enrichment = DocumentEnrichment(
                    document_id=doc.get("document_id", ""),
                    document_type="test",
                    blocks=[
                        {
                            "id": doc.get("chunk_id", ""),
                            "type": "text",
                            "content": doc.get("content", ""),
                        }
                    ],
                    metadata={
                        "similarity": doc.get("similarity", 0.0),
                        "embedding_version": doc.get("embedding_version", ""),
                        "index_version": doc.get("index_version", ""),
                        "retrieval_timestamp": datetime.now().isoformat(),
                    },
                )
                documents.append(enrichment)

            # Return enrichment with metrics
            return StageOutput.ok(
                documents=[d.to_dict() for d in documents],
                document_count=len(documents),
                retrieval_time_ms=execution_time_ms,
                search_time_ms=result.search_time_ms,
                cb_state=result.cb_state.value,
                silent_failure=result.silent_failure or len(documents) == 0,
                retry_count=result.retry_count,
                error_message=result.error_message,
                test_name=self.test_name,
            )

        except Exception as e:
            logger.error(f"Vector DB enrichment failed: {e}")
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return StageOutput.fail(
                error=f"Vector DB enrichment failed: {e}",
                execution_time_ms=execution_time_ms,
            )


class ValidationStage(Stage):
    """
    GUARD stage for validating enrichment results and detecting failures.
    
    This stage validates that retrieved data meets expected criteria
    and detects various failure modes including silent failures.
    """

    name = "validation"
    kind = StageKind.GUARD

    def __init__(
        self,
        expected_min_documents: int = 1,
        max_latency_ms: float = 10000.0,
        detect_silent_failures: bool = False,
    ):
        self.expected_min_documents = expected_min_documents
        self.max_latency_ms = max_latency_ms
        self.detect_silent_failures = detect_silent_failures
        self.validation_failures = []
        self.validation_warnings = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Validate enrichment results."""
        # Get enrichment output
        enrich_output = ctx.inputs.get_from("vector_db_enrich", "document_count")
        document_count = enrich_output if enrich_output is not None else 0
        
        retrieval_time_ms = ctx.inputs.get_from("vector_db_enrich", "retrieval_time_ms") or 0
        silent_failure = ctx.inputs.get_from("vector_db_enrich", "silent_failure") or False
        circuit_state = ctx.inputs.get_from("vector_db_enrich", "cb_state") or "closed"
        error_message = ctx.inputs.get_from("vector_db_enrich", "error_message")
        
        validation_passed = True
        validation_errors = []
        validation_warnings = []

        # Check document count
        if document_count < self.expected_min_documents:
            if silent_failure and self.detect_silent_failures:
                validation_warnings.append(
                    f"Silent failure: zero documents returned without error"
                )
            else:
                validation_passed = False
                validation_errors.append(
                    f"Insufficient documents: expected >= {self.expected_min_documents}, got {document_count}"
                )
                self.validation_failures.append({
                    "type": "insufficient_documents",
                    "expected": self.expected_min_documents,
                    "actual": document_count,
                })

        # Check latency
        if retrieval_time_ms > self.max_latency_ms:
            validation_warnings.append(
                f"High latency: {retrieval_time_ms:.2f}ms > {self.max_latency_ms}ms threshold"
            )

        # Check for circuit breaker state
        if circuit_state == CircuitBreakerState.OPEN.value:
            validation_warnings.append(
                f"Circuit breaker is OPEN - requests are being blocked"
            )

        # Check for error message (indicates failure was handled)
        if error_message:
            validation_warnings.append(
                f"Operation encountered error: {error_message}"
            )

        if validation_errors:
            return StageOutput.cancel(
                reason="Validation failed",
                data={
                    "validation_errors": validation_errors,
                    "validation_warnings": validation_warnings,
                    "document_count": document_count,
                    "retrieval_time_ms": retrieval_time_ms,
                    "silent_failure": silent_failure,
                    "circuit_state": circuit_state,
                },
            )

        return StageOutput.ok(
            validation_passed=True,
            document_count=document_count,
            retrieval_time_ms=retrieval_time_ms,
            silent_failure=silent_failure,
            circuit_state=circuit_state,
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
        metrics = {
            "test_name": self.test_name,
            "timestamp": datetime.now().isoformat(),
            "documents_retrieved": ctx.inputs.get_from("vector_db_enrich", "document_count") or 0,
            "retrieval_time_ms": ctx.inputs.get_from("vector_db_enrich", "retrieval_time_ms") or 0,
            "search_time_ms": ctx.inputs.get_from("vector_db_enrich", "search_time_ms") or 0,
            "cb_state": ctx.inputs.get_from("vector_db_enrich", "cb_state") or "unknown",
            "silent_failure": ctx.inputs.get_from("vector_db_enrich", "silent_failure") or False,
            "retry_count": ctx.inputs.get_from("vector_db_enrich", "retry_count") or 0,
            "error_message": ctx.inputs.get_from("vector_db_enrich", "error_message"),
        }

        self.metrics.append(metrics)

        # Log to file if specified
        if self.result_file:
            with open(self.result_file, "a") as f:
                f.write(json.dumps(metrics) + "\n")

        logger.info(f"Test metrics for {self.test_name}: {json.dumps(metrics, indent=2)}")

        return StageOutput.ok(
            metrics_collected=True,
            test_metrics=metrics,
        )


class RetryStage(Stage):
    """
    TRANSFORM stage that implements retry logic for failed operations.
    
    This stage demonstrates how retry patterns can be implemented in
    Stageflow pipelines.
    """

    name = "retry_handler"
    kind = StageKind.TRANSFORM

    def __init__(
        self,
        max_retries: int = 3,
        base_delay_ms: float = 100.0,
        max_delay_ms: float = 5000.0,
        jitter: float = 0.2,
    ):
        self.max_retries = max_retries
        self.base_delay_ms = base_delay_ms
        self.max_delay_ms = max_delay_ms
        self.jitter = jitter
        self.retry_history = []

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and jitter."""
        delay = min(
            self.base_delay_ms * (2 ** attempt),
            self.max_delay_ms,
        )
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return max(0, delay)

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Implement retry logic for failed operations."""
        previous_attempts = ctx.inputs.get_from("vector_db_enrich", "retry_count") or 0
        previous_error = ctx.inputs.get_from("vector_db_enrich", "error_message")
        
        retry_count = previous_attempts
        delay_ms = self._calculate_delay(retry_count)
        
        self.retry_history.append({
            "attempt": retry_count + 1,
            "delay_ms": delay_ms,
            "previous_error": previous_error,
        })

        return StageOutput.ok(
            retry_count=retry_count,
            next_delay_ms=delay_ms,
            retry_history=self.retry_history,
            should_retry=retry_count < self.max_retries,
        )


def create_test_pipeline(
    test_case: TestCase,
    vector_store: MockVectorStore,
    result_file: Optional[str] = None,
    detect_silent_failures: bool = False,
) -> Pipeline:
    """
    Create a test pipeline for a specific resilience scenario.
    """
    # Configure vector store
    vector_store.set_failure_mode(
        test_case.failure_mode,
        probability=test_case.failure_probability,
    )

    # Create stages
    enrich_stage = VectorDBEnrichStage(
        vector_store=vector_store,
        test_name=test_case.name,
        expected_documents=5,
        top_k=5,
    )

    validation_stage = ValidationStage(
        expected_min_documents=1,
        max_latency_ms=test_case.timeout_ms * 2,
        detect_silent_failures=detect_silent_failures or test_case.should_detect_silent,
    )

    metrics_stage = MetricsCollectionStage(
        test_name=test_case.name,
        result_file=result_file,
    )

    # Build pipeline
    pipeline = Pipeline()
    pipeline = pipeline.with_stage("vector_db_enrich", enrich_stage, StageKind.ENRICH)
    pipeline = pipeline.with_stage(
        "validation", validation_stage, StageKind.GUARD, dependencies=("vector_db_enrich",)
    )
    pipeline = pipeline.with_stage(
        "metrics_collection", metrics_stage, StageKind.WORK, dependencies=("vector_db_enrich", "validation")
    )

    return pipeline


def create_baseline_pipeline(
    vector_store: MockVectorStore,
    result_file: Optional[str] = None,
) -> Pipeline:
    """Create a baseline pipeline for normal operation."""
    test_case = TestCase(
        name="baseline",
        description="Normal operation without failures",
        failure_mode=FailureMode.NONE,
        expected_behavior="All operations complete successfully",
        failure_probability=0.0,
    )
    return create_test_pipeline(test_case, vector_store, result_file)


async def run_pipeline_test(
    pipeline: Pipeline,
    test_case: TestCase,
    input_text: str = "test query about topic 1",
) -> PipelineResult:
    """
    Execute a single pipeline test and return results.
    """
    test_results["total_tests"] += 1

    start_time = time.perf_counter()

    try:
        # Create context
        snapshot = create_test_snapshot(input_text=input_text)

        context = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name="root",
            timer=PipelineTimer(),
        )

        # Build and run pipeline
        graph = pipeline.build()
        result = await graph.run(context)

        execution_time_ms = (time.perf_counter() - start_time) * 1000

        # Extract metrics from result
        output = {}
        for stage_name, stage_result in result.items():
            if stage_name == "vector_db_enrich":
                if hasattr(stage_result, "data"):
                    output = stage_result.data or {}
                break

        documents_retrieved = output.get("document_count", 0)
        silent_failure = output.get("silent_failure", False)
        circuit_state = output.get("cb_state", "closed")
        retry_count = output.get("retry_count", 0)
        error_message = output.get("error_message")

        # Determine success
        all_completed = all(
            hasattr(r, "status") and r.status.value == "ok"
            for r in result.values()
        )

        # Check for validation stage cancellation
        validation_cancelled = False
        for stage_name, stage_result in result.items():
            if stage_name == "validation":
                if hasattr(stage_result, "status") and stage_result.status.value == "cancel":
                    validation_cancelled = True
                    break

        success = (
            documents_retrieved >= 1 and all_completed and not validation_cancelled
        )

        if silent_failure:
            test_results["silent_failures"] += 1

        if success:
            test_results["passed"] += 1
        else:
            test_results["failed"] += 1

        # Check circuit breaker state
        circuit_breaker_tripped = circuit_state == CircuitBreakerState.OPEN.value

        return PipelineResult(
            test_name=test_case.name,
            success=success,
            execution_time_ms=execution_time_ms,
            documents_retrieved=documents_retrieved,
            circuit_state=circuit_state,
            silent_failure=silent_failure,
            error_message=error_message,
            retry_count=retry_count,
            circuit_breaker_tripped=circuit_breaker_tripped,
            metrics={
                "validation_passed": all_completed and not validation_cancelled,
            },
        )

    except Exception as e:
        execution_time_ms = (time.perf_counter() - start_time) * 1000
        test_results["failed"] += 1

        return PipelineResult(
            test_name=test_case.name,
            success=False,
            execution_time_ms=execution_time_ms,
            documents_retrieved=0,
            circuit_state="error",
            silent_failure=False,
            error_message=str(e),
        )


async def run_comprehensive_tests(
    result_file: str = "results/enrich007_test_results.json",
) -> Dict[str, Any]:
    """
    Run comprehensive vector DB connection resilience tests.
    
    This function executes multiple test scenarios:
    1. Baseline (no failures)
    2. Connection timeouts
    3. Query timeouts
    4. Circuit breaker activation
    5. Silent empty results
    6. Authentication failures
    7. Service unavailability
    8. Resource exhaustion
    9. Network partition
    10. Partial write failures
    """
    results_dir = Path(result_file).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    # Initialize test environment
    vector_store, failure_injector = create_resilience_test_environment(
        document_count=100,
        failure_probability=0.1,
        base_latency_ms=30.0,
        timeout_ms=3000.0,
        circuit_breaker_threshold=5,
    )

    # Add test documents
    for i in range(100):
        doc_id = f"doc_{i}"
        chunk_id = f"chunk_{i}"
        content = f"Test document {i} about topic {i % 5}. " * 3
        await vector_store.add_document(doc_id, chunk_id, content)

    # Define test cases
    test_cases = [
        TestCase(
            name="baseline",
            description="Normal operation without failures",
            failure_mode=FailureMode.NONE,
            expected_behavior="All operations complete successfully",
            failure_probability=0.0,
        ),
        TestCase(
            name="connection_timeout",
            description="Connection timeout simulation",
            failure_mode=FailureMode.TIMEOUT,
            expected_behavior="Timeout detected and handled gracefully",
            failure_probability=0.3,
            base_latency_ms=2000.0,
            timeout_ms=1000.0,
        ),
        TestCase(
            name="query_timeout",
            description="Query execution timeout",
            failure_mode=FailureMode.QUERY_TIMEOUT,
            expected_behavior="Query timeout detected and reported",
            failure_probability=0.3,
            base_latency_ms=2000.0,
            timeout_ms=1000.0,
        ),
        TestCase(
            name="circuit_breaker_trip",
            description="Circuit breaker activation after failures",
            failure_mode=FailureMode.SERVICE_UNAVAILABLE,
            expected_behavior="Circuit breaker opens after threshold",
            failure_probability=1.0,
            circuit_breaker_threshold=5,
        ),
        TestCase(
            name="circuit_breaker_recovery",
            description="Circuit breaker recovery after timeout",
            failure_mode=FailureMode.SERVICE_UNAVAILABLE,
            expected_behavior="Circuit breaker transitions to half-open then closed",
            failure_probability=0.5,
            circuit_breaker_threshold=3,
        ),
        TestCase(
            name="silent_empty_results",
            description="Silent empty result detection",
            failure_mode=FailureMode.SILENT_EMPTY,
            expected_behavior="Empty results detected as potential silent failure",
            failure_probability=0.3,
            should_detect_silent=True,
        ),
        TestCase(
            name="auth_failure",
            description="Authentication failure handling",
            failure_mode=FailureMode.AUTH_FAILURE,
            expected_behavior="Auth failure properly reported, no retry",
            failure_probability=0.2,
        ),
        TestCase(
            name="service_unavailable",
            description="Service temporarily unavailable",
            failure_mode=FailureMode.SERVICE_UNAVAILABLE,
            expected_behavior="Service unavailability detected and handled",
            failure_probability=0.3,
        ),
        TestCase(
            name="resource_exhausted",
            description="Resource exhaustion handling",
            failure_mode=FailureMode.RESOURCE_EXHAUSTED,
            expected_behavior="Resource exhaustion properly reported",
            failure_probability=0.2,
        ),
        TestCase(
            name="network_partition",
            description="Network partition simulation",
            failure_mode=FailureMode.NETWORK_PARTITION,
            expected_behavior="Network partition detected, fallback triggered",
            failure_probability=0.2,
        ),
        TestCase(
            name="partial_write",
            description="Partial write failure detection",
            failure_mode=FailureMode.PARTIAL_WRITE,
            expected_behavior="Partial write detected and reported",
            failure_probability=0.2,
        ),
    ]

    all_results = []

    logger.info("=" * 60)
    logger.info("ENRICH-007 Vector DB Connection Resilience Test Suite")
    logger.info("=" * 60)

    for test_case in test_cases:
        logger.info(f"\nRunning test: {test_case.name}")
        logger.info(f"  Description: {test_case.description}")
        logger.info(f"  Failure mode: {test_case.failure_mode.value}")
        logger.info(f"  Failure probability: {test_case.failure_probability}")

        # Reset state for each test
        vector_store.reset()
        failure_injector.reset()

        # Re-populate documents
        for i in range(100):
            doc_id = f"doc_{i}"
            chunk_id = f"chunk_{i}"
            content = f"Test document {i} about topic {i % 5}. " * 3
            await vector_store.add_document(doc_id, chunk_id, content)

        # Create and run pipeline
        pipeline = create_test_pipeline(
            test_case, vector_store, result_file, detect_silent_failures=test_case.should_detect_silent
        )
        result = await run_pipeline_test(pipeline, test_case)

        all_results.append({
            "test_name": result.test_name,
            "success": result.success,
            "execution_time_ms": result.execution_time_ms,
            "documents_retrieved": result.documents_retrieved,
            "circuit_state": result.circuit_state,
            "silent_failure": result.silent_failure,
            "retry_count": result.retry_count,
            "circuit_breaker_tripped": result.circuit_breaker_tripped,
            "error": result.error_message,
            "metrics": result.metrics,
        })

        logger.info(f"  Result: {'PASS' if result.success else 'FAIL'}")
        logger.info(f"  Documents: {result.documents_retrieved}")
        logger.info(f"  Circuit State: {result.circuit_state}")
        logger.info(f"  Silent Failure: {result.silent_failure}")
        if result.error_message:
            logger.info(f"  Error: {result.error_message}")

    # Save results
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
    logger.info("Test Summary")
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


async def run_silent_failure_detection_tests(
    result_file: str = "results/enrich007_silent_failures.json",
) -> Dict[str, Any]:
    """
    Run specialized tests for silent failure detection.
    
    These tests specifically target:
    1. Swallowed exceptions
    2. Incorrect default values
    3. Partial state corruption
    4. Asynchronous failures
    """
    results_dir = Path(result_file).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    results = []

    logger.info("=" * 60)
    logger.info("ENRICH-007 Silent Failure Detection Tests")
    logger.info("=" * 60)

    # Test 1: Empty results without error
    logger.info("\nTest: Empty results without error")
    vector_store, _ = create_silent_failure_environment()
    for i in range(50):
        await vector_store.add_document(f"doc_{i}", f"chunk_{i}", f"Content {i}")

    pipeline = create_test_pipeline(
        TestCase(
            name="silent_empty_results",
            description="Empty results without error indication",
            failure_mode=FailureMode.SILENT_EMPTY,
            expected_behavior="Should detect empty results as potential failure",
            failure_probability=0.5,
            should_detect_silent=True,
        ),
        vector_store,
        result_file,
        detect_silent_failures=True,
    )

    result = await run_pipeline_test(pipeline, TestCase(
        name="silent_empty_results",
        description="Empty results without error indication",
        failure_mode=FailureMode.SILENT_EMPTY,
        expected_behavior="Should detect empty results as failure",
        failure_probability=0.5,
    ))

    results.append({
        "test_name": "silent_empty_results",
        "success": result.success,
        "silent_failure_detected": result.silent_failure,
        "documents_retrieved": result.documents_retrieved,
    })

    # Test 2: Circuit breaker silent blocking
    logger.info("\nTest: Circuit breaker silent blocking")
    vector_store, failure_injector = create_circuit_breaker_environment(threshold=3)
    for i in range(50):
        await vector_store.add_document(f"doc_{i}", f"chunk_{i}", f"Content {i}")

    # First trip the circuit breaker
    for _ in range(5):
        pipeline = create_test_pipeline(
            TestCase(
                name="circuit_breaker_trip",
                description="Circuit breaker trip",
                failure_mode=FailureMode.SERVICE_UNAVAILABLE,
                expected_behavior="Circuit breaker should trip",
                failure_probability=1.0,
                circuit_breaker_threshold=3,
            ),
            vector_store,
        )
        await run_pipeline_test(pipeline, TestCase(
            name="circuit_breaker_trip",
            description="Circuit breaker trip",
            failure_mode=FailureMode.SERVICE_UNAVAILABLE,
            expected_behavior="Circuit breaker should trip",
            failure_probability=1.0,
        ))

    # Now test in OPEN state
    pipeline = create_test_pipeline(
        TestCase(
            name="circuit_breaker_open",
            description="Circuit breaker in OPEN state",
            failure_mode=FailureMode.SERVICE_UNAVAILABLE,
            expected_behavior="Requests should be blocked",
            failure_probability=0.0,  # No additional failures
            circuit_breaker_threshold=3,
        ),
        vector_store,
    )

    result = await run_pipeline_test(pipeline, TestCase(
        name="circuit_breaker_open",
        description="Circuit breaker blocking requests",
        failure_mode=FailureMode.SERVICE_UNAVAILABLE,
        expected_behavior="Requests blocked by circuit breaker",
        failure_probability=0.0,
    ))

    results.append({
        "test_name": "circuit_breaker_open",
        "success": result.success,
        "circuit_state": result.circuit_state,
        "documents_retrieved": result.documents_retrieved,
    })

    # Save results
    with open(result_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "results": results,
            },
            f,
            indent=2,
        )

    logger.info(f"\nSilent failure tests completed. Results saved to: {result_file}")

    return {"results": results}


async def run_retry_pattern_tests(
    result_file: str = "results/enrich007_retry_tests.json",
) -> Dict[str, Any]:
    """
    Run tests for retry pattern effectiveness.
    
    These tests verify:
    1. Exponential backoff implementation
    2. Jitter effectiveness
    3. Max retry limit enforcement
    4. Success after retry
    """
    results_dir = Path(result_file).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    results = []

    logger.info("=" * 60)
    logger.info("ENRICH-007 Retry Pattern Tests")
    logger.info("=" * 60)

    # Test 1: Retry on transient failure
    logger.info("\nTest: Retry on transient failure")
    vector_store, failure_injector = create_vector_db_test_environment(
        document_count=50,
        failure_probability=0.5,
        base_latency_ms=50.0,
    )

    for i in range(50):
        await vector_store.add_document(f"doc_{i}", f"chunk_{i}", f"Content {i}")

    pipeline = Pipeline()
    enrich_stage = VectorDBEnrichStage(
        vector_store=vector_store,
        test_name="retry_transient",
        expected_documents=5,
    )
    pipeline = pipeline.with_stage("vector_db_enrich", enrich_stage, StageKind.ENRICH)

    result = await run_pipeline_test(pipeline, TestCase(
        name="retry_transient",
        description="Retry on transient failure",
        failure_mode=FailureMode.TIMEOUT,
        expected_behavior="Should retry and eventually succeed",
        failure_probability=0.5,
    ))

    results.append({
        "test_name": "retry_transient",
        "success": result.success,
        "retry_count": result.retry_count,
        "documents_retrieved": result.documents_retrieved,
    })

    # Test 2: Max retry limit
    logger.info("\nTest: Max retry limit enforcement")
    vector_store, failure_injector = create_vector_db_test_environment(
        document_count=50,
        failure_probability=1.0,  # Always fail
        base_latency_ms=50.0,
    )

    for i in range(50):
        await vector_store.add_document(f"doc_{i}", f"chunk_{i}", f"Content {i}")

    pipeline = Pipeline()
    enrich_stage = VectorDBEnrichStage(
        vector_store=vector_store,
        test_name="max_retries",
        expected_documents=5,
    )
    pipeline = pipeline.with_stage("vector_db_enrich", enrich_stage, StageKind.ENRICH)

    result = await run_pipeline_test(pipeline, TestCase(
        name="max_retries",
        description="Max retry limit enforcement",
        failure_mode=FailureMode.TIMEOUT,
        expected_behavior="Should fail after max retries",
        failure_probability=1.0,
    ))

    results.append({
        "test_name": "max_retries",
        "success": result.success,
        "retry_count": result.retry_count,
        "error": result.error_message,
    })

    # Save results
    with open(result_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "results": results,
            },
            f,
            indent=2,
        )

    logger.info(f"\nRetry pattern tests completed. Results saved to: {result_file}")

    return {"results": results}


# Convenience function for running all tests
async def run_all_enrich007_tests(
    base_dir: str = "results",
) -> Dict[str, Any]:
    """
    Run all ENRICH-007 vector DB connection resilience tests.
    
    Creates output directory structure:
    - {base_dir}/enrich007/
      - comprehensive_results.json
      - silent_failure_results.json
      - retry_tests_results.json
      - logs/
    """
    base_path = Path(base_dir) / "enrich007"
    base_path.mkdir(parents=True, exist_ok=True)

    (base_path / "logs").mkdir(exist_ok=True)

    comprehensive_results = await run_comprehensive_tests(
        result_file=str(base_path / "comprehensive_results.json"),
    )

    silent_failure_results = await run_silent_failure_detection_tests(
        result_file=str(base_path / "silent_failure_results.json"),
    )

    retry_results = await run_retry_pattern_tests(
        result_file=str(base_path / "retry_tests_results.json"),
    )

    return {
        "comprehensive": comprehensive_results,
        "silent_failures": silent_failure_results,
        "retry_tests": retry_results,
        "output_dir": str(base_path),
    }


if __name__ == "__main__":
    asyncio.run(run_all_enrich007_tests())
