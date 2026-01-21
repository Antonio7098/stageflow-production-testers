"""
WORK-009 Tool Output Validation - Test Scenarios

Defines test scenarios for tool output validation testing.
Each scenario describes an input, expected behavior, and pass/fail criteria.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class ScenarioType(Enum):
    BASELINE = "baseline"
    EDGE_CASE = "edge_case"
    CHAOS = "chaos"
    STRESS = "stress"
    SILENT_FAILURE = "silent_failure"


class Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ValidationSchema:
    """Schema that output should conform to."""
    type: str = "object"
    required: List[str] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TestScenario:
    """Definition of a test scenario for tool output validation."""
    id: str
    name: str
    description: str
    scenario_type: ScenarioType
    tool_name: str
    expected_schema: Optional[ValidationSchema] = None
    expected_behavior: str = ""
    actual_behavior: str = ""
    severity: Severity = Severity.MEDIUM
    passes_validation: bool = False
    has_silent_failure: bool = False
    error_message: Optional[str] = None
    notes: str = ""


# Baseline scenarios (happy path)
BASELINE_SCENARIOS = [
    TestScenario(
        id="VALID_001",
        name="Valid User Output",
        description="Tool returns valid user data matching expected schema",
        scenario_type=ScenarioType.BASELINE,
        tool_name="valid_user",
        expected_schema=ValidationSchema(
            type="object",
            required=["user_id", "name", "email", "age", "active"],
            properties={
                "user_id": {"type": "string"},
                "name": {"type": "string"},
                "email": {"type": "string"},
                "age": {"type": "integer"},
                "active": {"type": "boolean"},
                "roles": {"type": "array"},
                "profile": {"type": "object"},
            }
        ),
        expected_behavior="Output passes validation, no errors raised",
        severity=Severity.LOW,
        passes_validation=True,
        notes="Happy path - should always pass",
    ),
    TestScenario(
        id="VALID_002",
        name="Valid Output with Extra Fields",
        description="Tool returns valid data plus additional unexpected fields",
        scenario_type=ScenarioType.BASELINE,
        tool_name="extra_fields",
        expected_schema=ValidationSchema(
            type="object",
            required=["user_id", "name", "email"],
            properties={
                "user_id": {"type": "string"},
                "name": {"type": "string"},
                "email": {"type": "string"},
            }
        ),
        expected_behavior="Output passes validation, extra fields ignored",
        severity=Severity.LOW,
        passes_validation=True,
        notes="Extra fields should not cause validation failure",
    ),
    TestScenario(
        id="VALID_003",
        name="Valid Async Output",
        description="Tool returns valid data after async delay",
        scenario_type=ScenarioType.BASELINE,
        tool_name="async_delay",
        expected_schema=ValidationSchema(
            type="object",
            required=["status", "delay_ms"],
            properties={
                "status": {"type": "string"},
                "delay_ms": {"type": "number"},
                "timestamp": {"type": "string"},
            }
        ),
        expected_behavior="Output passes validation",
        severity=Severity.LOW,
        passes_validation=True,
        notes="Async operations should validate correctly",
    ),
]

# Edge case scenarios
EDGE_CASE_SCENARIOS = [
    TestScenario(
        id="EDGE_001",
        name="Missing Required Fields",
        description="Tool returns data missing required fields",
        scenario_type=ScenarioType.EDGE_CASE,
        tool_name="missing_fields",
        expected_schema=ValidationSchema(
            type="object",
            required=["user_id", "name", "email", "age"],
            properties={
                "user_id": {"type": "string"},
                "name": {"type": "string"},
                "email": {"type": "string"},
                "age": {"type": "integer"},
            }
        ),
        expected_behavior="Validation fails, error raised",
        severity=Severity.HIGH,
        passes_validation=False,
        notes="Missing required fields is a common validation failure",
    ),
    TestScenario(
        id="EDGE_002",
        name="Wrong Data Types",
        description="Tool returns data with incorrect types",
        scenario_type=ScenarioType.EDGE_CASE,
        tool_name="wrong_type",
        expected_schema=ValidationSchema(
            type="object",
            required=["user_id", "name", "email", "age", "active", "roles"],
            properties={
                "user_id": {"type": "string"},
                "name": {"type": "string"},
                "email": {"type": "string"},
                "age": {"type": "integer"},
                "active": {"type": "boolean"},
                "roles": {"type": "array"},
            }
        ),
        expected_behavior="Validation fails for type mismatches",
        severity=Severity.HIGH,
        passes_validation=False,
        notes="Type coercion may help but strict validation should fail",
    ),
    TestScenario(
        id="EDGE_003",
        name="Null Values",
        description="Tool returns null values for non-nullable fields",
        scenario_type=ScenarioType.EDGE_CASE,
        tool_name="null_values",
        expected_schema=ValidationSchema(
            type="object",
            required=["user_id", "name", "email", "age"],
            properties={
                "user_id": {"type": "string"},
                "name": {"type": "string"},
                "email": {"type": "string"},
                "age": {"type": "integer"},
            }
        ),
        expected_behavior="Validation fails due to null values",
        severity=Severity.MEDIUM,
        passes_validation=False,
        notes="Null handling depends on schema configuration",
    ),
    TestScenario(
        id="EDGE_004",
        name="Empty Data",
        description="Tool returns empty data object",
        scenario_type=ScenarioType.EDGE_CASE,
        tool_name="empty_data",
        expected_schema=ValidationSchema(
            type="object",
            required=["user_id", "name"],
            properties={
                "user_id": {"type": "string"},
                "name": {"type": "string"},
            }
        ),
        expected_behavior="Validation fails due to missing required fields",
        severity=Severity.MEDIUM,
        passes_validation=False,
        notes="Empty data should fail when fields are required",
    ),
    TestScenario(
        id="EDGE_005",
        name="Nested Type Mismatch",
        description="Tool returns data with invalid nested structure",
        scenario_type=ScenarioType.EDGE_CASE,
        tool_name="nested_invalid",
        expected_schema=ValidationSchema(
            type="object",
            required=["order_id", "items", "total", "customer"],
            properties={
                "order_id": {"type": "string"},
                "items": {"type": "array"},
                "total": {"type": "number"},
                "customer": {"type": "object"},
            }
        ),
        expected_behavior="Validation fails at nested level",
        severity=Severity.HIGH,
        passes_validation=False,
        notes="Nested validation is important for complex data",
    ),
    TestScenario(
        id="EDGE_006",
        name="Malformed Nested Data",
        description="Tool returns data with malformed nested JSON-like string",
        scenario_type=ScenarioType.EDGE_CASE,
        tool_name="malformed_data",
        expected_schema=ValidationSchema(
            type="object",
            required=["user_id", "name", "metadata"],
            properties={
                "user_id": {"type": "string"},
                "name": {"type": "string"},
                "metadata": {"type": "object"},
            }
        ),
        expected_behavior="Validation fails due to malformed data",
        severity=Severity.HIGH,
        passes_validation=False,
        notes="Malformed nested data is a security risk",
    ),
]

# Chaos scenarios (adversarial)
CHAOS_SCENARIOS = [
    TestScenario(
        id="CHAOS_001",
        name="Silent Failure - Appears Valid",
        description="Tool returns success=True but data is invalid type",
        scenario_type=ScenarioType.CHAOS,
        tool_name="silent_failure",
        expected_schema=ValidationSchema(
            type="object",
            required=["success", "data"],
            properties={
                "success": {"type": "boolean"},
                "data": {"type": "object"},
            }
        ),
        expected_behavior="Silent failure - passes as valid but data is wrong type",
        severity=Severity.CRITICAL,
        passes_validation=False,
        has_silent_failure=True,
        notes="CRITICAL: This is a silent failure that goes undetected",
    ),
    TestScenario(
        id="CHAOS_002",
        name="Circular References",
        description="Tool returns data with circular references",
        scenario_type=ScenarioType.CHAOS,
        tool_name="circular_ref",
        expected_schema=ValidationSchema(
            type="object",
            required=["name", "child"],
            properties={
                "name": {"type": "string"},
                "child": {"type": "object"},
            }
        ),
        expected_behavior="May cause infinite loop or memory issues",
        severity=Severity.HIGH,
        has_silent_failure=True,
        notes="Circular references can cause runtime errors",
    ),
    TestScenario(
        id="CHAOS_003",
        name="Large Output",
        description="Tool returns very large output (1MB+)",
        scenario_type=ScenarioType.CHAOS,
        tool_name="large_output",
        expected_schema=ValidationSchema(
            type="object",
            required=["items", "total"],
            properties={
                "items": {"type": "array"},
                "total": {"type": "integer"},
            }
        ),
        expected_behavior="May cause memory issues or performance degradation",
        severity=Severity.MEDIUM,
        passes_validation=True,
        notes="Large outputs should be handled efficiently",
    ),
    TestScenario(
        id="CHAOS_004",
        name="Deep Nesting",
        description="Tool returns deeply nested data (20+ levels)",
        scenario_type=ScenarioType.CHAOS,
        tool_name="deep_nesting",
        expected_schema=ValidationSchema(
            type="object",
            required=["id", "deep"],
            properties={
                "id": {"type": "string"},
                "deep": {"type": "object"},
            }
        ),
        expected_behavior="May cause stack overflow or performance issues",
        severity=Severity.MEDIUM,
        passes_validation=True,
        notes="Deep nesting should have reasonable limits",
    ),
    TestScenario(
        id="CHAOS_005",
        name="Inconsistent Types",
        description="Tool returns different types based on input",
        scenario_type=ScenarioType.CHAOS,
        tool_name="inconsistent_type",
        expected_schema=ValidationSchema(
            type="object",
            required=["data"],
            properties={
                "data": {"type": "object"},
            }
        ),
        expected_behavior="Type inconsistency causes validation failures",
        severity=Severity.HIGH,
        passes_validation=False,
        notes="Inconsistent types are a common source of bugs",
    ),
    TestScenario(
        id="CHAOS_006",
        name="Partial Success",
        description="Tool reports success but critical data is missing",
        scenario_type=ScenarioType.CHAOS,
        tool_name="partial_success",
        expected_schema=ValidationSchema(
            type="object",
            required=["status", "items", "total_count", "next_page_token"],
            properties={
                "status": {"type": "string"},
                "items": {"type": "array"},
                "total_count": {"type": "integer"},
                "next_page_token": {"type": "string"},
            }
        ),
        expected_behavior="Silent failure - appears to succeed but is incomplete",
        severity=Severity.HIGH,
        has_silent_failure=True,
        notes="Partial success is a common silent failure pattern",
    ),
]

# All scenarios combined
ALL_SCENARIOS = (
    BASELINE_SCENARIOS +
    EDGE_CASE_SCENARIOS +
    CHAOS_SCENARIOS
)


def get_scenarios_by_type(scenario_type: ScenarioType) -> List[TestScenario]:
    """Filter scenarios by type."""
    return [s for s in ALL_SCENARIOS if s.scenario_type == scenario_type]


def get_scenarios_by_severity(severity: Severity) -> List[TestScenario]:
    """Filter scenarios by severity."""
    return [s for s in ALL_SCENARIOS if s.severity == severity]


def get_silent_failure_scenarios() -> List[TestScenario]:
    """Get all scenarios that may cause silent failures."""
    return [s for s in ALL_SCENARIOS if s.has_silent_failure]


def run_scenario_validation(
    scenario: TestScenario,
    tool_output: dict,
) -> Dict[str, Any]:
    """
    Validate a tool output against a scenario's expected schema.
    
    Returns:
        Dict with validation results including:
        - passes: bool
        - errors: list of validation errors
        - is_silent_failure: bool
    """
    if scenario.expected_schema is None:
        return {
            "passes": True,
            "errors": [],
            "is_silent_failure": False,
        }
    
    schema = scenario.expected_schema
    errors = []
    
    # Check required fields
    if schema.required:
        for field_name in schema.required:
            if field_name not in tool_output:
                errors.append(f"Missing required field: {field_name}")
    
    # Check types if output is a dict
    if isinstance(tool_output, dict) and schema.properties:
        for field_name, field_schema in schema.properties.items():
            if field_name in tool_output and tool_output[field_name] is not None:
                expected_type = field_schema.get("type", "any")
                actual_value = tool_output[field_name]
                actual_type = type(actual_value).__name__
                
                type_map = {
                    "string": str,
                    "integer": int,
                    "number": (int, float),
                    "boolean": bool,
                    "array": list,
                    "object": dict,
                }
                
                if expected_type in type_map:
                    if not isinstance(actual_value, type_map[expected_type]):
                        # Special case: integer can be float that is whole number
                        if expected_type == "integer" and isinstance(actual_value, float):
                            if actual_value.is_integer():
                                continue
                        errors.append(
                            f"Field '{field_name}': expected {expected_type}, got {actual_type}"
                        )
    
    # Determine if this is a silent failure
    # Silent failure = validation fails but no error is raised
    is_silent_failure = (
        len(errors) > 0 and
        scenario.has_silent_failure
    )
    
    return {
        "passes": len(errors) == 0,
        "errors": errors,
        "is_silent_failure": is_silent_failure,
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
    }
