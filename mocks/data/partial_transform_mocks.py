"""TRANSFORM-008: Error recovery with partial transforms mock data generators.

This module contains mock data and generators for testing:
- Partial transform scenarios
- Error recovery patterns
- Idempotency verification
- Silent failure detection
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PartialTransformMockData:
    """Mock data for partial transform error recovery testing."""

    @staticmethod
    def happy_path_inputs() -> list[dict[str, Any]]:
        """Normal inputs that should process successfully."""
        return [
            {"id": i, "text": f"Record {i}", "value": random.randint(1, 1000)}
            for i in range(1, 101)
        ]

    @staticmethod
    def partial_failure_inputs() -> list[dict[str, Any]]:
        """Inputs where processing fails partway through.

        The last item (id=999) will cause a failure, simulating
        a pipeline that processes 998 items successfully then fails.
        """
        items = [{"id": i, "text": f"Record {i}", "value": random.randint(1, 1000)}
                 for i in range(1, 999)]
        items.append({"id": 999, "text": "FAILURE_TRIGGER", "value": -1})
        random.shuffle(items)
        return items

    @staticmethod
    def idempotency_test_inputs() -> list[dict[str, Any]]:
        """Inputs designed to test idempotent operations.

        Same inputs should produce same outputs regardless of retry count.
        """
        base_items = [
            {"id": 1, "operation": "add", "amount": 100},
            {"id": 2, "operation": "multiply", "factor": 2},
            {"id": 3, "operation": "add", "amount": 50},
        ]
        return base_items * 5  # Repeat to test idempotency

    @staticmethod
    def silent_failure_inputs() -> list[dict[str, Any]]:
        """Inputs designed to test silent failure detection.

        Some inputs may succeed technically but produce incorrect results.
        """
        return [
            {"id": 1, "input": 10, "expected_output": 20},
            {"id": 2, "input": 20, "expected_output": 40},
            {"id": 3, "input": "invalid_type", "expected_output": "ERROR"},  # Will cause silent failure
            {"id": 4, "input": 30, "expected_output": 60},
            {"id": 5, "input": 40, "expected_output": 80},
        ]

    @staticmethod
    def large_partial_dataset() -> list[dict[str, Any]]:
        """Large dataset for performance testing with partial failure."""
        items = [{"id": i, "data": "x" * 1000, "timestamp": time.time()}
                 for i in range(1, 10001)]
        items[5000]["data"] = "TRIGGER_FAILURE"  # Fail at 50%
        return items

    @staticmethod
    def parallel_branch_inputs() -> dict[str, list[dict[str, Any]]]:
        """Inputs for parallel branch testing with partial failure.

        Each branch gets different data - one branch will fail.
        """
        return {
            "branch_a": [{"id": i, "type": "A"} for i in range(1, 51)],
            "branch_b": [{"id": i, "type": "B"} for i in range(51, 101)],
            "branch_c": [{"id": i, "type": "C", "trigger_failure": True} for i in range(101, 151)],
        }


@dataclass
class RecoveryScenario:
    """Represents a recovery scenario for testing."""

    name: str
    description: str
    inputs: list[dict[str, Any]]
    expected_failures: int
    expected_successes: int
    should_preserve_partial: bool


@dataclass
class TransformTestCase:
    """A single test case for transform testing."""

    name: str
    input_data: Any
    expected_output: Any
    should_fail: bool
    failure_reason: str | None = None


class ErrorInjectionSimulator:
    """Simulates various error conditions for testing."""

    def __init__(self, failure_rate: float = 0.1, failure_mode: str = "random"):
        self.failure_rate = failure_rate
        self.failure_mode = failure_mode
        self.failure_count = 0
        self.processed_count = 0

    def should_fail(self) -> bool:
        """Determine if current operation should fail."""
        self.processed_count += 1
        if self.failure_mode == "random":
            should_fail = random.random() < self.failure_rate
        elif self.failure_mode == "nth":
            should_fail = self.processed_count % int(1 / self.failure_rate) == 0
        elif self.failure_mode == "specific":
            should_fail = self.processed_count == self._get_failure_index()
        else:
            should_fail = False

        if should_fail:
            self.failure_count += 1
        return should_fail

    def _get_failure_index(self) -> int:
        """Get the index at which failure should occur."""
        return int(self.processed_count * self.failure_rate)

    def reset(self):
        """Reset the simulator state."""
        self.failure_count = 0
        self.processed_count = 0


class CheckpointSimulator:
    """Simulates checkpoint-based recovery for testing."""

    def __init__(self, checkpoint_interval: int = 10):
        self.checkpoint_interval = checkpoint_interval
        self.state: dict[str, Any] = {}
        self.checkpoints: list[dict[str, Any]] = []
        self.current_index = 0

    def save_checkpoint(self, state: dict[str, Any], index: int):
        """Save a checkpoint with the current state."""
        checkpoint = {
            "index": index,
            "state": state.copy(),
            "timestamp": time.time(),
        }
        self.checkpoints.append(checkpoint)
        return checkpoint

    def get_last_checkpoint(self) -> dict[str, Any] | None:
        """Get the last saved checkpoint."""
        return self.checkpoints[-1] if self.checkpoints else None

    def restore_from_checkpoint(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        """Restore state from a checkpoint."""
        self.current_index = checkpoint["index"]
        self.state = checkpoint["state"].copy()
        return self.state

    def process_with_checkpoints(
        self,
        items: list[Any],
        process_func: callable,
    ) -> tuple[list[Any], dict[str, Any]]:
        """Process items with periodic checkpointing."""
        results = []
        state = {"processed_count": 0, "failed_count": 0}

        for i, item in enumerate(items):
            if i > 0 and i % self.checkpoint_interval == 0:
                self.save_checkpoint(state, i)

            try:
                result = process_func(item)
                results.append(result)
                state["processed_count"] += 1
            except Exception as e:
                state["failed_count"] += 1
                results.append({"error": str(e), "item": item})

        return results, state


class IdempotencyVerifier:
    """Verifies idempotent operation behavior."""

    def __init__(self):
        self.execution_history: list[dict[str, Any]] = []

    async def execute_idempotent(
        self,
        operation: callable,
        input_data: Any,
        execution_id: str,
    ) -> dict[str, Any]:
        """Execute an operation and track its results for idempotency."""
        execution_record = {
            "execution_id": execution_id,
            "input": input_data,
            "result": None,
            "timestamp": time.time(),
        }

        result = await operation(input_data)
        execution_record["result"] = result
        self.execution_history.append(execution_record)

        return result

    def verify_idempotency(self, operation_id: str) -> dict[str, Any]:
        """Verify that multiple executions of the same operation produce same results."""
        relevant_executions = [
            e for e in self.execution_history
            if e["execution_id"] == operation_id
        ]

        if len(relevant_executions) < 2:
            return {
                "is_idempotent": True,
                "message": "Only one execution, cannot verify idempotency",
                "execution_count": len(relevant_executions),
            }

        results = [e["result"] for e in relevant_executions]
        first_result = results[0]

        all_same = all(r == first_result for r in results)

        return {
            "is_idempotent": all_same,
            "execution_count": len(relevant_executions),
            "unique_results": len(set(str(r) for r in results)),
            "message": "Idempotent" if all_same else "NOT IDEMPOTENT - Results differ!",
        }


class PartialResultTracker:
    """Tracks partial results during failed pipeline execution."""

    def __init__(self):
        self.completed_items: list[dict[str, Any]] = []
        self.failed_item: dict[str, Any] | None = None
        self.state_at_failure: dict[str, Any] = {}

    def add_completed(self, item: dict[str, Any], result: dict[str, Any]):
        """Record a successfully processed item."""
        self.completed_items.append({
            "item": item,
            "result": result,
            "timestamp": time.time(),
        })

    def record_failure(self, item: dict[str, Any], error: str, state: dict[str, Any]):
        """Record the failure point."""
        self.failed_item = {
            "item": item,
            "error": error,
            "timestamp": time.time(),
        }
        self.state_at_failure = state.copy()

    def get_partial_result(self) -> dict[str, Any]:
        """Get the partial result for recovery."""
        return {
            "completed_count": len(self.completed_items),
            "completed_items": [c["item"] for c in self.completed_items],
            "failed_item": self.failed_item,
            "state_at_failure": self.state_at_failure,
            "recovery_point": len(self.completed_items),
        }


async def simulate_partial_transform(
    items: list[dict[str, Any]],
    transform_func: callable,
    failure_point: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Simulate a transform operation that may fail partway through.

    Args:
        items: Items to transform
        transform_func: Function to apply to each item
        failure_point: Index at which to fail (None for no failure)

    Returns:
        Tuple of (final_state, results)
    """
    tracker = PartialResultTracker()
    results = []
    state = {"processed": 0, "failed": 0}

    for i, item in enumerate(items):
        if i == failure_point:
            tracker.record_failure(item, "Simulated failure at failure_point", state)
            raise RuntimeError(f"Simulated failure at index {i}")

        try:
            result = await transform_func(item)
            results.append(result)
            tracker.add_completed(item, result)
            state["processed"] += 1
        except Exception as e:
            tracker.record_failure(item, str(e), state)
            state["failed"] += 1
            raise

    return state, results


# Export all classes and functions
__all__ = [
    "PartialTransformMockData",
    "RecoveryScenario",
    "TransformTestCase",
    "ErrorInjectionSimulator",
    "CheckpointSimulator",
    "IdempotencyVerifier",
    "PartialResultTracker",
    "simulate_partial_transform",
]
