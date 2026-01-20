#!/usr/bin/env python3
"""
GUARD-007 Adversarial Input Fuzzing Test Runner

This script executes the comprehensive adversarial input fuzzing test suite
for Stageflow pipelines and generates detailed reports.

Usage:
    python run_guard007_tests.py [--output DIR] [--verbose] [--category CATEGORY]

Categories:
    baseline  - Happy path and edge case tests
    security  - Security-focused pipeline tests
    adversarial - All adversarial input tests
    dos       - Denial of service resilience tests
    all       - Run all test categories (default)
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines.guard007_pipelines import (
    AdversarialPipelineBuilder,
    AdversarialTestRunner,
    run_adversarial_tests,
)
from mocks.adversarial_fuzzing_data import AdversarialInputFuzzer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run_category_tests(
    category: str,
    output_dir: Optional[str],
    verbose: bool,
) -> dict:
    """Run tests for a specific category."""

    builder = AdversarialPipelineBuilder()
    fuzzer = AdversarialInputFuzzer()

    # Select pipeline and test cases based on category
    if category == "baseline":
        pipeline = builder.build_baseline_pipeline()
        # Use low-severity and edge cases
        test_cases = (
            fuzzer.get_cases_by_severity("low")[:10] +
            [tc for tc in fuzzer.get_all_cases() if "edge" in tc.name][:5]
        )
    elif category == "security":
        pipeline = builder.build_security_pipeline()
        test_cases = fuzzer.get_injection_cases()[:15]
    elif category == "adversarial":
        pipeline = builder.build_adversarial_pipeline()
        test_cases = fuzzer.get_all_cases()
    elif category == "dos":
        pipeline = builder.build_baseline_pipeline()
        test_cases = fuzzer.get_dos_cases()
    else:
        raise ValueError(f"Unknown category: {category}")

    runner = AdversarialTestRunner(pipeline)

    logger.info(f"Running {category} tests: {len(test_cases)} test cases")

    results = await runner.run_test_suite(test_cases, verbose)

    summary = runner.generate_summary()

    if output_dir:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = output_path / f"guard007_{category}_results_{timestamp}.json"

        output_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "category": category,
            "test_count": len(results),
            "summary": summary,
            "detailed_results": [r.__dict__ for r in results],
        }

        with open(results_file, "w") as f:
            json.dump(output_data, f, indent=2, default=str)

        logger.info(f"Results saved to: {results_file}")

    return summary


async def main():
    parser = argparse.ArgumentParser(
        description="GUARD-007 Adversarial Input Fuzzing Test Runner"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output directory for test results",
        default="results"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--category", "-c",
        choices=["baseline", "security", "adversarial", "dos", "all"],
        default="all",
        help="Test category to run (default: all)"
    )
    parser.add_argument(
        "--list-tests",
        action="store_true",
        help="List available test cases and exit"
    )

    args = parser.parse_args()

    if args.list_tests:
        fuzzer = AdversarialInputFuzzer()
        cases = fuzzer.get_all_cases()

        print(f"\n{'='*60}")
        print("GUARD-007 Adversarial Input Fuzzing - Test Cases")
        print(f"{'='*60}\n")

        for category in AttackCategory:
            cat_cases = fuzzer.get_cases_by_category(category)
            print(f"\n[{category.value.upper()}] ({len(cat_cases)} tests)")
            print("-" * 40)

            for tc in cat_cases[:5]:  # Show first 5 per category
                severity_indicator = {
                    "critical": "[CRITICAL]",
                    "high": "[HIGH]",
                    "medium": "[MEDIUM]",
                    "low": "[LOW]",
                }.get(tc.severity, "[UNKNOWN]")

                print(f"  {severity_indicator} {tc.name}")
                print(f"       {tc.description[:60]}...")

            if len(cat_cases) > 5:
                print(f"  ... and {len(cat_cases) - 5} more")

        print(f"\n{'='*60}")
        print(f"Total: {len(cases)} test cases")
        print(f"{'='*60}\n")

        return

    print(f"\n{'='*60}")
    print("GUARD-007: Adversarial Input Fuzzing Test Suite")
    print(f"{'='*60}\n")

    if args.category == "all":
        results = await run_adversarial_tests(args.output, args.verbose)
    else:
        results = await run_category_tests(args.category, args.output, args.verbose)

    # Print summary
    print(f"\n{'='*60}")
    print("TEST EXECUTION COMPLETE")
    print(f"{'='*60}\n")

    if isinstance(results, dict):
        if "categories" in results:
            # Full results
            for cat, summary in results["categories"].items():
                print(f"[{cat.upper()}]")
                print(f"  Tests: {summary['total_tests']}")
                print(f"  Passed: {summary['passed']}")
                print(f"  Failed: {summary['failed']}")
                print(f"  Pass Rate: {summary['pass_rate']:.1%}")
                print()

            print(f"TOTAL: {results['total_tests']} tests")
            print(f"Passed: {results['passed']}")
            print(f"Failed: {results['failed']}")
        else:
            print(json.dumps(results, indent=2))

    print(f"\n{'='*60}")


if __name__ == "__main__":
    from mocks.adversarial_fuzzing_data import AttackCategory
    asyncio.run(main())
