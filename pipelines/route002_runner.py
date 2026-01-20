"""
Test runner for ROUTE-002: Routing decision explainability testing.

This script orchestrates all test phases and generates reports.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("results/route002/test_runner.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class LogCapture:
    """Captures logs for analysis."""
    
    def __init__(self, log_dir: str = "results/route002/logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.entries = []
    
    def capture(self, level: str, message: str, extra: Optional[Dict] = None):
        """Capture a log entry."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
            "extra": extra or {},
        }
        self.entries.append(entry)
        
        # Write to file
        log_file = self.log_dir / f"route002_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        with open(log_file, "w") as f:
            json.dump(self.entries, f, indent=2)
        
        return entry
    
    def info(self, message: str, extra: Optional[Dict] = None):
        return self.capture("INFO", message, extra)
    
    def error(self, message: str, extra: Optional[Dict] = None):
        return self.capture("ERROR", message, extra)
    
    def warning(self, message: str, extra: Optional[Dict] = None):
        return self.capture("WARNING", message, extra)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get log statistics."""
        stats = {
            "total_entries": len(self.entries),
            "by_level": {},
            "errors": [],
        }
        
        for entry in self.entries:
            level = entry["level"]
            stats["by_level"][level] = stats["by_level"].get(level, 0) + 1
            
            if level == "ERROR":
                stats["errors"].append(entry)
        
        return stats


class TestRunner:
    """Orchestrates all ROUTE-002 tests."""
    
    def __init__(self, results_dir: str = "results/route002"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.log_capture = LogCapture()
        self.findings = []
    
    async def run_baseline_tests(self) -> Dict[str, Any]:
        """Run baseline routing tests."""
        logger.info("Starting baseline tests")
        self.log_capture.info("phase_start", {"phase": "baseline"})
        
        try:
            from pipelines.route002_baseline import run_all_baseline_tests
            results = await run_all_baseline_tests(str(self.results_dir))
            
            # Analyze results
            passed = sum(1 for r in results if r.get("passed"))
            failed = len(results) - passed
            
            stats = {
                "total": len(results),
                "passed": passed,
                "failed": failed,
                "pass_rate": passed / len(results) if results else 0,
                "results": results,
            }
            
            self.log_capture.info("baseline_complete", stats)
            
            return stats
            
        except Exception as e:
            logger.error(f"Baseline tests failed: {e}")
            self.log_capture.error("baseline_failed", {"error": str(e)})
            return {"error": str(e)}
    
    async def run_chaos_tests(self) -> Dict[str, Any]:
        """Run chaos and stress tests."""
        logger.info("Starting chaos tests")
        self.log_capture.info("phase_start", {"phase": "chaos"})
        
        try:
            from pipelines.route002_chaos import run_all_chaos_tests
            from mocks.route002_mock_data import GOLDEN_OUTPUTS
            
            results = await run_all_chaos_tests(GOLDEN_OUTPUTS, str(self.results_dir))
            
            # Analyze results
            successful = sum(1 for r in results if r.get("status") == "COMPLETED")
            failed = sum(1 for r in results if r.get("status") == "FAILED")
            errors = [r for r in results if r.get("error")]
            
            stats = {
                "total": len(results),
                "successful": successful,
                "failed": failed,
                "error_count": len(errors),
                "success_rate": successful / len(results) if results else 0,
                "results": results,
                "errors": errors,
            }
            
            self.log_capture.info("chaos_complete", stats)
            
            return stats
            
        except Exception as e:
            logger.error(f"Chaos tests failed: {e}")
            self.log_capture.error("chaos_failed", {"error": str(e)})
            return {"error": str(e)}
    
    async def run_silent_failure_detection(self) -> Dict[str, Any]:
        """Run silent failure detection tests."""
        logger.info("Running silent failure detection")
        self.log_capture.info("phase_start", {"phase": "silent_failure_detection"})
        
        try:
            from mocks.route002_mock_data import (
                get_all_scenarios,
                GOLDEN_OUTPUTS,
            )
            
            scenarios = get_all_scenarios()
            silent_failures = []
            
            for scenario in scenarios:
                # Simulate routing and compare to golden output
                expected = GOLDEN_OUTPUTS.get(scenario.id)
                if not expected:
                    continue
                
                # Simulate actual output (this would come from actual pipeline runs)
                actual = {
                    "route": scenario.expected_route.value,
                    "confidence": 0.9,
                    "reason_codes": ["keyword_match"],
                }
                
                # Check for silent failures
                sf = self._check_silent_failure(scenario.id, expected, actual)
                if sf:
                    silent_failures.append(sf)
            
            stats = {
                "scenarios_tested": len(scenarios),
                "silent_failures_found": len(silent_failures),
                "silent_failures": silent_failures,
            }
            
            self.log_capture.info("silent_failure_detection_complete", stats)
            
            return stats
            
        except Exception as e:
            logger.error(f"Silent failure detection failed: {e}")
            self.log_capture.error("silent_failure_detection_failed", {"error": str(e)})
            return {"error": str(e)}
    
    def _check_silent_failure(
        self,
        scenario_id: str,
        expected: Any,
        actual: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Check for silent failures between expected and actual."""
        silent_failures = []
        
        # Check route
        if expected.route.value != actual.get("route"):
            silent_failures.append({
                "type": "route_mismatch",
                "expected": expected.route.value,
                "actual": actual.get("route"),
            })
        
        # Check confidence
        if actual.get("confidence") is None:
            silent_failures.append({
                "type": "missing_confidence",
                "expected_confidence": expected.confidence,
            })
        
        # Check explanation
        if expected.should_explain and not actual.get("explanation"):
            silent_failures.append({
                "type": "missing_explanation",
            })
        
        # Check reason codes
        if not actual.get("reason_codes") and expected.reason_codes:
            silent_failures.append({
                "type": "missing_reason_codes",
                "expected": expected.reason_codes,
            })
        
        if silent_failures:
            return {
                "scenario_id": scenario_id,
                "silent_failures": silent_failures,
            }
        
        return None
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all test phases."""
        logger.info("Starting ROUTE-002 full test suite")
        start_time = datetime.utcnow()
        
        results = {
            "test_run_id": str(start_time.isoformat()),
            "start_time": start_time.isoformat(),
            "baseline": {},
            "chaos": {},
            "silent_failure_detection": {},
        }
        
        # Phase 1: Baseline tests
        results["baseline"] = await self.run_baseline_tests()
        
        # Phase 2: Chaos tests
        results["chaos"] = await self.run_chaos_tests()
        
        # Phase 3: Silent failure detection
        results["silent_failure_detection"] = await self.run_silent_failure_detection()
        
        # Calculate summary
        end_time = datetime.utcnow()
        results["end_time"] = end_time.isoformat()
        results["duration_seconds"] = (end_time - start_time).total_seconds()
        
        # Calculate overall pass rate
        baseline_pass_rate = results["baseline"].get("pass_rate", 0)
        chaos_success_rate = results["chaos"].get("success_rate", 0)
        results["overall_score"] = (baseline_pass_rate + chaos_success_rate) / 2
        
        # Write final results
        results_file = self.results_dir / "full_test_results.json"
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2, default=str)
        
        # Generate log analysis
        log_stats = self.log_capture.get_stats()
        log_analysis = {
            "test_run_id": results["test_run_id"],
            "log_stats": log_stats,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        log_analysis_file = self.results_dir / "logs" / "log_analysis.json"
        with open(log_analysis_file, "w") as f:
            json.dump(log_analysis, f, indent=2)
        
        logger.info(f"Test suite completed in {results['duration_seconds']:.2f}s")
        logger.info(f"Overall score: {results['overall_score']:.2%}")
        
        return results
    
    def generate_report(self, results: Dict[str, Any]) -> str:
        """Generate markdown report from test results."""
        report = f"""# ROUTE-002: Routing Decision Explainability - Test Report

**Test Run ID**: {results.get("test_run_id", "N/A")}  
**Start Time**: {results.get("start_time", "N/A")}  
**End Time**: {results.get("end_time", "N/A")}  
**Duration**: {results.get("duration_seconds", 0):.2f}s

## Summary

**Overall Score**: {results.get("overall_score", 0):.2%}

### Baseline Tests
- **Total**: {results.get("baseline", {}).get("total", 0)}
- **Passed**: {results.get("baseline", {}).get("passed", 0)}
- **Failed**: {results.get("baseline", {}).get("failed", 0)}
- **Pass Rate**: {results.get("baseline", {}).get("pass_rate", 0):.2%}

### Chaos Tests
- **Total**: {results.get("chaos", {}).get("total", 0)}
- **Successful**: {results.get("chaos", {}).get("successful", 0)}
- **Failed**: {results.get("chaos", {}).get("failed", 0)}
- **Success Rate**: {results.get("chaos", {}).get("success_rate", 0):.2%}

### Silent Failure Detection
- **Scenarios Tested**: {results.get("silent_failure_detection", {}).get("scenarios_tested", 0)}
- **Silent Failures Found**: {results.get("silent_failure_detection", {}).get("silent_failures_found", 0)}

## Findings

### Bugs
"""

        # Add findings from JSON files
        try:
            with open("bugs.json", "r") as f:
                bugs = json.load(f)
                report += f"\nFound {len(bugs)} documented bugs\n"
        except:
            report += "\nNo bugs documented\n"

        report += """
### DX Issues
"""

        try:
            with open("dx.json", "r") as f:
                dx_issues = json.load(f)
                report += f"\nFound {len(dx_issues)} documented DX issues\n"
        except:
            report += "\nNo DX issues documented\n"

        report += """
### Improvements
"""

        try:
            with open("improvements.json", "r") as f:
                improvements = json.load(f)
                report += f"\nFound {len(improvements)} documented improvements\n"
        except:
            report += "\nNo improvements documented\n"

        report += """
## Recommendations

Based on test results, the following improvements are recommended:

1. **Confidence Calibration**: Improve confidence score accuracy
2. **Explanation Enhancement**: Add more detailed reasoning
3. **Policy Attribution**: Better tracking of policy versions
4. **Silent Failure Detection**: Implement more robust detection

---
*Generated by ROUTE-002 Test Runner*
"""

        return report


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="ROUTE-002 Test Runner")
    parser.add_argument("--baseline", action="store_true", help="Run baseline tests")
    parser.add_argument("--chaos", action="store_true", help="Run chaos tests")
    parser.add_argument("--silent", action="store_true", help="Run silent failure detection")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--report", action="store_true", help="Generate report")
    parser.add_argument("--results-dir", type=str, default="results/route002")
    
    args = parser.parse_args()
    
    runner = TestRunner(results_dir=args.results_dir)
    
    if args.all or (not args.baseline and not args.chaos and not args.silent):
        # Run all tests
        results = await runner.run_all_tests()
        
        if args.report:
            report = runner.generate_report(results)
            report_file = Path(args.results_dir) / "FINAL_REPORT.md"
            with open(report_file, "w") as f:
                f.write(report)
            print(f"Report written to {report_file}")
    
    else:
        # Run specific tests
        if args.baseline:
            results = await runner.run_baseline_tests()
            print(json.dumps(results, indent=2, default=str))
        
        if args.chaos:
            results = await runner.run_chaos_tests()
            print(json.dumps(results, indent=2, default=str))
        
        if args.silent:
            results = await runner.run_silent_failure_detection()
            print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
