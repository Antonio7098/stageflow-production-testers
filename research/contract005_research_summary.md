# CONTRACT-005 Research Summary: Optional vs Required Field Enforcement

**Run ID**: run-2026-01-19-001  
**Agent**: claude-3.5-sonnet  
**Date**: 2026-01-19  
**Focus**: Stage contract field validation and enforcement

---

## 1. Executive Summary

This research examines optional vs required field enforcement patterns in the Stageflow framework, focusing on how stage contracts handle field validation, what silent failure modes exist, and how field contracts can fail in production environments. The investigation covers industry best practices, Pydantic validation patterns, and Stageflow-specific implementation details.

**Key Findings:**
- Silent failures in field validation are a critical risk in production pipelines
- Pydantic's lax mode can mask type coercion issues that become bugs in strict contexts
- Stageflow's StageInputs provides explicit dependency access but doesn't enforce output schema validation
- Missing field validation in stage outputs can lead to cascading failures downstream

---

## 2. Industry Context

### 2.1 The Silent Failure Problem

Data pipelines don't usually fail loudly. They fail quietly while everyone still trusts the numbers. This is particularly dangerous in field validation:

- **Silent Type Coercion**: Pydantic's default behavior converts `"123"` to `123` for int fields, which can mask data quality issues
- **Missing Required Fields**: When a required field is missing, downstream stages may receive `None` or empty values without explicit error handling
- **Partial Validation**: Some fields may be validated while others are silently skipped due to validation errors

### 2.2 Common Field Validation Patterns

| Pattern | Description | Risk Level |
|---------|-------------|------------|
| Required fields | Fields that must be present | High if not enforced |
| Optional fields | Fields that may be absent | Medium |
| Default values | Fallback values when field missing | Low |
| Computed fields | Fields calculated from others | Medium |
| Conditional required | Fields required based on context | High |

### 2.3 Regulatory Considerations

- **GDPR**: Personal data fields must be explicitly handled; missing consent fields can be a violation
- **HIPAA**: Medical records require complete patient identifiers; missing fields can break audit trails
- **PCI-DSS**: Transaction records require specific fields; incomplete records are non-compliant

---

## 3. Technical Context

### 3.1 Pydantic Validation Modes

Pydantic v2 provides multiple validation modes:

```python
# Lax mode (default) - coerces values
from pydantic import BaseModel

class Model(BaseModel):
    x: int

m = Model(x="123")  # Works: coerced to int
```

```python
# Strict mode - requires exact types
from pydantic import BaseModel, StrictInt

class Model(BaseModel):
    x: StrictInt  # or model_config = {"strict": True}

m = Model(x="123")  # Fails: no coercion
```

### 3.2 Field Validator Patterns

```python
from pydantic import BaseModel, field_validator

class User(BaseModel):
    name: str
    
    @field_validator('name', mode='before')
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError('Name cannot be empty')
        return v
```

### 3.3 Optional vs Required Fields

```python
from typing import Optional

class Model(BaseModel):
    required_field: str          # Required
    optional_field: str = None   # Optional with None default
    defaulted_field: str = "default"  # Optional with default
```

---

## 4. Stageflow-Specific Analysis

### 4.1 StageOutput Contract

Stageflow uses `StageOutput` for stage contracts:

```python
from stageflow import StageOutput

# Success with data
return StageOutput.ok(key="value")

# Fail with error
return StageOutput.fail(error="Missing required field")
```

**Key observation**: `StageOutput.data` is a `dict[str, Any]` with no schema enforcement.

### 4.2 StageInputs Access Patterns

```python
from stageflow.stages.inputs import StageInputs

# Get value from any prior stage (non-validating)
text = ctx.inputs.get("text", default="")

# Get from specific stage (validates dependency)
route = ctx.inputs.get_from("router", "route", default="general")

# Require value (raises KeyError if missing)
token = ctx.inputs.require_from("auth", "token")
```

**Risk**: `get()` returns `None` if not found, which can lead to silent failures if downstream stages don't validate.

### 4.3 ContextSnapshot Fields

```python
from stageflow.context import ContextSnapshot

snapshot = ContextSnapshot(
    run_id=run_id,
    input_text="Hello!",
    # Optional fields (None by default):
    # - conversation
    # - enrichments
    # - extensions
    # - metadata
)
```

**Observation**: Optional fields use `None` as default, but there's no validation that required fields are actually populated.

---

## 5. Known Failure Modes

### 5.1 Silent Failure Patterns

| Pattern | Description | Detection Difficulty |
|---------|-------------|---------------------|
| Swallowed exceptions | Try/except with pass or no logging | High |
| Incorrect defaults | Functions returning defaults instead of errors | Medium |
| Partial state | Operations that partially succeed | High |
| Type coercion bugs | Silent type conversions causing issues | Low |
| Missing validation | No schema validation on outputs | Medium |

### 5.2 Stageflow-Specific Risks

1. **OutputBag Race Conditions**: Multiple stages writing to same keys can cause inconsistent state (see BUG-003, BUG-004)

2. **Missing Field Validation**: Stages may output incomplete data without error

3. **ContextSnapshot Serialization**: Large integers can cause serialization failures (BUG-005)

4. **Deserialization Performance**: Non-linear scaling at larger data sizes (BUG-006)

---

## 6. Hypotheses to Test

| # | Hypothesis | Test Approach |
|---|------------|---------------|
| H1 | StageOutput doesn't validate required fields | Try to retrieve fields that weren't output |
| H2 | StageInputs.get() silently returns None | Test accessing non-existent keys |
| H3 | Type coercion happens silently in context | Pass string where int expected |
| H4 | Missing required fields don't raise errors | Test pipeline with incomplete outputs |
| H5 | Default values mask validation failures | Test with explicit None vs missing |

---

## 7. Success Criteria

1. **Baseline**: Create a pipeline with stages that output required fields and verify successful execution
2. **Edge Cases**: Test missing fields, wrong types, empty values, and verify error handling
3. **Stress**: High-concurrency tests to find race conditions in field access
4. **Silent Failures**: Hunt for cases where validation passes but data is incorrect
5. **Documentation**: Document all findings and patterns

---

## 8. References

### Stageflow Documentation
- `stageflow-docs/index.md` - Framework overview
- `stageflow-docs/api/inputs.md` - StageInputs API
- `stageflow-docs/api/context.md` - Context API
- `stageflow-docs/advanced/errors.md` - Error handling
- `stageflow-docs/guides/stages.md` - Stage building guide

### Pydantic Documentation
- https://docs.pydantic.dev/latest/concepts/fields/ - Field customization
- https://docs.pydantic.dev/latest/concepts/strict_mode/ - Strict validation
- https://docs.pydantic.dev/latest/errors/validation_errors/ - Error handling

### Industry Resources
- https://medium.com/@dixitaniket76/why-most-data-pipelines-fail-in-production-and-how-to-prevent-it-8d3ed1589f79 - Silent failures
- https://airbyte.com/data-engineering-resources/how-to-write-test-cases-for-etl-pipelines-a-beginners-guide - ETL testing

---

## 9. Next Steps

1. Build baseline test pipeline with proper field contracts
2. Create edge case tests for missing/wrong field types
3. Implement chaos tests for race conditions
4. Execute all tests and log findings
5. Generate final report with recommendations

---

*Research completed: 2026-01-19*
