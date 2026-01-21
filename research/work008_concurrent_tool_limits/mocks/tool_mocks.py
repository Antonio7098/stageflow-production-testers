"""
Concurrent Tool Execution Mocks for WORK-008

Mocks for testing concurrent tool execution limits:
- ConfigurableConcurrencyTool: Tool with configurable execution time
- PriorityTool: Tool with priority levels
- RateLimitedTool: Simulates API rate limiting
- ResourceIntensiveTool: Consumes memory during execution
- SlowTool: Deliberately slow tool for queue buildup
- FastTool: Quick execution tool
- FailingTool: Tool that fails after N calls
- RaceConditionTool: Tool that may cause race conditions
"""

import asyncio
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set
from uuid import uuid4

from stageflow.tools import (
    BaseTool,
    ToolInput,
    ToolOutput,
    ToolDefinition,
    get_tool_registry,
)
from stageflow.helpers import ChunkQueue

logger = logging.getLogger(__name__)


@dataclass
class ExecutionRecord:
    """Record of a tool execution."""
    tool_name: str
    execution_id: str
    start_time: float
    end_time: Optional[float] = None
    priority: int = 0
    success: bool = True
    error: Optional[str] = None
    execution_time_ms: float = 0.0


class ExecutionTracker:
    """Global tracker for concurrent execution analysis."""
    
    _instance: Optional["ExecutionTracker"] = None
    _lock: asyncio.Lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.records: List[ExecutionRecord] = []
        self.active_executions: Dict[str, ExecutionRecord] = {}
        self.concurrent_count = 0
        self.max_concurrent = 0
        self.start_time = time.time()
        self.lock = asyncio.Lock()
    
    def record_start(self, tool_name: str, priority: int = 0) -> str:
        execution_id = str(uuid4())
        record = ExecutionRecord(
            tool_name=tool_name,
            execution_id=execution_id,
            start_time=time.time(),
            priority=priority,
        )
        self.records.append(record)
        self.active_executions[execution_id] = record
        self.concurrent_count += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent_count)
        return execution_id
    
    def record_end(self, execution_id: str, success: bool = True, error: Optional[str] = None):
        record = self.active_executions.pop(execution_id, None)
        if record:
            record.end_time = time.time()
            record.success = success
            record.error = error
            record.execution_time_ms = (record.end_time - record.start_time) * 1000
            self.concurrent_count -= 1
    
    def get_stats(self) -> Dict[str, Any]:
        total_time = time.time() - self.start_time
        completed = [r for r in self.records if r.end_time is not None]
        successful = [r for r in completed if r.success]
        failed = [r for r in completed if not r.success]
        
        execution_times = [r.execution_time_ms for r in completed]
        
        return {
            "total_executions": len(self.records),
            "completed_executions": len(completed),
            "successful_executions": len(successful),
            "failed_executions": len(failed),
            "max_concurrent": self.max_concurrent,
            "total_duration_ms": total_time * 1000,
            "throughput": len(completed) / total_time if total_time > 0 else 0,
            "avg_execution_time_ms": sum(execution_times) / len(execution_times) if execution_times else 0,
            "min_execution_time_ms": min(execution_times) if execution_times else 0,
            "max_execution_time_ms": max(execution_times) if execution_times else 0,
        }
    
    def reset(self):
        self.records.clear()
        self.active_executions.clear()
        self.concurrent_count = 0
        self.max_concurrent = 0
        self.start_time = time.time()


class ConfigurableConcurrencyTool(BaseTool):
    """Tool with configurable execution parameters for concurrency testing."""
    
    name = "configurable_concurrency"
    description = "Tool with configurable execution time and behavior"
    action_type = "CONFIGURED_CONCURRENCY"
    
    def __init__(
        self,
        execution_time_ms: int = 100,
        fail_rate: float = 0.0,
        fail_after_n: Optional[int] = None,
        priority: int = 0,
    ):
        self.execution_time_ms = execution_time_ms
        self.fail_rate = fail_rate
        self.fail_after_n = fail_after_n
        self.priority = priority
        self.call_count = 0
        self.tracker = ExecutionTracker()
    
    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        self.call_count += 1
        execution_id = self.tracker.record_start(self.name, self.priority)
        
        try:
            await asyncio.sleep(self.execution_time_ms / 1000.0)
            
            if self.fail_after_n and self.call_count > self.fail_after_n:
                raise Exception(f"Failed after {self.fail_after_n} calls")
            
            if random.random() < self.fail_rate:
                raise Exception(f"Random failure (rate={self.fail_rate})")
            
            self.tracker.record_end(execution_id, success=True)
            return ToolOutput.ok(
                data={
                    "execution_id": execution_id,
                    "call_number": self.call_count,
                    "execution_time_ms": self.execution_time_ms,
                    "priority": self.priority,
                }
            )
        except Exception as e:
            self.tracker.record_end(execution_id, success=False, error=str(e))
            return ToolOutput.fail(error=str(e))


class FastTool(BaseTool):
    """Quick execution tool for high-concurrency scenarios."""
    
    name = "fast_tool"
    description = "Fast execution tool (10ms)"
    action_type = "FAST_OPERATION"
    
    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        await asyncio.sleep(0.01)
        return ToolOutput.ok(data={"fast": True, "delay_ms": 10})


class SlowTool(BaseTool):
    """Slow execution tool for queue buildup testing."""
    
    name = "slow_tool"
    description = "Slow execution tool (500ms)"
    action_type = "SLOW_OPERATION"
    
    def __init__(self, execution_time_ms: int = 500):
        self.execution_time_ms = execution_time_ms
        self.tracker = ExecutionTracker()
    
    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        execution_id = self.tracker.record_start(self.name)
        await asyncio.sleep(self.execution_time_ms / 1000.0)
        self.tracker.record_end(execution_id, success=True)
        return ToolOutput.ok(data={"slow": True, "delay_ms": self.execution_time_ms})


class VariableDelayTool(BaseTool):
    """Tool with variable execution time."""
    
    name = "variable_delay_tool"
    description = "Tool with variable execution time"
    action_type = "VARIABLE_DELAY"
    
    def __init__(
        self,
        min_delay_ms: int = 50,
        max_delay_ms: int = 500,
    ):
        self.min_delay_ms = min_delay_ms
        self.max_delay_ms = max_delay_ms
        self.tracker = ExecutionTracker()
    
    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        execution_id = self.tracker.record_start(self.name)
        delay = random.randint(self.min_delay_ms, self.max_delay_ms)
        await asyncio.sleep(delay / 1000.0)
        self.tracker.record_end(execution_id, success=True)
        return ToolOutput.ok(
            data={
                "delay_ms": delay,
                "min_configured": self.min_delay_ms,
                "max_configured": self.max_delay_ms,
            }
        )


class ResourceIntensiveTool(BaseTool):
    """Tool that consumes memory during execution."""
    
    name = "resource_intensive_tool"
    description = "Tool that consumes memory"
    action_type = "RESOURCE_INTENSIVE"
    
    def __init__(self, memory_kb: int = 1024, duration_ms: int = 100):
        self.memory_kb = memory_kb
        self.duration_ms = duration_ms
        self.tracker = ExecutionTracker()
    
    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        execution_id = self.tracker.record_start(self.name)
        
        data = bytearray(self.memory_kb * 1024)
        try:
            await asyncio.sleep(self.duration_ms / 1000.0)
            self.tracker.record_end(execution_id, success=True)
            return ToolOutput.ok(
                data={
                    "memory_allocated_kb": self.memory_kb,
                    "duration_ms": self.duration_ms,
                }
            )
        finally:
            del data


class FailingTool(BaseTool):
    """Tool that fails after a certain number of calls."""
    
    name = "failing_tool"
    description = "Tool that fails after N calls"
    action_type = "FAILING_OPERATION"
    
    def __init__(self, fail_after_n: int = 5, failure_error: str = "Simulated failure"):
        self.fail_after_n = fail_after_n
        self.failure_error = failure_error
        self.call_count = 0
        self.tracker = ExecutionTracker()
    
    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        self.call_count += 1
        execution_id = self.tracker.record_start(self.name)
        
        if self.call_count > self.fail_after_n:
            self.tracker.record_end(execution_id, success=False, error=self.failure_error)
            return ToolOutput.fail(error=self.failure_error)
        
        self.tracker.record_end(execution_id, success=True)
        return ToolOutput.ok(
            data={
                "call_count": self.call_count,
                "fail_after": self.fail_after_n,
            }
        )


class RaceConditionTool(BaseTool):
    """Tool designed to trigger race conditions on shared state."""
    
    name = "race_condition_tool"
    description = "Tool that may cause race conditions"
    action_type = "RACE_CONDITION"
    
    def __init__(self, shared_counter: Optional[Dict[str, int]] = None):
        self.shared_counter = shared_counter or {"counter": 0}
        self.lock = asyncio.Lock()
        self.tracker = ExecutionTracker()
    
    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        execution_id = self.tracker.record_start(self.name)
        
        async with self.lock:
            current = self.shared_counter["counter"]
            await asyncio.sleep(0.001)
            self.shared_counter["counter"] = current + 1
        
        self.tracker.record_end(execution_id, success=True)
        return ToolOutput.ok(
            data={
                "counter_value": self.shared_counter["counter"],
            }
        )


class RateLimitedTool(BaseTool):
    """Tool that simulates rate-limited API behavior."""
    
    name = "rate_limited_tool"
    description = "Tool with simulated rate limiting"
    action_type = "RATE_LIMITED"
    
    def __init__(
        self,
        max_per_second: float = 10.0,
        max_burst: int = 20,
        simulated_delay_ms: int = 50,
    ):
        self.max_per_second = max_per_second
        self.max_burst = max_burst
        self.simulated_delay_ms = simulated_delay_ms
        self.token_bucket: Dict[str, List[float]] = {}
        self.lock = asyncio.Lock()
        self.tracker = ExecutionTracker()
    
    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        execution_id = self.tracker.record_start(self.name)
        
        async with self.lock:
            now = time.time()
            key = "default"
            
            if key not in self.token_bucket:
                self.token_bucket[key] = []
            
            self.token_bucket[key] = [
                t for t in self.token_bucket[key] if now - t < 1.0
            ]
            
            if len(self.token_bucket[key]) >= self.max_burst:
                self.tracker.record_end(execution_id, success=False, error="Rate limit exceeded (burst)")
                return ToolOutput.fail(error="Rate limit exceeded: burst limit reached")
            
            self.token_bucket[key].append(now)
        
        await asyncio.sleep(self.simulated_delay_ms / 1000.0)
        self.tracker.record_end(execution_id, success=True)
        return ToolOutput.ok(
            data={
                "tokens_used": len(self.token_bucket.get("default", [])),
                "max_per_second": self.max_per_second,
                "max_burst": self.max_burst,
            }
        )


class PriorityTool(BaseTool):
    """Tool with priority levels for testing scheduling."""
    
    name = "priority_tool"
    description = "Tool with priority levels"
    action_type = "PRIORITY_OPERATION"
    
    def __init__(self, priority: int = 0):
        self.priority = priority
        self.execution_order: List[Dict[str, Any]] = []
        self.tracker = ExecutionTracker()
    
    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        execution_id = self.tracker.record_start(self.name, self.priority)
        await asyncio.sleep(0.1)
        self.execution_order.append({
            "execution_id": execution_id,
            "priority": self.priority,
            "timestamp": time.time(),
        })
        self.tracker.record_end(execution_id, success=True)
        return ToolOutput.ok(
            data={
                "priority": self.priority,
                "execution_id": execution_id,
            }
        )


class ChainedTool(BaseTool):
    """Tool that triggers other tools via shared registry."""
    
    name = "chained_tool"
    description = "Tool that chains to other tools"
    action_type = "CHAINED_OPERATION"
    
    def __init__(self, chain_depth: int = 3):
        self.chain_depth = chain_depth
        self.tracker = ExecutionTracker()
        self.registry = get_tool_registry()
    
    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        execution_id = self.tracker.record_start(self.name)
        chain_results = []
        
        for i in range(self.chain_depth):
            action = {"type": "FAST_OPERATION", "payload": {"chain_level": i}}
            try:
                result = await self.registry.execute(action, ctx)
                chain_results.append({"level": i, "success": result.success})
            except Exception as e:
                chain_results.append({"level": i, "success": False, "error": str(e)})
        
        self.tracker.record_end(execution_id, success=True)
        return ToolOutput.ok(
            data={
                "chain_depth": self.chain_depth,
                "chain_results": chain_results,
            }
        )


class BulkToolExecutor:
    """Utility for executing multiple tools concurrently."""
    
    def __init__(self):
        self.tracker = ExecutionTracker()
    
    async def execute_all(
        self,
        tools: List[BaseTool],
        max_concurrent: Optional[int] = None,
    ) -> List[ToolOutput]:
        semaphore = asyncio.Semaphore(max_concurrent or len(tools))
        results = []
        
        async def execute_with_semaphore(tool: BaseTool) -> ToolOutput:
            async with semaphore:
                action = {"type": tool.action_type, "payload": {}}
                return await get_tool_registry().execute(action, {})
        
        tasks = [execute_with_semaphore(t) for t in tools]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                results[i] = ToolOutput.fail(error=str(result))
        
        return results


def create_concurrency_mock_registry() -> Dict[str, BaseTool]:
    """Create a registry with all concurrency testing tools."""
    return {
        "fast": FastTool(),
        "slow": SlowTool(),
        "variable": VariableDelayTool(),
        "failing": FailingTool(fail_after_n=5),
        "race_condition": RaceConditionTool(),
        "rate_limited": RateLimitedTool(),
        "priority_high": PriorityTool(priority=10),
        "priority_medium": PriorityTool(priority=5),
        "priority_low": PriorityTool(priority=0),
        "resource_intensive": ResourceIntensiveTool(),
        "chained": ChainedTool(),
    }


def register_concurrency_tools(registry=None):
    """Register all concurrency testing tools."""
    registry = registry or get_tool_registry()
    tools = create_concurrency_mock_registry()
    for tool in tools.values():
        registry.register(tool)
    return tools
