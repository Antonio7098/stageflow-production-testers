#!/usr/bin/env python
"""
Simple test runner for ENRICH-009 - Bypasses Stageflow to test mock logic directly.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mocks.chunk_overlap_deduplication_mocks import (
    ChunkOverlapDeduplicationMocks,
    ChunkingConfig,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_mock_chunking():
    """Test the mock chunking logic directly."""
    logger.info("=" * 60)
    logger.info("ENRICH-009 Mock Chunking Tests")
    logger.info("=" * 60)

    mocks = ChunkOverlapDeduplicationMocks()
    results = []

    test_cases = [
        ("baseline_20_overlap", 200, 0.20, False, "normal", 5),
        ("baseline_no_overlap", 200, 0.0, False, "normal", 4),
        ("baseline_50_overlap", 200, 0.50, False, "normal", 7),
        ("semantic_chunking", 200, 0.20, True, "normal", 3),
        ("tiny_content", 500, 0.20, False, "tiny", 1),
        ("empty_content", 100, 0.20, False, "empty", 0),
    ]

    for test_name, chunk_size, overlap, use_semantic, doc_type, expected_min in test_cases:
        logger.info(f"\nTest: {test_name}")
        logger.info(f"  Chunk size: {chunk_size}, Overlap: {overlap * 100}%")

        if doc_type == "empty":
            content = ""
        elif doc_type == "tiny":
            content = "This is a very short document."
        else:
            content = _generate_test_content()

        doc = mocks.create_test_document(f"doc_{test_name}", doc_type)
        doc.content = content

        result = mocks.create_chunked_document(
            doc,
            chunk_size_tokens=chunk_size,
            overlap_percent=overlap,
            use_semantic=use_semantic,
        )

        success = result["chunk_count"] >= expected_min
        overlap_count = sum(1 for c in result["chunks"] if c.get("overlap_with_previous"))

        logger.info(f"  Result: {'PASS' if success else 'FAIL'}")
        logger.info(f"  Chunks: {result['chunk_count']} (expected >= {expected_min})")
        logger.info(f"  Tokens: {result['original_token_count']}")
        logger.info(f"  Overlap count: {overlap_count}")
        logger.info(f"  Dedupe: {result['dedup_info']}")

        results.append({
            "test_name": test_name,
            "success": success,
            "chunks_created": result["chunk_count"],
            "expected_min": expected_min,
            "total_tokens": result["original_token_count"],
            "overlap_count": overlap_count,
            "dedup_info": result["dedup_info"],
        })

    return results


def test_deduplication():
    """Test deduplication logic."""
    logger.info("\n" + "=" * 60)
    logger.info("ENRICH-009 Deduplication Tests")
    logger.info("=" * 60)

    mocks = ChunkOverlapDeduplicationMocks()
    results = []

    doc = mocks.create_test_document("test_repetitive", "repetitive")
    logger.info(f"Generated repetitive document with {len(doc.content)} chars")

    for strategy in ["exact", "fuzzy"]:
        logger.info(f"\nTest: {strategy}_dedup")
        logger.info(f"  Strategy: {strategy}")

        config = ChunkingConfig(dedup_strategy=strategy)
        test_mocks = ChunkOverlapDeduplicationMocks(config)

        result = test_mocks.create_chunked_document(doc, chunk_size_tokens=100)

        logger.info(f"  Original chunks: {result['chunk_count']}")
        logger.info(f"  Duplicates removed: {result['dedup_info'].get('removed', 0)}")
        logger.info(f"  Final chunks: {result['chunk_count']}")

        results.append({
            "test_name": f"{strategy}_dedup",
            "strategy": strategy,
            "original_count": result["chunk_count"],
            "removed": result["dedup_info"].get("removed", 0),
            "success": result['dedup_info'].get('removed', 0) > 0,
        })

    return results


def test_performance():
    """Test chunking performance."""
    logger.info("\n" + "=" * 60)
    logger.info("ENRICH-009 Performance Tests")
    logger.info("=" * 60)

    import time

    mocks = ChunkOverlapDeduplicationMocks()
    content = _generate_test_content() * 10

    iterations = 100
    times = []

    logger.info(f"Testing {iterations} iterations with {len(content)} chars")

    for i in range(iterations):
        start = time.perf_counter()
        doc = mocks.create_test_document(f"perf_{i}", "normal")
        doc.content = content
        result = mocks.create_chunked_document(doc, chunk_size_tokens=200)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

    avg_time = sum(times) / len(times)
    p95_time = sorted(times)[int(len(times) * 0.95)]
    throughput = iterations / (sum(times) / 1000)

    logger.info(f"  Avg time: {avg_time:.2f}ms")
    logger.info(f"  P95 time: {p95_time:.2f}ms")
    logger.info(f"  Throughput: {throughput:.2f} ops/sec")

    return {
        "iterations": iterations,
        "avg_time_ms": avg_time,
        "p95_time_ms": p95_time,
        "throughput": throughput,
    }


def _generate_test_content():
    """Generate test content."""
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


def main():
    """Run all tests and save results."""
    output_dir = Path("results/enrich009")
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline_results = test_mock_chunking()
    dedup_results = test_deduplication()
    perf_results = test_performance()

    all_results = {
        "timestamp": datetime.now().isoformat(),
        "baseline": baseline_results,
        "deduplication": dedup_results,
        "performance": perf_results,
        "summary": {
            "total_tests": len(baseline_results) + len(dedup_results),
            "passed": sum(1 for r in baseline_results if r["success"]) + sum(1 for r in dedup_results if r["success"]),
            "failed": sum(1 for r in baseline_results if not r["success"]) + sum(1 for r in dedup_results if not r["success"]),
        }
    }

    result_file = output_dir / "test_results.json"
    with open(result_file, "w") as f:
        json.dump(all_results, f, indent=2)

    logger.info("\n" + "=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)
    logger.info(f"Total Tests: {all_results['summary']['total_tests']}")
    logger.info(f"Passed: {all_results['summary']['passed']}")
    logger.info(f"Failed: {all_results['summary']['failed']}")
    logger.info(f"Results saved to: {result_file}")

    return all_results


if __name__ == "__main__":
    main()
