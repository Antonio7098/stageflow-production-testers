"""
ENRICH-010 Test Runner: Metadata Filtering Accuracy

This script runs all ENRICH-010 tests and collects results for analysis.
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))

import enrich010_pipelines
import enrich010_chaos

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class TestRunner:
    """Test runner for ENRICH-010 metadata filtering tests."""

    def __init__(self, output_dir: str = "results/enrich010"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "logs").mkdir(exist_ok=True)
        self.test_results = {
            "baseline": [],
            "edge_cases": [],
            "complex_filters": [],
            "chaos": [],
        }
        self.findings = []

    async def run_baseline_tests(self) -> Dict[str, Any]:
        """Run baseline operator tests."""
        logger.info("=" * 60)
        logger.info("Running Baseline Tests")
        logger.info("=" * 60)

        result_file = str(self.output_dir / "baseline_results.json")
        results = await enrich010_pipelines.run_baseline_tests(result_file)

        self.test_results["baseline"] = results.get("results", [])

        return results

    async def run_edge_case_tests(self) -> Dict[str, Any]:
        """Run edge case tests."""
        logger.info("=" * 60)
        logger.info("Running Edge Case Tests")
        logger.info("=" * 60)

        result_file = str(self.output_dir / "edge_case_results.json")
        results = await enrich010_pipelines.run_edge_case_tests(result_file)

        self.test_results["edge_cases"] = results.get("results", [])

        return results

    async def run_complex_filter_tests(self) -> Dict[str, Any]:
        """Run complex filter tests."""
        logger.info("=" * 60)
        logger.info("Running Complex Filter Tests")
        logger.info("=" * 60)

        result_file = str(self.output_dir / "complex_filter_results.json")
        results = await enrich010_pipelines.run_complex_filter_tests(result_file)

        self.test_results["complex_filters"] = results.get("results", [])

        return results

    async def run_chaos_tests(self) -> Dict[str, Any]:
        """Run chaos tests."""
        logger.info("=" * 60)
        logger.info("Running Chaos Tests")
        logger.info("=" * 60)

        results = await enrich010_chaos.run_all_chaos_tests(str(self.output_dir))

        self.test_results["chaos"] = results.get("results", [])

        return results

    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all ENRICH-010 tests."""
        logger.info("=" * 60)
        logger.info("ENRICH-010 Full Test Suite")
        logger.info("=" * 60)
        logger.info(f"Output directory: {self.output_dir}")
        logger.info(f"Start time: {datetime.now().isoformat()}")

        start_time = time.perf_counter()

        # Run all test suites
        baseline_results = await self.run_baseline_tests()
        edge_case_results = await self.run_edge_case_tests()
        complex_filter_results = await self.run_complex_filter_tests()
        chaos_results = await self.run_chaos_tests()

        execution_time_ms = (time.perf_counter() - start_time) * 1000

        # Generate summary
        summary = self._generate_summary()

        # Save combined results
        combined_results = {
            "timestamp": datetime.now().isoformat(),
            "execution_time_ms": execution_time_ms,
            "summary": summary,
            "detailed_results": self.test_results,
        }

        result_file = self.output_dir / "combined_results.json"
        with open(result_file, "w") as f:
            json.dump(combined_results, f, indent=2)

        logger.info("\n" + "=" * 60)
        logger.info("Test Suite Complete")
        logger.info("=" * 60)
        logger.info(f"Total execution time: {execution_time_ms:.2f}ms")
        logger.info(f"Results saved to: {result_file}")

        return combined_results

    def _generate_summary(self) -> Dict[str, Any]:
        """Generate test summary."""
        total_passed = 0
        total_failed = 0
        total_silent_failures = 0

        for category, results in self.test_results.items():
            for result in results:
                if result.get("success", False):
                    total_passed += 1
                else:
                    total_failed += 1

                if result.get("silent_failure", False):
                    total_silent_failures += 1

        return {
            "total_tests": total_passed + total_failed,
            "passed": total_passed,
            "failed": total_failed,
            "pass_rate": total_passed / max(total_passed + total_failed, 1),
            "silent_failures": total_silent_failures,
        }

    def analyze_results(self) -> Dict[str, Any]:
        """Analyze test results for patterns and findings."""
        analysis = {
            "operator_performance": {},
            "edge_case_failures": [],
            "silent_failure_patterns": [],
            "performance_metrics": {},
        }

        # Analyze baseline results
        for result in self.test_results.get("baseline", []):
            if result.get("success"):
                op = result.get("filter_operator", "unknown")
                if op not in analysis["operator_performance"]:
                    analysis["operator_performance"][op] = {
                        "count": 0,
                        "avg_time_ms": 0,
                    }
                analysis["operator_performance"][op]["count"] += 1
                analysis["operator_performance"][op]["avg_time_ms"] = (
                    analysis["operator_performance"][op]["avg_time_ms"] * 0.9
                    + result.get("execution_time_ms", 0) * 0.1
                )

        # Analyze silent failures
        for category, results in self.test_results.items():
            for result in results:
                if result.get("silent_failure"):
                    analysis["silent_failure_patterns"].append({
                        "test_name": result.get("test_name"),
                        "category": category,
                        "documents_filtered": result.get("documents_filtered", 0),
                    })

        # Analyze edge case failures
        for result in self.test_results.get("edge_cases", []):
            if not result.get("success"):
                analysis["edge_case_failures"].append({
                    "test_name": result.get("test_name"),
                    "error": result.get("error"),
                })

        return analysis


async def main():
    """Main entry point."""
    runner = TestRunner()

    # Run all tests
    results = await runner.run_all_tests()

    # Analyze results
    analysis = runner.analyze_results()

    # Save analysis
    analysis_file = runner.output_dir / "analysis.json"
    with open(analysis_file, "w") as f:
        json.dump(analysis, f, indent=2)

    logger.info(f"\nAnalysis saved to: {analysis_file}")

    # Print summary
    summary = results["summary"]
    logger.info("\n" + "=" * 60)
    logger.info("FINAL SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total Tests: {summary['total_tests']}")
    logger.info(f"Passed: {summary['passed']}")
    logger.info(f"Failed: {summary['failed']}")
    logger.info(f"Pass Rate: {summary['pass_rate']:.2%}")
    logger.info(f"Silent Failures: {summary['silent_failures']}")

    return results


if __name__ == "__main__":
    asyncio.run(main())
