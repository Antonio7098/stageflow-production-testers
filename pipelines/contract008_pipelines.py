"""
CONTRACT-008 Test Pipelines: Contract Inheritance in Stage Hierarchies

This module contains test pipelines for validating:
1. Subpipeline contract inheritance and propagation
2. Base/derived stage contract chaining
3. Polymorphic stage hierarchies
4. Contract composition patterns
5. Silent failure detection for contract violations
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, TypeVar

from stageflow import (
    Pipeline,
    Stage,
    StageContext,
    StageKind,
    StageOutput,
    StageStatus,
)
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow.stages.context import PipelineContext
from stageflow.stages.inputs import StageInputs


T = TypeVar("T")


@dataclass
class ContractTestResult:
    """Result from a contract inheritance test."""
    test_name: str
    passed: bool
    expected_contract: Optional[Dict[str, Any]] = None
    actual_output: Optional[Dict[str, Any]] = None
    contract_violated: bool = False
    silent_failure: bool = False
    error_message: Optional[str] = None


class BaseValidationStage(Stage):
    """
    Base stage with common validation logic.
    Demonstrates class inheritance for stages.
    """
    name = "base_validation"
    kind = StageKind.GUARD
    
    # Define required_fields as a list, not a dataclass field
    _required_fields: List[str] = ["user_id", "timestamp"]
    
    @property
    def required_fields(self) -> List[str]:
        return self._required_fields
    
    def validate_common(self, data: Dict[str, Any]) -> Optional[str]:
        """Common validation logic that derived stages can extend."""
        for field_name in self.required_fields:
            if field_name not in data or data[field_name] is None:
                return f"Missing required field: {field_name}"
        return None
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        input_data = ctx.snapshot.metadata or {}
        error = self.validate_common(input_data)
        if error:
            return StageOutput.fail(error=error)
        return StageOutput.ok(validated=True, base_validated=True)


class DerivedValidationStage(BaseValidationStage):
    """
    Derived stage that extends base validation.
    Tests if validation logic is properly chained.
    """
    name = "derived_validation"
    kind = StageKind.GUARD
    
    # Extended contract - adds more required fields
    _required_fields: List[str] = ["user_id", "timestamp", "session_id", "action"]
    
    @property
    def required_fields(self) -> List[str]:
        return self._required_fields
    
    def validate_common(self, data: Dict[str, Any]) -> Optional[str]:
        """Extend base validation with additional checks."""
        # Call parent validation first
        parent_error = super().validate_common(data)
        if parent_error:
            return parent_error
        return None
    
    def validate_derived(self, data: Dict[str, Any]) -> Optional[str]:
        """Additional validation specific to derived stage."""
        if "action" in data and data["action"] not in ["read", "write", "delete"]:
            return f"Invalid action: {data.get('action')}"
        return None
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        input_data = ctx.snapshot.metadata or {}
        
        # Chain validations
        error = self.validate_common(input_data)
        if error:
            return StageOutput.fail(error=error)
        
        error = self.validate_derived(input_data)
        if error:
            return StageOutput.fail(error=error)
        
        return StageOutput.ok(
            validated=True,
            base_validated=True,
            derived_validated=True,
        )


class ContractEnforcingStage(Stage):
    """
    Stage that enforces a specific contract on its output.
    Used to test if parent pipelines can enforce contracts on children.
    """
    name = "contract_enforcing"
    kind = StageKind.TRANSFORM
    
    contract_schema: Dict[str, Any] = field(default_factory=dict)
    
    def __init__(
        self,
        contract_schema: Optional[Dict[str, Any]] = None,
        name: str = "contract_enforcing",
    ):
        self.name = name
        self.contract_schema = contract_schema or {
            "required": ["result", "status"],
            "types": {"result": str, "status": str},
        }
    
    def validate_contract(self, output: Dict[str, Any]) -> Optional[str]:
        """Validate output against contract schema."""
        required = self.contract_schema.get("required", [])
        for field_name in required:
            if field_name not in output:
                return f"Contract violation: missing required field '{field_name}'"
        return None
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        output = {"result": "test_result", "status": "success"}
        
        error = self.validate_contract(output)
        if error:
            return StageOutput.fail(error=error)
        
        return StageOutput.ok(
            result=output["result"],
            status=output["status"],
            contract_validated=True,
        )


class SubpipelineParentStage(Stage):
    """
    Stage that spawns a child pipeline and tests contract inheritance.
    """
    name = "subpipeline_parent"
    kind = StageKind.TRANSFORM
    
    def __init__(self, child_pipeline: Optional[Pipeline] = None):
        self.child_pipeline = child_pipeline
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        # Fork context for child pipeline
        child_run_id = uuid.uuid4()
        parent_ctx = ctx.snapshot
        
        # Create child snapshot with inherited context
        child_snapshot = ContextSnapshot(
            run_id=RunIdentity(
                pipeline_run_id=child_run_id,
                request_id=parent_ctx.request_id,
                session_id=parent_ctx.session_id,
                user_id=parent_ctx.user_id,
                org_id=parent_ctx.org_id,
                interaction_id=parent_ctx.interaction_id,
            ),
            input_text=parent_ctx.input_text,
            topology="child_test_pipeline",
            execution_mode="test",
            metadata={
                "parent_stage": "subpipeline_parent",
                "parent_run_id": str(parent_ctx.pipeline_run_id),
            },
        )
        
        # Execute child pipeline if provided
        child_result = None
        if self.child_pipeline:
            try:
                from stageflow.stages.context import PipelineContext
                child_pipeline_ctx = PipelineContext(
                    pipeline_run_id=child_run_id,
                    request_id=parent_ctx.request_id,
                    session_id=parent_ctx.session_id,
                    user_id=parent_ctx.user_id,
                    org_id=parent_ctx.org_id,
                    interaction_id=parent_ctx.interaction_id,
                    topology="child_test_pipeline",
                    execution_mode="test",
                )
                graph = self.child_pipeline.build()
                child_outputs = await graph.run(
                    StageContext(
                        snapshot=child_snapshot,
                        inputs=ctx.inputs,
                        stage_name="child_runner",
                        timer=ctx.timer,
                    )
                )
                child_result = {"success": True, "outputs": child_outputs}
            except Exception as e:
                child_result = {"success": False, "error": str(e)}
        
        return StageOutput.ok(
            parent_result="completed",
            child_run_id=str(child_run_id),
            child_result=child_result,
            inherited_context={
                "user_id": str(parent_ctx.user_id) if parent_ctx.user_id else None,
                "org_id": str(parent_ctx.org_id) if parent_ctx.org_id else None,
            },
        )


class PolymorphicBaseStage(Stage):
    """
    Base stage for polymorphic hierarchy testing.
    """
    name = "polymorphic_base"
    kind = StageKind.TRANSFORM
    
    base_field: str = "base_value"
    
    def get_contract(self) -> Dict[str, Any]:
        """Return the contract for this stage type."""
        return {
            "required": ["output_type", "base_field"],
            "types": {"output_type": str, "base_field": str},
        }
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        return StageOutput.ok(
            output_type="base",
            base_field=self.base_field,
            contract=self.get_contract(),
        )


class PolymorphicDerivedStage(PolymorphicBaseStage):
    """
    Derived stage that extends polymorphic base.
    Tests if contracts are properly extended.
    """
    name = "polymorphic_derived"
    
    derived_field: str = "derived_value"
    
    def get_contract(self) -> Dict[str, Any]:
        """Return extended contract for derived stage."""
        base_contract = super().get_contract()
        return {
            "required": base_contract["required"] + ["derived_field"],
            "types": {**base_contract["types"], "derived_field": str},
        }
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        return StageOutput.ok(
            output_type="derived",
            base_field=self.base_field,
            derived_field=self.derived_field,
            contract=self.get_contract(),
        )


class ContractCompositionStage(Stage):
    """
    Stage that composes multiple contracts.
    Tests contract intersection patterns.
    """
    name = "contract_composition"
    kind = StageKind.GUARD
    
    def __init__(self, contracts: List[Dict[str, Any]]):
        self.contracts = contracts
    
    def validate_composed_contract(self, data: Dict[str, Any]) -> Optional[str]:
        """Validate against all composed contracts."""
        errors = []
        for i, contract in enumerate(self.contracts):
            required = contract.get("required", [])
            for field_name in required:
                if field_name not in data:
                    errors.append(f"Contract {i}: missing '{field_name}'")
        if errors:
            return "; ".join(errors)
        return None
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        input_data = ctx.snapshot.metadata or {}
        error = self.validate_composed_contract(input_data)
        if error:
            return StageOutput.fail(error=error)
        return StageOutput.ok(
            validated=True,
            contracts_composed=len(self.contracts),
        )


class OutputContractTestStage(Stage):
    """
    Stage that tests if contracts on OUTPUT are properly enforced.
    """
    name = "output_contract_test"
    kind = StageKind.TRANSFORM
    
    def __init__(self, expect_fields: List[str]):
        self.expect_fields = expect_fields
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        # Get expected output from upstream
        upstream = ctx.inputs.get("incomplete")
        
        # Access the StageOutput object correctly
        if upstream and hasattr(upstream, 'data'):
            upstream_data = upstream.data if hasattr(upstream.data, 'get') else {}
        else:
            upstream_data = upstream if hasattr(upstream, 'get') else {}
        
        contract_violated = False
        missing_fields = []
        
        for field_name in self.expect_fields:
            if field_name not in upstream_data:
                contract_violated = True
                missing_fields.append(field_name)
        
        return StageOutput.ok(
            contract_check_passed=not contract_violated,
            missing_fields=missing_fields if contract_violated else [],
            contract_violated=contract_violated,
        )


class SilentFailureTestStage(Stage):
    """
    Stage designed to test silent failure detection.
    Returns incomplete data without error.
    """
    name = "silent_failure_test"
    kind = StageKind.TRANSFORM
    
    # Contract that would expect these fields
    expected_contract = {
        "required": ["required_field_1", "required_field_2", "required_field_3"],
    }
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        # Simulate a stage that partially completes
        # Returns data but missing some required fields
        return StageOutput.ok(
            partial_data=True,
            # Missing required_field_2 and required_field_3 - silent failure
            required_field_1="value1",
            # required_field_2 and required_field_3 are missing
        )


# Test Pipelines


def create_subpipeline_test_pipeline() -> Pipeline:
    """Create pipeline to test subpipeline contract inheritance."""
    return (
        Pipeline()
        .with_stage("context_setup", ContextSetupStage, StageKind.TRANSFORM)
        .with_stage(
            "subpipeline_parent",
            SubpipelineParentStage,
            StageKind.TRANSFORM,
            dependencies=("context_setup",),
        )
        .with_stage(
            "verify_inheritance",
            InheritanceVerificationStage,
            StageKind.GUARD,
            dependencies=("subpipeline_parent",),
        )
    )


def create_inheritance_test_pipeline() -> Pipeline:
    """Create pipeline to test base/derived stage inheritance."""
    return (
        Pipeline()
        .with_stage("base_test", BaseValidationStage, StageKind.GUARD)
        .with_stage(
            "derived_test",
            DerivedValidationStage,
            StageKind.GUARD,
            dependencies=("base_test",),
        )
        .with_stage(
            "verify_chain",
            ChainVerificationStage,
            StageKind.GUARD,
            dependencies=("derived_test",),
        )
    )


def create_polymorphic_test_pipeline() -> Pipeline:
    """Create pipeline to test polymorphic stage hierarchies."""
    return (
        Pipeline()
        .with_stage("base_polymorphic", PolymorphicBaseStage, StageKind.TRANSFORM)
        .with_stage(
            "derived_polymorphic",
            PolymorphicDerivedStage,
            StageKind.TRANSFORM,
            dependencies=("base_polymorphic",),
        )
        .with_stage(
            "check_contracts",
            PolymorphicContractCheckStage,
            StageKind.GUARD,
            dependencies=("base_polymorphic", "derived_polymorphic"),
        )
    )


def create_composition_test_pipeline() -> Pipeline:
    """Create pipeline to test contract composition."""
    return (
        Pipeline()
        .with_stage(
            "composition",
            ContractCompositionStage,
            StageKind.GUARD,
            dependencies=(),
        )
    )


def create_silent_failure_pipeline() -> Pipeline:
    """Create pipeline to test silent failure detection."""
    return (
        Pipeline()
        .with_stage("silent_failure", SilentFailureTestStage, StageKind.TRANSFORM)
        .with_stage(
            "verify_missing",
            MissingFieldVerificationStage,
            StageKind.GUARD,
            dependencies=("silent_failure",),
        )
    )


class ContextSetupStage(Stage):
    """Stage that sets up context for subpipeline testing."""
    name = "context_setup"
    kind = StageKind.TRANSFORM
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        return StageOutput.ok(
            setup_complete=True,
            user_id=str(ctx.snapshot.user_id) if ctx.snapshot.user_id else None,
            org_id=str(ctx.snapshot.org_id) if ctx.snapshot.org_id else None,
        )


class InheritanceVerificationStage(Stage):
    """Stage that verifies contract inheritance worked correctly."""
    name = "verify_inheritance"
    kind = StageKind.GUARD
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        parent_output = ctx.inputs.get("subpipeline_parent")
        inherited = ctx.inputs.get_from("subpipeline_parent", "inherited_context")
        
        # Check if inheritance worked
        user_id_inherited = inherited and inherited.get("user_id") is not None
        org_id_inherited = inherited and inherited.get("org_id") is not None
        
        if not user_id_inherited:
            return StageOutput.fail(error="user_id not inherited by child")
        if not org_id_inherited:
            return StageOutput.fail(error="org_id not inherited by child")
        
        return StageOutput.ok(
            inheritance_verified=True,
            user_id_present=user_id_inherited,
            org_id_present=org_id_inherited,
        )


class ChainVerificationStage(Stage):
    """Stage that verifies validation chain worked."""
    name = "verify_chain"
    kind = StageKind.GUARD
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        # Use get_from to access specific key from specific stage output
        base_validated = ctx.inputs.get_from("derived_test", "base_validated", default=False)
        derived_validated = ctx.inputs.get_from("derived_test", "derived_validated", default=False)
        
        if not base_validated:
            return StageOutput.fail(error="Base validation did not run")
        if not derived_validated:
            return StageOutput.fail(error="Derived validation did not run")
        
        return StageOutput.ok(
            chain_verified=True,
            base_validation_passed=base_validated,
            derived_validation_passed=derived_validated,
        )


class PolymorphicContractCheckStage(Stage):
    """Stage that checks polymorphic contract consistency."""
    name = "check_contracts"
    kind = StageKind.GUARD
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        # Use get_from to access specific keys from stage outputs
        base_contract = ctx.inputs.get_from("base_polymorphic", "contract", default={})
        derived_contract = ctx.inputs.get_from("derived_polymorphic", "contract", default={})
        
        # Check if derived contract extends base
        base_required = set(base_contract.get("required", []))
        derived_required = set(derived_contract.get("required", []))
        
        # Derived should have at least the same required fields (narrowing) or more (extension)
        contract_extends = base_required.issubset(derived_required)
        
        return StageOutput.ok(
            contract_check=True,
            base_contract=base_contract,
            derived_contract=derived_contract,
            contract_extends_base=contract_extends,
        )


class MissingFieldVerificationStage(Stage):
    """Stage that verifies missing fields were detected."""
    name = "verify_missing"
    kind = StageKind.GUARD
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        # Use get_from to access specific key from specific stage output
        has_partial = ctx.inputs.get_from("silent_failure", "partial_data", default=False)
        
        # Check what fields are present in silent_failure output
        # Since we can't get all keys easily, we rely on what was logged
        # Expected contract fields
        expected = ["required_field_1", "required_field_2", "required_field_3"]
        
        # Get actual fields from the output data by checking each expected field
        actual = []
        for field in expected:
            value = ctx.inputs.get_from("silent_failure", field)
            if value is not None:
                actual.append(field)
        
        missing = set(expected) - set(actual)
        
        # This is a silent failure - output says partial_data=True but no error was raised
        silent_failure_detected = has_partial and len(missing) > 0
        
        return StageOutput.ok(
            missing_fields=list(missing),
            silent_failure_detected=silent_failure_detected,
            stage_reported_partial=has_partial,
        )
