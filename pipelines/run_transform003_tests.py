#!/usr/bin/env python3
"""Test runner for TRANSFORM-003 format-induced misinterpretation tests."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from stageflow import Pipeline, StageContext, StageKind, StageOutput, PipelineTimer
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow.stages import StageInputs

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import test data and pipelines
from transform003_pipelines import (
    FormatTestData,
    DateParseStage,
    NumberParseStage,
    EncodingDetectStage,
    StructuredParseStage,
    create_date_format_pipeline,
    create_number_format_pipeline,
    create_encoding_pipeline,
    create_structured_parse_pipeline,
    create_comprehensive_format_pipeline,
)


class TestResult:
    """Container for test results."""

    def __init__(self, test_name: str, category: str):
        self.test_name = test_name
        self.category = category
        self.timestamp = datetime.now().isoformat()
        self.tests: List[Dict[str, Any]] = []
        self.passed = 0
        self.failed = 0
        self.silent_failures: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []

    def add_result(self, test_id: str, description: str, input_value: str,
                   success: bool, output: Dict[str, Any], expected: Optional[Dict] = None):
        """Add a test result."""
        result = {
            "test_id": test_id,
            "description": description,
            "input": input_value,
            "success": success,
            "timestamp": datetime.now().isoformat(),
            "output": output,
        }

        if expected:
            result["expected"] = expected

        self.tests.append(result)

        if success:
            self.passed += 1
        else:
            self.failed += 1
            # Check for silent failures
            if output.get("status") == "completed":
                self.silent_failures.append({
                    "test_id": test_id,
                    "description": description,
                    "input": input_value,
                    "issue": "Pipeline completed but test failed - potential silent failure",
                    "output": output,
                })


async def run_pipeline_test(
    pipeline: Pipeline,
    test_data: List[Dict[str, Any]],
    stage_name: str,
    test_name: str,
    category: str,
    expected_outputs: Optional[Dict[str, Any]] = None,
) -> TestResult:
    """Run tests with a pipeline."""
    result = TestResult(test_name, category)

    for item in test_data:
        test_id = str(uuid4())[:8]

        snapshot = ContextSnapshot(
            run_id=RunIdentity(
                pipeline_run_id=uuid4(),
                request_id=uuid4(),
                session_id=uuid4(),
                user_id=uuid4(),
                org_id=None,
                interaction_id=uuid4(),
            ),
            topology="format_test",
            execution_mode="test",
            input_text=item["value"],
        )

        ctx = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name=stage_name,
            timer=PipelineTimer(),
        )

        try:
            graph = pipeline.build()
            output = await graph.run(ctx)

            # Output is dict with stage names as keys
            stage_output = output.get(stage_name)
            if stage_output:
                success = stage_output.status.value == "ok"
                output_status = stage_output.status.value
                output_data = stage_output.data if stage_output else {}
                output_error = str(stage_output.error) if stage_output and stage_output.error else None
            else:
                success = False
                output_status = "unknown"
                output_data = {}
                output_error = "Stage not found in output"

            # For date parsing, check if we got expected fields
            if success and expected_outputs:
                for key, expected_val in expected_outputs.items():
                    actual_val = output_data.get(key)
                    if actual_val != expected_val:
                        success = False
                        output_status = "validation_error"
                        if "validation_errors" not in output_data:
                            output_data["validation_errors"] = []
                        output_data["validation_errors"].append({
                            "field": key,
                            "expected": expected_val,
                            "actual": actual_val,
                        })

            output_for_storage = {
                "status": output_status,
                "data": output_data,
                "error": output_error,
            }

            result.add_result(
                test_id=test_id,
                description=item["description"],
                input_value=item["value"],
                success=success,
                output=output_for_storage,
                expected=expected_outputs if expected_outputs else None,
            )

        except Exception as e:
            result.errors.append({
                "test_id": test_id,
                "description": item["description"],
                "error": str(e),
                "error_type": type(e).__name__,
            })
            result.failed += 1

    return result


async def run_all_tests() -> Dict[str, TestResult]:
    """Run all format tests."""
    results = {}

    # Test 1: Date Format Parsing
    logger.info("Running date format parsing tests...")
    date_pipeline = create_date_format_pipeline()
    date_results = await run_pipeline_test(
        date_pipeline,
        FormatTestData.generate_dates(),
        "date_parse",
        "date_format_parsing",
        "DATE_FORMATS",
    )
    results["date_format"] = date_results

    # Test 2: Number Format Parsing
    logger.info("Running number format parsing tests...")
    num_pipeline = create_number_format_pipeline()
    num_results = await run_pipeline_test(
        num_pipeline,
        FormatTestData.generate_numbers(),
        "number_parse",
        "number_format_parsing",
        "NUMBER_FORMATS",
    )
    results["number_format"] = num_results

    # Test 3: Encoding Detection
    logger.info("Running encoding detection tests...")
    encoding_pipeline = create_encoding_pipeline()
    encoding_results = await run_pipeline_test(
        encoding_pipeline,
        FormatTestData.generate_encoded_text(),
        "encoding_detect",
        "encoding_detection",
        "ENCODING",
    )
    results["encoding"] = encoding_results

    # Test 4: Structured Output Parsing
    logger.info("Running structured output parsing tests...")
    struct_pipeline = create_structured_parse_pipeline()
    struct_results = await run_pipeline_test(
        struct_pipeline,
        FormatTestData.generate_structured_outputs(),
        "structured_parse",
        "structured_output_parsing",
        "STRUCTURED_OUTPUT",
    )
    results["structured_output"] = struct_results

    return results


def analyze_results(results: Dict[str, TestResult]) -> Dict[str, Any]:
    """Analyze test results for patterns and findings."""
    analysis = {
        "summary": {
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "silent_failures": 0,
            "errors": 0,
        },
        "by_category": {},
        "findings": [],
        "patterns": {
            "date_issues": [],
            "number_issues": [],
            "encoding_issues": [],
            "structured_issues": [],
        },
    }

    for category, result in results.items():
        analysis["summary"]["total_tests"] += len(result.tests)
        analysis["summary"]["passed"] += result.passed
        analysis["summary"]["failed"] += result.failed
        analysis["summary"]["silent_failures"] += len(result.silent_failures)
        analysis["summary"]["errors"] += len(result.errors)

        cat_data = {
            "total": len(result.tests),
            "passed": result.passed,
            "failed": result.failed,
            "pass_rate": result.passed / len(result.tests) * 100 if result.tests else 0,
            "silent_failures": len(result.silent_failures),
            "errors": len(result.errors),
        }
        analysis["by_category"][category] = cat_data

        # Analyze failures for patterns
        for test in result.tests:
            if not test["success"]:
                issue = {
                    "description": test["description"],
                    "input": test["input"],
                    "output": test["output"],
                }

                if category == "date_format":
                    analysis["patterns"]["date_issues"].append(issue)
                elif category == "number_format":
                    analysis["patterns"]["number_issues"].append(issue)
                elif category == "encoding":
                    analysis["patterns"]["encoding_issues"].append(issue)
                elif category == "structured_output":
                    analysis["patterns"]["structured_issues"].append(issue)

    # Generate findings
    for pattern_name, issues in analysis["patterns"].items():
        if issues:
            finding = {
                "type": "format_misinterpretation",
                "pattern": pattern_name,
                "count": len(issues),
                "issues": issues[:5],  # Limit to 5 examples
            }
            analysis["findings"].append(finding)

    return analysis


def save_results(results: Dict[str, TestResult], analysis: Dict[str, Any], output_dir: Path):
    """Save test results to files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save detailed results
    detailed_results = {
        "run_timestamp": datetime.now().isoformat(),
        "test_suite": "TRANSFORM-003 Format-induced Misinterpretation",
        "categories": {},
    }

    for category, result in results.items():
        detailed_results["categories"][category] = {
            "test_name": result.test_name,
            "timestamp": result.timestamp,
            "total_tests": len(result.tests),
            "passed": result.passed,
            "failed": result.failed,
            "pass_rate": result.passed / len(result.tests) * 100 if result.tests else 0,
            "silent_failures": result.silent_failures,
            "errors": result.errors,
            "tests": result.tests,
        }

    with open(output_dir / "detailed_results.json", "w") as f:
        json.dump(detailed_results, f, indent=2, default=str)

    # Save analysis
    with open(output_dir / "analysis.json", "w") as f:
        json.dump(analysis, f, indent=2, default=str)

    # Save summary
    summary = {
        "run_timestamp": datetime.now().isoformat(),
        "total_tests": analysis["summary"]["total_tests"],
        "passed": analysis["summary"]["passed"],
        "failed": analysis["summary"]["failed"],
        "pass_rate": analysis["summary"]["passed"] / analysis["summary"]["total_tests"] * 100 if analysis["summary"]["total_tests"] else 0,
        "silent_failures": analysis["summary"]["silent_failures"],
        "categories": {},
    }

    for cat, data in analysis["by_category"].items():
        summary["categories"][cat] = {
            "pass_rate": data["pass_rate"],
            "passed": data["passed"],
            "failed": data["failed"],
            "silent_failures": data["silent_failures"],
        }

    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    logger.info(f"Results saved to {output_dir}")


async def main():
    """Main entry point."""
    from pathlib import Path

    output_dir = Path("results/transform003") / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting TRANSFORM-003 format-induced misinterpretation tests...")
    logger.info(f"Output directory: {output_dir}")

    # Run all tests
    results = await run_all_tests()

    # Analyze results
    analysis = analyze_results(results)

    # Save results
    save_results(results, analysis, output_dir)

    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total tests: {analysis['summary']['total_tests']}")
    logger.info(f"Passed: {analysis['summary']['passed']}")
    logger.info(f"Failed: {analysis['summary']['failed']}")
    logger.info(f"Pass rate: {analysis['summary']['passed'] / analysis['summary']['total_tests'] * 100:.1f}%" if analysis['summary']['total_tests'] else "N/A")
    logger.info(f"Silent failures: {analysis['summary']['silent_failures']}")
    logger.info(f"Errors: {analysis['summary']['errors']}")

    logger.info("\nBy Category:")
    for cat, data in analysis["by_category"].items():
        logger.info(f"  {cat}: {data['pass_rate']:.1f}% pass rate ({data['passed']}/{data['total']})")

    logger.info("\nFindings:")
    for finding in analysis["findings"]:
        logger.info(f"  - {finding['pattern']}: {finding['count']} issues")

    logger.info("\n" + "=" * 60)
    logger.info(f"Results saved to {output_dir}")

    return results, analysis


if __name__ == "__main__":
    asyncio.run(main())
