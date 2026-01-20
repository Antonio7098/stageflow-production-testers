#!/usr/bin/env python3
"""TRANSFORM-006: Encoding Detection and Conversion Test Runner.

This script runs comprehensive tests for encoding detection and conversion
in Stageflow TRANSFORM stages.

Usage:
    python run_transform006_tests.py [--verbose] [--output DIR]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow import Pipeline, StageContext, StageKind, StageOutput, PipelineTimer
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow.stages import StageInputs
from pipelines.transform006_pipelines import (
    create_bom_pipeline,
    create_mojibake_pipeline,
    create_surrogate_pipeline,
    create_encoding_conversion_pipeline,
    create_json_encoding_pipeline,
    create_comprehensive_encoding_pipeline,
)
from mocks.encoding_mocks import EncodingMockData

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class EncodingTestRunner:
    """Comprehensive test runner for TRANSFORM-006."""

    def __init__(self, verbose: bool = False, output_dir: Path | None = None):
        self.verbose = verbose
        self.output_dir = output_dir or Path("results")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: dict[str, Any] = {}
        self.findings: list[dict[str, Any]] = []

    async def run_test(
        self,
        pipeline: Pipeline,
        test_input: str,
        stage_name: str,
        test_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a single test."""
        test_id = f"tf006-{datetime.now().strftime('%H%M%S')}-{id(test_input) % 10000:04d}"

        snapshot = ContextSnapshot(
            run_id=RunIdentity(
                pipeline_run_id=__import__("uuid").uuid4(),
                request_id=__import__("uuid").uuid4(),
                session_id=__import__("uuid").uuid4(),
                user_id=__import__("uuid").uuid4(),
                org_id=None,
                interaction_id=__import__("uuid").uuid4(),
            ),
            topology="transform006",
            execution_mode="test",
            input_text=test_input,
        )

        ctx = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name=stage_name,
            timer=PipelineTimer(),
        )

        result = {
            "test_id": test_id,
            "category": test_metadata.get("category", "unknown"),
            "description": test_metadata.get("description", ""),
            "input_preview": test_input[:100] + ("..." if len(test_input) > 100 else ""),
            "success": False,
            "status": "pending",
            "data": {},
            "error": None,
            "expected": test_metadata.get("expected"),
            "timestamp": datetime.now().isoformat(),
        }

        try:
            graph = pipeline.build()
            output = await graph.run(ctx)

            stage_output = output.get(stage_name)
            if stage_output:
                result["success"] = stage_output.status.value == "ok"
                result["status"] = stage_output.status.value
                result["data"] = stage_output.data or {}
                result["error"] = str(stage_output.error) if stage_output.error else None
            else:
                result["status"] = "not_found"
                result["error"] = "Stage not found in output"

            # Check for silent failures
            if result["success"] and result["expected"]:
                if isinstance(result["expected"], dict):
                    # Check if expected keys are present
                    for key, expected_value in result["expected"].items():
                        actual_value = result["data"].get(key)
                        if actual_value != expected_value:
                            result["success"] = False
                            result["status"] = "validation_failed"
                            result["error"] = f"Expected {key}={expected_value}, got {actual_value}"
                            self._log_finding(
                                "silent_failure",
                                f"Expected {key}={expected_value}, got {actual_value}",
                                test_metadata,
                            )

        except Exception as e:
            result["status"] = "exception"
            result["error"] = str(e)
            result["exception_type"] = type(e).__name__

            # Log exception as finding if it's a bug
            if "encoding" in str(e).lower() or "unicode" in str(e).lower():
                self._log_finding(
                    "encoding_exception",
                    str(e),
                    test_metadata,
                )

        return result

    def _log_finding(
        self,
        finding_type: str,
        details: str,
        metadata: dict[str, Any],
    ) -> None:
        """Log a finding for later reporting."""
        self.findings.append({
            "type": finding_type,
            "details": details,
            "category": metadata.get("category", "unknown"),
            "description": metadata.get("description", ""),
        })

    async def run_bom_tests(self) -> list[dict[str, Any]]:
        """Run BOM handling tests."""
        logger.info("Running BOM tests...")
        pipeline = create_bom_pipeline()
        results = []

        for case in EncodingMockData.bom_test_cases():
            # Convert bytes to string for input
            test_input = case["raw_bytes"].decode("utf-8", errors="replace")

            result = await self.run_test(
                pipeline,
                test_input,
                "bom_strip",
                {
                    "category": "bom",
                    "description": case["description"],
                    "expected": {
                        "bom_detected": case.get("should_detect_bom", False),
                        "bom_type": case.get("expected_encoding"),
                    },
                },
            )
            results.append(result)

        return results

    async def run_mojibake_tests(self) -> list[dict[str, Any]]:
        """Run mojibake repair tests."""
        logger.info("Running mojibake tests...")
        pipeline = create_mojibake_pipeline()
        results = []

        for case in EncodingMockData.mojibake_test_cases():
            result = await self.run_test(
                pipeline,
                case["corrupted_bytes"],
                "mojibake_repair",
                {
                    "category": "mojibake",
                    "description": case["description"],
                    "expected": case.get("expected_repaired"),
                },
            )
            results.append(result)

        return results

    async def run_surrogate_tests(self) -> list[dict[str, Any]]:
        """Run surrogate pair validation tests."""
        logger.info("Running surrogate tests...")
        pipeline = create_surrogate_pipeline()
        results = []

        for case in EncodingMockData.surrogate_pair_test_cases():
            # Wrap in JSON object for testing
            test_input = f'{{"test": {case["json_string"]}}}'

            result = await self.run_test(
                pipeline,
                test_input,
                "surrogate_validate",
                {
                    "category": "surrogates",
                    "description": case["description"],
                    "expected": {
                        "is_valid": case.get("should_parse", True),
                        "has_surrogates": case.get("should_parse", True),
                    },
                },
            )
            results.append(result)

        return results

    async def run_charset_tests(self) -> list[dict[str, Any]]:
        """Run charset detection tests."""
        logger.info("Running charset detection tests...")
        pipeline = create_bom_pipeline()
        results = []

        for case in EncodingMockData.charset_detection_test_cases():
            result = await self.run_test(
                pipeline,
                case["input"],
                "encoding_detect",
                {
                    "category": "charset_detection",
                    "description": case["description"],
                    "expected": {
                        "encoding": case.get("expected_detection"),
                        "confidence": case.get("confidence"),
                    },
                },
            )
            results.append(result)

        return results

    async def run_conversion_tests(self) -> list[dict[str, Any]]:
        """Run encoding conversion tests."""
        logger.info("Running encoding conversion tests...")
        results = []

        for case in EncodingMockData.encoding_conversion_test_cases():
            pipeline = create_encoding_conversion_pipeline(
                target_encoding=case["target_encoding"],
                source_encoding=case.get("source_encoding"),
            )

            result = await self.run_test(
                pipeline,
                case["input_text"],
                "encoding_convert",
                {
                    "category": "encoding_conversion",
                    "description": case["description"],
                    "expected": {
                        "success": case.get("expected_success", True),
                        "source_encoding": case.get("source_encoding", "utf-8"),
                        "target_encoding": case["target_encoding"],
                    },
                },
            )
            results.append(result)

        return results

    async def run_json_tests(self) -> list[dict[str, Any]]:
        """Run JSON encoding tests."""
        logger.info("Running JSON encoding tests...")
        pipeline = create_json_encoding_pipeline()
        results = []

        for case in EncodingMockData.json_encoding_test_cases():
            test_input = case.get("json_string", case.get("json_bytes", ""))

            result = await self.run_test(
                pipeline,
                test_input,
                "json_parse",
                {
                    "category": "json_encoding",
                    "description": case["description"],
                    "expected": {
                        "is_valid": case.get("should_parse", True),
                    },
                },
            )
            results.append(result)

        return results

    async def run_all_tests(self) -> dict[str, Any]:
        """Run all encoding tests."""
        logger.info("=" * 60)
        logger.info("TRANSFORM-006: Encoding Detection and Conversion Tests")
        logger.info("=" * 60)

        self.results = {
            "test_run_id": f"transform006-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "timestamp": datetime.now().isoformat(),
            "categories": {},
            "summary": {},
            "findings": self.findings,
        }

        # Run all test categories
        test_categories = [
            ("bom", self.run_bom_tests),
            ("mojibake", self.run_mojibake_tests),
            ("surrogates", self.run_surrogate_tests),
            ("charset_detection", self.run_charset_tests),
            ("encoding_conversion", self.run_conversion_tests),
            ("json_encoding", self.run_json_tests),
        ]

        for category_name, test_func in test_categories:
            logger.info(f"\n{'=' * 40}")
            logger.info(f"Testing: {category_name}")
            logger.info(f"{'=' * 40}")

            try:
                results = await test_func()
                self.results["categories"][category_name] = results

                passed = sum(1 for r in results if r["success"])
                total = len(results)
                logger.info(f"Results: {passed}/{total} passed ({100*passed/total:.1f}%)")

                # Log failures
                for result in results:
                    if not result["success"]:
                        logger.warning(f"  FAILED: {result['description']}")
                        if result.get("error"):
                            logger.warning(f"    Error: {result['error'][:100]}")

            except Exception as e:
                logger.error(f"Category {category_name} failed: {e}")
                self.results["categories"][category_name] = []
                self.findings.append({
                    "type": "test_category_failure",
                    "details": str(e),
                    "category": category_name,
                })

        # Calculate summary
        total_tests = 0
        total_passed = 0

        for category, results in self.results["categories"].items():
            total_tests += len(results)
            total_passed += sum(1 for r in results if r["success"])

        self.results["summary"] = {
            "total_tests": total_tests,
            "total_passed": total_passed,
            "total_failed": total_tests - total_passed,
            "pass_rate": 100 * total_passed / total_tests if total_tests > 0 else 0,
            "categories_tested": len(test_categories),
        }

        # Save results
        self._save_results()

        return self.results

    def _save_results(self) -> None:
        """Save test results to files."""
        # Save full results as JSON
        results_file = self.output_dir / f"transform006_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, default=str)
        logger.info(f"\nResults saved to: {results_file}")

        # Save summary
        summary_file = self.output_dir / "transform006_summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(self.results["summary"], f, indent=2)
        logger.info(f"Summary saved to: {summary_file}")

        # Save findings
        if self.findings:
            findings_file = self.output_dir / "transform006_findings.json"
            with open(findings_file, "w", encoding="utf-8") as f:
                json.dump(self.findings, f, indent=2)
            logger.info(f"Findings saved to: {findings_file}")

    def print_summary(self) -> None:
        """Print test summary."""
        print("\n" + "=" * 60)
        print("TRANSFORM-006 TEST SUMMARY")
        print("=" * 60)

        summary = self.results["summary"]
        print(f"\nTotal Tests: {summary['total_tests']}")
        print(f"Passed: {summary['total_passed']}")
        print(f"Failed: {summary['total_failed']}")
        print(f"Pass Rate: {summary['pass_rate']:.1f}%")

        print("\nBy Category:")
        for category, results in self.results["categories"].items():
            passed = sum(1 for r in results if r["success"])
            total = len(results)
            print(f"  {category}: {passed}/{total} ({100*passed/total:.1f}%)")

        if self.findings:
            print(f"\nFindings: {len(self.findings)} issues found")
            for finding in self.findings[:5]:  # Show first 5
                print(f"  - [{finding['type']}] {finding['details'][:80]}")

        print("=" * 60)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="TRANSFORM-006 Encoding Detection and Conversion Tests"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("results"),
        help="Output directory for results",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    runner = EncodingTestRunner(verbose=args.verbose, output_dir=args.output)
    await runner.run_all_tests()
    runner.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
