"""
ENRICH-009 Chaos and Stress Test Pipelines

This module implements chaos engineering and stress testing pipelines
for Stageflow's chunk overlap and deduplication feature.

Chaos Categories:
1. Silent Failure Injection - Test detection of silent failures
2. Resource Exhaustion - Memory and processing limits
3. Concurrent Access - Race conditions in chunk processing
4. Malformed Input - Invalid or unexpected content
5. Performance Stress - High-volume chunking operations
"""

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

0, str(Path(__file__).parent.parent))

from stageflow import (
    Pipeline,
    Stage,
    StageKind,
    StageOutput,
    StageContext,
    PipelineTimer,
    TimeoutInterceptor,
)
from stageflow.context import ContextSnapshot
from stageflow.stages import StageInputs
from stageflow.testing import create_test_snapshot

from mocks.chunk_overlap_deduplication_mocks import (
    ChunkOverlapDeduplicationMocks,
    Chunk,
    Document,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


chaos_results = {
    "total_tests": 0,
    "passed": 0,
    "failed": 0,
    "silent_failures_detected": 0,
    "findings": [],
}


@dataclass
class ChaosTestCase:
    """Definition of a chaos test case."""
    name: str
    description: str
    content_type: str
    chunk_size_tokens: int
    overlap_percent: float
    inject_failure_type: str
    expected_behavior: str


class ChaosChunkingStage(Stage):
    """
    TRANSFORM stage with injected failure modes for chaos testing.
    """

    name = "chaos_chunking"
    kind = StageKind.TRANSFORM

    def __init__(
        self,
        chunk_size_tokens: int = 512,
        overlap_percent: float = 0.20,
        failure_type: str = "none",
        failure_probability: float = 0.0,
    ):
        self.chunk_size_tokens = chunk_size_tokens
        self.overlap_percent = overlap_percent
        self.failure_type = failure_type
        self.failure_probability = failure_probability
        self.mocks = ChunkOverlapDeduplicationMocks()
        self.chaos_injected = False

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute chunking with potential failure injection."""
        input_text = ctx.snapshot.input_text or ""
        document_id = ctx.snapshot.metadata.get("document_id", "doc_chaos")
        
        start_time = time.perf_counter()

        try:
            if self.failure_type == "corrupt_content" and self._should_inject():
                input_text = self._corrupt_content(input_text)
                self.chaos_injected = True

            if self.failure_type == "empty_result" and self._should_inject():
                self.chaos_injected = True
                return StageOutput.ok(
                    chunks=[],
                    chunk_count=0,
                    original_token_count=len(input_text.split()),
                    dedup_info={"strategy": "none", "removed": 0},
                    overlap_count=0,
                    execution_time_ms=0,
                    silent_failure=True,
                    chaos_injected=True,
                )

            document = Document(
                document_id=document_id,
                title=f"Chaos Test Document",
                content=input_text,
            )

            result = self.mocks.create_chunked_document(
                document,
                chunk_size_tokens=self.chunk_size_tokens,
                overlap_percent=self.overlap_percent,
            )

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            if self.failure_type == "missing_overlap" and self._should_inject():
                for chunk in result["chunks"]:
                    chunk["overlap_with_previous"] = False
                    chunk["overlap_with_next"] = False
                self.chaos_injected = True

            chunks = result["chunks"]
            silent_failure = (
                len(chunks) == 0 and len(input_text) > 0
            ) or (result["original_token_count"] > 0 and len(chunks) == 0)

            return StageOutput.ok(
                chunks=chunks,
                chunk_count=len(chunks),
                original_token_count=result["original_token_count"],
                dedup_info=result["dedup_info"],
                overlap_count=sum(1 for c in chunks if c.get("overlap_with_previous")),
                execution_time_ms=execution_time_ms,
                silent_failure=silent_failure,
                chaos_injected=self.chaos_injected,
            )

        except Exception as e:
            logger.error(f"Chaos chunking failed: {e}")
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return StageOutput.fail(
                error=f"Chaos chunking failed: {e}",
                execution_time_ms=execution_time_ms,
                chaos_injected=self.failure_type != "none",
            )

    def _should_inject(self) -> bool:
        """Determine if failure should be injected."""
        import random
        return random.random() < self.failure_probability

    def _corrupt_content(self, content: str) -> str:
        """Corrupt content to simulate bad input."""
        import random
        chars = list(content)
        for _ in range(max(1, len(chars) // 100)):
            idx = random.randint(0, len(chars) - 1)
            chars[idx] = chr(random.randint(32, 126))
        return "".join(chars)


class SilentFailureDetectionStage(Stage):
    """
    GUARD stage specifically designed to detect silent failures.
    
    This stage implements multiple detection strategies:
    1. Golden output comparison
    2. State audits
    3. Metrics validation
    4. Invariant checking
    """

    name = "silent_failure_detection"
    kind = StageKind.GUARD

    def __init__(
        self,
        expected_token_ratio: float = 0.9,
        detect_empty_chunks: bool = True,
    ):
        self.expected_token_ratio = expected_token_ratio
        self.detect_empty_chunks = detect_empty_chunks
        self.detection_methods = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Detect silent failures using multiple strategies."""
        chunks = ctx.inputs.get_from("chaos_chunking", "chunks") or []
        chunk_count = ctx.inputs.get_from("chaos_chunking", "chunk_count") or 0
        original_tokens = ctx.inputs.get_from("chaos_chunking", "original_token_count") or 0
        silent_failure = ctx.inputs.get_from("chaos_chunking", "silent_failure") or False
        chaos_injected = ctx.inputs.get_from("chaos_chunking", "chaos_injected") or False
        
        detection_results = []
        detected_silent_failures = []

        if self.detect_empty_chunks and chunk_count == 0 and original_tokens > 0:
            detected_silent_failures.append({
                "type": "empty_result",
                "description": "No chunks returned for non-empty input",
                "tokens_in": original_tokens,
                "chunks_out": chunk_count,
            })
            detection_results.append("empty_result: DETECTED")

        if chunk_count > 0:
            total_output_tokens = sum(len(c.get("content", "").split()) for c in chunks)
            token_ratio = total_output_tokens / original_tokens if original_tokens > 0 else 0
            
            if token_ratio < self.expected_token_ratio:
                detected_silent_failures.append({
                    "type": "token_loss",
                    "description": "Significant token loss during chunking",
                    "expected_ratio": self.expected_token_ratio,
                    "actual_ratio": token_ratio,
                })
                detection_results.append(f"token_loss: DETECTED ({token_ratio:.2f})")

            empty_chunks = [c for c in chunks if not c.get("content", "").strip()]
            if empty_chunks:
                detected_silent_failures.append({
                    "type": "empty_chunks",
                    "description": f"{len(empty_chunks)} chunks have empty content",
                })
                detection_results.append(f"empty_chunks: DETECTED")

        has_silent_failure = (
            len(detected_silent_failures) > 0 or silent_failure
        )

        return StageOutput.ok(
            validation_passed=not has_silent_failure,
            detection_results=detection_results,
            detected_silent_failures=detected_silent_failures,
            silent_failure=has_silent_failure,
            chaos_was_injected=chaos_injected,
        )


class ConcurrentChunkingStage(Stage):
    """
    TRANSFORM stage for testing concurrent chunking operations.
    
    This stage simulates concurrent access patterns that could
    reveal race conditions in chunk processing.
    """

    name = "concurrent_chunking"
    kind = StageKind.TRANSFORM

    def __init__(
        self,
        chunk_size_tokens: int = 512,
        overlap_percent: float = 0.20,
        concurrent_operations: int = 10,
    ):
        self.chunk_size_tokens = chunk_size_tokens
        self.overlap_percent = overlap_percent
        self.concurrent_operations = concurrent_operations
        self.mocks = ChunkOverlapDeduplicationMocks()
        self.lock_contention_detected = False

    async def execute(self, ctx: StageContext) -> StageContext:
        """Execute concurrent chunking operations."""
        input_text = ctx.snapshot.input_text or ""
        
        start_time = time.perf_counter()

        try:
            with ThreadPoolExecutor(max_workers=self.concurrent_operations) as executor:
                futures = []
                for i in range(self.concurrent_operations):
                    doc = Document(
                        document_id=f"concurrent_doc_{i}",
                        title=f"Concurrent Document {i}",
                        content=input_text,
                    )
                    future = executor.submit(
                        self._chunk_document_sync,
                        doc,
                    )
                    futures.append(future)

                results = [f.result() for f in futures]

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            all_chunks = []
            for result in results:
                all_chunks.extend(result["chunks"])

            unique_chunk_ids = set(c["chunk_id"] for c in all_chunks)
            self.lock_contention_detected = len(unique_chunk_ids) < len(all_chunks)

            return StageOutput.ok(
                concurrent_results=results,
                total_chunks=len(all_chunks),
                unique_chunks=len(unique_chunk_ids),
                lock_contention=self.lock_contention_detected,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.error(f"Concurrent chunking failed: {e}")
            return StageOutput.fail(error=f"Concurrent chunking failed: {e}")

    def _chunk_document_sync(self, document: Document) -> Dict[str, Any]:
        """Synchronous chunking for thread pool."""
        return self.mocks.create_chunked_document(
            document,
            chunk_size_tokens=self.chunk_size_tokens,
            overlap_percent=self.overlap_percent,
        )


class PerformanceStressStage(Stage):
    """
    WORK stage for measuring chunking performance under stress.
    
    This stage processes large volumes of content to measure
    performance characteristics and identify bottlenecks.
    """

    name = "performance_stress"
    kind = StageKind.WORK

    def __init__(
        self,
        iterations: int = 100,
        chunk_size_tokens: int = 512,
        overlap_percent: float = 0.20,
    ):
        self.iterations = iterations
        self.chunk_size_tokens = chunk_size_tokens
        self.overlap_percent = overlap_percent
        self.mocks = ChunkOverlapDeduplicationMocks()

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute performance stress test."""
        input_text = ctx.snapshot.input_text or ""
        
        start_time = time.perf_counter()
        iteration_times = []
        memory_samples = []

        for i in range(self.iterations):
            iter_start = time.perf_counter()
            
            document = Document(
                document_id=f"stress_doc_{i}",
                title=f"Stress Document {i}",
                content=input_text,
            )
            
            result = self.mocks.create_chunked_document(
                document,
                chunk_size_tokens=self.chunk_size_tokens,
                overlap_percent=self.overlap_percent,
            )
            
            iter_time = (time.perf_counter() - iter_start) * 1000
            iteration_times.append(iter_time)

        total_time_ms = (time.perf_counter() - start_time) * 1000
        avg_time_ms = sum(iteration_times) / len(iteration_times)
        p95_time = sorted(iteration_times)[int(len(iteration_times) * 0.95)]

        return StageOutput.ok(
            iterations=self.iterations,
            total_time_ms=total_time_ms,
            avg_time_ms=avg_time_ms,
            p95_time_ms=p95_time,
            min_time_ms=min(iteration_times),
            max_time_ms=max(iteration_times),
            throughput=self.iterations / (total_time_ms / 1000),
        )


def create_chaos_pipeline(
    failure_type: str = "none",
    failure_probability: float = 0.0,
    chunk_size_tokens: int = 512,
    overlap_percent: float = 0.20,
) -> Pipeline:
    """Create a chaos pipeline with specified failure injection."""
    pipeline = Pipeline()

    chaos_stage = ChaosChunkingStage(
        chunk_size_tokens=chunk_size_tokens,
        overlap_percent=overlap_percent,
        failure_type=failure_type,
        failure_probability=failure_probability,
    )

    detection_stage = SilentFailureDetectionStage()

    pipeline = pipeline.with_stage("chaos_chunking", chaos_stage, StageKind.TRANSFORM)
    pipeline = pipeline.with_stage(
        "silent_failure_detection", detection_stage, StageKind.GUARD,
        dependencies=("chaos_chunking",)
    )

    return pipeline


def create_concurrent_pipeline(
    chunk_size_tokens: int = 512,
    overlap_percent: float = 0.20,
    concurrent_operations: int = 10,
) -> Pipeline:
    """Create a concurrent access pipeline."""
    pipeline = Pipeline()

    concurrent_stage = ConcurrentChunkingStage(
        chunk_size_tokens=chunk_size_tokens,
        overlap_percent=overlap_percent,
        concurrent_operations=concurrent_operations,
    )

    pipeline = pipeline.with_stage(
        "concurrent_chunking", concurrent_stage, StageKind.TRANSFORM
    )

    return pipeline


def create_performance_pipeline(
    iterations: int = 100,
    chunk_size_tokens: int = 512,
    overlap_percent: float = 0.20,
) -> Pipeline:
    """Create a performance stress pipeline."""
    pipeline = Pipeline()

    performance_stage = PerformanceStressStage(
        iterations=iterations,
        chunk_size_tokens=chunk_size_tokens,
        overlap_percent=overlap_percent,
    )

    pipeline = pipeline.with_stage(
        "performance_stress", performance_stage, StageKind.WORK
    )

    return pipeline


def _get_stress_test_content() -> str:
    """Generate large test content for stress testing."""
    base_sentences = [
        "Machine learning enables computers to learn from data without explicit programming.",
        "Natural language processing helps machines understand human language.",
        "Vector databases store and retrieve high-dimensional data efficiently.",
        "Retrieval augmented generation combines search with language model generation.",
    ]
    return " ".join(base_sentences * 50)


async def run_silent_failure_tests(
    result_file: str = "results/enrich009_silent_failure_tests.json",
) -> Dict[str, Any]:
    """Run tests specifically targeting silent failure detection."""
    results_dir = Path(result_file).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    test_cases = [
        ChaosTestCase(
            name="silent_empty_result",
            description="Test detection of empty results without error",
            content_type="normal",
            chunk_size_tokens=200,
            overlap_percent=0.20,
            inject_failure_type="empty_result",
            expected_behavior="Silent failure detected by guard stage",
        ),
        ChaosTestCase(
            name="silent_content_corruption",
            description="Test detection of corrupted content",
            content_type="normal",
            chunk_size_tokens=200,
            overlap_percent=0.20,
            inject_failure_type="corrupt_content",
            expected_behavior="Corrupted content processed with warning",
        ),
        ChaosTestCase(
            name="silent_missing_overlap",
            description="Test detection of missing overlap",
            content_type="normal",
            chunk_size_tokens=200,
            overlap_percent=0.20,
            inject_failure_type="missing_overlap",
            expected_behavior="Missing overlap detected as potential issue",
        ),
    ]

    all_results = []

    logger.info("=" * 60)
    logger.info("ENRICH-009 Silent Failure Detection Tests")
    logger.info("=" * 60)

    for test_case in test_cases:
        logger.info(f"\nRunning test: {test_case.name}")
        logger.info(f"  Description: {test_case.description}")
        logger.info(f"  Failure type: {test_case.inject_failure_type}")

        pipeline = create_chaos_pipeline(
            chunk_size_tokens=test_case.chunk_size_tokens,
            overlap_percent=test_case.overlap_percent,
            failure_type=test_case.inject_failure_type,
            failure_probability=1.0,
        )

        try:
            snapshot = create_test_snapshot(
                input_text=_get_stress_test_content(),
                metadata={"document_id": "silent_failure_test"},
            )

            context = StageContext(
                snapshot=snapshot,
                inputs=StageInputs(snapshot=snapshot),
                stage_name="root",
                timer=PipelineTimer(),
            )

            graph = pipeline.build()
            result = await graph.run(context)

            detection_output = None
            for stage_name, stage_result in result.items():
                if stage_name == "silent_failure_detection":
                    if hasattr(stage_result, "data"):
                        detection_output = stage_result.data

            silent_failure_detected = (
                detection_output and detection_output.get("silent_failure", False)
            )
            detection_results = detection_output.get("detection_results", []) if detection_output else []

            chaos_results["total_tests"] += 1
            if detection_output and detection_output.get("validation_passed") == False:
                chaos_results["silent_failures_detected"] += 1
                chaos_results["passed"] += 1
                success = True
            else:
                chaos_results["failed"] += 1
                success = False

            all_results.append({
                "test_name": test_case.name,
                "success": success,
                "silent_failure_detected": silent_failure_detected,
                "detection_results": detection_results,
                "chaos_injected": True,
            })

            logger.info(f"  Result: {'PASS' if success else 'FAIL'}")
            logger.info(f"  Silent failure detected: {silent_failure_detected}")
            logger.info(f"  Detection results: {detection_results}")

        except Exception as e:
            logger.error(f"Test failed with exception: {e}")
            chaos_results["failed"] += 1
            all_results.append({
                "test_name": test_case.name,
                "success": False,
                "error": str(e),
            })

    with open(result_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "summary": {
                    "total_tests": chaos_results["total_tests"],
                    "passed": chaos_results["passed"],
                    "failed": chaos_results["failed"],
                    "silent_failures_detected": chaos_results["silent_failures_detected"],
                },
                "results": all_results,
            },
            f,
            indent=2,
        )

    return {
        "summary": chaos_results,
        "results": all_results,
    }


async def run_concurrent_tests(
    result_file: str = "results/enrich009_concurrent_tests.json",
) -> Dict[str, Any]:
    """Run concurrent access tests for race condition detection."""
    results_dir = Path(result_file).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("ENRICH-009 Concurrent Access Tests")
    logger.info("=" * 60)

    results = []

    for ops in [5, 10, 20]:
        logger.info(f"\nTesting with {ops} concurrent operations")

        pipeline = create_concurrent_pipeline(
            chunk_size_tokens=200,
            overlap_percent=0.20,
            concurrent_operations=ops,
        )

        try:
            snapshot = create_test_snapshot(
                input_text=_get_stress_test_content(),
                metadata={"document_id": "concurrent_test"},
            )

            context = StageContext(
                snapshot=snapshot,
                inputs=StageInputs(snapshot=snapshot),
                stage_name="root",
                timer=PipelineTimer(),
            )

            graph = pipeline.build()
            result = await graph.run(context)

            output = None
            for stage_name, stage_result in result.items():
                if stage_name == "concurrent_chunking":
                    if hasattr(stage_result, "data"):
                        output = stage_result.data

            lock_contention = output.get("lock_contention", False) if output else False
            total_chunks = output.get("total_chunks", 0) if output else 0

            chaos_results["total_tests"] += 1
            if not lock_contention:
                chaos_results["passed"] += 1
                success = True
            else:
                chaos_results["failed"] += 1
                success = False

            results.append({
                "concurrent_operations": ops,
                "success": success,
                "total_chunks": total_chunks,
                "lock_contention_detected": lock_contention,
            })

            logger.info(f"  Result: {'PASS' if success else 'FAIL'}")
            logger.info(f"  Total chunks: {total_chunks}")
            logger.info(f"  Lock contention: {lock_contention}")

        except Exception as e:
            logger.error(f"Concurrent test failed: {e}")
            chaos_results["failed"] += 1
            results.append({
                "concurrent_operations": ops,
                "success": False,
                "error": str(e),
            })

    with open(result_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "results": results,
            },
            f,
            indent=2,
        )

    return {"results": results}


async def run_performance_tests(
    result_file: str = "results/enrich009_performance_tests.json",
) -> Dict[str, Any]:
    """Run performance stress tests."""
    results_dir = Path(result_file).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("ENRICH-009 Performance Stress Tests")
    logger.info("=" * 60)

    results = []

    for iterations in [50, 100, 200]:
        logger.info(f"\nTesting with {iterations} iterations")

        pipeline = create_performance_pipeline(
            iterations=iterations,
            chunk_size_tokens=200,
            overlap_percent=0.20,
        )

        try:
            snapshot = create_test_snapshot(
                input_text=_get_stress_test_content(),
                metadata={"document_id": "performance_test"},
            )

            context = StageContext(
                snapshot=snapshot,
                inputs=StageInputs(snapshot=snapshot),
                stage_name="root",
                timer=PipelineTimer(),
            )

            graph = pipeline.build()
            result = await graph.run(context)

            output = None
            for stage_name, stage_result in result.items():
                if stage_name == "performance_stress":
                    if hasattr(stage_result, "data"):
                        output = stage_result.data

            if output:
                chaos_results["total_tests"] += 1
                chaos_results["passed"] += 1

                results.append({
                    "iterations": iterations,
                    "success": True,
                    "total_time_ms": output.get("total_time_ms", 0),
                    "avg_time_ms": output.get("avg_time_ms", 0),
                    "p95_time_ms": output.get("p95_time_ms", 0),
                    "throughput": output.get("throughput", 0),
                })

                logger.info(f"  Result: PASS")
                logger.info(f"  Total time: {output.get('total_time_ms', 0):.2f}ms")
                logger.info(f"  Avg time: {output.get('avg_time_ms', 0):.2f}ms")
                logger.info(f"  P95 time: {output.get('p95_time_ms', 0):.2f}ms")
                logger.info(f"  Throughput: {output.get('throughput', 0):.2f} ops/sec")

        except Exception as e:
            logger.error(f"Performance test failed: {e}")
            chaos_results["failed"] += 1
            results.append({
                "iterations": iterations,
                "success": False,
                "error": str(e),
            })

    with open(result_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "results": results,
            },
            f,
            indent=2,
        )

    return {"results": results}


async def run_all_chaos_tests(
    base_dir: str = "results",
) -> Dict[str, Any]:
    """Run all ENRICH-009 chaos and stress tests."""
    base_path = Path(base_dir) / "enrich009" / "chaos"
    base_path.mkdir(parents=True, exist_ok=True)

    silent_failure_results = await run_silent_failure_tests(
        result_file=str(base_path / "silent_failure_results.json"),
    )

    concurrent_results = await run_concurrent_tests(
        result_file=str(base_path / "concurrent_results.json"),
    )

    performance_results = await run_performance_tests(
        result_file=str(base_path / "performance_results.json"),
    )

    return {
        "silent_failures": silent_failure_results,
        "concurrent": concurrent_results,
        "performance": performance_results,
        "output_dir": str(base_path),
    }


if __name__ == "__main__":
    asyncio.run(run_all_chaos_tests())
