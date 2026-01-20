"""
Test Runner for Retrieval Latency Testing

This script executes all test pipelines and generates comprehensive results.
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from mocks.services.test_data import generate_test_queries, generate_edge_case_queries
from pipelines.baseline import BaselinePipeline
from pipelines.stress import StressPipeline
from pipelines.chaos import ChaosPipeline
from pipelines.recovery import RecoveryPipeline

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestRunner:
    """
    Comprehensive test runner for all retrieval latency tests.
    """
    
    def __init__(self, results_dir: str = "results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir = self.results_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.metrics_dir = self.results_dir / "metrics"
        self.metrics_dir.mkdir(parents=True, exist_ok=True)
        
        self.start_time = None
        self.all_results = {}
    
    def _setup_logging(self, test_name: str):
        """Setup logging for a specific test."""
        log_file = self.logs_dir / f"{test_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        logger = logging.getLogger(test_name)
        logger.handlers = []
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return log_file
    
    async def _run_baseline_test_async(self) -> Dict[str, Any]:
        """Run baseline happy path test."""
        log_file = self._setup_logging("baseline")
        logger.info("=" * 60)
        logger.info("BASELINE TEST: Happy path retrieval")
        logger.info("=" * 60)
        
        pipeline = BaselinePipeline(str(self.results_dir))
        queries = generate_test_queries(100)
        
        start = time.perf_counter()
        results = await pipeline.run_test(queries)
        elapsed = time.perf_counter() - start
        
        results["execution_time_seconds"] = elapsed
        results["log_file"] = str(log_file)
        
        logger.info(f"Baseline test completed in {elapsed:.2f}s")
        logger.info(f"  Success rate: {results['success_rate']*100:.1f}%")
        logger.info(f"  Mean latency: {results['latencies']['mean_ms']:.2f}ms")
        logger.info(f"  P95 latency: {results['latencies']['p95_ms']:.2f}ms")
        
        return results
    
    async def _run_stress_test_async(self) -> Dict[str, Any]:
        """Run stress tests with concurrency levels."""
        log_file = self._setup_logging("stress")
        logger.info("=" * 60)
        logger.info("STRESS TEST: Concurrent retrieval under load")
        logger.info("=" * 60)
        
        pipeline = StressPipeline(str(self.results_dir))
        queries = generate_test_queries(100)
        
        start = time.perf_counter()
        
        ramp_results = await pipeline.run_concurrency_ramp_test(
            queries,
            concurrency_levels=[1, 5, 10, 25, 50],
        )
        
        sustained_results = await pipeline.run_sustained_load_test(
            queries,
            concurrency=50,
            duration_seconds=30,
        )
        
        elapsed = time.perf_counter() - start
        
        results = {
            "execution_time_seconds": elapsed,
            "log_file": str(log_file),
            "concurrency_ramp": ramp_results,
            "sustained_load": sustained_results,
        }
        
        pipeline.save_results(results)
        
        logger.info(f"Stress test completed in {elapsed:.2f}s")
        logger.info("Concurrency ramp results:")
        for r in ramp_results:
            logger.info(f"  {r['concurrency']} concurrent: "
                       f"P95={r['latencies']['p95_ms']:.1f}ms, "
                       f"success={r['success_rate']*100:.1f}%")
        
        return results
    
    async def _run_chaos_test_async(self) -> Dict[str, Any]:
        """Run chaos engineering tests with failure injection."""
        log_file = self._setup_logging("chaos")
        logger.info("=" * 60)
        logger.info("CHAOS TEST: Failure injection and edge cases")
        logger.info("=" * 60)
        
        pipeline = ChaosPipeline(str(self.results_dir))
        queries = generate_test_queries(100)
        
        start = time.perf_counter()
        results = await pipeline.run_all_tests(queries)
        elapsed = time.perf_counter() - start
        
        results["execution_time_seconds"] = elapsed
        results["log_file"] = str(log_file)
        
        pipeline.save_results(results)
        
        logger.info(f"Chaos test completed in {elapsed:.2f}s")
        logger.info(f"  Timeout test: {results['timeout_test']['timeouts']} timeouts")
        logger.info(f"  Error injection: {results['error_injection_test']['errors']} errors")
        logger.info(f"  Fallback test: {results['fallback_test']['fallbacks']} fallbacks used")
        
        return results
    
    async def _run_recovery_test_async(self) -> Dict[str, Any]:
        """Run recovery tests after failures."""
        log_file = self._setup_logging("recovery")
        logger.info("=" * 60)
        logger.info("RECOVERY TEST: Post-failure behavior")
        logger.info("=" * 60)
        
        pipeline = RecoveryPipeline(str(self.results_dir))
        queries = generate_test_queries(100)
        
        start = time.perf_counter()
        results = await pipeline.run_all_tests(queries)
        elapsed = time.perf_counter() - start
        
        results["execution_time_seconds"] = elapsed
        results["log_file"] = str(log_file)
        
        pipeline.save_results(results)
        
        logger.info(f"Recovery test completed in {elapsed:.2f}s")
        recovery_metrics = results.get("failure_recovery_test", {}).get("recovery_metrics", {})
        logger.info(f"  Recovery success rate: {recovery_metrics.get('success_rate_in_recovery', 0)*100:.1f}%")
        
        return results
    
    async def _run_edge_case_test_async(self) -> Dict[str, Any]:
        """Run edge case tests."""
        log_file = self._setup_logging("edge_cases")
        logger.info("=" * 60)
        logger.info("EDGE CASE TEST: Boundary conditions")
        logger.info("=" * 60)
        
        queries = generate_edge_case_queries()
        
        pipeline = BaselinePipeline(str(self.results_dir))
        
        start = time.perf_counter()
        results = await pipeline.run_test(queries)
        elapsed = time.perf_counter() - start
        
        results["execution_time_seconds"] = elapsed
        results["log_file"] = str(log_file)
        results["test_type"] = "edge_cases"
        
        pipeline.save_results("edge_case_results.json")
        
        logger.info(f"Edge case test completed in {elapsed:.2f}s")
        logger.info(f"  Success rate: {results['success_rate']*100:.1f}%")
        
        return results
    
    def generate_summary_report(self) -> Dict[str, Any]:
        """Generate summary report of all test results."""
        
        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_duration_seconds": time.perf_counter() - self.start_time,
            "tests_run": [],
            "overall_metrics": {},
        }
        
        test_files = {
            "baseline": "baseline_results.json",
            "stress": "stress_results.json",
            "chaos": "chaos_results.json",
            "recovery": "recovery_results.json",
            "edge_cases": "edge_case_results.json",
        }
        
        all_latencies = []
        all_success_rates = []
        
        for test_name, filename in test_files.items():
            filepath = self.results_dir / filename
            if filepath.exists():
                with open(filepath) as f:
                    test_results = json.load(f)
                    summary["tests_run"].append(test_name)
                    
                    if isinstance(test_results, list) and len(test_results) > 0:
                        test_results = test_results[-1]
                    
                    if "latencies" in test_results:
                        all_latencies.append(test_results["latencies"])
                    if "success_rate" in test_results:
                        all_success_rates.append(test_results["success_rate"])
        
        if all_latencies:
            p50_values = [l.get("p50_ms", 0) for l in all_latencies]
            p95_values = [l.get("p95_ms", 0) for l in all_latencies]
            summary["overall_metrics"] = {
                "avg_p50_latency_ms": sum(p50_values) / len(p50_values),
                "avg_p95_latency_ms": sum(p95_values) / len(p95_values),
                "avg_success_rate": sum(all_success_rates) / len(all_success_rates) if all_success_rates else 0,
            }
        
        summary_filepath = self.results_dir / "summary_report.json"
        with open(summary_filepath, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        
        logger.info(f"Summary report saved to {summary_filepath}")
        
        return summary
    
    async def run_all_tests_async(self) -> Dict[str, Any]:
        """Run all test suites asynchronously."""
        self.start_time = time.perf_counter()
        
        logger.info("=" * 60)
        logger.info("RETRIEVAL LATENCY TEST SUITE")
        logger.info(f"Start time: {datetime.now(timezone.utc).isoformat()}")
        logger.info("=" * 60)
        
        try:
            self.all_results["baseline"] = await self._run_baseline_test_async()
            self.all_results["stress"] = await self._run_stress_test_async()
            self.all_results["chaos"] = await self._run_chaos_test_async()
            self.all_results["recovery"] = await self._run_recovery_test_async()
            self.all_results["edge_cases"] = await self._run_edge_case_test_async()
            
        except Exception as e:
            logger.exception(f"Test execution error: {e}")
            self.all_results["error"] = str(e)
        
        total_time = time.perf_counter() - self.start_time
        
        logger.info("=" * 60)
        logger.info("TEST SUITE COMPLETED")
        logger.info(f"Total duration: {total_time:.2f}s")
        logger.info("=" * 60)
        
        summary = self.generate_summary_report()
        
        return self.all_results


async def run_tests():
    """Run all tests."""
    runner = TestRunner()
    return await runner.run_all_tests_async()


def main():
    """Main entry point."""
    results = asyncio.run(run_tests())
    
    print("\n" + "=" * 60)
    print("FINAL RESULTS SUMMARY")
    print("=" * 60)
    
    for test_name, test_results in results.items():
        if isinstance(test_results, dict) and "success_rate" in test_results:
            print(f"\n{test_name.upper()}:")
            print(f"  Success rate: {test_results['success_rate']*100:.1f}%")
            print(f"  Mean latency: {test_results.get('latencies', {}).get('mean_ms', 0):.2f}ms")
            print(f"  P95 latency: {test_results.get('latencies', {}).get('p95_ms', 0):.2f}ms")
    
    return results


if __name__ == "__main__":
    main()
