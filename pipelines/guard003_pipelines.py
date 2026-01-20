"""
GUARD-003 Test Pipelines: PII/PHI Redaction Accuracy

This module contains test pipelines for stress-testing PII/PHI redaction
accuracy in Stageflow's GUARD stage architecture.

Target: >99% recall (less than 1% false negatives)

Pipelines:
1. Baseline Pipeline - Normal operation with standard PII formats
2. Edge Case Pipeline - Boundary conditions and unusual formats
3. Adversarial Pipeline - Obfuscation and evasion attempts
4. Chaos Pipeline - Low-recall configuration for failure testing
5. Scale Pipeline - Performance and throughput testing
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

from mocks.services.pii_detection_mocks import (
    PIIDetectionService,
    PIIDetectionConfig,
    PIITestDataGenerator,
    PIICategory,
    DetectionResult,
)


@dataclass
class RedactionTestResult:
    """Result of a single redaction test case."""
    test_id: str
    category: str
    text: str
    expected_redaction: bool
    actual_redacted: bool
    phi_detected: bool
    phi_missed: bool
    recall_achieved: bool
    processing_time_ms: float
    passed: bool
    error: Optional[str] = None
    detected_entities: list[dict] = field(default_factory=list)
    missed_entities: list[dict] = field(default_factory=list)


@dataclass
class PipelineTestResult:
    """Aggregated results for a test pipeline."""
    pipeline_name: str
    total_tests: int
    passed: int
    failed: int
    recall_rate: float
    precision_rate: float
    false_negative_rate: float
    false_positive_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    silent_failures: list[str]
    test_results: list[RedactionTestResult]
    timestamp: str


class PIIGuardStage:
    """GUARD stage that performs PII/PHI detection and redaction."""

    name = "pii_guard"
    kind = StageKind.GUARD

    def __init__(
        self,
        detector: Optional[PIIDetectionService] = None,
        config: Optional[PIIDetectionConfig] = None,
        redact_output: bool = True,
    ):
        self._detector = detector or PIIDetectionService(config)
        self._redact_output = redact_output
        self._stats = {
            "checks": 0,
            "redacted": 0,
            "passed": 0,
            "partial": 0,
            "failed": 0,
            "entities_detected": 0,
            "entities_missed": 0,
        }

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute PII detection and redaction on input."""
        self._stats["checks"] += 1

        input_text = ctx.snapshot.input_text or ""
        context = {"user_id": str(ctx.snapshot.user_id)}

        try:
            result = await self._detector.detect(content=input_text, context=context)

            self._stats["entities_detected"] += len(result.detected_entities)
            self._stats["entities_missed"] += (
                result.confidence < 1.0 and len(result.detected_entities) > 0
            )

            if result.result == DetectionResult.PASSED:
                self._stats["passed"] += 1
                return StageOutput.ok(
                    passed=True,
                    redaction_performed=False,
                    entities_detected=0,
                    processing_time_ms=result.processing_time_ms,
                )
            elif result.result == DetectionResult.REDACTED:
                self._stats["redacted"] += 1
                return StageOutput.ok(
                    passed=True,
                    redaction_performed=True,
                    redacted_text=result.redacted_text,
                    entities_detected=len(result.detected_entities),
                    processing_time_ms=result.processing_time_ms,
                )
            elif result.result == DetectionResult.PARTIAL:
                self._stats["partial"] += 1
                return StageOutput.ok(
                    passed=False,
                    redaction_performed=True,
                    redacted_text=result.redacted_text,
                    entities_detected=len(result.detected_entities),
                    partial_detection=True,
                    processing_time_ms=result.processing_time_ms,
                )
            else:
                self._stats["failed"] += 1
                return StageOutput.fail(
                    error="PII detection failed",
                    data={
                        "error_type": "detection_failure",
                        "processing_time_ms": result.processing_time_ms,
                    },
                )

        except Exception as e:
            self._stats["failed"] += 1
            return StageOutput.fail(
                error=f"PII detection error: {e}",
                data={"error_type": type(e).__name__},
            )

    def get_stats(self) -> dict:
        """Get stage statistics."""
        total = self._stats["checks"]
        detected = self._stats["entities_detected"]
        missed = self._stats["entities_missed"]

        return {
            **self._stats,
            "recall_rate": detected / max(detected + missed, 1),
        }


class MockLLMStage:
    """Mock LLM stage that may contain PII in outputs."""

    name = "mock_llm"
    kind = StageKind.TRANSFORM

    def __init__(self, include_phi_in_output: bool = True):
        self._include_phi = include_phi_in_output
        self._call_count = 0
        self._generator = PIITestDataGenerator(seed=42)

    async def execute(self, ctx: StageContext) -> StageOutput:
        """Generate mock LLM response."""
        self._call_count += 1
        input_text = ctx.snapshot.input_text or ""

        if self._include_phi:
            response = self._generator.generate_clinical_text(include_phi=True)
        else:
            response = f"Response to: {input_text[:50]}..."

        return StageOutput.ok(
            response=response,
            model="mock-llm",
            input_tokens=len(input_text),
            output_tokens=len(response),
        )

    def get_stats(self) -> dict:
        return {"calls": self._call_count}


def create_baseline_pipeline() -> Pipeline:
    """Create baseline pipeline for standard PII testing."""
    config = PIIDetectionConfig()
    guard_stage = PIIGuardStage(config=config)
    llm_stage = MockLLMStage(include_phi_in_output=False)

    return (
        Pipeline()
        .with_stage("input_guard", guard_stage, StageKind.GUARD)
        .with_stage("llm", llm_stage, StageKind.TRANSFORM, dependencies=("input_guard",))
        .with_stage("output_guard", PIIGuardStage(config=config), StageKind.GUARD, dependencies=("llm",))
    )


def create_edge_case_pipeline() -> Pipeline:
    """Create pipeline for edge case testing."""
    config = PIIDetectionConfig(
        detection_rates={
            "person_name": 0.85,
            "phone_number": 0.90,
            "email": 0.92,
            "ssn": 0.92,
            "date_of_birth": 0.88,
            "address": 0.75,
            "medical_record_number": 0.70,
            "health_plan_id": 0.68,
            "account_number": 0.78,
            "license_number": 0.65,
            "vehicle_id": 0.60,
            "device_id": 0.62,
            "web_url": 0.95,
            "ip_address": 0.93,
            "zip_code": 0.88,
            "age_over_89": 0.50,
            "other_phi": 0.60,
        },
        false_positive_rate=0.02,
        partial_detection_rate=0.10,
    )

    return (
        Pipeline()
        .with_stage("input_guard", PIIGuardStage(config=config), StageKind.GUARD)
        .with_stage("output_guard", PIIGuardStage(config=config), StageKind.GUARD)
    )


def create_adversarial_pipeline() -> Pipeline:
    """Create pipeline for adversarial PII testing."""
    config = PIIDetectionConfig(
        detection_rates={
            "person_name": 0.80,
            "phone_number": 0.85,
            "email": 0.88,
            "ssn": 0.88,
            "date_of_birth": 0.82,
            "address": 0.70,
            "medical_record_number": 0.65,
            "health_plan_id": 0.62,
            "account_number": 0.72,
            "license_number": 0.58,
            "vehicle_id": 0.55,
            "device_id": 0.58,
            "web_url": 0.92,
            "ip_address": 0.90,
            "zip_code": 0.85,
            "age_over_89": 0.45,
            "other_phi": 0.55,
        },
        false_positive_rate=0.03,
        partial_detection_rate=0.12,
        enable_adversarial_vulnerability=True,
    )

    return (
        Pipeline()
        .with_stage("input_guard", PIIGuardStage(config=config), StageKind.GUARD)
        .with_stage("output_guard", PIIGuardStage(config=config), StageKind.GUARD)
    )


def create_chaos_pipeline() -> Pipeline:
    """Create pipeline for chaos testing with low recall config."""
    config = PIIDetectionConfig(
        detection_rates={
            "person_name": 0.60,
            "phone_number": 0.70,
            "email": 0.75,
            "ssn": 0.75,
            "date_of_birth": 0.65,
            "address": 0.50,
            "medical_record_number": 0.45,
            "health_plan_id": 0.42,
            "account_number": 0.55,
            "license_number": 0.40,
            "vehicle_id": 0.35,
            "device_id": 0.38,
            "web_url": 0.80,
            "ip_address": 0.78,
            "zip_code": 0.70,
            "age_over_89": 0.30,
            "other_phi": 0.40,
        },
        false_positive_rate=0.08,
        partial_detection_rate=0.20,
        enable_adversarial_vulnerability=True,
        enable_edge_case_vulnerability=True,
    )

    return (
        Pipeline()
        .with_stage("input_guard", PIIGuardStage(config=config), StageKind.GUARD)
        .with_stage("output_guard", PIIGuardStage(config=config), StageKind.GUARD)
    )


async def run_test_case(
    pipeline: Pipeline,
    test_data: dict[str, Any],
    test_id: str,
) -> RedactionTestResult:
    """Run a single redaction test case."""
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
            input_text=test_data["text"],
        )

        ctx = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name="pipeline_entry",
            timer=PipelineTimer(),
        )

        outputs = await graph.run(ctx)

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        input_guard_output = outputs.get("input_guard")

        if input_guard_output:
            if input_guard_output.status.value == "failed":
                return RedactionTestResult(
                    test_id=test_id,
                    category=test_data.get("category", "unknown"),
                    text=test_data["text"][:100],
                    expected_redaction=test_data.get("expected_redaction", True),
                    actual_redacted=False,
                    phi_detected=False,
                    phi_missed=test_data.get("has_phi", False),
                    recall_achieved=False,
                    processing_time_ms=elapsed_ms,
                    passed=False,
                    error=input_guard_output.data.get("error", "Unknown error"),
                )

            detected_count = input_guard_output.data.get("entities_detected", 0)
            has_phi = test_data.get("has_phi", False)
            expected_redaction = test_data.get("expected_redaction", True)

            phi_detected = detected_count > 0
            phi_missed = has_phi and not phi_detected

            passed = (
                (not expected_redaction and not phi_detected) or
                (expected_redaction and phi_detected)
            )

            return RedactionTestResult(
                test_id=test_id,
                category=test_data.get("category", "unknown"),
                text=test_data["text"][:100],
                expected_redaction=expected_redaction,
                actual_redacted=phi_detected,
                phi_detected=phi_detected,
                phi_missed=phi_missed,
                recall_achieved=not phi_missed,
                processing_time_ms=elapsed_ms,
                passed=passed,
            )

        return RedactionTestResult(
            test_id=test_id,
            category=test_data.get("category", "unknown"),
            text=test_data["text"][:100],
            expected_redaction=test_data.get("expected_redaction", True),
            actual_redacted=False,
            phi_detected=False,
            phi_missed=test_data.get("has_phi", False),
            recall_achieved=False,
            processing_time_ms=elapsed_ms,
            passed=False,
            error="No output from input guard stage",
        )

    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return RedactionTestResult(
            test_id=test_id,
            category=test_data.get("category", "unknown"),
            text=test_data["text"][:100],
            expected_redaction=test_data.get("expected_redaction", True),
            actual_redacted=False,
            phi_detected=False,
            phi_missed=test_data.get("has_phi", False),
            recall_achieved=False,
            processing_time_ms=elapsed_ms,
            passed=False,
            error=str(e),
        )


async def run_baseline_tests(num_tests: int = 100) -> PipelineTestResult:
    """Run baseline tests with standard PII formats."""
    pipeline = create_baseline_pipeline()
    generator = PIITestDataGenerator(seed=42)
    dataset = generator.generate_happy_path_dataset(num_tests)

    results: list[RedactionTestResult] = []
    silent_failures: list[str] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"baseline_{i}")
        results.append(result)

        if result.phi_missed and item.get("has_phi", False):
            silent_failures.append(
                f"PHI missed: {item['category']} - {result.text[:50]}..."
            )

    return _aggregate_results("baseline", results, silent_failures)


async def run_edge_case_tests(num_tests: int = 50) -> PipelineTestResult:
    """Run edge case tests with unusual PII formats."""
    pipeline = create_edge_case_pipeline()
    generator = PIITestDataGenerator(seed=42)
    dataset = generator.generate_edge_case_dataset(num_tests)

    results: list[RedactionTestResult] = []
    silent_failures: list[str] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"edge_{i}")
        results.append(result)

        if result.phi_missed and item.get("has_phi", False):
            silent_failures.append(
                f"PHI missed (edge case): {item.get('description', item['category'])} - {result.text[:50]}..."
            )

    return _aggregate_results("edge_cases", results, silent_failures)


async def run_adversarial_tests(num_tests: int = 50) -> PipelineTestResult:
    """Run adversarial tests with obfuscation."""
    pipeline = create_adversarial_pipeline()
    generator = PIITestDataGenerator(seed=42)
    dataset = generator.generate_adversarial_dataset(num_tests)

    results: list[RedactionTestResult] = []
    silent_failures: list[str] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"adversarial_{i}")
        results.append(result)

        if result.phi_missed and item.get("has_phi", False):
            silent_failures.append(
                f"PHI missed (adversarial): {item.get('description', item['category'])} - {result.text[:50]}..."
            )

    return _aggregate_results("adversarial", results, silent_failures)


async def run_chaos_tests(num_tests: int = 50) -> PipelineTestResult:
    """Run chaos tests with low-recall configuration."""
    pipeline = create_chaos_pipeline()
    generator = PIITestDataGenerator(seed=42)
    dataset = generator.generate_full_test_dataset(
        happy_path_count=20,
        edge_case_count=10,
        adversarial_count=10,
        no_phi_count=10,
    )["happy_path"] + generator.generate_edge_case_dataset(10)

    results: list[RedactionTestResult] = []
    silent_failures: list[str] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"chaos_{i}")
        results.append(result)

        if result.phi_missed and item.get("has_phi", False):
            silent_failures.append(
                f"PHI missed (chaos): {item['category']} - {result.text[:50]}..."
            )

    return _aggregate_results("chaos", results, silent_failures)


async def run_no_phi_tests(num_tests: int = 30) -> PipelineTestResult:
    """Run tests on text with no PHI to check false positives."""
    pipeline = create_baseline_pipeline()
    generator = PIITestDataGenerator(seed=42)
    dataset = generator.generate_no_phi_dataset(num_tests)

    results: list[RedactionTestResult] = []
    false_positives: list[str] = []

    for i, item in enumerate(dataset):
        result = await run_test_case(pipeline, item, f"nophi_{i}")
        results.append(result)

        if result.actual_redacted and not item.get("has_phi", False):
            false_positives.append(
                f"False positive: {result.text[:50]}..."
            )

    aggregated = _aggregate_results("no_phi", results, false_positives)
    aggregated.false_positive_rate = len(false_positives) / max(len(results), 1)

    return aggregated


def _aggregate_results(
    pipeline_name: str,
    results: list[RedactionTestResult],
    silent_failures: list[str],
) -> PipelineTestResult:
    """Aggregate test results into PipelineTestResult."""
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    phi_results = [r for r in results if r.text]
    phi_detected = sum(1 for r in phi_results if r.phi_detected)
    phi_missed = sum(1 for r in phi_results if r.phi_missed)
    phi_total = phi_detected + phi_missed

    recall_rate = phi_detected / max(phi_total, 1)

    false_positive_results = [r for r in results if r.actual_redacted and not r.expected_redaction]
    false_positive_rate = len(false_positive_results) / max(len(results), 1)

    latencies = [r.processing_time_ms for r in results if r.processing_time_ms > 0]
    latencies.sort()

    return PipelineTestResult(
        pipeline_name=pipeline_name,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        recall_rate=recall_rate,
        precision_rate=1.0 - false_positive_rate,
        false_negative_rate=1.0 - recall_rate,
        false_positive_rate=false_positive_rate,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
        p95_latency_ms=latencies[int(len(latencies) * 0.95)] if latencies else 0,
        p99_latency_ms=latencies[int(len(latencies) * 0.99)] if latencies else 0,
        silent_failures=silent_failures,
        test_results=results,
        timestamp=datetime.now().isoformat(),
    )


async def run_all_tests() -> dict:
    """Run all test pipelines and return comprehensive results."""
    print("Running GUARD-003 PII/PHI Redaction Tests...")
    print("=" * 60)
    print("Target: >99% recall (less than 1% false negatives)")
    print()

    results = {
        "baseline": await run_baseline_tests(100),
        "edge_cases": await run_edge_case_tests(50),
        "adversarial": await run_adversarial_tests(50),
        "chaos": await run_chaos_tests(50),
        "no_phi": await run_no_phi_tests(30),
    }

    print("Test Results Summary:")
    print("-" * 60)

    for name, result in results.items():
        recall_status = "✅" if result.recall_rate >= 0.99 else "⚠️"
        print(f"\n{name.upper()}:")
        print(f"  Tests: {result.passed}/{result.total_tests} passed")
        print(f"  Recall: {result.recall_rate:.2%} {recall_status}")
        print(f"  False Negative Rate: {result.false_negative_rate:.2%}")
        print(f"  False Positive Rate: {result.false_positive_rate:.2%}")
        print(f"  Avg Latency: {result.avg_latency_ms:.2f}ms")
        print(f"  Silent Failures: {len(result.silent_failures)}")

    overall_recall = sum(r.recall_rate for r in results.values()) / len(results)
    print(f"\n{'='*60}")
    print(f"Overall Recall Rate: {overall_recall:.2%}")
    print(f"Target: >99% - {'✅ PASSED' if overall_recall >= 0.99 else '❌ NEEDS WORK'}")

    return results


async def run_recall_comparison_test() -> dict:
    """Compare recall rates across different configurations."""
    print("\nRunning Recall Comparison Test...")
    print("=" * 60)

    configs = {
        "baseline": PIIDetectionConfig(),
        "edge_optimized": PIIDetectionConfig(
            detection_rates={k: 0.98 for k in ["person_name", "phone_number", "email", "ssn", "date_of_birth"]},
        ),
        "high_recall": None,  # Will use create_high_recall_config
    }

    results = {}
    generator = PIITestDataGenerator(seed=42)
    dataset = generator.generate_full_test_dataset(
        happy_path_count=50,
        edge_case_count=25,
        adversarial_count=25,
        no_phi_count=0,
    )

    for config_name, config in configs.items():
        if config_name == "high_recall":
            from mocks.services.pii_detection_mocks import create_high_recall_config
            config = create_high_recall_config()

        service = PIIDetectionService(config)
        total_detected = 0
        total_missed = 0

        for category, items in dataset.items():
            for item in items:
                if item.get("has_phi", False):
                    detection = await service.detect(item["text"])
                    if detection.detected_entities:
                        total_detected += len(detection.detected_entities)
                    else:
                        total_missed += 1

        recall = total_detected / max(total_detected + total_missed, 1)
        results[config_name] = {
            "recall_rate": recall,
            "detected": total_detected,
            "missed": total_missed,
        }

        print(f"  {config_name}: Recall = {recall:.2%} ({total_detected} detected, {total_missed} missed)")

    return results


if __name__ == "__main__":
    asyncio.run(run_all_tests())
