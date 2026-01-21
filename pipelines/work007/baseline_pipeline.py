"""
WORK-007 Tool Timeout Management - Baseline Pipeline

Tests basic tool timeout functionality:
- Single tool timeout
- Tool completion before timeout
- Exact timeout boundary
- Tool with partial results
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
    TimeoutInterceptor,
    CircuitBreakerInterceptor,
)
from stageflow import create_test_snapshot
from stageflow.tools import BaseTool, ToolInput, ToolOutput, get_tool_registry

from mocks.work007.tool_mocks import (
    SlowTool,
    PartialResultTool,
    StreamingTool,
    HeartbeatTool,
    ConfigurableTimeoutTool,
    create_mock_tool_registry,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TimeoutTestStage:
    """Stage that executes a tool and reports timeout behavior."""
    name = "timeout_test"
    kind = StageKind.WORK

    def __init__(self, tool_name: str, timeout_ms: int = 3000):
        self.tool_name = tool_name
        self.timeout_ms = timeout_ms
        self.registry = get_tool_registry()

    async def execute(self, ctx: StageContext) -> StageOutput:
        tool_input = ToolInput(
            action=ctx.inputs.get("action", {"type": self.tool_name, "payload": {}})
        )

        start_time = time.time()
        timeout_occurred = False
        partial_result = None

        try:
            async with asyncio.timeout(self.timeout_ms / 1000.0):
                result = await self.registry.execute(tool_input.action, ctx.to_dict())

        except asyncio.TimeoutError:
            timeout_occurred = True
            elapsed_ms = (time.time() - start_time) * 1000
            partial_result = {
                "timeout_ms": self.timeout_ms,
                "elapsed_ms": elapsed_ms,
                "timeout_exceeded": elapsed_ms > self.timeout_ms,
            }

        execution_time_ms = (time.time() - start_time) * 1000

        return StageOutput.ok(
            tool_name=self.tool_name,
            timeout_ms=self.timeout_ms,
            execution_time_ms=execution_time_ms,
            timeout_occurred=timeout_occurred,
            partial_result=partial_result,
            success=not timeout_occurred,
        )


class SlowToolStage:
    """Stage that uses the slow tool for timeout testing."""
    name = "slow_tool_stage"
    kind = StageKind.WORK

    def __init__(self, execution_time_ms: int = 5000, timeout_ms: int = 3000):
        self.execution_time_ms = execution_time_ms
        self.timeout_ms = timeout_ms
        self.tool = SlowTool(execution_time_ms=execution_time_ms)
        self.registry = get_tool_registry()
        self.registry.register(self.tool)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        timeout_occurred = False
        error_result = None

        try:
            async with asyncio.timeout(self.timeout_ms / 1000.0):
                action = {"type": "SLOW_OPERATION", "payload": {}}
                result = await self.registry.execute(action, ctx.to_dict())

        except asyncio.TimeoutError:
            timeout_occurred = True
            error_result = {
                "message": "Tool execution timed out",
                "configured_timeout_ms": self.timeout_ms,
                "tool_execution_time_ms": self.execution_time_ms,
            }

        except Exception as e:
            error_result = {
                "message": str(e),
                "error_type": type(e).__name__,
            }

        execution_time_ms = (time.time() - start_time) * 1000

        return StageOutput.ok(
            slow_tool=True,
            timeout_ms=self.timeout_ms,
            execution_time_ms=execution_time_ms,
            timeout_occurred=timeout_occurred,
            error=error_result,
            success=not timeout_occurred,
        )


class PartialResultTestStage:
    """Tests partial result availability after timeout."""
    name = "partial_result_test"
    kind = StageKind.WORK

    def __init__(self, partial_delay_ms: int = 500, timeout_ms: int = 3000):
        self.partial_delay_ms = partial_delay_ms
        self.timeout_ms = timeout_ms
        self.tool = PartialResultTool(partial_delay_ms=partial_delay_ms)
        self.registry = get_tool_registry()
        self.registry.register(self.tool)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        timeout_occurred = False
        partial_data = None

        try:
            async with asyncio.timeout(self.timeout_ms / 1000.0):
                action = {"type": "PARTIAL_OPERATION", "payload": {}}
                result = await self.registry.execute(action, ctx.to_dict())

                if not result.success:
                    return StageOutput.fail(
                        error=result.error,
                        data=result.data,
                    )

        except asyncio.TimeoutError:
            timeout_occurred = True
            partial_data = {
                "partial_delay_ms": self.partial_delay_ms,
                "configured_timeout_ms": self.timeout_ms,
            }

        execution_time_ms = (time.time() - start_time) * 1000

        return StageOutput.ok(
            partial_result_test=True,
            timeout_ms=self.timeout_ms,
            execution_time_ms=execution_time_ms,
            timeout_occurred=timeout_occurred,
            partial_data_available=partial_data is not None,
            partial_data=partial_data,
            success=not timeout_occurred,
        )


class StreamingTimeoutStage:
    """Tests timeout during streaming tool execution."""
    name = "streaming_timeout_test"
    kind = StageKind.WORK

    def __init__(self, chunk_delay_ms: int = 500, total_chunks: int = 20, timeout_ms: int = 3000):
        self.chunk_delay_ms = chunk_delay_ms
        self.total_chunks = total_chunks
        self.timeout_ms = timeout_ms
        self.tool = StreamingTool(
            chunk_delay_ms=chunk_delay_ms,
            total_chunks=total_chunks,
        )
        self.registry = get_tool_registry()
        self.registry.register(self.tool)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        timeout_occurred = False
        chunks_received = 0

        try:
            async with asyncio.timeout(self.timeout_ms / 1000.0):
                action = {"type": "STREAMING_OPERATION", "payload": {}}
                result = await self.registry.execute(action, ctx.to_dict())

                if result.success:
                    chunks_received = len(result.data.get("chunks", []))
                else:
                    return StageOutput.fail(
                        error=result.error,
                        data=result.data,
                    )

        except asyncio.TimeoutError:
            timeout_occurred = True
            chunks_received = 0

        execution_time_ms = (time.time() - start_time) * 1000

        return StageOutput.ok(
            streaming_test=True,
            timeout_ms=self.timeout_ms,
            execution_time_ms=execution_time_ms,
            timeout_occurred=timeout_occurred,
            chunks_received=chunks_received,
            expected_chunks=self.total_chunks,
            completion_rate=chunks_received / self.total_chunks if self.total_chunks > 0 else 0,
            success=not timeout_occurred,
        )


class BaselinePipeline:
    """Baseline pipeline for tool timeout testing."""

    def __init__(self, test_name: str, timeout_ms: int = 3000):
        self.test_name = test_name
        self.timeout_ms = timeout_ms
        self.results: List[Dict[str, Any]] = []
        self.start_time: float = 0
        self.end_time: float = 0

    def create_pipeline(self) -> Pipeline:
        """Create the baseline test pipeline."""
        pipeline = Pipeline()

        pipeline.add_stage(
            "tool_execution_test",
            TimeoutTestStage(
                tool_name="slow_tool",
                timeout_ms=self.timeout_ms,
            ),
            StageKind.WORK,
        )

        pipeline.add_stage(
            "slow_tool_test",
            SlowToolStage(
                execution_time_ms=5000,
                timeout_ms=self.timeout_ms,
            ),
            StageKind.WORK,
        )

        pipeline.add_stage(
            "partial_result_test",
            PartialResultTestStage(
                partial_delay_ms=500,
                timeout_ms=self.timeout_ms,
            ),
            StageKind.WORK,
        )

        pipeline.add_stage(
            "streaming_test",
            StreamingTimeoutStage(
                chunk_delay_ms=200,
                total_chunks=20,
                timeout_ms=self.timeout_ms,
            ),
            StageKind.WORK,
        )

        return pipeline

    async def run_test(self) -> Dict[str, Any]:
        """Run the baseline test and return results."""
        self.start_time = time.time()

        try:
            pipeline = self.create_pipeline()

            snapshot = create_test_snapshot(input_text="Tool timeout test")

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
                "errors": [],
            }

            for stage_name, stage_result in result.outputs.items():
                if stage_result:
                    test_result["outputs"][stage_name] = {
                        "timeout_occurred": stage_result.data.get("timeout_occurred", False),
                        "execution_time_ms": stage_result.data.get("execution_time_ms", 0),
                        "success": stage_result.data.get("success", False),
                    }

                    if not stage_result.data.get("success", True):
                        test_result["errors"].append({
                            "stage": stage_name,
                            "error": stage_result.data.get("error"),
                        })

            logger.info(f"Baseline test '{self.test_name}' completed in {test_result['total_duration_ms']:.2f}ms")
            logger.info(f"  Status: {result.status}")
            logger.info(f"  Outputs: {json.dumps(test_result['outputs'], indent=2)}")

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


async def run_baseline_tests() -> List[Dict[str, Any]]:
    """Run all baseline timeout tests."""
    results = []

    test_cases = [
        ("baseline_normal", 5000),
        ("baseline_short_timeout", 1000),
        ("baseline_exact_boundary", 500),
        ("baseline_no_timeout", 10000),
    ]

    for test_name, timeout_ms in test_cases:
        pipeline = BaselinePipeline(test_name, timeout_ms)
        result = await pipeline.run_test()
        results.append(result)

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
