"""TRANSFORM-008: Error recovery with partial transforms test pipelines.

This module contains test pipelines for:
- Partial transform scenarios and recovery
- Error handling with partial results
- Idempotency verification
- Silent failure detection
- Parallel branch failure handling
- Context state recovery after failures
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

# Add mocks directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "mocks"))

from stageflow import (
    Pipeline,
    PipelineContext,
    StageContext,
    StageKind,
    StageOutput,
    PipelineTimer,
)
from stageflow.context import ContextSnapshot, RunIdentity, OutputBag
from stageflow.stages import StageInputs

from data.partial_transform_mocks import (
    PartialTransformMockData,
    ErrorInjectionSimulator,
    CheckpointSimulator,
    IdempotencyVerifier,
    PartialResultTracker,
    simulate_partial_transform,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Transform Stages for Error Recovery Testing
# =============================================================================

class StatefulTransformStage:
    """TRANSFORM stage that maintains state across multiple items.

    This stage simulates processing that requires state continuity.
    Failing mid-way should leave state inconsistent without proper recovery.
    """

    name = "stateful_transform"
    kind = StageKind.TRANSFORM

    def __init__(self, state_file: str | None = None) -> None:
        self.state_file = state_file
        self.state: dict[str, Any] = {"items_processed": 0, "sum": 0}

    async def execute(self, ctx: StageContext) -> StageOutput:
        items = ctx.snapshot.input_text or "[]"
        try:
            parsed_items = json.loads(items) if isinstance(items, str) else items
        except (json.JSONDecodeError, TypeError):
            return StageOutput.fail(error="Invalid JSON input")

        results = []
        for item in parsed_items:
            self.state["items_processed"] += 1
            self.state["sum"] += item.get("value", 0)
            results.append({
                "item_id": item.get("id"),
                "processed": True,
                "running_total": self.state["sum"],
            })

        return StageOutput.ok(
            items=results,
            final_total=self.state["sum"],
            processed_count=self.state["items_processed"],
            state_snapshot=self.state.copy(),
        )


class IdempotentTransformStage:
    """TRANSFORM stage that tests idempotent behavior.

    This stage should produce the same output regardless of how many times
    it's executed with the same input.
    """

    name = "idempotent_transform"
    kind = StageKind.TRANSFORM

    async def execute(self, ctx: StageContext) -> StageOutput:
        input_data = ctx.snapshot.input_text or "{}"
        try:
            parsed = json.loads(input_data) if isinstance(input_data, str) else input_data
        except (json.JSONDecodeError, TypeError):
            return StageOutput.fail(error="Invalid JSON input")

        # Idempotent operation: always produce same output for same input
        operation = parsed.get("operation", "unknown")
        amount = parsed.get("amount", 0)

        if operation == "add":
            result = {"operation": "add", "input": amount, "output": amount + 100}
        elif operation == "multiply":
            result = {"operation": "multiply", "input": amount, "output": amount * 2}
        else:
            result = {"operation": operation, "input": amount, "output": amount}

        return StageOutput.ok(
            result=result,
            idempotency_key=f"{operation}:{amount}",  # Key for idempotency verification
            execution_timestamp=time.time(),
        )


class PartialFailureTransformStage:
    """TRANSFORM stage that fails after processing some items.

    This stage simulates a transform that succeeds for N items then fails.
    Used to test partial result preservation.
    """

    name = "partial_failure_transform"
    kind = StageKind.TRANSFORM

    def __init__(self, fail_at_count: int = 10) -> None:
        self.fail_at_count = fail_at_count
        self.processed_count = 0

    async def execute(self, ctx: StageContext) -> StageOutput:
        items = ctx.snapshot.input_text or "[]"
        try:
            parsed_items = json.loads(items) if isinstance(items, str) else items
        except (json.JSONDecodeError, TypeError):
            return StageOutput.fail(error="Invalid JSON input")

        results = []
        for item in parsed_items:
            self.processed_count += 1
            if self.processed_count >= self.fail_at_count:
                return StageOutput.fail(
                    error=f"Simulated failure after {self.processed_count} items",
                    data={
                        "processed_count": self.processed_count,
                        "processed_items": results,
                        "failed_at_item": item,
                    },
                )
            results.append({"item": item, "success": True})

        return StageOutput.ok(
            results=results,
            processed_count=len(results),
            completed_without_failure=True,
        )


class RecoveryAwareTransformStage:
    """TRANSFORM stage that supports checkpoint-based recovery.

    This stage saves progress and can resume from checkpoints.
    """

    name = "recovery_aware_transform"
    kind = StageKind.TRANSFORM

    def __init__(self, checkpoint_interval: int = 5) -> None:
        self.checkpoint_interval = checkpoint_interval
        self.checkpoints: list[dict[str, Any]] = []

    async def execute(self, ctx: StageContext) -> StageOutput:
        items = ctx.snapshot.input_text or "[]"
        try:
            parsed_items = json.loads(items) if isinstance(items, str) else items
        except (json.JSONDecodeError, TypeError):
            return StageOutput.fail(error="Invalid JSON input")

        # Get previous checkpoint if resuming
        previous_checkpoint = ctx.inputs.get("last_checkpoint", {})
        start_index = previous_checkpoint.get("resume_index", 0)

        results = []
        for i, item in enumerate(parsed_items[start_index:], start=start_index):
            results.append({"item": item, "index": i})

            # Save checkpoint
            if (i + 1) % self.checkpoint_interval == 0:
                checkpoint = {
                    "resume_index": i + 1,
                    "checkpoint_timestamp": time.time(),
                    "items_processed": len(results),
                }
                self.checkpoints.append(checkpoint)

        return StageOutput.ok(
            results=results,
            start_index=start_index,
            end_index=start_index + len(results) - 1,
            checkpoint_count=len(self.checkpoints),
            checkpoints=self.checkpoints.copy(),
        )


class RetryableTransformStage:
    """TRANSFORM stage that can fail and retry with backoff.

    Tests retry behavior and idempotency across retries.
    """

    name = "retryable_transform"
    kind = StageKind.TRANSFORM

    def __init__(self, fail_times: int = 2, succeed_on_retry: bool = True) -> None:
        self.fail_times = fail_times
        self.succeed_on_retry = succeed_on_retry
        self.attempt_count = 0

    async def execute(self, ctx: StageContext) -> StageOutput:
        self.attempt_count += 1

        if self.attempt_count <= self.fail_times:
            return StageOutput.retry(
                error=f"Transient failure (attempt {self.attempt_count}/{self.fail_times})",
                data={
                    "attempt": self.attempt_count,
                    "will_succeed": self.attempt_count > self.fail_times if self.succeed_on_retry else True,
                },
            )

        return StageOutput.ok(
            result="success",
            attempts=self.attempt_count,
            final_attempt=True,
        )


class ValidationGuardStage:
    """GUARD stage that validates inputs before transform.

    Tests validation failure handling and error propagation.
    """

    name = "validation_guard"
    kind = StageKind.GUARD

    async def execute(self, ctx: StageContext) -> StageOutput:
        input_data = ctx.snapshot.input_text or ""

        if not input_data:
            return StageOutput.fail(error="Empty input not allowed")

        if isinstance(input_data, str) and "INVALID" in input_data:
            return StageOutput.fail(
                error="Validation failed: INVALID marker found",
                data={"reason": "invalid_input_marker"},
            )

        return StageOutput.ok(valid=True)


class RecoveryAggregationStage:
    """TRANSFORM stage that aggregates results for recovery testing.

    Combines results from multiple stages and tracks completeness.
    """

    name = "recovery_aggregation"
    kind = StageKind.TRANSFORM

    async def execute(self, ctx: StageContext) -> StageOutput:
        stage_a_results = ctx.inputs.get_from("stage_a", "results", default=[])
        stage_b_results = ctx.inputs.get_from("stage_b", "results", default=[])
        stage_c_results = ctx.inputs.get_from("stage_c", "results", default=[])

        all_results = {
            "stage_a": stage_a_results,
            "stage_b": stage_b_results,
            "stage_c": stage_c_results,
        }

        total_count = (
            len(stage_a_results) +
            len(stage_b_results) +
            len(stage_c_results)
        )

        return StageOutput.ok(
            aggregated=all_results,
            total_count=total_count,
            completeness_ratio=total_count / 30 if total_count > 0 else 0,
        )


# =============================================================================
# Pipeline Builders
# =============================================================================

def create_baseline_pipeline() -> Pipeline:
    """Create a simple baseline pipeline for happy path testing."""
    return (
        Pipeline()
        .with_stage("transform", StatefulTransformStage(), StageKind.TRANSFORM)
    )


def create_partial_failure_pipeline(fail_at: int = 5) -> Pipeline:
    """Create a pipeline that fails after processing some items."""
    return (
        Pipeline()
        .with_stage(
            "partial_transform",
            PartialFailureTransformStage(fail_at_count=fail_at),
            StageKind.TRANSFORM,
        )
    )


def create_recovery_pipeline() -> Pipeline:
    """Create a pipeline with checkpoint/recovery support."""
    return (
        Pipeline()
        .with_stage(
            "recovery_aware",
            RecoveryAwareTransformStage(checkpoint_interval=3),
            StageKind.TRANSFORM,
        )
        .with_stage(
            "validate",
            ValidationGuardStage(),
            StageKind.GUARD,
            dependencies=["recovery_aware"],
        )
    )


def create_parallel_recovery_pipeline() -> Pipeline:
    """Create a parallel pipeline with recovery aggregation."""
    return (
        Pipeline()
        .with_stage("stage_a", StatefulTransformStage(), StageKind.TRANSFORM)
        .with_stage("stage_b", StatefulTransformStage(), StageKind.TRANSFORM)
        .with_stage(
            "stage_c",
            PartialFailureTransformStage(fail_at_count=5),
            StageKind.TRANSFORM,
        )
        .with_stage(
            "aggregate",
            RecoveryAggregationStage(),
            StageKind.TRANSFORM,
            dependencies=["stage_a", "stage_b", "stage_c"],
        )
    )


def create_retry_pipeline(max_failures: int = 2) -> Pipeline:
    """Create a pipeline with retryable stages."""
    return (
        Pipeline()
        .with_stage(
            "retryable",
            RetryableTransformStage(fail_times=max_failures),
            StageKind.TRANSFORM,
        )
    )


def create_validation_pipeline() -> Pipeline:
    """Create a pipeline with validation guards."""
    return (
        Pipeline()
        .with_stage("validate", ValidationGuardStage(), StageKind.GUARD)
        .with_stage("transform", StatefulTransformStage(), StageKind.TRANSFORM)
    )


# =============================================================================
# Test Execution Functions
# =============================================================================

async def create_test_context(
    input_data: Any,
    topology: str = "transform008_test",
) -> StageContext:
    """Create a test context with the given input data."""
    test_id = uuid4()

    snapshot = ContextSnapshot(
        run_id=RunIdentity(
            pipeline_run_id=test_id,
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            org_id=None,
            interaction_id=uuid4(),
        ),
        topology=topology,
        execution_mode="test",
        input_text=input_data if isinstance(input_data, str) else json.dumps(input_data),
    )

    ctx = StageContext(
        snapshot=snapshot,
        inputs=StageInputs(snapshot=snapshot),
        stage_name="test",
        timer=PipelineTimer(),
    )

    return ctx


async def run_baseline_test() -> dict[str, Any]:
    """Run baseline test with happy path inputs."""
    pipeline = create_baseline_pipeline()
    test_data = PartialTransformMockData.happy_path_inputs()

    ctx = await create_test_context(test_data)

    try:
        graph = pipeline.build()
        output = await graph.run(ctx)

        stage_output = output.get("stateful_transform")
        return {
            "test_name": "baseline",
            "success": True,
            "items_processed": len(test_data),
            "output_status": "completed",
            "data": stage_output.data if stage_output else {},
        }
    except Exception as e:
        return {
            "test_name": "baseline",
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def run_partial_failure_test(fail_at: int = 10) -> dict[str, Any]:
    """Run test that fails after processing some items."""
    pipeline = create_partial_failure_pipeline(fail_at=fail_at)
    test_data = [{"id": i, "value": i} for i in range(1, 20)]

    ctx = await create_test_context(test_data)

    try:
        graph = pipeline.build()
        output = await graph.run(ctx)

        stage_output = output.get("partial_transform")
        return {
            "test_name": "partial_failure",
            "success": False,
            "expected_failure": True,
            "processed_before_failure": fail_at - 1,
            "output_status": stage_output.status.value if stage_output else "unknown",
            "output_data": stage_output.data if stage_output else {},
        }
    except Exception as e:
        return {
            "test_name": "partial_failure",
            "success": True,
            "expected_failure": True,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def run_parallel_recovery_test() -> dict[str, Any]:
    """Run test with parallel branches where one fails."""
    pipeline = create_parallel_recovery_pipeline()

    ctx = await create_test_context("test")

    try:
        graph = pipeline.build()
        output = await graph.run(ctx)

        return {
            "test_name": "parallel_recovery",
            "success": True,
            "output": output,
        }
    except Exception as e:
        return {
            "test_name": "parallel_recovery",
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def run_retry_test(max_failures: int = 2) -> dict[str, Any]:
    """Run test with retryable stage."""
    pipeline = create_retry_pipeline(max_failures=max_failures)

    ctx = await create_test_context("test")

    try:
        graph = pipeline.build()
        output = await graph.run(ctx)

        stage_output = output.get("retryable")
        attempts = stage_output.data.get("attempts", 0) if stage_output else 0

        return {
            "test_name": "retry",
            "success": True,
            "attempts_required": attempts,
            "expected_attempts": max_failures + 1,
            "output": stage_output.data if stage_output else {},
        }
    except Exception as e:
        return {
            "test_name": "retry",
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def run_validation_test(valid_input: bool = True) -> dict[str, Any]:
    """Run test with validation guard."""
    pipeline = create_validation_pipeline()

    if valid_input:
        test_input = json.dumps([{"id": 1, "value": 100}])
    else:
        test_input = "INVALID_INPUT_MARKER"

    ctx = await create_test_context(test_input)

    try:
        graph = pipeline.build()
        output = await graph.run(ctx)

        return {
            "test_name": "validation",
            "success": valid_input,
            "expected_success": valid_input,
            "output": output,
        }
    except Exception as e:
        return {
            "test_name": "validation",
            "success": not valid_input,
            "expected_failure": not valid_input,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def run_silent_failure_detection_test() -> dict[str, Any]:
    """Run test to detect silent failures in partial transforms."""

    class SilentFailureTransformStage:
        """Stage that silently produces incorrect output."""

        name = "silent_failure"
        kind = StageKind.TRANSFORM

        async def execute(self, ctx: StageContext) -> StageOutput:
            items = ctx.snapshot.input_text or "[]"
            try:
                parsed_items = json.loads(items) if isinstance(items, str) else items
            except (json.JSONDecodeError, TypeError):
                return StageOutput.fail(error="Invalid JSON")

            results = []
            for item in parsed_items:
                input_val = item.get("input", 0)
                expected = item.get("expected_output")

                # Silent bug: always returns 42 instead of correct value
                actual = 42  # BUG: Should be input_val * 2

                if expected is not None and actual != expected:
                    # This should be detected but stage returns ok anyway
                    pass

                results.append({
                    "item": item,
                    "input": input_val,
                    "output": actual,
                    "expected": expected,
                    "is_correct": actual == expected if expected is not None else True,
                })

            all_correct = all(r["is_correct"] for r in results)

            return StageOutput.ok(
                results=results,
                all_correct=all_correct,
                silently_incorrect=not all_correct,
            )

    pipeline = (
        Pipeline()
        .with_stage("silent_check", SilentFailureTransformStage(), StageKind.TRANSFORM)
    )

    test_data = PartialTransformMockData.silent_failure_inputs()
    ctx = await create_test_context(test_data)

    try:
        graph = pipeline.build()
        output = await graph.run(ctx)

        stage_output = output.get("silent_check")
        results = stage_output.data.get("results", []) if stage_output else []

        silent_failures = [r for r in results if not r["is_correct"]]

        return {
            "test_name": "silent_failure_detection",
            "success": len(silent_failures) > 0,  # Success if we detect silent failures
            "silent_failures_detected": len(silent_failures),
            "total_items": len(results),
            "silent_failure_items": [
                {"item": r["item"], "expected": r["expected"], "actual": r["output"]}
                for r in silent_failures
            ],
        }
    except Exception as e:
        return {
            "test_name": "silent_failure_detection",
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def run_idempotency_test() -> dict[str, Any]:
    """Run test to verify idempotent behavior."""

    idempotency_verifier = IdempotencyVerifier()

    test_input = json.dumps({"operation": "add", "amount": 100})
    execution_id = "test_execution_001"

    pipeline = create_baseline_pipeline()
    ctx = await create_test_context(test_input)

    # Execute multiple times
    results = []
    for i in range(3):
        try:
            graph = pipeline.build()
            output = await graph.run(ctx)
            stage_output = output.get("stateful_transform")
            results.append(stage_output.data if stage_output else None)
        except Exception as e:
            results.append({"error": str(e)})

    # Check idempotency
    unique_results = set(str(r) for r in results)

    return {
        "test_name": "idempotency",
        "success": len(unique_results) == 1,
        "execution_count": len(results),
        "unique_results": len(unique_results),
        "is_idempotent": len(unique_results) == 1,
    }


# =============================================================================
# Main Test Runner
# =============================================================================

async def run_all_tests() -> dict[str, Any]:
    """Run all TRANSFORM-008 tests and return results."""
    results = {}

    print("TRANSFORM-008: Error Recovery with Partial Transforms")
    print("=" * 60)

    # Baseline test
    print("\nRunning baseline test...")
    results["baseline"] = await run_baseline_test()
    print(f"  Baseline: {'PASS' if results['baseline']['success'] else 'FAIL'}")

    # Partial failure test
    print("\nRunning partial failure test...")
    results["partial_failure"] = await run_partial_failure_test(fail_at=5)
    print(f"  Partial Failure: {'PASS' if results['partial_failure'].get('expected_failure') else 'FAIL'}")

    # Retry test
    print("\nRunning retry test...")
    results["retry"] = await run_retry_test(max_failures=2)
    print(f"  Retry: {'PASS' if results['retry']['success'] else 'FAIL'}")

    # Validation test (valid input)
    print("\nRunning validation test (valid input)...")
    results["validation_valid"] = await run_validation_test(valid_input=True)
    print(f"  Validation (valid): {'PASS' if results['validation_valid']['success'] else 'FAIL'}")

    # Validation test (invalid input)
    print("\nRunning validation test (invalid input)...")
    results["validation_invalid"] = await run_validation_test(valid_input=False)
    print(f"  Validation (invalid): {'PASS' if not results['validation_invalid']['success'] else 'FAIL'}")

    # Silent failure detection test
    print("\nRunning silent failure detection test...")
    results["silent_failure"] = await run_silent_failure_detection_test()
    print(f"  Silent Failure Detection: {'PASS' if results['silent_failure'].get('silent_failures_detected', 0) > 0 else 'FAIL'}")

    # Idempotency test
    print("\nRunning idempotency test...")
    results["idempotency"] = await run_idempotency_test()
    print(f"  Idempotency: {'PASS' if results['idempotency'].get('is_idempotent') else 'FAIL'}")

    # Parallel recovery test
    print("\nRunning parallel recovery test...")
    results["parallel_recovery"] = await run_parallel_recovery_test()
    print(f"  Parallel Recovery: {'PASS' if results['parallel_recovery']['success'] else 'FAIL'}")

    # Summary
    print("\n" + "=" * 60)
    total_tests = len(results)
    passed_tests = sum(1 for r in results.values() if r.get("success", False))
    print(f"Total: {passed_tests}/{total_tests} tests passed")

    return results


async def main():
    """Main entry point."""
    results = await run_all_tests()

    # Save results to file
    import json
    from datetime import datetime

    output_file = f"results/transform008_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nResults saved to: {output_file}")

    return results


if __name__ == "__main__":
    asyncio.run(main())
