"""
Stageflow Stress-Testing: Baseline Pipeline Template

A template for creating baseline (happy path) test pipelines.
Copy this file to your run's pipelines/ folder and customize.
"""

from dataclasses import dataclass
from typing import Any

# Stageflow imports (adjust based on actual API)
# from stageflow import Pipeline, Stage, StageOutput, ContextSnapshot
# from stageflow.stages import TransformStage, EnrichStage, GuardStage, AgentStage, WorkStage


@dataclass
class BaselineConfig:
    """Configuration for the baseline pipeline."""
    
    # Identifiers
    pipeline_name: str = "baseline"
    roadmap_entry_id: str = "ENTRY-001"
    
    # Execution settings
    timeout_seconds: int = 30
    max_retries: int = 3
    
    # Feature flags
    enable_tracing: bool = True
    enable_metrics: bool = True
    
    # Custom settings (override in subclass)
    custom_settings: dict[str, Any] | None = None


# =============================================================================
# Stage Output Contracts
# =============================================================================

# Define your typed output contracts here using Pydantic or dataclasses

# Example:
# class TransformOutput(BaseModel):
#     """Output contract for the transform stage."""
#     processed_data: list[dict]
#     record_count: int
#     processing_time_ms: float


# =============================================================================
# Custom Stages
# =============================================================================

# Define any custom stages needed for your test

# Example:
# class CustomTransformStage(TransformStage):
#     """Custom transform stage for this test."""
#     
#     async def execute(self, context: ContextSnapshot) -> StageOutput:
#         # Your implementation here
#         pass


# =============================================================================
# Pipeline Definition
# =============================================================================

def create_baseline_pipeline(config: BaselineConfig):
    """
    Create the baseline pipeline for happy path testing.
    
    This pipeline should:
    1. Accept valid, well-formed input
    2. Process through all stages without errors
    3. Produce expected output
    4. Complete within timeout
    
    Args:
        config: Pipeline configuration
        
    Returns:
        Configured pipeline instance
    """
    # TODO: Implement using actual Stageflow API
    # 
    # Example structure:
    # pipeline = Pipeline(
    #     name=config.pipeline_name,
    #     stages=[
    #         TransformStage(name="transform", ...),
    #         EnrichStage(name="enrich", ...),
    #         GuardStage(name="guard", ...),
    #         AgentStage(name="agent", ...),
    #         WorkStage(name="work", ...),
    #     ],
    #     config={
    #         "timeout": config.timeout_seconds,
    #         "retries": config.max_retries,
    #     },
    # )
    # 
    # if config.enable_tracing:
    #     pipeline.add_interceptor(TracingInterceptor())
    # 
    # return pipeline
    
    raise NotImplementedError("Implement using actual Stageflow API")


# =============================================================================
# Test Execution
# =============================================================================

async def run_baseline_test(
    config: BaselineConfig,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Execute the baseline pipeline with the given input.
    
    Args:
        config: Pipeline configuration
        input_data: Input data for the pipeline
        
    Returns:
        Dictionary containing:
        - success: bool
        - output: Pipeline output (if successful)
        - error: Error details (if failed)
        - metrics: Execution metrics
    """
    pipeline = create_baseline_pipeline(config)
    
    result = {
        "success": False,
        "output": None,
        "error": None,
        "metrics": {
            "start_time": None,
            "end_time": None,
            "duration_ms": None,
            "stages_executed": 0,
        },
    }
    
    try:
        # TODO: Implement using actual Stageflow API
        # 
        # import time
        # start = time.perf_counter()
        # 
        # output = await pipeline.execute(input_data)
        # 
        # end = time.perf_counter()
        # 
        # result["success"] = True
        # result["output"] = output
        # result["metrics"]["duration_ms"] = (end - start) * 1000
        
        raise NotImplementedError("Implement using actual Stageflow API")
        
    except Exception as e:
        result["error"] = {
            "type": type(e).__name__,
            "message": str(e),
        }
    
    return result


# =============================================================================
# Assertions
# =============================================================================

def assert_baseline_success(result: dict[str, Any]) -> None:
    """Assert that the baseline test succeeded."""
    assert result["success"], f"Pipeline failed: {result['error']}"
    assert result["output"] is not None, "Output should not be None"


def assert_within_timeout(result: dict[str, Any], timeout_ms: float) -> None:
    """Assert that execution completed within timeout."""
    duration = result["metrics"]["duration_ms"]
    assert duration is not None, "Duration not recorded"
    assert duration < timeout_ms, f"Execution took {duration}ms, expected < {timeout_ms}ms"


def assert_output_schema(result: dict[str, Any], expected_keys: list[str]) -> None:
    """Assert that output contains expected keys."""
    output = result["output"]
    for key in expected_keys:
        assert key in output, f"Missing expected key: {key}"


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    import asyncio
    
    # Example usage
    config = BaselineConfig(
        pipeline_name="example_baseline",
        roadmap_entry_id="EXAMPLE-001",
    )
    
    sample_input = {
        "data": "sample input data",
    }
    
    print(f"Running baseline pipeline: {config.pipeline_name}")
    print(f"Roadmap entry: {config.roadmap_entry_id}")
    
    # result = asyncio.run(run_baseline_test(config, sample_input))
    # print(f"Result: {result}")
    
    print("NOTE: Implement using actual Stageflow API")
