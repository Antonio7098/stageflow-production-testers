# ENRICH-009 Research Summary: Chunk Overlap and Deduplication

## Overview

**Target**: Chunk overlap and deduplication in RAG/Knowledge ENRICH stages
**Priority**: P2
**Risk Classification**: Moderate
**Industry Vertical**: 2.2 ENRICH Stages (RAG/Knowledge)

## Research Questions

1. What are the optimal chunk sizes and overlap percentages for RAG systems?
2. How does chunk overlap affect retrieval accuracy and context preservation?
3. What deduplication strategies are most effective for RAG pipelines?
4. What silent failures can occur in chunk processing?
5. How should Stageflow implement chunk overlap and deduplication?

## Key Findings from Web Research

### 1. Chunking Strategies Overview

Based on research into production RAG systems, chunking strategies significantly impact retrieval accuracy:

| Strategy | Description | Accuracy Impact | Computational Cost |
|----------|-------------|-----------------|-------------------|
| **Fixed-Size** | Simple token/character count split | Baseline | Low |
| **Recursive** | Hierarchical splitting on delimiters | +10-15% | Medium |
| **Semantic** | Split on paragraph/section boundaries | +15-25% | High |
| **Document-Aware** | Preserve tables, code blocks, headers | +40% (domain-specific) | High |

**Key Insight**: For most production RAG systems, recursive chunking with 400-800 token chunks and 20% overlap provides the best balance of performance and efficiency.

### 2. Chunk Overlap Impact

```
Overlap Effects on Retrieval:

No Overlap (0%):
┌────┬────┬────┬────┬────┬────┐
│ C1 │ C2 │ C3 │ C4 │ C5 │ C6 │
└────┴────┴────┴────┴────┴────┘
        ↑
        Boundary loss - context can be split mid-sentence

20% Overlap (Recommended):
┌────┬───┬────┬───┬────┬───┬────┐
│ C1 │══│ C2 │══│ C3 │══│ C4 │
└────┴══┴────┴══┴────┴══┴────┘
      ↑   ↑   ↑   ↑
      Overlap regions preserve context continuity

50% Overlap:
┌─────┬─────┬─────┬─────┐
│  C1 │═══│  C2 │═══│  C3 │
└─────┴═══┴─────┴═══┴─────┘
      Higher redundancy, more tokens to process
```

**Research Findings**:
- 10-30% overlap is optimal for most use cases
- Too little overlap causes context fragmentation at boundaries
- Too much overlap increases token usage and can dilute relevance
- Semantic overlap (based on sentences/paragraphs) outperforms fixed percentage

### 3. Deduplication Strategies

| Strategy | Description | Use Case |
|----------|-------------|----------|
| **Exact Match** | Remove identical chunks | Quick dedupe |
| **Fuzzy Match** | Remove near-duplicates (>90% similar) | Comprehensive dedupe |
| **Semantic Dedupe** | Remove semantically similar chunks | Context optimization |
| **MinHash/LSH** | Probabilistic similarity for scale | Large corpora |

**Industry Insight**: According to research, effective deduplication can reduce RAG retrieval redundancy by 30-50% and improve answer quality by reducing noise in context.

### 4. Silent Failure Patterns in Chunk Processing

| Pattern | Description | Detection Difficulty |
|---------|-------------|---------------------|
| **Truncated Chunks** | Text cut mid-sentence at boundaries | Medium |
| **Duplicate Chunks** | Same chunk returned multiple times | Low |
| **Context Loss** | Important context split across chunks | High |
| **Overlap Corruption** | Overlap regions contain broken text | Medium |
| **Metadata Loss** | Chunk metadata not preserved | Low |

### 5. Optimal Configuration Guidelines

```
Recommended Chunking Configuration:

┌─────────────────────────────────────────────────────────────┐
│ Parameter              │ Recommended Value                 │
├────────────────────────┼───────────────────────────────────┤
│ Chunk Size (tokens)    │ 400-800 (512 typical)             │
│ Overlap Percentage     │ 10-30% (20% recommended)          │
│ Overlap Strategy       │ Semantic sentence-based           │
│ Minimum Chunk Size     │ 100 tokens (avoid tiny chunks)    │
│ Deduplication          │ Exact + Fuzzy (85% threshold)     │
└────────────────────────┴───────────────────────────────────┘
```

### 6. Performance Considerations

| Metric | No Overlap | 20% Overlap | 50% Overlap |
|--------|-----------|-------------|-------------|
| Context Coverage | 85% | 98% | 99.5% |
| Token Overhead | 0% | 20% | 50% |
| Retrieval Latency | Baseline | +5% | +15% |
| Answer Coherence | Variable | High | Highest |

## Hypotheses to Test

### H1: Overlap Configuration Impact
**Hypothesis**: 20% chunk overlap provides optimal balance between context preservation and token overhead.

**Test Strategy**:
- Create documents with known cross-boundary information
- Test retrieval with 0%, 10%, 20%, 30%, 50% overlap
- Measure ability to retrieve cross-boundary information

### H2: Deduplication Effectiveness
**Hypothesis**: Deduplication reduces redundant chunks without losing relevant information.

**Test Strategy**:
- Create documents with intentional duplicates
- Apply deduplication at various thresholds
- Verify relevant information is preserved

### H3: Chunk Boundary Integrity
**Hypothesis**: Chunks with proper overlap maintain semantic integrity at boundaries.

**Test Strategy**:
- Create sentences that span chunk boundaries
- Verify semantic meaning is preserved
- Check for truncated words or broken phrases

### H4: Silent Failure Detection
**Hypothesis**: Silent failures in chunk processing (truncation, duplication) can be detected through output validation.

**Test Strategy**:
- Inject known bad chunking configurations
- Verify detection through validation stages
- Measure false positive rate

### H5: Scale Performance
**Hypothesis**: Chunk overlap and deduplication scale linearly with document size.

**Test Strategy**:
- Process documents from 1KB to 10MB
- Measure processing time and memory usage
- Identify any non-linear scaling issues

## Success Criteria Definition

| Criterion | Metric | Target |
|-----------|--------|--------|
| **Context Preservation** | Cross-boundary info retrieval | >95% with 20% overlap |
| **Deduplication Accuracy** | Relevant info retained | >99% after dedupe |
| **Chunk Integrity** | No truncated chunks | 100% |
| **Performance Overhead** | Additional latency | <20% at 20% overlap |
| **Silent Failure Rate** | Undetected failures | <1% |
| **Scale Linearity** | Processing time growth | O(n) |

## Test Categories

1. **Correctness Tests**: Does chunking preserve semantic meaning?
2. **Overlap Tests**: Does overlap improve context retrieval?
3. **Deduplication Tests**: Does dedupe remove duplicates without data loss?
4. **Boundary Tests**: Are chunk boundaries handled correctly?
5. **Performance Tests**: What's the overhead of overlap/dedup?
6. **Silent Failure Tests**: Are chunking errors detected?

## References

1. Breaking up is hard to do: Chunking in RAG applications (Stack Overflow Blog, Dec 2024)
2. How Document Chunk Overlap Affects a RAG Pipeline (Ashish Abraham, Jul 2024)
3. The Ultimate Guide to RAG Chunking Strategies (Agenta, Aug 2025)
4. RAG Chunking Strategies For Better Retrieval (CustomGPT, Oct 2025)
5. Mastering Retrieval-Augmented Generation (DEV Community, Sep 2025)
6. Contextual Retrieval in AI Systems (Anthropic, Sep 2024)
7. Chunking Strategies for RAG (Adnan Masood, Nov 2025)
8. Stageflow Documentation - ENRICH Stages (stageflow-docs/guides/stages.md)
9. Stageflow Documentation - Context & Data Flow (stageflow-docs/guides/context.md)

## Next Steps

1. Create mock document generators with controllable chunking
2. Build test pipelines for overlap and deduplication
3. Execute comprehensive test suite
4. Log findings using add_finding.py
5. Generate final report
6. Update roadmap checklist entry
