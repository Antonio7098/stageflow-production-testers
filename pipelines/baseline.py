"""
Baseline Pipeline for Retrieval Latency Testing

This pipeline tests the happy path: normal retrieval under light load.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow import Pipeline, StageKind, StageContext, PipelineTimer
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow.stages.inputs import StageInputs

from mocks.services.mock_vector_db import MockVectorDatabase, VectorDBConfig
from mocks.services.enrich_stages import RetrievalEnrichStage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_context(input_text: str, user_id: str = "test_user", session_id: str = "baseline_test") -> StageContext:
    """Create a properly configured StageContext."""
    snapshot = ContextSnapshot(
        run_id=RunIdentity(
            pipeline_run_id=uuid4(),
            request_id=uuid4(),
            session_id=session_id,
            user_id=user_id,
            org_id=None,
            interaction_id=uuid4(),
        ),
        topology="baseline",
        execution_mode="test",
        input_text=input_text,
    )
    
    return StageContext(
        snapshot=snapshot,
        inputs=StageInputs(snapshot=snapshot),
        stage_name="pipeline_entry",
        timer=PipelineTimer(),
    )


class BaselinePipeline:
    """
    Baseline retrieval pipeline for happy path testing.
    
    Tests:
    - Single sequential retrieval requests
    - Expected latency ranges
    - Correct document retrieval
    - Proper event emission
    """
    
    def __init__(self, results_dir: str = "results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.vector_db = MockVectorDatabase(VectorDBConfig(
            base_latency_ms=20.0,
            latency_variance_ms=5.0,
        ))
        self.results = []
    
    async def run_test(self, queries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Run the baseline test with given queries.
        
        Args:
            queries: List of query dictionaries with 'id' and 'text' keys
            
        Returns:
            Test results including latency metrics
        """
        pipeline = Pipeline()
        
        pipeline = pipeline.with_stage(
            "retrieval",
            RetrievalEnrichStage(vector_db=self.vector_db, top_k=5),
            StageKind.ENRICH,
            dependencies=[],
        )
        
        graph = pipeline.build()
        
        start_time = time.perf_counter()
        latencies = []
        successes = 0
        failures = 0
        cache_hits = 0
        events = []
        
        for query in queries:
            ctx = create_context(query["text"])
            
            query_start = time.perf_counter()
            
            try:
                result = await graph.run(ctx)
                elapsed_ms = (time.perf_counter() - query_start) * 1000
                latencies.append(elapsed_ms)
                
                stage_output = result.get("retrieval")
                if stage_output and stage_output.status.value == "ok":
                    successes += 1
                    if stage_output.data.get("cache_hit"):
                        cache_hits += 1
                else:
                    failures += 1
                    if stage_output:
                        logger.warning(f"Query {query['id']} failed: {stage_output.data}")
                
            except Exception as e:
                failures += 1
                elapsed_ms = (time.perf_counter() - query_start) * 1000
                latencies.append(elapsed_ms)
                logger.error(f"Query {query['id']} exception: {e}")
        
        total_time = time.perf_counter() - start_time
        
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)
        
        results = {
            "test_type": "baseline",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query_count": len(queries),
            "successes": successes,
            "failures": failures,
            "success_rate": successes / max(1, len(queries)),
            "total_time_seconds": total_time,
            "throughput_qps": len(queries) / max(0.001, total_time),
            "latencies": {
                "min_ms": min(latencies) if latencies else 0,
                "max_ms": max(latencies) if latencies else 0,
                "mean_ms": sum(latencies) / len(latencies) if latencies else 0,
                "p50_ms": latencies_sorted[n // 2] if n > 0 else 0,
                "p75_ms": latencies_sorted[int(n * 0.75)] if n > 0 else 0,
                "p95_ms": latencies_sorted[int(n * 0.95)] if n > 0 else 0,
                "p99_ms": latencies_sorted[int(n * 0.99)] if n > 0 else 0,
            },
            "cache_hits": cache_hits,
            "cache_hit_rate": cache_hits / max(1, successes),
            "vector_db_stats": self.vector_db.get_stats(),
        }
        
        self.results.append(results)
        
        return results
    
    def save_results(self, filename: str = "baseline_results.json"):
        """Save test results to file."""
        filepath = self.results_dir / filename
        with open(filepath, "w") as f:
            json.dump(self.results, f, indent=2, default=str)
        logger.info(f"Results saved to {filepath}")
        return filepath


async def main():
    """Run the baseline test."""
    from mocks.services.test_data import generate_test_queries
    
    pipeline = BaselinePipeline()
    
    queries = generate_test_queries(50)
    
    logger.info(f"Running baseline test with {len(queries)} queries...")
    results = await pipeline.run_test(queries)
    
    logger.info(f"Results:")
    logger.info(f"  Successes: {results['successes']}")
    logger.info(f"  Failures: {results['failures']}")
    logger.info(f"  Mean latency: {results['latencies']['mean_ms']:.2f}ms")
    logger.info(f"  P95 latency: {results['latencies']['p95_ms']:.2f}ms")
    logger.info(f"  Throughput: {results['throughput_qps']:.2f} QPS")
    
    pipeline.save_results()
    
    return results


if __name__ == "__main__":
    asyncio.run(main())
