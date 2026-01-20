"""
CONTRACT-006: Nested Object Validation Depth Test Pipelines

Stress-tests Stageflow's nested object validation depth:
- Baseline validation with normal nesting
- Stress testing with deep nesting
- Chaos testing with malformed nested data
- Silent failure detection
- Performance benchmarking
"""

import asyncio
import json
import uuid
import time
import logging
from datetime import datetime
from typing import Any, Optional
from pathlib import Path

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

from mocks.nested_validation_mocks import (
    MockNestedDataGenerator,
    generate_nested_dict,
    generate_deeply_nested_with_type_mismatch,
    generate_max_depth_structure,
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class NestedOutputStage(Stage):
    """Stage that outputs nested data structures."""
    name = "nested_output"
    kind = StageKind.TRANSFORM
    
    def __init__(self, nested_data: dict[str, Any]):
        self.nested_data = nested_data
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        return StageOutput.ok(**self.nested_data)


class NestedConsumerStage(Stage):
    """Stage that consumes and validates nested data."""
    name = "nested_consumer"
    kind = StageKind.TRANSFORM
    
    def __init__(self, access_path: str = None):
        self.access_path = access_path
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        if self.access_path:
            # Navigate to specific nested path
            keys = self.access_path.split(".")
            value = ctx.inputs.get(keys[0])
            for key in keys[1:]:
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    return StageOutput.fail(
                        error=f"Cannot navigate path '{self.access_path}': {keys[0]} is not a dict",
                        data={"path": self.access_path, "type": type(value).__name__}
                    )
            return StageOutput.ok(
                accessed_value=value,
                access_path=self.access_path,
                value_type=type(value).__name__ if value is not None else "None"
            )
        else:
            # Get all data
            all_data = {}
            for key in ["user", "profile", "data", "result"]:
                value = ctx.inputs.get(key)
                if value is not None:
                    all_data[key] = {
                        "type": type(value).__name__,
                        "is_dict": isinstance(value, dict),
                        "is_nested": isinstance(value, dict) and any(
                            isinstance(v, dict) for v in value.values()
                        )
                    }
            
            return StageOutput.ok(
                consumption_summary=all_data,
                total_keys=len(all_data)
            )


class DeepNestingProducerStage(Stage):
    """Stage that produces deeply nested structures for stress testing."""
    name = "deep_producer"
    kind = StageKind.TRANSFORM
    
    def __init__(self, depth: int = 10):
        self.depth = depth
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        nested = generate_nested_dict(self.depth, max_width=2)
        return StageOutput.ok(deep_nested=nested, depth=self.depth)


class TypeMismatchInjectorStage(Stage):
    """Stage that intentionally produces type mismatches at depth."""
    name = "type_mismatch"
    kind = StageKind.TRANSFORM
    
    def __init__(self, depth: int = 5):
        self.depth = depth
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        # Build structure with intentional type mismatch
        data = {}
        current = data
        for i in range(self.depth - 1):
            current[f"level_{i}"] = {}
            current = current[f"level_{i}"]
        
        # Inject type mismatch at deepest level
        current["value"] = 42  # int where string expected
        
        # Also create a case where dict is replaced with string
        data["should_be_dict"] = "string_instead_of_dict"
        
        return StageOutput.ok(mixed_data=data)


class ValidationReporterStage(Stage):
    """Stage that reports validation results."""
    name = "validation_reporter"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        # Collect all inputs
        all_inputs = {}
        for key in ctx.inputs.get_all() if hasattr(ctx.inputs, 'get_all') else []:
            all_inputs[key] = ctx.inputs.get(key)
        
        # Validate structure
        validation_results = {
            "input_count": len(all_inputs),
            "has_nested": any(
                isinstance(v, dict) and any(isinstance(vv, dict) for vv in v.values())
                for v in all_inputs.values() if isinstance(v, dict)
            ),
            "max_depth_found": 0,
            "type_distribution": {}
        }
        
        for key, value in all_inputs.items():
            if isinstance(value, dict):
                def get_depth(d, current=0):
                    if not isinstance(d, dict):
                        return current
                    if not d:
                        return current
                    return max(get_depth(v, current + 1) for v in d.values())
                
                depth = get_depth(value)
                validation_results["max_depth_found"] = max(
                    validation_results["max_depth_found"], depth
                )
        
        return StageOutput.ok(validation=validation_results)


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
        topology="contract006_test",
    )
    
    return snapshot, output_bag, pipeline_ctx


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


async def test_baseline_nested_validation():
    """Test 1: Baseline - Normal nested data validation."""
    print("\n" + "="*60)
    print("TEST 1: Baseline Nested Validation")
    print("="*60)
    
    snapshot, output_bag, pipeline_ctx = create_test_context()
    
    generator = MockNestedDataGenerator()
    nested_data = generator.get_happy_path_data()
    
    stages = [
        ("nested_output", NestedOutputStage(nested_data), StageKind.TRANSFORM, []),
        ("nested_consumer", NestedConsumerStage(), StageKind.TRANSFORM, ["nested_output"]),
    ]
    
    result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
    
    print(f"Result: {result['status']}")
    if result['success']:
        print("[PASS] Normal nested data processed successfully")
    else:
        print(f"[FAIL] Failed: {result.get('error', 'Unknown error')}")
    
    return result


async def test_deep_nesting_performance():
    """Test 2: Deep nesting performance benchmark."""
    print("\n" + "="*60)
    print("TEST 2: Deep Nesting Performance Benchmark")
    print("="*60)
    
    generator = MockNestedDataGenerator()
    depth_benchmarks = generator.get_depth_benchmark_data()
    
    results = []
    for depth, data in depth_benchmarks.items():
        snapshot, output_bag, pipeline_ctx = create_test_context()
        
        stages = [
            ("deep_producer", DeepNestingProducerStage(depth), StageKind.TRANSFORM, []),
            ("validation_reporter", ValidationReporterStage(), StageKind.TRANSFORM, ["deep_producer"]),
        ]
        
        start_time = time.time()
        result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
        end_time = time.time()
        
        duration_ms = (end_time - start_time) * 1000
        
        results.append({
            "depth": depth,
            "duration_ms": duration_ms,
            "success": result['success'],
            "error": result.get('error')
        })
        
        status = "[PASS]" if result['success'] else "[FAIL]"
        print(f"  Depth {depth:2d}: {duration_ms:8.2f}ms {status}")
    
    # Analyze performance
    durations = [r['duration_ms'] for r in results if r['duration_ms'] > 0]
    max_duration = max(durations) if durations else 0
    min_duration = min(durations) if durations else 0
    
    print(f"\nPerformance Analysis:")
    print(f"  Min: {min_duration:.2f}ms")
    print(f"  Max: {max_duration:.2f}ms")
    if min_duration > 0:
        print(f"  Range: {max_duration/min_duration:.1f}x")
    
    return {
        "benchmark_results": results,
        "max_duration_ms": max_duration,
        "min_duration_ms": min_duration,
    }


async def test_type_mismatch_detection():
    """Test 3: Type mismatch detection in nested data."""
    print("\n" + "="*60)
    print("TEST 3: Type Mismatch Detection")
    print("="*60)
    
    snapshot, output_bag, pipeline_ctx = create_test_context()
    
    stages = [
        ("type_mismatch", TypeMismatchInjectorStage(depth=5), StageKind.TRANSFORM, []),
        ("nested_consumer", NestedConsumerStage("mixed_data.should_be_dict"), StageKind.TRANSFORM, ["type_mismatch"]),
    ]
    
    result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
    
    print(f"Result: {result['status']}")
    if result['success']:
        consumer_output = result.get('results', {}).get('outputs', {}).get('nested_consumer', {})
        accessed_value = consumer_output.get('data', {}).get('accessed_value', 'N/A')
        print(f"  Accessed value: {accessed_value} (type: {type(accessed_value).__name__})")
        
        if accessed_value == "string_instead_of_dict":
            print("[INFO] Type mismatch detected but not validated - data passed through")
        else:
            print("[WARN] Unexpected behavior with type mismatch")
    else:
        print(f"[PASS] Type mismatch properly detected: {result.get('error', 'Unknown error')}")
    
    return result


async def test_missing_nested_field():
    """Test 4: Accessing missing nested fields."""
    print("\n" + "="*60)
    print("TEST 4: Missing Nested Field Access")
    print("="*60)
    
    snapshot, output_bag, pipeline_ctx = create_test_context()
    
    # Create simple data without deep nesting
    simple_data = {"top_level": "value", "another": 42}
    
    stages = [
        ("nested_output", NestedOutputStage(simple_data), StageKind.TRANSFORM, []),
        ("nested_consumer", NestedConsumerStage("top_level.nested.does_not_exist"), StageKind.TRANSFORM, ["nested_output"]),
    ]
    
    result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
    
    print(f"Result: {result['status']}")
    if result['success']:
        consumer_output = result.get('results', {}).get('outputs', {}).get('nested_consumer', {})
        accessed_value = consumer_output.get('data', {}).get('accessed_value', 'N/A')
        print(f"  Accessed value: {accessed_value}")
        print("[WARN] Missing nested field accessed without error - potential silent failure!")
    else:
        print(f"[PASS] Missing field access properly handled: {result.get('error', 'Unknown error')}")
    
    return result


async def test_max_depth_handling():
    """Test 5: Maximum depth structure handling."""
    print("\n" + "="*60)
    print("TEST 5: Maximum Depth Structure (15 levels)")
    print("="*60)
    
    snapshot, output_bag, pipeline_ctx = create_test_context()
    
    max_depth_data = generate_max_depth_structure()
    
    stages = [
        ("nested_output", NestedOutputStage(max_depth_data), StageKind.TRANSFORM, []),
        ("validation_reporter", ValidationReporterStage(), StageKind.TRANSFORM, ["nested_output"]),
    ]
    
    result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
    
    print(f"Result: {result['status']}")
    if result['success']:
        reporter_output = result.get('results', {}).get('outputs', {}).get('validation_reporter', {})
        validation = reporter_output.get('data', {}).get('validation', {})
        print(f"  Max depth found: {validation.get('max_depth_found', 'N/A')}")
        print("[PASS] 15-level deep structure handled")
    else:
        print(f"[FAIL] Failed: {result.get('error', 'Unknown error')}")
    
    return result


async def test_silent_failure_detection():
    """Test 6: Silent failure detection in nested validation."""
    print("\n" + "="*60)
    print("TEST 6: Silent Failure Detection")
    print("="*60)
    
    silent_failures = []
    
    # Test 6a: Type coercion silently changing data
    print("\n  Test 6a: Type coercion silently changing nested values")
    snapshot, output_bag, pipeline_ctx = create_test_context()
    
    # Data with string that should be int
    type_coerced_data = {
        "level1": {
            "level2": {
                "numeric_string": "123",  # String that looks like number
                "actual_number": 456
            }
        }
    }
    
    stages = [
        ("nested_output", NestedOutputStage(type_coerced_data), StageKind.TRANSFORM, []),
        ("validation_reporter", ValidationReporterStage(), StageKind.TRANSFORM, ["nested_output"]),
    ]
    
    result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
    if result['success']:
        # Check if type coercion occurred silently
        print("  [WARN] Type coercion may have occurred silently")
        silent_failures.append("Type coercion in nested data not validated")
    
    # Test 6b: Data loss in deep nesting
    print("\n  Test 6b: Data loss in deep nesting")
    snapshot, output_bag, pipeline_ctx = create_test_context()
    
    deep_data = generate_nested_dict(depth=20, max_width=5)
    
    stages = [
        ("nested_output", NestedOutputStage({"deep": deep_data}), StageKind.TRANSFORM, []),
        ("validation_reporter", ValidationReporterStage(), StageKind.TRANSFORM, ["nested_output"]),
    ]
    
    result = await run_pipeline_with_stages(stages, snapshot, output_bag, pipeline_ctx)
    if not result['success']:
        silent_failures.append(f"Deep nesting caused failure: {result.get('error')}")
    
    return {
        "silent_failures": silent_failures,
        "silent_failure_count": len(silent_failures)
    }


async def run_all_tests():
    """Run all nested validation tests."""
    print("\n" + "="*70)
    print("CONTRACT-006: Nested Object Validation Depth Tests")
    print("="*70)
    
    test_results = []
    
    test_results.append(("baseline_nested_validation", await test_baseline_nested_validation()))
    test_results.append(("deep_nesting_performance", await test_deep_nesting_performance()))
    test_results.append(("type_mismatch_detection", await test_type_mismatch_detection()))
    test_results.append(("missing_nested_field", await test_missing_nested_field()))
    test_results.append(("max_depth_handling", await test_max_depth_handling()))
    test_results.append(("silent_failure_detection", await test_silent_failure_detection()))
    
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for name, result in test_results:
        status = "[PASS]" if result.get('success') else "[FAIL]"
        print(f"{status}: {name}")
    
    # Silent failure summary
    silent_test = test_results[-1][1]
    if isinstance(silent_test, dict) and silent_test.get('silent_failure_count', 0) > 0:
        print(f"\n[WARN] Silent failures detected: {silent_test['silent_failure_count']}")
        for sf in silent_test.get('silent_failures', []):
            print(f"  - {sf}")
    
    return test_results


if __name__ == "__main__":
    results = asyncio.run(run_all_tests())
    
    print("\n" + "="*70)
    print("Tests completed. Results above.")
    print("="*70)
