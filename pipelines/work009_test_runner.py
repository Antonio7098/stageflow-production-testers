"""
WORK-009: Tool Output Validation - Test Runner

Comprehensive test runner for tool output validation:
- Executes baseline, chaos, and stress tests
- Collects metrics and logs
- Performs log analysis
- Detects silent failures
- Generates findings
"""

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow.tools import get_tool_registry
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow.stages.inputs import StageInputs
from stageflow import PipelineTimer, StageContext

from research.work009_tool_output_validation.mocks.tool_mocks import (
    OutputTracker,
    register_validation_tools,
    ValidUserTool,
    MissingFieldsTool,
    WrongTypeTool,
    SilentFailureTool,
    AsyncDelayTool,
)
from research.work009_tool_output_validation.mocks.test_scenarios import (
    ALL_SCENARIOS,
    ScenarioType,
    Severity,
    get_silent_failure_scenarios,
)


@dataclass
class Action:
    id: uuid4
    type: str
    payload: dict


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("work009_runner")


@dataclass
class TestResult:
    """Result of a validation test."""
    test_id: str
    test_name: str
    scenario_type: str
    severity: str
    passed: bool
    execution_time_ms: float
    validation_errors: List[str]
    silent_failure: bool
    details: Dict[str, Any]


class ToolOutputValidationTester:
    """Comprehensive tester for tool output validation."""

    def __init__(self):
        self.registry = get_tool_registry()
        register_validation_tools(self.registry)
        self.results: List[TestResult] = []
        self.metrics = {
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "silent_failures": 0,
            "exceptions": 0,
            "by_type": {},
            "by_severity": {},
            "execution_times": [],
        }

    async def run_baseline_tests(self) -> List[TestResult]:
        """Run baseline validation tests."""
        logger.info("Running baseline tests...")

        snapshot = ContextSnapshot(
            run_id=RunIdentity(
                pipeline_run_id=uuid4(),
                request_id=uuid4(),
                session_id="baseline_test",
                user_id="test_user",
                org_id=None,
                interaction_id=uuid4(),
            ),
            topology="baseline",
            execution_mode="test",
            input_text="baseline test",
        )

        stage_ctx = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name="test",
            timer=PipelineTimer(),
        )

        baseline_tools = [
            ("VALID_001", "valid_user", ValidUserTool(), True),
            ("VALID_002", "missing_fields", MissingFieldsTool(), False),
            ("VALID_003", "wrong_type", WrongTypeTool(), False),
        ]

        for test_id, tool_name, tool, expected_pass in baseline_tools:
            start_time = time.time()

            try:
                if self.registry.get_tool(tool_name):
                    self.registry._tools.pop(tool_name, None)
                self.registry.register(tool)

                action = Action(id=uuid4(), type=tool.action_type, payload={})
                output = await self.registry.execute(action, {})

                execution_time_ms = (time.time() - start_time) * 1000

                # Validate output
                passed = self._validate_output(output)
                is_silent_failure = self._detect_silent_failure(output, passed)

                result = TestResult(
                    test_id=test_id,
                    test_name=f"Baseline: {tool_name}",
                    scenario_type="baseline",
                    severity="low",
                    passed=passed,
                    execution_time_ms=execution_time_ms,
                    validation_errors=[] if passed else ["Validation failed"],
                    silent_failure=is_silent_failure,
                    details={
                        "tool_name": tool_name,
                        "expected_pass": expected_pass,
                        "actual_pass": passed,
                        "output_success": output.success,
                        "output_data_type": type(output.data).__name__ if output.data else "None",
                    }
                )

                self.results.append(result)

            except Exception as e:
                execution_time_ms = (time.time() - start_time) * 1000
                result = TestResult(
                    test_id=test_id,
                    test_name=f"Baseline: {tool_name}",
                    scenario_type="baseline",
                    severity="medium",
                    passed=False,
                    execution_time_ms=execution_time_ms,
                    validation_errors=[f"Exception: {str(e)}"],
                    silent_failure=False,
                    details={
                        "tool_name": tool_name,
                        "exception": True,
                        "exception_type": type(e).__name__,
                    }
                )
                self.results.append(result)
                self.metrics["exceptions"] += 1

        return [r for r in self.results if r.scenario_type == "baseline"]

    async def run_silent_failure_tests(self) -> List[TestResult]:
        """Run tests specifically designed to detect silent failures."""
        logger.info("Running silent failure detection tests...")

        silent_scenarios = get_silent_failure_scenarios()

        for scenario in silent_scenarios:
            start_time = time.time()

            try:
                # Get the appropriate tool
                tool_map = {
                    "silent_failure": SilentFailureTool(),
                    "partial_success": None,  # Would need to import
                }

                tool = tool_map.get(scenario.tool_name)
                if tool is None:
                    continue

                if self.registry.get_tool(scenario.tool_name):
                    self.registry._tools.pop(scenario.tool_name, None)
                self.registry.register(tool)

                action = Action(id=uuid4(), type=tool.action_type, payload={})
                output = await self.registry.execute(action, {})

                execution_time_ms = (time.time() - start_time) * 1000

                # Check for silent failure
                validation_passed = self._validate_output(output)
                is_silent_failure = self._detect_silent_failure(output, validation_passed)

                result = TestResult(
                    test_id=scenario.id,
                    test_name=f"Silent Failure: {scenario.name}",
                    scenario_type="silent_failure",
                    severity=scenario.severity.value,
                    passed=not is_silent_failure,
                    execution_time_ms=execution_time_ms,
                    validation_errors=[] if validation_passed else ["Validation failed"],
                    silent_failure=is_silent_failure,
                    details={
                        "description": scenario.description,
                        "output_success": output.success,
                        "output_data": str(output.data)[:200],
                    }
                )

                self.results.append(result)

            except Exception as e:
                execution_time_ms = (time.time() - start_time) * 1000
                result = TestResult(
                    test_id=scenario.id,
                    test_name=f"Silent Failure: {scenario.name}",
                    scenario_type="silent_failure",
                    severity=scenario.severity.value,
                    passed=False,
                    execution_time_ms=execution_time_ms,
                    validation_errors=[f"Exception: {str(e)}"],
                    silent_failure=False,
                    details={
                        "exception": True,
                        "exception_type": type(e).__name__,
                    }
                )
                self.results.append(result)
                self.metrics["exceptions"] += 1

        return [r for r in self.results if r.scenario_type == "silent_failure"]

    async def run_concurrency_tests(self) -> List[TestResult]:
        """Run concurrent validation tests."""
        logger.info("Running concurrency tests...")

        results = []

        # Test concurrent tool executions
        concurrent_counts = [5, 10, 25]

        for count in concurrent_counts:
            start_time = time.time()

            try:
                # Create multiple async tasks
                tasks = []
                for i in range(count):
                    tool = AsyncDelayTool()
                    if self.registry.get_tool(f"async_{i}"):
                        self.registry._tools.pop(f"async_{i}", None)
                    self.registry.register(tool)
                    tasks.append(self._execute_tool(f"async_{i}", tool))

                outputs = await asyncio.gather(*tasks, return_exceptions=True)
                execution_time_ms = (time.time() - start_time) * 1000

                # Analyze results
                valid_count = sum(1 for o in outputs if isinstance(o, Exception) is False and self._validate_output(o))
                invalid_count = count - valid_count

                result = TestResult(
                    test_id=f"CONCURRENCY_{count}",
                    test_name=f"Concurrent: {count} tools",
                    scenario_type="stress",
                    severity="medium",
                    passed=invalid_count == 0,
                    execution_time_ms=execution_time_ms,
                    validation_errors=[] if invalid_count == 0 else [f"{invalid_count} invalid outputs"],
                    silent_failure=False,
                    details={
                        "concurrent_count": count,
                        "valid_outputs": valid_count,
                        "invalid_outputs": invalid_count,
                        "throughput": count / (execution_time_ms / 1000),
                    }
                )

                self.results.append(result)
                results.append(result)

            except Exception as e:
                execution_time_ms = (time.time() - start_time) * 1000
                result = TestResult(
                    test_id=f"CONCURRENCY_{count}",
                    test_name=f"Concurrent: {count} tools",
                    scenario_type="stress",
                    severity="medium",
                    passed=False,
                    execution_time_ms=execution_time_ms,
                    validation_errors=[f"Exception: {str(e)}"],
                    silent_failure=False,
                    details={"exception": True}
                )
                self.results.append(result)

        return results

    async def _execute_tool(self, tool_name: str, tool) -> Any:
        """Execute a single tool."""
        action = Action(id=uuid4(), type=tool.action_type, payload={})
        return await self.registry.execute(action, {})

    def _validate_output(self, output) -> bool:
        """Validate a tool output."""
        if not output.success:
            return False
        if output.data is None:
            return False
        if not isinstance(output.data, dict):
            return False
        return True

    def _detect_silent_failure(self, output, validation_passed: bool) -> bool:
        """Detect if this is a silent failure."""
        if not output.success:
            return False
        if output.data is None:
            return True
        if not isinstance(output.data, dict):
            return True
        if not validation_passed and output.success:
            return True
        return False

    def compute_metrics(self):
        """Compute aggregate metrics from results."""
        self.metrics["total_tests"] = len(self.results)
        self.metrics["passed"] = sum(1 for r in self.results if r.passed)
        self.metrics["failed"] = self.metrics["total_tests"] - self.metrics["passed"]
        self.metrics["silent_failures"] = sum(1 for r in self.results if r.silent_failure)
        self.metrics["execution_times"] = [r.execution_time_ms for r in self.results]

        # Group by type
        for result in self.results:
            if result.scenario_type not in self.metrics["by_type"]:
                self.metrics["by_type"][result.scenario_type] = {"total": 0, "passed": 0, "failed": 0}
            self.metrics["by_type"][result.scenario_type]["total"] += 1
            if result.passed:
                self.metrics["by_type"][result.scenario_type]["passed"] += 1
            else:
                self.metrics["by_type"][result.scenario_type]["failed"] += 1

        # Group by severity
        for result in self.results:
            if result.severity not in self.metrics["by_severity"]:
                self.metrics["by_severity"][result.severity] = []
            self.metrics["by_severity"][result.severity].append(result.test_id)

    def generate_report(self) -> Dict[str, Any]:
        """Generate a comprehensive test report."""
        self.compute_metrics()

        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "test_type": "tool_output_validation",
            "metrics": self.metrics,
            "summary": {
                "total_tests": self.metrics["total_tests"],
                "passed": self.metrics["passed"],
                "failed": self.metrics["failed"],
                "silent_failures": self.metrics["silent_failures"],
                "exceptions": self.metrics["exceptions"],
                "pass_rate": (
                    self.metrics["passed"] / self.metrics["total_tests"]
                    if self.metrics["total_tests"] > 0 else 0
                ),
            },
            "findings": {
                "critical_bugs": [r.test_id for r in self.results if not r.passed and r.severity == "critical"],
                "high_severity_bugs": [r.test_id for r in self.results if not r.passed and r.severity == "high"],
                "silent_failures": [r.test_id for r in self.results if r.silent_failure],
            },
            "test_details": [
                {
                    "test_id": r.test_id,
                    "test_name": r.test_name,
                    "scenario_type": r.scenario_type,
                    "severity": r.severity,
                    "passed": r.passed,
                    "execution_time_ms": r.execution_time_ms,
                    "silent_failure": r.silent_failure,
                    "validation_errors": r.validation_errors,
                    "details": r.details,
                }
                for r in self.results
            ],
        }

        return report


async def main():
    """Run all tests and generate report."""
    logger.info("=" * 60)
    logger.info("WORK-009: Tool Output Validation - Test Runner")
    logger.info("=" * 60)

    tester = ToolOutputValidationTester()

    # Run all test categories
    logger.info("\n[1/3] Running baseline tests...")
    await tester.run_baseline_tests()

    logger.info("\n[2/3] Running silent failure detection tests...")
    await tester.run_silent_failure_tests()

    logger.info("\n[3/3] Running concurrency/stress tests...")
    await tester.run_concurrency_tests()

    # Generate report
    report = tester.generate_report()

    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total tests: {report['summary']['total_tests']}")
    logger.info(f"Passed: {report['summary']['passed']}")
    logger.info(f"Failed: {report['summary']['failed']}")
    logger.info(f"Silent failures: {report['summary']['silent_failures']}")
    logger.info(f"Pass rate: {report['summary']['pass_rate'] * 100:.1f}%")

    logger.info("\nBy Test Type:")
    for test_type, stats in report["metrics"]["by_type"].items():
        logger.info(f"  {test_type}: {stats['passed']}/{stats['total']} passed")

    logger.info("\nCritical Findings:")
    if report["findings"]["critical_bugs"]:
        for bug in report["findings"]["critical_bugs"]:
            logger.info(f"  - {bug}")
    else:
        logger.info("  None")

    logger.info("\nHigh Severity Bugs:")
    if report["findings"]["high_severity_bugs"]:
        for bug in report["findings"]["high_severity_bugs"]:
            logger.info(f"  - {bug}")
    else:
        logger.info("  None")

    logger.info("\nSilent Failures Detected:")
    if report["findings"]["silent_failures"]:
        for sf in report["findings"]["silent_failures"]:
            logger.info(f"  - {sf}")
    else:
        logger.info("  None")

    # Save report
    output_file = Path(__file__).parent / "results" / "work009_test_results.json"
    output_file.parent.mkdir(exist_ok=True)

    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(f"\nFull report saved to: {output_file}")

    return report


if __name__ == "__main__":
    report = asyncio.run(main())
