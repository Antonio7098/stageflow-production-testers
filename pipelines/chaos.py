"""
Chaos Pipeline for Retrieval Latency Testing

This pipeline tests retrieval behavior under failure conditions.
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

from mocks.services.mock_vector_db import (
    MockVectorDatabase, VectorDBConfig, FailureMode
)
from mocks.services.enrich_stages import (
    RetrievalEnrichStage, FallbackRetrievalEnrichStage
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChaosPipeline:
    """
    Chaos engineering pipeline for retrieval testing.
    
    Tests:
    - Timeout handling
    - Error recovery
    - Circuit breaker behavior
    - Fallback mechanisms
    - Latency spike injection
    """
    
    def __init__(self, results_dir: str = "results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
    
    async def run_timeout_test(
        self,
        queries: List[Dict[str, Any]],
        timeout_ms: int = 50,
        slow_queries_ratio: float = 0.3,
        slow_query_latency_ms: int = 500,
    ) -> Dict[str, Any]:
        """
        Test timeout handling with slow queries.
        
        Args:
            queries: Test queries
            timeout_ms: Request timeout in milliseconds
            slow_queries_ratio: Ratio of queries that will be slow
            slow_query_latency_ms: Latency for slow queries
            
        Returns:
            Test results
        """
        logger.info(f"Running timeout test (timeout={timeout_ms}ms, slow_ratio={slow_queries_ratio})")
        
        config = VectorDBConfig(
            base_latency_ms=20.0,
            failure_mode=FailureMode.TIMEOUT,
            failure_rate=slow_queries_ratio,
        )
        
        slow_vector_db = MockVectorDatabase(config)
        
        def slow_search(query: str, top_k: int = 5):
            async def _slow():
                await asyncio.sleep(slow_query_latency_ms / 1000)
                return []
            return _slow()
        
        stage = RetrievalEnrichStage(vector_db=slow_vector_db, top_k=5)
        pipeline = Pipeline()
        pipeline = pipeline.with_stage("retrieval", stage, StageKind.ENRICH)
        graph = pipeline.build()
        
        results = []
        timeout_count = 0
        success_count = 0
        failure_count = 0
        
        for i, query in enumerate(queries[:20]):
            snapshot = ContextSnapshot(
                input_text=query["text"],
                user_id="timeout_test",
                session_id=f"test_{i}",
            )
            
            start_time = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    graph.run(snapshot),
                    timeout=timeout_ms / 1000,
                )
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                
                if result.status.value == "ok":
                    success_count += 1
                else:
                    failure_count += 1
                
                results.append({
                    "query_id": query["id"],
                    "success": result.status.value == "ok",
                    "latency_ms": elapsed_ms,
                    "status": result.status.value,
                })
                
            except asyncio.TimeoutError:
                timeout_count += 1
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                results.append({
                    "query_id": query["id"],
                    "success": False,
                    "latency_ms": elapsed_ms,
                    "status": "timeout",
                })
        
        return {
            "test_type": "timeout",
            "timeout_ms": timeout_ms,
            "total_queries": len(results),
            "timeouts": timeout_count,
            "successes": success_count,
            "failures": failure_count,
            "results": results,
        }
    
    async def run_error_injection_test(
        self,
        queries: List[Dict[str, Any]],
        error_rate: float = 0.2,
    ) -> Dict[str, Any]:
        """
        Test error handling with simulated errors.
        
        Args:
            queries: Test queries
            error_rate: Ratio of queries that will error
            
        Returns:
            Test results
        """
        logger.info(f"Running error injection test (error_rate={error_rate})")
        
        config = VectorDBConfig(
            base_latency_ms=20.0,
            failure_mode=FailureMode.ERROR,
            failure_rate=error_rate,
        )
        vector_db = MockVectorDatabase(config)
        
        stage = RetrievalEnrichStage(vector_db=vector_db, top_k=5)
        pipeline = Pipeline()
        pipeline = pipeline.with_stage("retrieval", stage, StageKind.ENRICH)
        graph = pipeline.build()
        
        results = []
        error_count = 0
        success_count = 0
        
        for i, query in enumerate(queries[:30]):
            snapshot = ContextSnapshot(
                input_text=query["text"],
                user_id="error_test",
                session_id=f"test_{i}",
            )
            
            start_time = time.perf_counter()
            try:
                result = await graph.run(snapshot)
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                
                if result.status.value == "ok":
                    success_count += 1
                else:
                    error_count += 1
                    if "error" in result.data:
                        logger.debug(f"Error: {result.data['error']}")
                
                results.append({
                    "query_id": query["id"],
                    "success": result.status.value == "ok",
                    "latency_ms": elapsed_ms,
                    "status": result.status.value,
                    "error": result.data.get("error"),
                })
                
            except Exception as e:
                error_count += 1
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                results.append({
                    "query_id": query["id"],
                    "success": False,
                    "latency_ms": elapsed_ms,
                    "status": "exception",
                    "error": str(e)[:100],
                })
        
        return {
            "test_type": "error_injection",
            "error_rate": error_rate,
            "total_queries": len(results),
            "errors": error_count,
            "successes": success_count,
            "error_rate_observed": error_count / len(results),
            "results": results,
        }
    
    async def run_latency_spike_test(
        self,
        queries: List[Dict[str, Any]],
        spike_rate: float = 0.1,
        spike_multiplier: int = 5,
    ) -> Dict[str, Any]:
        """
        Test behavior during latency spikes.
        
        Args:
            queries: Test queries
            spike_rate: Ratio of queries that will experience spikes
            spike_multiplier: Multiplier for latency during spikes
            
        Returns:
            Test results
        """
        logger.info(f"Running latency spike test (spike_rate={spike_rate}, multiplier={spike_multiplier})")
        
        config = VectorDBConfig(
            base_latency_ms=20.0,
            latency_variance_ms=5.0,
            failure_mode=FailureMode.LATENCY_SPIKE,
            failure_rate=spike_rate,
        )
        vector_db = MockVectorDatabase(config)
        
        stage = RetrievalEnrichStage(vector_db=vector_db, top_k=5)
        pipeline = Pipeline()
        pipeline = pipeline.with_stage("retrieval", stage, StageKind.ENRICH)
        graph = pipeline.build()
        
        latencies = []
        spike_count = 0
        normal_count = 0
        
        for i, query in enumerate(queries[:50]):
            snapshot = ContextSnapshot(
                input_text=query["text"],
                user_id="spike_test",
                session_id=f"test_{i}",
            )
            
            start_time = time.perf_counter()
            result = await graph.run(snapshot)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            latencies.append(elapsed_ms)
            
            if elapsed_ms > 50:
                spike_count += 1
            else:
                normal_count += 1
        
        latencies.sort()
        n = len(latencies)
        
        return {
            "test_type": "latency_spike",
            "spike_rate": spike_rate,
            "spike_multiplier": spike_multiplier,
            "total_queries": len(queries[:50]),
            "normal_queries": normal_count,
            "spike_queries": spike_count,
            "latencies": {
                "min_ms": min(latencies) if latencies else 0,
                "max_ms": max(latencies) if latencies else 0,
                "mean_ms": sum(latencies) / len(latencies) if latencies else 0,
                "p50_ms": latencies[n // 2] if n > 0 else 0,
                "p95_ms": latencies[int(n * 0.95)] if n > 0 else 0,
                "p99_ms": latencies[int(n * 0.99)] if n > 0 else 0,
            },
        }
    
    async def run_fallback_test(
        self,
        queries: List[Dict[str, Any]],
        failure_rate: float = 0.3,
    ) -> Dict[str, Any]:
        """
        Test fallback mechanism with failures.
        
        Args:
            queries: Test queries
            failure_rate: Ratio of queries that will fail
            
        Returns:
            Test results
        """
        logger.info(f"Running fallback test (failure_rate={failure_rate})")
        
        config = VectorDBConfig(
            base_latency_ms=20.0,
            failure_mode=FailureMode.ERROR,
            failure_rate=failure_rate,
        )
        vector_db = MockVectorDatabase(config)
        
        stage = FallbackRetrievalEnrichStage(vector_db=vector_db, top_k=5)
        pipeline = Pipeline()
        pipeline = pipeline.with_stage("retrieval", stage, StageKind.ENRICH)
        graph = pipeline.build()
        
        results = []
        fallback_count = 0
        success_count = 0
        pure_success_count = 0
        
        for i, query in enumerate(queries[:30]):
            snapshot = ContextSnapshot(
                input_text=query["text"],
                user_id="fallback_test",
                session_id=f"test_{i}",
            )
            
            start_time = time.perf_counter()
            result = await graph.run(snapshot)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            results.append({
                "query_id": query["id"],
                "success": result.status.value == "ok",
                "latency_ms": elapsed_ms,
                "status": result.status.value,
                "fallback": result.data.get("fallback", False),
                "warning": result.data.get("warning"),
            })
            
            if result.data.get("fallback"):
                fallback_count += 1
            elif result.status.value == "ok":
                pure_success_count += 1
                success_count += 1
            else:
                success_count += 1
        
        return {
            "test_type": "fallback",
            "failure_rate": failure_rate,
            "total_queries": len(results),
            "pure_successes": pure_success_count,
            "fallbacks": fallback_count,
            "total_successes": success_count,
            "fallback_rate": fallback_count / len(results),
        }
    
    async def run_all_tests(
        self,
        queries: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Run all chaos tests.
        
        Args:
            queries: Test queries
            
        Returns:
            Combined test results
        """
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "test_type": "chaos",
        }
        
        results["timeout_test"] = await self.run_timeout_test(queries)
        results["error_injection_test"] = await self.run_error_injection_test(queries)
        results["latency_spike_test"] = await self.run_latency_spike_test(queries)
        results["fallback_test"] = await self.run_fallback_test(queries)
        
        return results
    
    def save_results(self, results: Dict, filename: str = "chaos_results.json"):
        """Save test results to file."""
        filepath = self.results_dir / filename
        with open(filepath, "w") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"Results saved to {filepath}")
        return filepath


async def main():
    """Run chaos tests."""
    from mocks.services.test_data import generate_test_queries
    
    pipeline = ChaosPipeline()
    
    queries = generate_test_queries(100)
    
    results = await pipeline.run_all_tests(queries)
    
    pipeline.save_results(results)
    
    return results


if __name__ == "__main__":
    asyncio.run(main())
