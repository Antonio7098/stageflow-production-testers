"""
WORK-007 Tool Timeout Management - Stress Pipeline

Tests concurrent tool timeout scenarios:
- Multiple tools timing out simultaneously
- Resource contention during timeout cascade
- High-concurrency timeout handling
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
from stageflow.stages.context import ContextSnapshot
from stageflow.tools import BaseTool, ToolInput, ToolOutput, get_tool_registry

from mocks.work007.tool_mocks import (
    SlowTool,
    ConfigurableTimeoutTool,
    ErrorInjectionTool,
    create_mock_tool_registry,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConcurrentToolStage:
    """Stage that executes multiple tools concurrently with individual timeouts."""
    name = "concurrent_tools"
    kind = StageKind.WORK

    def __init__(
        self,
        num_tools: int = 10,
        timeout_ms: int = 3000,
        execution_time_ms: int = 5000,
        stagger_ms: int = 0,
    ):
        self.num_tools = num_tools
        self.timeout_ms = timeout_ms
        self.execution_time_ms = execution_time_ms
        self.stagger_ms = stagger_ms
        self.registry = get_tool_registry()

        for i in range(num_tools):
            self.registry.register(SlowTool(
                execution_time_ms=execution_time_ms,
                fail_count=0,
            ))

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()

        async def run_tool_with_timeout(tool_id: int) -> Dict[str, Any]:
            if self.stagger_ms > 0:
                await asyncio.sleep(self.stagger_ms * tool_id / 1000.0)

            tool_start = time.time()
            timeout_occurred = False
            error = None

            try:
                async with asyncio.timeout(self.timeout_ms / 1000.0):
                    action = {"type": "SLOW_OPERATION", "payload": {}}
                    result = await self.registry.execute(action, ctx.to_dict())
                    return {
                        "tool_id": tool_id,
                        "success": result.success,
                        "execution_time_ms": (time.time() - tool_start) * 1000,
                        "timeout_occurred": False,
                    }

            except asyncio.TimeoutError:
                timeout_occurred = True
                return {
                    "tool_id": tool_id,
                    "success": False,
                    "execution_time_ms": (time.time() - tool_start) * 1000,
                    "timeout_occurred": True,
                    "error": "Timeout exceeded",
                }

            except Exception as e:
                return {
                    "tool_id": tool_id,
                    "success": False,
                    "execution_time_ms": (time.time() - tool_start) * 1000,
                    "error": str(e),
                }

        tasks = [run_tool_with_timeout(i) for i in range(self.num_tools)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        execution_time_ms = (time.time() - start_time) * 1000

        successful = sum(1 for r in results if isinstance(r, dict) and r.get("success", False))
        timed_out = sum(1 for r in results if isinstance(r, dict) and r.get("timeout_occurred", False))
        errors = [r for r in results if isinstance(r, dict) and r.get("error")]

        return StageOutput.ok(
            concurrent_test=True,
            num_tools=self.num_tools,
            timeout_ms=self.timeout_ms,
            execution_time_ms=execution_time_ms,
            successful_count=successful,
            timed_out_count=timed_out,
            error_count=len(errors),
            success_rate=successful / self.num_tools if self.num_tools > 0 else 0,
            results=results if all(isinstance(r, dict) for r in results) else [],
            all_timed_out=timed_out == self.num_tools,
        )


class FanOutFanInTimeoutStage:
    """Tests fan-out/fan-in pattern with timeouts on workers."""
    name = "fan_out_fan_in"
    kind = StageKind.WORK

    def __init__(
        self,
        num_workers: int = 10,
        timeout_ms: int = 3000,
        slow_worker_ratio: float = 0.5,
    ):
        self.num_workers = num_workers
        self.timeout_ms = timeout_ms
        self.slow_worker_ratio = slow_worker_ratio
        self.registry = get_tool_registry()

        for i in range(num_workers):
            execution_time = 5000 if i < (num_workers * slow_worker_ratio) else 100
            self.registry.register(SlowTool(execution_time_ms=execution_time))

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()

        async def worker(worker_id: int) -> Dict[str, Any]:
            tool_start = time.time()
            timeout_occurred = False

            try:
                async with asyncio.timeout(self.timeout_ms / 1000.0):
                    action = {"type": "SLOW_OPERATION", "payload": {}}
                    result = await self.registry.execute(action, ctx.to_dict())
                    return {
                        "worker_id": worker_id,
                        "success": result.success,
                        "execution_time_ms": (time.time() - tool_start) * 1000,
                        "timeout_occurred": False,
                    }

            except asyncio.TimeoutError:
                return {
                    "worker_id": worker_id,
                    "success": False,
                    "execution_time_ms": (time.time() - tool_start) * 1000,
                    "timeout_occurred": True,
                    "error": "Timeout exceeded",
                }

        tasks = [worker(i) for i in range(self.num_workers)]
        results = await asyncio.gather(*tasks)

        execution_time_ms = (time.time() - start_time) * 1000

        successful = sum(1 for r in results if r.get("success", False))
        timed_out = sum(1 for r in results if r.get("timeout_occurred", False))

        return StageOutput.ok(
            fan_out_fan_in=True,
            num_workers=self.num_workers,
            timeout_ms=self.timeout_ms,
            execution_time_ms=execution_time_ms,
            successful_count=successful,
            timed_out_count=timed_out,
            success_rate=successful / self.num_workers if self.num_workers > 0 else 0,
            results=results,
            aggregation_complete=True,
        )


class ResourceContentionStage:
    """Tests resource contention during concurrent timeouts."""
    name = "resource_contention"
    kind = StageKind.WORK

    def __init__(
        self,
        num_concurrent: int = 50,
        timeout_ms: int = 2000,
        shared_resource_delay_ms: int = 100,
    ):
        self.num_concurrent = num_concurrent
        self.timeout_ms = timeout_ms
        self.shared_resource_delay_ms = shared_resource_delay_ms
        self.semaphore = asyncio.Semaphore(10)
        self.registry = get_tool_registry()

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        shared_counter = {"value": 0}
        lock = asyncio.Lock()

        async def contended_tool(tool_id: int) -> Dict[str, Any]:
            tool_start = time.time()
            timeout_occurred = False

            try:
                async with asyncio.timeout(self.timeout_ms / 1000.0):
                    async with self.semaphore:
                        async with lock:
                            shared_counter["value"] += 1
                            counter_value = shared_counter["value"]

                        await asyncio.sleep(self.shared_resource_delay_ms / 1000.0)

                    return {
                        "tool_id": tool_id,
                        "success": True,
                        "counter_value": counter_value,
                        "execution_time_ms": (time.time() - tool_start) * 1000,
                        "timeout_occurred": False,
                    }

            except asyncio.TimeoutError:
                return {
                    "tool_id": tool_id,
                    "success": False,
                    "execution_time_ms": (time.time() - tool_start) * 1000,
                    "timeout_occurred": True,
                }

        tasks = [contended_tool(i) for i in range(self.num_concurrent)]
        results = await asyncio.gather(*tasks)

        execution_time_ms = (time.time() - start_time) * 1000

        successful = sum(1 for r in results if r.get("success", False))
        timed_out = sum(1 for r in results if r.get("timeout_occurred", False))

        return StageOutput.ok(
            resource_contention=True,
            num_concurrent=self.num_concurrent,
            timeout_ms=self.timeout_ms,
            execution_time_ms=execution_time_ms,
            successful_count=successful,
            timed_out_count=timed_out,
            final_counter_value=shared_counter["value"],
            success_rate=successful / self.num_concurrent if self.num_concurrent > 0 else 0,
            results=results[:10],
        )


class StressPipeline:
    """Stress test pipeline for concurrent tool timeouts."""

    def __init__(self, test_name: str, timeout_ms: int = 3000):
        self.test_name = test_name
        self.timeout_ms = timeout_ms
        self.results: List[Dict[str, Any]] = []
        self.start_time: float = 0
        self.end_time: float = 0

    def create_pipeline(self) -> Pipeline:
        pipeline = Pipeline()

        pipeline.add_stage(
            "concurrent_tools",
            ConcurrentToolStage(
                num_tools=20,
                timeout_ms=self.timeout_ms,
                execution_time_ms=5000,
            ),
            StageKind.WORK,
        )

        pipeline.add_stage(
            "fan_out_fan_in",
            FanOutFanInTimeoutStage(
                num_workers=10,
                timeout_ms=self.timeout_ms,
                slow_worker_ratio=0.5,
            ),
            StageKind.WORK,
        )

        pipeline.add_stage(
            "resource_contention",
            ResourceContentionStage(
                num_concurrent=30,
                timeout_ms=self.timeout_ms,
            ),
            StageKind.WORK,
        )

        return pipeline

    async def run_test(self) -> Dict[str, Any]:
        self.start_time = time.time()

        try:
            pipeline = self.create_pipeline()

            snapshot = ContextSnapshot(
                input_text="Stress test",
                session_id=uuid4(),
                user_id=uuid4(),
            )

            ctx = PipelineContext(
                run_id=uuid4(),
                request_id=uuid4(),
                user_id=snapshot.user_id,
                session_id=snapshot.session_id,
                topology=pipeline.stage_specs,
                data={
                    "_timeout_ms": self.timeout_ms,
                    "test_name": self.test_name,
                },
            )

            result = await pipeline.run(ctx)

            self.end_time = time.time()

            test_result = {
                "test_name": self.test_name,
                "timeout_ms": self.timeout_ms,
                "total_duration_ms": (self.end_time - self.start_time) * 1000,
                "success": result.status == "completed",
                "result_status": result.status,
                "outputs": {},
                "summary": {},
            }

            for stage_name, stage_result in result.outputs.items():
                if stage_result:
                    test_result["outputs"][stage_name] = {
                        "successful_count": stage_result.data.get("successful_count", 0),
                        "timed_out_count": stage_result.data.get("timed_out_count", 0),
                        "execution_time_ms": stage_result.data.get("execution_time_ms", 0),
                        "success_rate": stage_result.data.get("success_rate", 0),
                    }

            test_result["summary"] = {
                "total_successful": sum(
                    o.get("successful_count", 0) for o in test_result["outputs"].values()
                ),
                "total_timed_out": sum(
                    o.get("timed_out_count", 0) for o in test_result["outputs"].values()
                ),
            }

            logger.info(f"Stress test '{self.test_name}' completed in {test_result['total_duration_ms']:.2f}ms")
            logger.info(f"  Status: {result.status}")
            logger.info(f"  Total successful: {test_result['summary']['total_successful']}")
            logger.info(f"  Total timed out: {test_result['summary']['total_timed_out']}")

            return test_result

        except Exception as e:
            self.end_time = time.time()
            return {
                "test_name": self.test_name,
                "timeout_ms": self.timeout_ms,
                "total_duration_ms": (self.end_time - self.start_time) * 1000,
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }


async def run_stress_tests() -> List[Dict[str, Any]]:
    """Run all stress tests."""
    results = []

    test_cases = [
        ("stress_20_concurrent", 3000),
        ("stress_50_concurrent", 5000),
        ("stress_short_timeout", 1000),
        ("stress_resource_content", 3000),
    ]

    for test_name, timeout_ms in test_cases:
        pipeline = StressPipeline(test_name, timeout_ms)
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
