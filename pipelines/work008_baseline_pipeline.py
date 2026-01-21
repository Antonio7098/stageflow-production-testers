"""
WORK-008 Concurrent Tool Execution Limits - Baseline Pipeline

Tests basic concurrent tool execution behavior:
- Sequential execution
- Parallel execution of 2-4 tools
- Basic functionality verification
- Baseline metrics collection
"""

import asyncio
import json
import logging
import time
from datetime import datetime, UTC
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
    PriorityTool,
    register_concurrency_tools,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SequentialExecutionStage:
    """Stage that executes tools sequentially."""
    name = "sequential_execution"
    kind = StageKind.WORK

    def __init__(self, tool_count: int = 3):
        self.tool_count = tool_count
        self.tracker = ExecutionTracker()
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        results = []

        for i in range(self.tool_count):
            action = {"type": "FAST_OPERATION", "payload": {"index": i}}
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                results.append({
                    "index": i,
                    "success": result.success,
                    "data": result.data,
                })
            except Exception as e:
                results.append({
                    "index": i,
                    "success": False,
                    "error": str(e),
                })

        execution_time_ms = (time.time() - start_time) * 1000
        stats = self.tracker.get_stats()

        return StageOutput.ok(
            sequential=True,
            tool_count=self.tool_count,
            execution_time_ms=execution_time_ms,
            results=results,
            tracker_stats=stats,
        )


class ParallelExecutionStage:
    """Stage that executes tools in parallel."""
    name = "parallel_execution"
    kind = StageKind.WORK

    def __init__(self, tool_count: int = 4):
        self.tool_count = tool_count
        self.tracker = ExecutionTracker()
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        
        async def execute_tool(i: int) -> Dict[str, Any]:
            action = {"type": "FAST_OPERATION", "payload": {"index": i}}
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                return {
                    "index": i,
                    "success": result.success,
                    "data": result.data,
                }
            except Exception as e:
                return {
                    "index": i,
                    "success": False,
                    "error": str(e),
                }

        tasks = [execute_tool(i) for i in range(self.tool_count)]
        results = await asyncio.gather(*tasks)

        execution_time_ms = (time.time() - start_time) * 1000
        stats = self.tracker.get_stats()

        return StageOutput.ok(
            parallel=True,
            tool_count=self.tool_count,
            execution_time_ms=execution_time_ms,
            results=results,
            tracker_stats=stats,
        )


class MixedExecutionStage:
    """Stage with mix of fast and slow tools."""
    name = "mixed_execution"
    kind = StageKind.WORK

    def __init__(self, fast_count: int = 3, slow_count: int = 2):
        self.fast_count = fast_count
        self.slow_count = slow_count
        self.tracker = ExecutionTracker()
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()

        async def execute_fast(i: int) -> Dict[str, Any]:
            action = {"type": "FAST_OPERATION", "payload": {"index": i, "type": "fast"}}
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                return {"index": i, "type": "fast", "success": result.success, "data": result.data}
            except Exception as e:
                return {"index": i, "type": "fast", "success": False, "error": str(e)}

        async def execute_slow(i: int) -> Dict[str, Any]:
            action = {"type": "SLOW_OPERATION", "payload": {"index": i, "type": "slow"}}
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                return {"index": i, "type": "slow", "success": result.success, "data": result.data}
            except Exception as e:
                return {"index": i, "type": "slow", "success": False, "error": str(e)}

        fast_tasks = [execute_fast(i) for i in range(self.fast_count)]
        slow_tasks = [execute_slow(i) for i in range(self.slow_count)]

        results = await asyncio.gather(*fast_tasks, *slow_tasks)

        execution_time_ms = (time.time() - start_time) * 1000
        stats = self.tracker.get_stats()

        return StageOutput.ok(
            mixed=True,
            fast_count=self.fast_count,
            slow_count=self.slow_count,
            execution_time_ms=execution_time_ms,
            results=list(results),
            tracker_stats=stats,
        )


class PriorityTestStage:
    """Stage for testing priority-based execution."""
    name = "priority_test"
    kind = StageKind.WORK

    def __init__(self, tools_per_priority: int = 2):
        self.tools_per_priority = tools_per_priority
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()

        async def execute_priority(priority: int, i: int) -> Dict[str, Any]:
            action = {"type": "PRIORITY_OPERATION", "payload": {"priority": priority, "index": i}}
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                return {"priority": priority, "index": i, "success": result.success, "data": result.data}
            except Exception as e:
                return {"priority": priority, "index": i, "success": False, "error": str(e)}

        tasks = []
        for priority in [0, 5, 10]:
            for i in range(self.tools_per_priority):
                tasks.append(execute_priority(priority, i))

        results = await asyncio.gather(*tasks)

        execution_time_ms = (time.time() - start_time) * 1000

        return StageOutput.ok(
            priority_test=True,
            tools_per_priority=self.tools_per_priority,
            execution_time_ms=execution_time_ms,
            results=list(results),
        )


class BaselinePipeline:
    """Baseline pipeline for concurrent tool execution testing."""

    def __init__(self, test_name: str, tool_count: int = 4):
        self.test_name = test_name
        self.tool_count = tool_count
        self.results: List[Dict[str, Any]] = []
        self.start_time: float = 0
        self.end_time: float = 0
        self.tracker = ExecutionTracker()

    def create_pipeline(self) -> Pipeline:
        """Create the baseline test pipeline."""
        pipeline = Pipeline()

        pipeline = pipeline.with_stage(
            "sequential_test",
            SequentialExecutionStage(tool_count=min(self.tool_count, 3)),
            StageKind.WORK,
        )

        pipeline = pipeline.with_stage(
            "parallel_test",
            ParallelExecutionStage(tool_count=self.tool_count),
            StageKind.WORK,
        )

        pipeline = pipeline.with_stage(
            "mixed_test",
            MixedExecutionStage(fast_count=self.tool_count, slow_count=2),
            StageKind.WORK,
        )

        pipeline = pipeline.with_stage(
            "priority_test",
            PriorityTestStage(tools_per_priority=2),
            StageKind.WORK,
        )

        return pipeline

    async def run_test(self) -> Dict[str, Any]:
        """Run the baseline test and return results."""
        self.start_time = time.time()
        self.tracker.reset()

        try:
            pipeline = self.create_pipeline()

            snapshot = create_test_snapshot(input_text="Concurrent tool execution test")

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
                    "tool_count": self.tool_count,
                },
            )

            graph = pipeline.build()
            result = await graph.run(ctx)

            self.end_time = time.time()
            tracker_stats = self.tracker.get_stats()

            test_result = {
                "test_name": self.test_name,
                "tool_count": self.tool_count,
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
                        "success": stage_result.data.get("success", stage_result.status.value == "ok"),
                    }

                    if stage_result.status.value == "fail":
                        test_result["errors"].append({
                            "stage": stage_name,
                            "error": stage_result.error,
                        })

            logger.info(f"Baseline test '{self.test_name}' completed in {test_result['total_duration_ms']:.2f}ms")
            logger.info(f"  Pipeline status: {result.status}")
            logger.info(f"  Tracker stats: {json.dumps(tracker_stats, indent=2)}")

            return test_result

        except Exception as e:
            self.end_time = time.time()
            return {
                "test_name": self.test_name,
                "tool_count": self.tool_count,
                "total_duration_ms": (self.end_time - self.start_time) * 1000,
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }


async def run_baseline_tests() -> List[Dict[str, Any]]:
    """Run all baseline concurrent execution tests."""
    results = []

    test_cases = [
        ("baseline_sequential", 3),
        ("baseline_parallel_2", 2),
        ("baseline_parallel_4", 4),
        ("baseline_parallel_6", 6),
        ("baseline_mixed", 4),
    ]

    tracker = ExecutionTracker()
    for test_name, tool_count in test_cases:
        logger.info(f"Running baseline test: {test_name}")
        pipeline = BaselinePipeline(test_name, tool_count)
        result = await pipeline.run_test()
        results.append(result)
        tracker.reset()

    return results


if __name__ == "__main__":
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    results = asyncio.run(run_baseline_tests())

    output_file = results_dir / "baseline_test_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"Baseline tests completed. Results saved to {output_file}")
    print(json.dumps(results, indent=2, default=str))
