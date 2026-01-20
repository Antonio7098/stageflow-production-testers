# CORE-006: Context Propagation Across Nested Pipelines Research

## Executive Summary

This research document captures findings from web research and analysis of Stageflow's context propagation capabilities across nested pipelines. The focus is on understanding how context flows between parent and child pipelines, identifying failure modes, and defining test scenarios.

## Key Research Findings

### 1. Industry Context: Context Propagation Challenges

**Critical Problems Identified:**
- Context pollution from bloated tool sets causes agent failures
- State not properly propagated between stages in nested pipelines
- Subgraph state isolation issues in frameworks like LangGraph
- Silent context loss - context changes without detection

**Reference:** [Context Engineering: The Real Reason AI Agents Fail in Production](https://inkeep.com/blog/context-engineering-why-agents-fail)

### 2. LangGraph Subgraph State Management

**Key Concepts:**
- Parent and child graphs can share state keys
- State transformation required when entering/exiting subgraphs
- Subgraphs have isolated state unless explicitly configured
- Shared keys can be used for parent-child communication

**Example Pattern:**
```python
# Subgraph state with shared key 'foo'
class SubgraphState(TypedDict):
    foo: str  # shared with parent
    bar: str  # subgraph-only

# Parent state
class ParentState(TypedDict):
    foo: str  # shared key
```

**Reference:** [LangGraph Subgraphs Documentation](https://langchain-ai.github.io/langgraph/how-tos/subgraph/)

### 3. OpenAI Swarm Context Model

**Key Pattern:**
- All agents share the same message context
- Handoffs transfer context between agents
- No explicit state isolation between agents
- Simple but can lead to context pollution

**Reference:** [OpenAI Swarm Framework](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/swarm.html)

### 4. Common Failure Modes (Microsoft Taxonomy)

**Critical Categories:**
- **Context Overflow**: Context window limits exceeded
- **Context Drift**: Gradual context corruption over time
- **Context Loss**: Silent state loss between stages
- **Context Leakage**: Information from previous runs affecting current runs
- **Context Isolation Failures**: Child pipelines accessing parent state incorrectly

**Reference:** [Microsoft Taxonomy of Failure Modes in Agentic AI Systems](https://cdn-dynmedia-1.microsoft.com/is/content/microsoftcorp/microsoft/final/en-us/microsoft-brand/documents/Taxonomy-of-Failure-Mode-in-Agentic-AI-Systems-Whitepaper.pdf)

### 5. Anthropic Multi-Agent System Lessons

**Key Insights:**
- State management becomes complex with multiple agents
- Tool design affects context propagation
- Error handling must consider context state
- Monitoring context size is critical

**Reference:** [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)

## Stageflow-Specific Analysis

### Current Context System (from docs)

**PipelineContext:**
- Contains: pipeline_run_id, request_id, session_id, user_id, org_id, interaction_id
- Supports `fork()` for creating child contexts
- Child contexts get read-only parent data via FrozenDict
- Fresh data dict and artifacts list for child

**ContextSnapshot:**
- Immutable, serializable view of execution state
- Contains: run_id, conversation, enrichments, extensions, input_text, metadata
- Derived from PipelineContext and passed to stages

**Key Gap Identified:**
- No explicit mechanism for controlling which context data is shared with children
- No state transformation capability when entering/exiting subpipelines
- No explicit key-sharing configuration like LangGraph
- Limited observability of context propagation

### Hypotheses to Test

1. **Context Isolation**: Do child pipelines correctly isolate their state from parents?
2. **Context Inheritance**: Are all required fields correctly inherited by child contexts?
3. **Context Transformation**: Can context be transformed when passing to subpipelines?
4. **Context Propagation Completeness**: Are all prior outputs accessible in nested stages?
5. **Silent Failures**: Are there cases where context silently fails to propagate?
6. **Concurrency Safety**: Is context safe under concurrent access?
7. **Memory Growth**: Does context grow unboundedly in deep nesting?

## Risk Analysis

| Risk | Severity | Description |
|------|----------|-------------|
| Silent Context Loss | Critical | Context changes without detection |
| Context Isolation Breach | High | Child accesses/modifies parent state |
| Context Bloat | High | Memory grows unboundedly in nested pipelines |
| State Inconsistency | High | Different context views at different nesting levels |
| Missing Inheritance | Medium | Some fields not inherited by child contexts |
| Concurrent Corruption | Medium | Race conditions in context access |

## Success Criteria

1. **Isolation**: Child pipelines cannot modify parent state (verified via tests)
2. **Inheritance**: All identity fields correctly inherited (user_id, org_id, etc.)
3. **Propagation**: Prior outputs accessible through all nesting levels
4. **Observability**: Context propagation can be traced and monitored
5. **Memory Safety**: No unbounded memory growth in deep nesting
6. **Failure Detection**: Context propagation failures are detectable

## Test Scenarios

### 1. Baseline Context Propagation
- Simple parent → child → grandchild pipeline
- Verify identity fields propagate correctly
- Verify prior outputs accessible at each level

### 2. Context Isolation Testing
- Attempt to modify parent data from child
- Verify parent data unchanged after child completes
- Test FrozenDict behavior

### 3. State Transformation Testing
- Create context transformation at fork point
- Verify transformation applied correctly
- Test partial transformations

### 4. Deep Nesting Testing
- Create 5+ levels of nesting
- Verify context accessible at all levels
- Monitor memory growth

### 5. Concurrent Context Access
- Multiple parallel child pipelines
- Verify isolation under concurrent access
- Test race condition scenarios

### 6. Context Corruption Testing
- Inject malformed context data
- Verify graceful handling
- Check error messages

### 7. Edge Cases
- Empty context fields
- Very large context payloads
- Special characters in context data
- Unicode and encoding issues

## Research Artifacts

- Web search results captured in initial queries
- Industry patterns documented from 10+ sources
- Stageflow documentation reviewed (context.md, subpipelines.md)
- Existing components analyzed (GroqChatStage, streaming mocks)
- Related CORE-005 research reviewed for patterns

## Next Steps

1. Build test pipeline for context propagation baseline
2. Implement stress tests for isolation and inheritance
3. Test deep nesting scenarios
4. Evaluate performance under concurrent access
5. Test edge cases and failure modes
6. Document all findings using add_finding.py
