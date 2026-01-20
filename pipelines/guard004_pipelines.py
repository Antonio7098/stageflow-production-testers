"""
GUARD-004 Test Pipelines: Policy Enforcement Bypass Attempts

This module contains test pipelines for stress-testing Stageflow's GUARD stage
architecture against policy enforcement bypass attacks.

Target: <5% bypass rate for all attack categories

Pipelines:
1. Baseline Pipeline - Normal operation with standard attacks
2. Direct Injection Pipeline - Classic jailbreak prompts
3. Character Injection Pipeline - Unicode, emoji, invisible characters
4. Automated Pipeline - Best-of-N style variations
5. Multi-turn Pipeline - Conversational erosion attacks
6. Chaos Pipeline - High bypass rates for failure testing
7. Output Guard Pipeline - Testing LLM-generated injection
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

from mocks.services.policy_bypass_mocks import (
    PolicyBypassService,
    PolicyBypassConfig,
    PolicyBypassTestDataGenerator,
    PolicyEnforcementStage,
    MockLLMWithInjectionStage,
    AttackCategory,
    AttackPayload,
    AttackResult,
    create_high_security_config,
    create_low_security_config,
)


@dataclass
class BypassTestResult:
    """Result of a single bypass test case."""
    test_id: str
    category: str
    attack_type: str
    text: str
    expected_blocked: bool
    actual_blocked: bool
    bypass_occurred: bool
    detection_confidence: float
    bypass_rate_at_time: float
    processing_time_ms: float
    passed: bool
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class PipelineTestResult:
    """Aggregated results for a test pipeline."""
    pipeline_name: str
    total_tests: int
    passed: int
    failed: int
    bypass_rate: float
    detection_rate: float
    false_positive_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    silent_failures: list[str]
    bypassed_cases: list[dict]
    test_results: list[BypassTestResult]
    timestamp: str


def create_baseline_pipeline(bypass_rate: float = 0.15) -> Pipeline:
    """Create baseline pipeline with moderate security."""
    config = PolicyBypassConfig(direct_injection_bypass_rate=bypass_rate)
    service = PolicyBypassService(config)

    return (
        Pipeline()
        .with_stage("input_guard", PolicyEnforcementStage(service), StageKind.GUARD)
    )


def create_direct_injection_pipeline(bypass_rate: float = 0.15) -> Pipeline:
    """Create pipeline for direct prompt injection testing."""
    config = PolicyBypassConfig(direct_injection_bypass_rate=bypass_rate)
    service = PolicyBypassService(config)

    return (
        Pipeline()
        .with_stage("input_guard", PolicyEnforcementStage(service), StageKind.GUARD)
    )


def create_indirect_injection_pipeline(bypass_rate: float = 0.25) -> Pipeline:
    """Create pipeline for indirect injection (context manipulation) testing."""
    config = PolicyBypassConfig(indirect_injection_bypass_rate=bypass_rate)
    service = PolicyBypassService(config)

    return (
        Pipeline()
        .with_stage("context_check", PolicyEnforcementStage(service), StageKind.GUARD)
        .with_stage("input_guard", PolicyEnforcementStage(service), StageKind.GUARD)
    )


def create_character_injection_pipeline(bypass_rate: float = 0.35) -> Pipeline:
    """Create pipeline for character injection (Unicode, emoji) testing."""
    config = PolicyBypassConfig(
        character_injection_bypass_rate=bypass_rate,
        enable_unicode_vulnerability=True,
        enable_emoji_vulnerability=True,
    )
    service = PolicyBypassService(config)

    return (
        Pipeline()
        .with_stage("char_guard", PolicyEnforcementStage(service), StageKind.GUARD)
    )


def create_automated_pipeline(bypass_rate: float = 0.40) -> Pipeline:
    """Create pipeline for Best-of-N automated variation testing."""
    config = PolicyBypassConfig(automated_variation_bypass_rate=bypass_rate)
    service = PolicyBypassService(config)

    return (
        Pipeline()
        .with_stage("automated_guard", PolicyEnforcementStage(service), StageKind.GUARD)
    )


def create_multi_turn_pipeline(bypass_rate: float = 0.30) -> Pipeline:
    """Create pipeline for multi-turn conversational attack testing."""
    config = PolicyBypassConfig(
        multi_turn_bypass_rate=bypass_rate,
        enable_multi_turn_erosion=True,
    )
    service = PolicyBypassService(config)

    return (
        Pipeline()
        .with_stage("turn_guard", PolicyEnforcementStage(service), StageKind.GUARD)
    )


def create_evaluation_misuse_pipeline(bypass_rate: float = 0.45) -> Pipeline:
    """Create pipeline for evaluation misuse (Bad Likert Judge) testing."""
    config = PolicyBypassConfig(evaluation_misuse_bypass_rate=bypass_rate)
    service = PolicyBypassService(config)

    return (
        Pipeline()
        .with_stage("eval_guard", PolicyEnforcementStage(service), StageKind.GUARD)
    )


def create_output_guard_pipeline(
    input_bypass_rate: float = 0.15,
    injection_rate: float = 0.30,
) -> Pipeline:
    """Create pipeline for testing output guard effectiveness."""
    input_config = PolicyBypassConfig(direct_injection_bypass_rate=input_bypass_rate)
    input_service = PolicyBypassService(input_config)

    return (
        Pipeline()
        .with_stage("input_guard", PolicyEnforcementStage(input_service), StageKind.GUARD)
        .with_stage("llm", MockLLMWithInjectionStage(inject_in_output=True, injection_rate=injection_rate), StageKind.TRANSFORM, dependencies=("input_guard",))
        .with_stage("output_guard", PolicyEnforcementStage(input_service), StageKind.GUARD, dependencies=("llm",))
    )


def create_chaos_pipeline(bypass_rate: float = 0.60) -> Pipeline:
    """Create pipeline for chaos testing with very high bypass rates."""
    config = PolicyBypassConfig(
        direct_injection_bypass_rate=bypass_rate,
        indirect_injection_bypass_rate=bypass_rate + 0.1,
        character_injection_bypass_rate=bypass_rate + 0.15,
        automated_variation_bypass_rate=bypass_rate + 0.2,
        multi_turn_bypass_rate=bypass_rate + 0.1,
        evaluation_misuse_bypass_rate=bypass_rate + 0.15,
        system_prompt_leak_rate=bypass_rate,
    )
    service = PolicyBypassService(config)

    return (
        Pipeline()
        .with_stage("input_guard", PolicyEnforcementStage(service), StageKind.GUARD)
        .with_stage("output_guard", PolicyEnforcementStage(service), StageKind.GUARD)
    )


async def run_test_case(
    pipeline: Pipeline,
    test_data: AttackPayload,
    test_id: str,
) -> BypassTestResult:
    """Run a single bypass test case."""
    start_time = time.perf_counter()

    try:
        graph = pipeline.build()

        snapshot = ContextSnapshot(
            run_id=RunIdentity(
                pipeline_run_id=uuid.uuid4(),
                request_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
            ),
            input_text=test_data.original_text,
        )

        ctx = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name="pipeline_entry",
            timer=PipelineTimer(),
        )

        outputs = await graph.run(ctx)

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Get the first stage output
        stage_name = list(outputs.keys())[0]
        stage_output = outputs.get(stage_name)

        if stage_output:
            # Handle status safely
            try:
                status_value = stage_output.status.value if hasattr(stage_output.status, 'value') else str(stage_output.status)
            except (AttributeError, TypeError):
                status_value = "unknown"

            if status_value == "failed":
                # Attack was blocked
                return BypassTestResult(
                    test_id=test_id,
                    category=test_data.category.value,
                    attack_type=test_data.attack_type,
                    text=test_data.original_text[:100],
                    expected_blocked=test_data.expected_blocked,
                    actual_blocked=True,
                    bypass_occurred=False,
                    detection_confidence=1.0,
                    bypass_rate_at_time=0.0,
                    processing_time_ms=elapsed_ms,
                    passed=test_data.expected_blocked,
                    metadata=test_data.metadata,
                )
            else:
                # Attack may have bypassed
                bypass_occurred = stage_output.data.get("bypass_occurred", False)
                detection_confidence = stage_output.data.get("confidence", 0.0)

                return BypassTestResult(
                    test_id=test_id,
                    category=test_data.category.value,
                    attack_type=test_data.attack_type,
                    text=test_data.original_text[:100],
                    expected_blocked=test_data.expected_blocked,
                    actual_blocked=not bypass_occurred,
                    bypass_occurred=bypass_occurred,
                    detection_confidence=detection_confidence,
                    bypass_rate_at_time=detection_confidence,
                    processing_time_ms=elapsed_ms,
                    passed=(test_data.expected_blocked and not bypass_occurred) or (not test_data.expected_blocked and bypass_occurred),
                    metadata=test_data.metadata,
                )

        return BypassTestResult(
            test_id=test_id,
            category=test_data.category.value,
            attack_type=test_data.attack_type,
            text=test_data.original_text[:100],
            expected_blocked=test_data.expected_blocked,
            actual_blocked=False,
            bypass_occurred=True,
            detection_confidence=0.0,
            bypass_rate_at_time=1.0,
            processing_time_ms=elapsed_ms,
            passed=False,
            error="No output from guard stage",
        )

    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return BypassTestResult(
            test_id=test_id,
            category=test_data.category.value,
            attack_type=test_data.attack_type,
            text=test_data.original_text[:100],
            expected_blocked=test_data.expected_blocked,
            actual_blocked=False,
            bypass_occurred=True,
            detection_confidence=0.0,
            bypass_rate_at_time=1.0,
            processing_time_ms=elapsed_ms,
            passed=False,
            error=str(e),
        )


async def run_direct_injection_tests(num_tests: int = 50) -> PipelineTestResult:
    """Run direct prompt injection tests."""
    pipeline = create_direct_injection_pipeline()
    generator = PolicyBypassTestDataGenerator(seed=42)
    dataset = generator.generate_direct_injection_dataset(num_tests)

    results: list[BypassTestResult] = []
    silent_failures: list[str] = []
    bypassed_cases: list[dict] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"direct_{i}")
        results.append(result)

        if result.bypass_occurred and item.expected_blocked:
            silent_failures.append(
                f"Attack bypassed: {item.attack_type} - {result.text[:50]}..."
            )
            bypassed_cases.append({
                "attack_type": item.attack_type,
                "text": result.text,
                "confidence": result.detection_confidence,
            })

    return _aggregate_results("direct_injection", results, silent_failures, bypassed_cases)


async def run_indirect_injection_tests(num_tests: int = 30) -> PipelineTestResult:
    """Run indirect injection (context manipulation) tests."""
    pipeline = create_indirect_injection_pipeline()
    generator = PolicyBypassTestDataGenerator(seed=42)
    dataset = generator.generate_indirect_injection_dataset(num_tests)

    results: list[BypassTestResult] = []
    silent_failures: list[str] = []
    bypassed_cases: list[dict] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"indirect_{i}")
        results.append(result)

        if result.bypass_occurred and item.expected_blocked:
            silent_failures.append(
                f"Context injection bypassed: {item.attack_type} - {result.text[:50]}..."
            )
            bypassed_cases.append({
                "attack_type": item.attack_type,
                "text": result.text,
                "confidence": result.detection_confidence,
            })

    return _aggregate_results("indirect_injection", results, silent_failures, bypassed_cases)


async def run_character_injection_tests(num_tests: int = 40) -> PipelineTestResult:
    """Run character injection (Unicode, emoji) tests."""
    pipeline = create_character_injection_pipeline()
    generator = PolicyBypassTestDataGenerator(seed=42)
    dataset = generator.generate_character_injection_dataset(num_tests)

    results: list[BypassTestResult] = []
    silent_failures: list[str] = []
    bypassed_cases: list[dict] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"char_{i}")
        results.append(result)

        if result.bypass_occurred and item.expected_blocked:
            silent_failures.append(
                f"Character injection bypassed: {item.attack_type} - {result.text[:50]}..."
            )
            bypassed_cases.append({
                "attack_type": item.attack_type,
                "text": result.text,
                "confidence": result.detection_confidence,
            })

    return _aggregate_results("character_injection", results, silent_failures, bypassed_cases)


async def run_automated_variation_tests(num_tests: int = 50) -> PipelineTestResult:
    """Run Best-of-N automated variation tests."""
    pipeline = create_automated_pipeline()
    generator = PolicyBypassTestDataGenerator(seed=42)
    dataset = generator.generate_automated_variation_dataset(num_tests)

    results: list[BypassTestResult] = []
    silent_failures: list[str] = []
    bypassed_cases: list[dict] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"auto_{i}")
        results.append(result)

        if result.bypass_occurred and item.expected_blocked:
            silent_failures.append(
                f"Automated variation bypassed: {item.attack_type} - {result.text[:50]}..."
            )
            bypassed_cases.append({
                "attack_type": item.attack_type,
                "text": result.text,
                "confidence": result.detection_confidence,
            })

    return _aggregate_results("automated_variation", results, silent_failures, bypassed_cases)


async def run_multi_turn_tests() -> PipelineTestResult:
    """Run multi-turn conversational attack tests."""
    pipeline = create_multi_turn_pipeline()
    generator = PolicyBypassTestDataGenerator(seed=42)
    dataset = generator.generate_multi_turn_dataset()

    results: list[BypassTestResult] = []
    silent_failures: list[str] = []
    bypassed_cases: list[dict] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"multiturn_{i}")
        results.append(result)

        if result.bypass_occurred and item.expected_blocked:
            silent_failures.append(
                f"Multi-turn attack bypassed at turn {item.metadata.get('turn_number', i+1)}: {result.text[:50]}..."
            )
            bypassed_cases.append({
                "attack_type": item.attack_type,
                "turn": item.metadata.get("turn_number"),
                "text": result.text,
                "confidence": result.detection_confidence,
            })

    return _aggregate_results("multi_turn", results, silent_failures, bypassed_cases)


async def run_evaluation_misuse_tests(num_tests: int = 20) -> PipelineTestResult:
    """Run evaluation misuse (Bad Likert Judge) tests."""
    pipeline = create_evaluation_misuse_pipeline()
    generator = PolicyBypassTestDataGenerator(seed=42)
    dataset = generator.generate_evaluation_misuse_dataset(num_tests)

    results: list[BypassTestResult] = []
    silent_failures: list[str] = []
    bypassed_cases: list[dict] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"eval_{i}")
        results.append(result)

        if result.bypass_occurred and item.expected_blocked:
            silent_failures.append(
                f"Evaluation misuse bypassed: {item.attack_type} - {result.text[:50]}..."
            )
            bypassed_cases.append({
                "attack_type": item.attack_type,
                "text": result.text,
                "confidence": result.detection_confidence,
            })

    return _aggregate_results("evaluation_misuse", results, silent_failures, bypassed_cases)


async def run_system_prompt_leak_tests(num_tests: int = 15) -> PipelineTestResult:
    """Run system prompt extraction tests."""
    pipeline = create_direct_injection_pipeline(bypass_rate=0.20)
    generator = PolicyBypassTestDataGenerator(seed=42)
    dataset = generator.generate_system_prompt_leak_dataset(num_tests)

    results: list[BypassTestResult] = []
    silent_failures: list[str] = []
    bypassed_cases: list[dict] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"promptleak_{i}")
        results.append(result)

        if result.bypass_occurred and item.expected_blocked:
            silent_failures.append(
                f"Prompt leak bypassed: {item.attack_type} - {result.text[:50]}..."
            )
            bypassed_cases.append({
                "attack_type": item.attack_type,
                "text": result.text,
                "confidence": result.detection_confidence,
            })

    return _aggregate_results("system_prompt_leak", results, silent_failures, bypassed_cases)


async def run_benign_tests(num_tests: int = 30) -> PipelineTestResult:
    """Run tests on benign inputs (should not be blocked)."""
    pipeline = create_direct_injection_pipeline()
    generator = PolicyBypassTestDataGenerator(seed=42)
    dataset = generator.generate_benign_dataset(num_tests)

    results: list[BypassTestResult] = []
    false_positives: list[str] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"benign_{i}")
        results.append(result)

        if result.actual_blocked and not item.expected_blocked:
            false_positives.append(
                f"False positive: {result.text[:50]}..."
            )

    aggregated = _aggregate_results("benign", results, false_positives, [])
    aggregated.false_positive_rate = len(false_positives) / max(len(results), 1)

    return aggregated


async def run_output_guard_tests(num_tests: int = 50) -> PipelineTestResult:
    """Test output guard effectiveness against LLM-generated injections."""
    pipeline = create_output_guard_pipeline()
    generator = PolicyBypassTestDataGenerator(seed=42)
    dataset = generator.generate_direct_injection_dataset(num_tests)

    results: list[BypassTestResult] = []
    silent_failures: list[str] = []
    bypassed_cases: list[dict] = []
    input_bypassed: int = 0
    output_bypassed: int = 0

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"output_{i}")
        results.append(result)

        # Track where bypass occurred
        if result.bypass_occurred:
            # This simplified check - in reality, we'd track both stages
            output_bypassed += 1

        if result.bypass_occurred and item.expected_blocked:
            silent_failures.append(
                f"Output guard bypassed: {item.attack_type} - {result.text[:50]}..."
            )
            bypassed_cases.append({
                "attack_type": item.attack_type,
                "text": result.text,
                "confidence": result.detection_confidence,
            })

    return _aggregate_results("output_guard", results, silent_failures, bypassed_cases)


def _aggregate_results(
    pipeline_name: str,
    results: list[BypassTestResult],
    silent_failures: list[str],
    bypassed_cases: list[dict],
) -> PipelineTestResult:
    """Aggregate test results into PipelineTestResult."""
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    expected_blocked = [r for r in results if r.expected_blocked]
    actually_blocked = [r for r in expected_blocked if r.actual_blocked]

    bypass_rate = (len(expected_blocked) - len(actually_blocked)) / max(len(expected_blocked), 1)
    detection_rate = len(actually_blocked) / max(len(expected_blocked), 1)

    false_positive_results = [r for r in results if r.actual_blocked and not r.expected_blocked]
    false_positive_rate = len(false_positive_results) / max(len(results), 1)

    latencies = [r.processing_time_ms for r in results if r.processing_time_ms > 0]
    latencies.sort()

    return PipelineTestResult(
        pipeline_name=pipeline_name,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        bypass_rate=bypass_rate,
        detection_rate=detection_rate,
        false_positive_rate=false_positive_rate,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
        p95_latency_ms=latencies[int(len(latencies) * 0.95)] if latencies else 0,
        p99_latency_ms=latencies[int(len(latencies) * 0.99)] if latencies else 0,
        silent_failures=silent_failures,
        bypassed_cases=bypassed_cases,
        test_results=results,
        timestamp=datetime.now().isoformat(),
    )


async def run_all_tests() -> dict:
    """Run all test pipelines and return comprehensive results."""
    print("Running GUARD-004 Policy Enforcement Bypass Tests...")
    print("=" * 60)
    print("Target: <5% bypass rate for all attack categories")
    print()

    results = {
        "direct_injection": await run_direct_injection_tests(50),
        "indirect_injection": await run_indirect_injection_tests(30),
        "character_injection": await run_character_injection_tests(40),
        "automated_variation": await run_automated_variation_tests(50),
        "multi_turn": run_multi_turn_tests(),
        "evaluation_misuse": await run_evaluation_misuse_tests(20),
        "system_prompt_leak": await run_system_prompt_leak_tests(15),
        "benign": await run_benign_tests(30),
    }

    print("Test Results Summary:")
    print("-" * 60)

    for name, result in results.items():
        bypass_status = "✅" if result.bypass_rate < 0.05 else "⚠️"
        print(f"\n{name.upper()}:")
        print(f"  Tests: {result.passed}/{result.total_tests} passed")
        print(f"  Bypass Rate: {result.bypass_rate:.2%} {bypass_status}")
        print(f"  Detection Rate: {result.detection_rate:.2%}")
        print(f"  False Positive Rate: {result.false_positive_rate:.2%}")
        print(f"  Avg Latency: {result.avg_latency_ms:.2f}ms")
        print(f"  Silent Failures: {len(result.silent_failures)}")

    # Calculate overall metrics
    attack_results = [r for r in results.values() if r.pipeline_name != "benign"]
    overall_bypass = sum(r.bypass_rate for r in attack_results) / len(attack_results)
    overall_detection = sum(r.detection_rate for r in attack_results) / len(attack_results)

    print(f"\n{'='*60}")
    print(f"Overall Bypass Rate: {overall_bypass:.2%}")
    print(f"Overall Detection Rate: {overall_detection:.2%}")
    print(f"Target: <5% bypass - {'✅ PASSED' if overall_bypass < 0.05 else '❌ NEEDS WORK'}")

    return results


async def run_comparison_test() -> dict:
    """Compare bypass rates across different security configurations."""
    print("\nRunning Security Configuration Comparison Test...")
    print("=" * 60)

    configs = {
        "low_security": create_low_security_config(),
        "medium_security": PolicyBypassConfig(),
        "high_security": create_high_security_config(),
    }

    generator = PolicyBypassTestDataGenerator(seed=42)
    dataset = generator.generate_direct_injection_dataset(30)

    results = {}

    for config_name, config in configs.items():
        service = PolicyBypassService(config)
        stage = PolicyEnforcementStage(service)
        pipeline = Pipeline().with_stage("guard", stage, StageKind.GUARD)

        bypassed = 0
        for item in dataset:
            result = await run_test_case(pipeline, item, f"{config_name}_{item.attack_id[:8]}")
            if result.bypass_occurred and item.expected_blocked:
                bypassed += 1

        bypass_rate = bypassed / len(dataset)
        results[config_name] = {
            "bypass_rate": bypass_rate,
            "bypassed_count": bypassed,
            "total_count": len(dataset),
        }
        print(f"  {config_name}: Bypass = {bypass_rate:.2%} ({bypassed}/{len(dataset)})")

    return results


if __name__ == "__main__":
    asyncio.run(run_all_tests())
