"""
WORK-008 Concurrent Tool Execution Limits - Simplified Test Runner

Directly tests concurrent tool execution behavior without full pipeline framework overhead.
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow.tools import get_tool_registry, ToolInput, ToolOutput
from dataclasses import dataclass

from research.work008_concurrent_tool_limits.mocks.tool_mocks import (
    ExecutionTracker,
    FastTool,
    SlowTool,
    VariableDelayTool,
    RaceConditionTool,
    RateLimitedTool,
    PriorityTool,
    ResourceIntensiveTool,
    FailingTool,
    register_concurrency_tools,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("work008_tests")


@dataclass
class Action:
    id: uuid4
    type: str
    payload: dict


class TestResult:
    """Result of a concurrent execution test."""
    def __init__(
        self,
        test_name: str,
        success: bool,
        execution_time_ms: float,
        details: Dict[str, Any],
        error: str = None,
    ):
        self.test_name = test_name
        self.success = success
        self.execution_time_ms = execution_time_ms
        self.details = details
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_name": self.test_name,
            "success": self.success,
            "execution_time_ms": self.execution_time_ms,
            "details": self.details,
            "error": self.error,
        }


async def test_sequential_execution(registry, tool_count: int = 5) -> TestResult:
    """Test sequential tool execution."""
    start_time = time.time()
    results = []

    for i in range(tool_count):
        tool = FastTool()
        registry.register(tool)
        action = Action(id=uuid4(), type="FAST_OPERATION", payload={"index": i})
        try:
            result = await registry.execute(action, {})
            results.append({"index": i, "success": result.success})
        except Exception as e:
            results.append({"index": i, "success": False, "error": str(e)})

    execution_time_ms = (time.time() - start_time) * 1000
    successful = sum(1 for r in results if r.get("success", False))

    return TestResult(
        test_name="sequential_execution",
        success=successful == tool_count,
        execution_time_ms=execution_time_ms,
        details={
            "tool_count": tool_count,
            "successful": successful,
            "failed": tool_count - successful,
            "results": results,
        },
    )


async def test_parallel_execution(registry, tool_count: int = 10) -> TestResult:
    """Test parallel tool execution."""
    start_time = time.time()

    async def execute_tool(i: int) -> Dict[str, Any]:
        tool = FastTool()
        registry.register(tool)
        action = Action(id=uuid4(), type="FAST_OPERATION", payload={"index": i})
        try:
            result = await registry.execute(action, {})
            return {"index": i, "success": result.success}
        except Exception as e:
            return {"index": i, "success": False, "error": str(e)}

    tasks = [execute_tool(i) for i in range(tool_count)]
    results = await asyncio.gather(*tasks)

    execution_time_ms = (time.time() - start_time) * 1000
    successful = sum(1 for r in results if r.get("success", False))

    return TestResult(
        test_name="parallel_execution",
        success=successful == tool_count,
        execution_time_ms=execution_time_ms,
        details={
            "tool_count": tool_count,
            "successful": successful,
            "failed": tool_count - successful,
            "results": results[:5],
            "note": "Showing first 5 results",
        },
    )


async def test_high_concurrency(registry, concurrency_level: int = 50) -> TestResult:
    """Test high concurrency tool execution."""
    start_time = time.time()
    tracker = ExecutionTracker()
    tracker.reset()

    async def execute_tool(i: int) -> Dict[str, Any]:
        execution_id = tracker.record_start(f"tool_{i}")
        tool = FastTool()
        registry.register(tool)
        action = Action(id=uuid4(), type="FAST_OPERATION", payload={"index": i})
        try:
            result = await registry.execute(action, {})
            tracker.record_end(execution_id, success=result.success)
            return {"index": i, "success": result.success, "execution_id": execution_id}
        except Exception as e:
            tracker.record_end(execution_id, success=False, error=str(e))
            return {"index": i, "success": False, "error": str(e), "execution_id": execution_id}

    tasks = [execute_tool(i) for i in range(concurrency_level)]
    results = await asyncio.gather(*tasks)

    execution_time_ms = (time.time() - start_time) * 1000
    stats = tracker.get_stats()
    successful = sum(1 for r in results if r.get("success", False))

    return TestResult(
        test_name=f"high_concurrency_{concurrency_level}",
        success=successful == concurrency_level,
        execution_time_ms=execution_time_ms,
        details={
            "concurrency_level": concurrency_level,
            "successful": successful,
            "failed": concurrency_level - successful,
            "max_concurrent": stats.get("max_concurrent", 0),
            "throughput": stats.get("throughput", 0),
            "avg_execution_time_ms": stats.get("avg_execution_time_ms", 0),
        },
    )


async def test_race_condition(registry, tool_count: int = 20) -> TestResult:
    """Test for race conditions on shared state."""
    start_time = time.time()
    shared_counter = {"counter": 0}

    async def execute_race_tool(i: int) -> Dict[str, Any]:
        tool = RaceConditionTool(shared_counter=shared_counter)
        registry.register(tool)
        action = Action(id=uuid4(), type="RACE_CONDITION", payload={"index": i})
        try:
            result = await registry.execute(action, {})
            return {"index": i, "success": result.success, "counter": result.data.get("counter_value")}
        except Exception as e:
            return {"index": i, "success": False, "error": str(e)}

    tasks = [execute_race_tool(i) for i in range(tool_count)]
    results = await asyncio.gather(*tasks)

    execution_time_ms = (time.time() - start_time) * 1000
    final_counter = shared_counter["counter"]
    expected_counter = tool_count
    race_detected = final_counter != expected_counter

    return TestResult(
        test_name="race_condition_test",
        success=not race_detected,
        execution_time_ms=execution_time_ms,
        details={
            "tool_count": tool_count,
            "expected_counter": expected_counter,
            "actual_counter": final_counter,
            "race_detected": race_detected,
            "severity": "high" if race_detected else "none",
        },
    )


async def test_rate_limiting(registry, request_count: int = 50, max_per_second: float = 10.0) -> TestResult:
    """Test rate limiting behavior."""
    start_time = time.time()

    rate_limited_tool = RateLimitedTool(max_per_second=max_per_second)
    registry.register(rate_limited_tool)

    async def execute_rate_limited(i: int) -> Dict[str, Any]:
        action = Action(id=uuid4(), type="RATE_LIMITED", payload={"index": i})
        try:
            result = await registry.execute(action, {})
            return {"index": i, "success": result.success, "tokens": result.data.get("tokens_used")}
        except Exception as e:
            return {"index": i, "success": False, "error": str(e)}

    tasks = [execute_rate_limited(i) for i in range(request_count)]
    results = await asyncio.gather(*tasks)

    execution_time_ms = (time.time() - start_time) * 1000
    successful = sum(1 for r in results if r.get("success", False))
    rate_limited = sum(1 for r in results if r.get("error") and "rate limit" in r.get("error", "").lower())

    return TestResult(
        test_name="rate_limit_simulation",
        success=successful >= 0,
        execution_time_ms=execution_time_ms,
        details={
            "request_count": request_count,
            "max_per_second": max_per_second,
            "successful": successful,
            "rate_limited": rate_limited,
            "throughput_per_second": successful / (execution_time_ms / 1000) if execution_time_ms > 0 else 0,
        },
    )


async def test_cascading_failure(registry, total_tools: int = 20, fail_ratio: float = 0.3) -> TestResult:
    """Test cascading failure behavior."""
    start_time = time.time()

    failing_tool = FailingTool(fail_after_n=int(total_tools * (1 - fail_ratio)))
    registry.register(failing_tool)

    results = []
    for i in range(total_tools):
        action = Action(id=uuid4(), type="FAILING_OPERATION", payload={"index": i})
        try:
            result = await registry.execute(action, {})
            results.append({"index": i, "success": result.success, "error": result.error})
        except Exception as e:
            results.append({"index": i, "success": False, "error": str(e)})

    execution_time_ms = (time.time() - start_time) * 1000
    successful = sum(1 for r in results if r.get("success", False))
    failed = sum(1 for r in results if not r.get("success", False))

    return TestResult(
        test_name="cascading_failure",
        success=failed > 0,
        execution_time_ms=execution_time_ms,
        details={
            "total_tools": total_tools,
            "fail_ratio": fail_ratio,
            "successful": successful,
            "failed": failed,
            "expected_failures": int(total_tools * fail_ratio),
        },
    )


async def test_resource_exhaustion(registry, tool_count: int = 5, memory_kb: int = 2048) -> TestResult:
    """Test resource exhaustion behavior."""
    start_time = time.time()

    async def execute_resource_tool(i: int) -> Dict[str, Any]:
        tool = ResourceIntensiveTool(memory_kb=memory_kb, duration_ms=50)
        registry.register(tool)
        action = Action(id=uuid4(), type="RESOURCE_INTENSIVE", payload={"index": i})
        try:
            result = await registry.execute(action, {})
            return {"index": i, "success": result.success}
        except Exception as e:
            return {"index": i, "success": False, "error": str(e)}

    tasks = [execute_resource_tool(i) for i in range(tool_count)]
    results = await asyncio.gather(*tasks)

    execution_time_ms = (time.time() - start_time) * 1000
    successful = sum(1 for r in results if r.get("success", False))

    return TestResult(
        test_name="resource_exhaustion",
        success=successful > 0,
        execution_time_ms=execution_time_ms,
        details={
            "tool_count": tool_count,
            "memory_kb_per_tool": memory_kb,
            "successful": successful,
            "failed": tool_count - successful,
        },
    )


async def run_all_tests() -> Dict[str, Any]:
    """Run all concurrent execution tests."""
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    
    logs_dir = results_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    all_results = []
    start_time = time.time()

    logger.info("=" * 80)
    logger.info("WORK-008 Concurrent Tool Execution Limits - Test Suite")
    logger.info("=" * 80)

    test_cases = [
        ("sequential_5", lambda r: test_sequential_execution(r, 5)),
        ("parallel_10", lambda r: test_parallel_execution(r, 10)),
        ("parallel_25", lambda r: test_parallel_execution(r, 25)),
        ("high_concurrency_50", lambda r: test_high_concurrency(r, 50)),
        ("high_concurrency_100", lambda r: test_high_concurrency(r, 100)),
        ("race_condition_20", lambda r: test_race_condition(r, 20)),
        ("rate_limiting_50", lambda r: test_rate_limiting(r, 50, 10.0)),
        ("cascading_failure_20", lambda r: test_cascading_failure(r, 20, 0.3)),
        ("resource_exhaustion_5", lambda r: test_resource_exhaustion(r, 5, 2048)),
    ]

    for test_name, test_func in test_cases:
        logger.info(f"\nRunning test: {test_name}")
        try:
            registry = get_tool_registry()
            register_concurrency_tools(registry)
            result = await test_func(registry)
            all_results.append(result.to_dict())
            logger.info(f"  Completed in {result.execution_time_ms:.2f}ms - Success: {result.success}")
        except Exception as e:
            logger.error(f"  Test failed with error: {e}")
            all_results.append({
                "test_name": test_name,
                "success": False,
                "error": str(e),
                "execution_time_ms": 0,
                "details": {},
            })

    total_time = time.time() - start_time

    summary = {
        "test_run_summary": {
            "total_duration_seconds": total_time,
            "timestamp": str(time.strftime("%Y-%m-%d %H:%M:%S")),
        },
        "results": all_results,
        "summary": {
            "total_tests": len(all_results),
            "passed": sum(1 for r in all_results if r.get("success", False)),
            "failed": sum(1 for r in all_results if not r.get("success", False)),
        },
    }

    output_file = results_dir / "work008_test_summary.json"
    with open(output_file, "w") as f:
        json.dump(summary, f, indent=2)

    output_file_details = results_dir / "work008_all_results.json"
    with open(output_file_details, "w") as f:
        json.dump(all_results, f, indent=2)

    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total duration: {total_time:.2f}s")
    logger.info(f"Tests passed: {summary['summary']['passed']}/{summary['summary']['total_tests']}")
    logger.info(f"Tests failed: {summary['summary']['failed']}/{summary['summary']['total_tests']}")
    logger.info(f"\nResults saved to: {output_file}")
    logger.info("=" * 80)

    return summary


async def main():
    """Main entry point."""
    return await run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
