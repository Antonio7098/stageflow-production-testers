"""
Test pipelines for CONTRACT-007: Custom Validator Integration

This module contains test pipelines for validating custom validator
integration capabilities in Stageflow.
"""

import sys
import uuid
import json
import logging
from datetime import datetime
from typing import Any, Optional
from pathlib import Path

import stageflow as sf
from stageflow import (
    Pipeline,
    StageKind,
    StageOutput,
    StageContext,
    Stage,
    PipelineContext,
    create_stage_context,
    get_default_interceptors,
)
from stageflow.context import ContextSnapshot

# Add mocks to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from mocks.validators import (
    Validator,
    ValidationResult,
    StringValidator,
    EmailValidator,
    NumberValidator,
    ChoiceValidator,
    LengthValidator,
    RangeValidator,
    CompositeValidator,
    create_string_validator,
    create_email_validator,
    create_number_validator,
    create_choice_validator,
    create_length_validator,
    create_range_validator,
)
from mocks.validation_data import MockDataGenerator

logger = logging.getLogger(__name__)


class ValidationTestCase:
    """Test case for validation testing."""

    def __init__(
        self,
        name: str,
        input_data: dict,
        validators: list[Validator],
        expected_valid: bool,
        expected_errors: Optional[list[str]] = None,
    ):
        self.name = name
        self.input_data = input_data
        self.validators = validators
        self.expected_valid = expected_valid
        self.expected_errors = expected_errors or []


class BaseValidationStage(Stage):
    """Base stage for validation testing."""

    name = "base_validation"
    kind = StageKind.GUARD

    def __init__(self, validators: list[Validator], field_name: str = None):
        self.validators = validators
        self.field_name = field_name

    async def execute(self, ctx: sf.StageContext) -> StageOutput:
        try:
            # Get value to validate from context
            # Stageflow uses input_text and snapshot, not a generic 'data' field
            if self.field_name:
                # Try to get from snapshot first
                value = getattr(ctx.snapshot, self.field_name, None)
                if value is None:
                    value = ctx.inputs.get(self.field_name)
            else:
                # Validate using input_text or first string field
                value = ctx.snapshot.input_text if ctx.snapshot.input_text else ""

            # Run all validators
            errors = []
            for validator in self.validators:
                result = validator.validate(value, {
                    "input_text": ctx.snapshot.input_text,
                    "user_id": str(ctx.snapshot.user_id) if ctx.snapshot.user_id else None,
                })
                if not result.is_valid:
                    errors.append({
                        "validator": validator.name,
                        "message": result.message,
                        "field": result.field_name,
                        "code": result.error_code,
                    })

            if errors:
                return StageOutput.fail(
                    error=f"Validation failed with {len(errors)} error(s)",
                    data={
                        "validation_errors": errors,
                        "input_value": value,
                    },
                )

            return StageOutput.ok(
                validated=True,
                input_value=value,
            )

        except Exception as e:
            logger.exception("Unexpected error in validation stage")
            return StageOutput.fail(
                error=f"Validation error: {str(e)}",
                data={"exception_type": type(e).__name__},
            )


class DataTransformStage(Stage):
    """Stage that produces data for validation."""

    name = "data_transform"
    kind = StageKind.TRANSFORM

    def __init__(self, data_provider: callable):
        self.data_provider = data_provider

    async def execute(self, ctx: sf.StageContext) -> StageOutput:
        try:
            data = self.data_provider()
            return StageOutput.ok(**data)
        except Exception as e:
            return StageOutput.fail(error=str(e))


class ValidationResultStage(Stage):
    """Stage that records validation results."""

    name = "result_recorder"
    kind = StageKind.WORK

    def __init__(self, results_storage: list):
        self.results_storage = results_storage

    async def execute(self, ctx: sf.StageContext) -> StageOutput:
        try:
            # Get validation result from upstream
            validation_result = ctx.inputs.get("validation_result")

            # Store result
            self.results_storage.append({
                "timestamp": datetime.utcnow().isoformat(),
                "passed": validation_result.get("validated", False) if validation_result else False,
                "errors": validation_result.get("validation_errors", []) if validation_result else [],
                "data": validation_result.get("input_data", {}) if validation_result else {},
            })

            return StageOutput.ok(recorded=True)

        except Exception as e:
            return StageOutput.fail(error=str(e))


class BaselineValidationPipeline:
    """Baseline pipeline for happy path validation testing."""

    def __init__(self):
        self.results = []

    def build(self) -> Pipeline:
        validators = [
            create_string_validator(min_length=3, max_length=20),
            create_email_validator(),
        ]

        return (
            Pipeline()
            .with_stage("transform", DataTransformStage(MockDataGenerator.valid_user_data), StageKind.TRANSFORM)
            .with_stage("validate", BaseValidationStage(validators), StageKind.GUARD, dependencies=("transform",))
            .with_stage("record", ValidationResultStage(self.results), StageKind.WORK, dependencies=("validate",))
        )

    def run(self):
        """Execute the baseline pipeline."""
        pipeline = self.build()
        graph = pipeline.build()

        ctx = create_stage_context(
            snapshot=ContextSnapshot(
                data={},
                input_text="",
                user_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
            ),
        )

        try:
            results = graph.run(ctx)
            return results
        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}")
            raise


class CompositeValidationPipeline:
    """Pipeline testing composite validators."""

    def __init__(self):
        self.results = []

    def build(self) -> Pipeline:
        email_validators = [
            create_string_validator(min_length=5),
            create_email_validator(),
        ]

        choice_validators = [
            create_choice_validator(["pending", "processing", "completed", "cancelled"]),
        ]

        return (
            Pipeline()
            .with_stage("transform", DataTransformStage(MockDataGenerator.valid_order_data), StageKind.TRANSFORM)
            .with_stage("validate_email", BaseValidationStage(email_validators, "email"), StageKind.GUARD, dependencies=("transform",))
            .with_stage("validate_status", BaseValidationStage(choice_validators, "status"), StageKind.GUARD, dependencies=("transform",))
            .with_stage("record", ValidationResultStage(self.results), StageKind.WORK, dependencies=("validate_email", "validate_status"))
        )


class EdgeCaseValidationPipeline:
    """Pipeline testing edge cases."""

    def __init__(self):
        self.results = []

    def build(self, test_case: str) -> Pipeline:
        validators = [
            create_string_validator(min_length=1, max_length=100),
            create_number_validator(min_value=0, max_value=120),
            create_choice_validator(["active", "inactive", "pending"]),
        ]

        data_providers = {
            "unicode": MockDataGenerator.edge_case_unicode_data,
            "whitespace": MockDataGenerator.edge_case_whitespace_data,
            "nulls": MockDataGenerator.edge_case_null_data,
            "empty": MockDataGenerator.edge_case_empty_data,
            "boundaries": MockDataGenerator.edge_case_boundary_values,
        }

        data_provider = data_providers.get(test_case, MockDataGenerator.valid_user_data)

        return (
            Pipeline()
            .with_stage("transform", DataTransformStage(data_provider), StageKind.TRANSFORM)
            .with_stage("validate", BaseValidationStage(validators), StageKind.GUARD, dependencies=("transform",))
            .with_stage("record", ValidationResultStage(self.results), StageKind.WORK, dependencies=("validate",))
        )


class ErrorRecoveryPipeline:
    """Pipeline testing validation error recovery."""

    def __init__(self):
        self.results = []
        self.error_count = 0
        self.recovery_count = 0

    def build(self) -> Pipeline:
        validators = [
            create_number_validator(min_value=0),
        ]

        return (
            Pipeline()
            .with_stage("transform", DataTransformStage(MockDataGenerator.negative_number_data), StageKind.TRANSFORM)
            .with_stage("validate", BaseValidationStage(validators), StageKind.GUARD, dependencies=("transform",))
            .with_stage("recover", self._recovery_stage(), StageKind.WORK, dependencies=("validate",))
            .with_stage("record", ValidationResultStage(self.results), StageKind.WORK, dependencies=("recover",))
        )

    class _recovery_stage(Stage):
        name = "recovery"
        kind = StageKind.WORK

        async def execute(self, ctx: sf.StageContext) -> StageOutput:
            # Check if validation failed
            validation_result = ctx.inputs.get("validation_result")

            if validation_result and validation_result.get("validation_errors"):
                # Attempt recovery by using default values
                default_data = {
                    "quantity": 1,
                    "price": 0.0,
                    "corrected": True,
                }
                return StageOutput.ok(**default_data)

            return StageOutput.ok(corrected=False)


class StressValidationPipeline:
    """Pipeline for stress testing validation."""

    def __init__(self, concurrent_requests: int = 100):
        self.concurrent_requests = concurrent_requests
        self.results = []

    def build(self) -> Pipeline:
        validators = [
            create_string_validator(min_length=1, max_length=50),
            create_email_validator(),
            create_number_validator(min_value=0, max_value=150),
        ]

        def batch_provider():
            return MockDataGenerator.scale_data_batch(10)

        return (
            Pipeline()
            .with_stage("transform", DataTransformStage(batch_provider), StageKind.TRANSFORM)
            .with_stage("validate", BaseValidationStage(validators), StageKind.GUARD, dependencies=("transform",))
            .with_stage("record", ValidationResultStage(self.results), StageKind.WORK, dependencies=("validate",))
        )


class ChaosValidationPipeline:
    """Pipeline for chaos testing validation (adversarial inputs)."""

    def __init__(self):
        self.results = []

    def build(self, test_type: str) -> Pipeline:
        validators = [
            create_string_validator(min_length=1, max_length=1000),
        ]

        data_providers = {
            "sql_injection": MockDataGenerator.adversarial_sql_injection,
            "xss": MockDataGenerator.adversarial_xss,
            "unicode_overflow": MockDataGenerator.adversarial_unicode_overflow,
        }

        data_provider = data_providers.get(test_type, MockDataGenerator.valid_user_data)

        return (
            Pipeline()
            .with_stage("transform", DataTransformStage(data_provider), StageKind.TRANSFORM)
            .with_stage("validate", BaseValidationStage(validators), StageKind.GUARD, dependencies=("transform",))
            .with_stage("record", ValidationResultStage(self.results), StageKind.WORK, dependencies=("validate",))
        )


class CustomValidatorRegistrationStage(Stage):
    """Stage demonstrating custom validator registration pattern."""

    name = "custom_validator_registration"
    kind = StageKind.GUARD

    def __init__(self):
        self._validator_registry = {}

    def register_validator(self, name: str, validator: Validator):
        """Register a custom validator."""
        self._validator_registry[name] = validator

    async def execute(self, ctx: sf.StageContext) -> StageOutput:
        try:
            # Get validators to run from context or configuration
            validator_names = ctx.config.get("validators", [])

            errors = []
            for name in validator_names:
                validator = self._validator_registry.get(name)
                if validator:
                    # Get value to validate
                    value = ctx.snapshot.data.get("value_to_validate")

                    result = validator.validate(value, ctx.snapshot.data if hasattr(ctx.snapshot, 'data') else None)
                    if not result.is_valid:
                        errors.append({
                            "validator": name,
                            "message": result.message,
                            "code": result.error_code,
                        })

            if errors:
                return StageOutput.fail(
                    error=f"Validation failed with {len(errors)} error(s)",
                    data={"validation_errors": errors},
                )

            return StageOutput.ok(validated=True)

        except Exception as e:
            return StageOutput.fail(error=str(e))


class ValidatorCompositionPipeline:
    """Pipeline demonstrating validator composition patterns."""

    def __init__(self):
        self.results = []

    def build(self, composition_type: str) -> Pipeline:
        if composition_type == "sequential":
            validators = [
                create_string_validator(min_length=3),
                create_email_validator(),
            ]
        elif composition_type == "choice_based":
            validators = [
                create_choice_validator(["a", "b", "c"]),
            ]
        elif composition_type == "length_based":
            validators = [
                create_length_validator(min_items=1, max_items=10),
            ]
        else:
            validators = []

        return (
            Pipeline()
            .with_stage("transform", DataTransformStage(MockDataGenerator.valid_user_data), StageKind.TRANSFORM)
            .with_stage("validate", BaseValidationStage(validators), StageKind.GUARD, dependencies=("transform",))
            .with_stage("record", ValidationResultStage(self.results), StageKind.WORK, dependencies=("validate",))
        )


def run_validation_test(test_case: ValidationTestCase) -> dict:
    """Run a single validation test case."""
    pipeline = (
        Pipeline()
        .with_stage(
            "validate",
            BaseValidationStage(test_case.validators, None),
            StageKind.GUARD,
        )
    )

    graph = pipeline.build()

    from stageflow.context import ContextSnapshot, RunIdentity
    from stageflow import StageContext, StageInputs, PipelineTimer

    run_id = RunIdentity(
        pipeline_run_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        interaction_id=uuid.uuid4(),
    )

    snapshot = ContextSnapshot(
        run_id=run_id,
        input_text=test_case.input_data.get("email", ""),
    )

    ctx = StageContext(
        snapshot=snapshot,
        inputs=StageInputs(snapshot=snapshot),
        stage_name="validation_test",
        timer=PipelineTimer(),
    )

    try:
        results = graph.run(ctx)
        validate_result = results.get("validate")

        if validate_result and validate_result.status.value == "ok":
            actual_valid = True
        else:
            actual_valid = False

        return {
            "test_name": test_case.name,
            "expected_valid": test_case.expected_valid,
            "actual_valid": actual_valid,
            "passed": actual_valid == test_case.expected_valid,
            "output": validate_result.data if validate_result else None,
        }
    except Exception as e:
        return {
            "test_name": test_case.name,
            "expected_valid": test_case.expected_valid,
            "actual_valid": False,
            "passed": False,
            "error": str(e),
        }


def create_validator_test_suite() -> list[ValidationTestCase]:
    """Create a comprehensive test suite for validators."""
    return [
        # Happy path tests
        ValidationTestCase(
            "valid_email",
            MockDataGenerator.valid_user_data(),
            [create_email_validator()],
            expected_valid=True,
        ),
        ValidationTestCase(
            "valid_string_length",
            {"username": "john_doe"},
            [create_string_validator(min_length=3, max_length=20)],
            expected_valid=True,
        ),
        ValidationTestCase(
            "valid_number_range",
            {"age": 25},
            [create_number_validator(min_value=0, max_value=120)],
            expected_valid=True,
        ),
        ValidationTestCase(
            "valid_choice",
            {"status": "pending"},
            [create_choice_validator(["pending", "processing", "completed"])],
            expected_valid=True,
        ),
        ValidationTestCase(
            "valid_length",
            {"items": [1, 2, 3]},
            [create_length_validator(min_items=1, max_items=10)],
            expected_valid=True,
        ),

        # Edge case tests
        ValidationTestCase(
            "empty_string_allowed",
            {"username": ""},
            [create_string_validator(min_length=0, max_length=20)],
            expected_valid=True,
        ),
        ValidationTestCase(
            "boundary_min_value",
            {"age": 0},
            [create_number_validator(min_value=0, max_value=120)],
            expected_valid=True,
        ),
        ValidationTestCase(
            "boundary_max_value",
            {"age": 120},
            [create_number_validator(min_value=0, max_value=120)],
            expected_valid=True,
        ),

        # Failure tests
        ValidationTestCase(
            "invalid_email",
            MockDataGenerator.invalid_email_data(),
            [create_email_validator()],
            expected_valid=False,
            expected_errors=["INVALID_FORMAT"],
        ),
        ValidationTestCase(
            "string_too_short",
            {"username": "ab"},
            [create_string_validator(min_length=3, max_length=20)],
            expected_valid=False,
            expected_errors=["TOO_SHORT"],
        ),
        ValidationTestCase(
            "string_too_long",
            {"description": "x" * 1001},
            [create_string_validator(min_length=0, max_length=1000)],
            expected_valid=False,
            expected_errors=["TOO_LONG"],
        ),
        ValidationTestCase(
            "number_negative",
            {"quantity": -5},
            [create_number_validator(min_value=0)],
            expected_valid=False,
            expected_errors=["BELOW_MIN"],
        ),
        ValidationTestCase(
            "number_above_max",
            {"age": 150},
            [create_number_validator(min_value=0, max_value=120)],
            expected_valid=False,
            expected_errors=["ABOVE_MAX"],
        ),
        ValidationTestCase(
            "invalid_choice",
            {"status": "invalid"},
            [create_choice_validator(["pending", "processing", "completed"])],
            expected_valid=False,
            expected_errors=["NOT_ALLOWED"],
        ),
        ValidationTestCase(
            "list_too_short",
            {"items": []},
            [create_length_validator(min_items=1, max_items=10)],
            expected_valid=False,
            expected_errors=["TOO_FEW"],
        ),
        ValidationTestCase(
            "list_too_long",
            {"items": list(range(20))},
            [create_length_validator(min_items=1, max_items=10)],
            expected_valid=False,
            expected_errors=["TOO_MANY"],
        ),
    ]


if __name__ == "__main__":
    # Run basic validation test
    print("Running validation test suite...")

    test_suite = create_validator_test_suite()
    results = []

    for test_case in test_suite:
        result = run_validation_test(test_case)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] {test_case.name}")

    passed = sum(1 for r in results if r["passed"])
    print(f"\nTotal: {len(results)} tests, {passed} passed, {len(results) - passed} failed")
