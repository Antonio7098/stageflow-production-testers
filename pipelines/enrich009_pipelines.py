"""
ENRICH-009 Test Pipelines: Chunk Overlap and Deduplication

This module implements comprehensive test pipelines for stress-testing
Stageflow's ENRICH stage handling of chunk overlap and deduplication
in RAG/Knowledge retrieval pipelines.

Pipeline Categories:
1. Baseline Pipeline - Normal chunking operation verification
2. Overlap Variation Pipeline - Different overlap percentages
3. Deduplication Pipeline - Duplicate detection and removal
4. Silent Failure Pipeline - Detection of silent failures
5. Edge Case Pipeline - Boundary conditions and unusual inputs
6. Scale Pipeline - Performance under load
"""

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
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

from mocks.chunk_overlap_deduplication_mocks import (
    ChunkOverlapDeduplicationMocks,
    ChunkingConfig,
    Chunk,
    Document,
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
class ChunkTestCase:
    """Definition of a chunking test case."""
    name: str
    description: str
    document_type: str
    chunk_size_tokens: int
    overlap_percent: float
    use_semantic: bool
    dedup_strategy: str
    expected_chunks: int
    expected_behavior: str


@dataclass
class ChunkPipelineResult:
    """Result of a chunk pipeline test execution."""
    test_name: str
    success: bool
    execution_time_ms: float
    chunks_created: int
    total_tokens: int
    overlap_detected: int
    duplicates_removed: int
    silent_failure: bool
    error_message: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)


class ChunkingStage(Stage):
    """
    TRANSFORM stage for document chunking with configurable overlap.
    
    This stage splits documents into chunks with configurable size
    and overlap percentage for RAG pipelines.
    """

    name = "chunking"
    kind = StageKind.TRANSFORM

    def __init__(
        self,
        chunk_size_tokens: int = 512,
        overlap_percent: float = 0.20,
        use_semantic: bool = False,
    ):
        self.chunk_size_tokens = chunk_size_tokens
        self.overlap_percent = overlap_percent
        self.use_semantic = use_semantic
        self.mocks = ChunkOverlapDeduplicationMocks()
        self.execution_metrics = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute chunking with metrics tracking."""
        input_text = ctx.snapshot.input_text or ""
        document_id = ctx.snapshot.metadata.get("document_id", "doc_0")
        
        start_time = time.perf_counter()

        try:
            document = Document(
                document_id=document_id,
                title=f"Test Document {document_id}",
                content=input_text,
            )

            result = self.mocks.create_chunked_document(
                document,
                chunk_size_tokens=self.chunk_size_tokens,
                overlap_percent=self.overlap_percent,
                use_semantic=self.use_semantic,
            )

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            chunks = result["chunks"]
            overlap_count = sum(
                1 for c in chunks if c.get("overlap_with_previous")
            )
            
            metrics = {
                "test_name": self.name,
                "timestamp": datetime.now().isoformat(),
                "chunks_created": len(chunks),
                "total_tokens": result["original_token_count"],
                "overlap_count": overlap_count,
                "dedup_info": result["dedup_info"],
                "execution_time_ms": execution_time_ms,
            }
            self.execution_metrics.append(metrics)

            silent_failure = (
                len(chunks) == 0 and len(input_text) > 0
            ) or result["original_token_count"] > 0 and len(chunks) == 0

            return StageOutput.ok(
                chunks=chunks,
                chunk_count=len(chunks),
                original_token_count=result["original_token_count"],
                dedup_info=result["dedup_info"],
                overlap_count=overlap_count,
                execution_time_ms=execution_time_ms,
                silent_failure=silent_failure,
                config=result["config"],
            )

        except Exception as e:
            logger.error(f"Chunking failed: {e}")
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return StageOutput.fail(
                error=f"Chunking failed: {e}",
                execution_time_ms=execution_time_ms,
            )


class DeduplicationStage(Stage):
    """
    TRANSFORM stage for chunk deduplication.
    
    This stage removes duplicate or near-duplicate chunks
    from the chunking output.
    """

    name = "deduplication"
    kind = StageKind.TRANSFORM

    def __init__(
        self,
        dedup_strategy: str = "exact",
        dedup_threshold: float = 0.85,
    ):
        self.dedup_strategy = dedup_strategy
        self.dedup_threshold = dedup_threshold
        self.mocks = ChunkOverlapDeduplicationMocks(
            ChunkingConfig(dedup_strategy=dedup_strategy, dedup_threshold=dedup_threshold)
        )
        self.deduplicator = self.mocks.deduplicator

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute deduplication on chunks."""
        chunks = ctx.inputs.get_from("chunking", "chunks") or []
        
        start_time = time.perf_counter()

        try:
            chunk_objects = [
                Chunk(
                    chunk_id=c.get("chunk_id", f"chunk_{i}"),
                    document_id=c.get("document_id", "doc_0"),
                    content=c.get("content", ""),
                    start_position=c.get("start_position", 0),
                    end_position=c.get("end_position", 0),
                    chunk_index=c.get("chunk_index", i),
                    total_chunks=c.get("total_chunks", len(chunks)),
                )
                for i, c in enumerate(chunks)
            ]

            deduped_chunks, dedup_info = self.deduplicator.deduplicate(chunk_objects)

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            silent_failure = (
                len(chunks) > 0 and len(deduped_chunks) == 0
            )

            return StageOutput.ok(
                chunks=[
                    {
                        "chunk_id": c.chunk_id,
                        "content": c.content,
                        "chunk_index": c.chunk_index,
                    }
                    for c in deduped_chunks
                ],
                chunk_count=len(deduped_chunks),
                original_chunk_count=len(chunks),
                dedup_info=dedup_info,
                execution_time_ms=execution_time_ms,
                silent_failure=silent_failure,
            )

        except Exception as e:
            logger.error(f"Deduplication failed: {e}")
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return StageOutput.fail(
                error=f"Deduplication failed: {e}",
                execution_time_ms=execution_time_ms,
            )


class ValidationStage(Stage):
    """
    GUARD stage for validating chunking results and detecting failures.
    
    This stage validates chunk integrity, overlap coverage,
    and detects various failure modes including silent failures.
    """

    name = "chunk_validation"
    kind = StageKind.GUARD

    def __init__(
        self,
        expected_min_chunks: int = 1,
        max_chunk_size_tokens: int = 1024,
        validate_overlap: bool = True,
        detect_silent_failures: bool = False,
    ):
        self.expected_min_chunks = expected_min_chunks
        self.max_chunk_size_tokens = max_chunk_size_tokens
        self.validate_overlap = validate_overlap
        self.detect_silent_failures = detect_silent_failures
        self.validation_failures = []
        self.validation_warnings = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Validate chunking results."""
        chunks = ctx.inputs.get_from("deduplication", "chunks") or []
        chunk_count = ctx.inputs.get_from("deduplication", "chunk_count") or 0
        original_count = ctx.inputs.get_from("deduplication", "original_chunk_count") or 0
        dedup_info = ctx.inputs.get_from("deduplication", "dedup_info") or {}
        silent_failure = ctx.inputs.get_from("deduplication", "silent_failure") or False
        overlap_count = ctx.inputs.get_from("chunking", "overlap_count") or 0
        
        validation_passed = True
        validation_errors = []
        validation_warnings = []

        if chunk_count < self.expected_min_chunks:
            if silent_failure and self.detect_silent_failures:
                validation_warnings.append(
                    f"Silent failure: zero chunks returned without error"
                )
            else:
                validation_passed = False
                validation_errors.append(
                    f"Insufficient chunks: expected >= {self.expected_min_chunks}, got {chunk_count}"
                )
                self.validation_failures.append({
                    "type": "insufficient_chunks",
                    "expected": self.expected_min_chunks,
                    "actual": chunk_count,
                })

        if self.validate_overlap and overlap_count == 0 and chunk_count > 1:
            validation_warnings.append(
                f"Expected overlap for {chunk_count} chunks, but none detected"
            )

        if dedup_info.get("removed", 0) > original_count * 0.5:
            validation_warnings.append(
                f"High deduplication rate: {dedup_info['removed']} chunks removed from {original_count}"
            )

        if validation_errors:
            return StageOutput.cancel(
                reason="Validation failed",
                data={
                    "validation_errors": validation_errors,
                    "validation_warnings": validation_warnings,
                    "chunk_count": chunk_count,
                    "dedup_info": dedup_info,
                    "silent_failure": silent_failure,
                },
            )

        return StageOutput.ok(
            validation_passed=True,
            chunk_count=chunk_count,
            dedup_info=dedup_info,
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
        metrics = {
            "test_name": self.test_name,
            "timestamp": datetime.now().isoformat(),
            "chunks": ctx.inputs.get_from("deduplication", "chunk_count") or 0,
            "original_chunks": ctx.inputs.get_from("deduplication", "original_chunk_count") or 0,
            "dedup_removed": ctx.inputs.get_from("deduplication", "dedup_info", {}).get("removed", 0),
            "execution_time_ms": ctx.inputs.get_from("deduplication", "execution_time_ms") or 0,
            "silent_failure": ctx.inputs.get_from("deduplication", "silent_failure") or False,
        }

        self.metrics.append(metrics)

        if self.result_file:
            with open(self.result_file, "a") as f:
                f.write(json.dumps(metrics) + "\n")

        logger.info(f"Test metrics for {self.test_name}: {json.dumps(metrics, indent=2)}")

        return StageOutput.ok(
            metrics_collected=True,
            test_metrics=metrics,
        )


def create_chunk_pipeline(
    chunk_size_tokens: int = 512,
    overlap_percent: float = 0.20,
    use_semantic: bool = False,
    dedup_strategy: str = "exact",
    result_file: Optional[str] = None,
    detect_silent_failures: bool = False,
) -> Pipeline:
    """Create a chunk pipeline with specified configuration."""
    pipeline = Pipeline()

    chunking_stage = ChunkingStage(
        chunk_size_tokens=chunk_size_tokens,
        overlap_percent=overlap_percent,
        use_semantic=use_semantic,
    )

    dedup_stage = DeduplicationStage(dedup_strategy=dedup_strategy)

    validation_stage = ValidationStage(
        expected_min_chunks=1,
        validate_overlap=overlap_percent > 0,
        detect_silent_failures=detect_silent_failures,
    )

    metrics_stage = MetricsCollectionStage(
        test_name=f"chunk_{chunk_size_tokens}_{overlap_percent}_{dedup_strategy}",
        result_file=result_file,
    )

    pipeline = pipeline.with_stage("chunking", chunking_stage, StageKind.TRANSFORM)
    pipeline = pipeline.with_stage(
        "deduplication", dedup_stage, StageKind.TRANSFORM, dependencies=("chunking",)
    )
    pipeline = pipeline.with_stage(
        "chunk_validation", validation_stage, StageKind.GUARD, dependencies=("deduplication",)
    )
    pipeline = pipeline.with_stage(
        "metrics_collection", metrics_stage, StageKind.WORK,
        dependencies=("chunking", "deduplication", "chunk_validation")
    )

    return pipeline


async def run_chunk_test(
    pipeline: Pipeline,
    test_case: ChunkTestCase,
    input_text: str = "",
) -> ChunkPipelineResult:
    """Execute a single chunk pipeline test."""
    test_results["total_tests"] += 1

    start_time = time.perf_counter()

    try:
        snapshot = create_test_snapshot(
            input_text=input_text or _get_default_test_content(),
            metadata={"document_id": test_case.document_type}
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

        output = {}
        for stage_name, stage_result in result.items():
            if stage_name == "deduplication":
                if hasattr(stage_result, "data"):
                    output = stage_result.data or {}
                break

        chunks_created = output.get("chunk_count", 0)
        silent_failure = output.get("silent_failure", False)
        dedup_info = output.get("dedup_info", {})
        overlap_count = 0

        all_completed = all(
            hasattr(r, "status") and r.status.value in ["ok", "cancel"]
            for r in result.values()
        )

        validation_cancelled = False
        for stage_name, stage_result in result.items():
            if stage_name == "chunk_validation":
                if hasattr(stage_result, "status") and stage_result.status.value == "cancel":
                    validation_cancelled = True
                    break

        success = chunks_created >= test_case.expected_chunks and all_completed and not validation_cancelled

        if silent_failure:
            test_results["silent_failures"] += 1

        if success:
            test_results["passed"] += 1
        else:
            test_results["failed"] += 1

        return ChunkPipelineResult(
            test_name=test_case.name,
            success=success,
            execution_time_ms=execution_time_ms,
            chunks_created=chunks_created,
            total_tokens=output.get("original_token_count", 0),
            overlap_detected=overlap_count,
            duplicates_removed=dedup_info.get("removed", 0),
            silent_failure=silent_failure,
            error_message=None,
            metrics={
                "validation_passed": all_completed and not validation_cancelled,
            },
        )

    except Exception as e:
        execution_time_ms = (time.perf_counter() - start_time) * 1000
        test_results["failed"] += 1

        return ChunkPipelineResult(
            test_name=test_case.name,
            success=False,
            execution_time_ms=execution_time_ms,
            chunks_created=0,
            total_tokens=0,
            overlap_detected=0,
            duplicates_removed=0,
            silent_failure=False,
            error_message=str(e),
        )


def _get_default_test_content() -> str:
    """Generate default test content for chunking."""
    sentences = [
        "The quick brown fox jumps over the lazy dog.",
        "Machine learning enables computers to learn from data without explicit programming.",
        "Natural language processing helps machines understand human language.",
        "Vector databases store and retrieve high-dimensional data efficiently.",
        "Retrieval augmented generation combines search with language model generation.",
        "Chunking is essential for breaking down large documents into manageable pieces.",
        "Overlap ensures that context is not lost at chunk boundaries.",
        "Deduplication removes redundant information from search results.",
        "The optimal chunk size depends on the specific use case and data characteristics.",
        "Semantic chunking preserves meaning by splitting at logical boundaries.",
    ]
    return " ".join(sentences * 5)


async def run_baseline_tests(
    result_file: str = "results/enrich009_baseline_results.json",
) -> Dict[str, Any]:
    """Run baseline chunk overlap and deduplication tests."""
    results_dir = Path(result_file).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    test_cases = [
        ChunkTestCase(
            name="baseline_20_overlap",
            description="Baseline with 20% overlap",
            document_type="normal",
            chunk_size_tokens=200,
            overlap_percent=0.20,
            use_semantic=False,
            dedup_strategy="exact",
            expected_chunks=5,
            expected_behavior="All chunks created with 20% overlap",
        ),
        ChunkTestCase(
            name="baseline_no_overlap",
            description="Baseline with 0% overlap (control)",
            document_type="normal",
            chunk_size_tokens=200,
            overlap_percent=0.0,
            use_semantic=False,
            dedup_strategy="exact",
            expected_chunks=4,
            expected_behavior="All chunks created without overlap",
        ),
        ChunkTestCase(
            name="baseline_50_overlap",
            description="Baseline with 50% overlap",
            document_type="normal",
            chunk_size_tokens=200,
            overlap_percent=0.50,
            use_semantic=False,
            dedup_strategy="exact",
            expected_chunks=7,
            expected_behavior="All chunks created with 50% overlap",
        ),
        ChunkTestCase(
            name="semantic_chunking",
            description="Semantic chunking",
            document_type="normal",
            chunk_size_tokens=200,
            overlap_percent=0.20,
            use_semantic=True,
            dedup_strategy="exact",
            expected_chunks=3,
            expected_behavior="Semantic chunks created at sentence boundaries",
        ),
    ]

    all_results = []

    logger.info("=" * 60)
    logger.info("ENRICH-009 Chunk Overlap and Deduplication Baseline Tests")
    logger.info("=" * 60)

    for test_case in test_cases:
        logger.info(f"\nRunning test: {test_case.name}")
        logger.info(f"  Description: {test_case.description}")
        logger.info(f"  Chunk size: {test_case.chunk_size_tokens} tokens")
        logger.info(f"  Overlap: {test_case.overlap_percent * 100}%")

        pipeline = create_chunk_pipeline(
            chunk_size_tokens=test_case.chunk_size_tokens,
            overlap_percent=test_case.overlap_percent,
            use_semantic=test_case.use_semantic,
            dedup_strategy=test_case.dedup_strategy,
            result_file=result_file,
        )

        result = await run_chunk_test(pipeline, test_case)

        all_results.append({
            "test_name": result.test_name,
            "success": result.success,
            "execution_time_ms": result.execution_time_ms,
            "chunks_created": result.chunks_created,
            "total_tokens": result.total_tokens,
            "duplicates_removed": result.duplicates_removed,
            "silent_failure": result.silent_failure,
            "error": result.error_message,
            "metrics": result.metrics,
        })

        logger.info(f"  Result: {'PASS' if result.success else 'FAIL'}")
        logger.info(f"  Chunks: {result.chunks_created}")
        logger.info(f"  Tokens: {result.total_tokens}")
        logger.info(f"  Duplicates removed: {result.duplicates_removed}")
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


async def run_deduplication_tests(
    result_file: str = "results/enrich009_dedup_results.json",
) -> Dict[str, Any]:
    """Run deduplication-specific tests."""
    results_dir = Path(result_file).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    mocks = ChunkOverlapDeduplicationMocks()
    repetitive_doc = mocks.create_test_document("test_repetitive", "repetitive")

    test_cases = [
        ChunkTestCase(
            name="exact_dedupe",
            description="Exact match deduplication",
            document_type="repetitive",
            chunk_size_tokens=100,
            overlap_percent=0.0,
            use_semantic=False,
            dedup_strategy="exact",
            expected_chunks=5,
            expected_behavior="Exact duplicates removed",
        ),
        ChunkTestCase(
            name="fuzzy_dedupe",
            description="Fuzzy match deduplication",
            document_type="repetitive",
            chunk_size_tokens=100,
            overlap_percent=0.0,
            use_semantic=False,
            dedup_strategy="fuzzy",
            expected_chunks=3,
            expected_behavior="Near-duplicates removed",
        ),
    ]

    all_results = []

    logger.info("=" * 60)
    logger.info("ENRICH-009 Deduplication Tests")
    logger.info("=" * 60)

    for test_case in test_cases:
        logger.info(f"\nRunning test: {test_case.name}")
        logger.info(f"  Description: {test_case.description}")
        logger.info(f"  Strategy: {test_case.dedup_strategy}")

        pipeline = create_chunk_pipeline(
            chunk_size_tokens=test_case.chunk_size_tokens,
            overlap_percent=test_case.overlap_percent,
            use_semantic=test_case.use_semantic,
            dedup_strategy=test_case.dedup_strategy,
            result_file=result_file,
        )

        input_text = repetitive_doc.content
        result = await run_chunk_test(pipeline, test_case, input_text)

        all_results.append({
            "test_name": result.test_name,
            "success": result.success,
            "execution_time_ms": result.execution_time_ms,
            "chunks_created": result.chunks_created,
            "duplicates_removed": result.duplicates_removed,
            "silent_failure": result.silent_failure,
            "error": result.error_message,
        })

        logger.info(f"  Result: {'PASS' if result.success else 'FAIL'}")
        logger.info(f"  Chunks: {result.chunks_created}")
        logger.info(f"  Duplicates removed: {result.duplicates_removed}")

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


async def run_edge_case_tests(
    result_file: str = "results/enrich009_edge_cases.json",
) -> Dict[str, Any]:
    """Run edge case tests for chunking."""
    results_dir = Path(result_file).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    test_cases = [
        ChunkTestCase(
            name="empty_content",
            description="Empty content handling",
            document_type="empty",
            chunk_size_tokens=100,
            overlap_percent=0.20,
            use_semantic=False,
            dedup_strategy="exact",
            expected_chunks=0,
            expected_behavior="No chunks from empty content",
        ),
        ChunkTestCase(
            name="tiny_content",
            description="Content smaller than chunk size",
            document_type="tiny",
            chunk_size_tokens=500,
            overlap_percent=0.20,
            use_semantic=False,
            dedup_strategy="exact",
            expected_chunks=1,
            expected_behavior="Single chunk for small content",
        ),
        ChunkTestCase(
            name="very_small_chunks",
            description="Minimum chunk size enforcement",
            document_type="normal",
            chunk_size_tokens=50,
            overlap_percent=0.10,
            use_semantic=False,
            dedup_strategy="exact",
            expected_chunks=15,
            expected_behavior="Small chunks created with min size",
        ),
    ]

    all_results = []

    logger.info("=" * 60)
    logger.info("ENRICH-009 Edge Case Tests")
    logger.info("=" * 60)

    for test_case in test_cases:
        logger.info(f"\nRunning test: {test_case.name}")
        logger.info(f"  Description: {test_case.description}")

        pipeline = create_chunk_pipeline(
            chunk_size_tokens=test_case.chunk_size_tokens,
            overlap_percent=test_case.overlap_percent,
            use_semantic=test_case.use_semantic,
            dedup_strategy=test_case.dedup_strategy,
            result_file=result_file,
        )

        input_text = _get_test_content_for_case(test_case)
        result = await run_chunk_test(pipeline, test_case, input_text)

        all_results.append({
            "test_name": result.test_name,
            "success": result.success,
            "execution_time_ms": result.execution_time_ms,
            "chunks_created": result.chunks_created,
            "expected_chunks": test_case.expected_chunks,
            "silent_failure": result.silent_failure,
        })

        logger.info(f"  Result: {'PASS' if result.success else 'FAIL'}")
        logger.info(f"  Chunks: {result.chunks_created} (expected: {test_case.expected_chunks})")

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


def _get_test_content_for_case(test_case: ChunkTestCase) -> str:
    """Get test content based on test case type."""
    if test_case.document_type == "empty":
        return ""
    elif test_case.document_type == "tiny":
        return "This is a very short document."
    else:
        return _get_default_test_content()


async def run_all_enrich009_tests(
    base_dir: str = "results",
) -> Dict[str, Any]:
    """Run all ENRICH-009 chunk overlap and deduplication tests."""
    base_path = Path(base_dir) / "enrich009"
    base_path.mkdir(parents=True, exist_ok=True)

    (base_path / "logs").mkdir(exist_ok=True)

    baseline_results = await run_baseline_tests(
        result_file=str(base_path / "baseline_results.json"),
    )

    dedup_results = await run_deduplication_tests(
        result_file=str(base_path / "dedup_results.json"),
    )

    edge_case_results = await run_edge_case_tests(
        result_file=str(base_path / "edge_case_results.json"),
    )

    return {
        "baseline": baseline_results,
        "deduplication": dedup_results,
        "edge_cases": edge_case_results,
        "output_dir": str(base_path),
    }


if __name__ == "__main__":
    asyncio.run(run_all_enrich009_tests())
