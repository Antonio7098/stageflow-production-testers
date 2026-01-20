"""
Stress Pipeline for Retrieval Latency Testing

This pipeline tests retrieval performance under concurrent load.
"""

import asyncio
import json
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow import Pipeline, StageKind
from pipelines.test_utils import create_stage_context

from mocks.services.mock_vector_db import MockVectorDatabase, VectorDBConfig, FailureMode
from mocks.services.enrich_stages import RetrievalEnrichStage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StressPipeline:
    """
    Stress test pipeline for retrieval under concurrent load.
    
    Tests:
    - High concurrency retrieval requests
    - Latency degradation under load
    - Connection pool behavior
    - Cache effectiveness under load
    """
    
    def __init__(self, results_dir: str = "results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.results = []
    
    def _create_vector_db(self, config: VectorDBConfig) -> MockVectorDatabase:
        """Create a configured vector database."""
        return MockVectorDatabase(config)
    
    async def _run_concurrent_batch(
        self,
        vector_db: MockVectorDatabase,
        queries: List[Dict[str, Any]],
        concurrency: int,
    ) -> Dict[str, Any]:
        """
        Run a batch of queries with specified concurrency.
        
        Args:
            vector_db: Vector database to query
            queries: Queries to execute
            concurrency: Maximum concurrent requests
            
        Returns:
            Batch results including latency metrics
        """
        stage = RetrievalEnrichStage(vector_db=vector_db, top_k=5)
        pipeline = Pipeline()
        pipeline = pipeline.with_stage("retrieval", stage, StageKind.ENRICH)
        graph = pipeline.build()
        
        semaphore = asyncio.Semaphore(concurrency)
        
        async def run_query(query: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                ctx = create_stage_context(
                    query["text"],
                    user_id=f"user_{random.randint(1, 100)}",
                    session_id=f"stress_test_{int(time.time())}",
                )
                
                start_time = time.perf_counter()
                try:
                    result = await graph.run(ctx)
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    
                    stage_output = result.get("retrieval")
                    return {
                        "query_id": query["id"],
                        "success": stage_output and stage_output.status.value == "ok",
                        "latency_ms": elapsed_ms,
                        "cache_hit": stage_output.data.get("cache_hit", False) if stage_output else False,
                        "document_count": stage_output.data.get("document_count", 0) if stage_output else 0,
                    }
                except Exception as e:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    return {
                        "query_id": query["id"],
                        "success": False,
                        "latency_ms": elapsed_ms,
                        "error": str(e)[:100],
                    }
        
        tasks = [run_query(q) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            "concurrency": concurrency,
            "query_count": len(queries),
            "results": [r if isinstance(r, dict) else {"error": str(r)} for r in results],
        }
    
    async def run_concurrency_ramp_test(
        self,
        base_queries: List[Dict[str, Any]],
        concurrency_levels: List[int] = [1, 5, 10, 25, 50, 100],
    ) -> List[Dict[str, Any]]:
        """
        Run tests with increasing concurrency levels.
        
        Args:
            base_queries: Base set of queries to use
            concurrency_levels: List of concurrency levels to test
            
        Returns:
            List of results for each concurrency level
        """
        all_results = []
        
        for concurrency in concurrency_levels:
            logger.info(f"Testing concurrency level: {concurrency}")
            
            vector_db = self._create_vector_db(VectorDBConfig(
                base_latency_ms=20.0,
                latency_variance_ms=5.0,
                max_concurrent_connections=concurrency,
                connection_acquire_timeout_ms=5000,
            ))
            
            batch_results = await self._run_concurrent_batch(
                vector_db=vector_db,
                queries=random.sample(base_queries, min(50, len(base_queries))),
                concurrency=concurrency,
            )
            
            latencies = [
                r["latency_ms"] for r in batch_results["results"]
                if isinstance(r, dict) and "latency_ms" in r
            ]
            latencies.sort()
            
            n = len(latencies)
            successes = sum(1 for r in batch_results["results"] if isinstance(r, dict) and r.get("success"))
            
            result_summary = {
                "concurrency": concurrency,
                "total_requests": batch_results["query_count"],
                "successes": successes,
                "failures": batch_results["query_count"] - successes,
                "success_rate": successes / batch_results["query_count"],
                "latencies": {
                    "min_ms": min(latencies) if latencies else 0,
                    "max_ms": max(latencies) if latencies else 0,
                    "mean_ms": sum(latencies) / len(latencies) if latencies else 0,
                    "p50_ms": latencies[n // 2] if n > 0 else 0,
                    "p75_ms": latencies[int(n * 0.75)] if n > 0 else 0,
                    "p95_ms": latencies[int(n * 0.95)] if n > 0 else 0,
                    "p99_ms": latencies[int(n * 0.99)] if n > 0 else 0,
                },
                "vector_db_stats": vector_db.get_stats(),
            }
            
            all_results.append(result_summary)
            
            logger.info(f"  Results: {result_summary['success_rate']*100:.1f}% success, "
                       f"P95: {result_summary['latencies']['p95_ms']:.1f}ms")
        
        return all_results
    
    async def run_sustained_load_test(
        self,
        base_queries: List[Dict[str, Any]],
        concurrency: int = 50,
        duration_seconds: int = 60,
    ) -> Dict[str, Any]:
        """
        Run sustained load test for specified duration.
        
        Args:
            base_queries: Queries to use
            concurrency: Concurrent requests to maintain
            duration_seconds: Test duration
            
        Returns:
            Test results
        """
        logger.info(f"Running sustained load test: {concurrency} concurrent for {duration_seconds}s")
        
        vector_db = self._create_vector_db(VectorDBConfig(
            base_latency_ms=20.0,
            latency_variance_ms=10.0,
            max_concurrent_connections=concurrency,
        ))
        
        stage = RetrievalEnrichStage(vector_db=vector_db, top_k=5)
        pipeline = Pipeline()
        pipeline = pipeline.with_stage("retrieval", stage, StageKind.ENRICH)
        graph = pipeline.build()
        
        semaphore = asyncio.Semaphore(concurrency)
        start_time = time.perf_counter()
        results = []
        stats = {
            "total_requests": 0,
            "successes": 0,
            "failures": 0,
            "latencies": [],
            "cache_hits": 0,
            "intervals": [],
        }
        
        async def run_query() -> None:
            async with semaphore:
                if time.perf_counter() - start_time > duration_seconds:
                    return
                
                query = random.choice(base_queries)
                ctx = create_stage_context(
                    query["text"],
                    user_id=f"user_{random.randint(1, 100)}",
                    session_id=f"sustained_{int(time.time())}",
                )
                
                query_start = time.perf_counter()
                try:
                    result = await graph.run(ctx)
                    elapsed_ms = (time.perf_counter() - query_start) * 1000
                    
                    stats["total_requests"] += 1
                    if result.status.value == "ok":
                        stats["successes"] += 1
                        if result.data.get("cache_hit"):
                            stats["cache_hits"] += 1
                    else:
                        stats["failures"] += 1
                    
                    stats["latencies"].append(elapsed_ms)
                    
                except Exception as e:
                    stats["total_requests"] += 1
                    stats["failures"] += 1
                    elapsed_ms = (time.perf_counter() - query_start) * 1000
                    stats["latencies"].append(elapsed_ms)
        
        tasks = []
        while time.perf_counter() - start_time < duration_seconds:
            if len(tasks) < 100:
                tasks.append(asyncio.create_task(run_query()))
            else:
                await asyncio.gather(*tasks[:10])
                tasks = tasks[10:]
        
        if tasks:
            await asyncio.gather(*tasks)
        
        latencies = sorted(stats["latencies"])
        n = len(latencies)
        
        return {
            "test_type": "sustained_load",
            "concurrency": concurrency,
            "duration_seconds": duration_seconds,
            "total_requests": stats["total_requests"],
            "successes": stats["successes"],
            "failures": stats["failures"],
            "success_rate": stats["successes"] / max(1, stats["total_requests"]),
            "throughput_qps": stats["total_requests"] / duration_seconds,
            "latencies": {
                "min_ms": min(latencies) if latencies else 0,
                "max_ms": max(latencies) if latencies else 0,
                "mean_ms": sum(latencies) / len(latencies) if latencies else 0,
                "p50_ms": latencies[n // 2] if n > 0 else 0,
                "p75_ms": latencies[int(n * 0.75)] if n > 0 else 0,
                "p95_ms": latencies[int(n * 0.95)] if n > 0 else 0,
                "p99_ms": latencies[int(n * 0.99)] if n > 0 else 0,
            },
            "cache_hits": stats["cache_hits"],
            "vector_db_stats": vector_db.get_stats(),
        }
    
    def save_results(self, results: List[Dict], filename: str = "stress_results.json"):
        """Save test results to file."""
        filepath = self.results_dir / filename
        with open(filepath, "w") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"Results saved to {filepath}")
        return filepath


async def main():
    """Run stress tests."""
    from mocks.services.test_data import generate_test_queries, generate_scale_queries
    
    pipeline = StressPipeline()
    
    base_queries = generate_test_queries(100)
    
    logger.info("Running concurrency ramp test...")
    ramp_results = await pipeline.run_concurrency_ramp_test(base_queries)
    
    logger.info("Running sustained load test...")
    sustained_results = await pipeline.run_sustained_load_test(
        base_queries,
        concurrency=50,
        duration_seconds=30,
    )
    
    all_results = {
        "concurrency_ramp": ramp_results,
        "sustained_load": sustained_results,
    }
    
    pipeline.save_results(all_results, "stress_results.json")
    
    return all_results


if __name__ == "__main__":
    asyncio.run(main())
