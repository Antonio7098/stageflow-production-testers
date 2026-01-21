"""
WORK-009: Tool Output Validation - Chaos Pipeline

Tests edge cases and silent failures in tool output validation:
- Silent failures (appear successful but invalid)
- Malformed data handling
- Circular references
- Large outputs
- Deep nesting
"""

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow import (
    StageContext,
    StageKind,
    StageOutput,
)
from stageflow.tools import get_tool_registry, ToolInput, ToolOutput
from stageflow.context import ContextSnapshot
from stageflow import PipelineContext

from research.work009_tool_output_validation.mocks.tool_mocks import (
    OutputTracker,
    register_validation_tools,
    SilentFailureTool,
    CircularRefTool,
    LargeOutputTool,
    DeepNestingTool,
    TypeMismatchDeepTool,
    InconsistentTypeTool,
    MalformedDataTool,
    ValidationTestTool,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("work009_chaos")


@dataclass
class Action:
    id: uuid4
    type: str
    payload: dict


class ChaosTestStage:
    """Stage that tests chaotic tool output scenarios."""
    name = "chaos_test"
    kind = StageKind.WORK

    def __init__(self):
        self.tracker = OutputTracker()
        self.registry = get_tool_registry()
        self.results: List[Dict[str, Any]] = []
        self.silent_failures: List[Dict[str, Any]] = []
        self.exceptions: List[Dict[str, Any]] = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()

        # Chaos scenarios to test
        chaos_tools = [
            ("silent_failure", SilentFailureTool(), "Appears successful but invalid data"),
            ("circular_ref", CircularRefTool(), "Circular reference in output"),
            ("large_output", LargeOutputTool(), "Very large output (>1MB)"),
            ("deep_nesting", DeepNestingTool(), "Deeply nested data (20+ levels)"),
            ("type_mismatch_deep", TypeMismatchDeepTool(), "Type mismatch at deep level"),
            ("inconsistent_type", InconsistentTypeTool(), "Inconsistent return types"),
            ("malformed_data", MalformedDataTool(), "Malformed nested data"),
        ]

        for tool_name, tool, description in chaos_tools:
            # Register the tool
            if self.registry.get_tool(tool_name):
                self.registry._tools.pop(tool_name, None)
            self.registry.register(tool)

            action = Action(id=uuid4(), type=tool.action_type, payload={})
            execution_start = time.time()

            try:
                output = await self.registry.execute(action, ctx.to_dict())
                execution_time_ms = (time.time() - execution_start) * 1000

                # Record the output
                self.tracker.record(tool_name, output)

                # Analyze for issues
                issues = self._analyze_output(tool_name, output, description)

                result = {
                    "tool_name": tool_name,
                    "description": description,
                    "success": output.success,
                    "execution_time_ms": execution_time_ms,
                    "output_type": type(output.data).__name__ if output.data else "None",
                    "output_size_bytes": len(json.dumps(output.data, default=str)) if output.data else 0,
                    "issues": issues,
                    "data_preview": self._get_data_preview(output.data),
                }

                # Check for silent failures
                if self._is_silent_failure(output, issues):
                    self.silent_failures.append({
                        "tool_name": tool_name,
                        "description": description,
                        "output": output.data,
                        "issues": issues,
                    })
                    result["is_silent_failure"] = True

                self.results.append(result)

            except Exception as e:
                self.exceptions.append({
                    "tool_name": tool_name,
                    "description": description,
                    "exception_type": type(e).__name__,
                    "error": str(e),
                })
                self.results.append({
                    "tool_name": tool_name,
                    "description": description,
                    "success": False,
                    "exception": True,
                    "exception_type": type(e).__name__,
                    "error": str(e),
                })

        execution_time_ms = (time.time() - start_time) * 1000

        return StageOutput.ok(
            execution_time_ms=execution_time_ms,
            results=self.results,
            silent_failures=self.silent_failures,
            exceptions=self.exceptions,
            tracker_stats=self.tracker.get_stats(),
        )

    def _analyze_output(
        self,
        tool_name: str,
        output: ToolOutput,
        description: str,
    ) -> List[Dict[str, Any]]:
        """Analyze tool output for potential issues."""
        issues = []

        if not output.success:
            if output.error:
                issues.append({
                    "type": "execution_error",
                    "message": output.error,
                })
            return issues

        if output.data is None:
            issues.append({
                "type": "null_data",
                "message": "Tool returned null data",
            })
            return issues

        # Check for silent failure indicators
        if isinstance(output.data, str):
            issues.append({
                "type": "wrong_type",
                "message": f"Expected object, got string: {output.data[:100]}",
            })

        # Check for circular references
        if self._has_circular_ref(output.data):
            issues.append({
                "type": "circular_reference",
                "message": "Circular reference detected in output",
            })

        # Check for deep nesting
        depth = self._get_nesting_depth(output.data)
        if depth > 10:
            issues.append({
                "type": "deep_nesting",
                "message": f"Nesting depth: {depth} (recommended max: 10)",
            })

        # Check output size
        size_bytes = len(json.dumps(output.data, default=str))
        if size_bytes > 100000:  # 100KB
            issues.append({
                "type": "large_output",
                "message": f"Output size: {size_bytes / 1024:.1f}KB (recommended max: 100KB)",
            })

        return issues

    def _has_circular_ref(self, obj: Any, seen: set = None) -> bool:
        """Check if object has circular references."""
        if seen is None:
            seen = set()

        if id(obj) in seen:
            return True

        if isinstance(obj, dict):
            seen.add(id(obj))
            for value in obj.values():
                if self._has_circular_ref(value, seen):
                    return True
            seen.discard(id(obj))

        elif isinstance(obj, list):
            seen.add(id(obj))
            for item in obj:
                if self._has_circular_ref(item, seen):
                    return True
            seen.discard(id(obj))

        return False

    def _get_nesting_depth(self, obj: Any, current_depth: int = 0) -> int:
        """Get the maximum nesting depth of an object."""
        if isinstance(obj, dict):
            if not obj:
                return current_depth
            return max(
                self._get_nesting_depth(v, current_depth + 1)
                for v in obj.values()
            )
        elif isinstance(obj, list):
            if not obj:
                return current_depth
            return max(
                self._get_nesting_depth(item, current_depth + 1)
                for item in obj
            )
        return current_depth

    def _is_silent_failure(
        self,
        output: ToolOutput,
        issues: List[Dict[str, Any]],
    ) -> bool:
        """Determine if this is a silent failure."""
        if not output.success:
            return False

        if output.data is None:
            return False

        # Silent failure indicators
        if isinstance(output.data, str):
            return True

        for issue in issues:
            if issue["type"] in ["wrong_type", "null_data"]:
                return True

        return False

    def _get_data_preview(self, data: Any) -> str:
        """Get a preview of the data for logging."""
        if data is None:
            return "None"
        if isinstance(data, str):
            return f'String: "{data[:50]}{"..." if len(data) > 50 else ""}"'
        if isinstance(data, (dict, list)):
            preview = str(data)[:100]
            return f'{type(data).__name__}: {preview}{"..." if len(str(data)) > 100 else ""}'
        return f'{type(data).__name__}: {str(data)[:50]}'


class ChaosPipeline:
    """Chaos pipeline for testing edge cases."""

    def __init__(self):
        self.registry = get_tool_registry()
        register_validation_tools(self.registry)

    async def run(self) -> Dict[str, Any]:
        """Run the chaos tests."""
        logger.info("Starting chaos tool output validation tests")

        test_stage = ChaosTestStage()

        snapshot = ContextSnapshot(
            input_text="chaos test input",
            messages=[],
            attachments=[],
        )

        ctx = PipelineContext(
            snapshot=snapshot,
            pipeline_run_id=uuid4(),
            request_id=uuid4(),
        )

        stage_ctx = StageContext(snapshot=snapshot, config={})
        stage_ctx.pipeline_run_id = ctx.pipeline_run_id
        stage_ctx.request_id = ctx.request_id

        output = await test_stage.execute(stage_ctx)

        results = output.data.get("results", [])
        silent_failures = output.data.get("silent_failures", [])
        exceptions = output.data.get("exceptions", [])

        # Analyze results
        tools_with_issues = sum(1 for r in results if r.get("issues"))
        silent_failure_count = len(silent_failures)
        exception_count = len(exceptions)

        logger.info(f"Chaos test results:")
        logger.info(f"  Total tests: {len(results)}")
        logger.info(f"  Tools with issues: {tools_with_issues}")
        logger.info(f"  Silent failures: {silent_failure_count}")
        logger.info(f"  Exceptions: {exception_count}")

        return {
            "test_type": "chaos",
            "total_tests": len(results),
            "tools_with_issues": tools_with_issues,
            "silent_failures": silent_failures,
            "silent_failure_count": silent_failure_count,
            "exceptions": exceptions,
            "exception_count": exception_count,
            "results": results,
            "execution_time_ms": output.data.get("execution_time_ms", 0),
        }


async def main():
    """Run the chaos pipeline."""
    pipeline = ChaosPipeline()
    results = await pipeline.run()

    output_file = Path(__file__).parent / "results" / "work009_chaos_results.json"
    output_file.parent.mkdir(exist_ok=True)

    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"Results saved to {output_file}")

    return results


if __name__ == "__main__":
    results = asyncio.run(main())
    print(f"\nChaos Test Summary:")
    print(f"  Total: {results['total_tests']}")
    print(f"  Tools with issues: {results['tools_with_issues']}")
    print(f"  Silent failures: {results['silent_failure_count']}")
    print(f"  Exceptions: {results['exception_count']}")
