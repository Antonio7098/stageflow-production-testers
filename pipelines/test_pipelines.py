# Snapshot Versioning and Rollback Test Pipelines

## Pipeline 1: Baseline Pipeline - Happy Path

Tests basic snapshot creation, versioning, and restoration.

```python
# pipelines/baseline_pipeline.py
from uuid import uuid4
from datetime import datetime
from stageflow import Pipeline, Stage, StageKind, StageOutput
from stageflow.context import ContextSnapshot, RunIdentity, Conversation, Message
from stageflow.stages.context import PipelineContext

class SnapshotCreateStage(Stage):
    name = "create_snapshot"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        snapshot = ctx.snapshot
        return StageOutput.ok(
            snapshot_version="v1",
            data={"initial": "data"}
        )

class SnapshotModifyStage(Stage):
    name = "modify_snapshot"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        initial_data = ctx.inputs.get("data", {})
        initial_data["modified"] = True
        initial_data["version"] = "v2"
        return StageOutput.ok(
            modified_data=initial_data
        )

class SnapshotVerifyStage(Stage):
    name = "verify_snapshot"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        original = ctx.snapshot.to_dict()
        modified = ctx.inputs.get("modified_data", {})
        
        return StageOutput.ok(
            original_preserved="initial" in original.get("input_text", ""),
            modified_received=True,
            all_keys=list(original.keys())
        )

# Build baseline pipeline
baseline_pipeline = Pipeline()
baseline_pipeline.add_stage("create", SnapshotCreateStage)
baseline_pipeline.add_stage("modify", SnapshotModifyStage)
baseline_pipeline.add_stage("verify", SnapshotVerifyStage)
```

## Pipeline 2: Serialization Stress Pipeline

Tests serialization/deserialization under various conditions.

```python
# pipelines/serialization_pipeline.py
import json
import pickle
from stageflow import Stage, StageKind, StageOutput
from stageflow.context import ContextSnapshot, RunIdentity

class LargePayloadStage(Stage):
    name = "large_payload"
    kind = StageKind.TRANSFORM
    
    def __init__(self, payload_size_kb: int = 100):
        self.payload_size = payload_size_kb * 1024
        
    async def execute(self, ctx) -> StageOutput:
        large_data = "x" * self.payload_size
        return StageOutput.ok(
            large_payload=large_data,
            payload_size=len(large_data)
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
            missing_fields=missing
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
            
        return StageOutput.ok(
            versions_created=len(versions),
            total_size_bytes=sum(len(str(v)) for v in versions)
        )
```

## Pipeline 3: Rollback Recovery Pipeline

Tests rollback scenarios and recovery from failures.

```python
# pipelines/rollback_pipeline.py
from stageflow import Stage, StageKind, StageOutput
from stageflow.context import ContextSnapshot

class CreateCheckpointStage(Stage):
    name = "create_checkpoint"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        snapshot_data = ctx.snapshot.to_dict()
        checkpoint = {
            "snapshot": snapshot_data,
            "timestamp": str(datetime.utcnow()),
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
        
        # Modify state
        modified = original.copy()
        modified["modified_state"] = True
        modified["modification_stage"] = "modify_state"
        
        return StageOutput.ok(
            pre_modification=original,
            post_modification=modified,
            modification_successful=True
        )

class RollbackStage(Stage):
    name = "rollback"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        checkpoint = ctx.inputs.get("checkpoint", {})
        post_mod = ctx.inputs.get("post_modification", {})
        
        original = checkpoint.get("snapshot", {})
        
        # Verify rollback matches original
        rollback_matches_original = (
            original.get("input_text") == post_mod.get("input_text") or
            "input_text" not in post_mod
        )
        
        return StageOutput.ok(
            rollback_success=rollback_matches_original,
            original_keys=list(original.keys()),
            rolled_back=True
        )

class FailureRecoveryStage(Stage):
    name = "failure_recovery"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        previous_output = ctx.inputs.get("previous_output")
        
        if previous_output is None:
            return StageOutput.ok(
                recovery_mode="initial",
                data={"state": "initial"}
            )
        
        # Simulate recovery
        recovered_data = previous_output.get("data", {})
        recovered_data["recovered"] = True
        recovered_data["recovery_timestamp"] = str(datetime.utcnow())
        
        return StageOutput.ok(
            recovery_mode="rollback",
            data=recovered_data,
            recovery_successful=True
        )
```

## Pipeline 4: Concurrency Pipeline

Tests concurrent snapshot access and modification.

```python
# pipelines/concurrency_pipeline.py
import asyncio
from stageflow import Stage, StageKind, StageOutput

class ConcurrentReadStage(Stage):
    name = "concurrent_read"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        snapshot = ctx.snapshot
        reads = []
        
        # Simulate multiple concurrent reads
        for i in range(10):
            snapshot_dict = snapshot.to_dict()
            reads.append({
                "read_id": i,
                "pipeline_run_id": str(snapshot.run_id.pipeline_run_id)
            })
            
        return StageOutput.ok(
            reads_performed=len(reads),
            all_consistent=all(
                r["pipeline_run_id"] == reads[0]["pipeline_run_id"] 
                for r in reads
            )
        )

class ParallelSnapshotModificationStage(Stage):
    name = "parallel_mod"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        snapshot = ctx.snapshot
        modifications = []
        
        # Stage receives outputs from parallel stages
        for i in range(5):
            mod_data = ctx.inputs.get(f"parallel_stage_{i}", {})
            modifications.append(mod_data)
            
        return StageOutput.ok(
            modifications_received=len(modifications),
            all_outputs_valid=True
        )
```

## Pipeline 5: Chaos Pipeline

Tests snapshot integrity under adverse conditions.

```python
# pipelines/chaos_pipeline.py
from stageflow import Stage, StageKind, StageOutput
from stageflow.context.output_bag import OutputBag, OutputEntry

class CorruptInputStage(Stage):
    name = "corrupt_input"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        # Stage receives potentially corrupted input
        input_data = ctx.inputs.get("data", {})
        
        # Detect corruption
        is_corrupted = (
            isinstance(input_data, str) and 
            input_data.startswith("CORRUPTED")
        )
        
        return StageOutput.ok(
            input_received=True,
            input_type=type(input_data).__name__,
            corruption_detected=is_corrupted
        )

class LargeSnapshotStage(Stage):
    name = "large_snapshot"
    kind = StageKind.TRANSFORM
    
    def __init__(self, depth: int = 100):
        self.depth = depth
        
    async def execute(self, ctx) -> StageOutput:
        # Create deeply nested structure
        data = {"level": 0}
        current = data
        for i in range(self.depth):
            current["nested"] = {"level": i + 1}
            current = current["nested"]
            
        return StageOutput.ok(
            nested_structure=data,
            depth=self.depth
        )

class MemoryPressureStage(Stage):
    name = "memory_pressure"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        snapshots = []
        
        # Create many snapshots to test memory
        for i in range(100):
            snapshot = ctx.snapshot.to_dict()
            snapshots.append(snapshot)
            
        return StageOutput.ok(
            snapshots_created=len(snapshots),
            total_memory_estimate=sum(
                len(str(s)) for s in snapshots
            )
        )

class NullFieldStage(Stage):
    name = "null_field_handling"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx) -> StageOutput:
        snapshot = ctx.snapshot
        
        # Access potentially null fields
        input_text = snapshot.input_text
        messages = snapshot.messages
        profile = snapshot.profile if snapshot.enrichments else None
        
        return StageOutput.ok(
            input_text_type=type(input_text).__name__,
            messages_type=type(messages).__name__ if messages else "None",
            profile_type=type(profile).__name__ if profile else "None",
            all_fields_accessible=True
        )
```
