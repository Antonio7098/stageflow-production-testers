# ENRICH-008 Research Summary: Retrieval Latency Under Load

**Run ID**: run-2026-01-20-001
**Agent**: claude-3.5-sonnet
**Date**: 2026-01-20
**Target**: Retrieval latency under load
**Priority**: P1
**Risk**: Moderate

---

## 1. Research Summary

### 1.1 Industry Context

Retrieval-Augmented Generation (RAG) has become a dominant pattern for building knowledge-augmented AI systems. According to recent research from ETH Zurich and Georgia Tech, RAG systems combine vector similarity search with LLMs to deliver accurate, context-aware responses. The key challenge is that co-locating the vector retriever and LLM on shared infrastructure introduces significant challenges: vector search is memory and I/O-intensive, while LLM inference demands high throughput and low latency.

**Key Industry Requirements:**
- Sub-50ms query latency for production workloads (Pinecone SLA)
- 99.99% uptime for enterprise deployments
- Handle billion-scale vector indexes with predictable latency
- Graceful degradation under burst load

**Real-World Failure Incidents:**
- HNSW index latency spikes at 700K-1.2M vectors (p95/p99 become erratic)
- Connection storms overwhelming databases when multiple service instances each open hundreds of connections
- Cache invalidation storms during index updates causing thundering herd problems

### 1.2 Technical Context

**State of the Art Approaches:**

1. **Semantic Pyramid Indexing (SPI)**: Multi-resolution vector indexing that adapts to query semantic granularity
2. **VectorLiteRAG**: Latency-aware resource partitioning for efficient RAG deployment
3. **Approximate Caching**: Caching strategies for faster RAG retrieval
4. **Distributed Parallel Multi-Resolution Search**: Hyper-efficient RAG in vector databases

**Known Failure Modes:**

| Failure Mode | Technical Mechanism | Impact |
|--------------|---------------------|--------|
| HNSW Latency Spikes | Index size threshold at 700K-1.2M vectors | p95/p99 latency becomes erratic |
| Connection Pool Exhaustion | Each service instance opens hundreds of connections | Database refuses connections |
| Cache Miss Storms | Index updates cause cache invalidation | Latency spikes 3-5x baseline |
| Thread Contention | Shared GPU infrastructure between vector search and LLM | Severe performance degradation |
| Recall-Latency Tradeoff | Higher accuracy requires more search parameters | Latency increases non-linearly |

**Academic Research References:**
- "RAGO: Systematic Performance Optimization for RAG Serving" (arXiv:2503.14649)
- "VectorLiteRAG: Latency-Aware Resource Partitioning" (arXiv:2504.08930)
- "RAG-Stack: Co-Optimizing RAG Quality and Performance" (arXiv:2510.20296)
- "Towards Hyper-Efficient RAG Systems" (arXiv:2511.16681)

### 1.3 Stageflow-Specific Context

ENRICH stages in Stageflow are designed for:
- Profile lookup and enrichment
- Memory retrieval
- Document fetching
- External data enrichment

**Relevant Stageflow Components:**
- `StageKind.ENRICH` - Categorization for enrichment stages
- `ContextSnapshot` - Immutable state with profile, memory, documents fields
- `StageOutput.ok()` - Standard success output
- Interceptors for cross-cutting concerns (timeout, circuit breaker)

**Extension Points for Latency Management:**
- Custom interceptors for retry/backoff
- Circuit breaker patterns for downstream service failures
- Telemetry integration for latency monitoring

### 1.4 Hypotheses to Test

| # | Hypothesis | Test Method |
|---|------------|-------------|
| H1 | Retrieval latency degrades predictably with concurrent requests | Concurrency ramp-up test |
| H2 | Circuit breakers prevent cascade failures | Chaos injection test |
| H3 | Caching reduces latency by >50% for repeated queries | Cache hit/miss comparison |
| H4 | Silent failures occur when timeouts are misconfigured | Timeout boundary test |
| H5 | Connection pool exhaustion causes silent failures | Connection saturation test |

### 1.5 Success Criteria

- Latency P95 < 200ms under 10 concurrent retrievals
- Latency P99 < 500ms under 50 concurrent retrievals
- Zero silent failures during 1000+ retrieval requests
- Recovery time < 5s after failure injection
- Circuit breaker activates within 3 consecutive failures

---

## 2. Web Search Results Summary

### 2.1 Key Findings

1. **HNSW Index Scaling**: Latency spikes occur at 700K-1.2M vectors due to graph traversal complexity increases. The p50/p75 stay flat but p95/p99 become erratic.

2. **Connection Pooling**: High concurrency without proper connection pooling leads to "connection storms" that overwhelm databases.

3. **Cache Effectiveness**: Production RAG systems show 72% cache hit rates with 25-45ms latency (vs 100-180ms for cache misses).

4. **Resource Contention**: Vector search and LLM inference compete for GPU memory, causing severe degradation under load.

5. **Production RAG Failure Modes**:
   - Retrieval latency under load
   - Stale index data
   - Bad chunking causing irrelevant results
   - Reranker bottlenecks
   - Context overload

### 2.2 Citations

| # | Source | Relevance |
|---|--------|-----------|
| 1 | arXiv:2503.14649 (RAGO) | Systematic RAG performance optimization |
| 2 | arXiv:2504.08930 (VectorLiteRAG) | Resource partitioning for RAG |
| 3 | arXiv:2510.20296 (RAG-Stack) | Quality and performance co-optimization |
| 4 | arXiv:2511.16681 | Distributed multi-resolution vector search |
| 5 | Medium: HNSW Explained | Practical HNSW latency troubleshooting |
| 6 | Medium: Connection Pooling | High concurrency database patterns |
| 7 | TopK Bench Benchmark | Real-world vector database benchmarks |
| 8 | DeconvoluteAI: RAG Failures | Production RAG failure taxonomy |

---

## 3. Research Artifacts

### 3.1 Test Scenarios

1. **Baseline**: Single-threaded retrieval with mock vector DB
2. **Concurrency Test**: Ramp from 1 to 100 concurrent requests
3. **Stress Test**: Sustained 50 concurrent requests for 5 minutes
4. **Chaos Test**: Simulate vector DB timeouts and errors
5. **Recovery Test**: Verify system recovery after failure injection

### 3.2 Metrics to Capture

- P50, P75, P95, P99 latency
- Throughput (requests/second)
- Error rate
- Circuit breaker activation count
- Cache hit/miss ratio
- Connection pool utilization

---

## 4. Next Steps

1. Create mock vector database with configurable latency
2. Build ENRICH stage with retrieval logic
3. Implement test pipelines (baseline, stress, chaos, recovery)
4. Execute tests and capture metrics
5. Log findings and generate report
