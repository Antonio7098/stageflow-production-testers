"""
CONTRACT-004: Contract Violation Error Messaging Test Pipeline

Stress-tests Stageflow's contract violation error messages for:
- Clarity and actionability
- Context completeness
- Consistency across error types
- Programmatic handling support
- Debugging experience
"""

import asyncio
import uuid
from datetime import datetime
from typing import Any

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
)
from stageflow.stages.inputs import UndeclaredDependencyError
from stageflow.pipeline.spec import PipelineValidationError, CycleDetectedError
from stageflow.pipeline.dag import StageExecutionError
from stageflow.context import ContextSnapshot, OutputBag
from stageflow.stages.result import StageError


class SimpleStage(Stage):
    """Simple stage that returns OK with data."""
    name = "simple"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        ctx.emit_event("simple_stage.executed", {"timestamp": datetime.utcnow().isoformat()})
        return StageOutput.ok(result="simple_done", value=42)


class FailingStage(Stage):
    """Stage that intentionally fails."""
    name = "failing"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        raise ValueError("Intentional failure for testing")


class SlowStage(Stage):
    """Stage that simulates slow operation."""
    name = "slow"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        await asyncio.sleep(0.1)
        return StageOutput.ok(slow_result="completed")


class AccessorStage(Stage):
    """Stage that tries to access undeclared dependency."""
    name = "accessor"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        # This will trigger UndeclaredDependencyError
        data = ctx.inputs.get_from("source", "data")
        return StageOutput.ok(data=data)


class MultiAccessorStage(Stage):
    """Stage that accesses multiple undeclared dependencies."""
    name = "multi_accessor"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        # Access multiple undeclared dependencies
        a = ctx.inputs.get_from("stage_a", "value")
        b = ctx.inputs.get_from("stage_b", "value")
        return StageOutput.ok(a=a, b=b)


class OutputWriterStage(Stage):
    """Stage that writes output."""
    name = "output_writer"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        return StageOutput.ok(output_key="output_value")


class SecondWriterStage(Stage):
    """Second stage that writes to same key."""
    name = "second_writer"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        return StageOutput.ok(output_key="duplicate_value")


def create_test_snapshot() -> ContextSnapshot:
    """Create a test context snapshot."""
    return ContextSnapshot(
        input_text="test input",
        execution_mode="test",
    )


def evaluate_error_message(
    error: Exception,
    test_name: str,
    expected_elements: list[str] = None,
) -> dict[str, Any]:
    """
    Evaluate error message quality.
    
    Returns evaluation result with:
    - message: The error message string
    - clarity_score: 1-5 rating
    - context_completeness: dict of context elements found
    - actionability: list of fix suggestions found
    - issues: list of problems identified
    """
    result = {
        "test_name": test_name,
        "error_type": type(error).__name__,
        "message": str(error),
        "clarity_score": 0,
        "context_completeness": {},
        "actionability": [],
        "issues": [],
        "attributes": {},
        "evaluation_timestamp": datetime.utcnow().isoformat(),
    }
    
    # Extract attributes based on error type
    if isinstance(error, UndeclaredDependencyError):
        result["attributes"] = {
            "stage": getattr(error, "stage_name", None),
            "dependency": getattr(error, "dependency", None),
            "declared_deps": getattr(error, "declared_deps", None),
            "accessing_stage": getattr(error, "accessing_stage", None),
        }
    elif isinstance(error, CycleDetectedError):
        result["attributes"] = {
            "cycle_path": getattr(error, "cycle_path", None),
            "stages": getattr(error, "stages", None),
        }
    elif isinstance(error, StageExecutionError):
        result["attributes"] = {
            "stage": getattr(error, "stage", None),
            "original": getattr(error, "original", None),
        }
    elif isinstance(error, PipelineValidationError):
        result["attributes"] = {
            "args": getattr(error, "args", None),
        }
    
    message = result["message"]
    
    # Check for context elements
    context_checks = {
        "has_stage_name": "stage" in message.lower() or "stage_name" in message,
        "has_dependency_info": "dependency" in message.lower() or "depend" in message.lower(),
        "has_error_type": type(error).__name__ in message or error.__doc__,
        "has_fix_suggestion": "add" in message.lower() or "fix" in message.lower() or "declare" in message.lower(),
        "has_code_example": "depends_on" in message or "dependencies=" in message,
    }
    result["context_completeness"] = context_checks
    
    # Check actionability
    actionability_checks = [
        "Add" in message,
        "fix" in message.lower(),
        "declare" in message.lower(),
        "depends_on" in message,
        "dependencies=" in message,
    ]
    result["actionability"] = [a for i, a in enumerate([
        "Add missing dependency instruction",
        "Fix instruction",
        "Declare dependency instruction",
        "depends_on syntax",
        "dependencies= syntax",
    ]) if actionability_checks[i]]
    
    # Calculate clarity score
    score = 0
    if context_checks["has_stage_name"]:
        score += 1
    if context_checks["has_dependency_info"]:
        score += 1
    if context_checks["has_error_type"]:
        score += 1
    if context_checks["has_fix_suggestion"]:
        score += 1
    if context_checks["has_code_example"]:
        score += 1
    result["clarity_score"] = score
    
    # Identify issues
    if not context_checks["has_stage_name"]:
        result["issues"].append("Missing stage name in error message")
    if not context_checks["has_fix_suggestion"]:
        result["issues"].append("No fix guidance provided")
    if not context_checks["has_code_example"]:
        result["issues"].append("No code example for fix")
    if len(message) > 500:
        result["issues"].append("Error message too long")
    if len(message) < 20:
        result["issues"].append("Error message too short, lacks detail")
    
    return result


async def test_undeclared_dependency_error():
    """Test UndeclaredDependencyError message quality."""
    results = []
    
    # Test 1: Single undeclared dependency
    try:
        pipeline = (
            Pipeline()
            .with_stage("source", SimpleStage, StageKind.TRANSFORM)
            .with_stage("accessor", AccessorStage, StageKind.TRANSFORM)
        )
        # accessor doesn't declare 'source' as dependency
        graph = pipeline.build()
        snapshot = create_test_snapshot()
        output_bag = OutputBag()
        
        # Run the pipeline
        from stageflow import run_with_interceptors
        await run_with_interceptors(
            graph=graph,
            snapshot=snapshot,
            output_bag=output_bag,
        )
    except UndeclaredDependencyError as e:
        results.append(evaluate_error_message(e, "single_undeclared_dependency"))
    except Exception as e:
        results.append({
            "test_name": "single_undeclared_dependency",
            "error_type": type(e).__name__,
            "message": str(e),
            "issues": [f"Unexpected error type: {type(e).__name__}"],
            "clarity_score": 0,
        })
    
    # Test 2: Multiple undeclared dependencies
    try:
        pipeline = (
            Pipeline()
            .with_stage("stage_a", SimpleStage, StageKind.TRANSFORM)
            .with_stage("stage_b", SimpleStage, StageKind.TRANSFORM)
            .with_stage("multi_accessor", MultiAccessorStage, StageKind.TRANSFORM)
        )
        graph = pipeline.build()
        snapshot = create_test_snapshot()
        output_bag = OutputBag()
        
        await run_with_interceptors(
            graph=graph,
            snapshot=snapshot,
            output_bag=output_bag,
        )
    except UndeclaredDependencyError as e:
        results.append(evaluate_error_message(e, "multiple_undeclared_dependencies"))
    except Exception as e:
        results.append({
            "test_name": "multiple_undeclared_dependencies",
            "error_type": type(e).__name__,
            "message": str(e),
            "issues": [f"Unexpected error type: {type(e).__name__}"],
            "clarity_score": 0,
        })
    
    return results


async def test_cycle_detected_error():
    """Test CycleDetectedError message quality."""
    results = []
    
    try:
        # Create a pipeline with a cycle: A -> B -> C -> A
        class StageA(Stage):
            name = "a"
            kind = StageKind.TRANSFORM
            async def execute(self, ctx: StageContext) -> StageOutput:
                return StageOutput.ok()
        
        class StageB(Stage):
            name = "b"
            kind = StageKind.TRANSFORM
            async def execute(self, ctx: StageContext) -> StageOutput:
                return StageOutput.ok()
        
        class StageC(Stage):
            name = "c"
            kind = StageKind.TRANSFORM
            async def execute(self, ctx: StageContext) -> StageOutput:
                return StageOutput.ok()
        
        pipeline = (
            Pipeline()
            .with_stage("a", StageA, StageKind.TRANSFORM)
            .with_stage("b", StageB, StageKind.TRANSFORM, dependencies=("a",))
            .with_stage("c", StageC, StageKind.TRANSFORM, dependencies=("b",))
            # Intentionally create cycle
            .with_stage("a_again", StageA, StageKind.TRANSFORM, dependencies=("c",))
        )
        graph = pipeline.build()
    except CycleDetectedError as e:
        results.append(evaluate_error_message(e, "cycle_detected"))
    except Exception as e:
        results.append({
            "test_name": "cycle_detected",
            "error_type": type(e).__name__,
            "message": str(e),
            "issues": [f"Unexpected error type: {type(e).__name__}"],
            "clarity_score": 0,
        })
    
    return results


async def test_pipeline_validation_error():
    """Test PipelineValidationError message quality."""
    results = []
    
    # Test: Non-existent dependency
    try:
        pipeline = (
            Pipeline()
            .with_stage("stage_a", SimpleStage, StageKind.TRANSFORM)
            .with_stage("stage_b", SimpleStage, StageKind.TRANSFORM, dependencies=("nonexistent",))
        )
        graph = pipeline.build()
    except PipelineValidationError as e:
        results.append(evaluate_error_message(e, "nonexistent_dependency"))
    except Exception as e:
        results.append({
            "test_name": "nonexistent_dependency",
            "error_type": type(e).__name__,
            "message": str(e),
            "issues": [f"Unexpected error type: {type(e).__name__}"],
            "clarity_score": 0,
        })
    
    return results


async def test_stage_execution_error():
    """Test StageExecutionError message quality."""
    results = []
    
    try:
        pipeline = (
            Pipeline()
            .with_stage("failing", FailingStage, StageKind.TRANSFORM)
        )
        graph = pipeline.build()
        snapshot = create_test_snapshot()
        output_bag = OutputBag()
        
        await run_with_interceptors(
            graph=graph,
            snapshot=snapshot,
            output_bag=output_bag,
        )
    except StageExecutionError as e:
        result = evaluate_error_message(e, "stage_execution_error")
        # Check for exception chaining
        result["has_exception_chaining"] = (
            e.__cause__ is not None or 
            hasattr(e, 'original') and e.original is not None
        )
        result["original_exception"] = str(getattr(e, 'original', None))
        results.append(result)
    except Exception as e:
        results.append({
            "test_name": "stage_execution_error",
            "error_type": type(e).__name__,
            "message": str(e),
            "issues": [f"Unexpected error type: {type(e).__name__}"],
            "clarity_score": 0,
        })
    
    return results


async def test_output_conflict_error():
    """Test OutputConflictError message quality."""
    results = []
    
    # This would require concurrent stage execution which is complex to set up
    # We'll test the error class directly if available
    try:
        from stageflow.context.output_bag import OutputConflictError
        # Check the constructor signature
        try:
            error = OutputConflictError("test_key", "stage_a")
            results.append(evaluate_error_message(error, "output_conflict"))
        except TypeError as e:
            # Try with the correct signature
            error = OutputConflictError(key="test_key", stage_name="stage_a")
            results.append(evaluate_error_message(error, "output_conflict"))
    except ImportError as e:
        results.append({
            "test_name": "output_conflict",
            "error_type": "ImportError",
            "message": f"OutputConflictError not importable: {e}",
            "issues": ["Could not import OutputConflictError"],
            "clarity_score": 0,
        })
    except Exception as e:
        results.append({
            "test_name": "output_conflict",
            "error_type": type(e).__name__,
            "message": str(e),
            "issues": [f"Unexpected error: {type(e).__name__}"],
            "clarity_score": 0,
        })
    
    return results


async def run_all_tests():
    """Run all error message tests and return results."""
    print("=" * 70)
    print("CONTRACT-004: Contract Violation Error Messaging Tests")
    print("=" * 70)
    
    all_results = {
        "test_run_timestamp": datetime.utcnow().isoformat(),
        "test_run_id": "contract004-2026-01-19-001",
        "summary": {
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "average_clarity_score": 0.0,
        },
        "detailed_results": [],
    }
    
    test_functions = [
        ("UndeclaredDependencyError", test_undeclared_dependency_error),
        ("CycleDetectedError", test_cycle_detected_error),
        ("PipelineValidationError", test_pipeline_validation_error),
        ("StageExecutionError", test_stage_execution_error),
        ("OutputConflictError", test_output_conflict_error),
    ]
    
    total_score = 0
    total_tests = 0
    
    for test_category, test_func in test_functions:
        print(f"\n--- Testing {test_category} ---")
        try:
            results = await test_func()
            for result in results:
                print(f"\nTest: {result.get('test_name', 'unknown')}")
                print(f"  Error Type: {result.get('error_type', 'unknown')}")
                print(f"  Message: {result.get('message', 'N/A')[:200]}...")
                print(f"  Clarity Score: {result.get('clarity_score', 0)}/5")
                
                if result.get('issues'):
                    print(f"  Issues: {result.get('issues')}")
                
                if result.get('attributes'):
                    print(f"  Attributes: {result.get('attributes')}")
                
                all_results["detailed_results"].append(result)
                total_tests += 1
                if result.get('clarity_score', 0) > 0:
                    total_score += result.get('clarity_score', 0)
        except Exception as e:
            print(f"  ERROR in {test_category}: {e}")
            all_results["detailed_results"].append({
                "test_category": test_category,
                "error": str(e),
                "issues": [f"Test suite error: {type(e).__name__}"],
            })
    
    # Calculate summary
    all_results["summary"]["total_tests"] = total_tests
    all_results["summary"]["average_clarity_score"] = round(total_score / max(total_tests, 1), 2)
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total Tests: {all_results['summary']['total_tests']}")
    print(f"Average Clarity Score: {all_results['summary']['average_clarity_score']}/5")
    
    return all_results


if __name__ == "__main__":
    import json
    results = asyncio.run(run_all_tests())
    
    # Save results
    output_file = "results/test_results_contract004.json"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\nResults saved to {output_file}")
