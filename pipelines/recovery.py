"""
Recovery Pipeline for Retrieval Latency Testing

This pipeline tests recovery behavior after failures.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow import Pipeline, StageKind
from stageflow.context import ContextSnapshot

from mocks.services.mock_vector_db import MockVectorDatabase, VectorDBConfig, FailureMode
from mocks.services.enrich_stages import RetrievalEnrichStage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RecoveryPipeline:
    """
    Recovery testing pipeline for retrieval behavior after failures.
    
    Tests:
    - Recovery time after failure bursts
    - Cache validity after index updates
    - Connection pool recovery
    - Back-to-back failure/success patterns
    """
    
    def __init__(self, results_dir: str = "results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
    
    async def run_failure_recovery_test(
        self,
        queries: List[Dict[str, Any]],
        failure_burst_size: int = 10,
        recovery_check_count: int = 20,
    ) -> Dict[str, Any]:
        """
        Test recovery after a burst of failures.
        
        Args:
            queries: Test queries
            failure_burst_size: Number of consecutive failures
            recovery_check_count: Number of queries to check recovery
            
        Returns:
            Test results with recovery timing
        """
        logger.info(f"Running failure recovery test (burst={failure_burst_size}, checks={recovery_check_count})")
        
        config = VectorDBConfig(
            base_latency_ms=20.0,
            failure_mode=FailureMode.ERROR,
            failure_rate=1.0,
        )
        vector_db = MockVectorDatabase(config)
        
        stage = RetrievalEnrichStage(vector_db=vector_db, top_k=5, fail_silently=True)
        pipeline = Pipeline()
        pipeline = pipeline.with_stage("retrieval", stage, StageKind.ENRICH)
        graph = pipeline.build()
        
        results = []
        
        logger.info("Phase 1: Failure burst")
        for i in range(failure_burst_size):
            snapshot = ContextSnapshot(
                input_text=queries[0]["text"],
                user_id="recovery_test",
                session_id=f"fail_{i}",
            )
            
            start_time = time.perf_counter()
            result = await graph.run(snapshot)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            results.append({
                "phase": "failure_burst",
                "index": i,
                "latency_ms": elapsed_ms,
                "success": result.status.value == "ok",
            })
        
        logger.info("Phase 2: Recovery check")
        vector_db.set_failure_mode(FailureMode.NONE, 0.0)
        
        recovery_latencies = []
        recovery_times = []
        first_success_time = None
        
        for i in range(recovery_check_count):
            snapshot = ContextSnapshot(
                input_text=queries[0]["text"],
                user_id="recovery_test",
                session_id=f"recover_{i}",
            )
            
            start_time = time.perf_counter()
            result = await graph.run(snapshot)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            recovery_latencies.append(elapsed_ms)
            recovery_times.append(time.perf_counter())
            
            if result.status.value == "ok" and first_success_time is None:
                first_success_time = time.perf_counter()
                logger.info(f"  First success at iteration {i+1}")
            
            results.append({
                "phase": "recovery",
                "index": i,
                "latency_ms": elapsed_ms,
                "success": result.status.value == "ok",
            })
        
        recovery_latencies.sort()
        n = len(recovery_latencies)
        
        return {
            "test_type": "failure_recovery",
            "failure_burst_size": failure_burst_size,
            "recovery_check_count": recovery_check_count,
            "failure_burst_results": [r for r in results if r["phase"] == "failure_burst"],
            "recovery_results": [r for r in results if r["phase"] == "recovery"],
            "recovery_metrics": {
                "first_success_iteration": (
                    next((i for i, r in enumerate(results) 
                          if r["phase"] == "recovery" and r["success"]), None)
                ),
                "recovery_latency_p50_ms": recovery_latencies[n // 2] if n > 0 else 0,
                "recovery_latency_p95_ms": recovery_latencies[int(n * 0.95)] if n > 0 else 0,
                "success_rate_in_recovery": sum(
                    1 for r in results if r["phase"] == "recovery" and r["success"]
                ) / recovery_check_count,
            },
        }
    
    async def run_cache_invalidation_test(
        self,
        queries: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Test cache behavior after index changes.
        
        Args:
            queries: Test queries
            
        Returns:
            Test results
        """
        logger.info("Running cache invalidation test")
        
        config = VectorDBConfig(
            base_latency_ms=20.0,
            cache_size=100,
            cache_ttl_seconds=300,
        )
        vector_db = MockVectorDatabase(config)
        
        stage = RetrievalEnrichStage(vector_db=vector_db, top_k=5)
        pipeline = Pipeline()
        pipeline = pipeline.with_stage("retrieval", stage, StageKind.ENRICH)
        graph = pipeline.build()
        
        results = []
        
        logger.info("Phase 1: Populate cache")
        cache_stats = []
        for i in range(10):
            query = queries[i % len(queries)]
            snapshot = ContextSnapshot(
                input_text=query["text"],
                user_id="cache_test",
                session_id=f"populate_{i}",
            )
            
            start_time = time.perf_counter()
            result = await graph.run(snapshot)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            cache_stats.append({
                "iteration": i,
                "latency_ms": elapsed_ms,
                "cache_hit": result.data.get("cache_hit", False),
            })
            
            results.append({
                "phase": "populate",
                "iteration": i,
                "latency_ms": elapsed_ms,
                "cache_hit": result.data.get("cache_hit", False),
            })
        
        logger.info("Phase 2: Clear cache and re-query")
        vector_db.clear_cache()
        
        cache_miss_latencies = []
        for i in range(5):
            query = queries[i % len(queries)]
            snapshot = ContextSnapshot(
                input_text=query["text"],
                user_id="cache_test",
                session_id=f"miss_{i}",
            )
            
            start_time = time.perf_counter()
            result = await graph.run(snapshot)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            cache_miss_latencies.append(elapsed_ms)
            results.append({
                "phase": "cache_miss",
                "iteration": i,
                "latency_ms": elapsed_ms,
                "cache_hit": result.data.get("cache_hit", False),
            })
        
        populate_hits = sum(1 for r in cache_stats if r["cache_hit"])
        populate_misses = len(cache_stats) - populate_hits
        
        return {
            "test_type": "cache_invalidation",
            "cache_population": {
                "total_queries": len(cache_stats),
                "cache_hits": populate_hits,
                "cache_misses": populate_misses,
                "hit_rate": populate_hits / len(cache_stats),
                "avg_hit_latency_ms": sum(
                    r["latency_ms"] for r in cache_stats if r["cache_hit"]
                ) / max(1, populate_hits),
                "avg_miss_latency_ms": sum(
                    r["latency_ms"] for r in cache_stats if not r["cache_hit"]
                ) / max(1, populate_misses),
            },
            "cache_invalidation": {
                "queries_after_clear": len(cache_miss_latencies),
                "avg_latency_ms": sum(cache_miss_latencies) / len(cache_miss_latencies),
            },
            "results": results,
        }
    
    async def run_connection_pool_recovery_test(
        self,
        queries: List[Dict[str, Any]],
        pool_size: int = 5,
        concurrent_requests: int = 20,
    ) -> Dict[str, Any]:
        """
        Test connection pool recovery after saturation.
        
        Args:
            queries: Test queries
            pool_size: Connection pool size
            concurrent_requests: Number of concurrent requests to saturate pool
            
        Returns:
            Test results
        """
        logger.info(f"Running connection pool recovery test (pool={pool_size}, concurrent={concurrent_requests})")
        
        config = VectorDBConfig(
            base_latency_ms=50.0,
            max_concurrent_connections=pool_size,
            connection_acquire_timeout_ms=1000,
        )
        vector_db = MockVectorDatabase(config)
        
        stage = RetrievalEnrichStage(vector_db=vector_db, top_k=5)
        pipeline = Pipeline()
        pipeline = pipeline.with_stage("retrieval", stage, StageKind.ENRICH)
        graph = pipeline.build()
        
        semaphore = asyncio.Semaphore(concurrent_requests)
        
        latencies = []
        timeouts = 0
        successes = 0
        
        logger.info("Phase 1: Saturate connection pool")
        async def run_query(query: Dict[str, Any], index: int):
            async with semaphore:
                snapshot = ContextSnapshot(
                    input_text=query["text"],
                    user_id="pool_test",
                    session_id=f"saturation_{index}",
                )
                
                start_time = time.perf_counter()
                try:
                    result = await graph.run(snapshot)
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    
                    return {
                        "success": result.status.value == "ok",
                        "latency_ms": elapsed_ms,
                        "timeout": False,
                    }
                except Exception as e:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    return {
                        "success": False,
                        "latency_ms": elapsed_ms,
                        "timeout": "timeout" in str(e).lower(),
                        "error": str(e)[:100],
                    }
        
        tasks = [
            run_query(queries[i % len(queries)], i)
            for i in range(concurrent_requests)
        ]
        saturation_results = await asyncio.gather(*tasks)
        
        for r in saturation_results:
            latencies.append(r["latency_ms"])
            if r.get("timeout"):
                timeouts += 1
            elif r.get("success"):
                successes += 1
        
        logger.info(f"  Saturation: {successes} successes, {timeouts} timeouts")
        
        logger.info("Phase 2: Normal operation recovery")
        normal_latencies = []
        normal_successes = 0
        
        for i in range(10):
            query = queries[i % len(queries)]
            snapshot = ContextSnapshot(
                input_text=query["text"],
                user_id="pool_test",
                session_id=f"normal_{i}",
            )
            
            start_time = time.perf_counter()
            result = await graph.run(snapshot)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            normal_latencies.append(elapsed_ms)
            if result.status.value == "ok":
                normal_successes += 1
        
        latencies.sort()
        n = len(latencies)
        normal_latencies.sort()
        nn = len(normal_latencies)
        
        return {
            "test_type": "connection_pool_recovery",
            "pool_size": pool_size,
            "concurrent_requests": concurrent_requests,
            "saturation_phase": {
                "total_requests": len(saturation_results),
                "successes": successes,
                "timeouts": timeouts,
                "success_rate": successes / len(saturation_results),
                "latencies": {
                    "p50_ms": latencies[n // 2] if n > 0 else 0,
                    "p95_ms": latencies[int(n * 0.95)] if n > 0 else 0,
                },
            },
            "recovery_phase": {
                "total_requests": len(normal_latencies),
                "successes": normal_successes,
                "success_rate": normal_successes / len(normal_latencies),
                "latencies": {
                    "p50_ms": normal_latencies[nn // 2] if nn > 0 else 0,
                    "p95_ms": normal_latencies[int(nn * 0.95)] if nn > 0 else 0,
                },
            },
        }
    
    async def run_all_tests(
        self,
        queries: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Run all recovery tests.
        
        Args:
            queries: Test queries
            
        Returns:
            Combined test results
        """
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "test_type": "recovery",
        }
        
        results["failure_recovery_test"] = await self.run_failure_recovery_test(queries)
        results["cache_invalidation_test"] = await self.run_cache_invalidation_test(queries)
        results["connection_pool_recovery_test"] = await self.run_connection_pool_recovery_test(queries)
        
        return results
    
    def save_results(self, results: Dict, filename: str = "recovery_results.json"):
        """Save test results to file."""
        filepath = self.results_dir / filename
        with open(filepath, "w") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"Results saved to {filepath}")
        return filepath


async def main():
    """Run recovery tests."""
    from mocks.services.test_data import generate_test_queries
    
    pipeline = RecoveryPipeline()
    
    queries = generate_test_queries(100)
    
    results = await pipeline.run_all_tests(queries)
    
    pipeline.save_results(results)
    
    return results


if __name__ == "__main__":
    asyncio.run(main())
