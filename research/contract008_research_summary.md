# CONTRACT-008 Research Summary: Contract Inheritance in Stage Hierarchies

**Run ID**: contract008-2026-01-19-001  
**Agent**: claude-3.5-sonnet  
**Date**: 2026-01-19  
**Focus**: Contract inheritance and propagation in stage hierarchies (subpipelines, nested stages)

---

## 1. Executive Summary

This research examines contract inheritance patterns in the Stageflow framework, focusing on how stage contracts (StageOutput schemas) propagate through hierarchical stage structures including subpipelines, nested pipelines, and polymorphic stage hierarchies. The investigation covers how parent-child relationships affect contract enforcement, schema inheritance, and validation behavior.

**Key Findings:**
- Subpipeline context inheritance is well-documented but contract propagation lacks explicit enforcement
- StageOutput contracts are not automatically inherited or validated across hierarchy boundaries
- ContextSnapshot fields are inherited but validation contracts require manual enforcement
- Polymorphic stage hierarchies need explicit contract composition patterns

---

## 2. Industry Context

### 2.1 Contract Inheritance Patterns

Contract inheritance is a fundamental pattern in type-safe systems:

| Pattern | Description | Risk Level |
|---------|-------------|------------|
| Base Contract | Common requirements inherited by all child stages | High if violated |
| Polymorphic Contracts | Child stages can extend or override parent contracts | Medium |
| Composite Contracts | Multiple contracts combined via intersection | High |
| Narrowing Contracts | Child contracts are stricter than parent | Medium |
| Widening Contracts | Child contracts relax parent requirements | High (violates Liskov) |

### 2.2 Design by Contract Principles

From Wikipedia's Design by Contract specification:
- **Preconditions**: Requirements that must be met before a stage executes
- **Postconditions**: Guarantees that must be true after a stage completes
- **Invariants**: Conditions that must remain true throughout execution

Inheritance rules:
- Subcontracts must not strengthen preconditions
- Subcontracts must not weaken postconditions
- Invariants of supertype must be maintained

### 2.3 Subpipeline Orchestration Patterns

From CI/CD and orchestration frameworks:
- **Parent-child pipelines**: Child inherits context but maintains isolation
- **Hierarchical execution**: Multiple levels of nesting with depth limits
- **Contract propagation**: Parent contracts may or may not apply to children

---

## 3. Technical Context

### 3.1 Stageflow Subpipeline Architecture

From `stageflow-docs/advanced/subpipelines.md`:

```python
# Forking context for child pipeline
child_ctx = parent_ctx.fork(
    child_run_id=uuid4(),
    parent_stage_id="tool_executor",
    correlation_id=uuid4(),
    topology="child_pipeline",
    execution_mode="tool_mode",
)
```

**Child Context Properties:**
- Has its own `pipeline_run_id`
- References parent via `parent_run_id` and `parent_stage_id`
- Gets a **read-only snapshot** of parent data
- Inherits auth context (`user_id`, `org_id`, `session_id`)
- Has its own fresh `data` dict and `artifacts` list

### 3.2 StageOutput Contract System

```python
from stageflow import StageOutput

# Success with data - contract is implicit dict[str, Any]
return StageOutput.ok(key="value")

# Fail with error
return StageOutput.fail(error="Missing required field")
```

**Key observation**: `StageOutput.data` is a `dict[str, Any]` with no schema enforcement.

### 3.3 Context Inheritance Patterns

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

### 3.4 Pydantic Validation and Inheritance

From web research on Pydantic patterns:

```python
# Base validator with inheritance
class BaseValidator:
    @field_validator('field')
    def validate_base(cls, v):
        return v

class DerivedValidator(BaseValidator):
    @field_validator('field')
    def validate_derived(cls, v):
        return super().validate_base(v)  # Chain validation
```

**Key patterns:**
- Validators can be inherited from parent classes
- Root validators run in MRO order
- Composition allows combining multiple validation rules

---

## 4. Stageflow-Specific Analysis

### 4.1 Subpipeline Contract Inheritance

**Current behavior:**
1. ContextSnapshot fields are inherited from parent to child
2. `user_id`, `org_id`, `session_id` propagate automatically
3. StageOutput contracts are NOT automatically inherited
4. Each child stage defines its own contract

**Risk**: Parent pipeline assumes child outputs satisfy parent's contract expectations, but there's no enforcement.

### 4.2 Hierarchical Contract Propagation Scenarios

| Scenario | Inheritance Type | Current Support | Gap |
|----------|-----------------|-----------------|-----|
| Parent → Child Pipeline | Context fields | ✅ Full | Contracts not enforced |
| Base Stage → Derived Stage | Class inheritance | ⚠️ Partial | Validation not chained |
| Guard → Transform | Stage dependency | ✅ Via explicit deps | No schema validation |
| Subpipeline → Nested Subpipeline | Multi-level | ⚠️ Depth limited | No contract propagation |

### 4.3 Known Contract Inheritance Patterns

1. **Base Stage Pattern**: Common behavior in base class, specialized in derived
2. **Contract Composition**: Multiple contracts combined via validation chains
3. **Contract Narrowing**: Child stages add stricter requirements
4. **Contract Delegation**: Child delegates to parent for base validation

---

## 5. Hypotheses to Test

| # | Hypothesis | Test Approach |
|---|------------|---------------|
| H1 | StageOutput contracts are not automatically inherited by child pipelines | Create parent with required fields, child without, verify no enforcement |
| H2 | ContextSnapshot fields propagate correctly through fork() | Test user_id/org_id inheritance across subpipeline levels |
| H3 | Base class validators don't chain with derived class validators | Create base/derived stages with validators, check both run |
| H4 | Parent cannot enforce contract on child outputs | Create parent expecting specific child output, verify no validation |
| H5 | Polymorphic stage hierarchies break contract consistency | Create stage hierarchy with varying contracts, verify behavior |

---

## 6. Success Criteria

1. **Baseline**: Create stage hierarchy with proper contract inheritance patterns
2. **Inheritance Tests**: Verify context and contract propagation at each level
3. **Validation Chain**: Test that parent/derived validation chains work correctly
4. **Edge Cases**: Test deep nesting, polymorphic types, contract violations
5. **Silent Failures**: Hunt for cases where contract violations go undetected
6. **Documentation**: Document all findings and recommended patterns

---

## 7. References

### Stageflow Documentation
- `stageflow-docs/advanced/subpipelines.md` - Subpipeline execution guide
- `stageflow-docs/api/context.md` - Context API reference
- `stageflow-docs/api/core.md` - Core types and StageOutput
- `stageflow-docs/guides/stages.md` - Stage building guide

### Previous CONTRACT Entries
- `research/contract005_research_summary.md` - Optional vs required field enforcement
- `research/contract006_research_summary.md` - Nested object validation depth
- `research/contract007_research_summary.md` - Custom validator integration

### Industry Resources
- https://en.wikipedia.org/wiki/Design_by_contract - Design by contract principles
- https://docs.fluentvalidation.net/en/latest/inheritance.html - Inheritance validation patterns
- https://softwareengineering.stackexchange.com/questions/234613/design-pattern-for-data-validation - Data validation patterns

---

## 8. Next Steps

1. Build test pipelines for subpipeline contract inheritance
2. Create base/derived stage hierarchies for validation testing
3. Implement contract composition and narrowing patterns
4. Test edge cases (deep nesting, polymorphic types)
5. Execute tests and log all findings
6. Generate final report with recommendations

---

*Research completed: 2026-01-19*
