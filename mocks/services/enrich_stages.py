"""
ENRICH stages for retrieval testing in Stageflow.

This module provides ENRICH stages that demonstrate retrieval patterns
and can be used for latency testing under various conditions.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional
import logging

from stageflow import StageContext, StageKind, StageOutput
from stageflow.context import ContextSnapshot

from mocks.services.mock_vector_db import MockVectorDatabase, VectorDBConfig, FailureMode


logger = logging.getLogger(__name__)


class RetrievalEnrichStage:
    """
    ENRICH stage that performs vector similarity search.
    
    This stage queries the vector database for documents similar to the
    input query and adds them to the context for downstream stages.
    
    Usage:
        - Populates ctx.snapshot.documents with retrieved results
        - Emits retrieval latency metrics via events
        - Handles failures gracefully with appropriate output types
    """
    
    name = "retrieval_enrich"
    kind = StageKind.ENRICH
    
    def __init__(
        self,
        vector_db: Optional[MockVectorDatabase] = None,
        *,
        top_k: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None,
        fail_silently: bool = False,
    ):
        """
        Initialize the retrieval enrichment stage.
        
        Args:
            vector_db: Mock vector database instance (creates default if None)
            top_k: Number of documents to retrieve
            filter_metadata: Optional metadata filter
            fail_silently: If True, return empty results on failure instead of failing
        """
        self.vector_db = vector_db or MockVectorDatabase()
        self.top_k = top_k
        self.filter_metadata = filter_metadata
        self.fail_silently = fail_silently
        self._retrieval_count = 0
        self._total_latency_ms = 0.0
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        """
        Execute the retrieval enrichment.
        
        Retrieves documents from the vector database based on the
        input query and adds them to the context.
        """
        snapshot = ctx.snapshot
        query = snapshot.input_text or ""
        
        if not query:
            if self.fail_silently:
                return StageOutput.ok(documents=[], message="No query provided")
            return StageOutput.skip(reason="No query provided for retrieval")
        
        start_time = time.perf_counter()
        self._retrieval_count += 1
        
        try:
            filter_fn = None
            if self.filter_metadata:
                def create_filter(metadata: Dict[str, Any]):
                    def filter_doc(doc):
                        for key, value in metadata.items():
                            if doc.metadata.get(key) != value:
                                return False
                        return True
                    return filter_fn
                filter_fn = create_filter(self.filter_metadata)
            
            result = await self.vector_db.search(
                query=query,
                top_k=self.top_k,
                filter_fn=filter_fn,
            )
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self._total_latency_ms += elapsed_ms
            
            ctx.try_emit_event(
                "retrieval.completed",
                {
                    "query": query[:100],
                    "latency_ms": elapsed_ms,
                    "results_count": len(result.documents),
                    "cache_hit": result.cache_hit,
                    "error": result.error,
                }
            )
            
            if result.error:
                if self.fail_silently:
                    logger.warning(f"Retrieval error (silently handling): {result.error}")
                    return StageOutput.ok(
                        documents=[],
                        error=result.error,
                        latency_ms=elapsed_ms,
                    )
                return StageOutput.fail(
                    error=result.error,
                    data={"query": query[:100], "latency_ms": elapsed_ms},
                )
            
            documents_data = [
                {
                    "id": doc.id,
                    "content": doc.content,
                    "metadata": doc.metadata,
                }
                for doc in result.documents
            ]
            
            return StageOutput.ok(
                documents=documents_data,
                document_count=len(documents_data),
                latency_ms=elapsed_ms,
                cache_hit=result.cache_hit,
            )
            
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"Retrieval timeout after {elapsed_ms:.2f}ms")
            
            if self.fail_silently:
                return StageOutput.ok(documents=[], error="Timeout", latency_ms=elapsed_ms)
            return StageOutput.fail(
                error="Retrieval timeout",
                data={"timeout_ms": elapsed_ms},
            )
            
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(f"Unexpected retrieval error: {e}")
            
            if self.fail_silently:
                return StageOutput.ok(documents=[], error=str(e), latency_ms=elapsed_ms)
            return StageOutput.fail(
                error=f"Retrieval failed: {str(e)}",
                data={"latency_ms": elapsed_ms},
            )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get retrieval statistics."""
        return {
            "retrieval_count": self._retrieval_count,
            "total_latency_ms": self._total_latency_ms,
            "avg_latency_ms": self._total_latency_ms / max(1, self._retrieval_count),
        }
    
    def reset_stats(self):
        """Reset statistics."""
        self._retrieval_count = 0
        self._total_latency_ms = 0.0


class CacheableRetrievalEnrichStage(RetrievalEnrichStage):
    """
    ENRICH stage with caching support for repeated queries.
    
    Extends the base retrieval stage with explicit caching that
    can be controlled via stage inputs.
    """
    
    name = "cacheable_retrieval_enrich"
    
    def __init__(
        self,
        vector_db: Optional[MockVectorDatabase] = None,
        *,
        top_k: int = 5,
        cache_ttl_seconds: int = 300,
    ):
        super().__init__(vector_db=vector_db, top_k=top_k)
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        snapshot = ctx.snapshot
        query = snapshot.input_text or ""
        use_cache = ctx.inputs.get("use_cache", True)
        
        cache_key = f"{query}:{self.top_k}"
        
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            if time.time() - cached["timestamp"] < self.cache_ttl_seconds:
                ctx.try_emit_event("retrieval.cache_hit", {"query": query[:50]})
                return StageOutput.ok(
                    documents=cached["documents"],
                    document_count=len(cached["documents"]),
                    latency_ms=1.0,
                    cache_hit=True,
                )
        
        result = await super().execute(ctx)
        
        if result.status.value == "ok":
            self._cache[cache_key] = {
                "documents": result.data.get("documents", []),
                "timestamp": time.time(),
            }
        
        return result
    
    def clear_cache(self):
        """Clear the query cache."""
        self._cache.clear()


class BatchedRetrievalEnrichStage(RetrievalEnrichStage):
    """
    ENRICH stage that handles batched retrieval requests.
    
    Useful for scenarios where multiple queries need to be
    processed together for efficiency.
    """
    
    name = "batched_retrieval_enrich"
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        snapshot = ctx.snapshot
        queries = ctx.inputs.get("queries", [])
        
        if not queries:
            return await super().execute(ctx)
        
        results = []
        total_latency = 0.0
        total_cache_hits = 0
        
        start_time = time.perf_counter()
        
        for query in queries:
            result = await self.vector_db.search(query=query, top_k=self.top_k)
            results.append({
                "query": query,
                "documents": [
                    {"id": doc.id, "content": doc.content}
                    for doc in result.documents
                ],
                "latency_ms": result.latency_ms,
            })
            total_latency += result.latency_ms
            if result.cache_hit:
                total_cache_hits += 1
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        return StageOutput.ok(
            batch_results=results,
            query_count=len(queries),
            total_latency_ms=total_latency,
            avg_latency_ms=total_latency / len(queries),
            cache_hits=total_cache_hits,
        )


class FallbackRetrievalEnrichStage(RetrievalEnrichStage):
    """
    ENRICH stage with fallback to cached results on failure.
    
    Demonstrates resilience patterns where failures trigger
    fallback to stale but available cached data.
    """
    
    name = "fallback_retrieval_enrich"
    
    def __init__(
        self,
        vector_db: Optional[MockVectorDatabase] = None,
        *,
        top_k: int = 5,
        fallback_ttl_seconds: int = 3600,
    ):
        super().__init__(vector_db=vector_db, top_k=top_k)
        self.fallback_ttl_seconds = fallback_ttl_seconds
        self._fallback_cache: Dict[str, Dict[str, Any]] = {}
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        snapshot = ctx.snapshot
        query = snapshot.input_text or ""
        
        result = await super().execute(ctx)
        
        if result.status.value == "fail":
            cache_key = f"{query}:{self.top_k}"
            
            if cache_key in self._fallback_cache:
                cached = self._fallback_cache[cache_key]
                if time.time() - cached["timestamp"] < self.fallback_ttl_seconds:
                    ctx.try_emit_event("retrieval.fallback_used", {"query": query[:50]})
                    return StageOutput.ok(
                        documents=cached["documents"],
                        document_count=len(cached["documents"]),
                        latency_ms=5.0,
                        fallback=True,
                        warning="Using stale cached results due to retrieval failure",
                    )
            
            return StageOutput.fail(
                error=result.data.get("error", "Unknown error"),
                data=result.data,
            )
        
        cache_key = f"{query}:{self.top_k}"
        self._fallback_cache[cache_key] = {
            "documents": result.data.get("documents", []),
            "timestamp": time.time(),
        }
        
        return result
