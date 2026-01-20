"""
ENRICH-002 Test Pipelines: Embedding Drift and Index Desync

This module implements comprehensive test pipelines for stress-testing
Stageflow's ENRICH stage handling of embedding drift and index desync scenarios.

Pipeline Categories:
1. Baseline Pipeline - Normal operation verification
2. Drift Injection Pipeline - Simulated embedding drift
3. Index Desync Pipeline - Index/document mismatch scenarios
4. Silent Failure Pipeline - Detection of silent failures
5. Recovery Pipeline - Failure recovery and fallback
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

import numpy as np

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow import (
    Pipeline,
    Stage,
    StageKind,
    StageOutput,
    StageContext,
    PipelineTimer,
)
from stageflow.context import ContextSnapshot, DocumentEnrichment, Message, RunIdentity
from stageflow.stages import StageInputs
from stageflow.testing import create_test_pipeline_context, create_test_snapshot

from mocks.embedding_drift_mocks import (
    MockEmbeddingModel,
    MockVectorStore,
    EmbeddingDriftDetector,
    VectorStoreMode,
    DriftType,
    create_drift_injector,
    create_synced_test_environment,
    create_synced_test_environment_async,
    create_drift_test_environment,
    create_drift_test_environment_async,
)

logging.basicConfig(level=logging.INFO)
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
    vector_store_mode: VectorStoreMode
    expected_behavior: str
    drift_severity: float = 0.1
    silent_failure_rate: float = 0.0


@dataclass  
class PipelineResult:
    """Result of a pipeline test execution."""
    test_name: str
    success: bool
    execution_time_ms: float
    documents_retrieved: int
    drift_score: float
    silent_failure: bool
    error_message: Optional[str] = None
    metrics: dict = field(default_factory=dict)


class EmbeddingDriftTestStage(Stage):
    """
    ENRICH stage for document retrieval with configurable drift simulation.
    
    This stage queries the mock vector store and returns document enrichments.
    It can be configured to simulate various drift and failure scenarios.
    """

    name = "embedding_drift_test"
    kind = StageKind.ENRICH

    def __init__(
        self,
        vector_store: MockVectorStore,
        drift_detector: EmbeddingDriftDetector,
        test_name: str,
        expected_documents: int = 5,
    ):
        self.vector_store = vector_store
        self.drift_detector = drift_detector
        self.test_name = test_name
        self.expected_documents = expected_documents
        self.drift_metrics = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute document enrichment with drift tracking."""
        query = ctx.snapshot.input_text or "test query"
        start_time = time.perf_counter()

        try:
            # Perform similarity search
            result = await self.vector_store.similarity_search(
                query=query,
                k=self.expected_documents,
                include_metadata=True,
            )

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Track drift metrics
            self.drift_metrics.append({
                "test_name": self.test_name,
                "timestamp": datetime.now().isoformat(),
                "search_time_ms": result.search_time_ms,
                "drift_score": result.drift_score,
                "neighbor_overlap": result.neighbor_overlap_with_previous,
                "documents_retrieved": len(result.documents),
                "is_desynced": result.is_desynced,
                "silent_failure": result.silent_failure,
            })

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

            # Detect drift if we have baseline
            drift_report = self.drift_detector.detect_drift(
                current_embeddings=[d.get("vector", []) for d in result.documents],
            )

            return StageOutput.ok(
                documents=[d.to_dict() for d in documents],
                document_count=len(documents),
                retrieval_time_ms=execution_time_ms,
                drift_score=result.drift_score,
                neighbor_overlap=result.neighbor_overlap_with_previous,
                is_desynced=result.is_desynced,
                silent_failure=result.silent_failure,
                drift_report=drift_report,
                test_name=self.test_name,
            )

        except Exception as e:
            logger.error(f"Embedding drift test stage failed: {e}")
            return StageOutput.fail(
                error=f"Document retrieval failed: {e}",
                test_name=self.test_name,
            )


class ValidationStage(Stage):
    """
    GUARD stage for validating enrichment results.
    
    This stage validates that retrieved documents meet expected criteria
    and detects silent failures.
    """

    name = "validation"
    kind = StageKind.GUARD

    def __init__(self, expected_min_documents: int = 1, max_drift_score: float = 0.5):
        self.expected_min_documents = expected_min_documents
        self.max_drift_score = max_drift_score
        self.validation_failures = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Validate enrichment results."""
        # Get enrichment output
        enrich_output = ctx.inputs.get_from("embedding_drift_test", "documents")
        document_count = ctx.inputs.get_from("embedding_drift_test", "document_count")
        drift_score = ctx.inputs.get_from("embedding_drift_test", "drift_score")
        silent_failure = ctx.inputs.get_from("embedding_drift_test", "silent_failure")
        
        validation_passed = True
        validation_errors = []

        # Check document count
        if document_count < self.expected_min_documents:
            validation_passed = False
            error_msg = f"Insufficient documents: expected >= {self.expected_min_documents}, got {document_count}"
            validation_errors.append(error_msg)
            self.validation_failures.append({
                "type": "insufficient_documents",
                "expected": self.expected_min_documents,
                "actual": document_count,
            })

        # Check drift score
        if drift_score and drift_score > self.max_drift_score:
            validation_passed = False
            error_msg = f"Drift score exceeds threshold: {drift_score} > {self.max_drift_score}"
            validation_errors.append(error_msg)
            self.validation_failures.append({
                "type": "excessive_drift",
                "threshold": self.max_drift_score,
                "actual": drift_score,
            })

        # Check for silent failure
        if silent_failure:
            validation_passed = False
            error_msg = "Silent failure detected in enrichment"
            validation_errors.append(error_msg)
            self.validation_failures.append({
                "type": "silent_failure",
                "details": "Retrieval returned without error but failed silently",
            })

        if not validation_passed:
            return StageOutput.cancel(
                reason="Validation failed",
                data={
                    "validation_errors": validation_errors,
                    "document_count": document_count,
                    "drift_score": drift_score,
                    "silent_failure": silent_failure,
                },
            )

        return StageOutput.ok(
            validation_passed=True,
            document_count=document_count,
            drift_score=drift_score,
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
        # Get all test outputs - get the full output dict from each stage
        enrich_output = ctx.inputs.get_from("embedding_drift_test", "documents")
        if enrich_output is None:
            # Try to get specific keys directly
            enrich_output = {}
        
        validation_output = ctx.inputs.get_from("validation", "validation_passed")
        if validation_output is None:
            validation_output = {}
        
        metrics = {
            "test_name": self.test_name,
            "timestamp": datetime.now().isoformat(),
            "documents_retrieved": ctx.inputs.get_from("embedding_drift_test", "document_count") or 0,
            "retrieval_time_ms": ctx.inputs.get_from("embedding_drift_test", "retrieval_time_ms") or 0,
            "drift_score": ctx.inputs.get_from("embedding_drift_test", "drift_score") or 0,
            "neighbor_overlap": ctx.inputs.get_from("embedding_drift_test", "neighbor_overlap") or 1.0,
            "is_desynced": ctx.inputs.get_from("embedding_drift_test", "is_desynced") or False,
            "silent_failure": ctx.inputs.get_from("embedding_drift_test", "silent_failure") or False,
            "validation_passed": validation_output.get("validation_passed") if isinstance(validation_output, dict) else False,
            "drift_report": ctx.inputs.get_from("embedding_drift_test", "drift_report") or {},
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


def create_test_pipeline(
    test_case: TestCase,
    vector_store: MockVectorStore,
    drift_detector: EmbeddingDriftDetector,
    result_file: Optional[str] = None,
) -> Pipeline:
    """
    Create a test pipeline for a specific drift scenario.
    """
    # Configure vector store
    vector_store.set_mode(test_case.vector_store_mode, test_case.drift_severity)
    vector_store.silent_failure_rate = test_case.silent_failure_rate

    # Create stages
    enrich_stage = EmbeddingDriftTestStage(
        vector_store=vector_store,
        drift_detector=drift_detector,
        test_name=test_case.name,
        expected_documents=5,
    )

    validation_stage = ValidationStage(
        expected_min_documents=1,
        max_drift_score=0.8,  # Allow higher drift for testing
    )

    metrics_stage = MetricsCollectionStage(
        test_name=test_case.name,
        result_file=result_file,
    )

    # Build pipeline
    pipeline = Pipeline()
    pipeline = pipeline.with_stage("embedding_drift_test", enrich_stage, StageKind.ENRICH)
    pipeline = pipeline.with_stage("validation", validation_stage, StageKind.GUARD, dependencies=("embedding_drift_test",))
    pipeline = pipeline.with_stage("metrics_collection", metrics_stage, StageKind.WORK, dependencies=("embedding_drift_test", "validation"))

    return pipeline


def create_baseline_pipeline(
    vector_store: MockVectorStore,
    drift_detector: EmbeddingDriftDetector,
    result_file: Optional[str] = None,
) -> Pipeline:
    """
    Create a baseline pipeline for normal operation.
    """
    test_case = TestCase(
        name="baseline",
        description="Normal operation without drift",
        vector_store_mode=VectorStoreMode.SYNCED,
        expected_behavior="Normal retrieval",
    )
    return create_test_pipeline(test_case, vector_store, drift_detector, result_file)


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
        # Create context using StageContext
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

        # Extract metrics from result - graph.run returns dict of stage_name -> StageOutput
        # Get the embedding_drift_test output which has the metrics we need
        output = {}
        for stage_name, stage_result in result.items():
            if stage_name == "embedding_drift_test":
                # StageOutput has 'data' attribute with key-value pairs
                if hasattr(stage_result, 'data'):
                    output = stage_result.data or {}
                break
        
        documents_retrieved = output.get("document_count", 0)
        drift_score = output.get("drift_score", 0)
        silent_failure = output.get("silent_failure", False)
        is_desynced = output.get("is_desynced", False)

        # Determine success - check all stage results for failures
        all_completed = all(
            hasattr(r, 'status') and r.status.value == "ok" 
            for r in result.values()
        )
        
        # Get error message from failed stage if any
        error_message = None
        for stage_name, stage_result in result.items():
            if hasattr(stage_result, 'status') and stage_result.status.value != "ok":
                error_message = stage_result.error if hasattr(stage_result, 'error') else f"Stage {stage_name} failed"
                break
        
        success = (
            documents_retrieved >= 1 and
            not silent_failure and
            all_completed
        )

        if silent_failure:
            test_results["silent_failures"] += 1

        if success:
            test_results["passed"] += 1
        else:
            test_results["failed"] += 1

        return PipelineResult(
            test_name=test_case.name,
            success=success,
            execution_time_ms=execution_time_ms,
            documents_retrieved=documents_retrieved,
            drift_score=drift_score,
            silent_failure=silent_failure,
            error_message=error_message,
            metrics={
                "is_desynced": is_desynced,
                "status": "completed" if all_completed else "failed",
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
            drift_score=0,
            silent_failure=False,
            error_message=str(e),
        )


async def run_comprehensive_tests(
    result_file: str = "results/enrich002_test_results.json",
) -> dict:
    """
    Run comprehensive embedding drift tests.
    
    This function executes multiple test scenarios:
    1. Baseline (no drift)
    2. Text shape drift
    3. Hidden character drift
    4. Model version mismatch
    5. Index desync
    6. Partial re-embedding
    7. Silent failures
    8. Recovery scenarios
    """
    results_dir = Path(result_file).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    # Initialize test environment
    embedding_model, vector_store, drift_detector = create_drift_test_environment(
        document_count=100,
        drift_document_ratio=0.3,
    )

    # Define test cases
    test_cases = [
        TestCase(
            name="baseline",
            description="Normal operation without drift",
            vector_store_mode=VectorStoreMode.SYNCED,
            expected_behavior="All documents retrieved correctly",
        ),
        TestCase(
            name="text_shape_drift",
            description="Text shape variations (whitespace, markdown)",
            vector_store_mode=VectorStoreMode.DRIFTING,
            expected_behavior="Some retrieval degradation expected",
            drift_severity=0.15,
        ),
        TestCase(
            name="hidden_char_drift",
            description="Hidden characters in documents",
            vector_store_mode=VectorStoreMode.DRIFTING,
            expected_behavior="Drift detected but retrieval continues",
            drift_severity=0.1,
        ),
        TestCase(
            name="index_desync",
            description="Index out of sync with embeddings",
            vector_store_mode=VectorStoreMode.DESYNCED,
            expected_behavior="Incorrect or degraded retrieval",
            drift_severity=0.2,
        ),
        TestCase(
            name="partial_reembed",
            description="Partial document re-embedding",
            vector_store_mode=VectorStoreMode.PARTIAL,
            expected_behavior="Fewer documents retrieved than requested",
            drift_severity=0.1,
        ),
        TestCase(
            name="silent_failure",
            description="Silent failures without error propagation",
            vector_store_mode=VectorStoreMode.SYNCED,
            expected_behavior="Silent failure detected by validation",
            drift_severity=0.0,
            silent_failure_rate=0.2,
        ),
        TestCase(
            name="mixed_versions",
            description="Mixed embedding model versions",
            vector_store_mode=VectorStoreMode.DESYNCED,
            expected_behavior="Inconsistent retrieval quality",
            drift_severity=0.25,
        ),
        TestCase(
            name="high_drift",
            description="High severity drift scenario",
            vector_store_mode=VectorStoreMode.DRIFTING,
            expected_behavior="Significant retrieval degradation",
            drift_severity=0.4,
        ),
    ]

    all_results = []

    logger.info("=" * 60)
    logger.info("ENRICH-002 Embedding Drift Test Suite")
    logger.info("=" * 60)

    for test_case in test_cases:
        logger.info(f"\nRunning test: {test_case.name}")
        logger.info(f"  Description: {test_case.description}")
        logger.info(f"  Mode: {test_case.vector_store_mode.value}")

        # Reset vector store for each test
        vector_store.reset()
        
        # Re-populate documents
        for i in range(100):
            doc_id = f"doc_{i}"
            chunk_id = f"chunk_{i}"
            content = f"Test document {i} with some content about topic {i % 5}. " * 3
            await vector_store.add_document_async(doc_id, chunk_id, content)

        # Create and run pipeline
        pipeline = create_test_pipeline(test_case, vector_store, drift_detector, result_file)
        result = await run_pipeline_test(pipeline, test_case)

        all_results.append({
            "test_name": result.test_name,
            "success": result.success,
            "execution_time_ms": result.execution_time_ms,
            "documents_retrieved": result.documents_retrieved,
            "drift_score": result.drift_score,
            "silent_failure": result.silent_failure,
            "error": result.error_message,
            "metrics": result.metrics,
        })

        logger.info(f"  Result: {'PASS' if result.success else 'FAIL'}")
        logger.info(f"  Documents: {result.documents_retrieved}")
        logger.info(f"  Drift Score: {result.drift_score:.4f}")
        logger.info(f"  Silent Failure: {result.silent_failure}")
        if result.error_message:
            logger.info(f"  Error: {result.error_message}")

    # Save results
    with open(result_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_tests": test_results["total_tests"],
                "passed": test_results["passed"],
                "failed": test_results["failed"],
                "silent_failures": test_results["silent_failures"],
            },
            "results": all_results,
        }, f, indent=2)

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
    result_file: str = "results/enrich002_silent_failures.json",
) -> dict:
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
    logger.info("ENRICH-002 Silent Failure Detection Tests")
    logger.info("=" * 60)

    # Test 1: Empty results without error
    logger.info("\nTest: Empty results without error")
    embedding_model, vector_store, _ = await create_synced_test_environment_async(document_count=50)
    vector_store.silent_failure_rate = 0.5

    pipeline = Pipeline()
    stage = EmbeddingDriftTestStage(
        vector_store=vector_store,
        drift_detector=EmbeddingDriftDetector(),
        test_name="silent_empty_results",
        expected_documents=5,
    )
    pipeline = pipeline.with_stage("embedding_drift_test", stage, StageKind.ENRICH)

    result = await run_pipeline_test(pipeline, TestCase(
        name="silent_empty_results",
        description="Empty results without error indication",
        vector_store_mode=VectorStoreMode.SYNCED,
        expected_behavior="Should detect empty results as failure",
    ))

    results.append({
        "test_name": "silent_empty_results",
        "success": result.success,
        "silent_failure_detected": result.silent_failure,
        "documents_retrieved": result.documents_retrieved,
    })

    # Test 2: Desync detection
    logger.info("\nTest: Index desync without error")
    embedding_model, vector_store, _ = await create_drift_test_environment_async(document_count=50)
    vector_store.set_mode(VectorStoreMode.DESYNCED, severity=0.3)

    stage = EmbeddingDriftTestStage(
        vector_store=vector_store,
        drift_detector=EmbeddingDriftDetector(),
        test_name="desync_no_error",
        expected_documents=5,
    )
    pipeline = Pipeline()
    pipeline.with_stage("embedding_drift_test", stage, StageKind.ENRICH)

    result = await run_pipeline_test(pipeline, TestCase(
        name="desync_no_error",
        description="Index desync without explicit error",
        vector_store_mode=VectorStoreMode.DESYNCED,
        expected_behavior="Should detect desync via drift metrics",
    ))

    results.append({
        "test_name": "desync_no_error",
        "success": result.success,
        "is_desynced": result.metrics.get("is_desynced", False),
        "drift_score": result.drift_score,
    })

    # Save results
    with open(result_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "results": results,
        }, f, indent=2)

    logger.info(f"\nSilent failure tests completed. Results saved to: {result_file}")

    return {"results": results}


# Convenience function for running all tests
async def run_all_enrich002_tests(
    base_dir: str = "results",
) -> dict:
    """
    Run all ENRICH-002 embedding drift tests.
    
    Creates output directory structure:
    - {base_dir}/enrich002/
      - comprehensive_results.json
      - silent_failure_results.json
      - logs/
    """
    base_path = Path(base_dir) / "enrich002"
    base_path.mkdir(parents=True, exist_ok=True)

    (base_path / "logs").mkdir(exist_ok=True)

    comprehensive_results = await run_comprehensive_tests(
        result_file=str(base_path / "comprehensive_results.json"),
    )

    silent_failure_results = await run_silent_failure_detection_tests(
        result_file=str(base_path / "silent_failure_results.json"),
    )

    return {
        "comprehensive": comprehensive_results,
        "silent_failures": silent_failure_results,
        "output_dir": str(base_path),
    }


if __name__ == "__main__":
    asyncio.run(run_all_enrich002_tests())
