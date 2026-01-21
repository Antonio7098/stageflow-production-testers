#!/usr/bin/env python3
"""
Rate Limit Test Runner and Log Analyzer

Comprehensive test execution and log analysis for Stageflow rate limit handling tests.
Part of WORK-004: Rate limit handling (429 responses) stress-testing.

Usage:
    python run_rate_limit_tests.py --scenario <scenario_name>
    python run_rate_limit_tests.py --all
    python run_rate_limit_tests.py --analyze-logs
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import random

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow import (
    Pipeline, Stage, StageKind, StageOutput, StageContext,
    PipelineContext, PipelineTimer, create_stage_context,
    LoggingInterceptor, MetricsInterceptor
)
from stageflow.context import ContextSnapshot, RunIdentity

from mocks.services.rate_limit_mocks import (
    MockRateLimitedLLMService, RateLimitError, RateLimitConfig,
    RateLimitAlgorithm, create_rate_limited_service
)
from mocks.data.rate_limit_test_data import (
    RateLimitTestDataGenerator, RateLimitTestCase, RateLimitScenario
)
from pipelines.rate_limit_pipelines import (
    RateLimitedLLMStage, RateLimitDetectorStage,
    MetricsCollectionStage, RetryStage, RateLimitPipelineBuilder
)


# =============================================================================
# Configuration and Logging
# =============================================================================

@dataclass
class TestConfig:
    """Configuration for test execution."""
    log_dir: Path = Path("results/logs")
    metrics_dir: Path = Path("results/metrics")
    trace_dir: Path = Path("results/traces")
    log_level: int = logging.DEBUG
    capture_logs: bool = True
    capture_metrics: bool = True
    capture_traces: bool = True


class LogCaptureHandler(logging.Handler):
    """Custom handler to capture logs for analysis."""
    
    def __init__(self, log_dir: Path):
        super().__init__()
        self.log_dir = log_dir
        self.records: list[logging.LogRecord] = []
        self.run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    def emit(self, record: logging.LogRecord):
        self.records.append(record)
    
    def save_logs(self, test_name: str):
        """Save captured logs to file."""
        log_file = self.log_dir / f"{test_name}_{self.run_timestamp}.log"
        
        with open(log_file, "w") as f:
            f.write(f"# Test: {test_name}\n")
            f.write(f"# Timestamp: {self.run_timestamp}\n")
            f.write(f"# Total records: {len(self.records)}\n")
            f.write("\n" + "=" * 60 + "\n\n")
            
            for record in self.records:
                timestamp = datetime.fromtimestamp(record.created).isoformat()
                f.write(f"[{timestamp}] {record.levelname:8} | {record.name:20} | {record.getMessage()}\n")
        
        return log_file
    
    def get_stats(self) -> dict[str, int]:
        """Get log statistics."""
        stats = {
            "total": len(self.records),
            "debug": 0,
            "info": 0,
            "warning": 0,
            "error": 0,
            "critical": 0
        }
        for record in self.records:
            level_name = record.levelname.lower()
            if level_name in stats:
                stats[level_name] += 1
        return stats


# =============================================================================
# Test Executors
# =============================================================================

class RateLimitTestExecutor:
    """Executes rate limit tests with comprehensive logging."""
    
    def __init__(self, config: TestConfig):
        self.config = config
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        self.config.metrics_dir.mkdir(parents=True, exist_ok=True)
        self.config.trace_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        self.log_handler = LogCaptureHandler(self.config.log_dir)
        self.logger = self._setup_logging()
        
        # Test state
        self.test_history: list[dict] = []
        self.metrics_history: list[dict] = []
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging with capture."""
        logger = logging.getLogger("rate_limit_test")
        logger.setLevel(self.config.log_level)
        
        # Clear existing handlers
        logger.handlers.clear()
        
        # Add capture handler
        if self.config.capture_logs:
            logger.addHandler(self.log_handler)
        
        # Add console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.config.log_level)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        return logger
    
    async def execute_test_case(
        self,
        test_case: RateLimitTestCase,
        service: MockRateLimitedLLMService
    ) -> dict[str, Any]:
        """Execute a single test case."""
        test_name = f"{test_case.scenario}_{test_case.name}"
        self.logger.info(f"Starting test: {test_name}")
        self.logger.info(f"  RPM: {test_case.rpm}, Burst: {test_case.burst}, Requests: {test_case.request_count}")
        
        start_time = time.time()
        
        # Create test service
        test_service = create_rate_limited_service(
            rpm=test_case.rpm,
            burst=test_case.burst
        )
        
        results = []
        for i in range(test_case.request_count):
            try:
                result = await self._single_request_test(test_service, i + 1)
                results.append(result)
            except Exception as e:
                self.logger.error(f"Request {i + 1} failed: {e}")
                results.append({
                    "request": i + 1,
                    "success": False,
                    "error": str(e)
                })
        
        execution_time = time.time() - start_time
        
        # Calculate metrics
        success_count = sum(1 for r in results if r.get("success", False))
        rate_limited_count = sum(
            1 for r in results
            if "rate limited" in r.get("error", "").lower()
        )
        
        test_result = {
            "test_name": test_name,
            "scenario": getattr(test_case, 'scenario', 'unknown'),
            "description": test_case.description,
            "expected_behavior": test_case.expected_behavior,
            "severity": test_case.severity,
            "config": {
                "rpm": test_case.rpm,
                "burst": test_case.burst,
                "request_count": test_case.request_count
            },
            "results": {
                "total_requests": test_case.request_count,
                "successes": success_count,
                "rate_limited": rate_limited_count,
                "success_rate": success_count / test_case.request_count if test_case.request_count > 0 else 0,
                "execution_time_seconds": execution_time,
                "requests_per_second": test_case.request_count / execution_time if execution_time > 0 else 0
            },
            "request_details": results,
            "timestamp": datetime.now().isoformat()
        }
        
        # Save logs
        if self.config.capture_logs:
            log_file = self.log_handler.save_logs(test_name)
            self.logger.info(f"Logs saved to: {log_file}")
        
        self.logger.info(f"Test completed: {test_name}")
        self.logger.info(f"  Success rate: {test_result['results']['success_rate']:.2%}")
        self.logger.info(f"  Rate limited: {rate_limited_count}/{test_case.request_count}")
        
        return test_result
    
    async def _single_request_test(
        self,
        service: MockRateLimitedLLMService,
        request_num: int
    ) -> dict[str, Any]:
        """Execute a single request test."""
        start_time = time.time()
        
        try:
            # Make LLM call with retry
            response = await service.chat_with_retry(
                messages=[{"role": "user", "content": f"Test message {request_num}"}],
                max_retries=3
            )
            
            latency_ms = (time.time() - start_time) * 1000
            
            return {
                "request": request_num,
                "success": True,
                "latency_ms": latency_ms,
                "content_length": len(response.content)
            }
            
        except RateLimitError as e:
            latency_ms = (time.time() - start_time) * 1000
            
            self.logger.warning(f"Request {request_num} rate limited: retry_after={e.retry_after_ms}ms")
            
            return {
                "request": request_num,
                "success": False,
                "error": f"Rate limited: {e.message}",
                "retry_after_ms": e.retry_after_ms,
                "latency_ms": latency_ms
            }
        
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            
            self.logger.error(f"Request {request_num} error: {e}")
            
            return {
                "request": request_num,
                "success": False,
                "error": str(e),
                "latency_ms": latency_ms
            }
    
    async def execute_scenario(
        self,
        scenario: RateLimitScenario
    ) -> dict[str, Any]:
        """Execute all test cases in a scenario."""
        self.logger.info(f"=" * 60)
        self.logger.info(f"Executing scenario: {scenario.name}")
        self.logger.info(f"Description: {scenario.description}")
        self.logger.info(f"=" * 60)
        
        service = create_rate_limited_service(rpm=60, burst=10)
        
        scenario_result = {
            "scenario_name": scenario.name,
            "description": scenario.description,
            "test_cases": [],
            "summary": {}
        }
        
        total_requests = 0
        total_successes = 0
        total_rate_limited = 0
        tests_passed = 0
        tests_failed = 0
        
        for test_case in scenario.test_cases:
            # Add scenario to test_case for tracking
            test_case.scenario = scenario.name
            
            result = await self.execute_test_case(test_case, service)
            scenario_result["test_cases"].append(result)
            
            # Update summary
            total_requests += result["results"]["total_requests"]
            total_successes += result["results"]["successes"]
            total_rate_limited += result["results"]["rate_limited"]
            
            if result["results"]["success_rate"] >= 0.9:
                tests_passed += 1
            else:
                tests_failed += 1
        
        scenario_result["summary"] = {
            "total_requests": total_requests,
            "total_successes": total_successes,
            "total_rate_limited": total_rate_limited,
            "tests_passed": tests_passed,
            "tests_failed": tests_failed,
            "pass_rate": tests_passed / len(scenario.test_cases) if scenario.test_cases else 0,
            "overall_success_rate": total_successes / total_requests if total_requests > 0 else 0
        }
        
        self.logger.info(f"Scenario completed: {scenario.name}")
        self.logger.info(f"  Tests: {tests_passed}/{len(scenario.test_cases)} passed")
        self.logger.info(f"  Success rate: {scenario_result['summary']['overall_success_rate']:.2%}")
        
        return scenario_result
    
    async def execute_all(self) -> dict[str, Any]:
        """Execute all test scenarios."""
        self.logger.info("=" * 60)
        self.logger.info("Starting Full Rate Limit Test Suite")
        self.logger.info("=" * 60)
        
        generator = RateLimitTestDataGenerator(seed=42)
        
        full_result = {
            "test_run_timestamp": datetime.now().isoformat(),
            "config": {
                "log_dir": str(self.config.log_dir),
                "capture_logs": self.config.capture_logs,
                "capture_metrics": self.config.capture_metrics
            },
            "scenarios": [],
            "overall_summary": {}
        }
        
        total_tests = 0
        total_passed = 0
        total_failed = 0
        
        for scenario in generator.generate_all_scenarios():
            scenario_result = await self.execute_scenario(scenario)
            full_result["scenarios"].append(scenario_result)
            
            total_tests += len(scenario.test_cases)
            total_passed += scenario_result["summary"]["tests_passed"]
            total_failed += scenario_result["summary"]["tests_failed"]
        
        full_result["overall_summary"] = {
            "total_test_cases": total_tests,
            "passed": total_passed,
            "failed": total_failed,
            "pass_rate": total_passed / total_tests if total_tests > 0 else 0
        }
        
        # Save comprehensive results
        self._save_comprehensive_results(full_result)
        
        self.logger.info("=" * 60)
        self.logger.info("Test Suite Completed")
        self.logger.info("=" * 60)
        self.logger.info(f"Total tests: {total_tests}")
        self.logger.info(f"Passed: {total_passed}")
        self.logger.info(f"Failed: {total_failed}")
        self.logger.info(f"Pass rate: {full_result['overall_summary']['pass_rate']:.2%}")
        
        return full_result
    
    def _save_comprehensive_results(self, results: dict[str, Any]):
        """Save comprehensive test results."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = self.config.metrics_dir / f"comprehensive_results_{timestamp}.json"
        
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2, default=str)
        
        self.logger.info(f"Results saved to: {results_file}")


# =============================================================================
# Log Analyzer
# =============================================================================

class LogAnalyzer:
    """Analyzes test logs for patterns and issues."""
    
    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
    
    def analyze_logs(self, log_pattern: str = "*.log") -> dict[str, Any]:
        """Analyze logs for patterns and issues."""
        log_files = list(self.log_dir.glob(log_pattern))
        
        analysis = {
            "analyzed_files": len(log_files),
            "patterns_found": [],
            "errors": [],
            "warnings": [],
            "statistics": {}
        }
        
        all_records = []
        for log_file in log_files:
            with open(log_file, "r") as f:
                lines = f.readlines()
                
            # Parse log lines
            for line in lines:
                if "[ERROR]" in line:
                    analysis["errors"].append({
                        "file": log_file.name,
                        "message": line.strip()
                    })
                elif "[WARNING]" in line:
                    analysis["warnings"].append({
                        "file": log_file.name,
                        "message": line.strip()
                    })
        
        # Calculate statistics
        analysis["statistics"] = {
            "total_errors": len(analysis["errors"]),
            "total_warnings": len(analysis["warnings"]),
            "files_analyzed": len(log_files)
        }
        
        return analysis
    
    def generate_report(self, results: dict[str, Any]) -> str:
        """Generate a human-readable report from test results."""
        report = []
        report.append("=" * 60)
        report.append("RATE LIMIT HANDLING TEST REPORT")
        report.append("=" * 60)
        report.append(f"Generated: {results.get('test_run_timestamp', 'N/A')}")
        report.append("")
        
        # Overall summary
        summary = results.get("overall_summary", {})
        report.append("OVERALL SUMMARY")
        report.append("-" * 40)
        report.append(f"Total test cases: {summary.get('total_test_cases', 'N/A')}")
        report.append(f"Passed: {summary.get('passed', 'N/A')}")
        report.append(f"Failed: {summary.get('failed', 'N/A')}")
        report.append(f"Pass rate: {summary.get('pass_rate', 0):.2%}")
        report.append("")
        
        # Per-scenario results
        report.append("SCENARIO RESULTS")
        report.append("-" * 40)
        for scenario in results.get("scenarios", []):
            s_summary = scenario.get("summary", {})
            status = "✓ PASS" if s_summary.get("pass_rate", 0) >= 0.9 else "✗ FAIL"
            report.append(f"{status} {scenario.get('scenario_name', 'Unknown')}")
            report.append(f"    Tests: {s_summary.get('tests_passed', 0)}/{s_summary.get('tests_passed', 0) + s_summary.get('tests_failed', 0)}")
            report.append(f"    Success rate: {s_summary.get('overall_success_rate', 0):.2%}")
        
        return "\n".join(report)


# =============================================================================
# Main Entry Point
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(
        description="Stageflow Rate Limit Test Runner"
    )
    parser.add_argument(
        "--scenario",
        type=str,
        help="Run specific scenario (e.g., 'happy_path', 'rate_limit_edge_cases')"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all scenarios"
    )
    parser.add_argument(
        "--analyze-logs",
        action="store_true",
        help="Analyze existing logs"
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default="results/logs",
        help="Log directory"
    )
    
    args = parser.parse_args()
    
    # Setup configuration
    config = TestConfig(
        log_dir=Path(args.log_dir),
        metrics_dir=Path("results/metrics"),
        trace_dir=Path("results/traces")
    )
    
    executor = RateLimitTestExecutor(config)
    
    if args.analyze_logs:
        # Run log analysis
        analyzer = LogAnalyzer(config.log_dir)
        analysis = analyzer.analyze_logs()
        print(json.dumps(analysis, indent=2))
        
        if args.all or args.scenario:
            results = await executor.execute_all()
            report = analyzer.generate_report(results)
            print("\n" + report)
    
    elif args.scenario:
        # Run specific scenario
        generator = RateLimitTestDataGenerator(seed=42)
        try:
            scenario = generator.generate_scenario(args.scenario)
            result = await executor.execute_scenario(scenario)
            print(json.dumps(result, indent=2, default=str))
        except ValueError as e:
            print(f"Error: {e}")
            print(f"Available scenarios: {list(generator.SCENARIOS.keys())}")
    
    elif args.all:
        # Run all scenarios
        results = await executor.execute_all()
        print(json.dumps(results, indent=2, default=str))
    
    else:
        # Default: run all
        results = await executor.execute_all()
        print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
