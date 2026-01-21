"""
WORK-009 Tool Output Validation - Mock Tools

Mock tools with various output types for testing validation scenarios:
- Valid outputs (conforming to expected schemas)
- Invalid outputs (missing fields, wrong types, etc.)
- Edge cases (null values, empty data, malformed structures)
- Chaos outputs (malicious payloads, circular refs, etc.)
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime, UTC

from stageflow.tools import BaseTool, ToolInput, ToolOutput


class OutputTracker:
    """Track tool outputs for validation testing."""
    def __init__(self):
        self.outputs: List[Dict[str, Any]] = []
        self.validation_errors: List[Dict[str, Any]] = []
        self.silent_failures: List[Dict[str, Any]] = []

    def record(self, tool_name: str, output: ToolOutput, expected_schema: Dict[str, Any] = None):
        """Record a tool output for later analysis."""
        record = {
            "tool_name": tool_name,
            "timestamp": datetime.now(UTC).isoformat(),
            "success": output.success,
            "data": output.data,
            "error": output.error,
            "has_expected_schema": expected_schema is not None,
        }
        self.outputs.append(record)

        if expected_schema:
            is_valid = self._validate_against_schema(output.data, expected_schema)
            record["schema_validation_passed"] = is_valid
            if not is_valid:
                self.validation_errors.append({
                    "tool_name": tool_name,
                    "output": output.data,
                    "expected_schema": expected_schema,
                    "timestamp": record["timestamp"],
                })

    def _validate_against_schema(self, data: Any, schema: Dict[str, Any]) -> bool:
        """Simple schema validation for testing."""
        if data is None:
            return not schema.get("required", [])
        if not isinstance(data, dict):
            return schema.get("type") in ["any", None]
        
        # Check required fields
        required = schema.get("required", [])
        for field_name in required:
            if field_name not in data:
                return False
        
        # Check types
        properties = schema.get("properties", {})
        for field_name, field_schema in properties.items():
            if field_name in data and data[field_name] is not None:
                expected_type = field_schema.get("type")
                if expected_type and expected_type != "any":
                    actual_type = type(data[field_name]).__name__
                    if expected_type == "integer" and isinstance(data[field_name], float):
                        if not data[field_name].is_integer():
                            return False
                    elif expected_type == "number" and not isinstance(data[field_name], (int, float)):
                        return False
                    elif expected_type == "string" and not isinstance(data[field_name], str):
                        return False
                    elif expected_type == "boolean" and not isinstance(data[field_name], bool):
                        return False
                    elif expected_type == "array" and not isinstance(data[field_name], list):
                        return False
                    elif expected_type == "object" and not isinstance(data[field_name], dict):
                        return False
        
        return True

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_outputs": len(self.outputs),
            "validation_errors": len(self.validation_errors),
            "silent_failures": len(self.silent_failures),
        }


class ValidUserTool(BaseTool):
    """Tool that returns valid user data matching expected schema."""
    name = "valid_user"
    description = "Returns valid user data"
    action_type = "GET_USER"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        return ToolOutput.ok(data={
            "user_id": "user_123",
            "name": "Alice",
            "email": "alice@example.com",
            "age": 30,
            "active": True,
            "roles": ["admin", "user"],
            "profile": {
                "avatar": "avatar.png",
                "bio": "Software engineer",
            }
        })


class MissingFieldsTool(BaseTool):
    """Tool that returns data missing required fields."""
    name = "missing_fields"
    description = "Returns data missing required fields"
    action_type = "GET_USER"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        return ToolOutput.ok(data={
            "user_id": "user_123",
            # Missing: name, email, age, etc.
        })


class WrongTypeTool(BaseTool):
    """Tool that returns data with wrong types."""
    name = "wrong_type"
    description = "Returns data with incorrect types"
    action_type = "GET_USER"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        return ToolOutput.ok(data={
            "user_id": 123,  # Should be string
            "name": "Alice",
            "email": "alice@example.com",
            "age": "thirty",  # Should be integer
            "active": "yes",  # Should be boolean
            "roles": "admin,user",  # Should be array
        })


class NullValuesTool(BaseTool):
    """Tool that returns data with null values where required."""
    name = "null_values"
    description = "Returns data with null values"
    action_type = "GET_USER"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        return ToolOutput.ok(data={
            "user_id": "user_123",
            "name": None,  # Null where string expected
            "email": "alice@example.com",
            "age": None,  # Null where integer expected
            "active": True,
        })


class EmptyDataTool(BaseTool):
    """Tool that returns empty data."""
    name = "empty_data"
    description = "Returns empty data"
    action_type = "GET_USER"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        return ToolOutput.ok(data={})


class NestedInvalidTool(BaseTool):
    """Tool that returns data with invalid nested structure."""
    name = "nested_invalid"
    description = "Returns data with invalid nested structure"
    action_type = "GET_ORDER"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        return ToolOutput.ok(data={
            "order_id": "order_456",
            "items": "not_an_array",  # Should be array
            "total": "99.99",  # Should be number
            "customer": {
                "id": 789,
                "name": "Bob",
                "contacts": "not_an_array",  # Should be array
            }
        })


class ExtraFieldsTool(BaseTool):
    """Tool that returns data with extra unexpected fields."""
    name = "extra_fields"
    description = "Returns data with extra fields"
    action_type = "GET_USER"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        return ToolOutput.ok(data={
            "user_id": "user_123",
            "name": "Alice",
            "email": "alice@example.com",
            "age": 30,
            "active": True,
            "secret_token": "abc123",  # Extra field
            "internal_id": 999,  # Extra field
        })


class MalformedDataTool(BaseTool):
    """Tool that returns malformed data."""
    name = "malformed_data"
    description = "Returns malformed data"
    action_type = "GET_USER"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        return ToolOutput.ok(data={
            "user_id": "user_123",
            "name": "Alice",
            "metadata": "{invalid_json",  # Malformed JSON string
        })


class DeepNestingTool(BaseTool):
    """Tool that returns deeply nested data."""
    name = "deep_nesting"
    description = "Returns deeply nested data"
    action_type = "GET_COMPLEX_DATA"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        nested = {"value": 1}
        for i in range(20):
            nested = {"level": i, "data": nested}
        return ToolOutput.ok(data={
            "id": "test_1",
            "deep": nested,
        })


class TypeMismatchDeepTool(BaseTool):
    """Tool with type mismatch at deep nesting level."""
    name = "type_mismatch_deep"
    description = "Returns data with type mismatch at deep level"
    action_type = "GET_COMPLEX_DATA"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        return ToolOutput.ok(data={
            "id": "test_2",
            "level_0": {
                "level_1": {
                    "level_2": {
                        "level_3": {
                            "value": "should_be_number",  # Wrong type
                        }
                    }
                }
            }
        })


class AsyncDelayTool(BaseTool):
    """Tool with async delay that returns valid data."""
    name = "async_delay"
    description = "Returns valid data after delay"
    action_type = "ASYNC_OPERATION"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        delay_ms = input.payload.get("delay_ms", 100)
        await asyncio.sleep(delay_ms / 1000)
        return ToolOutput.ok(data={
            "status": "completed",
            "delay_ms": delay_ms,
            "timestamp": datetime.now(UTC).isoformat(),
        })


class FailingTool(BaseTool):
    """Tool that fails with error."""
    name = "failing_tool"
    description = "Always fails"
    action_type = "FAIL_OPERATION"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        return ToolOutput.fail(error="Intentional failure for testing")


class PartialSuccessTool(BaseTool):
    """Tool that reports success but has partial data."""
    name = "partial_success"
    description = "Reports success but missing critical data"
    action_type = "GET_PARTIAL"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        return ToolOutput.ok(data={
            "status": "success",
            "items": ["item1", "item2"],
            "total_count": 100,
            # Missing: "next_page_token" which is required for pagination
        })


class SchemaValidationTool(BaseTool):
    """Tool that validates output against a schema internally."""
    name = "schema_validation"
    description = "Tool that internally validates its output"
    action_type = "VALIDATED_OPERATION"

    SCHEMA = {
        "type": "object",
        "required": ["status", "result_id"],
        "properties": {
            "status": {"type": "string"},
            "result_id": {"type": "string"},
            "metadata": {"type": "object"},
        }
    }

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        # Simulate validation
        output_data = {
            "status": "success",
            "result_id": str(uuid.uuid4()),
            "metadata": {"created_at": datetime.now(UTC).isoformat()},
        }
        
        # Note: In real implementation, this would validate against SCHEMA
        # Currently Stageflow doesn't support this natively
        
        return ToolOutput.ok(data=output_data)


class SilentFailureTool(BaseTool):
    """Tool that silently fails - returns success but with invalid data."""
    name = "silent_failure"
    description = "Appears to succeed but returns invalid data"
    action_type = "SILENT_OPERATION"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        # Returns success=True but data is completely wrong
        return ToolOutput.ok(data={
            "success": True,
            "data": "this_is_a_string_not_an_object",  # Should be object
            "error": None,
        })


class CircularRefTool(BaseTool):
    """Tool that returns data with circular references."""
    name = "circular_ref"
    description = "Returns data with circular references"
    action_type = "GET_REF_DATA"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        data = {"name": "parent"}
        data["child"] = {"name": "child", "parent": data}  # Circular ref
        return ToolOutput.ok(data=data)


class LargeOutputTool(BaseTool):
    """Tool that returns very large output."""
    name = "large_output"
    description = "Returns large output data"
    action_type = "GET_LARGE_DATA"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        # Generate ~1MB of data
        items = [{"id": i, "data": "x" * 1000} for i in range(1000)]
        return ToolOutput.ok(data={"items": items, "total": len(items)})


class InconsistentTypeTool(BaseTool):
    """Tool that returns inconsistent types based on input."""
    name = "inconsistent_type"
    description = "Returns different types based on input"
    action_type = "GET_DATA"

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        data_type = input.payload.get("data_type", "object")
        if data_type == "object":
            return ToolOutput.ok(data={"key": "value"})
        elif data_type == "array":
            return ToolOutput.ok(data=["item1", "item2"])
        elif data_type == "string":
            return ToolOutput.ok(data="just_a_string")
        elif data_type == "null":
            return ToolOutput.ok(data=None)
        else:
            return ToolOutput.ok(data=123)


class ValidationTestTool(BaseTool):
    """Configurable tool for validation testing."""
    name = "validation_test"
    description = "Tool with configurable output for validation testing"
    action_type = "VALIDATION_TEST"

    def __init__(self, output_config: Dict[str, Any]):
        self.output_config = output_config

    async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
        return ToolOutput.ok(data=self.output_config)


# Expected schemas for validation testing
EXPECTED_SCHEMAS = {
    "user": {
        "type": "object",
        "required": ["user_id", "name", "email", "age", "active"],
        "properties": {
            "user_id": {"type": "string"},
            "name": {"type": "string"},
            "email": {"type": "string"},
            "age": {"type": "integer"},
            "active": {"type": "boolean"},
            "roles": {"type": "array"},
            "profile": {"type": "object"},
        }
    },
    "order": {
        "type": "object",
        "required": ["order_id", "items", "total", "customer"],
        "properties": {
            "order_id": {"type": "string"},
            "items": {"type": "array"},
            "total": {"type": "number"},
            "customer": {"type": "object"},
        }
    },
    "simple_status": {
        "type": "object",
        "required": ["status"],
        "properties": {
            "status": {"type": "string"},
        }
    },
}


def register_validation_tools(registry):
    """Register all validation test tools with the registry."""
    registry.register(ValidUserTool())
    registry.register(MissingFieldsTool())
    registry.register(WrongTypeTool())
    registry.register(NullValuesTool())
    registry.register(EmptyDataTool())
    registry.register(NestedInvalidTool())
    registry.register(ExtraFieldsTool())
    registry.register(MalformedDataTool())
    registry.register(DeepNestingTool())
    registry.register(TypeMismatchDeepTool())
    registry.register(AsyncDelayTool())
    registry.register(FailingTool())
    registry.register(PartialSuccessTool())
    registry.register(SchemaValidationTool())
    registry.register(SilentFailureTool())
    registry.register(CircularRefTool())
    registry.register(LargeOutputTool())
    registry.register(InconsistentTypeTool())
    registry.register(ValidationTestTool(output_config={"test": "value"}))


def create_tool_with_output(output_data: Dict[str, Any], tool_name: str = "custom_tool") -> BaseTool:
    """Factory function to create a tool with specific output."""
    class CustomTool(BaseTool):
        name = tool_name
        description = f"Custom tool returning {type(output_data)}"
        action_type = "CUSTOM_OPERATION"

        async def execute(self, input: ToolInput, ctx: dict) -> ToolOutput:
            return ToolOutput.ok(data=output_data)

    return CustomTool()
