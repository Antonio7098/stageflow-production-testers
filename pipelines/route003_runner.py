#!/usr/bin/env python3
"""
ROUTE-003 Test Runner

Orchestrates all ROUTE-003 tests and generates comprehensive results.
"""

import asyncio
import json
import logging
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines.route003_baseline import run_baseline_tests, run_concurrent_baseline_test
from pipelines.route003_stress import run_all_stress_tests, run_scalability_test, run_priority_stress_test
from pipelines.route003_chaos import run_all_chaos_tests, run_edge_case_tests, run_race_condition_test
from pipelines.route003_recovery import run_all_recovery_tests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ROUTE003TestRunner:
    """Test runner for ROUTE-003: Dynamic routing under load."""

    def __init__(self, results_dir: str = "results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.results: Dict[str, Any] = {}
        self.start_time = datetime.now()

    def _save_results(self, filename: str, data: Any):
        """Save results to file."""
        filepath = self.results_dir / filename
        with open(filepath, "w") as f:
            if isinstance(data, str):
                f.write(data)
            else:
                json.dump(data, f, indent=2, default=str)
        logger.info(f"Saved results to {filepath}")

    async def run_baseline_phase(self) -> Dict[str, Any]:
        """Run baseline tests."""
        logger.info("=" * 60)
        logger.info("PHASE: Baseline Testing")
        logger.info("=" * 60)

        baseline_results = await run_baseline_tests()
        concurrent_results = await run_concurrent_baseline_test(num_concurrent=10)

        self._save_results("baseline_results.json", {
            "baseline": baseline_results,
            "concurrent": concurrent_results,
        })

        return {
            "baseline": baseline_results,
            "concurrent": concurrent_results,
        }

    async def run_stress_phase(self) -> Dict[str, Any]:
        """Run stress tests."""
        logger.info("=" * 60)
        logger.info("PHASE: Stress Testing")
        logger.info("=" * 60)

        stress_results = await run_all_stress_tests()
        scalability_results = await run_scalability_test()
        priority_results = await run_priority_stress_test()

        self._save_results("stress_results.json", {
            "load_level_tests": stress_results,
            "scalability": scalability_results,
            "priority_handling": priority_results,
        })

        return {
            "stress": stress_results,
            "scalability": scalability_results,
            "priority": priority_results,
        }

    async def run_chaos_phase(self) -> Dict[str, Any]:
        """Run chaos tests."""
        logger.info("=" * 60)
        logger.info("PHASE: Chaos Testing")
        logger.info("=" * 60)

        chaos_results = await run_all_chaos_tests()
        edge_results = await run_edge_case_tests()
        race_results = await run_race_condition_test()

        self._save_results("chaos_results.json", {
            "chaos_tests": chaos_results,
            "edge_cases": edge_results,
            "race_conditions": race_results,
        })

        return {
            "chaos": chaos_results,
            "edge_cases": edge_results,
            "race_conditions": race_results,
        }

    async def run_recovery_phase(self) -> Dict[str, Any]:
        """Run recovery tests."""
        logger.info("=" * 60)
        logger.info("PHASE: Recovery Testing")
        logger.info("=" * 60)

        recovery_results = await run_all_recovery_tests()

        self._save_results("recovery_results.json", recovery_results)

        return recovery_results

    def generate_summary(self) -> Dict[str, Any]:
        """Generate test summary."""
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        # Calculate overall metrics
        baseline = self.results.get("baseline", {})
        stress = self.results.get("stress", {})

        baseline_pass_rate = baseline.get("baseline", {}).get("pass_rate", 0)
        concurrent_pass_rate = baseline.get("concurrent", {}).get("pass_rate", 0)

        # Extract key metrics from stress tests
        load_results = stress.get("stress", {}).get("load_level_results", {})

        p95_at_100_concurrent = None
        for level, data in load_results.items():
            if data.get("concurrent_requests") == 100:
                p95_at_100_concurrent = data.get("p95_latency_ms")

        return {
            "test_id": "ROUTE-003",
            "test_name": "Dynamic routing under load",
            "status": "completed",
            "start_time": self.start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "summary": {
                "baseline_pass_rate": baseline_pass_rate,
                "concurrent_pass_rate": concurrent_pass_rate,
                "p95_latency_at_100_concurrent_ms": p95_at_100_concurrent,
                "tests_completed": True,
            },
            "phases_completed": list(self.results.keys()),
        }

    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all test phases."""
        logger.info("=" * 60)
        logger.info("ROUTE-003: Dynamic Routing Under Load - Test Suite")
        logger.info("=" * 60)

        try:
            # Run baseline tests
            self.results["baseline"] = await self.run_baseline_phase()

            # Run stress tests
            self.results["stress"] = await self.run_stress_phase()

            # Run chaos tests
            self.results["chaos"] = await self.run_chaos_phase()

            # Run recovery tests
            self.results["recovery"] = await self.run_recovery_phase()

            # Generate and save summary
            summary = self.generate_summary()
            self._save_results("test_summary.json", summary)

            logger.info("=" * 60)
            logger.info("ALL TESTS COMPLETED")
            logger.info(f"Duration: {summary['duration_seconds']:.2f} seconds")
            logger.info("=" * 60)

            return self.results

        except Exception as e:
            logger.error(f"Test suite failed: {e}")
            raise


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="ROUTE-003 Test Runner")
    parser.add_argument("--results-dir", default="results", help="Results directory")
    parser.add_argument("--phase", choices=["baseline", "stress", "chaos", "recovery", "all"],
                       default="all", help="Test phase to run")
    args = parser.parse_args()

    runner = ROUTE003TestRunner(results_dir=args.results_dir)

    if args.phase == "all":
        results = await runner.run_all_tests()
    elif args.phase == "baseline":
        results = {"baseline": await runner.run_baseline_phase()}
    elif args.phase == "stress":
        results = {"stress": await runner.run_stress_phase()}
    elif args.phase == "chaos":
        results = {"chaos": await runner.run_chaos_phase()}
    elif args.phase == "recovery":
        results = {"recovery": await runner.run_recovery_phase()}

    return results


if __name__ == "__main__":
    results = asyncio.run(main())

    print("\n" + "=" * 60)
    print("ROUTE-003 Test Run Complete")
    print("=" * 60)
    print(f"Results saved to: results/")
    print("=" * 60)
