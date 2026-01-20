"""
CONTRACT-005: Optional vs Required Field Enforcement Test Pipeline

Stress-tests Stageflow's field validation for:
- Required vs optional field handling
- Silent failure detection
- Type coercion behavior
- Missing field handling
- Default value behavior
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, Optional
import logging

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stageflow
from stageflow import (
    Pipeline,
    Stage,
    StageKind,
    StageOutput,
    StageContext,
    StageStatus,
    create_stage_context,
    create_test_snapshot,
)
from stageflow.context import ContextSnapshot, RunIdentity, OutputBag
from stageflow.stages.context import PipelineContext
from stageflow.stages.inputs import StageInputs, create_stage_inputs
from stageflow.helpers import LLMResponse

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class RequiredFieldOutputStage(Stage):
    """Stage that outputs required fields."""
    name = "required_output"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        return StageOutput.ok(
            required_field="value1",
            optional_field="value2",
            numeric_field=42,
        )


class OptionalFieldOnlyStage(Stage):
    """Stage that outputs only optional fields."""
    name = "optional_only"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        return StageOutput.ok(optional_field="optional_value")


class MissingRequiredFieldStage(Stage):
    """Stage that intentionally omits required fields."""
    name = "missing_required"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        return StageOutput.ok(
            optional_field="only_optional",
            missing_required="this should cause issues downstream",
        )


class TypeCoercionTestStage(Stage):
    """Stage that tests type coercion behavior."""
    name = "type_coercion"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        return StageOutput.ok(
            string_as_int="123",
            int_as_string=456,
            float_as_int=99.9,
            bool_as_int=True,
        )


class FieldConsumerStage(Stage):
    """Stage that consumes fields from upstream stages."""
    name = "field_consumer"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        required = ctx.inputs.get("required_field")
        optional = ctx.inputs.get("optional_field")
        numeric = ctx.inputs.get("numeric_field")
        missing = ctx.inputs.get("missing_field")
        
        return StageOutput.ok(
            received_required=required,
            received_optional=optional,
            received_numeric=numeric,
            received_missing=missing,
            all_fields=dict(ctx.inputs.get_all()) if hasattr(ctx.inputs, 'get_all') else {},
        )


class StrictFieldConsumerStage(Stage):
    """Stage that requires specific fields to be present."""
    name = "strict_consumer"
    kind = StageKind.GUARD
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        required = ctx.inputs.get("required_field")
        
        if required is None:
            return StageOutput.fail(
                error="Required field 'required_field' is missing",
                data={"field": "required_field", "received": None},
            )
        
        return StageOutput.ok(validated=required)


class DefaultValueStage(Stage):
    """Stage that uses default values when fields are missing."""
    name = "default_value"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        value = ctx.inputs.get("field", default="default_value")
        return StageOutput.ok(value=value, has_default=True)


class TypeValidationStage(Stage):
    """Stage that tests type validation of received values."""
    name = "type_validation"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        string_as_int = ctx.inputs.get("string_as_int")
        int_as_string = ctx.inputs.get("int_as_string")
        
        results = {}
        
        if string_as_int is not None:
            results["string_as_int_type"] = type(string_as_int).__name__
            results["string_as_int_value"] = string_as_int
            
        if int_as_string is not None:
            results["int_as_string_type"] = type(int_as_string).__name__
            results["int_as_string_value"] = int_as_string
        
        return StageOutput.ok(type_checks=results)


class PartialOutputStage(Stage):
    """Stage that outputs partial data on subsequent runs."""
    name = "partial_output"
    kind = StageKind.TRANSFORM
    
    def __init__(self, run_id: str = "first"):
        self.run_id = run_id
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        if self.run_id == "first":
            return StageOutput.ok(field_a="a", field_b="b", field_c="c")
        else:
            return StageOutput.ok(field_a="a")


class AllFieldsConsumerStage(Stage):
    """Stage that tries to consume all expected fields."""
    name = "all_consumer"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        field_a = ctx.inputs.get("field_a")
        field_b = ctx.inputs.get("field_b")
        field_c = ctx.inputs.get("field_c")
        
        return StageOutput.ok(
            field_a=field_a,
            field_b=field_b,
            field_c=field_c,
            all_present=all([field_a, field_b, field_c]),
        )


def create_test_context(
    input_text: str = "test",
    user_id: Optional[uuid.UUID] = None,
) -> tuple[ContextSnapshot, OutputBag, PipelineContext]:
    """Create test context components."""
    run_id = RunIdentity(
        pipeline_run_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        org_id=uuid.uuid4(),
        interaction_id=uuid.uuid4(),
    )
    
    snapshot = ContextSnapshot(
        run_id=run_id,
        input_text=input_text,
        execution_mode="test",
    )
    
    output_bag = OutputBag()
    
    pipeline_ctx = PipelineContext(
        pipeline_run_id=run_id.pipeline_run_id,
        request_id=run_id.request_id,
        session_id=run_id.session_id,
        user_id=run_id.user_id,
        org_id=run_id.org_id,
        interaction_id=run_id.interaction_id,
        topology="contract005_test",
    )
    
    return snapshot, output_bag, pipeline_ctx


def create_stage_inputs_for_test(
    snapshot: ContextSnapshot,
    output_bag: OutputBag,
    stage_name: str,
    prior_outputs: dict[str, StageOutput] = None,
    declared_deps: list[str] = None,
    strict: bool = True,
) -> StageInputs:
    """Create StageInputs for testing."""
    if prior_outputs is None:
        prior_outputs = {}
    
    outputs_dict = {name: output for name, output in output_bag.outputs()}
    outputs_dict.update(prior_outputs)
    
    return create_stage_inputs(
        snapshot=snapshot,
        prior_outputs=outputs_dict,
        declared_deps=frozenset(declared_deps or []),
        stage_name=stage_name,
        strict=strict,
    )


async def run_pipeline_with_stages(
    stages: list[tuple[str, Stage, StageKind, list[str]]],
    snapshot: ContextSnapshot,
    output_bag: OutputBag,
    pipeline_ctx: PipelineContext,
) -> dict[str, Any]:
    """Run a pipeline with the given stages."""
    from stageflow import StageContext, StageInputs, PipelineTimer
    
    pipeline = Pipeline()
    
    for name, stage_class, kind, deps in stages:
        pipeline = pipeline.with_stage(name, stage_class, kind, dependencies=deps)
    
    graph = pipeline.build()
    
    try:
        ctx = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name="pipeline_entry",
            timer=PipelineTimer(),
        )
        
        results = await graph.run(ctx)
        
        return {
            "success": True,
            "status": "completed",
            "results": results,
        }
    except Exception as e:
        return {
            "success": False,
            "status": "failed",
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def test_baseline_field_contract():
    """Test 1: Baseline - All required fields present."""
    print("\n" + "="*60)
    print("TEST 1: Baseline Field Contract")
    print("="*60)
    
    snapshot, output_bag, pipeline_ctx = create_test_context()
    
    stages = [
        ("required_output", RequiredFieldOutputStage, StageKind.TRANSFORM, []),
        ("field_consumer", FieldConsumerStage, StageKind.TRANSFORM, ["required_output"]),
    ]
    
    result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
    
    print(f"Result: {result['status']}")
    if result['success']:
        print("[PASS] All required fields present - pipeline completed successfully")
    else:
        print(f"[FAIL] Failed: {result.get('error', 'Unknown error')}")
    
    return result


async def test_missing_required_field():
    """Test 2: Missing required field - downstream stage behavior."""
    print("\n" + "="*60)
    print("TEST 2: Missing Required Field")
    print("="*60)
    
    snapshot, output_bag, pipeline_ctx = create_test_context()
    
    stages = [
        ("missing_required", MissingRequiredFieldStage, StageKind.TRANSFORM, []),
        ("field_consumer", FieldConsumerStage, StageKind.TRANSFORM, ["missing_required"]),
    ]
    
    result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
    
    print(f"Result: {result['status']}")
    if result['success']:
        print("[WARN] Silent failure: Pipeline completed but field was missing!")
        print("  - field_consumer received None for required_field")
        print("  - No error was raised!")
    else:
        print(f"[PASS] Error properly detected: {result.get('error', 'Unknown error')}")
    
    return result


async def test_strict_field_validation():
    """Test 3: Strict field validation with GUARD stage."""
    print("\n" + "="*60)
    print("TEST 3: Strict Field Validation (GUARD)")
    print("="*60)
    
    snapshot, output_bag, pipeline_ctx = create_test_context()
    
    stages = [
        ("missing_required", MissingRequiredFieldStage, StageKind.TRANSFORM, []),
        ("strict_consumer", StrictFieldConsumerStage, StageKind.GUARD, ["missing_required"]),
    ]
    
    result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
    
    print(f"Result: {result['status']}")
    if result['success']:
        print("[WARN] Silent failure: GUARD stage didn't detect missing field!")
    else:
        print("[PASS] GUARD properly rejected missing field")
    
    return result


async def test_type_coercion_behavior():
    """Test 4: Type coercion in StageOutput data."""
    print("\n" + "="*60)
    print("TEST 4: Type Coercion Behavior")
    print("="*60)
    
    snapshot, output_bag, pipeline_ctx = create_test_context()
    
    stages = [
        ("type_coercion", TypeCoercionTestStage, StageKind.TRANSFORM, []),
        ("type_validation", TypeValidationStage, StageKind.TRANSFORM, ["type_coercion"]),
    ]
    
    result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
    
    print(f"Result: {result['status']}")
    if result['success']:
        print("[PASS] Type coercion test completed")
    else:
        print(f"[FAIL] Failed: {result.get('error', 'Unknown error')}")
    
    return result


async def test_default_value_behavior():
    """Test 5: Default values when fields are missing."""
    print("\n" + "="*60)
    print("TEST 5: Default Value Behavior")
    print("="*60)
    
    snapshot, output_bag, pipeline_ctx = create_test_context()
    
    stages = [
        ("default_value", DefaultValueStage, StageKind.TRANSFORM, []),
    ]
    
    result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
    
    print(f"Result: {result['status']}")
    if result['success']:
        print("[PASS] Default value behavior works as expected")
    else:
        print(f"[FAIL] Failed: {result.get('error', 'Unknown error')}")
    
    return result


async def test_optional_field_only():
    """Test 6: Pipeline with only optional fields."""
    print("\n" + "="*60)
    print("TEST 6: Optional Field Only Pipeline")
    print("="*60)
    
    snapshot, output_bag, pipeline_ctx = create_test_context()
    
    stages = [
        ("optional_only", OptionalFieldOnlyStage, StageKind.TRANSFORM, []),
        ("field_consumer", FieldConsumerStage, StageKind.TRANSFORM, ["optional_only"]),
    ]
    
    result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
    
    print(f"Result: {result['status']}")
    if result['success']:
        print("[PASS] Optional-only pipeline completed")
        print("  - required_field received None (no error)")
    else:
        print(f"[FAIL] Failed: {result.get('error', 'Unknown error')}")
    
    return result


async def test_partial_output_consumer():
    """Test 7: Consumer with partial output."""
    print("\n" + "="*60)
    print("TEST 7: Partial Output Consumer")
    print("="*60)
    
    snapshot, output_bag, pipeline_ctx = create_test_context()
    
    stages = [
        ("partial_output", PartialOutputStage, StageKind.TRANSFORM, []),
        ("all_consumer", AllFieldsConsumerStage, StageKind.TRANSFORM, ["partial_output"]),
    ]
    
    result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
    
    print(f"Result: {result['status']}")
    if result['success']:
        print("[WARN] Partial output test completed silently")
        print("  - field_b and field_c may be missing")
    else:
        print(f"[FAIL] Failed: {result.get('error', 'Unknown error')}")
    
    return result


async def test_concurrent_field_access():
    """Test 8: Concurrent field access with race conditions."""
    print("\n" + "="*60)
    print("TEST 8: Concurrent Field Access")
    print("="*60)
    
    async def run_concurrent_test():
        tasks = []
        for i in range(10):
            task = test_baseline_field_contract()
            tasks.append(task)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
    
    results = await run_concurrent_test()
    
    success_count = sum(1 for r in results if isinstance(r, dict) and r.get('success'))
    print(f"Concurrent test results: {success_count}/10 successful")
    
    if success_count < 10:
        print("[WARN] Race conditions detected in concurrent execution!")
    
    return {"success_count": success_count, "total": 10}


async def run_all_tests():
    """Run all field validation tests."""
    print("\n" + "="*70)
    print("CONTRACT-005: Optional vs Required Field Enforcement Tests")
    print("="*70)
    
    test_results = []
    
    test_results.append(("baseline_field_contract", await test_baseline_field_contract()))
    test_results.append(("missing_required_field", await test_missing_required_field()))
    test_results.append(("strict_field_validation", await test_strict_field_validation()))
    test_results.append(("type_coercion_behavior", await test_type_coercion_behavior()))
    test_results.append(("default_value_behavior", await test_default_value_behavior()))
    test_results.append(("optional_field_only", await test_optional_field_only()))
    test_results.append(("partial_output_consumer", await test_partial_output_consumer()))
    test_results.append(("concurrent_field_access", await test_concurrent_field_access()))
    
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for name, result in test_results:
        status = "[PASS]" if result.get('success') else "[FAIL]"
        print(f"{status}: {name}")
    
    silent_failures = 0
    for name, result in test_results:
        if result.get('success') and 'silent' in str(result).lower():
            silent_failures += 1
            print(f"[WARN] SILENT FAILURE: {name}")
    
    if silent_failures > 0:
        print(f"\n[WARN] Detected {silent_failures} potential silent failures!")
    
    return test_results


if __name__ == "__main__":
    results = asyncio.run(run_all_tests())
    
    print("\n" + "="*70)
    print("Tests completed. Results above.")
    print("="*70)
