#!/usr/bin/env python3
"""
CONTRACT-008 Test Runner: Contract Inheritance in Stage Hierarchies

This script executes all contract inheritance tests and collects results.
"""

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow import Pipeline, StageContext, StageKind, StageOutput, StageStatus
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow.core import PipelineTimer
from stageflow.stages.inputs import StageInputs

from pipelines.contract008_pipelines import (
    create_composition_test_pipeline,
    create_inheritance_test_pipeline,
    create_polymorphic_test_pipeline,
    create_silent_failure_pipeline,
    create_subpipeline_test_pipeline,
    ContractCompositionStage,
    OutputContractTestStage,
    ContractEnforcingStage,
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"results/logs/contract008_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result from a single test."""
    test_name: str
    category: str
    passed: bool
    duration_ms: float
    expected_behavior: str
    actual_behavior: str
    contract_violated: bool = False
    silent_failure: bool = False
    error_message: Optional[str] = None
    output_data: Optional[Dict[str, Any]] = None


def create_test_context(
    user_id: Optional[str] = None,
    org_id: Optional[str] = None,
    input_text: str = "test input",
    metadata: Optional[Dict[str, Any]] = None,
) -> StageContext:
    """Create a test StageContext."""
    snapshot = ContextSnapshot(
        run_id=RunIdentity(
            pipeline_run_id=uuid4(),
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4() if user_id else None,
            org_id=uuid4() if org_id else None,
            interaction_id=uuid4(),
        ),
        input_text=input_text,
        topology="test",
        execution_mode="test",
        metadata=metadata or {},
    )
    return StageContext(
        snapshot=snapshot,
        inputs=StageInputs(snapshot=snapshot),
        stage_name="root",
        timer=PipelineTimer(),
    )


class CONTRACT008TestRunner:
    """Test runner for CONTRACT-008: Contract Inheritance in Stage Hierarchies."""
    
    def __init__(self):
        self.results: List[TestResult] = []
        self.start_time = None
        self.test_count = 0
        self.pass_count = 0
        self.fail_count = 0
    
    async def run_pipeline(
        self,
        pipeline: Pipeline,
        context: StageContext,
        test_name: str,
        category: str,
        expected_behavior: str,
    ) -> TestResult:
        """Run a single pipeline test."""
        start = time.time()
        error_message = None
        passed = False
        contract_violated = False
        silent_failure = False
        output_data = None
        
        try:
            logger.info(f"Running test: {test_name}")
            
            # Build and run pipeline
            graph = pipeline.build()
            
            # Run the pipeline
            outputs = await graph.run(context)
            
            # Analyze results
            duration_ms = (time.time() - start) * 1000
            
            # Check for contract violations in outputs
            for stage_name, output in outputs.items():
                if output.status == StageStatus.FAIL:
                    error_message = output.error
                    passed = False
                    break
                if hasattr(output, "data"):
                    if output.data.get("contract_violated"):
                        contract_violated = True
                    if output.data.get("silent_failure_detected"):
                        silent_failure = True
            
            # For now, basic pass/fail based on no errors
            passed = all(
                o.status == StageStatus.OK for o in outputs.values()
            )
            output_data = {
                stage: {
                    "status": o.status.value,
                    "data": o.data,
                }
                for stage, o in outputs.items()
            }
            
            logger.info(f"Test {test_name}: PASSED" if passed else f"Test {test_name}: FAILED")
            
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            error_message = str(e)
            passed = False
            logger.error(f"Test {test_name} failed with exception: {e}")
        
        actual_behavior = "Pipeline executed without errors" if not error_message else error_message
        
        result = TestResult(
            test_name=test_name,
            category=category,
            passed=passed,
            duration_ms=duration_ms,
            expected_behavior=expected_behavior,
            actual_behavior=actual_behavior,
            contract_violated=contract_violated,
            silent_failure=silent_failure,
            error_message=error_message,
            output_data=output_data,
        )
        
        self.results.append(result)
        self.test_count += 1
        if passed:
            self.pass_count += 1
        else:
            self.fail_count += 1
        
        return result
    
    async def test_subpipeline_context_inheritance(self) -> TestResult:
        """Test 1: Context inheritance through subpipeline fork."""
        pipeline = create_subpipeline_test_pipeline()
        context = create_test_context(user_id="test_user", org_id="test_org")
        
        return await self.run_pipeline(
            pipeline,
            context,
            test_name="subpipeline_context_inheritance",
            category="context_inheritance",
            expected_behavior="Child pipeline should inherit user_id and org_id from parent",
        )
    
    async def test_base_derived_validation_chaining(self) -> TestResult:
        """Test 2: Base/derived stage validation chaining."""
        pipeline = create_inheritance_test_pipeline()
        
        # Test with valid data
        context = create_test_context(
            metadata={
                "user_id": "user123",
                "timestamp": "2024-01-01T00:00:00Z",
                "session_id": "session123",
                "action": "read",
            }
        )
        
        return await self.run_pipeline(
            pipeline,
            context,
            test_name="base_derived_validation_chaining",
            category="validation_chaining",
            expected_behavior="Both base and derived validation should run in sequence",
        )
    
    async def test_polymorphic_contract_extension(self) -> TestResult:
        """Test 3: Polymorphic stage contract extension."""
        pipeline = create_polymorphic_test_pipeline()
        context = create_test_context()
        
        return await self.run_pipeline(
            pipeline,
            context,
            test_name="polymorphic_contract_extension",
            category="polymorphic_contracts",
            expected_behavior="Derived stage contract should extend base stage contract",
        )
    
    async def test_contract_composition(self) -> TestResult:
        """Test 4: Multiple contracts composed together."""
        # Modify the pipeline to include the contracts
        pipeline_with_contracts = (
            Pipeline()
            .with_stage(
                "composition",
                ContractCompositionStage(
                    contracts=[
                        {"required": ["field_a", "field_b"]},
                        {"required": ["field_b", "field_c"]},
                    ]
                ),
                StageKind.GUARD,
            )
        )
        context = create_test_context(
            metadata={
                "field_a": "value_a",
                "field_b": "value_b",
                "field_c": "value_c",
            }
        )
        
        return await self.run_pipeline(
            pipeline_with_contracts,
            context,
            test_name="contract_composition",
            category="contract_composition",
            expected_behavior="Output should satisfy all composed contracts",
        )
    
    async def test_silent_failure_detection(self) -> TestResult:
        """Test 5: Silent failure detection for incomplete contracts."""
        pipeline = create_silent_failure_pipeline()
        context = create_test_context()
        
        return await self.run_pipeline(
            pipeline,
            context,
            test_name="silent_failure_detection",
            category="silent_failure",
            expected_behavior="Missing contract fields should be detected as silent failure",
        )
    
    async def test_contract_violation_no_enforcement(self) -> TestResult:
        """Test 6: Verify that contracts are NOT automatically enforced (documenting current behavior)."""
        # Create a pipeline where one stage returns incomplete data
        # and another stage expects specific fields
        pipeline = (
            Pipeline()
            .with_stage("incomplete", ContractEnforcingStage, StageKind.TRANSFORM)
            .with_stage(
                "expect_fields",
                OutputContractTestStage(expect_fields=["result", "status", "extra_field"]),
                StageKind.TRANSFORM,
                dependencies=("incomplete",),
            )
        )
        
        context = create_test_context()
        
        return await self.run_pipeline(
            pipeline,
            context,
            test_name="contract_violation_no_enforcement",
            category="contract_enforcement",
            expected_behavior="Child stage output missing 'extra_field' should NOT raise error (no automatic enforcement)",
        )
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all CONTRACT-008 tests."""
        self.start_time = datetime.now()
        logger.info("=" * 60)
        logger.info("Starting CONTRACT-008: Contract Inheritance Tests")
        logger.info("=" * 60)
        
        # Run all tests
        await self.test_subpipeline_context_inheritance()
        await self.test_base_derived_validation_chaining()
        await self.test_polymorphic_contract_extension()
        await self.test_contract_composition()
        await self.test_silent_failure_detection()
        await self.test_contract_violation_no_enforcement()
        
        # Generate results
        results = self.generate_results()
        
        return results
    
    def generate_results(self) -> Dict[str, Any]:
        """Generate test results summary."""
        duration = (datetime.now() - self.start_time).total_seconds()
        
        results = {
            "test_run_id": f"contract008_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "timestamp": self.start_time.isoformat(),
            "duration_seconds": duration,
            "summary": {
                "total_tests": self.test_count,
                "passed": self.pass_count,
                "failed": self.fail_count,
                "pass_rate": f"{(self.pass_count / self.test_count * 100):.1f}%" if self.test_count > 0 else "N/A",
            },
            "tests": [
                {
                    "name": r.test_name,
                    "category": r.category,
                    "passed": r.passed,
                    "duration_ms": r.duration_ms,
                    "expected_behavior": r.expected_behavior,
                    "actual_behavior": r.actual_behavior,
                    "contract_violated": r.contract_violated,
                    "silent_failure": r.silent_failure,
                    "error_message": r.error_message,
                    "output_data": r.output_data,
                }
                for r in self.results
            ],
            "findings": {
                "contract_inheritance_gaps": [],
                "silent_failures": [],
                "strengths": [],
                "improvements_needed": [],
            },
        }
        
        # Analyze results for findings
        for r in self.results:
            if r.category == "contract_enforcement" and not r.passed:
                results["findings"]["contract_inheritance_gaps"].append({
                    "test": r.test_name,
                    "description": "Contracts are not automatically enforced across stage boundaries",
                    "impact": "Silent data corruption possible when contracts are violated",
                    "recommendation": "Consider adding contract validation interceptor",
                })
            
            if r.silent_failure:
                results["findings"]["silent_failures"].append({
                    "test": r.test_name,
                    "description": r.actual_behavior,
                    "impact": "Contract violations may go undetected",
                })
        
        # Log findings
        logger.info("\n" + "=" * 60)
        logger.info("TEST RESULTS SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total Tests: {self.test_count}")
        logger.info(f"Passed: {self.pass_count}")
        logger.info(f"Failed: {self.fail_count}")
        logger.info(f"Pass Rate: {results['summary']['pass_rate']}")
        logger.info("=" * 60)
        
        return results


async def main():
    """Main entry point."""
    runner = CONTRACT008TestRunner()
    results = await runner.run_all_tests()
    
    # Save results to JSON
    output_path = Path("results/test_results_contract008.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info(f"\nResults saved to: {output_path}")
    
    # Also print summary
    print("\n" + "=" * 60)
    print("CONTRACT-008 TEST SUMMARY")
    print("=" * 60)
    print(f"Total Tests: {results['summary']['total_tests']}")
    print(f"Passed: {results['summary']['passed']}")
    print(f"Failed: {results['summary']['failed']}")
    print(f"Pass Rate: {results['summary']['pass_rate']}")
    print("=" * 60)
    
    # Print individual test results
    print("\nTest Results:")
    for test in results["tests"]:
        status = "PASS" if test["passed"] else "FAIL"
        print(f"  [{status}] - {test['name']} ({test['category']})")
        if test["error_message"]:
            print(f"         Error: {test['error_message']}")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())
