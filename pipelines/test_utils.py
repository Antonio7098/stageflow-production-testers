"""
Shared utilities for Stageflow test pipelines.
"""

from typing import Optional
from uuid import uuid4

from stageflow import StageContext, PipelineTimer
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow.stages.inputs import StageInputs


def create_stage_context(
    input_text: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    topology: str = "test",
    execution_mode: str = "test",
) -> StageContext:
    """
    Create a properly configured StageContext for test pipelines.
    
    Args:
        input_text: The input text for the pipeline
        user_id: Optional user ID (auto-generated if not provided)
        session_id: Optional session ID (auto-generated if not provided)
        topology: Pipeline topology name
        execution_mode: Execution mode
        
    Returns:
        Configured StageContext ready for pipeline execution
    """
    snapshot = ContextSnapshot(
        run_id=RunIdentity(
            pipeline_run_id=uuid4(),
            request_id=uuid4(),
            session_id=session_id or str(uuid4()),
            user_id=user_id or str(uuid4()),
            org_id=None,
            interaction_id=uuid4(),
        ),
        topology=topology,
        execution_mode=execution_mode,
        input_text=input_text,
    )
    
    return StageContext(
        snapshot=snapshot,
        inputs=StageInputs(snapshot=snapshot),
        stage_name="pipeline_entry",
        timer=PipelineTimer(),
    )
