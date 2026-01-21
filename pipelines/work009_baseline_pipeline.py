"""
WORK-009: Tool Output Validation - Baseline Pipeline

Tests basic tool output validation behavior:
- Valid outputs (should pass)
- Invalid outputs (should fail)
- Basic validation detection
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
    Pipeline,
    StageContext,
    StageKind,
    StageOutput,
)
from stageflow.tools import get_tool_registry, ToolInput, ToolOutput

from research.work009_tool_output_validation.mocks.tool_mocks import (
    OutputTracker,
    register_validation_tools,
    EXPECTED_SCHEMAS,
    ValidUserTool,
    MissingFieldsTool,
    WrongTypeTool,
    NullValuesTool,
    EmptyDataTool,
    NestedInvalidTool,
    ExtraFieldsTool,
    MalformedDataTool,
    SilentFailureTool,
    PartialSuccessTool,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("work009_baseline")


@dataclass
class Action:
    id: uuid4
    type: str
    payload: dict


class ValidationTestStage:
    """Stage that executes tools and validates their outputs."""
    name = "validation_test"
    kind = StageKind.WORK

    def __init__(self, schema_name: str = "user"):
        self.schema_name = schema_name
        self.tracker = OutputTracker()
        self.registry = get_tool_registry()
        self.results: List[Dict[str, Any]] = []

    def _get_schema(self) -> Optional[Dict[str, Any]]:
        """Get the expected schema for validation."""
        return EXPECTED_SCHEMAS.get(self.schema_name)

    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.time()
        schema = self._get_schema()

        # Execute tools and track outputs
        tools_to_test = [
            ("valid_user", ValidUserTool(), True),  # Expected to pass
            ("missing_fields", MissingFieldsTool(), False),  # Expected to fail
            ("wrong_type", WrongTypeTool(), False),  # Expected to fail
            ("null_values", NullValuesTool(), False),  # Expected to fail
            ("empty_data", EmptyDataTool(), False),  # Expected to fail
            ("nested_invalid", NestedInvalidTool(), False),  # Expected to fail
            ("extra_fields", ExtraFieldsTool(), True),  # Expected to pass (extra fields ok)
            ("silent_failure", SilentFailureTool(), False),  # Expected to fail (silent)
            ("partial_success", PartialSuccessTool(), False),  # Expected to fail (incomplete)
        ]

        for tool_name, tool, expected_pass in tools_to_test:
            # Register the tool
            if self.registry.get_tool(tool_name):
                self.registry._tools.pop(tool_name, None)
            self.registry.register(tool)

            # Execute the tool
            action = Action(id=uuid4(), type=tool.action_type, payload={})
            try:
                output = await self.registry.execute(action, ctx.to_dict())
                self.tracker.record(tool_name, output, schema)

                # Validate against schema manually
                validation_result = self._validate_output(output, schema, tool_name)
                self.results.append({
                    "tool_name": tool_name,
                    "success": output.success,
                    "expected_pass": expected_pass,
                    "validation_passed": validation_result["passed"],
                    "validation_errors": validation_result.get("errors", []),
                    "data": output.data,
                    "error": output.error,
                })

            except Exception as e:
                self.results.append({
                    "tool_name": tool_name,
                    "success": False,
                    "expected_pass": expected_pass,
                    "validation_passed": False,
                    "validation_errors": [str(e)],
                    "error": str(e),
                    "exception": True,
                })

        execution_time_ms = (time.time() - start_time) * 1000
        stats = self.tracker.get_stats()

        return StageOutput.ok(
            execution_time_ms=execution_time_ms,
            results=self.results,
            tracker_stats=stats,
            schema_name=self.schema_name,
            schema=schema,
        )

    def _validate_output(
        self,
        output: ToolOutput,
        schema: Optional[Dict[str, Any]],
        tool_name: str,
    ) -> Dict[str, Any]:
        """Manually validate tool output against schema."""
        if schema is None or output.data is None:
            return {"passed": True, "errors": []}

        data = output.data
        errors = []

        # Check required fields
        required = schema.get("required", [])
        for field_name in required:
            if field_name not in data:
                errors.append(f"Missing required field: {field_name}")

        # Check types
        properties = schema.get("properties", {})
        for field_name, field_schema in properties.items():
            if field_name in data and data[field_name] is not None:
                expected_type = field_schema.get("type", "any")
                actual_value = data[field_name]
                actual_type = type(actual_value).__name__

                type_map = {
                    "string": str,
                    "integer": int,
                    "number": (int, float),
                    "boolean": bool,
                    "array": list,
                    "object": dict,
                }

                if expected_type in type_map:
                    if not isinstance(actual_value, type_map[expected_type]):
                        if expected_type == "integer" and isinstance(actual_value, float):
                            if actual_value.is_integer():
                                continue
                        errors.append(
                            f"Field '{field_name}': expected {expected_type}, got {actual_type}"
                        )

        return {
            "passed": len(errors) == 0,
            "errors": errors,
        }


class BaselinePipeline:
    """Baseline pipeline for tool output validation testing."""

    def __init__(self):
        self.registry = get_tool_registry()
        register_validation_tools(self.registry)

    async def run(self) -> Dict[str, Any]:
        """Run the baseline validation tests."""
        logger.info("Starting baseline tool output validation tests")

        test_stage = ValidationTestStage(schema_name="user")

        # Create a simple test snapshot
        from stageflow.context import ContextSnapshot
        from stageflow import PipelineContext

        snapshot = ContextSnapshot(
            input_text="test input",
            messages=[],
            attachments=[],
        )

        ctx = PipelineContext(
            snapshot=snapshot,
            pipeline_run_id=uuid4(),
            request_id=uuid4(),
        )

        # Execute the test stage
        stage_ctx = StageContext(snapshot=snapshot, config={})
        stage_ctx.pipeline_run_id = ctx.pipeline_run_id
        stage_ctx.request_id = ctx.request_id

        output = await test_stage.execute(stage_ctx)

        results = output.data.get("results", [])
        stats = output.data.get("tracker_stats", {})

        # Analyze results
        passed_count = sum(1 for r in results if r.get("validation_passed"))
        failed_count = len(results) - passed_count
        expected_vs_actual = sum(
            1 for r in results
            if r.get("expected_pass") == r.get("validation_passed")
        )

        logger.info(f"Baseline test results:")
        logger.info(f"  Total tests: {len(results)}")
        logger.info(f"  Passed validation: {passed_count}")
        logger.info(f"  Failed validation: {failed_count}")
        logger.info(f"  Expected vs Actual match: {expected_vs_actual}/{len(results)}")

        return {
            "test_type": "baseline",
            "total_tests": len(results),
            "passed": passed_count,
            "failed": failed_count,
            "expected_vs_actual_match": expected_vs_actual,
            "results": results,
            "stats": stats,
            "execution_time_ms": output.data.get("execution_time_ms", 0),
        }


async def main():
    """Run the baseline pipeline."""
    pipeline = BaselinePipeline()
    results = await pipeline.run()

    # Save results
    output_file = Path(__file__).parent / "results" / "work009_baseline_results.json"
    output_file.parent.mkdir(exist_ok=True)

    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"Results saved to {output_file}")

    return results


if __name__ == "__main__":
    results = asyncio.run(main())
    print(f"\nBaseline Test Summary:")
    print(f"  Total: {results['total_tests']}")
    print(f"  Passed: {results['passed']}")
    print(f"  Failed: {results['failed']}")
