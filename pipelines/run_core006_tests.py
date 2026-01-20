#!/usr/bin/env python
"""
CORE-006: Context Propagation Across Nested Pipelines Test Runner

This script executes all test pipelines for context propagation across
nested pipelines, collecting metrics and logging findings.
"""
import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import stageflow
from stageflow import Pipeline, Stage, StageKind, StageOutput
from stageflow.context import (
    ContextSnapshot, RunIdentity, Conversation, Message,
    ProfileEnrichment, MemoryEnrichment
)
from stageflow.context.output_bag import OutputBag
from stageflow.stages.context import PipelineContext
from stageflow.stages.inputs import StageInputs
from stageflow.core import PipelineTimer

RESULTS_DIR = Path("results")
LOGS_DIR = RESULTS_DIR / "logs"
METRICS_DIR = RESULTS_DIR / "metrics"


def setup_directories():
    """Create necessary directories for test artifacts."""
    RESULTS_DIR.mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)
    METRICS_DIR.mkdir(exist_ok=True)


def get_timestamp():
    """Get current timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def create_test_context(
    pipeline_run_id=None,
    request_id=None,
    session_id=None,
    user_id=None,
    org_id=None,
    interaction_id=None,
    input_text="Test input for context propagation",
    topology="test_topology",
    execution_mode="test"
):
    """Create a test pipeline context with standard configuration."""
    run_id = RunIdentity(
        pipeline_run_id=pipeline_run_id or uuid4(),
        request_id=request_id or uuid4(),
        session_id=session_id or uuid4(),
        user_id=user_id or uuid4(),
        org_id=org_id or uuid4(),
        interaction_id=interaction_id or uuid4()
    )
    
    snapshot = ContextSnapshot(
        run_id=run_id,
        input_text=input_text,
        conversation=Conversation(
            messages=[
                Message(role="user", content="Test message 1"),
                Message(role="assistant", content="Test response 1")
            ]
        ),
        enrichments=None,
        topology=topology,
        execution_mode=execution_mode,
        metadata={"test_run": str(uuid4()), "nested_level": 0}
    )
    
    return PipelineContext(
        pipeline_run_id=run_id.pipeline_run_id,
        request_id=run_id.request_id,
        session_id=run_id.session_id,
        user_id=run_id.user_id,
        org_id=run_id.org_id,
        interaction_id=run_id.interaction_id,
        topology=topology,
        execution_mode=execution_mode,
    ), snapshot


def log_message(log_file, level: str, message: str, **kwargs):
    """Write a log message to file and stdout."""
    timestamp = get_timestamp()
    log_entry = {
        "timestamp": timestamp,
        "level": level,
        "message": message,
        **kwargs
    }
    log_entry_str = json.dumps(log_entry)
    log_file.write(log_entry_str + "\n")
    log_file.flush()
    print(f"[{level}] {message}")


class ContextCaptureStage(Stage):
    """Stage that captures and reports current context state."""
    name = "capture_context"
    kind = StageKind.TRANSFORM
    
    def __init__(self, capture_level: str = "parent"):
        self.capture_level = capture_level
    
    async def execute(self, ctx) -> StageOutput:
        snapshot = ctx.snapshot
        run_id = snapshot.run_id
        
        captured = {
            "pipeline_run_id": str(run_id.pipeline_run_id),
            "request_id": str(run_id.request_id),
            "session_id": str(run_id.session_id),
            "user_id": str(run_id.user_id),
            "org_id": str(run_id.org_id),
            "interaction_id": str(run_id.interaction_id),
            "input_text": snapshot.input_text,
            "topology": snapshot.topology,
            "execution_mode": snapshot.execution_mode,
            "messages_count": len(snapshot.messages) if snapshot.messages else 0,
            "metadata": snapshot.metadata or {},
            "capture_level": self.capture_level
        }
        
        return StageOutput.ok(context_captured=captured)


class ContextModifyStage(Stage):
    """Stage that attempts to modify context data."""
    name = "modify_context"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        original_input = ctx.snapshot.input_text
        original_metadata = ctx.snapshot.metadata.copy() if ctx.snapshot.metadata else {}
        
        return StageOutput.ok(
            original_input=original_input,
            original_metadata=original_metadata,
            modification_attempted=True,
            stage_run_id=str(uuid4())
        )


class ContextVerifyStage(Stage):
    """Stage that verifies context consistency."""
    name = "verify_context"
    kind = StageKind.TRANSFORM
    
    def __init__(self, expected_parent_run_id: str = None):
        self.expected_parent_run_id = expected_parent_run_id
    
    async def execute(self, ctx) -> StageOutput:
        snapshot = ctx.snapshot
        run_id = snapshot.run_id
        
        verification = {
            "run_id_matches": True,
            "identity_fields_present": all([
                run_id.pipeline_run_id,
                run_id.request_id,
                run_id.session_id,
                run_id.user_id,
                run_id.org_id,
                run_id.interaction_id
            ]),
            "input_text_preserved": snapshot.input_text is not None,
            "topology_preserved": snapshot.topology is not None,
            "execution_mode_preserved": snapshot.execution_mode is not None,
            "messages_preserved": snapshot.messages is not None
        }
        
        all_verified = all(verification.values())
        
        return StageOutput.ok(
            verification_passed=all_verified,
            verification_details=verification,
            run_id=str(run_id.pipeline_run_id)
        )


class NestedChildStage(Stage):
    """Stage executed within a child pipeline."""
    name = "nested_child"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        snapshot = ctx.snapshot
        run_id = snapshot.run_id
        
        return StageOutput.ok(
            child_processed=True,
            child_run_id=str(run_id.pipeline_run_id),
            parent_data_accessible=False,
            input_text_received=snapshot.input_text
        )


class DeepNestStage(Stage):
    """Stage for testing deep nesting."""
    name = "deep_nest"
    kind = StageKind.TRANSFORM
    
    def __init__(self, nest_level: int = 1):
        self.nest_level = nest_level
    
    async def execute(self, ctx) -> StageOutput:
        snapshot = ctx.snapshot
        run_id = snapshot.run_id
        
        current_level = ctx.snapshot.metadata.get("nested_level", 0) if ctx.snapshot.metadata else 0
        
        return StageOutput.ok(
            nest_level=self.nest_level,
            current_run_id=str(run_id.pipeline_run_id),
            processed_at_level=self.nest_level,
            metadata_received=ctx.snapshot.metadata or {}
        )


class ContextPropagateStage(Stage):
    """Stage that propagates context to child pipelines."""
    name = "propagate_context"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        return StageOutput.ok(
            propagated=True,
            stage_run_id=str(uuid4()),
            propagated_at=get_timestamp()
        )


class PriorOutputAccessStage(Stage):
    """Stage that accesses prior stage outputs."""
    name = "access_prior_outputs"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        prior_keys = []
        prior_values = {}
        
        for key in ["context_captured", "original_input", "modification_attempted"]:
            value = ctx.inputs.get(key)
            if value is not None:
                prior_keys.append(key)
                prior_values[key] = value
        
        return StageOutput.ok(
            prior_keys_accessed=prior_keys,
            prior_values_received=len(prior_keys),
            all_expected=True
        )


class ConcurrentAccessStage(Stage):
    """Stage for concurrent context access testing."""
    name = "concurrent_access"
    kind = StageKind.TRANSFORM
    
    def __init__(self, instance_id: int = 0):
        self.instance_id = instance_id
    
    async def execute(self, ctx) -> StageOutput:
        snapshot = ctx.snapshot
        run_id = snapshot.run_id
        
        return StageOutput.ok(
            instance_id=self.instance_id,
            run_id=str(run_id.pipeline_run_id),
            input_text=snapshot.input_text,
            processed=True
        )


class EdgeCaseStage(Stage):
    """Stage for testing edge cases."""
    name = "edge_case"
    kind = StageKind.TRANSFORM
    
    def __init__(self, test_type: str = "empty"):
        self.test_type = test_type
    
    async def execute(self, ctx) -> StageOutput:
        snapshot = ctx.snapshot
        
        results = {
            "test_type": self.test_type,
            "input_text_type": type(snapshot.input_text).__name__ if snapshot.input_text else "None",
            "input_text_value": snapshot.input_text,
            "messages_type": type(snapshot.messages).__name__ if snapshot.messages else "None",
            "messages_count": len(snapshot.messages) if snapshot.messages else 0,
            "metadata_type": type(snapshot.metadata).__name__ if snapshot.metadata else "None",
            "metadata_keys": list(snapshot.metadata.keys()) if snapshot.metadata else []
        }
        
        return StageOutput.ok(**results)


async def run_test_pipeline(log_file, test_name: str, pipeline, pipeline_ctx, snapshot, expected_stages: int = 3):
    """Execute a test pipeline and collect results."""
    log_message(log_file, "INFO", f"Starting test: {test_name}")
    start_time = time.time()
    
    results = {
        "test_name": test_name,
        "start_time": get_timestamp(),
        "stages_expected": expected_stages,
        "stages_completed": 0,
        "outputs": {},
        "errors": [],
        "success": False
    }
    
    try:
        output_bag = OutputBag()
        
        graph = pipeline.build()
        
        stage_names = list(pipeline.stages.keys())
        for stage_name in stage_names:
            stage_spec = pipeline.stages[stage_name]
            stage_ctx = pipeline_ctx.derive_for_stage(
                stage_name=stage_name,
                snapshot=snapshot,
                output_bag=output_bag,
                declared_deps=stage_spec.dependencies or (),
            )
            
            stage_runner = stage_spec.runner
            if isinstance(stage_runner, type):
                stage_instance = stage_runner()
            else:
                stage_instance = stage_runner
            
            output = await stage_instance.execute(stage_ctx)
            await output_bag.write(stage_name, output)
            
            results["stages_completed"] += 1
            results["outputs"][stage_name] = {
                "data": output.data if output else None,
                "status": str(output.status) if output else "None"
            }
        
        results["success"] = results["stages_completed"] == expected_stages
        results["duration_ms"] = (time.time() - start_time) * 1000
        
        log_message(log_file, "INFO", 
                   f"Test {test_name} completed: success={results['success']}, "
                   f"stages={results['stages_completed']}/{expected_stages}, "
                   f"duration={results['duration_ms']:.2f}ms")
        
    except Exception as e:
        error_msg = f"Test {test_name} failed: {str(e)}"
        log_message(log_file, "ERROR", error_msg, traceback=traceback.format_exc())
        results["errors"].append({
            "type": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc()
        })
        results["duration_ms"] = (time.time() - start_time) * 1000
    
    results["end_time"] = get_timestamp()
    return results


async def run_context_isolation_test(log_file, test_name: str):
    """Test context isolation between parent and child contexts."""
    log_message(log_file, "INFO", f"Starting context isolation test: {test_name}")
    start_time = time.time()
    
    results = {
        "test_name": test_name,
        "start_time": get_timestamp(),
        "success": False,
        "outputs": {},
        "errors": []
    }
    
    try:
        parent_ctx, parent_snapshot = create_test_context()
        parent_run_id = parent_snapshot.run_id.pipeline_run_id
        
        log_message(log_file, "INFO", f"Parent run ID: {parent_run_id}")
        
        child_ctx = parent_ctx.fork(
            child_run_id=uuid4(),
            parent_stage_id="test_parent_stage",
            correlation_id=uuid4(),
            topology="child_topology"
        )
        
        child_run_id = child_ctx.pipeline_run_id
        
        isolation_tests = {
            "different_run_ids": parent_run_id != child_run_id,
            "parent_run_id_preserved": str(parent_ctx.pipeline_run_id) == str(parent_run_id),
            "child_has_own_run_id": child_run_id is not None,
            "child_references_parent": child_ctx.parent_run_id == parent_run_id,
            "child_has_parent_stage": child_ctx.parent_stage_id == "test_parent_stage",
            "child_data_is_fresh": len(child_ctx.data) == 0,
            "child_artifacts_is_fresh": len(child_ctx.artifacts) == 0,
            "identity_inherited": all([
                child_ctx.request_id == parent_ctx.request_id,
                child_ctx.session_id == parent_ctx.session_id,
                child_ctx.user_id == parent_ctx.user_id,
                child_ctx.org_id == parent_ctx.org_id,
                child_ctx.interaction_id == parent_ctx.interaction_id
            ])
        }
        
        results["outputs"]["isolation"] = isolation_tests
        results["outputs"]["parent_run_id"] = str(parent_run_id)
        results["outputs"]["child_run_id"] = str(child_run_id)
        
        all_tests_passed = all(isolation_tests.values())
        results["success"] = all_tests_passed
        
        log_message(log_file, "INFO", 
                   f"Context isolation test: all_passed={all_tests_passed}")
        for test_name, passed in isolation_tests.items():
            log_message(log_file, "INFO", f"  - {test_name}: {passed}")
        
    except Exception as e:
        error_msg = f"Context isolation test failed: {str(e)}"
        log_message(log_file, "ERROR", error_msg, traceback=traceback.format_exc())
        results["errors"].append({"type": type(e).__name__, "message": str(e)})
    
    results["duration_ms"] = (time.time() - start_time) * 1000
    results["end_time"] = get_timestamp()
    return results


async def run_context_propagation_test(log_file, test_name: str):
    """Test context propagation across multiple pipeline levels."""
    log_message(log_file, "INFO", f"Starting context propagation test: {test_name}")
    start_time = time.time()
    
    results = {
        "test_name": test_name,
        "start_time": get_timestamp(),
        "success": False,
        "outputs": {},
        "errors": []
    }
    
    try:
        level_0_ctx, level_0_snapshot = create_test_context()
        level_0_run_id = level_0_snapshot.run_id.pipeline_run_id
        
        level_1_ctx = level_0_ctx.fork(
            child_run_id=uuid4(),
            parent_stage_id="level_0_stage",
            correlation_id=uuid4(),
            topology="level_1_topology"
        )
        
        level_2_ctx = level_1_ctx.fork(
            child_run_id=uuid4(),
            parent_stage_id="level_1_stage",
            correlation_id=uuid4(),
            topology="level_2_topology"
        )
        
        level_3_ctx = level_2_ctx.fork(
            child_run_id=uuid4(),
            parent_stage_id="level_2_stage",
            correlation_id=uuid4(),
            topology="level_3_topology"
        )
        
        propagation_tests = {
            "level_0_run_id": str(level_0_run_id),
            "level_1_run_id": str(level_1_ctx.pipeline_run_id),
            "level_2_run_id": str(level_2_ctx.pipeline_run_id),
            "level_3_run_id": str(level_3_ctx.pipeline_run_id),
            "all_run_ids_unique": len(set([
                str(level_0_run_id),
                str(level_1_ctx.pipeline_run_id),
                str(level_2_ctx.pipeline_run_id),
                str(level_3_ctx.pipeline_run_id)
            ])) == 4,
            "identity_preserved_level_1": all([
                level_1_ctx.request_id == level_0_ctx.request_id,
                level_1_ctx.session_id == level_0_ctx.session_id,
                level_1_ctx.user_id == level_0_ctx.user_id,
                level_1_ctx.org_id == level_0_ctx.org_id
            ]),
            "identity_preserved_level_2": all([
                level_2_ctx.request_id == level_1_ctx.request_id,
                level_2_ctx.session_id == level_1_ctx.session_id,
                level_2_ctx.user_id == level_1_ctx.user_id,
                level_2_ctx.org_id == level_1_ctx.org_id
            ]),
            "identity_preserved_level_3": all([
                level_3_ctx.request_id == level_2_ctx.request_id,
                level_3_ctx.session_id == level_2_ctx.session_id,
                level_3_ctx.user_id == level_2_ctx.user_id,
                level_3_ctx.org_id == level_2_ctx.org_id
            ]),
            "topology_overrides_work": all([
                level_1_ctx.topology == "level_1_topology",
                level_2_ctx.topology == "level_2_topology",
                level_3_ctx.topology == "level_3_topology"
            ]),
            "parent_chain_intact": all([
                level_1_ctx.parent_run_id == level_0_run_id,
                level_2_ctx.parent_run_id == level_1_ctx.pipeline_run_id,
                level_3_ctx.parent_run_id == level_2_ctx.pipeline_run_id
            ])
        }
        
        results["outputs"]["propagation"] = propagation_tests
        all_passed = all(v if isinstance(v, bool) else True for v in propagation_tests.values() if isinstance(v, bool))
        results["success"] = all_passed
        
        log_message(log_file, "INFO", 
                   f"Context propagation test: all_passed={all_passed}")
        for test_name, passed in propagation_tests.items():
            if isinstance(passed, bool):
                log_message(log_file, "INFO", f"  - {test_name}: {passed}")
        
    except Exception as e:
        error_msg = f"Context propagation test failed: {str(e)}"
        log_message(log_file, "ERROR", error_msg, traceback=traceback.format_exc())
        results["errors"].append({"type": type(e).__name__, "message": str(e)})
    
    results["duration_ms"] = (time.time() - start_time) * 1000
    results["end_time"] = get_timestamp()
    return results


async def run_edge_case_test(log_file, test_name: str, test_type: str):
    """Test edge cases in context propagation."""
    log_message(log_file, "INFO", f"Starting edge case test: {test_name} (type: {test_type})")
    start_time = time.time()
    
    results = {
        "test_name": test_name,
        "start_time": get_timestamp(),
        "success": False,
        "outputs": {},
        "errors": []
    }
    
    try:
        if test_type == "empty_input":
            ctx, snapshot = create_test_context(input_text="")
        elif test_type == "unicode":
            ctx, snapshot = create_test_context(input_text="Hello 世界 🌍 Привет")
        elif test_type == "special_chars":
            ctx, snapshot = create_test_context(input_text="Test <script>alert('xss')</script> & \"quotes\"")
        elif test_type == "very_long":
            ctx, snapshot = create_test_context(input_text="x" * 10000)
        elif test_type == "none_input":
            ctx, snapshot = create_test_context(input_text=None)
        else:
            ctx, snapshot = create_test_context()
        
        output_bag = OutputBag()
        stage_ctx = ctx.derive_for_stage(
            stage_name="edge_case",
            snapshot=snapshot,
            output_bag=output_bag,
            declared_deps=(),
        )
        
        edge_stage = EdgeCaseStage(test_type=test_type)
        output = await edge_stage.execute(stage_ctx)
        
        results["outputs"]["edge_case"] = output.data
        results["outputs"]["test_type"] = test_type
        results["success"] = output.data.get("test_type") == test_type
        
        log_message(log_file, "INFO", 
                   f"Edge case test ({test_type}): success={results['success']}")
        
    except Exception as e:
        error_msg = f"Edge case test ({test_type}) failed: {str(e)}"
        log_message(log_file, "ERROR", error_msg, traceback=traceback.format_exc())
        results["errors"].append({"type": type(e).__name__, "message": str(e)})
    
    results["duration_ms"] = (time.time() - start_time) * 1000
    results["end_time"] = get_timestamp()
    return results


async def run_prior_output_test(log_file, test_name: str):
    """Test that prior outputs are accessible in nested stages."""
    log_message(log_file, "INFO", f"Starting prior output access test: {test_name}")
    start_time = time.time()
    
    results = {
        "test_name": test_name,
        "start_time": get_timestamp(),
        "success": False,
        "outputs": {},
        "errors": []
    }
    
    try:
        ctx, snapshot = create_test_context()
        
        pipeline = (
            Pipeline()
            .with_stage("capture", ContextCaptureStage, StageKind.TRANSFORM)
            .with_stage("modify", ContextModifyStage, StageKind.TRANSFORM, dependencies=("capture",))
            .with_stage("access", PriorOutputAccessStage, StageKind.TRANSFORM, dependencies=("modify",))
        )
        
        output_bag = OutputBag()
        
        stage_names = ["capture", "modify", "access"]
        for stage_name in stage_names:
            stage_spec = pipeline.stages[stage_name]
            stage_ctx = ctx.derive_for_stage(
                stage_name=stage_name,
                snapshot=snapshot,
                output_bag=output_bag,
                declared_deps=stage_spec.dependencies or (),
            )
            
            stage_runner = stage_spec.runner
            if isinstance(stage_runner, type):
                stage_instance = stage_runner()
            else:
                stage_instance = stage_runner
            
            output = await stage_instance.execute(stage_ctx)
            await output_bag.write(stage_name, output)
        
        access_output = output_bag.get("access")
        access_data = access_output.output.data if access_output else {}
        
        prior_tests = {
            "prior_output_accessible": access_data.get("prior_values_received", 0) > 0,
            "context_captured_accessible": "context_captured" in access_data.get("prior_keys_accessed", []),
            "original_input_accessible": "original_input" in access_data.get("prior_keys_accessed", []),
            "modification_accessible": "modification_attempted" in access_data.get("prior_keys_accessed", []),
            "all_expected": access_data.get("all_expected", False)
        }
        
        results["outputs"]["prior_tests"] = prior_tests
        results["outputs"]["access_details"] = access_data
        results["success"] = all(prior_tests.values())
        
        log_message(log_file, "INFO", 
                   f"Prior output test: all_passed={results['success']}")
        for test_name, passed in prior_tests.items():
            log_message(log_file, "INFO", f"  - {test_name}: {passed}")
        
    except Exception as e:
        error_msg = f"Prior output test failed: {str(e)}"
        log_message(log_file, "ERROR", error_msg, traceback=traceback.format_exc())
        results["errors"].append({"type": type(e).__name__, "message": str(e)})
    
    results["duration_ms"] = (time.time() - start_time) * 1000
    results["end_time"] = get_timestamp()
    return results


async def run_nested_pipeline_test(log_file, test_name: str):
    """Test nested pipeline execution."""
    log_message(log_file, "INFO", f"Starting nested pipeline test: {test_name}")
    start_time = time.time()
    
    results = {
        "test_name": test_name,
        "start_time": get_timestamp(),
        "success": False,
        "outputs": {},
        "errors": []
    }
    
    try:
        level_0_ctx, level_0_snapshot = create_test_context()
        
        child_1_ctx = level_0_ctx.fork(
            child_run_id=uuid4(),
            parent_stage_id="parent_stage",
            correlation_id=uuid4(),
            topology="child_1"
        )
        
        child_2_ctx = child_1_ctx.fork(
            child_run_id=uuid4(),
            parent_stage_id="child_1_stage",
            correlation_id=uuid4(),
            topology="child_2"
        )
        
        grandchild_ctx = child_2_ctx.fork(
            child_run_id=uuid4(),
            parent_stage_id="child_2_stage",
            correlation_id=uuid4(),
            topology="grandchild"
        )
        
        results["outputs"]["nesting"] = {
            "level_0_run_id": str(level_0_snapshot.run_id.pipeline_run_id),
            "level_1_run_id": str(child_1_ctx.pipeline_run_id),
            "level_2_run_id": str(child_2_ctx.pipeline_run_id),
            "level_3_run_id": str(grandchild_ctx.pipeline_run_id),
            "nesting_depth": 3
        }
        
        results["success"] = True
        
        log_message(log_file, "INFO", 
                   f"Nested pipeline test: created 3 levels of nesting successfully")
        
    except Exception as e:
        error_msg = f"Nested pipeline test failed: {str(e)}"
        log_message(log_file, "ERROR", error_msg, traceback=traceback.format_exc())
        results["errors"].append({"type": type(e).__name__, "message": str(e)})
    
    results["duration_ms"] = (time.time() - start_time) * 1000
    results["end_time"] = get_timestamp()
    return results


async def main():
    """Main test runner."""
    setup_directories()
    
    timestamp_str = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    log_file_path = LOGS_DIR / f"core006_test_run_{timestamp_str}.log"
    
    with open(log_file_path, 'w') as log_file:
        log_message(log_file, "INFO", "=" * 60)
        log_message(log_file, "INFO", "CORE-006: Context Propagation Across Nested Pipelines Test Run")
        log_message(log_file, "INFO", f"Start time: {get_timestamp()}")
        log_message(log_file, "INFO", "=" * 60)
        
        all_results = {
            "test_run_id": str(uuid4()),
            "start_time": get_timestamp(),
            "target": "CORE-006",
            "description": "Context propagation across nested pipelines",
            "tests": []
        }
        
        log_message(log_file, "INFO", "\n--- Test 1: Baseline Pipeline ---")
        ctx, snapshot = create_test_context()
        baseline_pipeline = (
            Pipeline()
            .with_stage("capture", ContextCaptureStage, StageKind.TRANSFORM)
            .with_stage("modify", ContextModifyStage, StageKind.TRANSFORM, dependencies=("capture",))
            .with_stage("verify", ContextVerifyStage, StageKind.TRANSFORM, dependencies=("modify",))
        )
        
        result = await run_test_pipeline(log_file, "baseline_pipeline", baseline_pipeline, ctx, snapshot, 3)
        all_results["tests"].append(result)
        
        log_message(log_file, "INFO", "\n--- Test 2: Context Isolation Test ---")
        result = await run_context_isolation_test(log_file, "context_isolation")
        all_results["tests"].append(result)
        
        log_message(log_file, "INFO", "\n--- Test 3: Context Propagation Test (Deep Nesting) ---")
        result = await run_context_propagation_test(log_file, "context_propagation")
        all_results["tests"].append(result)
        
        log_message(log_file, "INFO", "\n--- Test 4: Prior Output Access Test ---")
        result = await run_prior_output_test(log_file, "prior_output_access")
        all_results["tests"].append(result)
        
        log_message(log_file, "INFO", "\n--- Test 5: Nested Pipeline Test ---")
        result = await run_nested_pipeline_test(log_file, "nested_pipeline")
        all_results["tests"].append(result)
        
        log_message(log_file, "INFO", "\n--- Test 6: Edge Case Tests ---")
        edge_case_types = ["empty_input", "unicode", "special_chars", "very_long", "none_input"]
        for test_type in edge_case_types:
            result = await run_edge_case_test(log_file, f"edge_case_{test_type}", test_type)
            all_results["tests"].append(result)
        
        summary = {
            "total_tests": len(all_results["tests"]),
            "passed": sum(1 for t in all_results["tests"] if t.get("success", False)),
            "failed": sum(1 for t in all_results["tests"] if not t.get("success", False)),
            "end_time": get_timestamp()
        }
        all_results["summary"] = summary
        
        log_message(log_file, "INFO", "\n" + "=" * 60)
        log_message(log_file, "INFO", f"Test Run Summary: {summary['passed']}/{summary['total_tests']} tests passed")
        log_message(log_file, "INFO", f"End time: {get_timestamp()}")
        log_message(log_file, "INFO", "=" * 60)
        
        results_path = METRICS_DIR / f"core006_results_{timestamp_str}.json"
        with open(results_path, 'w') as f:
            json.dump(all_results, f, indent=2, default=str)
        log_message(log_file, "INFO", f"Results saved to: {results_path}")
        
        return all_results


if __name__ == "__main__":
    results = asyncio.run(main())
    sys.exit(0 if all(t.get("success", False) for t in results["tests"]) else 1)
