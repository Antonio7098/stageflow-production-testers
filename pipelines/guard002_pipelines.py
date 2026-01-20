"""
GUARD-002 Test Pipelines: Jailbreak Detection and Blocking

This module contains test pipelines for stress-testing jailbreak detection
in Stageflow's GUARD stage architecture.

Pipelines:
1. Baseline Pipeline - Normal operation with benign inputs
2. Adversarial Pipeline - Direct jailbreak attack testing
3. Chaos Pipeline - Failure injection and edge cases
4. Stress Pipeline - Performance and scalability testing
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from stageflow import Pipeline, StageContext, StageKind, StageOutput, StageInputs, PipelineTimer
from stageflow.context import ContextSnapshot, RunIdentity

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from mocks.services.jailbreak_detection_mocks import (
    JailbreakDetectionService,
    JailbreakDetectorConfig,
    JailbreakTestDataGenerator,
    JailbreakCategory,
    DetectionResult,
)


@dataclass
class TestResult:
    """Result of a single test case."""
    test_id: str
    category: str
    prompt: str
    expected_result: str
    actual_result: str
    detected: bool
    detection_time_ms: float
    passed: bool
    error: Optional[str] = None


@dataclass
class PipelineTestResult:
    """Aggregated results for a test pipeline."""
    pipeline_name: str
    total_tests: int
    passed: int
    failed: int
    detection_rate: float
    false_positive_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    silent_failures: list[str]
    test_results: list[TestResult]
    timestamp: str


class JailbreakGuardStage:
    """GUARD stage that performs jailbreak detection."""

    name = "jailbreak_guard"
    kind = StageKind.GUARD

    def __init__(
        self,
        detector: Optional[JailbreakDetectionService] = None,
        config: Optional[JailbreakDetectorConfig] = None,
    ):
        self._detector = detector or JailbreakDetectionService(config)
        self._stats = {
            "checks": 0,
            "blocked": 0,
            "flagged": 0,
            "passed": 0,
            "errors": 0,
        }

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute jailbreak detection on input."""
        self._stats["checks"] += 1

        input_text = ctx.snapshot.input_text or ""
        conversation_history = []

        # Check for conversation history in extensions
        if ctx.snapshot.extensions:
            conversation_history = ctx.snapshot.extensions.get("conversation_history", [])

        try:
            result = await self._detector.detect(
                content=input_text,
                context={"user_id": str(ctx.snapshot.user_id)},
                conversation_history=conversation_history,
            )

            if result.result == DetectionResult.BLOCKED:
                self._stats["blocked"] += 1
                return StageOutput.cancel(
                    reason=f"Jailbreak detected: {result.reason}",
                    data={
                        "blocked": True,
                        "category": result.category.value,
                        "confidence": result.confidence,
                        "attack_pattern": result.attack_pattern,
                        "detection_time_ms": result.processing_time_ms,
                    },
                )
            elif result.result == DetectionResult.FLAGGED:
                self._stats["flagged"] += 1
                return StageOutput.ok(
                    flagged=True,
                    category=result.category.value,
                    confidence=result.confidence,
                    reason=result.reason,
                    detection_time_ms=result.processing_time_ms,
                )
            else:
                self._stats["passed"] += 1
                return StageOutput.ok(
                    passed=True,
                    detection_time_ms=result.processing_time_ms,
                )

        except Exception as e:
            self._stats["errors"] += 1
            return StageOutput.fail(
                error=f"Jailbreak detection failed: {e}",
                data={"error_type": type(e).__name__},
            )

    def get_stats(self) -> dict:
        """Get stage statistics."""
        return self._stats


class JailbreakOutputGuardStage:
    """Output guard stage for detecting jailbreak-generated harmful content."""

    name = "output_guard"
    kind = StageKind.GUARD

    def __init__(
        self,
        detector: Optional[JailbreakDetectionService] = None,
        config: Optional[JailbreakDetectorConfig] = None,
    ):
        self._detector = detector or JailbreakDetectionService(config)
        self._stats = {"checks": 0, "blocked": 0, "passed": 0}

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Check output for jailbreak-generated harmful content."""
        self._stats["checks"] += 1

        # Get response from upstream stage
        response = ctx.inputs.get("response")
        if not response:
            return StageOutput.ok(passed=True, reason="No response to check")

        try:
            result = await self._detector.detect(
                content=response,
                context={"stage": "output_guard"},
            )

            if result.result == DetectionResult.BLOCKED:
                self._stats["blocked"] += 1
                return StageOutput.cancel(
                    reason=f"Output rejected: {result.reason}",
                    data={
                        "blocked": True,
                        "category": result.category.value,
                    },
                )

            self._stats["passed"] += 1
            return StageOutput.ok(passed=True)

        except Exception as e:
            return StageOutput.fail(error=f"Output guard failed: {e}")

    def get_stats(self) -> dict:
        return self._stats


class MockLLMStage:
    """Mock LLM stage for testing without actual API calls."""

    name = "mock_llm"
    kind = StageKind.TRANSFORM

    def __init__(self, response_template: str = "I can help you with that."):
        self._response_template = response_template
        self._call_count = 0

    async def execute(self, ctx: StageContext) -> StageOutput:
        self._call_count += 1
        input_text = ctx.snapshot.input_text or ""

        # Generate response based on input
        if "hello" in input_text.lower():
            response = "Hello! How can I assist you today?"
        elif "?" in input_text:
            response = "That's a great question. Let me help you with that."
        else:
            response = self._response_template

        return StageOutput.ok(
            response=response,
            model="mock-llm",
            input_tokens=len(input_text),
            output_tokens=len(response),
        )

    def get_stats(self) -> dict:
        return {"calls": self._call_count}


def create_baseline_pipeline() -> Pipeline:
    """Create baseline pipeline for normal operation testing."""
    guard_stage = JailbreakGuardStage()
    llm_stage = MockLLMStage()
    output_guard = JailbreakOutputGuardStage()

    return (
        Pipeline()
        .with_stage("input_guard", guard_stage, StageKind.GUARD)
        .with_stage("llm", llm_stage, StageKind.TRANSFORM, dependencies=("input_guard",))
        .with_stage("output_guard", output_guard, StageKind.GUARD, dependencies=("llm",))
    )


def create_adversarial_pipeline() -> Pipeline:
    """Create pipeline for adversarial jailbreak testing."""
    # Configure detector with varied detection rates
    config = JailbreakDetectorConfig(
        detection_rates={
            "optimization": 0.85,
            "llm_assisted": 0.70,
            "obfuscation": 0.60,
            "function_tool": 0.50,
            "multi_turn": 0.40,
            "direct_injection": 0.95,
            "indirect_injection": 0.80,
            "benign": 0.02,
        },
        block_on_detection=True,
    )

    guard_stage = JailbreakGuardStage(config=config)
    llm_stage = MockLLMStage()
    output_guard = JailbreakOutputGuardStage(config=config)

    return (
        Pipeline()
        .with_stage("input_guard", guard_stage, StageKind.GUARD)
        .with_stage("llm", llm_stage, StageKind.TRANSFORM, dependencies=("input_guard",))
        .with_stage("output_guard", output_guard, StageKind.GUARD, dependencies=("llm",))
    )


def create_chaos_pipeline() -> Pipeline:
    """Create pipeline for chaos testing (failure injection)."""
    # Configure detector with low detection rates for chaos
    config = JailbreakDetectorConfig(
        detection_rates={
            "optimization": 0.30,
            "llm_assisted": 0.20,
            "obfuscation": 0.15,
            "function_tool": 0.10,
            "multi_turn": 0.05,
            "direct_injection": 0.50,
            "indirect_injection": 0.30,
            "benign": 0.10,  # Higher false positive rate
        },
        block_on_detection=True,
    )

    guard_stage = JailbreakGuardStage(config=config)
    llm_stage = MockLLMStage()
    output_guard = JailbreakOutputGuardStage(config=config)

    return (
        Pipeline()
        .with_stage("input_guard", guard_stage, StageKind.GUARD)
        .with_stage("llm", llm_stage, StageKind.TRANSFORM, dependencies=("input_guard",))
        .with_stage("output_guard", output_guard, StageKind.GUARD, dependencies=("llm",))
    )


async def run_test_case(
    pipeline: Pipeline,
    prompt: str,
    expected_blocked: bool,
    test_id: str,
) -> TestResult:
    """Run a single test case."""
    start_time = time.perf_counter()

    try:
        # Build the graph from pipeline
        graph = pipeline.build()

        snapshot = ContextSnapshot(
            run_id=RunIdentity(
                pipeline_run_id=uuid.uuid4(),
                request_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
            ),
            input_text=prompt,
        )

        # Create StageContext with required parameters
        ctx = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name="pipeline_entry",
            timer=PipelineTimer(),
        )

        outputs = await graph.run(ctx)

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Check if input guard cancelled the pipeline
        input_guard_output = outputs.get("input_guard")
        if input_guard_output:
            if input_guard_output.status.value == "cancelled":
                return TestResult(
                    test_id=test_id,
                    category="test",
                    prompt=prompt[:100],
                    expected_result="blocked" if expected_blocked else "passed",
                    actual_result="blocked",
                    detected=True,
                    detection_time_ms=elapsed_ms,
                    passed=expected_blocked,
                )
            elif input_guard_output.status.value == "failed":
                return TestResult(
                    test_id=test_id,
                    category="test",
                    prompt=prompt[:100],
                    expected_result="blocked" if expected_blocked else "passed",
                    actual_result="error",
                    detected=False,
                    detection_time_ms=elapsed_ms,
                    passed=False,
                    error=input_guard_output.data.get("error", "Unknown error"),
                )

        # Check if output guard blocked
        output_guard_output = outputs.get("output_guard")
        if output_guard_output and output_guard_output.data.get("blocked"):
            return TestResult(
                test_id=test_id,
                category="test",
                prompt=prompt[:100],
                expected_result="blocked" if expected_blocked else "passed",
                actual_result="blocked",
                detected=True,
                detection_time_ms=elapsed_ms,
                passed=expected_blocked,
            )

        # Pipeline passed (no blocking)
        return TestResult(
            test_id=test_id,
            category="test",
            prompt=prompt[:100],
            expected_result="blocked" if expected_blocked else "passed",
            actual_result="passed",
            detected=False,
            detection_time_ms=elapsed_ms,
            passed=not expected_blocked,  # Passed if we expected it to pass
        )

    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return TestResult(
            test_id=test_id,
            category="test",
            prompt=prompt[:100],
            expected_result="blocked" if expected_blocked else "passed",
            actual_result="error",
            detected=False,
            detection_time_ms=elapsed_ms,
            passed=False,
            error=str(e),
        )


async def run_baseline_tests(
    num_tests: int = 50,
) -> PipelineTestResult:
    """Run baseline tests with benign inputs."""
    pipeline = create_baseline_pipeline()
    generator = JailbreakTestDataGenerator(seed=42)

    benign_prompts = generator.generate_benign_prompts(num_tests)

    results: list[TestResult] = []
    silent_failures: list[str] = []

    for i, prompt in enumerate(benign_prompts):
        result = await run_test_case(
            pipeline, prompt, expected_blocked=False, test_id=f"benign_{i}"
        )
        results.append(result)

        if not result.passed and result.actual_result == "blocked":
            # False positive - benign content blocked
            silent_failures.append(
                f"False positive: benign content incorrectly blocked - {prompt[:50]}..."
            )

    # Calculate metrics
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    false_positives = sum(
        1 for r in results if r.actual_result == "blocked" and not r.expected_result
    )
    latencies = [r.detection_time_ms for r in results]
    latencies.sort()

    return PipelineTestResult(
        pipeline_name="baseline",
        total_tests=len(results),
        passed=passed,
        failed=failed,
        detection_rate=0.0,  # No malicious inputs in baseline
        false_positive_rate=false_positives / len(results) if results else 0,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
        p95_latency_ms=latencies[int(len(latencies) * 0.95)] if latencies else 0,
        silent_failures=silent_failures,
        test_results=results,
        timestamp=datetime.now().isoformat(),
    )


async def run_adversarial_tests(
    attacks_per_category: int = 10,
) -> PipelineTestResult:
    """Run adversarial tests with jailbreak attacks."""
    pipeline = create_adversarial_pipeline()
    generator = JailbreakTestDataGenerator(seed=42)

    # Generate test dataset
    dataset = generator.generate_test_dataset(
        attacks_per_category=attacks_per_category,
        benign_count=20,
    )

    results: list[TestResult] = []
    silent_failures: list[str] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(
            pipeline,
            item["prompt"],
            expected_blocked=item["expected_malicious"],
            test_id=f"adversarial_{i}",
        )
        result.category = item["category"]
        results.append(result)

        # Check for silent failures
        if not result.passed:
            if result.expected_result == "blocked" and result.actual_result == "passed":
                # Silent failure: jailbreak not detected
                silent_failures.append(
                    f"Silent failure: jailbreak not detected - {item['category']} - {result.prompt[:50]}..."
                )

    # Calculate metrics
    malicious_results = [r for r in results if r.category != "benign"]
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    detected = sum(
        1
        for r in results
        if r.category != "benign" and r.actual_result == "blocked"
    )
    total_malicious = len(malicious_results) if malicious_results else 1
    detection_rate = detected / total_malicious

    false_positives = sum(
        1 for r in results if r.actual_result == "blocked" and r.category == "benign"
    )
    benign_count = sum(1 for r in results if r.category == "benign")
    false_positive_rate = (
        false_positives / benign_count if benign_count > 0 else 0
    )

    latencies = [r.detection_time_ms for r in results]
    latencies.sort()

    return PipelineTestResult(
        pipeline_name="adversarial",
        total_tests=len(results),
        passed=passed,
        failed=failed,
        detection_rate=detection_rate,
        false_positive_rate=false_positive_rate,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
        p95_latency_ms=latencies[int(len(latencies) * 0.95)] if latencies else 0,
        silent_failures=silent_failures,
        test_results=results,
        timestamp=datetime.now().isoformat(),
    )


async def run_chaos_tests(
    num_tests: int = 50,
) -> PipelineTestResult:
    """Run chaos tests with failure injection."""
    pipeline = create_chaos_pipeline()
    generator = JailbreakTestDataGenerator(seed=42)

    # Mix of attacks and benign content
    dataset = generator.generate_test_dataset(
        attacks_per_category=5,
        benign_count=25,
    )

    results: list[TestResult] = []
    silent_failures: list[str] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(
            pipeline,
            item["prompt"],
            expected_blocked=item["expected_malicious"],
            test_id=f"chaos_{i}",
        )
        result.category = item["category"]
        results.append(result)

        if not result.passed:
            if result.expected_result == "blocked" and result.actual_result == "passed":
                silent_failures.append(
                    f"Silent failure (chaos): undetected attack - {item['category']}"
                )

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    malicious_results = [r for r in results if r.category != "benign"]
    detected = sum(
        1
        for r in results
        if r.category != "benign" and r.actual_result == "blocked"
    )
    total_malicious = len(malicious_results) if malicious_results else 1
    detection_rate = detected / total_malicious

    latencies = [r.detection_time_ms for r in results]
    latencies.sort()

    return PipelineTestResult(
        pipeline_name="chaos",
        total_tests=len(results),
        passed=passed,
        failed=failed,
        detection_rate=detection_rate,
        false_positive_rate=0.0,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
        p95_latency_ms=latencies[int(len(latencies) * 0.95)] if latencies else 0,
        silent_failures=silent_failures,
        test_results=results,
        timestamp=datetime.now().isoformat(),
    )


async def run_stress_test(
    concurrent_requests: int = 100,
    duration_seconds: int = 10,
) -> dict:
    """Run stress test with concurrent requests."""
    import concurrent.futures

    pipeline = create_baseline_pipeline()
    generator = JailbreakTestDataGenerator(seed=42)
    prompts = generator.generate_benign_prompts(100)

    results: list[TestResult] = []
    start_time = time.time()
    request_count = 0

    async def run_single_request(prompt: str, idx: int) -> TestResult:
        nonlocal request_count
        request_count += 1
        return await run_test_case(
            pipeline, prompt, expected_blocked=False, test_id=f"stress_{idx}"
        )

    tasks = []
    idx = 0
    while time.time() - start_time < duration_seconds:
        for prompt in prompts:
            if time.time() - start_time >= duration_seconds:
                break
            idx += 1
            tasks.append(run_single_request(prompt, idx))

        if tasks:
            # Run batch concurrently
            batch = tasks[:concurrent_requests]
            tasks = tasks[concurrent_requests:]

            results.extend(await asyncio.gather(*batch))

    passed = sum(1 for r in results if r.passed)
    latencies = [r.detection_time_ms for r in results if r.detection_time_ms > 0]
    latencies.sort()

    return {
        "pipeline_name": "stress",
        "total_requests": request_count,
        "duration_seconds": duration_seconds,
        "requests_per_second": request_count / duration_seconds,
        "passed": passed,
        "failed": len(results) - passed,
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
        "p95_latency_ms": latencies[int(len(latencies) * 0.95)] if latencies else 0,
        "p99_latency_ms": latencies[int(len(latencies) * 0.99)] if latencies else 0,
        "max_latency_ms": max(latencies) if latencies else 0,
        "timestamp": datetime.now().isoformat(),
    }


async def run_all_tests() -> dict:
    """Run all test pipelines and return comprehensive results."""
    print("Running GUARD-002 Jailbreak Detection Tests...")
    print("=" * 60)

    results = {
        "baseline": await run_baseline_tests(50),
        "adversarial": await run_adversarial_tests(10),
        "chaos": await run_chaos_tests(50),
    }

    print(f"Baseline Tests: {results['baseline'].passed}/{results['baseline'].total_tests} passed")
    print(f"  - False Positive Rate: {results['baseline'].false_positive_rate:.2%}")
    print(f"  - Avg Latency: {results['baseline'].avg_latency_ms:.2f}ms")

    print(f"\nAdversarial Tests: {results['adversarial'].passed}/{results['adversarial'].total_tests} passed")
    print(f"  - Detection Rate: {results['adversarial'].detection_rate:.2%}")
    print(f"  - False Positive Rate: {results['adversarial'].false_positive_rate:.2%}")
    print(f"  - Silent Failures: {len(results['adversarial'].silent_failures)}")

    print(f"\nChaos Tests: {results['chaos'].passed}/{results['chaos'].total_tests} passed")
    print(f"  - Detection Rate: {results['chaos'].detection_rate:.2%}")
    print(f"  - Silent Failures: {len(results['chaos'].silent_failures)}")

    return results


if __name__ == "__main__":
    asyncio.run(run_all_tests())
