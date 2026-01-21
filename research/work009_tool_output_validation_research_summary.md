# WORK-009: Tool Output Validation - Research Summary

## Executive Summary

This research document summarizes findings from web research and Stageflow documentation analysis for the WORK-009 roadmap entry: **Tool Output Validation**. Tool output validation is critical for ensuring that LLM-generated tool calls produce valid, safe, and predictable data that downstream stages can rely on. The research identifies significant gaps in Stageflow's current tool output validation capabilities compared to industry standards.

**Key Findings:**
- Stageflow has **input schema validation** for tools but **no output schema validation**
- Industry frameworks (Pydantic AI, Mastra, LangGraph, etc.) all support output schema validation
- Silent failures in tool outputs are a major reliability concern in production AI systems
- JSON Schema and Pydantic are the dominant validation approaches

---

## 1. Industry Context

### 1.1 The Critical Role of Tool Output Validation

Tool output validation ensures that when an LLM agent calls a tool, the returned data conforms to expected schemas and constraints. Without validation:

- **Data corruption**: Invalid data propagates through the pipeline
- **Silent failures**: Tools fail without detection
- **Security vulnerabilities**: Malformed outputs can be exploited
- **Debugging complexity**: Invalid data causes cryptic errors downstream

### 1.2 Industry Standards and Practices

From web research, the following patterns are established best practices:

| Framework | Output Validation Approach | Key Features |
|-----------|---------------------------|--------------|
| **Pydantic AI** | `output_type` with Pydantic models | Full type validation, streaming support |
| **Mastra** | `outputSchema` with Zod | Runtime validation, async support |
| **LangGraph** | Custom validation in nodes | Flexible, no built-in schema |
| **FastMCP** | `output_schema` parameter | JSON Schema validation |
| **Agent Development Kit** | `outputSchema` | Structured output enforcement |

### 1.3 Silent Failure Detection

Research from vLLora (2025) highlights that "silent failures" in LLM workflows can cost 40% more due to:
- Retries and fallback chains
- Wasted token usage
- Incorrect outputs that appear valid

---

## 2. Stageflow Architecture Analysis

### 2.1 Current Tool System

From `stageflow-docs/guides/tools.md` and `stageflow-docs/api/tools.md`:

**Current Capabilities:**
- `ToolInput`: Input schema validation via `input_schema` (JSON Schema)
- `ToolOutput`: Output structure with `success`, `data`, `error`, `artifacts`, `undo_metadata`
- `ToolRegistry`: Tool discovery and execution
- `AdvancedToolExecutor`: Observability and behavior gating

**ToolOutput Structure:**
```python
@dataclass
class ToolOutput:
    success: bool
    data: dict | None = None
    error: str | None = None
    artifacts: list[dict] | None = None
    undo_metadata: dict | None = None
```

### 2.2 Identified Gaps

| Gap | Description | Impact |
|-----|-------------|--------|
| **No Output Schema** | `ToolDefinition` has `input_schema` but no `output_schema` | Cannot validate tool output structure |
| **No Output Validation** | No built-in mechanism to validate `ToolOutput.data` | Invalid data propagates silently |
| **No Schema Enforcement** | Tools can return arbitrary dict structures | Downstream stages receive unexpected data |
| **No Type Safety** | `data: dict | None` lacks type constraints | Runtime type errors in downstream stages |

### 2.3 Comparison with Industry

| Feature | Stageflow | Pydantic AI | Mastra |
|---------|-----------|-------------|--------|
| Input Schema | ✅ JSON Schema | ✅ Pydantic | ✅ Zod |
| Output Schema | ❌ None | ✅ Pydantic | ✅ Zod |
| Runtime Validation | ❌ Manual | ✅ Automatic | ✅ Automatic |
| Type Coercion | ❌ None | ✅ Yes | ✅ Yes |

---

## 3. Hypotheses to Test

### 3.1 Core Hypotheses

**H1: Tool outputs are not validated against any schema**
- Expected: Tools can return any data structure
- Test: Execute tools with various output types and check for validation

**H2: Invalid tool outputs propagate silently to downstream stages**
- Expected: No error raised for malformed outputs
- Test: Create tool that returns invalid data, check downstream behavior

**H3: No mechanism exists to enforce output contracts**
- Expected: Cannot specify expected output structure
- Test: Attempt to define output schema for a tool

**H4: Silent failures occur when tools return unexpected data types**
- Expected: Downstream stages may fail or behave unexpectedly
- Test: Pass wrong types through tool outputs

### 3.2 Edge Cases to Test

| Edge Case | Description |
|-----------|-------------|
| Missing required fields | Tool omits expected data keys |
| Type mismatches | Wrong types (string instead of int) |
| Null values | `None` where data expected |
| Extra fields | Additional unexpected keys |
| Malformed JSON | String instead of structured data |
| Nested structure violations | Deeply nested validation failures |

---

## 4. Success Criteria Definition

### 4.1 Functional Success Criteria

| Criterion | Metric | Target |
|-----------|--------|--------|
| Output schema support | Can define output schema for tools | ✅ Yes/No |
| Runtime validation | Invalid outputs detected | ✅ Yes/No |
| Error reporting | Validation errors actionable | ✅ Yes/No |
| Type coercion | Automatic type conversion | ✅ Yes/No |

### 4.2 Reliability Success Criteria

| Criterion | Metric | Target |
|-----------|--------|--------|
| Silent failure rate | Undetected invalid outputs | < 1% |
| Detection latency | Time to detect invalid output | < 100ms |
| False positive rate | Valid outputs incorrectly rejected | < 0.1% |

### 4.3 Performance Success Criteria

| Criterion | Metric | Target |
|-----------|--------|--------|
| Validation overhead | Additional latency per tool call | < 5ms |
| Memory impact | Additional memory per validation | < 1KB |

---

## 5. Test Scenarios

### 5.1 Baseline Scenarios (Happy Path)

1. **Valid output with all required fields**: Tool returns correct schema
2. **Valid output with extra fields**: Tool returns schema + additional keys
3. **Valid nested structure**: Tool returns deeply nested valid data
4. **Type coercion**: Tool returns coercible types (string "123" → int 123)

### 5.2 Edge Case Scenarios

1. **Missing required field**: Tool omits a required key
2. **Wrong type**: Tool returns wrong type for a field
3. **Null values**: Tool returns `None` for non-nullable field
4. **Empty data**: Tool returns empty dict or null
5. **Malformed nested structure**: Deeply nested type mismatch
6. **Unexpected root type**: Tool returns array instead of object

### 5.3 Chaos Scenarios

1. **Malicious payload**: Tool returns data designed to exploit downstream
2. **Extremely deep nesting**: Tool returns deeply nested dict
3. **Very large output**: Tool returns megabytes of data
4. **Circular references**: Tool returns dict with circular refs
5. **JSON injection**: Tool returns string containing JSON-like data

### 5.4 Stress Scenarios

1. **High-frequency validation**: 100+ tools executed concurrently
2. **Large schemas**: Validation against complex nested schemas
3. **Rapid succession**: Tools called in tight loops

---

## 6. Framework Comparison Details

### 6.1 Pydantic AI Approach

```python
from pydantic_ai import Agent
from pydantic import BaseModel

class UserProfile(BaseModel):
    name: str
    age: int

agent = Agent('openai:gpt-4', output_type=UserProfile)
```

**Key features:**
- Full Pydantic validation
- Automatic type coercion
- Detailed error messages
- Streaming validation support

### 6.2 Mastra Approach

```typescript
const structuredTool = createTool({
  description: 'A test tool.',
  parameters: z.object({ input: z.string() }),
  outputSchema: z.object({
    processedInput: z.string(),
    timestamp: z.string(),
  }),
  execute: async ({ input }) => ({
    processedInput: `processed: ${input}`,
    timestamp: new Date().toISOString(),
  }),
});
```

**Key features:**
- Zod schema validation
- Runtime type checking
- Async validation support

### 6.3 FastMCP Approach

```python
@mcp.tool(output_schema={
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "data": {"type": "object"}
    }
})
def custom_schema_tool() -> dict:
    return {"data": "Hello", "metadata": {"version": "1.0"}}
```

**Key features:**
- JSON Schema validation
- Custom output handling via `ToolResult`
- Flexible error reporting

---

## 7. Stageflow Documentation Analysis

### 7.1 Documentation Gaps Identified

| Topic | Documentation Status | Gap |
|-------|---------------------|-----|
| Tool output validation | Not documented | Missing entirely |
| Output schema specification | Not documented | Missing entirely |
| Validation error handling | Not documented | Missing entirely |
| Type enforcement | Not documented | Missing entirely |

### 7.2 Reference Documentation

- `stageflow-docs/guides/tools.md`: Tool definitions, execution, and error handling
- `stageflow-docs/api/tools.md`: ToolInput, ToolOutput, ToolDefinition APIs
- `stageflow-docs/api/core.md`: StageOutput structure and conventions
- `stageflow-docs/guides/stages.md`: Stage implementation guidelines

### 7.3 Documentation Inconsistencies

1. **Provider Response Conventions**: `LLMResponse`, `STTResponse`, `TTSResponse` are documented as conventions but no validation is mentioned
2. **Tool Events**: `tool.completed` and `tool.failed` events exist but no validation event
3. **Error Handling**: `ToolExecutionError` exists but no `ToolValidationError`

---

## 8. Risk Assessment

### 8.1 Technical Risks

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Data corruption | High | Medium | Add output validation |
| Silent failures | High | High | Implement validation checks |
| Security vulnerabilities | High | Low | Sanitize and validate outputs |
| Performance impact | Medium | Medium | Optimize validation overhead |

### 8.2 Reliability Risks

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Cascading failures | High | Medium | Fail-fast on validation errors |
| Debugging complexity | Medium | High | Provide detailed error messages |
| Backward compatibility | Medium | Low | Make validation optional |

---

## 9. Recommendations

### 9.1 Immediate Actions

1. **Add output schema support to `ToolDefinition`**
   - Add `output_schema: dict | None` parameter
   - Implement JSON Schema validation

2. **Create `ToolValidationError` exception class**
   - Distinguish validation errors from execution errors
   - Provide detailed error context

3. **Add validation to `AdvancedToolExecutor`**
   - Validate outputs after tool execution
   - Emit validation events

### 9.2 Short-term Enhancements

1. **Pydantic integration (Stageflow Plus)**
   - Support Pydantic models as output schemas
   - Automatic type coercion

2. **Validation interceptor**
   - Create `ValidationInterceptor` for cross-cutting validation
   - Apply to specific stages or all stages

3. **Enhanced observability**
   - Emit `tool.validated` events
   - Log validation failures with context

### 9.3 Long-term Roadmap

1. **Schema registry**
   - Centralized schema management
   - Schema versioning and evolution

2. **Contract testing**
   - Generate tests from schemas
   - Validate tool outputs against contracts

3. **AI-assisted validation**
   - Detect semantic violations
   - Flag suspicious output patterns

---

## 10. Conclusion

Tool output validation is a critical gap in Stageflow's current tool system. While input validation exists via JSON Schema, there is no mechanism to validate that tool outputs conform to expected structures. This creates risks for data corruption, silent failures, and debugging complexity.

The research identifies clear patterns from industry frameworks that Stageflow can follow to implement output validation. The recommended approach is:
1. Add output schema support to `ToolDefinition`
2. Implement JSON Schema validation
3. Create appropriate error types and events
4. Provide Stageflow Plus package with Pydantic integration

This research provides the foundation for Phase 2: Environment Simulation and Phase 3: Pipeline Construction.

---

## References

1. Pydantic AI Documentation - Output Processing and Validation
2. Mastra Documentation - Structured Output and Schema Validation
3. FastMCP Documentation - Tool Transformation and Output Schema
4. vLLora Blog - Silent Failures in LLM Workflows (2025)
5. Agentic AI Frameworks Survey - arXiv:2508.10146 (2025)
6. Stageflow Documentation - Tools and Agents Guide
7. Stageflow Documentation - Tools API Reference
