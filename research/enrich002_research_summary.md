# ENRICH-002 Research Summary: Embedding Drift and Index Desync

## Overview

**Target**: Embedding drift and index desync in RAG/Knowledge ENRICH stages
**Priority**: P1
**Risk Classification**: Severe
**Industry Vertical**: 2.2 ENRICH Stages (RAG/Knowledge)

## Research Questions

1. What causes embedding drift in production RAG systems?
2. How does index desync affect retrieval quality?
3. What silent failures can occur without detection?
4. How can Stageflow's ENRICH stage architecture be stress-tested?

## Key Findings from Web Research

### 1. Embedding Drift Definition

Embedding drift occurs when **the same text produces different embeddings over time due to small changes upstream or around the embedding process**. This is NOT about the text changing meaning, but about structural differences in the vector representation.

**Critical Insight**: Embedding drift is the "third major failure point in RAG workflows—after ingestion and chunking" and typically manifests as silent correctness failures.

### 2. Root Causes of Embedding Drift

| Cause | Description | Detection Difficulty |
|-------|-------------|---------------------|
| **Text-Shape Differences** | Whitespace changes, markdown shifts, PDF quirks affecting token patterns | Low |
| **Hidden Characters** | OCR noise, HTML remnants, non-breaking spaces affecting tokenization | Medium |
| **Non-Deterministic Preprocessing** | Cleanup rules differing between environments | Medium |
| **Chunk-Boundary Drift** | Segmentation changes affecting context windows | High |
| **Partial Re-Embedding** | #1 Silent Killer - mixing old/new embeddings | High |
| **Embedding Model Updates** | Minor model versions causing vector-space reshaping | Low |
| **Index Rebuild Drift** | FAISS/HNSW parameter variations across builds | Medium |

### 3. Detection Strategies

#### Cosine Distance Comparison
- Take sample document, embed at different times
- Stable systems: distance ≈ 0.0001–0.005
- Unstable systems: distance ≥ 0.05 (sometimes 0.10+)

#### Nearest-Neighbor Stability
- Run same query at different times
- Stable: 85–95% of neighbors persist
- Drifting: 25–40% drop off silently

#### Vector Norm Variance
- Different norms indicate different preprocessing/model versions

#### Embedding Distribution Drift
- Plot histogram of embedding magnitudes
- Shape changes over time indicate drift

### 4. Mitigation Strategies

1. **Enforce Deterministic Preprocessing**: Identical rules every time
2. **Store Canonical Text**: Never re-extract dynamically
3. **Re-Embed Entire Corpus**: Never mix embeddings from different versions
4. **Pin Embedding Model Version**: No silent updates
5. **Auto-Run Drift Checks Weekly**: Compare embeddings over time
6. **Track Metadata in Vector Store**: Model version, preprocessing hash, text checksum

### 5. Industry Impact

- Engineers spend 10–30 hours/month troubleshooting RAG issues starting with embedding drift
- Outdated embeddings can cause performance declines of up to 20% in LLM tasks
- Most retrieval problems blamed on models are actually embedding drift problems

## Stageflow-Specific Analysis

### ENRICH Stage Architecture

Based on `stageflow-docs/guides/stages.md`:
- ENRICH stages add contextual information without transforming core data
- Used for: Profile lookup, memory retrieval, document fetching, external data enrichment
- Output: `StageOutput.ok()` with enrichment data added to context

### Context System

From `stageflow-docs/guides/context.md`:
- `DocumentEnrichment` structure stores document context
- `ContextSnapshot.documents` field contains retrieved documents
- Enrichments flow through immutable snapshots

### Potential Failure Modes in Stageflow

| Failure Mode | Description | Stageflow Component |
|--------------|-------------|---------------------|
| **Silent Retrieval Failure** | ENRICH stage returns empty documents without error | StageOutput handling |
| **Index Desync** | Document embeddings don't match query embeddings | Vector store integration |
| **Partial Enrichment** | Some documents enriched, others silently skipped | OutputBag collection |
| **Metadata Loss** | Document provenance information dropped | ContextSnapshot creation |
| **Version Mismatch** | Old embeddings queried against new index | External vector DB |

### Key Stageflow APIs for Testing

```python
from stageflow import StageKind, StageOutput

class DocumentEnrichStage:
    name = "document_enrich"
    kind = StageKind.ENRICH
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        # Access query
        query = ctx.snapshot.input_text
        
        # Retrieve documents (potential failure point)
        documents = await self.vector_store.similarity_search(query)
        
        # Return enrichment (potential silent failure)
        return StageOutput.ok(
            documents=[
                DocumentEnrichment(...),
            ]
        )
```

## Hypotheses to Test

### H1: Silent Document Drop
**Hypothesis**: ENRICH stages can silently drop documents during retrieval without raising errors.

**Test Strategy**:
- Mock vector store returning degraded results
- Verify downstream stages receive incomplete enrichment
- Check if silent failures occur without logging

### H2: Embedding Version Mismatch
**Hypothesis**: Mixing document embeddings from different model versions causes retrieval failures.

**Test Strategy**:
- Create index with mixed-version embeddings
- Execute queries and measure relevance degradation
- Verify if errors are raised or silent

### H3: Index Desync Detection
**Hypothesis**: Stageflow lacks mechanisms to detect when document index is out of sync with embeddings.

**Test Strategy**:
- Create desynchronized index (embeddings don't match documents)
- Execute pipeline and observe behavior
- Check if Stageflow detects or propagates the issue

### H4: Partial Re-Embedding Impact
**Hypothesis**: Partial re-embedding of documents causes inconsistent retrieval without errors.

**Test Strategy**:
- Create index with 70% new embeddings, 30% old
- Run queries and measure neighbor overlap
- Verify if Stageflow handles mixed embeddings

### H5: Context Corruption via Drift
**Hypothesis**: Embedding drift can corrupt the ContextSnapshot in ways that propagate silently.

**Test Strategy**:
- Inject drift into document enrichment
- Track context changes through pipeline
- Verify if corruption is detected

## Success Criteria Definition

| Criterion | Metric | Target |
|-----------|--------|--------|
| **Detection Coverage** | % of drift scenarios detected | 100% |
| **Silent Failure Rate** | % of failures without error/trace | <5% |
| **Latency Impact** | Additional latency from drift detection | <50ms |
| **Recovery Success** | % of failures recovered gracefully | >80% |
| **False Positive Rate** | % of normal operations flagged as drift | <1% |

## Test Categories

1. **Correctness Tests**: Does retrieval return correct documents?
2. **Reliability Tests**: Does system handle drift gracefully?
3. **Performance Tests**: Does drift detection add acceptable overhead?
4. **Silent Failure Tests**: Are failures detected vs. silent?
5. **Recovery Tests**: Can system recover from drift?

## References

1. Embedding Drift: The Quiet Killer of Retrieval Quality in RAG Systems (Medium, Dec 2025)
2. When Embeddings Go Stale: Detecting & Fixing Retrieval Drift in Production (Medium, Oct 2025)
3. 23 RAG Pitfalls and How to Fix Them (Non-Brand Data, Aug 2025)
4. Stageflow Documentation - Building Stages (guides/stages.md)
5. Stageflow Documentation - Context & Data Flow (guides/context.md)
6. Stageflow Documentation - API Reference (api/core.md, api/context.md)
7. Mission Brief - Embedding Drift and Index Desync (docs/roadmap/mission-brief.md lines 146, 303)

## Next Steps

1. Create mock embedding service with drift injection
2. Build test pipelines simulating embedding drift
3. Execute comprehensive test suite
4. Log findings using add_finding.py
5. Generate final report
