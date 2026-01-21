"""
WORK-008 Concurrent Tool Execution Limits - Stress Pipeline

Tests high-concurrency scenarios:
- 10, 50, 100+ concurrent tool executions
- Resource usage monitoring
- Latency degradation measurement
- Throughput characterization
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from stageflow import (
    Pipeline,
    StageContext,
    StageKind,
    StageOutput,
    PipelineContext,
)
from stageflow import create_test_snapshot
from stageflow.tools import get_tool_registry

from research.work008_concurrent_tool_limits.mocks.tool_mocks import (
    ExecutionTracker,
    FastTool,
    SlowTool,
    VariableDelayTool,
    RateLimitedTool,
    register_concurrency_tools,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HighConcurrencyStage:
    """Stage that executes many tools concurrently."""
    name = "high_concurrency"
    kind = StageKind.WORK

    def __init__(self, concurrency_level: int = 50):
        self.concurrency_level = concurrency_level
        self.tracker = ExecutionTracker()
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        self.tracker.reset()

        async def execute_tool(i: int) -> Dict[str, Any]:
            action = {"type": "FAST_OPERATION", "payload": {"index": i}}
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                return {
                    "index": i,
                    "success": result.success,
                    "execution_time_ms": result.data.get("delay_ms", 0) if result.success else 0,
                }
            except Exception as e:
                return {
                    "index": i,
                    "success": False,
                    "error": str(e),
                }

        tasks = [execute_tool(i) for i in range(self.concurrency_level)]
        results = await asyncio.gather(*tasks)

        execution_time_ms = (time.time() - start_time) * 1000
        stats = self.tracker.get_stats()

        successful = [r for r in results if r.get("success", False)]
        failed = [r for r in results if not r.get("success", False)]

        return StageOutput.ok(
            high_concurrency=True,
            concurrency_level=self.concurrency_level,
            execution_time_ms=execution_time_ms,
            total_results=len(results),
            successful_count=len(successful),
            failed_count=len(failed),
            results=results[:10],
            tracker_stats=stats,
        )


class VariableLoadStage:
    """Stage with variable execution times under load."""
    name = "variable_load"
    kind = StageKind.WORK

    def __init__(self, tool_count: int = 20, min_delay: int = 10, max_delay: int = 200):
        self.tool_count = tool_count
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.tracker = ExecutionTracker()
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        self.tracker.reset()

        tools = [
            VariableDelayTool(min_delay_ms=self.min_delay, max_delay_ms=self.max_delay)
            for _ in range(self.tool_count)
        ]

        async def execute_tool(tool: VariableDelayTool, i: int) -> Dict[str, Any]:
            action = {"type": "VARIABLE_DELAY", "payload": {"index": i}}
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                return {
                    "index": i,
                    "success": result.success,
                    "actual_delay_ms": result.data.get("delay_ms", 0) if result.success else 0,
                }
            except Exception as e:
                return {
                    "index": i,
                    "success": False,
                    "error": str(e),
                }

        tasks = [execute_tool(tools[i], i) for i in range(self.tool_count)]
        results = await asyncio.gather(*tasks)

        execution_time_ms = (time.time() - start_time) * 1000
        stats = self.tracker.get_stats()

        delays = [r.get("actual_delay_ms", 0) for r in results if r.get("success")]

        return StageOutput.ok(
            variable_load=True,
            tool_count=self.tool_count,
            min_delay_ms=self.min_delay,
            max_delay_ms=self.max_delay,
            execution_time_ms=execution_time_ms,
            avg_actual_delay_ms=sum(delays) / len(delays) if delays else 0,
            tracker_stats=stats,
            results=results[:10],
        )


class BurstLoadStage:
    """Stage that simulates burst traffic patterns."""
    name = "burst_load"
    kind = StageKind.WORK

    def __init__(self, burst_size: int = 10, bursts: int = 5, delay_between_bursts_ms: int = 100):
        self.burst_size = burst_size
        self.bursts = bursts
        self.delay_between_bursts_ms = delay_between_bursts_ms
        self.tracker = ExecutionTracker()
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        self.tracker.reset()
        all_results = []

        for burst_idx in range(self.bursts):
            async def execute_tool(i: int) -> Dict[str, Any]:
                action = {"type": "FAST_OPERATION", "payload": {"burst": burst_idx, "index": i}}
                try:
                    result = await self.registry.execute(action, ctx.to_dict())
                    return {
                        "burst": burst_idx,
                        "index": i,
                        "success": result.success,
                    }
                except Exception as e:
                    return {
                        "burst": burst_idx,
                        "index": i,
                        "success": False,
                        "error": str(e),
                    }

            tasks = [execute_tool(i) for i in range(self.burst_size)]
            burst_results = await asyncio.gather(*tasks)
            all_results.extend(burst_results)

            if burst_idx < self.bursts - 1:
                await asyncio.sleep(self.delay_between_bursts_ms / 1000.0)

        execution_time_ms = (time.time() - start_time) * 1000
        stats = self.tracker.get_stats()

        return StageOutput.ok(
            burst_load=True,
            burst_size=self.burst_size,
            bursts=self.bursts,
            delay_between_bursts_ms=self.delay_between_bursts_ms,
            execution_time_ms=execution_time_ms,
            total_results=len(all_results),
            tracker_stats=stats,
        )


class SustainedLoadStage:
    """Stage that maintains sustained load over time."""
    name = "sustained_load"
    kind = StageKind.WORK

    def __init__(self, concurrent_tools: int = 20, duration_seconds: float = 2.0):
        self.concurrent_tools = concurrent_tools
        self.duration_seconds = duration_seconds
        self.tracker = ExecutionTracker()
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        self.tracker.reset()
        all_results = []
        iteration = 0

        while time.time() - start_time < self.duration_seconds:
            iteration += 1

            async def execute_tool(i: int) -> Dict[str, Any]:
                action = {"type": "FAST_OPERATION", "payload": {"iteration": iteration, "index": i}}
                try:
                    result = await self.registry.execute(action, ctx.to_dict())
                    return {
                        "iteration": iteration,
                        "index": i,
                        "success": result.success,
                    }
                except Exception as e:
                    return {
                        "iteration": iteration,
                        "index": i,
                        "success": False,
                        "error": str(e),
                    }

            tasks = [execute_tool(i) for i in range(self.concurrent_tools)]
            batch_results = await asyncio.gather(*tasks)
            all_results.extend(batch_results)

        execution_time_ms = (time.time() - start_time) * 1000
        stats = self.tracker.get_stats()

        return StageOutput.ok(
            sustained_load=True,
            concurrent_tools=self.concurrent_tools,
            duration_seconds=self.duration_seconds,
            iterations=iteration,
            total_results=len(all_results),
            execution_time_ms=execution_time_ms,
            tracker_stats=stats,
        )


class RateLimitSimulationStage:
    """Stage that simulates rate-limited API behavior."""
    name = "rate_limit_simulation"
    kind = StageKind.WORK

    def __init__(self, request_count: int = 50, max_per_second: float = 10.0):
        self.request_count = request_count
        self.max_per_second = max_per_second
        self.tracker = ExecutionTracker()
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        self.tracker.reset()

        rate_limited_tool = RateLimitedTool(max_per_second=self.max_per_second)
        self.registry.register(rate_limited_tool)

        async def execute_rate_limited(i: int) -> Dict[str, Any]:
            action = {"type": "RATE_LIMITED", "payload": {"index": i}}
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                return {
                    "index": i,
                    "success": result.success,
                    "tokens_used": result.data.get("tokens_used", 0) if result.success else None,
                    "error": result.error,
                }
            except Exception as e:
                return {
                    "index": i,
                    "success": False,
                    "error": str(e),
                }

        tasks = [execute_rate_limited(i) for i in range(self.request_count)]
        results = await asyncio.gather(*tasks)

        execution_time_ms = (time.time() - start_time) * 1000
        stats = self.tracker.get_stats()

        successful = [r for r in results if r.get("success", False)]
        rate_limited = [r for r in results if r.get("error") == "Rate limit exceeded: burst limit reached"]

        return StageOutput.ok(
            rate_limit_simulation=True,
            request_count=self.request_count,
            max_per_second=self.max_per_second,
            execution_time_ms=execution_time_ms,
            successful_count=len(successful),
            rate_limited_count=len(rate_limited),
            throughput_per_second=len(successful) / (execution_time_ms / 1000) if execution_time_ms > 0 else 0,
            tracker_stats=stats,
        )


class StressPipeline:
    """Stress pipeline for high-concurrency testing."""

    def __init__(self, test_name: str, concurrency_level: int = 50):
        self.test_name = test_name
        self.concurrency_level = concurrency_level
        self.results: List[Dict[str, Any]] = []
        self.start_time: float = 0
        self.end_time: float = 0
        self.tracker = ExecutionTracker()

    def create_pipeline(self) -> Pipeline:
        """Create the stress test pipeline."""
        pipeline = Pipeline()

        pipeline = pipeline.with_stage(
            "high_concurrency",
            HighConcurrencyStage(concurrency_level=self.concurrency_level),
            StageKind.WORK,
        )

        pipeline = pipeline.with_stage(
            "variable_load",
            VariableLoadStage(tool_count=self.concurrency_level),
            StageKind.WORK,
        )

        pipeline = pipeline.with_stage(
            "burst_load",
            BurstLoadStage(burst_size=min(self.concurrency_level, 10), bursts=5),
            StageKind.WORK,
        )

        pipeline = pipeline.with_stage(
            "rate_limit_simulation",
            RateLimitSimulationStage(request_count=self.concurrency_level, max_per_second=10.0),
            StageKind.WORK,
        )

        return pipeline

    async def run_test(self) -> Dict[str, Any]:
        """Run the stress test and return results."""
        self.start_time = time.time()
        self.tracker.reset()

        try:
            pipeline = self.create_pipeline()

            snapshot = create_test_snapshot(input_text="Stress test concurrent execution")

            run_id = uuid4()
            
            ctx = PipelineContext(
                pipeline_run_id=run_id,
                request_id=uuid4(),
                session_id=snapshot.session_id,
                user_id=snapshot.user_id,
                org_id=uuid4(),
                interaction_id=uuid4(),
                topology=pipeline.stages,
                data={
                    "test_name": self.test_name,
                    "concurrency_level": self.concurrency_level,
                },
            )

            graph = pipeline.build()
            result = await graph.run(ctx)

            self.end_time = time.time()
            tracker_stats = self.tracker.get_stats()

            test_result = {
                "test_name": self.test_name,
                "concurrency_level": self.concurrency_level,
                "total_duration_ms": (self.end_time - self.start_time) * 1000,
                "pipeline_status": result.status,
                "tracker_stats": tracker_stats,
                "stage_outputs": {},
                "errors": [],
            }

            for stage_name, stage_result in result.outputs.items():
                if stage_result:
                    test_result["stage_outputs"][stage_name] = {
                        "status": stage_result.status.value,
                        "execution_time_ms": stage_result.data.get("execution_time_ms", 0),
                        "successful_count": stage_result.data.get("successful_count", 0),
                        "failed_count": stage_result.data.get("failed_count", 0),
                    }

                    if stage_result.status.value == "fail":
                        test_result["errors"].append({
                            "stage": stage_name,
                            "error": stage_result.error,
                        })

            logger.info(f"Stress test '{self.test_name}' completed in {test_result['total_duration_ms']:.2f}ms")
            logger.info(f"  Pipeline status: {result.status}")
            logger.info(f"  Max concurrent: {tracker_stats.get('max_concurrent', 0)}")

            return test_result

        except Exception as e:
            self.end_time = time.time()
            return {
                "test_name": self.test_name,
                "concurrency_level": self.concurrency_level,
                "total_duration_ms": (self.end_time - self.start_time) * 1000,
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }


async def run_stress_tests() -> List[Dict[str, Any]]:
    """Run all stress tests."""
    results = []

    concurrency_levels = [10, 25, 50, 75, 100]

    for level in concurrency_levels:
        logger.info(f"Running stress test with concurrency level: {level}")
        pipeline = StressPipeline(f"stress_{level}", concurrency_level=level)
        result = await pipeline.run_test()
        results.append(result)

    return results


if __name__ == "__main__":
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    results = asyncio.run(run_stress_tests())

    output_file = results_dir / "stress_test_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"Stress tests completed. Results saved to {output_file}")
    print(json.dumps(results, indent=2, default=str))
