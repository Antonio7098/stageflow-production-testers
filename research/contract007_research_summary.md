# CONTRACT-007 Research Summary: Custom Validator Integration

> **Run ID**: run-2026-01-19-001  
> **Date**: 2026-01-19  
> **Focus**: Custom validator integration patterns for Stageflow

---

## 1. Executive Summary

This research investigates the integration of custom validators into the Stageflow framework for Stage Contract Enforcement. Custom validators are essential for enforcing domain-specific business rules, regulatory compliance, and data quality constraints that go beyond basic type checking. This document synthesizes findings from web research on validator patterns across multiple frameworks and provides a testing strategy for Stageflow's custom validator integration capabilities.

---

## 2. Industry Context

### 2.1 Why Custom Validators Matter

Custom validators are critical for:

1. **Domain-Specific Rules**: Business logic validation (e.g., "order total must be positive", "user must be 18+ for adult content")
2. **Regulatory Compliance**: HIPAA, PCI-DSS, GDPR requirements for data validation
3. **Cross-Field Validation**: Rules that depend on multiple fields (e.g., "end date must be after start date")
4. **External System Validation**: Validating against external databases or services
5. **Complex Format Validation**: Custom regex patterns, Luhn algorithms, etc.

### 2.2 Regulatory Requirements

| Regulation | Validation Requirements |
|------------|------------------------|
| HIPAA | PHI field validation, minimum necessary checks |
| PCI-DSS | Credit card format validation, PAN masking |
| GDPR | Consent validation, data minimization checks |
| SOC 2 | Access control validation, audit trail integrity |

---

## 3. Technical Context

### 3.1 State of the Art: Validator Patterns

Based on web research, the following patterns are prevalent across modern frameworks:

#### 3.1.1 Pydantic Validators

Pydantic provides the most comprehensive validator system:

```python
# Field validators
@field_validator('field_name', mode='before')
@classmethod
def validate_field(cls, value):
    return value

# Root validators (all fields)
@root_validator(pre=True)
def validate_root(cls, values):
    return values

# Annotated validators (Pydantic v2)
from typing import Annotated
from pydantic import AfterValidator

def check_value(v: int) -> int:
    if v < 0:
        raise ValueError("Must be non-negative")
    return v

class Model(BaseModel):
    value: Annotated[int, AfterValidator(check_value)]
```

#### 3.1.2 Guardrails AI Validators

Guardrails AI provides a registry-based approach:

```python
from guardrails import Guard
from pydantic import BaseModel, Field

class MyModel(BaseModel):
    a_string: Field(validators=[toxic_words()])
    custom_string: Field(validators=[ToxicLanguage(threshold=0.8)])

guard = Guard.for_pydantic(MyModel)
```

#### 3.1.3 Express-Validator Patterns

Express-validator demonstrates composition patterns:

```javascript
body('email')
  .isEmail()
  .bail()
  .custom(checkDenylistDomain)
  .bail()
  .custom(checkEmailExists);
```

#### 3.1.4 Zod Refinements

Zod shows the refinement pattern:

```typescript
const schema = z.object({
  password: z.string().min(8),
  confirmPassword: z.string(),
}).refine((data) => data.password === data.confirmPassword, {
  message: "Passwords don't match",
  path: ["confirmPassword"],
});
```

### 3.2 Known Failure Modes

From research, common validator failure modes include:

1. **Silent Validation Failures**: Validators that don't raise errors on invalid input
2. **Async Validator Timeouts**: Network-based validators that hang
3. **Cascading Failures**: One validation failure preventing other validations
4. **Injection Vulnerabilities**: Custom validators that don't sanitize inputs
5. **Performance Issues**: Expensive validators causing timeouts
6. **Error Message Leaks**: Validation errors revealing sensitive information

### 3.3 Stageflow-Specific Considerations

Based on the Stageflow documentation (stageflow-docs/):

1. **StageOutput Contract**: Stages return typed `StageOutput` with validation
2. **GUARD Stages**: Dedicated validation stage kind for input/output filtering
3. **Interceptor Pattern**: Cross-cutting validation via interceptors
4. **ContextSnapshot**: Immutable input data that can be validated
5. **Dependency Validation**: StageInputs validates key access

---

## 4. Hypotheses to Test

| # | Hypothesis | Test Approach |
|---|------------|---------------|
| H1 | Custom validators can be registered and applied to StageOutputs | Register validators and test with valid/invalid inputs |
| H2 | Validators compose correctly with multiple rules | Chain validators and verify each is applied |
| H3 | Async validators work correctly (network/database calls) | Test validators that make async calls |
| H4 | Validation errors provide actionable error messages | Check error message quality |
| H5 | Validators can access pipeline context for context-aware validation | Test context-dependent validation |
| H6 | Validation failures are handled gracefully (not silent) | Verify errors are raised and logged |
| H7 | Custom validators integrate with Stageflow's interceptor system | Test validation as interceptor |
| H8 | Performance impact of validation is bounded | Measure latency with/without validators |

---

## 5. Success Criteria Definition

### 5.1 Functional Criteria

- [ ] Custom validators can be registered for stage outputs
- [ ] Validators run on stage output production
- [ ] Validation errors prevent invalid data from propagating
- [ ] Multiple validators can be chained/composed
- [ ] Async validators work correctly
- [ ] Context-aware validation is supported

### 5.2 Non-Functional Criteria

- [ ] Validation overhead < 10% of stage execution time
- [ ] Error messages are actionable and include field names
- [ ] No silent validation failures
- [ ] Thread-safety for concurrent pipeline execution

### 5.3 DX Criteria

- [ ] Clear API for registering custom validators
- [ ] Documentation includes examples for common use cases
- [ ] Error messages are understandable by developers
- [ ] Validation can be enabled/disabled per environment

---

## 6. Key Findings from Web Research

### 6.1 Validator Registration Patterns

Most frameworks use one of three patterns:

1. **Decorator-based**: `@validator` decorators on model fields
2. **Registry-based**: Explicit registration in a validator registry
3. **Functional**: Pass validators as parameters to field definitions

### 6.2 Composition Patterns

- **Sequential**: Each validator runs in order, all must pass
- **Parallel**: All validators run, errors collected
- **Conditional**: Validators run based on other field values

### 6.3 Error Handling

- **Fail-fast**: Stop at first validation error
- **Collect-all**: Run all validators, report all errors
- **Weighted**: Some errors are warnings, others are failures

### 6.4 Async Support

Async validators require:
- Non-blocking I/O for external calls
- Timeout handling
- Connection pooling for database validators

---

## 7. References

1. Pydantic Validators - https://docs.pydantic.dev/latest/concepts/validators/
2. Guardrails AI Custom Validators - https://guardrails.ai/docs/how_to_guides/custom_validators/
3. Express Validator Custom Validators - https://express-validator.github.io/docs/api/validation-chain/
4. Zod Refine - https://zod.dev/?id=refine
5. Stageflow Documentation - stageflow-docs/
6. Stageflow Interceptors - stageflow-docs/guides/interceptors.md
7. Stageflow Stages - stageflow-docs/guides/stages.md
8. Stageflow Core API - stageflow-docs/api/core.md

---

## 8. Next Steps

1. Create mock validators with various patterns
2. Build test pipelines for validation scenarios
3. Execute tests covering happy path, edge cases, and failure modes
4. Analyze logs for silent failures
5. Document DX evaluation
6. Generate final report with findings
