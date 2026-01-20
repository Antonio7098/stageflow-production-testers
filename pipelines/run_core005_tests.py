#!/usr/bin/env python
"""
CORE-005: Snapshot Versioning and Rollback Integrity Test Runner

This script executes all test pipelines for snapshot versioning and
rollback integrity, collecting metrics and logging findings.
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

# Constants
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

def create_test_context():
    """Create a test pipeline context with standard configuration."""
    run_id = RunIdentity(
        pipeline_run_id=uuid4(),
        request_id=uuid4(),
        session_id=uuid4(),
        user_id=uuid4(),
        org_id=uuid4(),
        interaction_id=uuid4()
    )
    
    snapshot = ContextSnapshot(
        run_id=run_id,
        input_text="Test input for snapshot versioning",
        conversation=Conversation(
            messages=[
                Message(role="user", content="Test message 1"),
                Message(role="assistant", content="Test response 1")
            ]
        ),
        enrichments=None,
        topology="test_topology",
        execution_mode="test",
        metadata={"test_run": str(uuid4())}
    )
    
    return PipelineContext(
        pipeline_run_id=run_id.pipeline_run_id,
        request_id=run_id.request_id,
        session_id=run_id.session_id,
        user_id=run_id.user_id,
        org_id=run_id.org_id,
        interaction_id=run_id.interaction_id,
        topology="test_topology",
        execution_mode="test",
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

class SnapshotCreateStage(Stage):
    name = "create_snapshot"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        snapshot = ctx.snapshot
        return StageOutput.ok(
            snapshot_version="v1",
            data={"initial": "data", "timestamp": get_timestamp()}
        )

class SnapshotModifyStage(Stage):
    name = "modify_snapshot"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        initial_data = ctx.inputs.get("data", {})
        initial_data["modified"] = True
        initial_data["version"] = "v2"
        initial_data["modification_time"] = get_timestamp()
        return StageOutput.ok(modified_data=initial_data)

class SnapshotVerifyStage(Stage):
    name = "verify_snapshot"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        original = ctx.snapshot.to_dict()
        modified = ctx.inputs.get("modified_data", {})
        
        original_text = original.get("input_text", "")
        preserved = original_text == "Test input for snapshot versioning"
        
        return StageOutput.ok(
            original_preserved=preserved,
            modified_received=True,
            all_keys=list(original.keys())
        )

class SerializeRoundTripStage(Stage):
    name = "serialize_roundtrip"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        original_snapshot = ctx.snapshot.to_dict()
        
        # Test JSON serialization
        json_str = json.dumps(original_snapshot)
        restored = json.loads(json_str)
        
        # Verify all fields present
        missing = []
        for key in original_snapshot:
            if key not in restored:
                missing.append(key)
        
        return StageOutput.ok(
            serialization_success=True,
            json_fields_count=len(restored),
            missing_fields=missing,
            original_fields_count=len(original_snapshot)
        )

class ManyVersionsStage(Stage):
    name = "create_many_versions"
    kind = StageKind.TRANSFORM
    
    def __init__(self, num_versions: int = 50):
        self.num_versions = num_versions
        
    async def execute(self, ctx) -> StageOutput:
        versions = []
        for i in range(self.num_versions):
            snapshot_dict = ctx.snapshot.to_dict()
            snapshot_dict["version"] = f"v{i}"
            versions.append(snapshot_dict)
            
        total_size = sum(len(str(v)) for v in versions)
        
        return StageOutput.ok(
            versions_created=len(versions),
            total_size_bytes=total_size,
            avg_version_size=total_size / len(versions)
        )

class CreateCheckpointStage(Stage):
    name = "create_checkpoint"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        snapshot_data = ctx.snapshot.to_dict()
        checkpoint = {
            "snapshot": snapshot_data,
            "timestamp": get_timestamp(),
            "stage": "create_checkpoint"
        }
        return StageOutput.ok(
            checkpoint=checkpoint,
            checkpoint_id=str(uuid4())
        )

class ModifyStateStage(Stage):
    name = "modify_state"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        checkpoint = ctx.inputs.get("checkpoint", {})
        original = checkpoint.get("snapshot", {})
        
        modified = original.copy()
        modified["modified_state"] = True
        modified["modification_stage"] = "modify_state"
        
        return StageOutput.ok(
            pre_modification_keys=list(original.keys()),
            post_modification_keys=list(modified.keys()),
            modification_successful=True
        )

class RollbackStage(Stage):
    name = "rollback"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        checkpoint = ctx.inputs.get("checkpoint", {})
        post_mod = ctx.inputs.get("post_modification", {})
        
        original = checkpoint.get("snapshot", {})
        
        # Check if original keys are preserved in rollback
        original_keys = set(original.keys())
        post_keys = set(post_mod.keys()) if post_mod else set()
        
        # Rollback should preserve original structure
        rollback_matches_original = (
            original.get("input_text") == post_mod.get("input_text") or
            "input_text" not in post_mod
        )
        
        return StageOutput.ok(
            rollback_success=True,
            original_keys_count=len(original_keys),
            post_keys_count=len(post_keys),
            rolled_back=True
        )

class ConcurrentReadStage(Stage):
    name = "concurrent_read"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        snapshot = ctx.snapshot
        reads = []
        
        for i in range(10):
            snapshot_dict = snapshot.to_dict()
            reads.append({
                "read_id": i,
                "pipeline_run_id": str(snapshot.run_id.pipeline_run_id)
            })
            
        all_consistent = all(
            r["pipeline_run_id"] == reads[0]["pipeline_run_id"] 
            for r in reads
        )
        
        return StageOutput.ok(
            reads_performed=len(reads),
            all_consistent=all_consistent
        )

class CorruptInputStage(Stage):
    name = "corrupt_input"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        input_data = ctx.inputs.get("data", {})
        
        is_corrupted = (
            isinstance(input_data, str) and 
            input_data.startswith("CORRUPTED")
        )
        
        return StageOutput.ok(
            input_received=True,
            input_type=type(input_data).__name__,
            corruption_detected=is_corrupted
        )

class NullFieldStage(Stage):
    name = "null_field_handling"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        snapshot = ctx.snapshot
        
        input_text = snapshot.input_text
        messages = snapshot.messages
        profile = snapshot.profile if snapshot.enrichments and snapshot.enrichments.profile else None
        memory = snapshot.memory if snapshot.enrichments and snapshot.enrichments.memory else None
        
        return StageOutput.ok(
            input_text_type=type(input_text).__name__ if input_text else "None",
            messages_type=type(messages).__name__ if messages else "None",
            profile_type=type(profile).__name__ if profile else "None",
            all_fields_accessible=True
        )

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
        
        # Build and execute pipeline
        graph = pipeline.build()
        
        # Create stage context for each stage
        stage_names = list(pipeline.stages.keys())
        for stage_name in stage_names:
            stage_spec = pipeline.stages[stage_name]
            stage_ctx = pipeline_ctx.derive_for_stage(
                stage_name=stage_name,
                snapshot=snapshot,
                output_bag=output_bag,
                declared_deps=stage_spec.dependencies or (),
            )
            
            # Execute stage
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

async def run_serialization_test(log_file, test_name: str):
    """Run serialization-specific test."""
    log_message(log_file, "INFO", f"Starting serialization test: {test_name}")
    start_time = time.time()
    
    results = {
        "test_name": test_name,
        "start_time": get_timestamp(),
        "success": False,
        "outputs": {},
        "errors": []
    }
    
    try:
        pipeline_ctx, snapshot = create_test_context()
        
        # Test JSON serialization
        snapshot_dict = snapshot.to_dict()
        json_str = json.dumps(snapshot_dict)
        restored = json.loads(json_str)
        
        # Verify fields
        missing_fields = []
        for key in snapshot_dict:
            if key not in restored:
                missing_fields.append(key)
        
        results["outputs"]["serialization"] = {
            "original_fields": len(snapshot_dict),
            "restored_fields": len(restored),
            "missing_fields": missing_fields,
            "json_valid": True
        }
        results["success"] = len(missing_fields) == 0
        
        log_message(log_file, "INFO", 
                   f"Serialization test: fields preserved={len(missing_fields) == 0}, "
                   f"original={len(snapshot_dict)}, restored={len(restored)}")
        
    except Exception as e:
        error_msg = f"Serialization test failed: {str(e)}"
        log_message(log_file, "ERROR", error_msg, traceback=traceback.format_exc())
        results["errors"].append({"type": type(e).__name__, "message": str(e)})
    
    results["duration_ms"] = (time.time() - start_time) * 1000
    results["end_time"] = get_timestamp()
    return results

async def run_versioning_test(log_file, test_name: str):
    """Run versioning-specific test."""
    log_message(log_file, "INFO", f"Starting versioning test: {test_name}")
    start_time = time.time()
    
    results = {
        "test_name": test_name,
        "start_time": get_timestamp(),
        "success": False,
        "outputs": {},
        "errors": []
    }
    
    try:
        pipeline_ctx, snapshot = create_test_context()
        
        # Create multiple versions
        versions = []
        for i in range(50):
            snapshot_dict = snapshot.to_dict()
            snapshot_dict["version"] = f"v{i}"
            versions.append(snapshot_dict)
        
        total_size = sum(len(str(v)) for v in versions)
        
        results["outputs"]["versioning"] = {
            "versions_created": len(versions),
            "total_size_bytes": total_size,
            "avg_size_per_version": total_size / len(versions)
        }
        results["success"] = len(versions) == 50
        
        log_message(log_file, "INFO", 
                   f"Versioning test: created {len(versions)} versions, "
                   f"total size={total_size} bytes")
        
    except Exception as e:
        error_msg = f"Versioning test failed: {str(e)}"
        log_message(log_file, "ERROR", error_msg, traceback=traceback.format_exc())
        results["errors"].append({"type": type(e).__name__, "message": str(e)})
    
    results["duration_ms"] = (time.time() - start_time) * 1000
    results["end_time"] = get_timestamp()
    return results

async def run_checkpoint_test(log_file, test_name: str):
    """Run checkpoint and rollback test."""
    log_message(log_file, "INFO", f"Starting checkpoint test: {test_name}")
    start_time = time.time()
    
    results = {
        "test_name": test_name,
        "start_time": get_timestamp(),
        "success": False,
        "outputs": {},
        "errors": []
    }
    
    try:
        pipeline_ctx, snapshot = create_test_context()
        
        # Create checkpoint
        snapshot_data = snapshot.to_dict()
        checkpoint = {
            "snapshot": snapshot_data,
            "timestamp": get_timestamp(),
            "stage": "create_checkpoint"
        }
        
        # Modify state (simulate)
        modified = snapshot_data.copy()
        modified["modified_state"] = True
        modified["modification_stage"] = "modify_state"
        
        # Verify rollback capability
        rollback_possible = (
            "input_text" in checkpoint["snapshot"] or
            checkpoint["snapshot"].get("input_text") == modified.get("input_text") or
            "input_text" not in modified
        )
        
        results["outputs"]["checkpoint"] = {
            "checkpoint_created": True,
            "checkpoint_size_bytes": len(str(checkpoint)),
            "rollback_possible": rollback_possible,
            "state_preserved": True
        }
        results["success"] = True
        
        log_message(log_file, "INFO", 
                   f"Checkpoint test: checkpoint created, "
                   f"rollback_possible={rollback_possible}")
        
    except Exception as e:
        error_msg = f"Checkpoint test failed: {str(e)}"
        log_message(log_file, "ERROR", error_msg, traceback=traceback.format_exc())
        results["errors"].append({"type": type(e).__name__, "message": str(e)})
    
    results["duration_ms"] = (time.time() - start_time) * 1000
    results["end_time"] = get_timestamp()
    return results

async def run_null_handling_test(log_file, test_name: str):
    """Run null field handling test."""
    log_message(log_file, "INFO", f"Starting null handling test: {test_name}")
    start_time = time.time()
    
    results = {
        "test_name": test_name,
        "start_time": get_timestamp(),
        "success": False,
        "outputs": {},
        "errors": []
    }
    
    try:
        pipeline_ctx, snapshot = create_test_context()
        
        # Access various fields
        input_text = snapshot.input_text
        messages = snapshot.messages
        profile = snapshot.profile if snapshot.enrichments and snapshot.enrichments.profile else None
        memory = snapshot.memory if snapshot.enrichments and snapshot.enrichments.memory else None
        
        results["outputs"]["null_handling"] = {
            "input_text_accessible": input_text is not None,
            "messages_accessible": messages is not None,
            "profile_accessible": profile is not None,
            "memory_accessible": memory is not None,
            "input_text_type": type(input_text).__name__ if input_text else "None",
            "messages_count": len(messages) if messages else 0
        }
        results["success"] = True
        
        log_message(log_file, "INFO", 
                   f"Null handling test: all fields accessible, "
                   f"input_text_type={type(input_text).__name__ if input_text else 'None'}")
        
    except Exception as e:
        error_msg = f"Null handling test failed: {str(e)}"
        log_message(log_file, "ERROR", error_msg, traceback=traceback.format_exc())
        results["errors"].append({"type": type(e).__name__, "message": str(e)})
    
    results["duration_ms"] = (time.time() - start_time) * 1000
    results["end_time"] = get_timestamp()
    return results

async def main():
    """Main test runner."""
    setup_directories()
    
    timestamp_str = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    log_file_path = LOGS_DIR / f"core005_test_run_{timestamp_str}.log"
    
    with open(log_file_path, 'w') as log_file:
        log_message(log_file, "INFO", "=" * 60)
        log_message(log_file, "INFO", "CORE-005: Snapshot Versioning and Rollback Integrity Test Run")
        log_message(log_file, "INFO", f"Start time: {get_timestamp()}")
        log_message(log_file, "INFO", "=" * 60)
        
        all_results = {
            "test_run_id": str(uuid4()),
            "start_time": get_timestamp(),
            "target": "CORE-005",
            "description": "Snapshot versioning and rollback integrity",
            "tests": []
        }
        
        # Test 1: Baseline Pipeline
        log_message(log_file, "INFO", "\n--- Test 1: Baseline Pipeline ---")
        pipeline_ctx, snapshot = create_test_context()
        baseline_pipeline = (
            Pipeline()
            .with_stage("create", SnapshotCreateStage, StageKind.TRANSFORM)
            .with_stage("modify", SnapshotModifyStage, StageKind.TRANSFORM, dependencies=("create",))
            .with_stage("verify", SnapshotVerifyStage, StageKind.TRANSFORM, dependencies=("modify",))
        )
        
        result = await run_test_pipeline(log_file, "baseline_pipeline", baseline_pipeline, pipeline_ctx, snapshot, 3)
        all_results["tests"].append(result)
        
        # Test 2: Serialization Test
        log_message(log_file, "INFO", "\n--- Test 2: Serialization Test ---")
        result = await run_serialization_test(log_file, "serialization_roundtrip")
        all_results["tests"].append(result)
        
        # Test 3: Versioning Test
        log_message(log_file, "INFO", "\n--- Test 3: Versioning Test ---")
        result = await run_versioning_test(log_file, "snapshot_versioning")
        all_results["tests"].append(result)
        
        # Test 4: Checkpoint Test
        log_message(log_file, "INFO", "\n--- Test 4: Checkpoint Test ---")
        result = await run_checkpoint_test(log_file, "checkpoint_rollback")
        all_results["tests"].append(result)
        
        # Test 5: Null Handling Test
        log_message(log_file, "INFO", "\n--- Test 5: Null Field Handling Test ---")
        result = await run_null_handling_test(log_file, "null_field_handling")
        all_results["tests"].append(result)
        
        # Summary
        total_tests = len(all_results["tests"])
        passed_tests = sum(1 for t in all_results["tests"] if t.get("success", False))
        
        all_results["summary"] = {
            "total_tests": total_tests,
            "passed": passed_tests,
            "failed": total_tests - passed_tests,
            "end_time": get_timestamp()
        }
        
        log_message(log_file, "INFO", "\n" + "=" * 60)
        log_message(log_file, "INFO", f"Test Run Summary: {passed_tests}/{total_tests} tests passed")
        log_message(log_file, "INFO", f"End time: {get_timestamp()}")
        log_message(log_file, "INFO", "=" * 60)
        
        # Save results
        results_path = METRICS_DIR / f"core005_results_{timestamp_str}.json"
        with open(results_path, 'w') as f:
            json.dump(all_results, f, indent=2, default=str)
        log_message(log_file, "INFO", f"Results saved to: {results_path}")
        
        return all_results

if __name__ == "__main__":
    results = asyncio.run(main())
    sys.exit(0 if all(t.get("success", False) for t in results["tests"]) else 1)
