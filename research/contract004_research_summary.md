# CONTRACT-004 Research Summary: Contract Violation Error Messaging

**Run ID**: contract004-2026-01-19-001
**Agent**: claude-3.5-sonnet
**Date**: 2026-01-19
**Focus**: Contract violation error messaging quality and actionability

## Research Objective

Stress-test Stageflow's contract violation error messaging by evaluating:
- Error message clarity and actionability
- Developer experience when encountering contract violations
- Consistency across different error types
- Completeness of error information provided
- Gap analysis against industry best practices

## Key Findings from Web Research

### 1. Industry Error Message Best Practices

**From Nielsen Norman Group** ([Error-Message Guidelines](https://www.nngroup.com/articles/error-message-guidelines/)):
- Error messages should be highly visible and provide constructive communication
- Messages should respect user effort and avoid blame
- Help users recover from errors by clearly identifying problems
- Provide actionable guidance for resolution

**From Google Technical Writing** ([Writing Helpful Error Messages](https://developers.google.com/tech-writing/error-messages)):
- Good error messages explain what happened and how to fix it
- Include the right amount of context without overwhelming
- Use consistent terminology and formatting
- Avoid technical jargon when面向开发者

**From Smashing Magazine** ([Designing Better Error Messages UX](https://smashingmagazine.com/2022/08/error-messages-ux-design)):
- Error messages should be human-readable and empathetic
- Include error codes for programmatic handling
- Provide links to documentation or troubleshooting guides
- Use consistent structure across all error types

**From Stack Overflow Design** ([Error messages](https://stackoverflow.design/content/examples/error-messages/)):
- Good structure: `[The error] [How to fix it]`
- Understand the error: What happened, how it happened, how to fix it
- Help developers understand root causes and remediation steps

### 2. Python Exception Handling Best Practices

**From Real Python** ([Python Exception Handling](https://jerrynsh.com/python-exception-handling-patterns-and-best-practices/)):
- Include context in exceptions without exposing sensitive information
- Use exception chaining to preserve original tracebacks
- Make exceptions actionable with clear error messages
- Include relevant data for debugging (stage name, pipeline ID, etc.)

**From Python Documentation** ([traceback module](https://docs.python.org/3/library/traceback.html)):
- Tracebacks should show the full call stack
- Exception messages should clearly indicate the error type
- Include relevant variable values (not sensitive data)

### 3. Workflow Orchestration Error Handling

**AWS Step Functions** ([Error Handling](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)):
- Provide detailed error names and causes
- Include retry hints and Catch conditions
- Support custom error names for different failure modes

**Temporal.io** ([Error Handling](https://temporal.io/blog/error-handling-in-distributed-systems)):
- Distinguish between different failure types (timeout, cancellation, application error)
- Include stack traces and activity information
- Support error conversion for client handling

## Stageflow-Specific Context

### Error Types Identified

| Error Type | Location | Purpose |
|------------|----------|---------|
| `UndeclaredDependencyError` | `stages/inputs.py` | Enforces dependency contracts |
| `PipelineValidationError` | `pipeline/spec.py` | Pipeline structure validation |
| `CycleDetectedError` | `pipeline/spec.py` | DAG cycle detection |
| `StageExecutionError` | `pipeline/dag.py` | Stage execution failures |
| `CircuitBreakerOpenError` | `observability/` | Circuit breaker triggers |
| `OutputConflictError` | `context/output_bag.py` | Concurrent output conflicts |
| `DataConflictError` | `context/bag.py` | Data collision handling |
| `MaxDepthExceededError` | `pipeline/subpipeline.py` | Subpipeline nesting limit |

### Error Message Quality Criteria

Based on research, high-quality error messages should include:

1. **Clear problem statement**: What went wrong?
2. **Context**: Where did it happen (stage, pipeline, component)?
3. **Root cause hint**: Why did it happen?
4. **Actionable guidance**: How to fix it?
5. **Relevant data**: Error codes, affected resources, boundary values
6. **Documentation reference**: Links to relevant docs

### Current Stageflow Error Messages (Sample)

**UndeclaredDependencyError**:
```
UndeclaredDependencyError: Stage 'transform': Attempted to access
undeclared dependency 'fetch_data'. Declared dependencies: ['router'].
Add 'fetch_data' to depends_on to fix this error.
```
✓ Clear problem statement, context, and actionable guidance

**CycleDetectedError**:
- Contains `cycle_path` and `stages` attributes
- String representation may vary

**StageExecutionError**:
- Base exception with `stage` and `original` attributes
- String representation needs verification

## Hypotheses to Test

### H1: Error Message Clarity
**Hypothesis**: All contract violation errors provide clear, actionable messages that explain what happened and how to fix it.

**Test**: Trigger each error type and evaluate message quality against criteria.

### H2: Error Context Completeness
**Hypothesis**: Error messages include sufficient context (stage names, dependency lists, cycle paths) to understand and debug issues.

**Test**: Check error attributes and string representations for completeness.

### H3: Error Message Consistency
**Hypothesis**: All error messages follow a consistent format and terminology.

**Test**: Compare message structures across different error types.

### H4: Documentation Links
**Hypothesis**: Error messages include references to relevant documentation.

**Test**: Verify presence of doc links or codes in error messages.

### H5: Programmatic Error Handling
**Hypothesis**: Errors provide attributes that enable programmatic handling (error codes, types, structured data).

**Test**: Check error classes for structured attributes.

### H6: Debugging Experience
**Hypothesis**: Stack traces and error context enable quick debugging of contract violations.

**Test**: Trigger errors and measure time to understand and fix.

### H7: Sensitive Data Exposure
**Hypothesis**: Error messages do not expose sensitive information in error strings.

**Test**: Verify error messages don't include secrets, PII, or internal details.

### H8: Internationalization Readiness
**Hypothesis**: Error messages are structured for potential internationalization.

**Test**: Check for string interpolation vs. hardcoded messages.

## Test Scenarios

### Scenario 1: Dependency Contract Violations
```
Pipeline: A → B (B accesses A's output without declaring dependency)
Error: UndeclaredDependencyError
Test: Verify message clarity, context, and fix guidance
```

### Scenario 2: Circular Dependency
```
Pipeline: A → B → C → A
Error: CycleDetectedError
Test: Verify cycle path reporting and resolution guidance
```

### Scenario 3: Invalid Pipeline Structure
```
Pipeline: Missing required stages, invalid dependencies
Error: PipelineValidationError
Test: Verify validation message completeness
```

### Scenario 4: Stage Execution Failure
```
Stage: Raises exception during execution
Error: StageExecutionError
Test: Verify exception chaining and context preservation
```

### Scenario 5: Output Conflict
```
Parallel stages: A and B both write to same key
Error: OutputConflictError
Test: Verify conflict resolution guidance
```

### Scenario 6: Circuit Breaker Trigger
```
Stage: Repeated failures trigger circuit breaker
Error: CircuitBreakerOpenError
Test: Verify recovery guidance and timing info
```

## Success Criteria

1. All error types have clear, actionable messages
2. Error context includes relevant debugging information
3. Consistent formatting across error types
4. No sensitive data exposure in error messages
5. Programmatic error handling supported via attributes
6. Developer can resolve errors from message alone
7. Recommendations for error message improvements documented

## References

- [Nielsen Norman Group: Error-Message Guidelines](https://www.nngroup.com/articles/error-message-guidelines/)
- [Google: Writing Helpful Error Messages](https://developers.google.com/tech-writing/error-messages)
- [Smashing Magazine: Designing Better Error Messages UX](https://smashingmagazine.com/2022/08/error-messages-ux-design)
- [Stack Overflow Design: Error messages](https://stackoverflow.design/content/examples/error-messages/)
- [AWS Step Functions Error Handling](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)
- [Temporal Error Handling](https://temporal.io/blog/error-handling-in-distributed-systems)
- [Python traceback module](https://docs.python.org/3/library/traceback.html)
