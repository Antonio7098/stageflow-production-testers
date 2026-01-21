"""
WORK-007 Tool Timeout Management - Chaos Pipeline

Tests failure injection scenarios for tool timeout management:
- Timeout leakage in async generators
- Resource exhaustion during timeout cascade
- Race condition injection
- Forced timeout scenarios
"""

import asyncio
import json
import logging
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional, AsyncGenerator
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
    ErrorInjectionTool,
    ResourceCleanupTool,
    create_mock_tool_registry,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AsyncGeneratorTimeoutStage:
    """Tests timeout leakage in async generators.

    PEP 789: Async Generator Cancellation
    When an async generator is timeout-ed, we need to ensure
    cleanup happens properly and doesn't leak to outer scope.
    """
    name = "async_generator_timeout"
    kind = StageKind.WORK

    def __init__(self, timeout_ms: int = 2000, yield_count: int = 20, yield_delay_ms: int = 500):
        self.timeout_ms = timeout_ms
        self.yield_count = yield_count
        self.yield_delay_ms = yield_delay_ms
        self.generator_cleanup_called = False
        self.yields_after_timeout = 0

    async def slow_generator(self) -> AsyncGenerator[str, None]:
        """Generator that yields items with delay."""
        try:
            for i in range(self.yield_count):
                yield f"item_{i}"
                await asyncio.sleep(self.yield_delay_ms / 1000.0)
        except asyncio.CancelledError:
            self.generator_cleanup_called = True
            raise
        finally:
            self.generator_cleanup_called = True

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        items_collected = []
        timeout_leaked = False
        outer_scope_error = None

        try:
            async with asyncio.timeout(self.timeout_ms / 1000.0):
                async for item in self.slow_generator():
                    items_collected.append(item)
                    if len(items_collected) >= 10:
                        break

        except asyncio.TimeoutError:
            pass

        except Exception as e:
            outer_scope_error = str(e)
            timeout_leaked = True

        execution_time_ms = (time.time() - start_time) * 1000

        return StageOutput.ok(
            async_generator_test=True,
            timeout_ms=self.timeout_ms,
            execution_time_ms=execution_time_ms,
            items_collected=len(items_collected),
            expected_items=10,
            generator_cleanup_called=self.generator_cleanup_called,
            timeout_leaked=timeout_leaked,
            outer_scope_error=outer_scope_error,
            success=not timeout_leaked,
        )


class ResourceExhaustionStage:
    """Tests resource exhaustion during timeout cascade.

    When many tools timeout simultaneously, we need to ensure
    resources are properly cleaned up.
    """
    name = "resource_exhaustion"
    kind = StageKind.WORK

    def __init__(
        self,
        num_tools: int = 100,
        timeout_ms: int = 2000,
        execution_time_ms: int = 10000,
    ):
        self.num_tools = num_tools
        self.timeout_ms = timeout_ms
        self.execution_time_ms = execution_time_ms
        self.cleanup_tools: List[ResourceCleanupTool] = []
        self.registry = get_tool_registry()

    def create_cleanup_tool(self, tool_id: int) -> ResourceCleanupTool:
        tool = ResourceCleanupTool(should_timeout=True)
        self.cleanup_tools.append(tool)
        return tool

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()

        cleanup_tools = [
            self.create_cleanup_tool(i)
            for i in range(self.num_tools)
        ]

        async def run_tool_with_cleanup(tool: ResourceCleanupTool, tool_id: int) -> Dict[str, Any]:
            tool_start = time.time()
            timeout_occurred = False

            try:
                async with asyncio.timeout(self.timeout_ms / 1000.0):
                    action = {"type": "RESOURCE_CLEANUP", "payload": {"should_timeout": True}}
                    result = await self.registry.execute(action, ctx.to_dict())
                    return {
                        "tool_id": tool_id,
                        "success": result.success,
                        "cleanup_called": result.data.get("cleanup_called", False),
                        "execution_time_ms": (time.time() - tool_start) * 1000,
                    }

            except asyncio.TimeoutError:
                timeout_occurred = True
                return {
                    "tool_id": tool_id,
                    "success": False,
                    "timeout_occurred": True,
                    "cleanup_called": tool.cleanup_called,
                    "execution_time_ms": (time.time() - tool_start) * 1000,
                }

        tasks = [run_tool_with_cleanup(tool, i) for i, tool in enumerate(cleanup_tools)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        execution_time_ms = (time.time() - start_time) * 1000

        successful = sum(1 for r in results if isinstance(r, dict) and r.get("success", False))
        timed_out = sum(1 for r in results if isinstance(r, dict) and r.get("timeout_occurred", False))
        cleanups_called = sum(1 for r in results if isinstance(r, dict) and r.get("cleanup_called", False))

        return StageOutput.ok(
            resource_exhaustion=True,
            num_tools=self.num_tools,
            timeout_ms=self.timeout_ms,
            execution_time_ms=execution_time_ms,
            successful_count=successful,
            timed_out_count=timed_out,
            cleanups_called=cleanups_called,
            cleanup_rate=cleanups_called / self.num_tools if self.num_tools > 0 else 0,
            success_rate=successful / self.num_tools if self.num_tools > 0 else 0,
            results=results[:5],
        )


class RaceConditionStage:
    """Tests race conditions between timeout and completion.

    What happens when a tool completes right at the timeout boundary?
    """
    name = "race_condition"
    kind = StageKind.WORK

    def __init__(self, timeout_ms: int = 1000, execution_time_ms: int = 950):
        self.timeout_ms = timeout_ms
        self.execution_time_ms = execution_time_ms
        self.registry = get_tool_registry()

        self.registry.register(SlowTool(execution_time_ms=execution_time_ms))

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        race_results: List[Dict[str, Any]] = []

        for i in range(50):
            race_start = time.time()
            timeout_occurred = False
            success = False

            try:
                async with asyncio.timeout(self.timeout_ms / 1000.0):
                    action = {"type": "SLOW_OPERATION", "payload": {}}
                    result = await self.registry.execute(action, ctx.to_dict())
                    success = result.success

            except asyncio.TimeoutError:
                timeout_occurred = True

            race_results.append({
                "attempt": i,
                "timeout_occurred": timeout_occurred,
                "success": success,
                "execution_time_ms": (time.time() - race_start) * 1000,
            })

        execution_time_ms = (time.time() - start_time) * 1000

        timeout_count = sum(1 for r in race_results if r.get("timeout_occurred"))
        success_count = sum(1 for r in race_results if r.get("success"))

        return StageOutput.ok(
            race_condition=True,
            timeout_ms=self.timeout_ms,
            execution_time_ms=execution_time_ms,
            total_attempts=len(race_results),
            timeout_count=timeout_count,
            success_count=success_count,
            timeout_rate=timeout_count / len(race_results) if race_results else 0,
            success_rate=success_count / len(race_results) if race_results else 0,
            results=race_results,
            deterministic=timeout_count in [0, 50],
        )


class ErrorInjectionStage:
    """Tests various error injection scenarios."""
    name = "error_injection"
    kind = StageKind.WORK

    def __init__(self, timeout_ms: int = 3000):
        self.timeout_ms = timeout_ms
        self.tool = ErrorInjectionTool()
        self.registry = get_tool_registry()
        self.registry.register(self.tool)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        results: List[Dict[str, Any]] = []

        test_cases = [
            {"error_type": "none", "delay_ms": 0, "should_raise": False},
            {"error_type": "timeout", "delay_ms": 0, "should_raise": True},
            {"error_type": "connection", "delay_ms": 100, "should_raise": True},
            {"error_type": "value", "delay_ms": 50, "should_raise": True},
        ]

        for test_case in test_cases:
            test_start = time.time()
            timeout_occurred = False
            tool_error = None

            try:
                async with asyncio.timeout(self.timeout_ms / 1000.0):
                    action = {
                        "type": "ERROR_INJECTION",
                        "payload": test_case,
                    }
                    result = await self.registry.execute(action, ctx.to_dict())

                    if not result.success:
                        tool_error = result.error

            except asyncio.TimeoutError:
                timeout_occurred = True

            except Exception as e:
                tool_error = str(e)

            results.append({
                "error_type": test_case["error_type"],
                "timeout_occurred": timeout_occurred,
                "tool_error": tool_error,
                "execution_time_ms": (time.time() - test_start) * 1000,
            })

        execution_time_ms = (time.time() - start_time) * 1000

        timeouts_handled = sum(1 for r in results if r.get("timeout_occurred"))
        errors_handled = sum(1 for r in results if r.get("tool_error"))

        return StageOutput.ok(
            error_injection=True,
            timeout_ms=self.timeout_ms,
            execution_time_ms=execution_time_ms,
            total_tests=len(results),
            timeouts_handled=timeouts_handled,
            errors_handled=errors_handled,
            results=results,
        )


class ForcedTimeoutStage:
    """Tests forced timeout scenarios with very long-running tools."""
    name = "forced_timeout"
    kind = StageKind.WORK

    def __init__(self, timeout_ms: int = 1000, execution_time_multiplier: int = 10):
        self.timeout_ms = timeout_ms
        self.execution_time_multiplier = execution_time_multiplier
        self.registry = get_tool_registry()

        self.registry.register(SlowTool(
            execution_time_ms=timeout_ms * execution_time_multiplier
        ))

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        timeout_occurred = False
        execution_time_ms = 0

        try:
            async with asyncio.timeout(self.timeout_ms / 1000.0):
                action = {"type": "SLOW_OPERATION", "payload": {}}
                result = await self.registry.execute(action, ctx.to_dict())
                execution_time_ms = (time.time() - start_time) * 1000
                return StageOutput.ok(
                    forced_timeout=True,
                    success=result.success,
                    execution_time_ms=execution_time_ms,
                    timeout_occurred=False,
                )

        except asyncio.TimeoutError:
            timeout_occurred = True
            execution_time_ms = (time.time() - start_time) * 1000
            return StageOutput.ok(
                forced_timeout=True,
                success=False,
                execution_time_ms=execution_time_ms,
                timeout_occurred=True,
                timeout_ms=self.timeout_ms,
                actual_time_ratio=execution_time_ms / self.timeout_ms if self.timeout_ms > 0 else 0,
            )


class ChaosPipeline:
    """Chaos test pipeline for tool timeout failure injection."""

    def __init__(self, test_name: str, timeout_ms: int = 3000):
        self.test_name = test_name
        self.timeout_ms = timeout_ms
        self.results: List[Dict[str, Any]] = []
        self.start_time: float = 0
        self.end_time: float = 0

    def create_pipeline(self) -> Pipeline:
        pipeline = Pipeline()

        pipeline.add_stage(
            "async_generator",
            AsyncGeneratorTimeoutStage(
                timeout_ms=self.timeout_ms,
                yield_count=20,
                yield_delay_ms=500,
            ),
            StageKind.WORK,
        )

        pipeline.add_stage(
            "resource_exhaustion",
            ResourceExhaustionStage(
                num_tools=50,
                timeout_ms=self.timeout_ms,
            ),
            StageKind.WORK,
        )

        pipeline.add_stage(
            "race_condition",
            RaceConditionStage(
                timeout_ms=self.timeout_ms,
                execution_time_ms=self.timeout_ms - 50,
            ),
            StageKind.WORK,
        )

        pipeline.add_stage(
            "error_injection",
            ErrorInjectionStage(timeout_ms=self.timeout_ms),
            StageKind.WORK,
        )

        pipeline.add_stage(
            "forced_timeout",
            ForcedTimeoutStage(
                timeout_ms=self.timeout_ms,
                execution_time_multiplier=10,
            ),
            StageKind.WORK,
        )

        return pipeline

    async def run_test(self) -> Dict[str, Any]:
        self.start_time = time.time()

        try:
            pipeline = self.create_pipeline()

            snapshot = ContextSnapshot(
                input_text="Chaos test",
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
                "issues": [],
            }

            for stage_name, stage_result in result.outputs.items():
                if stage_result:
                    test_result["outputs"][stage_name] = stage_result.data

                    if stage_result.data.get("timeout_leaked", False):
                        test_result["issues"].append({
                            "stage": stage_name,
                            "issue": "Timeout leaked to outer scope",
                            "severity": "high",
                        })

                    if stage_result.data.get("deterministic") == False:
                        test_result["issues"].append({
                            "stage": stage_name,
                            "issue": "Non-deterministic timeout behavior",
                            "severity": "medium",
                        })

            logger.info(f"Chaos test '{self.test_name}' completed in {test_result['total_duration_ms']:.2f}ms")
            logger.info(f"  Status: {result.status}")
            logger.info(f"  Issues found: {len(test_result['issues'])}")

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


async def run_chaos_tests() -> List[Dict[str, Any]]:
    """Run all chaos tests."""
    results = []

    test_cases = [
        ("chaos_generator_timeout", 2000),
        ("chaos_resource_exhaustion", 3000),
        ("chaos_race_condition", 1000),
        ("chaos_error_injection", 3000),
        ("chaos_forced_timeout", 1000),
    ]

    for test_name, timeout_ms in test_cases:
        pipeline = ChaosPipeline(test_name, timeout_ms)
        result = await pipeline.run_test()
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
