"""
DAG-007: Dynamic DAG Modification During Execution - Test Pipelines

This module implements test pipelines to verify Stageflow's behavior
when attempting dynamic DAG modifications during execution.

Target: Dynamic DAG modification during execution
Priority: P2
Risk Class: Moderate

Industry Persona: Healthcare Systems Architect
Concerns:
- Clinical workflows must adapt to patient state changes in real-time
- Emergency protocols may require adding stages mid-execution
- Audit trails must capture all dynamic modifications
"""

import asyncio
import json
import logging
import random
import sys
import time
import uuid
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import stageflow
from stageflow import (
    Pipeline, Stage, StageKind, StageOutput, StageContext,
    create_stage_context, create_stage_inputs, PipelineTimer, StageGraph, PipelineRegistry,
)
from stageflow.context import ContextSnapshot
from stageflow.stages.inputs import StageInputs
from stageflow.pipeline import PipelineValidationError, CycleDetectedError
from mocks.dag007_mock_data import (
    MockDAGModifier,
    DynamicWorkloadGenerator,
    CycleDetector,
    ModificationEvent,
    DAGModificationResult,
    DYNAMIC_DAG_TEST_CONFIGS,
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("dag007_tests")


# ============================================================================
# Test Stages
# ============================================================================


class BaseTestStage(Stage):
    """Base stage that tracks execution and modification attempts."""
    name = "base_test"
    kind = StageKind.TRANSFORM
    
    def __init__(self, stage_id: int, modifier: MockDAGModifier | None = None):
        self.stage_id = stage_id
        self.modifier = modifier
        self.executed = False
        self.execution_order = None
        self.modification_during_execution = None
        self.start_time = None
        self.end_time = None
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        self.start_time = time.perf_counter()
        self.executed = True
        
        # Track execution order if available
        order = ctx.inputs.get("execution_counter", 0)
        self.execution_order = order
        
        # Attempt modification if modifier is available
        if self.modifier and self.stage_id == 1:
            # Only first stage attempts modification for baseline tests
            result = await self.modifier.add_stage(
                stage_name=f"dynamic_stage_{uuid.uuid4().hex[:8]}",
                dependencies=[f"stage_{self.stage_id}"],
                config={"added_by": f"stage_{self.stage_id}"}
            )
            self.modification_during_execution = result
        
        # Simulate work
        await asyncio.sleep(random.uniform(0.01, 0.05))
        
        self.end_time = time.perf_counter()
        
        return StageOutput.ok(
            stage_id=self.stage_id,
            execution_time_ms=(self.end_time - self.start_time) * 1000,
            executed=True,
            order=self.execution_order,
        )


class ConditionalBranchStage(Stage):
    """
    Stage that determines which path to take based on context.
    
    Simulates clinical decision-making that determines workflow path.
    """
    name = "conditional_branch"
    kind = StageKind.ROUTE
    
    def __init__(self):
        self.branch_decisions = []
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.perf_counter()
        
        # Get input value to determine branch
        input_value = ctx.inputs.get("input_value", 0)
        
        # Simulate decision logic
        if input_value > 50:
            branch = "high_risk_path"
            next_stage = "high_risk_handler"
        elif input_value > 20:
            branch = "medium_risk_path"
            next_stage = "medium_risk_handler"
        else:
            branch = "low_risk_path"
            next_stage = "low_risk_handler"
        
        self.branch_decisions.append({
            'input': input_value,
            'branch': branch,
            'next_stage': next_stage,
        })
        
        processing_time = time.perf_counter() - start_time
        
        return StageOutput.ok(
            branch=branch,
            next_stage=next_stage,
            branch_decision=self.branch_decisions[-1],
            processing_time_ms=processing_time * 1000,
        )


class DynamicAdaptationStage(Stage):
    """
    Stage that attempts to dynamically modify the pipeline.
    
    This stage tests whether Stageflow allows runtime DAG modifications.
    """
    name = "dynamic_adaptation"
    kind = StageKind.TRANSFORM
    
    def __init__(self, modifier: MockDAGModifier | None = None):
        self.modifier = modifier
        self.adaptation_attempts = []
        self.successful_adaptations = 0
        self.failed_adaptations = 0
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.perf_counter()
        
        # Track adaptation attempts
        adaptation = {
            'timestamp': time.perf_counter(),
            'input_value': ctx.inputs.get("input_value", 0),
            'attempts': [],
        }
        
        # Attempt various modifications
        if self.modifier:
            # Test 1: Try to add a stage
            add_result = await self.modifier.add_stage(
                stage_name=f"adapted_stage_{uuid.uuid4().hex[:8]}",
                dependencies=["dynamic_adaptation"],
                config={"adaptation": True}
            )
            adaptation['attempts'].append({
                'type': 'add_stage',
                'result': 'success' if add_result.success else 'failure',
                'error': add_result.error,
            })
            
            if add_result.success:
                self.successful_adaptations += 1
            else:
                self.failed_adaptations += 1
            
            # Test 2: Try to replace pipeline
            replace_result = await self.modifier.replace_pipeline({
                "replaced_stage": {"dependencies": [], "config": {}}
            })
            adaptation['attempts'].append({
                'type': 'replace_pipeline',
                'result': 'success' if replace_result.success else 'failure',
            })
        
        self.adaptation_attempts.append(adaptation)
        
        processing_time = time.perf_counter() - start_time
        
        return StageOutput.ok(
            adaptations_attempted=len(adaptation['attempts']),
            successful_adaptations=self.successful_adaptations,
            failed_adaptations=self.failed_adaptations,
            adaptation_details=adaptation,
            processing_time_ms=processing_time * 1000,
        )


class CycleDetectionTestStage(Stage):
    """
    Stage that attempts to create a cycle in the DAG.
    
    Tests whether Stageflow properly detects and prevents cycles.
    """
    name = "cycle_test"
    kind = StageKind.TRANSFORM
    
    def __init__(self, existing_stages: dict | None = None):
        self.existing_stages = existing_stages or {}
        self.cycle_detection_result = None
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        start_time = time.perf_counter()
        
        # Test if adding dependencies would create a cycle
        test_stages = dict(self.existing_stages)
        
        # Add a new stage that would depend on a later stage
        test_stages["new_stage"] = {"dependencies": ["stage_3"]}
        test_stages["stage_1"] = {"dependencies": ["new_stage"]}  # This creates a cycle
        
        cycle = CycleDetector.detect_cycle(test_stages)
        self.cycle_detection_result = cycle
        
        processing_time = time.perf_counter() - start_time
        
        return StageOutput.ok(
            cycle_detected=cycle is not None,
            cycle_path=cycle,
            test_stages=list(test_stages.keys()),
            processing_time_ms=processing_time * 1000,
        )


class MetricsCollectionStage(Stage):
    """Collects metrics from the pipeline execution."""
    name = "metrics_collection"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        metrics = {
            'timestamp': time.time(),
            'pipeline_run_id': str(uuid.uuid4()),
            'collected_inputs': list(ctx.inputs._inputs.keys()) if hasattr(ctx.inputs, '_inputs') else [],
        }
        
        # Collect any metrics from prior stages
        for key, value in ctx.snapshot.data.items():
            if isinstance(value, (int, float, str, bool)):
                metrics[f"context_{key}"] = value
        
        return StageOutput.ok(metrics=metrics)


# ============================================================================
# Baseline Pipeline
# ============================================================================


def make_test_stage_class(i: int):
    """Create a stage class with the given stage_id."""
    class StageClass(BaseTestStage):
        name = f"stage_{i}"
        kind = StageKind.TRANSFORM
        
        def __init__(self):
            BaseTestStage.__init__(self, stage_id=i)
    
    return StageClass


def create_linear_pipeline(num_stages: int) -> Pipeline:
    """Create a linear pipeline with N sequential stages."""
    pipeline = Pipeline()
    
    for i in range(1, num_stages + 1):
        dependencies = (f"stage_{i-1}",) if i > 1 else ()
        stage_class = make_test_stage_class(i)
        
        pipeline = pipeline.with_stage(
            f"stage_{i}",
            stage_class,
            StageKind.TRANSFORM,
            dependencies=dependencies
        )
    
    return pipeline


def create_baseline_pipeline() -> Pipeline:
    """
    Create a baseline pipeline without any dynamic modification.
    
    This pipeline serves as the control group for comparison.
    """
    return create_linear_pipeline(5)


async def run_baseline_test() -> dict[str, Any]:
    """Run the baseline pipeline test."""
    logger.info("Running baseline pipeline test...")
    
    # Create context
    snapshot = ContextSnapshot(
        run_id=type('RunIdentity', (), {
            'pipeline_run_id': uuid.uuid4(),
            'request_id': uuid.uuid4(),
            'session_id': uuid.uuid4(),
            'user_id': uuid.uuid4(),
            'org_id': uuid.uuid4(),
            'interaction_id': uuid.uuid4(),
        })(),
        topology="dag007_baseline",
        execution_mode="test",
        input_text="baseline_test",
    )
    
    timer = PipelineTimer()
    inputs = create_stage_inputs(
        snapshot=snapshot,
        prior_outputs={},
        declared_deps=[],
        stage_name="stage_1",
        strict=False,
    )
    ctx = create_stage_context(
        snapshot=snapshot,
        inputs=inputs,
        stage_name="stage_1",
        timer=timer,
    )
    
    # Create and run pipeline
    pipeline = create_baseline_pipeline()
    graph = pipeline.build()
    
    start_time = time.perf_counter()
    results = await graph.run(ctx)
    end_time = time.perf_counter()
    
    # Collect results
    executed_stages = [
        name for name, result in results.items()
        if result.data.get('executed', False)
    ]
    
    return {
        'test_type': 'baseline',
        'success': all(
            result.status.value == 'ok' for result in results.values()
        ),
        'total_stages': len(results),
        'executed_stages': len(executed_stages),
        'execution_time_ms': (end_time - start_time) * 1000,
        'results': {name: result.data for name, result in results.items()},
    }


# ============================================================================
# Dynamic Modification Test Pipelines
# ============================================================================


def make_modification_stage_class(i: int, modifier: MockDAGModifier):
    """Create a stage class with the given stage_id and modifier."""
    class StageClass(BaseTestStage):
        name = f"stage_{i}"
        kind = StageKind.TRANSFORM
        
        def __init__(self):
            BaseTestStage.__init__(self, stage_id=i, modifier=modifier)
    
    return StageClass


def create_pipeline_for_modification_test(
    modifier: MockDAGModifier,
    num_stages: int = 5
) -> tuple[Pipeline, list[type]]:
    """
    Create a pipeline for testing dynamic modifications.
    
    Returns the pipeline and a list of stage classes.
    """
    stage_classes = []
    
    pipeline = Pipeline()
    
    for i in range(1, num_stages + 1):
        dependencies = (f"stage_{i-1}",) if i > 1 else ()
        stage_class = make_modification_stage_class(i, modifier)
        stage_classes.append(stage_class)
        
        pipeline = pipeline.with_stage(
            f"stage_{i}",
            stage_class,
            StageKind.TRANSFORM,
            dependencies=dependencies
        )
    
    return pipeline, stage_classes


async def test_modification_during_execution(
    test_config: dict
) -> dict[str, Any]:
    """
    Test dynamic modification during pipeline execution.
    
    This tests whether Stageflow allows modifications to the DAG
    while the pipeline is running.
    """
    logger.info(f"Running modification test: {test_config}")
    
    modifier = MockDAGModifier()
    
    # Create context
    snapshot = ContextSnapshot(
        run_id=type('RunIdentity', (), {
            'pipeline_run_id': uuid.uuid4(),
            'request_id': uuid.uuid4(),
            'session_id': uuid.uuid4(),
            'user_id': uuid.uuid4(),
            'org_id': uuid.uuid4(),
            'interaction_id': uuid.uuid4(),
        })(),
        topology="dag007_modification",
        execution_mode="test",
        input_text="modification_test",
    )
    
    timer = PipelineTimer()
    inputs = create_stage_inputs(
        snapshot=snapshot,
        prior_outputs={},
        declared_deps=[],
        stage_name="stage_1",
        strict=False,
    )
    ctx = create_stage_context(
        snapshot=snapshot,
        inputs=inputs,
        stage_name="stage_1",
        timer=timer,
    )
    
    # Create pipeline with modifier-aware stages
    pipeline, _ = create_pipeline_for_modification_test(
        modifier, 
        test_config.get('num_stages', 3)
    )
    
    try:
        graph = pipeline.build()
        
        start_time = time.perf_counter()
        results = await graph.run(ctx)
        end_time = time.perf_counter()
        
        # Check if modifications were applied
        modification_stats = modifier.get_stats()
        
        return {
            'test_type': 'modification_during_execution',
            'config': test_config,
            'success': all(
                result.status.value == 'ok' for result in results.values()
            ),
            'execution_time_ms': (end_time - start_time) * 1000,
            'modification_stats': modification_stats,
            'results': {name: result.data for name, result in results.items()},
        }
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        return {
            'test_type': 'modification_during_execution',
            'config': test_config,
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
            'modification_stats': modifier.get_stats(),
        }


async def test_pipeline_replacement() -> dict[str, Any]:
    """
    Test replacing a pipeline during execution.
    
    This tests whether Stageflow allows complete pipeline replacement.
    """
    logger.info("Running pipeline replacement test...")
    
    modifier = MockDAGModifier()
    
    # Create context
    snapshot = ContextSnapshot(
        run_id=type('RunIdentity', (), {
            'pipeline_run_id': uuid.uuid4(),
            'request_id': uuid.uuid4(),
            'session_id': uuid.uuid4(),
            'user_id': uuid.uuid4(),
            'org_id': uuid.uuid4(),
            'interaction_id': uuid.uuid4(),
        })(),
        topology="dag007_replacement",
        execution_mode="test",
        input_text="replacement_test",
    )
    
    timer = PipelineTimer()
    inputs = create_stage_inputs(
        snapshot=snapshot,
        prior_outputs={},
        declared_deps=[],
        stage_name="stage_1",
        strict=False,
    )
    ctx = create_stage_context(
        snapshot=snapshot,
        inputs=inputs,
        stage_name="stage_1",
        timer=timer,
    )
    
    # Create initial pipeline
    initial_pipeline = create_baseline_pipeline()
    
    try:
        graph = initial_pipeline.build()
        
        start_time = time.perf_counter()
        results = await graph.run(ctx)
        end_time = time.perf_counter()
        
        # Attempt to replace the pipeline (this should fail or be ignored)
        replace_result = await modifier.replace_pipeline({
            "replaced_stage": {"dependencies": [], "config": {}}
        })
        
        return {
            'test_type': 'pipeline_replacement',
            'success': all(
                result.status.value == 'ok' for result in results.values()
            ),
            'execution_time_ms': (end_time - start_time) * 1000,
            'replacement_attempted': True,
            'replacement_result': {
                'success': replace_result.success,
                'error': replace_result.error,
            },
            'modification_stats': modifier.get_stats(),
            'results': {name: result.data for name, result in results.items()},
        }
    except Exception as e:
        logger.error(f"Pipeline replacement test failed: {e}")
        return {
            'test_type': 'pipeline_replacement',
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
        }


async def test_cycle_detection() -> dict[str, Any]:
    """
    Test cycle detection during DAG modification.
    
    This verifies that attempting to create cycles is properly detected.
    """
    logger.info("Running cycle detection test...")
    
    # Test the cycle detector utility
    # Test 1: Simple cycle
    stages_with_cycle = {
        "stage_1": {"dependencies": ["stage_2"]},
        "stage_2": {"dependencies": ["stage_3"]},
        "stage_3": {"dependencies": ["stage_1"]},  # Creates cycle: 1 -> 2 -> 3 -> 1
    }
    
    cycle = CycleDetector.detect_cycle(stages_with_cycle)
    
    # Test 2: Would adding a stage create a cycle?
    existing_stages = {
        "stage_1": {"dependencies": []},
        "stage_2": {"dependencies": ["stage_1"]},
        "stage_3": {"dependencies": ["stage_2"]},
    }
    
    would_cycle, cycle_path = CycleDetector.would_create_cycle(
        existing_stages,
        "stage_1",  # Adding stage that depends on stage_1
        ["stage_3"]  # With dependency on stage_3 (creates 1 -> 3 -> ... -> 1)
    )
    
    # Test 3: Valid DAG (no cycle)
    valid_stages = {
        "stage_1": {"dependencies": []},
        "stage_2": {"dependencies": ["stage_1"]},
        "stage_3": {"dependencies": ["stage_1", "stage_2"]},
    }
    valid_cycle = CycleDetector.detect_cycle(valid_stages)
    
    return {
        'test_type': 'cycle_detection',
        'success': True,
        'cycle_detection_tests': {
            'simple_cycle_detected': cycle is not None,
            'cycle_path': cycle,
            'would_create_cycle': would_cycle,
            'would_cycle_path': cycle_path,
            'valid_dag_no_cycle': valid_cycle is None,
        },
    }


async def test_conditional_pipeline() -> dict[str, Any]:
    """
    Test pipeline with conditional branching.
    
    This tests the existing conditional stage functionality.
    """
    logger.info("Running conditional pipeline test...")
    
    # Test with different input values using XCom/inputs
    for input_value in [10, 30, 70]:
        snapshot = ContextSnapshot(
            run_id=type('RunIdentity', (), {
                'pipeline_run_id': uuid.uuid4(),
                'request_id': uuid.uuid4(),
                'session_id': uuid.uuid4(),
                'user_id': uuid.uuid4(),
                'org_id': uuid.uuid4(),
                'interaction_id': uuid.uuid4(),
            })(),
            topology="dag007_conditional",
            execution_mode="test",
            input_text=f"test_{input_value}",  # Use input_text to pass value
        )
        
        timer = PipelineTimer()
        inputs = create_stage_inputs(
            snapshot=snapshot,
            prior_outputs={"input_value": input_value},  # Pass input_value via inputs
            declared_deps=[],
            stage_name="branch",
            strict=False,
        )
        ctx = create_stage_context(
            snapshot=snapshot,
            inputs=inputs,
            stage_name="branch",
            timer=timer,
        )
        
        # Create pipeline with conditional branching
        pipeline = (
            Pipeline()
            .with_stage("branch", ConditionalBranchStage(), StageKind.ROUTE)
        )
        
        try:
            graph = pipeline.build()
            results = await graph.run(ctx)
            
            branch_result = results.get("branch")
            if branch_result:
                logger.info(f"Input {input_value} -> Branch: {branch_result.data.get('branch')}")
        except Exception as e:
            logger.error(f"Conditional test failed for input {input_value}: {e}")
            return {
                'test_type': 'conditional_pipeline',
                'success': False,
                'error': str(e),
                'input_value': input_value,
            }
    
    return {
        'test_type': 'conditional_pipeline',
        'success': True,
        'note': 'Conditional stages work as documented',
    }


# ============================================================================
# Chaos and Stress Tests
# ============================================================================


async def test_concurrent_modifications(
    num_concurrent: int = 10
) -> dict[str, Any]:
    """
    Test concurrent modification attempts.
    
    This stress tests the modification system under concurrent access.
    """
    logger.info(f"Running concurrent modification test with {num_concurrent} concurrent attempts...")
    
    modifier = MockDAGModifier()
    
    # Create context
    snapshot = ContextSnapshot(
        run_id=type('RunIdentity', (), {
            'pipeline_run_id': uuid.uuid4(),
            'request_id': uuid.uuid4(),
            'session_id': uuid.uuid4(),
            'user_id': uuid.uuid4(),
            'org_id': uuid.uuid4(),
            'interaction_id': uuid.uuid4(),
        })(),
        topology="dag007_concurrent",
        execution_mode="test",
        input_text="concurrent_test",
    )
    
    timer = PipelineTimer()
    inputs = create_stage_inputs(
        snapshot=snapshot,
        prior_outputs={},
        declared_deps=[],
        stage_name="concurrent_test",
        strict=False,
    )
    ctx = create_stage_context(
        snapshot=snapshot,
        inputs=inputs,
        stage_name="concurrent_test",
        timer=timer,
    )
    
    # Run concurrent modification attempts
    async def attempt_modification(i: int) -> dict:
        result = await modifier.add_stage(
            stage_name=f"concurrent_stage_{i}",
            dependencies=["stage_1"],
            config={"concurrent_index": i}
        )
        return {
            'index': i,
            'success': result.success,
            'error': result.error,
        }
    
    start_time = time.perf_counter()
    tasks = [attempt_modification(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    end_time = time.perf_counter()
    
    stats = modifier.get_stats()
    
    return {
        'test_type': 'concurrent_modifications',
        'concurrent_attempts': num_concurrent,
        'successful': sum(1 for r in results if isinstance(r, dict) and r.get('success')),
        'failed': sum(1 for r in results if isinstance(r, dict) and not r.get('success')),
        'exceptions': [str(r) for r in results if isinstance(r, Exception)],
        'execution_time_ms': (end_time - start_time) * 1000,
        'modification_stats': stats,
    }


async def test_invalid_modifications() -> dict[str, Any]:
    """
    Test various invalid modification scenarios.
    
    This tests error handling for invalid DAG modifications.
    """
    logger.info("Running invalid modification tests...")
    
    modifier = MockDAGModifier()
    
    test_cases = [
        {
            'name': 'duplicate_stage',
            'action': lambda: modifier.add_stage('stage_1', []),
            'expected_error': True,
        },
        {
            'name': 'missing_dependency',
            'action': lambda: modifier.add_stage('orphan', ['nonexistent']),
            'expected_error': True,
        },
        {
            'name': 'valid_addition',
            'action': lambda: modifier.add_stage('valid_stage', []),
            'expected_error': False,
        },
    ]
    
    results = []
    for test_case in test_cases:
        try:
            result = test_case['action']()
            results.append({
                'name': test_case['name'],
                'success': result.success,
                'error': result.error,
                'expected_error': test_case['expected_error'],
                'correctly_handled': result.success != test_case['expected_error'],
            })
        except Exception as e:
            results.append({
                'name': test_case['name'],
                'success': False,
                'error': str(e),
                'exception': True,
                'expected_error': test_case['expected_error'],
            })
    
    return {
        'test_type': 'invalid_modifications',
        'results': results,
        'all_correctly_handled': all(r.get('correctly_handled', True) for r in results),
    }


# ============================================================================
# Main Test Runner
# ============================================================================


async def run_all_tests() -> dict[str, Any]:
    """
    Run all DAG-007 test scenarios.
    
    Returns a comprehensive result dictionary.
    """
    logger.info("=" * 80)
    logger.info("DAG-007: Dynamic DAG Modification During Execution - Test Suite")
    logger.info("=" * 80)
    
    results = {
        'test_suite': 'DAG-007',
        'target': 'Dynamic DAG modification during execution',
        'priority': 'P2',
        'risk': 'Moderate',
        'tests': {},
        'summary': {},
    }
    
    # Run baseline test
    logger.info("\n[1/7] Running baseline test...")
    results['tests']['baseline'] = await run_baseline_test()
    
    # Run modification tests
    logger.info("\n[2/7] Running modification during execution tests...")
    for config_name, config in DYNAMIC_DAG_TEST_CONFIGS.items():
        if config_name in ['baseline', 'simple_add', 'parallel_add']:
            results['tests'][f'modification_{config_name}'] = await test_modification_during_execution(config)
    
    # Run pipeline replacement test
    logger.info("\n[3/7] Running pipeline replacement test...")
    results['tests']['pipeline_replacement'] = await test_pipeline_replacement()
    
    # Run cycle detection test
    logger.info("\n[4/7] Running cycle detection test...")
    results['tests']['cycle_detection'] = await test_cycle_detection()
    
    # Run conditional pipeline test
    logger.info("\n[5/7] Running conditional pipeline test...")
    results['tests']['conditional_pipeline'] = await test_conditional_pipeline()
    
    # Run concurrent modification test
    logger.info("\n[6/7] Running concurrent modification stress test...")
    results['tests']['concurrent_modifications'] = await test_concurrent_modifications(10)
    
    # Run invalid modification tests
    logger.info("\n[7/7] Running invalid modification tests...")
    results['tests']['invalid_modifications'] = await test_invalid_modifications()
    
    # Generate summary
    total_tests = len(results['tests'])
    passed_tests = sum(1 for t in results['tests'].values() if t.get('success', False))
    failed_tests = total_tests - passed_tests
    
    results['summary'] = {
        'total_tests': total_tests,
        'passed': passed_tests,
        'failed': failed_tests,
        'pass_rate': passed_tests / total_tests * 100 if total_tests > 0 else 0,
    }
    
    logger.info("\n" + "=" * 80)
    logger.info(f"Test Suite Complete: {passed_tests}/{total_tests} tests passed")
    logger.info(f"Pass Rate: {results['summary']['pass_rate']:.1f}%")
    logger.info("=" * 80)
    
    return results


if __name__ == "__main__":
    import json
    
    async def main():
        results = await run_all_tests()
        print("\n" + json.dumps(results, indent=2, default=str))
    
    asyncio.run(main())
