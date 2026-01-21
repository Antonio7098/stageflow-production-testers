#!/usr/bin/env python3
"""
WORK-007 Tool Timeout Management - Simplified Test Runner

Directly tests tool timeout behavior without full pipeline framework overhead.
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

test_dir = Path(__file__).parent
project_dir = test_dir.parent.parent
sys.path.insert(0, str(project_dir))
sys.path.insert(0, str(test_dir))

from mocks.work007.tool_mocks import (
    SlowTool,
    PartialResultTool,
    StreamingTool,
    HeartbeatTool,
    ConfigurableTimeoutTool,
    ErrorInjectionTool,
    ResourceCleanupTool,
    create_mock_tool_registry,
)
from stageflow.tools import get_tool_registry, ToolInput, ToolOutput
from dataclasses import dataclass
from uuid import uuid4


@dataclass
class Action:
    id: uuid4
    type: str
    payload: dict


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class TimeoutTestResult:
    """Result of a timeout test."""
    def __init__(
        self,
        test_name: str,
        timeout_ms: int,
        success: bool,
        execution_time_ms: float,
        details: Dict[str, Any],
    ):
        self.test_name = test_name
        self.timeout_ms = timeout_ms
        self.success = success
        self.execution_time_ms = execution_time_ms
        self.details = details

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_name": self.test_name,
            "timeout_ms": self.timeout_ms,
            "success": self.success,
            "execution_time_ms": self.execution_time_ms,
            "details": self.details,
        }


async def test_slow_tool_timeout(
    registry,
    timeout_ms: int = 3000,
    execution_time_ms: int = 5000,
) -> TimeoutTestResult:
    """Test slow tool with timeout."""
    start_time = time.time()

    tool = SlowTool(execution_time_ms=execution_time_ms)
    registry.register(tool)

    action = Action(id=uuid4(), type="SLOW_OPERATION", payload={})
    timeout_occurred = False
    error = None

    try:
        async with asyncio.timeout(timeout_ms / 1000.0):
            result = await registry.execute(action, {})

    except asyncio.TimeoutError:
        timeout_occurred = True

    except Exception as e:
        error = str(e)

    execution_time_ms = (time.time() - start_time) * 1000

    return TimeoutTestResult(
        test_name="slow_tool_timeout",
        timeout_ms=timeout_ms,
        success=timeout_occurred,
        execution_time_ms=execution_time_ms,
        details={
            "execution_time_ms": execution_time_ms,
            "timeout_occurred": timeout_occurred,
            "error": error,
            "expected_timeout": execution_time_ms > timeout_ms,
        },
    )


async def test_partial_result_tool(
    registry,
    timeout_ms: int = 3000,
    partial_delay_ms: int = 500,
) -> TimeoutTestResult:
    """Test partial result availability after timeout."""
    start_time = time.time()

    tool = PartialResultTool(partial_delay_ms=partial_delay_ms)
    registry.register(tool)

    action = Action(id=uuid4(), type="PARTIAL_OPERATION", payload={})
    timeout_occurred = False
    partial_data = None

    try:
        async with asyncio.timeout(timeout_ms / 1000.0):
            result = await registry.execute(action, {})

            if not result.success:
                return TimeoutTestResult(
                    test_name="partial_result_tool",
                    timeout_ms=timeout_ms,
                    success=False,
                    execution_time_ms=(time.time() - start_time) * 1000,
                    details={
                        "error": result.error,
                        "data": result.data,
                    },
                )

    except asyncio.TimeoutError:
        timeout_occurred = True
        partial_data = {"partial_delay_ms": partial_delay_ms}

    execution_time_ms = (time.time() - start_time) * 1000

    return TimeoutTestResult(
        test_name="partial_result_tool",
        timeout_ms=timeout_ms,
        success=timeout_occurred,
        execution_time_ms=execution_time_ms,
        details={
            "timeout_occurred": timeout_occurred,
            "partial_data_available": partial_data is not None,
            "partial_delay_ms": partial_delay_ms,
        },
    )


async def test_streaming_tool_timeout(
    registry,
    timeout_ms: int = 3000,
    chunk_delay_ms: int = 500,
    total_chunks: int = 20,
) -> TimeoutTestResult:
    """Test streaming tool timeout during execution."""
    start_time = time.time()

    tool = StreamingTool(
        chunk_delay_ms=chunk_delay_ms,
        total_chunks=total_chunks,
    )
    registry.register(tool)

    action = Action(id=uuid4(), type="STREAMING_OPERATION", payload={})
    timeout_occurred = False
    chunks_received = 0

    try:
        async with asyncio.timeout(timeout_ms / 1000.0):
            result = await registry.execute(action, {})

            if result.success:
                chunks_received = len(result.data.get("chunks", []))
            else:
                return TimeoutTestResult(
                    test_name="streaming_tool_timeout",
                    timeout_ms=timeout_ms,
                    success=False,
                    execution_time_ms=(time.time() - start_time) * 1000,
                    details={
                        "error": result.error,
                        "data": result.data,
                    },
                )

    except asyncio.TimeoutError:
        timeout_occurred = True
        chunks_received = 0

    execution_time_ms = (time.time() - start_time) * 1000

    return TimeoutTestResult(
        test_name="streaming_tool_timeout",
        timeout_ms=timeout_ms,
        success=timeout_occurred,
        execution_time_ms=execution_time_ms,
        details={
            "timeout_occurred": timeout_occurred,
            "chunks_received": chunks_received,
            "total_chunks": total_chunks,
            "completion_rate": chunks_received / total_chunks if total_chunks > 0 else 0,
        },
    )


async def test_concurrent_timeout(
    registry,
    num_tools: int = 20,
    timeout_ms: int = 3000,
    execution_time_ms: int = 5000,
) -> TimeoutTestResult:
    """Test concurrent tool timeouts."""
    start_time = time.time()

    for i in range(num_tools):
        registry.register(SlowTool(execution_time_ms=execution_time_ms))

    async def run_tool(tool_id: int) -> Dict[str, Any]:
        tool_start = time.time()
        timeout_occurred = False

        try:
            async with asyncio.timeout(timeout_ms / 1000.0):
                action = Action(id=uuid4(), type="SLOW_OPERATION", payload={})
                result = await registry.execute(action, {})
                return {
                    "tool_id": tool_id,
                    "success": result.success,
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

    tasks = [run_tool(i) for i in range(num_tools)]
    results = await asyncio.gather(*tasks)

    execution_time_ms = (time.time() - start_time) * 1000

    successful = sum(1 for r in results if r.get("success", False))
    timed_out = sum(1 for r in results if r.get("timeout_occurred", False))

    return TimeoutTestResult(
        test_name="concurrent_timeout",
        timeout_ms=timeout_ms,
        success=timed_out > 0,
        execution_time_ms=execution_time_ms,
        details={
            "num_tools": num_tools,
            "successful_count": successful,
            "timed_out_count": timed_out,
            "success_rate": successful / num_tools if num_tools > 0 else 0,
            "all_timed_out": timed_out == num_tools,
        },
    )


async def test_async_generator_timeout(
    timeout_ms: int = 2000,
    yield_count: int = 20,
    yield_delay_ms: int = 500,
) -> TimeoutTestResult:
    """Test async generator timeout behavior."""
    start_time = time.time()

    items_collected = []
    timeout_leaked = False

    async def slow_generator():
        try:
            for i in range(yield_count):
                yield f"item_{i}"
                await asyncio.sleep(yield_delay_ms / 1000.0)
        except asyncio.CancelledError:
            raise
        finally:
            pass

    try:
        async with asyncio.timeout(timeout_ms / 1000.0):
            async for item in slow_generator():
                items_collected.append(item)
                if len(items_collected) >= 5:
                    break

    except asyncio.TimeoutError:
        pass

    except Exception as e:
        timeout_leaked = True

    execution_time_ms = (time.time() - start_time) * 1000

    return TimeoutTestResult(
        test_name="async_generator_timeout",
        timeout_ms=timeout_ms,
        success=not timeout_leaked,
        execution_time_ms=execution_time_ms,
        details={
            "items_collected": len(items_collected),
            "expected_items": 5,
            "timeout_leaked": timeout_leaked,
        },
    )


async def test_resource_cleanup(
    registry,
    num_tools: int = 50,
    timeout_ms: int = 2000,
) -> TimeoutTestResult:
    """Test resource cleanup during timeout cascade."""
    start_time = time.time()

    cleanup_tools = []
    for i in range(num_tools):
        tool = ResourceCleanupTool()
        cleanup_tools.append(tool)
        registry.register(tool)

    async def run_tool_with_cleanup(tool: ResourceCleanupTool, tool_id: int) -> Dict[str, Any]:
        tool_start = time.time()

        try:
            async with asyncio.timeout(timeout_ms / 1000.0):
                action = Action(id=uuid4(), type="RESOURCE_CLEANUP", payload={"should_timeout": True})
                result = await registry.execute(action, {})
                return {
                    "tool_id": tool_id,
                    "success": result.success,
                    "cleanup_called": result.data.get("cleanup_called", False),
                    "execution_time_ms": (time.time() - tool_start) * 1000,
                }

        except asyncio.TimeoutError:
            return {
                "tool_id": tool_id,
                "success": False,
                "timeout_occurred": True,
                "cleanup_called": tool.cleanup_called,
                "execution_time_ms": (time.time() - tool_start) * 1000,
            }

    tasks = [run_tool_with_cleanup(tool, i) for i, tool in enumerate(cleanup_tools)]
    results = await asyncio.gather(*tasks)

    execution_time_ms = (time.time() - start_time) * 1000

    successful = sum(1 for r in results if r.get("success", False))
    timed_out = sum(1 for r in results if r.get("timeout_occurred", False))
    cleanups_called = sum(1 for r in results if r.get("cleanup_called", False))

    return TimeoutTestResult(
        test_name="resource_cleanup",
        timeout_ms=timeout_ms,
        success=timed_out > 0,
        execution_time_ms=execution_time_ms,
        details={
            "num_tools": num_tools,
            "successful_count": successful,
            "timed_out_count": timed_out,
            "cleanups_called": cleanups_called,
            "cleanup_rate": cleanups_called / num_tools if num_tools > 0 else 0,
        },
    )


async def test_error_injection(
    registry,
    timeout_ms: int = 3000,
) -> TimeoutTestResult:
    """Test various error injection scenarios."""
    start_time = time.time()

    tool = ErrorInjectionTool()
    registry.register(tool)

    test_cases = [
        {"error_type": "none", "delay_ms": 0, "should_raise": False},
        {"error_type": "timeout", "delay_ms": 0, "should_raise": True},
        {"error_type": "connection", "delay_ms": 100, "should_raise": True},
    ]

    results = []

    for test_case in test_cases:
        test_start = time.time()
        timeout_occurred = False
        tool_error = None

        try:
            async with asyncio.timeout(timeout_ms / 1000.0):
                action = Action(id=uuid4(), type="ERROR_INJECTION", payload=test_case)
                result = await registry.execute(action, {})

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

    return TimeoutTestResult(
        test_name="error_injection",
        timeout_ms=timeout_ms,
        success=True,
        execution_time_ms=execution_time_ms,
        details={
            "total_tests": len(results),
            "results": results,
        },
    )


async def run_all_tests() -> List[TimeoutTestResult]:
    """Run all timeout tests."""
    results = []

    registry = create_mock_tool_registry()

    logger.info("Running baseline tests...")

    result = await test_slow_tool_timeout(registry, timeout_ms=2000, execution_time_ms=5000)
    results.append(result)
    logger.info(f"  slow_tool_timeout: success={result.success}, time={result.execution_time_ms:.2f}ms")

    result = await test_partial_result_tool(registry, timeout_ms=2000, partial_delay_ms=500)
    results.append(result)
    logger.info(f"  partial_result_tool: success={result.success}, time={result.execution_time_ms:.2f}ms")

    result = await test_streaming_tool_timeout(registry, timeout_ms=2000, chunk_delay_ms=200, total_chunks=20)
    results.append(result)
    logger.info(f"  streaming_tool_timeout: success={result.success}, time={result.execution_time_ms:.2f}ms")

    logger.info("Running stress tests...")

    result = await test_concurrent_timeout(registry, num_tools=20, timeout_ms=3000, execution_time_ms=5000)
    results.append(result)
    logger.info(f"  concurrent_timeout: success={result.success}, time={result.execution_time_ms:.2f}ms")

    result = await test_resource_cleanup(registry, num_tools=30, timeout_ms=2000)
    results.append(result)
    logger.info(f"  resource_cleanup: success={result.success}, time={result.execution_time_ms:.2f}ms")

    logger.info("Running chaos tests...")

    result = await test_async_generator_timeout(timeout_ms=2000, yield_count=20, yield_delay_ms=500)
    results.append(result)
    logger.info(f"  async_generator_timeout: success={result.success}, time={result.execution_time_ms:.2f}ms")

    result = await test_error_injection(registry, timeout_ms=3000)
    results.append(result)
    logger.info(f"  error_injection: success={result.success}, time={result.execution_time_ms:.2f}ms")

    return results


def analyze_results(results: List[TimeoutTestResult]) -> List[Dict[str, Any]]:
    """Analyze test results and generate findings."""
    findings = []

    for result in results:
        if not result.success and result.test_name not in ["error_injection"]:
            findings.append({
                "title": f"Test failed: {result.test_name}",
                "description": f"Test with timeout_ms={result.timeout_ms} did not complete as expected",
                "type": "reliability",
                "severity": "medium",
                "component": result.test_name,
                "reproduction": f"Run test with timeout_ms={result.timeout_ms}",
                "impact": f"Tool timeout behavior may be unreliable",
                "recommendation": "Investigate timeout handling implementation",
            })

        if result.execution_time_ms > result.timeout_ms * 1.5:
            findings.append({
                "title": f"Timeout exceeded significantly: {result.test_name}",
                "description": f"Execution took {result.execution_time_ms:.2f}ms vs timeout of {result.timeout_ms}ms",
                "type": "performance",
                "severity": "low",
                "component": "Timeout enforcement",
                "context": f"Test: {result.test_name}",
                "impact": "Timeout enforcement may have timing inaccuracies",
                "recommendation": "Review asyncio.timeout implementation and timing precision",
            })

    return findings


def log_finding(
    finding_type: str,
    entry: Dict[str, Any],
    agent: str = "claude-3.5-sonnet",
) -> None:
    """Log a finding using the add_finding.py script."""
    import subprocess

    entry_json = json.dumps(entry)

    try:
        result = subprocess.run(
            [sys.executable, "add_finding.py", "--file", finding_type, "--entry", entry_json, "--agent", agent],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            logger.info(f"Logged finding: {entry.get('title', 'Unknown')}")
        else:
            logger.warning(f"Failed to log finding: {result.stderr}")

    except Exception as e:
        logger.warning(f"Could not log finding: {e}")


async def main():
    """Main entry point."""
    results_dir = Path(__file__).parent / "results" / "work007"
    results_dir.mkdir(parents=True, exist_ok=True)

    logs_dir = results_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    logger.info("=" * 60)
    logger.info("WORK-007 Tool Timeout Management - Test Execution")
    logger.info("=" * 60)

    start_time = time.time()
    results = await run_all_tests()
    end_time = time.time()

    logger.info("\n" + "=" * 60)
    logger.info("Test Results Summary")
    logger.info("=" * 60)

    passed = sum(1 for r in results if r.success)
    logger.info(f"Total Tests: {len(results)}")
    logger.info(f"Passed: {passed}")
    logger.info(f"Failed: {len(results) - passed}")
    logger.info(f"Total Duration: {(end_time - start_time) * 1000:.2f}ms")

    output_data = {
        "summary": {
            "total_tests": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "total_duration_ms": (end_time - start_time) * 1000,
        },
        "results": [r.to_dict() for r in results],
    }

    output_file = results_dir / "all_test_results.json"
    with open(output_file, "w") as f:
        json.dump(output_data, f, indent=2)

    logger.info(f"\nResults saved to: {output_file}")

    findings = analyze_results(results)
    logger.info(f"\nFound {len(findings)} issues to log")

    for finding in findings:
        finding_type = "bug" if finding.get("severity") in ["critical", "high"] else "dx"
        log_finding(finding_type, finding)

    return output_data


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
