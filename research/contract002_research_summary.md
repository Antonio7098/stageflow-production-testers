# CONTRACT-002 Research Summary: Schema Evolution and Backward Compatibility

**Run ID**: run-2026-01-19-001
**Agent**: claude-3.5-sonnet
**Date**: 2026-01-19

## Research Objective

Stress-test Stageflow's ability to handle schema evolution and maintain backward compatibility in StageOutput contracts. The focus is on typed stage contracts and how they handle changes over time.

## Key Findings from Web Research

### 1. Schema Evolution Best Practices

From Confluent Schema Registry best practices:
- **Backward Compatibility** (default): All messages conforming to the old schema are valid with the new schema
- **Forward Compatibility**: All messages conforming to the new schema are valid with the old schema
- **Full Compatibility**: Both directions, but overly restrictive in practice

**Critical Pattern**: Schema migration rules enable both old and new consumers/producers to work simultaneously through UPGRADE/DOWNGRADE transformations.

### 2. Key Compatibility Strategies

1. **Version Metadata**: Add major_version field to schemas to track breaking changes
2. **Compatibility Groups**: Partition schemas by version to allow breaking changes within groups
3. **Additive Changes**: Add fields with defaults instead of modifying/removing
4. **Deprecation Periods**: 6-12 month warning before removing fields

### 3. Pydantic Migration Patterns

```python
# Version-aware state with migration
class ThreadStateV1(BaseModel):
    version: Literal[1] = 1
    data: OldFields

class ThreadStateV2(BaseModel):
    version: Literal[2] = 2
    data: NewFields
    metadata: dict  # New field with default

def migrate_v1_to_v2(v1: ThreadStateV1) -> ThreadStateV2:
    return ThreadStateV2(
        initial_email=v1.initial_email,
        metadata={}  # Default for new field
    )
```

### 4. API Versioning Strategies

- **URI-based**: `/v1/`, `/v2/` path segments
- **Header-based**: `api-version: 2.0` custom headers
- **Query-based**: `?version=2.0`

### 5. Breaking vs Non-Breaking Changes

**Non-Breaking**:
- Adding optional fields with defaults
- Adding new endpoints
- Adding new enum values

**Breaking**:
- Removing or renaming fields
- Changing field types
- Making optional fields required
- Changing validation rules

## Stageflow-Specific Context

### StageOutput Structure

From `stageflow-docs/api/core.md`:
```python
StageOutput(
    status: StageStatus,       # OK, SKIP, CANCEL, FAIL, RETRY
    data: dict[str, Any],      # Output data dictionary
    artifacts: list[StageArtifact],
    events: list[StageEvent],
    error: str | None
)
```

### Key Questions for Stageflow

1. **Schema Registration**: Are StageOutput schemas registered/validated anywhere?
2. **Version Tracking**: Does ContextSnapshot track schema versions?
3. **Migration Support**: Are there migration helpers for schema changes?
4. **Validation**: Is there runtime validation of StageOutput contracts?
5. **Backward Compatibility**: How does StageInputs handle missing fields?

## Hypotheses to Test

### H1: Missing Required Fields
**Hypothesis**: When a stage's output schema changes (field removed), downstream stages may fail silently or crash when accessing the missing field.

**Test**: Create pipeline with stage producing v1 output, then update to v2 without the field. Observe downstream behavior.

### H2: Type Changes Not Detected
**Hypothesis**: Changing a field's type in StageOutput (e.g., str to int) causes downstream failures that aren't caught at validation time.

**Test**: Change field type and observe whether downstream type handling fails.

### H3: Default Value Handling
**Hypothesis**: When adding new fields, there's no standard way to provide defaults, causing failures in stages expecting the field.

**Test**: Add new field to output, run old downstream stage that expects it.

### H4: Serialization Compatibility
**Hypothesis**: ContextSnapshot serialization/deserialization may not preserve all schema information, causing compatibility issues.

**Test**: Serialize/deserialize context with various data types and observe.

### H5: Strict vs Lenient Validation
**Hypothesis**: StageInputs `get()` vs `get_from()` may behave differently with missing or type-mismatched data.

**Test**: Compare behavior of different access methods.

## Test Scenarios

### Scenario 1: Field Addition (Non-Breaking)
- Stage A v1: outputs `{"result": "value"}`
- Stage B: expects `result`
- Update Stage A to v2: outputs `{"result": "value", "metadata": {}}`
- Expected: Stage B continues working

### Scenario 2: Field Removal (Breaking)
- Stage A v1: outputs `{"result": "value", "extra": "data"}`
- Stage B: uses `extra`
- Update Stage A to v2: outputs `{"result": "value"}`
- Expected: Stage B fails gracefully with clear error

### Scenario 3: Type Change (Breaking)
- Stage A v1: outputs `{"count": "123"}` (string)
- Stage B: treats count as string
- Update Stage A to v2: outputs `{"count": 123}` (int)
- Expected: Type mismatch detected or handled

### Scenario 4: Required vs Optional
- Stage A v1: always outputs `{"status": "ok"}`
- Stage A v2: sometimes omits `status` field
- Expected: Downstream handles missing optional field

### Scenario 5: Nested Object Changes
- Stage A v1: outputs `{"user": {"name": "John", "age": 30}}`
- Stage A v2: outputs `{"user": {"display_name": "John"}}` (renamed field)
- Expected: Nested changes handled appropriately

## Success Criteria

1. All test scenarios execute without silent failures
2. Clear error messages when schema violations occur
3. Documentation of backward compatibility guarantees
4. Recommendations for Stageflow schema evolution best practices

## References

- Confluent Schema Registry Best Practices: https://www.confluent.io/blog/best-practices-for-confluent-schema-registry/
- Pydantic Migration Guide: https://docs.pydantic.dev/latest/migration/
- API Backward Compatibility Best Practices: https://zuplo.com/learning-center/api-versioning-backward-compatibility-best-practices
