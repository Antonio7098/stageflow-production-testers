#!/usr/bin/env python3
"""Simple test to debug pipeline execution."""

import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow import Pipeline, StageKind, StageOutput, StageContext, StageInputs, PipelineTimer
from stageflow.context import ContextSnapshot, RunIdentity

class DebugStage:
    name = "debug"
    kind = StageKind.TRANSFORM

    async def execute(self, ctx: StageContext) -> StageOutput:
        print(f"StageContext type: {type(ctx)}")
        print(f"Has snapshot: {hasattr(ctx, 'snapshot')}")
        print(f"Has timer: {hasattr(ctx, 'timer')}")
        if hasattr(ctx, 'snapshot'):
            print(f"Snapshot type: {type(ctx.snapshot)}")
            print(f"Has input_text: {hasattr(ctx.snapshot, 'input_text')}")
            print(f"Input text: {ctx.snapshot.input_text}")
        return StageOutput.ok(result="success")

async def main():
    print("Testing basic pipeline execution...")
    
    pipeline = (
        Pipeline()
        .with_stage("debug", DebugStage(), StageKind.TRANSFORM)
    )
    
    graph = pipeline.build()
    
    snapshot = ContextSnapshot(
        run_id=RunIdentity(
            pipeline_run_id=None,
            user_id=None,
        ),
        input_text="test input",
    )
    
    print(f"Snapshot type: {type(snapshot)}")
    
    # Create StageContext from snapshot
    ctx = StageContext(
        snapshot=snapshot,
        inputs=StageInputs(snapshot=snapshot),
        stage_name="pipeline_entry",
        timer=PipelineTimer(),
    )
    print(f"StageContext type: {type(ctx)}")
    print(f"Has timer: {hasattr(ctx, 'timer')}")
    
    try:
        outputs = await graph.run(ctx)
        print(f"Outputs: {outputs}")
        print("SUCCESS!")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
