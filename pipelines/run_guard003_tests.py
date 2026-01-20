#!/usr/bin/env python3
"""
GUARD-003 Test Runner: PII/PHI Redaction Accuracy

This script runs all test pipelines for GUARD-003 and generates
comprehensive results including metrics, logs, and findings.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines.guard003_pipelines import (
    run_baseline_tests,
    run_edge_case_tests,
    run_adversarial_tests,
    run_chaos_tests,
    run_no_phi_tests,
    run_recall_comparison_test,
    create_baseline_pipeline,
    create_edge_case_pipeline,
    create_adversarial_pipeline,
    create_chaos_pipeline,
)

from mocks.services.pii_detection_mocks import (
    PIIDetectionService,
    PIIDetectionConfig,
    PIITestDataGenerator,
)


RESULTS_DIR = Path(__file__).parent.parent / "results"
LOGS_DIR = RESULTS_DIR / "logs"
METRICS_DIR = RESULTS_DIR / "metrics"


def setup_logging(log_file: Path) -> logging.Logger:
    """Set up structured logging for test run."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("guard003")
    logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(log_file, mode='w')
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def calculate_overall_metrics(results: dict) -> dict:
    """Calculate overall metrics across all test pipelines."""
    total_passed = sum(r.passed for r in results.values())
    total_tests = sum(r.total_tests for r in results.values())

    total_recall = sum(r.recall_rate for r in results.values())
    avg_recall = total_recall / len(results) if results else 0

    total_fn = sum(r.false_negative_rate for r in results.values())
    avg_fn = total_fn / len(results) if results else 0

    total_fp = sum(r.false_positive_rate for r in results.values())
    avg_fp = total_fp / len(results) if results else 0

    total_latency = sum(r.avg_latency_ms for r in results.values())
    avg_latency = total_latency / len(results) if results else 0

    total_silent = sum(len(r.silent_failures) for r in results.values())

    return {
        "total_tests": total_tests,
        "total_passed": total_passed,
        "overall_pass_rate": total_passed / max(total_tests, 1),
        "average_recall_rate": avg_recall,
        "average_false_negative_rate": avg_fn,
        "average_false_positive_rate": avg_fp,
        "average_latency_ms": avg_latency,
        "total_silent_failures": total_silent,
        "recall_target_met": avg_recall >= 0.99,
    }


def generate_test_summary(results: dict, comparison_results: dict) -> dict:
    """Generate comprehensive test summary."""
    overall = calculate_overall_metrics(results)

    summary = {
        "mission_id": "GUARD-003",
        "target": "PII/PHI redaction accuracy (>99% recall)",
        "priority": "P0",
        "risk": "Severe",
        "timestamp": datetime.now().isoformat(),
        "overall_metrics": overall,
        "pipeline_results": {},
        "recall_comparison": comparison_results,
        "verdict": "PASS" if overall["recall_target_met"] else "NEEDS_WORK",
        "recommendations": [],
    }

    for name, result in results.items():
        summary["pipeline_results"][name] = {
            "total_tests": result.total_tests,
            "passed": result.passed,
            "failed": result.failed,
            "recall_rate": result.recall_rate,
            "false_negative_rate": result.false_negative_rate,
            "false_positive_rate": result.false_positive_rate,
            "avg_latency_ms": result.avg_latency_ms,
            "p95_latency_ms": result.p95_latency_ms,
            "silent_failures_count": len(result.silent_failures),
            "silent_failures": result.silent_failures[:10],
        }

    if overall["recall_target_met"]:
        summary["recommendations"].append("Continue monitoring recall rate in production")
        summary["recommendations"].append("Consider periodic adversarial testing")
    else:
        summary["recommendations"].append("Improve detection rates for missed PII categories")
        summary["recommendations"].append("Add multi-pass detection for edge cases")
        summary["recommendations"].append("Consider LLM-based detection for adversarial inputs")

    return summary


def save_results(results: dict, comparison_results: dict, logger: logging.Logger):
    """Save all test results to files."""
    METRICS_DIR.mkdir(parents=True, exist_ok=True)

    summary = generate_test_summary(results, comparison_results)

    summary_file = METRICS_DIR / "guard003_summary.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Saved summary to {summary_file}")

    for name, result in results.items():
        result_file = METRICS_DIR / f"guard003_{name}_results.json"
        result_data = {
            "pipeline_name": result.pipeline_name,
            "timestamp": result.timestamp,
            "total_tests": result.total_tests,
            "passed": result.passed,
            "failed": result.failed,
            "recall_rate": result.recall_rate,
            "precision_rate": result.precision_rate,
            "false_negative_rate": result.false_negative_rate,
            "false_positive_rate": result.false_positive_rate,
            "avg_latency_ms": result.avg_latency_ms,
            "p95_latency_ms": result.p95_latency_ms,
            "p99_latency_ms": result.p99_latency_ms,
            "silent_failures": result.silent_failures,
            "test_results": [
                {
                    "test_id": r.test_id,
                    "category": r.category,
                    "passed": r.passed,
                    "recall_achieved": r.recall_achieved,
                    "processing_time_ms": r.processing_time_ms,
                }
                for r in result.test_results
            ],
        }
        with open(result_file, 'w') as f:
            json.dump(result_data, f, indent=2)
        logger.info(f"Saved {name} results to {result_file}")

    return summary


async def main():
    """Run all GUARD-003 tests."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"guard003_test_{timestamp}.log"
    logger = setup_logging(log_file)

    logger.info("=" * 70)
    logger.info("GUARD-003 Test Runner: PII/PHI Redaction Accuracy")
    logger.info("=" * 70)
    logger.info(f"Target: >99% recall (less than 1% false negatives)")
    logger.info(f"Started: {datetime.now().isoformat()}")
    logger.info("")

    try:
        logger.info("Phase 1: Baseline Tests (Standard PII formats)")
        logger.info("-" * 40)
        results = {
            "baseline": await run_baseline_tests(100),
        }

        logger.info("\nPhase 2: Edge Case Tests (Unusual formats)")
        logger.info("-" * 40)
        results["edge_cases"] = await run_edge_case_tests(50)

        logger.info("\nPhase 3: Adversarial Tests (Obfuscation)")
        logger.info("-" * 40)
        results["adversarial"] = await run_adversarial_tests(50)

        logger.info("\nPhase 4: Chaos Tests (Low recall config)")
        logger.info("-" * 40)
        results["chaos"] = await run_chaos_tests(50)

        logger.info("\nPhase 5: False Positive Tests (No PHI)")
        logger.info("-" * 40)
        results["no_phi"] = await run_no_phi_tests(30)

        logger.info("\nPhase 6: Recall Comparison")
        logger.info("-" * 40)
        comparison_results = await run_recall_comparison_test()

        logger.info("\n" + "=" * 70)
        logger.info("Saving Results")
        logger.info("-" * 40)

        summary = save_results(results, comparison_results, logger)

        logger.info("\n" + "=" * 70)
        logger.info("FINAL RESULTS")
        logger.info("=" * 70)
        logger.info(f"Overall Recall Rate: {summary['overall_metrics']['average_recall_rate']:.2%}")
        logger.info(f"Target (>99%): {'✅ PASSED' if summary['overall_metrics']['recall_target_met'] else '❌ FAILED'}")
        logger.info(f"Total Silent Failures: {summary['overall_metrics']['total_silent_failures']}")
        logger.info(f"Verdict: {summary['verdict']}")
        logger.info("=" * 70)

        return summary

    except Exception as e:
        logger.error(f"Test run failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
