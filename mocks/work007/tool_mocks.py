"""
WORK-007 Tool Timeout Management - Mock Tools

Mock tools with configurable timeout behavior for stress-testing tool timeout management
in the Stageflow framework.
"""

import asyncio
import time
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum

from stageflow.tools import BaseTool, ToolInput, ToolOutput


class ToolBehavior(Enum):
    """Enum defining mock tool behavior modes."""
    NORMAL = "normal"  # Completes successfully
    SLOW = "slow"  # Takes longer than default timeout
    PARTIAL_HANG = "partial_hang"  # Returns partial results, then hangs
    STREAMING_SLOW = "streaming_slow"  # Streams slowly, may timeout mid-stream
    IMMEDIATE_ERROR = "immediate_error"  # Fails immediately
    HANG_FOREVER = "hang_forever"  # Never completes
    HEARTBEAT = "heartbeat"  # Reports progress, extends timeout


@dataclass
class MockToolConfig:
    """Configuration for mock tool behavior."""
    behavior: ToolBehavior = ToolBehavior.NORMAL
    execution_time_ms: int = 100  # Base execution time
    partial_result_delay_ms: int = 500  # Time before hanging
    stream_chunk_delay_ms: int = 100  # Delay between stream chunks
    total_stream_items: int = 20  # Total items in streaming response
    heartbeat_interval_ms: int = 500  # Heartbeat report interval
    timeout_extension_ms: int = 2000  # How much to extend timeout by
    fail_on_count: Optional[int] = None  # Fail after N executions


class SlowTool(BaseTool):
    """
    A tool that simulates slow external API calls.

    This tool is designed to test timeout behavior by intentionally
    executing longer than the configured timeout.
    """
    name = "slow_tool"
    description = "Simulates a slow external API call"
    action_type = "SLOW_OPERATION"

    def __init__(
        self,
        execution_time_ms: int = 5000,
        fail_count: Optional[int] = None,
    ):
        self.execution_time_ms = execution_time_ms
        self.fail_count = fail_count
        self.execution_count = 0

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        self.execution_count += 1

        if self.fail_count and self.execution_count <= self.fail_count:
            return ToolOutput(
                success=False,
                error=f"Simulated failure on attempt {self.execution_count}",
            )

        await asyncio.sleep(self.execution_time_ms / 1000.0)

        return ToolOutput(
            success=True,
            data={
                "execution_time_ms": self.execution_time_ms,
                "attempt": self.execution_count,
                "completed_at": time.time(),
            },
        )


class PartialResultTool(BaseTool):
    """
    A tool that returns partial results then hangs.

    Tests whether partial results are accessible after timeout.
    """
    name = "partial_result_tool"
    description = "Returns partial results, then simulates hanging"
    action_type = "PARTIAL_OPERATION"

    def __init__(
        self,
        partial_delay_ms: int = 500,
        hang_forever: bool = True,
    ):
        self.partial_delay_ms = partial_delay_ms
        self.hang_forever = hang_forever
        self.partial_results = {
            "items_processed": 5,
            "total_items": 100,
            "status": "in_progress",
        }

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        await asyncio.sleep(self.partial_delay_ms / 1000.0)

        if self.hang_forever:
            await asyncio.sleep(3600)  # Hang for 1 hour

        return ToolOutput(
            success=True,
            data={
                **self.partial_results,
                "completed_at": time.time(),
            },
        )


class StreamingTool(BaseTool):
    """
    A tool that streams results slowly.

    Tests timeout behavior during streaming operations.
    """
    name = "streaming_tool"
    description = "Streams results with configurable chunk delay"
    action_type = "STREAMING_OPERATION"

    def __init__(
        self,
        chunk_delay_ms: int = 500,
        total_chunks: int = 10,
        fail_on_chunk: Optional[int] = None,
    ):
        self.chunk_delay_ms = chunk_delay_ms
        self.total_chunks = total_chunks
        self.fail_on_chunk = fail_on_chunk

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        chunks = []

        for i in range(self.total_chunks):
            if self.fail_on_chunk and i == self.fail_on_chunk:
                return ToolOutput(
                    success=False,
                    error=f"Failed on chunk {i}",
                    data={"chunks_received": chunks},
                )

            chunks.append(f"chunk_{i}")

            if self.chunk_delay_ms > 0:
                await asyncio.sleep(self.chunk_delay_ms / 1000.0)

        return ToolOutput(
            success=True,
            data={
                "chunks": chunks,
                "total_chunks": len(chunks),
            },
        )


class HeartbeatTool(BaseTool):
    """
    A tool that reports progress via heartbeat.

    Tests whether heartbeat patterns can prevent premature timeout.
    """
    name = "heartbeat_tool"
    description = "Reports progress via heartbeat pattern"
    action_type = "HEARTBEAT_OPERATION"

    def __init__(
        self,
        total_work: int = 10,
        work_item_delay_ms: int = 200,
        heartbeat_interval_ms: int = 500,
        heartbeat_callback=None,
    ):
        self.total_work = total_work
        self.work_item_delay_ms = work_item_delay_ms
        self.heartbeat_interval_ms = heartbeat_interval_ms
        self.heartbeat_callback = heartbeat_callback
        self.last_heartbeat_time = 0

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        completed_items = []
        start_time = time.time()

        for i in range(self.total_work):
            current_time = time.time()

            if current_time - self.last_heartbeat_time >= (self.heartbeat_interval_ms / 1000.0):
                self.last_heartbeat_time = current_time
                if self.heartbeat_callback:
                    await self.heartbeat_callback(i, self.total_work)

            await asyncio.sleep(self.work_item_delay_ms / 1000.0)
            completed_items.append(f"item_{i}")

        return ToolOutput(
            success=True,
            data={
                "completed_items": completed_items,
                "total_items": len(completed_items),
                "execution_time_ms": (time.time() - start_time) * 1000,
            },
        )


class ConfigurableTimeoutTool(BaseTool):
    """
    A tool with configurable timeout behavior per execution.

    Tests per-execution timeout configuration.
    """
    name = "configurable_timeout_tool"
    description = "Tool with configurable timeout behavior"
    action_type = "CONFIGURABLE_TIMEOUT"

    def __init__(self):
        self.executions: list[Dict[str, Any]] = []
        self.config: MockToolConfig = MockToolConfig()

    def configure(self, config: MockToolConfig):
        """Configure the tool behavior for next execution."""
        self.config = config

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        execution_record = {
            "start_time": time.time(),
            "config": self.config.behavior.value,
        }

        try:
            if self.config.behavior == ToolBehavior.NORMAL:
                await asyncio.sleep(self.config.execution_time_ms / 1000.0)
                result = {"status": "completed", "items": list(range(5))}

            elif self.config.behavior == ToolBehavior.SLOW:
                await asyncio.sleep(self.config.execution_time_ms / 1000.0)
                result = {"status": "completed_slow", "items": list(range(5))}

            elif self.config.behavior == ToolBehavior.PARTIAL_HANG:
                await asyncio.sleep(self.config.partial_result_delay_ms / 1000.0)
                result = {"partial": True, "items_processed": 3}
                await asyncio.sleep(3600)  # Hang forever
                result["status"] = "completed"

            elif self.config.behavior == ToolBehavior.STREAMING_SLOW:
                chunks = []
                for i in range(self.config.total_stream_items):
                    await asyncio.sleep(self.config.stream_chunk_delay_ms / 1000.0)
                    chunks.append(f"chunk_{i}")
                result = {"chunks": chunks, "total": len(chunks)}

            elif self.config.behavior == ToolBehavior.IMMEDIATE_ERROR:
                result = {"status": "error"}
                return ToolOutput(
                    success=False,
                    error="Simulated immediate error",
                    data=result,
                )

            elif self.config.behavior == ToolBehavior.HANG_FOREVER:
                await asyncio.sleep(self.config.execution_time_ms / 1000.0)
                await asyncio.sleep(3600)  # Hang forever
                result = {"status": "completed"}

            elif self.config.behavior == ToolBehavior.HEARTBEAT:
                completed = []
                for i in range(5):
                    await asyncio.sleep(self.work_item_delay_ms / 1000.0)
                    completed.append(i)
                result = {"completed": completed, "total": 5}

            else:
                result = {"status": "unknown_behavior"}

            execution_record["result"] = result
            execution_record["success"] = True

            return ToolOutput(success=True, data=result)

        except asyncio.CancelledError:
            execution_record["success"] = False
            execution_record["cancelled"] = True
            raise

        except Exception as e:
            execution_record["success"] = False
            execution_record["error"] = str(e)
            return ToolOutput(success=False, error=str(e))

        finally:
            execution_record["end_time"] = time.time()
            self.executions.append(execution_record)


class ErrorInjectionTool(BaseTool):
    """
    A tool that can inject various error conditions.

    Tests error handling and recovery patterns.
    """
    name = "error_injection_tool"
    description = "Tool for injecting various error conditions"
    action_type = "ERROR_INJECTION"

    def __init__(self):
        self.execution_log: list[Dict[str, Any]] = []

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        error_type = input.action.payload.get("error_type", "none")
        delay_ms = input.action.payload.get("delay_ms", 0)
        should_raise = input.action.payload.get("should_raise", False)

        execution = {
            "error_type": error_type,
            "delay_ms": delay_ms,
            "timestamp": time.time(),
        }

        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)

        if should_raise:
            if error_type == "timeout":
                raise asyncio.TimeoutError("Simulated timeout error")
            elif error_type == "connection":
                raise ConnectionError("Simulated connection error")
            elif error_type == "value":
                raise ValueError("Simulated value error")
            else:
                raise Exception(f"Simulated {error_type} error")

        if error_type == "timeout":
            await asyncio.sleep(60)  # Simulate timeout by hanging
            return ToolOutput(success=False, error="Timeout exceeded")

        execution["status"] = "completed"
        self.execution_log.append(execution)

        return ToolOutput(
            success=True,
            data={"injected_error": error_type, "status": "completed"},
        )


class ResourceCleanupTool(BaseTool):
    """
    A tool that tracks resource cleanup on timeout.

    Tests whether cleanup handlers are properly called.
    """
    name = "resource_cleanup_tool"
    description = "Tool that tracks resource cleanup on timeout"
    action_type = "RESOURCE_CLEANUP"

    def __init__(self):
        self.resource_allocated = False
        self.cleanup_called = False
        self.allocation_time: Optional[float] = None
        self.cleanup_time: Optional[float] = None
        self.execution_log: list[Dict[str, Any]] = []

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        self.execution_log.append({"event": "execute_start", "time": time.time()})

        self.resource_allocated = True
        self.allocation_time = time.time()
        self.execution_log.append({"event": "resource_allocated", "time": self.allocation_time})

        delay_ms = input.action.payload.get("delay_ms", 0)
        should_timeout = input.action.payload.get("should_timeout", False)

        try:
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)

            if should_timeout:
                await asyncio.sleep(60)
                self.execution_log.append({"event": "timeout_triggered", "time": time.time()})

        except asyncio.CancelledError:
            self.execution_log.append({"event": "cancelled", "time": time.time()})
            raise

        finally:
            if self.resource_allocated and not self.cleanup_called:
                self.cleanup_called = True
                self.cleanup_time = time.time()
                self.execution_log.append({
                    "event": "cleanup",
                    "time": self.cleanup_time,
                    "allocated_for": (self.cleanup_time - self.allocation_time) * 1000,
                })

        return ToolOutput(
            success=True,
            data={
                "resource_allocated": self.resource_allocated,
                "cleanup_called": self.cleanup_called,
                "execution_log": self.execution_log,
            },
        )


def create_mock_tool_registry():
    """Create a registry with all mock tools for testing."""
    from stageflow.tools import register_tool, get_tool_registry

    registry = get_tool_registry()

    registry.register(SlowTool())
    registry.register(PartialResultTool())
    registry.register(StreamingTool())
    registry.register(HeartbeatTool())
    registry.register(ConfigurableTimeoutTool())
    registry.register(ErrorInjectionTool())
    registry.register(ResourceCleanupTool())

    return registry
