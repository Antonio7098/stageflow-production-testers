"""Schema mapping accuracy test pipelines for TRANSFORM-002.

This module contains test pipelines for validating schema mapping accuracy
in TRANSFORM stages across various scenarios.
"""

import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import stageflow as sf
from stageflow import (
    Pipeline, StageContext, StageKind, StageOutput, PipelineTimer
)
from stageflow.context import ContextSnapshot, RunIdentity

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# ============================================================================
# Schema Definitions for Testing
# ============================================================================

class UserSchema:
    """User schema definition for validation tests."""
    
    @staticmethod
    def validate_user(data: dict) -> tuple[bool, list[str]]:
        """Validate user data against schema."""
        errors = []
        
        # Required field checks
        required_fields = ["user_id", "email", "full_name", "age", "account_balance", "is_active", "created_at"]
        for field in required_fields:
            if field not in data:
                errors.append(f"Missing required field: {field}")
            elif data[field] is None:
                errors.append(f"Field {field} is None")
        
        # Type checks
        if "user_id" in data and data["user_id"] is not None and not isinstance(data["user_id"], str):
            errors.append(f"user_id must be string, got {type(data['user_id']).__name__}")
        
        if "email" in data and data["email"] is not None:
            if not isinstance(data["email"], str):
                errors.append(f"email must be string, got {type(data['email']).__name__}")
            elif "@" not in data["email"]:
                errors.append(f"email format invalid: {data['email']}")
        
        if "age" in data and data["age"] is not None:
            if not isinstance(data["age"], (int, float)):
                errors.append(f"age must be numeric, got {type(data['age']).__name__}")
            elif data["age"] < 0 or data["age"] > 150:
                errors.append(f"age out of range: {data['age']}")
        
        if "account_balance" in data and data["account_balance"] is not None:
            if not isinstance(data["account_balance"], (int, float)):
                errors.append(f"account_balance must be numeric, got {type(data['account_balance']).__name__}")
        
        if "is_active" in data and data["is_active"] is not None:
            if not isinstance(data["is_active"], bool):
                errors.append(f"is_active must be boolean, got {type(data['is_active']).__name__}")
        
        return len(errors) == 0, errors


# ============================================================================
# TRANSFORM Stages for Schema Mapping Tests
# ============================================================================

class SchemaValidationStage:
    """Stage that validates input against a schema."""
    
    name = "schema_validation"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        input_data = ctx.snapshot.metadata.get("input_data", {}) if ctx.snapshot.metadata else {}
        
        is_valid, errors = UserSchema.validate_user(input_data)
        
        if is_valid:
            return StageOutput.ok(
                validated=True,
                schema_version="1.0",
                errors=[]
            )
        else:
            return StageOutput.fail(
                error="Schema validation failed",
                data={
                    "validated": False,
                    "errors": errors,
                    "input_fields": list(input_data.keys())
                }
            )


class SchemaMappingStage:
    """Stage that maps fields from source to target schema."""
    
    def __init__(self, field_mapping: dict[str, str]):
        self.field_mapping = field_mapping
    
    name = "schema_mapping"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        input_data = ctx.snapshot.metadata.get("input_data", {}) if ctx.snapshot.metadata else {}
        input_fields = ctx.inputs.get("input_data") or input_data
        
        mapped_data = {}
        unmapped_fields = []
        
        for target_field, source_field in self.field_mapping.items():
            if source_field in input_fields:
                value = input_fields[source_field]
                # Type coercion based on target field
                if target_field == "age" and value is not None:
                    try:
                        value = int(float(str(value)))
                    except (ValueError, TypeError):
                        value = None
                elif target_field == "account_balance" and value is not None:
                    try:
                        value = float(str(value))
                    except (ValueError, TypeError):
                        value = None
                elif target_field == "is_active" and value is not None:
                    if isinstance(value, str):
                        value = value.lower() in ("true", "1", "yes")
                    else:
                        value = bool(value)
                mapped_data[target_field] = value
            else:
                unmapped_fields.append(source_field)
        
        # Check for missing required fields
        required_mapped = [f for f in self.field_mapping.keys()]
        missing_required = [f for f in required_mapped if f not in mapped_data or mapped_data[f] is None]
        
        if missing_required:
            return StageOutput.fail(
                error=f"Missing required mapped fields: {missing_required}",
                data={
                    "mapped_data": mapped_data,
                    "unmapped_source": unmapped_fields,
                    "missing_required": missing_required
                }
            )
        
        return StageOutput.ok(
            mapped_data=mapped_data,
            unmapped_source=unmapped_fields,
            mapping_complete=True
        )


class TypeCoercionStage:
    """Stage that tests type coercion behavior."""
    
    name = "type_coercion"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        input_data = ctx.snapshot.metadata.get("input_data", {}) if ctx.snapshot.metadata else {}
        
        results = {}
        coerce_log = []
        
        for field, value in input_data.items():
            original_type = type(value).__name__
            original_value = value
            
            # Test various type coercions
            if field == "string_to_int":
                try:
                    coerced = int(value) if value is not None else None
                    results[field] = coerced
                    coerce_log.append(f"{field}: '{original_value}' ({original_type}) -> {coerced} (int)")
                except (ValueError, TypeError) as e:
                    results[field] = None
                    coerce_log.append(f"{field}: Failed to coerce '{original_value}': {e}")
            
            elif field == "float_to_int":
                try:
                    coerced = int(float(value)) if value is not None else None
                    results[field] = coerced
                    coerce_log.append(f"{field}: '{original_value}' ({original_type}) -> {coerced} (int)")
                except (ValueError, TypeError) as e:
                    results[field] = None
                    coerce_log.append(f"{field}: Failed to coerce '{original_value}': {e}")
            
            elif field == "bool_string":
                if isinstance(value, str):
                    coerced = value.lower() in ("true", "1", "yes", "on")
                    results[field] = coerced
                    coerce_log.append(f"{field}: '{original_value}' ({original_type}) -> {coerced} (bool)")
                else:
                    results[field] = bool(value)
                    coerce_log.append(f"{field}: {original_value} ({original_type}) -> {results[field]} (bool)")
            
            elif field == "number_string":
                try:
                    coerced = float(value) if value is not None else None
                    results[field] = coerced
                    coerce_log.append(f"{field}: '{original_value}' ({original_type}) -> {coerced} (float)")
                except (ValueError, TypeError) as e:
                    results[field] = None
                    coerce_log.append(f"{field}: Failed to coerce '{original_value}': {e}")
            
            else:
                # No coercion - pass through
                results[field] = value
                coerce_log.append(f"{field}: No coercion needed ({original_type})")
        
        return StageOutput.ok(
            coerced_values=results,
            coerce_log=coerce_log,
            coercion_complete=True
        )


class NestedFieldAccessStage:
    """Stage that tests accessing nested fields."""
    
    name = "nested_access"
    kind = StageKind.TRANSFORM
    
    def __init__(self, path: str):
        self.path = path
        self.path_parts = path.split(".")
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        input_data = ctx.snapshot.metadata.get("input_data", {}) if ctx.snapshot.metadata else {}
        
        try:
            value = input_data
            for part in self.path_parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return StageOutput.fail(
                        error=f"Nested path not found: {self.path}",
                        data={
                            "path": self.path,
                            "found_path": self.path_parts[:self.path_parts.index(part)] if part in str(value) else [],
                            "available_keys": list(value.keys()) if isinstance(value, dict) else str(type(value))
                        }
                    )
            
            return StageOutput.ok(
                nested_value=value,
                path=self.path,
                success=True
            )
        
        except Exception as e:
            return StageOutput.fail(
                error=f"Nested access error: {str(e)}",
                data={
                    "path": self.path,
                    "exception_type": type(e).__name__
                }
            )


class SchemaDriftStage:
    """Stage that detects and handles schema drift."""
    
    name = "schema_drift_detection"
    kind = StageKind.TRANSFORM
    
    def __init__(self, expected_fields: list[str], required_fields: list[str]):
        self.expected_fields = set(expected_fields)
        self.required_fields = set(required_fields)
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        input_data = ctx.snapshot.metadata.get("input_data", {}) if ctx.snapshot.metadata else {}
        
        actual_fields = set(input_data.keys())
        
        # Detect added fields (new in source)
        added_fields = actual_fields - self.expected_fields
        
        # Detect missing fields (removed from source)
        missing_fields = self.expected_fields - actual_fields
        
        # Check required fields
        missing_required = self.required_fields - actual_fields
        
        # Detect type changes (would need comparison with previous version)
        type_changes = []
        
        drift_info = {
            "added_fields": list(added_fields),
            "missing_fields": list(missing_fields),
            "missing_required": list(missing_required),
            "type_changes": type_changes,
            "total_fields": len(actual_fields),
            "drift_detected": len(added_fields) > 0 or len(missing_fields) > 0
        }
        
        if missing_required:
            return StageOutput.fail(
                error="Schema drift: required fields missing",
                data={
                    **drift_info,
                    "severity": "critical"
                }
            )
        elif drift_info["drift_detected"]:
            return StageOutput.ok(
                **drift_info,
                severity="warning"
            )
        else:
            return StageOutput.ok(
                **drift_info,
                severity="none"
            )


class ValidationReporterStage:
    """Stage that reports validation results."""
    
    name = "validation_reporter"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        validation_result = ctx.inputs.get("validation_result")
        mapping_result = ctx.inputs.get("mapping_result")
        drift_result = ctx.inputs.get("drift_result")
        
        all_valid = True
        all_errors = []
        
        for result_name, result in [("validation", validation_result), ("mapping", mapping_result), ("drift", drift_result)]:
            if result and hasattr(result, 'data'):
                data = result.data if hasattr(result, 'data') else result
                if isinstance(data, dict):
                    if data.get("validated") == False or data.get("validated") == False:
                        all_valid = False
                        all_errors.append(f"{result_name}: {data.get('error', 'Unknown error')}")
                    if data.get("severity") == "critical":
                        all_valid = False
                        all_errors.append(f"{result_name}: Critical severity - {data}")
        
        return StageOutput.ok(
            all_valid=all_valid,
            errors=all_errors,
            timestamp=datetime.now().isoformat()
        )


# ============================================================================
# Pipeline Builders
# ============================================================================

def create_baseline_pipeline() -> Pipeline:
    """Create a baseline pipeline for happy path schema mapping."""
    return (
        Pipeline()
        .with_stage("validate", SchemaValidationStage, StageKind.TRANSFORM)
        .with_stage(
            "map",
            SchemaMappingStage({
                "user_id": "uid",
                "email": "email_address",
                "full_name": "name",
                "age": "years_old",
                "account_balance": "balance",
                "is_active": "active_flag",
                "created_at": "registration_date"
            }),
            StageKind.TRANSFORM,
            dependencies=("validate",)
        )
        .with_stage("report", ValidationReporterStage, StageKind.TRANSFORM, dependencies=("map",))
    )


def create_type_coercion_pipeline() -> Pipeline:
    """Create a pipeline for testing type coercion."""
    return (
        Pipeline()
        .with_stage("coerce", TypeCoercionStage, StageKind.TRANSFORM)
    )


def create_nested_access_pipeline(path: str) -> Pipeline:
    """Create a pipeline for testing nested field access."""
    return (
        Pipeline()
        .with_stage("access", NestedFieldAccessStage(path), StageKind.TRANSFORM)
    )


def create_schema_drift_pipeline() -> Pipeline:
    """Create a pipeline for testing schema drift detection."""
    return (
        Pipeline()
        .with_stage(
            "drift_detect",
            SchemaDriftStage(
                expected_fields=["user_id", "email", "full_name", "age", "account_balance", "is_active", "created_at"],
                required_fields=["user_id", "email"]
            ),
            StageKind.TRANSFORM
        )
    )


# ============================================================================
# Pipeline Execution Utilities
# ============================================================================

async def run_pipeline_with_data(
    pipeline: Pipeline,
    input_data: dict,
    run_id: str = "test"
) -> dict[str, Any]:
    """Execute a pipeline with the given input data."""
    
    graph = pipeline.build()
    
    snapshot = ContextSnapshot(
        run_id=RunIdentity(
            pipeline_run_id=uuid4(),
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            org_id=None,
            interaction_id=uuid4(),
        ),
        topology=f"transform002_{run_id}",
        execution_mode="test",
        metadata={"input_data": input_data},
    )
    
    ctx = StageContext(
        snapshot=snapshot,
        inputs=sf.StageInputs(snapshot=snapshot),
        stage_name="pipeline_entry",
        timer=PipelineTimer(),
    )
    
    results = await graph.run(ctx)
    
    return {
        "input": input_data,
        "results": {name: (result.data if hasattr(result, 'data') else str(result)) for name, result in results.items()},
        "success": all(
            hasattr(result, 'data') and 
            (result.data.get("validated", True) if isinstance(result.data, dict) else True)
            for result in results.values()
        )
    }


async def run_suite(pipeline_name: str, pipeline: Pipeline, test_data: list[dict]) -> dict[str, Any]:
    """Run a suite of tests with the given pipeline and data."""
    
    results = []
    successes = 0
    failures = 0
    
    for i, data in enumerate(test_data):
        try:
            result = await run_pipeline_with_data(pipeline, data, f"{pipeline_name}_{i}")
            results.append(result)
            if result["success"]:
                successes += 1
            else:
                failures += 1
        except Exception as e:
            results.append({
                "input": data,
                "error": str(e),
                "success": False
            })
            failures += 1
    
    return {
        "pipeline": pipeline_name,
        "total": len(test_data),
        "successes": successes,
        "failures": failures,
        "success_rate": successes / len(test_data) if test_data else 0,
        "results": results
    }


if __name__ == "__main__":
    # Quick test
    async def main():
        # Create test data
        test_data = [
            {
                "uid": "user_001",
                "email_address": "test@example.com",
                "name": "John Doe",
                "years_old": 30,
                "balance": 100.50,
                "active_flag": True,
                "registration_date": "2024-01-15T10:30:00Z"
            },
            {
                "uid": "user_002",
                "email_address": "invalid-email",
                "name": "Jane Doe",
                "years_old": 25,
                "balance": 200.75,
                "active_flag": "yes",
                "registration_date": "2024-01-16T14:45:00Z"
            }
        ]
        
        pipeline = create_baseline_pipeline()
        
        for data in test_data:
            result = await run_pipeline_with_data(pipeline, data, "quick_test")
            print(f"\nInput: {data}")
            print(f"Success: {result['success']}")
            print(f"Results: {json.dumps(result['results'], indent=2, default=str)}")
    
    asyncio.run(main())
