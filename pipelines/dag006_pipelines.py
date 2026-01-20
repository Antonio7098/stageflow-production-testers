import asyncio
import time
import tracemalloc
from typing import Any

from stageflow import Pipeline, StageKind, StageContext, StageOutput
from stageflow.context import ContextSnapshot
from uuid import uuid4


class TrackedStage:
    """Base stage that tracks execution metrics."""
    name = "tracked"
    kind = StageKind.TRANSFORM
    
    def __init__(self, stage_id: int):
        self.stage_id = stage_id
        self.executed = False
        self.start_time = None
        self.end_time = None
        
    async def execute(self, ctx: StageContext) -> StageOutput:
        self.start_time = time.perf_counter()
        self.executed = True
        value = ctx.inputs.get(f"stage_{self.stage_id - 1}_value", 0)
        self.end_time = time.perf_counter()
        return StageOutput.ok(
            stage_id=self.stage_id,
            execution_time_ms=(self.end_time - self.start_time) * 1000,
            accumulated_value=value + 1
        )


def create_linear_pipeline(num_stages: int) -> Pipeline:
    """Create a linear pipeline with N sequential stages.
    
    Pipeline structure:
        [stage_1] -> [stage_2] -> ... -> [stage_N]
    """
    pipeline = Pipeline()
    
    for i in range(1, num_stages + 1):
        dependencies = (f"stage_{i-1}",) if i > 1 else ()
        
        # Use a factory function to create a unique stage class for each position
        stage_class = type(
            f"Stage{i}",
            (TrackedStage,),
            {
                'name': f"stage_{i}",
                'kind': StageKind.TRANSFORM,
                '__init__': lambda self, sid=i: setattr(self, 'stage_id', sid) or TrackedStage.__init__(self, sid)
            }
        )
        
        pipeline = pipeline.with_stage(
            f"stage_{i}",
            stage_class,
            StageKind.TRANSFORM,
            dependencies=dependencies
        )
    
    return pipeline


async def run_pipeline(pipeline: Pipeline, num_stages: int) -> dict[str, Any]:
    """Execute a pipeline and collect metrics."""
    from stageflow import create_stage_context
    
    # Create context
    snapshot = ContextSnapshot(
        run_id=type('RunIdentity', (), {
            'pipeline_run_id': uuid4(),
            'request_id': uuid4(),
            'session_id': uuid4(),
            'user_id': uuid4(),
            'org_id': uuid4(),
            'interaction_id': uuid4()
        })(),
        topology="dag006_test",
        execution_mode="test",
        input_text="test_input"
    )
    
    ctx = create_stage_context(snapshot=snapshot)
    
    # Build graph
    graph = pipeline.build()
    
    # Track memory
    tracemalloc.start()
    start_time = time.perf_counter()
    
    # Run pipeline
    results = await graph.run(ctx)
    
    end_time = time.perf_counter()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    # Collect metrics
    metrics = {
        "num_stages": num_stages,
        "total_time_ms": (end_time - start_time) * 1000,
        "per_stage_avg_ms": (end_time - start_time) * 1000 / num_stages,
        "memory_current_mb": current / 1024 / 1024,
        "memory_peak_mb": peak / 1024 / 1024,
        "successful_stages": sum(1 for r in results.values() if r.status.value == "ok"),
        "failed_stages": sum(1 for r in results.values() if r.status.value == "fail"),
        "results": results
    }
    
    return metrics


async def test_memory_growth(num_stages: int = 1000) -> dict[str, Any]:
    """Test if memory grows proportionally with stage count."""
    results = []
    
    for count in [100, 250, 500, 750, 1000]:
        pipeline = create_linear_pipeline(count)
        metrics = await run_pipeline(pipeline, count)
        results.append({
            "stages": count,
            "memory_peak_mb": metrics["memory_peak_mb"],
            "total_time_ms": metrics["total_time_ms"]
        })
    
    return {"memory_growth_test": results}


async def test_latency_consistency(num_stages: int = 1000) -> dict[str, Any]:
    """Test if per-stage latency remains consistent across the pipeline."""
    import numpy as np
    
    pipeline = create_linear_pipeline(num_stages)
    metrics = await run_pipeline(pipeline, num_stages)
    
    # Extract per-stage times from results
    stage_times = []
    for name, result in metrics["results"].items():
        if name.startswith("stage_") and "execution_time_ms" in result.data:
            stage_times.append(result.data["execution_time_ms"])
    
    if len(stage_times) >= num_stages:
        stage_times = stage_times[:num_stages]
    
    latency_stats = {
        "mean_ms": float(np.mean(stage_times)) if stage_times else 0,
        "std_ms": float(np.std(stage_times)) if stage_times else 0,
        "min_ms": float(np.min(stage_times)) if stage_times else 0,
        "max_ms": float(np.max(stage_times)) if stage_times else 0,
        "p50_ms": float(np.percentile(stage_times, 50)) if stage_times else 0,
        "p95_ms": float(np.percentile(stage_times, 95)) if stage_times else 0,
        "p99_ms": float(np.percentile(stage_times, 99)) if stage_times else 0
    }
    
    return {
        "latency_stats": latency_stats,
        "stage_count": num_stages
    }
