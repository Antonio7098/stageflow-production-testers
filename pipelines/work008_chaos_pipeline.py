"""
WORK-008 Concurrent Tool Execution Limits - Chaos Pipeline

Tests failure scenarios and edge cases:
- Race conditions on shared state
- Cascading failures
- Resource exhaustion
- Priority inversion
- Starvation scenarios
"""

import asyncio
import json
import logging
import random
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
    FailingTool,
    RaceConditionTool,
    ResourceIntensiveTool,
    PriorityTool,
    register_concurrency_tools,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RaceConditionStage:
    """Stage that tests for race conditions on shared state."""
    name = "race_condition_test"
    kind = StageKind.WORK

    def __init__(self, tool_count: int = 10):
        self.tool_count = tool_count
        self.shared_counter = {"counter": 0}
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()

        race_tool = RaceConditionTool(shared_counter=self.shared_counter)
        self.registry.register(race_tool)

        async def execute_race(i: int) -> Dict[str, Any]:
            action = {"type": "RACE_CONDITION", "payload": {"index": i}}
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                return {
                    "index": i,
                    "success": result.success,
                    "counter": result.data.get("counter_value", 0) if result.success else None,
                }
            except Exception as e:
                return {
                    "index": i,
                    "success": False,
                    "error": str(e),
                }

        tasks = [execute_race(i) for i in range(self.tool_count)]
        results = await asyncio.gather(*tasks)

        execution_time_ms = (time.time() - start_time) * 1000
        final_counter = self.shared_counter["counter"]

        expected_counter = self.tool_count
        race_detected = final_counter != expected_counter

        return StageOutput.ok(
            race_condition_test=True,
            tool_count=self.tool_count,
            expected_counter=expected_counter,
            actual_counter=final_counter,
            race_detected=race_detected,
            execution_time_ms=execution_time_ms,
            results=results,
        )


class CascadingFailureStage:
    """Stage that tests cascading failure behavior."""
    name = "cascading_failure_test"
    kind = StageKind.WORK

    def __init__(self, total_tools: int = 20, fail_ratio: float = 0.3):
        self.total_tools = total_tools
        self.fail_ratio = fail_ratio
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()

        failing_tool = FailingTool(fail_after_n=int(self.total_tools * (1 - self.fail_ratio)))
        self.registry.register(failing_tool)

        results = []
        for i in range(self.total_tools):
            action = {"type": "FAILING_OPERATION", "payload": {"index": i}}
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                results.append({
                    "index": i,
                    "success": result.success,
                    "error": result.error,
                })
            except Exception as e:
                results.append({
                    "index": i,
                    "success": False,
                    "error": str(e),
                })

        execution_time_ms = (time.time() - start_time) * 1000
        successful = [r for r in results if r.get("success", False)]
        failed = [r for r in results if not r.get("success", False)]

        return StageOutput.ok(
            cascading_failure_test=True,
            total_tools=self.total_tools,
            fail_ratio=self.fail_ratio,
            execution_time_ms=execution_time_ms,
            successful_count=len(successful),
            failed_count=len(failed),
            results=results,
        )


class ResourceExhaustionStage:
    """Stage that tests resource exhaustion behavior."""
    name = "resource_exhaustion_test"
    kind = StageKind.WORK

    def __init__(self, tool_count: int = 10, memory_kb: int = 2048):
        self.tool_count = tool_count
        self.memory_kb = memory_kb
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()

        resource_tools = [
            ResourceIntensiveTool(memory_kb=self.memory_kb, duration_ms=100)
            for _ in range(self.tool_count)
        ]

        async def execute_resource(tool: ResourceIntensiveTool, i: int) -> Dict[str, Any]:
            action = {"type": "RESOURCE_INTENSIVE", "payload": {"index": i}}
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                return {
                    "index": i,
                    "success": result.success,
                    "memory_allocated_kb": result.data.get("memory_allocated_kb", 0) if result.success else None,
                }
            except Exception as e:
                return {
                    "index": i,
                    "success": False,
                    "error": str(e),
                }

        tasks = [execute_resource(resource_tools[i], i) for i in range(self.tool_count)]
        results = await asyncio.gather(*tasks)

        execution_time_ms = (time.time() - start_time) * 1000
        successful = [r for r in results if r.get("success", False)]
        failed = [r for r in results if not r.get("success", False)]

        return StageOutput.ok(
            resource_exhaustion_test=True,
            tool_count=self.tool_count,
            memory_kb_per_tool=self.memory_kb,
            execution_time_ms=execution_time_ms,
            successful_count=len(successful),
            failed_count=len(failed),
            results=results,
        )


class PriorityInversionStage:
    """Stage that tests priority inversion scenarios."""
    name = "priority_inversion_test"
    kind = StageKind.WORK

    def __init__(self, low_priority_count: int = 5, high_priority_count: int = 3):
        self.low_priority_count = low_priority_count
        self.high_priority_count = high_priority_count
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()

        priority_results = []

        async def execute_priority_tool(priority: int, i: int, delay_ms: int = 0) -> Dict[str, Any]:
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)
            action = {"type": "PRIORITY_OPERATION", "payload": {"priority": priority, "index": i}}
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                return {
                    "priority": priority,
                    "index": i,
                    "success": result.success,
                    "execution_id": result.data.get("execution_id", "") if result.success else None,
                    "timestamp": time.time(),
                }
            except Exception as e:
                return {
                    "priority": priority,
                    "index": i,
                    "success": False,
                    "error": str(e),
                    "timestamp": time.time(),
                }

        tasks = []
        for i in range(self.low_priority_count):
            tasks.append(execute_priority_tool(0, i, delay_ms=50))

        low_priority_results = await asyncio.gather(*tasks)
        priority_results.extend(low_priority_results)

        for i in range(self.high_priority_count):
            tasks.append(execute_priority_tool(10, i, delay_ms=0))

        high_priority_results = await asyncio.gather(*tasks)
        priority_results.extend(high_priority_results)

        execution_time_ms = (time.time() - start_time) * 1000

        low_priority_completed = [r for r in low_priority_results if r.get("success", False)]
        high_priority_completed = [r for r in high_priority_results if r.get("success", False)]

        return StageOutput.ok(
            priority_inversion_test=True,
            low_priority_count=self.low_priority_count,
            high_priority_count=self.high_priority_count,
            execution_time_ms=execution_time_ms,
            low_priority_completed=len(low_priority_completed),
            high_priority_completed=len(high_priority_completed),
            priority_results=priority_results,
        )


class StarvationStage:
    """Stage that tests starvation scenarios."""
    name = "starvation_test"
    kind = StageKind.WORK

    def __init__(self, high_priority_tools: int = 5, low_priority_tools: int = 5):
        self.high_priority_tools = high_priority_tools
        self.low_priority_tools = low_priority_tools
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()

        slow_tool = SlowTool(execution_time_ms=100)
        self.registry.register(slow_tool)

        results = []

        async def execute_with_delay(tool_type: str, priority: int, i: int, delay_before: int = 0) -> Dict[str, Any]:
            if delay_before > 0:
                await asyncio.sleep(delay_before / 1000.0)
            
            action = {"type": "SLOW_OPERATION", "payload": {"type": tool_type, "priority": priority, "index": i}}
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                return {
                    "type": tool_type,
                    "priority": priority,
                    "index": i,
                    "success": result.success,
                    "timestamp": time.time(),
                    "execution_time": result.data.get("delay_ms", 0) if result.success else 0,
                }
            except Exception as e:
                return {
                    "type": tool_type,
                    "priority": priority,
                    "index": i,
                    "success": False,
                    "error": str(e),
                    "timestamp": time.time(),
                }

        tasks = []
        for i in range(self.high_priority_tools):
            tasks.append(execute_with_delay("high", 10, i, delay_before=i*10))

        high_priority_results = await asyncio.gather(*tasks)

        for i in range(self.low_priority_tools):
            tasks.append(execute_with_delay("low", 0, i, delay_before=0))

        all_results = await asyncio.gather(*high_priority_results + tasks)
        results = list(all_results)

        execution_time_ms = (time.time() - start_time) * 1000

        high_priority_results_filtered = [r for r in results if r.get("type") == "high"]
        low_priority_results_filtered = [r for r in results if r.get("type") == "low"]

        high_priority_avg_time = sum(r.get("execution_time", 0) for r in high_priority_results_filtered) / len(high_priority_results_filtered) if high_priority_results_filtered else 0
        low_priority_avg_time = sum(r.get("execution_time", 0) for r in low_priority_results_filtered) / len(low_priority_results_filtered) if low_priority_results_filtered else 0

        starvation_detected = False
        if low_priority_results_filtered:
            low_priority_avg_completion = sum(r.get("timestamp", 0) for r in low_priority_results_filtered) / len(low_priority_results_filtered)
            high_priority_avg_completion = sum(r.get("timestamp", 0) for r in high_priority_results_filtered) / len(high_priority_results_filtered)
            if low_priority_avg_completion > high_priority_avg_completion + 1.0:
                starvation_detected = True

        return StageOutput.ok(
            starvation_test=True,
            high_priority_tools=self.high_priority_tools,
            low_priority_tools=self.low_priority_tools,
            execution_time_ms=execution_time_ms,
            starvation_detected=starvation_detected,
            high_priority_completed=len(high_priority_results_filtered),
            low_priority_completed=len(low_priority_results_filtered),
            avg_completion_time_high=high_priority_avg_time,
            avg_completion_time_low=low_priority_avg_time,
            results=results,
        )


class MixedFailureStage:
    """Stage with mixed success/failure scenarios."""
    name = "mixed_failure_test"
    kind = StageKind.WORK

    def __init__(self, tool_count: int = 20, failure_rate: float = 0.2):
        self.tool_count = tool_count
        self.failure_rate = failure_rate
        self.registry = get_tool_registry()
        register_concurrency_tools(self.registry)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()

        async def execute_mixed(i: int) -> Dict[str, Any]:
            if random.random() < self.failure_rate:
                action = {"type": "FAILING_OPERATION", "payload": {"index": i}}
            else:
                action = {"type": "FAST_OPERATION", "payload": {"index": i}}
            
            try:
                result = await self.registry.execute(action, ctx.to_dict())
                return {
                    "index": i,
                    "success": result.success,
                    "error": result.error,
                }
            except Exception as e:
                return {
                    "index": i,
                    "success": False,
                    "error": str(e),
                }

        tasks = [execute_mixed(i) for i in range(self.tool_count)]
        results = await asyncio.gather(*tasks)

        execution_time_ms = (time.time() - start_time) * 1000
        successful = [r for r in results if r.get("success", False)]
        failed = [r for r in results if not r.get("success", False)]

        return StageOutput.ok(
            mixed_failure_test=True,
            tool_count=self.tool_count,
            failure_rate=self.failure_rate,
            execution_time_ms=execution_time_ms,
            successful_count=len(successful),
            failed_count=len(failed),
            results=results,
        )


class ChaosPipeline:
    """Chaos pipeline for failure injection testing."""

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.results: List[Dict[str, Any]] = []
        self.start_time: float = 0
        self.end_time: float = 0
        self.tracker = ExecutionTracker()

    def create_pipeline(self) -> Pipeline:
        """Create the chaos test pipeline."""
        pipeline = Pipeline()

        pipeline = pipeline.with_stage(
            "race_condition",
            RaceConditionStage(tool_count=10),
            StageKind.WORK,
        )

        pipeline = pipeline.with_stage(
            "cascading_failure",
            CascadingFailureStage(total_tools=20, fail_ratio=0.3),
            StageKind.WORK,
        )

        pipeline = pipeline.with_stage(
            "resource_exhaustion",
            ResourceExhaustionStage(tool_count=5, memory_kb=2048),
            StageKind.WORK,
        )

        pipeline = pipeline.with_stage(
            "priority_inversion",
            PriorityInversionStage(low_priority_count=5, high_priority_count=3),
            StageKind.WORK,
        )

        pipeline = pipeline.with_stage(
            "starvation",
            StarvationStage(high_priority_tools=3, low_priority_tools=5),
            StageKind.WORK,
        )

        pipeline = pipeline.with_stage(
            "mixed_failure",
            MixedFailureStage(tool_count=20, failure_rate=0.2),
            StageKind.WORK,
        )

        return pipeline

    async def run_test(self) -> Dict[str, Any]:
        """Run the chaos test and return results."""
        self.start_time = time.time()
        self.tracker.reset()

        try:
            pipeline = self.create_pipeline()

            snapshot = create_test_snapshot(input_text="Chaos test concurrent execution")

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
                },
            )

            graph = pipeline.build()
            result = await graph.run(ctx)

            self.end_time = time.time()
            tracker_stats = self.tracker.get_stats()

            test_result = {
                "test_name": self.test_name,
                "total_duration_ms": (self.end_time - self.start_time) * 1000,
                "pipeline_status": result.status,
                "tracker_stats": tracker_stats,
                "stage_outputs": {},
                "issues_detected": [],
                "errors": [],
            }

            for stage_name, stage_result in result.outputs.items():
                if stage_result:
                    stage_data = {
                        "status": stage_result.status.value,
                        "execution_time_ms": stage_result.data.get("execution_time_ms", 0),
                    }

                    if stage_name == "race_condition" and stage_result.data.get("race_detected"):
                        stage_data["race_detected"] = True
                        test_result["issues_detected"].append({
                            "type": "race_condition",
                            "severity": "high",
                            "details": "Race condition detected on shared counter",
                        })

                    if stage_name == "priority_inversion":
                        stage_data["priority_inversion"] = True

                    if stage_name == "starvation" and stage_result.data.get("starvation_detected"):
                        stage_data["starvation_detected"] = True
                        test_result["issues_detected"].append({
                            "type": "starvation",
                            "severity": "medium",
                            "details": "Low priority tasks delayed due to high priority tasks",
                        })

                    if stage_result.status.value == "fail":
                        test_result["errors"].append({
                            "stage": stage_name,
                            "error": stage_result.error,
                        })

                    test_result["stage_outputs"][stage_name] = stage_data

            logger.info(f"Chaos test '{self.test_name}' completed in {test_result['total_duration_ms']:.2f}ms")
            logger.info(f"  Pipeline status: {result.status}")
            logger.info(f"  Issues detected: {len(test_result['issues_detected'])}")

            return test_result

        except Exception as e:
            self.end_time = time.time()
            return {
                "test_name": self.test_name,
                "total_duration_ms": (self.end_time - self.start_time) * 1000,
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }


async def run_chaos_tests() -> List[Dict[str, Any]]:
    """Run all chaos tests."""
    results = []

    chaos_pipeline = ChaosPipeline("chaos_full_suite")
    result = await chaos_pipeline.run_test()
    results.append(result)

    return results


if __name__ == "__main__":
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    results = asyncio.run(run_chaos_tests())

    output_file = results_dir / "chaos_test_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"Chaos tests completed. Results saved to {output_file}")
    print(json.dumps(results, indent=2, default=str))
