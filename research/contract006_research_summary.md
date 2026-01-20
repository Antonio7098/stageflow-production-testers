# CONTRACT-006: Nested Object Validation Depth - Research Summary

**Run ID**: run-2026-01-19-001
**Agent**: claude-3.5-sonnet
**Target**: Nested object validation depth
**Priority**: P2
**Risk Class**: Moderate
**Date**: 2026-01-19

---

## 1. Industry Context

Nested object validation is a critical concern across regulated industries where data structures are deeply hierarchical:

### 1.1 Healthcare (HL7 FHIR)
Healthcare data follows HL7 FHIR standards with deeply nested resources:
- Patient -> Identifier -> System/Value
- Observation -> Component -> ValueQuantity -> Code/Value/Unit
- DiagnosticReport -> Result[] -> Reference

**Requirement**: Nested field validation depth must handle 5-10 levels of nesting with strict type enforcement.

### 1.2 Finance (Financial Instruments)
Complex financial products require validation of nested structures:
- Portfolio -> Holdings[] -> Security -> Pricing -> Adjustments[]
- Transaction -> Counterparty -> Address -> Country/PostalCode

**Requirement**: Deeply nested monetary values and dates must be validated with precision.

### 1.3 Legal (Contract Documents)
Legal documents contain nested clauses and definitions:
- Contract -> Articles[] -> Sections[] -> Paragraphs[]
- Definition -> Terms[] -> References[] -> Context

**Requirement**: Nested references must be validated for circular dependencies.

---

## 2. Technical Context

### 2.1 State of the Art: Pydantic Nested Validation

Pydantic v2 provides robust nested model validation:

```python
from pydantic import BaseModel, field_validator

class Address(BaseModel):
    street: str
    city: str
    zip_code: str

class Person(BaseModel):
    name: str
    address: Address  # Nested validation
    contacts: list[Address]  # List of nested models
```

**Key Features:**
- Recursive model validation
- Depth-limited validation (configurable `max_depth`)
- Custom validators at each nesting level
- Strict mode for complete validation

### 2.2 Known Failure Modes

| Failure Mode | Description | Impact |
|--------------|-------------|--------|
| **Stack Overflow** | Unbounded recursion on circular references | Crash |
| **Silent Truncation** | Deeply nested valid data silently dropped | Data loss |
| **Partial Validation** | Only shallow fields validated | Security risk |
| **Type Coercion Issues** | Wrong coercion at deep levels | Incorrect data |
| **Performance Degradation** | O(n^2) validation on deep structures | Latency spike |

### 2.3 Stageflow-Specific Context

Stageflow uses Pydantic for `StageOutput` validation:

```python
from stageflow import StageOutput

# StageOutput is a typed structure with data dict
output = StageOutput.ok(
    result={"nested": {"deep": {"value": 42}}}
)
```

**Current Limitations:**
1. `StageOutput.data` is `dict[str, Any]` - no schema enforcement on nested data
2. No depth limit configuration available
3. Validation only occurs when manually triggered with Pydantic models
4. Nested dict structure validation is ad-hoc

---

## 3. Research Findings

### 3.1 Web Research Results

**Pydantic Nested Validation Depth:**
- Pydantic v2 handles arbitrary depth but has performance implications
- Configurable via model_config settings
- Custom validators can enforce depth limits

**Best Practices for Deep Nesting:**
1. Use `model_config = {"strict": True}` for strict type checking
2. Implement depth-limiting validators for untrusted input
3. Consider flattening deeply nested structures
4. Use `Annotated` types for complex validation logic

### 3.2 Stageflow Architecture Analysis

**Key Stageflow Components:**
- `StageOutput`: Dict-based output with no inherent schema
- `StageInputs`: Provides access to prior stage outputs via key lookup
- `ContextSnapshot`: Immutable input snapshot with typed fields
- `OutputBag`: Merges outputs from parallel stages

**Risk Areas for Nested Validation:**
1. **OutputBag Merging**: Parallel stages may produce nested data that gets merged incorrectly
2. **Context Propagation**: Nested data in ContextSnapshot may lose structure during propagation
3. **StageInputs Access**: Deeply nested keys accessed via `get()` may not validate structure

---

## 4. Hypotheses to Test

| # | Hypothesis | Test Approach |
|---|------------|---------------|
| H1 | StageOutput accepts arbitrarily nested dicts without validation | Create nested data and verify pipeline runs |
| H2 | Nested data is preserved through context propagation | Check data integrity after pipeline execution |
| H3 | Deep nesting (>10 levels) causes performance degradation | Benchmark validation at various depths |
| H4 | Missing nested fields cause silent failures | Test access to non-existent deep keys |
| H5 | Type coercion in nested structures behaves unexpectedly | Test type mismatches at various depths |

---

## 5. Success Criteria

1. **Validation Depth Limit Identified**: Find maximum safe nesting depth
2. **Silent Failure Patterns Documented**: List all ways nested validation can silently fail
3. **Performance Baseline Established**: Latency metrics at different nesting depths
4. **Recommendations Provided**: Concrete improvements for Stageflow nested validation

---

## 6. References

1. Pydantic v2 Documentation - Nested Models: https://docs.pydantic.dev/latest/concepts/models/#recursive-types-and-self-referencing-models
2. Stack Overflow - Deeply Nested Pydantic Validation: https://stackoverflow.com/questions/77021379/how-to-validate-deeply-nested-data-structures-using-pydantic
3. HL7 FHIR Specification - Nested Resources: https://www.hl7.org/fhir/
4. Stageflow API Reference - StageOutput: See `stageflow-docs/api/core.md`

---

## 7. Appendix: Test Data Patterns

### 7.1 Happy Path Pattern
```python
{
    "level1": {
        "level2": {
            "level3": {
                "value": "valid"
            }
        }
    }
}
```

### 7.2 Edge Case Patterns
- **Maximum depth**: 15+ levels of nesting
- **Mixed types**: Array, dict, primitive at same depth
- **Empty structures**: `{}`, `[]` at various levels
- **Type coercion**: String where int expected at deep level

### 7.3 Adversarial Patterns
- **Circular reference**: A -> B -> A
- **Extremely deep**: 1000 levels
- **Mismatched types**: Non-dict where dict expected
- **Special characters**: Keys with dots, brackets
