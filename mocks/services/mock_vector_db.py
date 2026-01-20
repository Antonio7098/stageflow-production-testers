"""
Mock Vector Database Service for RAG Retrieval Testing

This module provides a mock vector database with configurable latency,
failure injection, and connection pool simulation for testing retrieval
latency under load in Stageflow ENRICH stages.
"""

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from enum import Enum
import hashlib


class FailureMode(Enum):
    NONE = "none"
    TIMEOUT = "timeout"
    ERROR = "error"
    LATENCY_SPIKE = "latency_spike"
    PARTIAL_RESULT = "partial_result"


@dataclass
class VectorDocument:
    """A document in the mock vector database."""
    id: str
    content: str
    embedding: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class RetrievalResult:
    """Result from a vector search operation."""
    documents: List[VectorDocument]
    latency_ms: float
    cache_hit: bool = False
    error: Optional[str] = None


@dataclass
class VectorDBConfig:
    """Configuration for the mock vector database."""
    base_latency_ms: float = 20.0
    latency_variance_ms: float = 5.0
    max_concurrent_connections: int = 100
    connection_acquire_timeout_ms: int = 5000
    cache_size: int = 1000
    cache_ttl_seconds: int = 300
    failure_rate: float = 0.0
    failure_mode: FailureMode = FailureMode.NONE
    index_size: int = 100000
    enable_latency_scaling: bool = True


class MockVectorDatabase:
    """
    Mock vector database for testing retrieval latency under load.
    
    Features:
    - Configurable base latency with variance
    - Connection pool simulation
    - Caching with TTL
    - Failure injection (timeouts, errors, latency spikes)
    - Index size-based latency scaling
    """

    def __init__(self, config: Optional[VectorDBConfig] = None):
        self.config = config or VectorDBConfig()
        self._documents: Dict[str, VectorDocument] = {}
        self._connection_semaphore = asyncio.Semaphore(self.config.max_concurrent_connections)
        self._cache: Dict[str, RetrievalResult] = {}
        self._cache_order: List[str] = []
        self._stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "connection_waits": 0,
            "failures": 0,
            "latencies": [],
        }
        self._latency_scale_factor = 1.0
        
        self._initialize_index()

    def _initialize_index(self):
        """Initialize the mock index with sample documents."""
        sample_contents = [
            "Stageflow is a Python framework for building observable, composable pipeline architectures.",
            "ENRICH stages add contextual information without transforming the core data.",
            "Vector databases store high-dimensional embeddings for similarity search.",
            "Retrieval-Augmented Generation combines search and generation for better answers.",
            "Circuit breakers prevent cascade failures in distributed systems.",
            "Connection pooling manages database connections efficiently under load.",
            "Caching reduces latency for repeated queries significantly.",
            "HNSW is a popular algorithm for approximate nearest neighbor search.",
            "Latency under load is a critical metric for production RAG systems.",
            "Stageflow supports multiple stage kinds: TRANSFORM, ENRICH, ROUTE, GUARD, WORK, AGENT.",
        ]
        
        for i in range(min(self.config.index_size, len(sample_contents) * 100)):
            content = sample_contents[i % len(sample_contents)]
            doc_id = f"doc_{i:06d}"
            embedding = self._generate_embedding(doc_id, content)
            
            self._documents[doc_id] = VectorDocument(
                id=doc_id,
                content=content,
                embedding=embedding,
                metadata={"index": i, "category": f"cat_{i % 10}"},
            )

    def _generate_embedding(self, doc_id: str, content: str) -> List[float]:
        """Generate a deterministic embedding based on document content."""
        hash_input = f"{doc_id}:{content}".encode()
        hash_bytes = hashlib.sha256(hash_input).digest()
        return [b / 255.0 for b in hash_bytes[:64]]

    def _get_cache_key(self, query: str, top_k: int) -> str:
        """Generate a cache key for a query."""
        return hashlib.md5(f"{query}:{top_k}".encode()).hexdigest()

    def _update_latency_scale(self):
        """Update latency scale factor based on index size and load."""
        if not self.config.enable_latency_scaling:
            return
        
        base_vectors = 100000
        current_vectors = len(self._documents)
        
        if current_vectors > base_vectors:
            scale = 1.0 + (current_vectors - base_vectors) / base_vectors * 0.5
            self._latency_scale_factor = min(scale, 3.0)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filter_fn: Optional[Callable[[VectorDocument], bool]] = None,
    ) -> RetrievalResult:
        """
        Search for documents similar to the query.
        
        Args:
            query: The search query
            top_k: Number of results to return
            filter_fn: Optional filter function for metadata filtering
            
        Returns:
            RetrievalResult with documents and latency info
        """
        start_time = time.perf_counter()
        self._stats["total_requests"] += 1
        
        cache_key = self._get_cache_key(query, top_k)
        
        if cache_key in self._cache:
            result = self._cache[cache_key]
            if time.time() - result.latency_ms / 1000 < self.config.cache_ttl_seconds:
                self._stats["cache_hits"] += 1
                return RetrievalResult(
                    documents=result.documents,
                    latency_ms=result.latency_ms,
                    cache_hit=True,
                )
        
        self._stats["cache_misses"] += 1
        
        try:
            async with self._connection_semaphore:
                self._stats["connection_waits"] += 1
                result = await self._execute_search(query, top_k, filter_fn)
        except asyncio.TimeoutError:
            self._stats["failures"] += 1
            return RetrievalResult(
                documents=[],
                latency_ms=self.config.connection_acquire_timeout_ms,
                error="Connection timeout",
            )
        except Exception as e:
            self._stats["failures"] += 1
            return RetrievalResult(
                documents=[],
                latency_ms=0,
                error=str(e),
            )
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        cache_result = RetrievalResult(
            documents=result.documents,
            latency_ms=elapsed_ms,
        )
        self._cache[cache_key] = cache_result
        self._cache_order.append(cache_key)
        
        while len(self._cache_order) > self.config.cache_size:
            old_key = self._cache_order.pop(0)
            self._cache.pop(old_key, None)
        
        self._stats["latencies"].append(elapsed_ms)
        return result

    async def _execute_search(
        self,
        query: str,
        top_k: int,
        filter_fn: Optional[Callable[[VectorDocument], bool]],
    ) -> RetrievalResult:
        """Execute the actual search with simulated latency."""
        self._update_latency_scale()
        
        base_latency = self.config.base_latency_ms * self._latency_scale_factor
        variance = random.uniform(-self.config.latency_variance_ms, self.config.latency_variance_ms)
        latency = max(1.0, base_latency + variance)
        
        if self.config.failure_mode == FailureMode.TIMEOUT:
            latency *= 10
            if random.random() < self.config.failure_rate:
                await asyncio.sleep(latency / 1000)
                raise asyncio.TimeoutError("Simulated timeout")
        
        elif self.config.failure_mode == FailureMode.ERROR:
            if random.random() < self.config.failure_rate:
                raise RuntimeError("Simulated vector DB error")
        
        elif self.config.failure_mode == FailureMode.LATENCY_SPIKE:
            if random.random() < self.config.failure_rate:
                latency *= 5
        
        await asyncio.sleep(latency / 1000)
        
        query_embedding = self._generate_embedding("query", query)
        
        candidates = []
        for doc in self._documents.values():
            if filter_fn and not filter_fn(doc):
                continue
            similarity = self._cosine_similarity(query_embedding, doc.embedding)
            candidates.append((doc, similarity))
        
        candidates.sort(key=lambda x: x[1], reverse=True)
        top_results = [doc for doc, _ in candidates[:top_k]]
        
        return RetrievalResult(documents=top_results, latency_ms=latency)

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a * norm_b == 0:
            return 0.0
        return dot_product / (norm_a * norm_b)

    def set_failure_mode(self, mode: FailureMode, failure_rate: float = 0.1):
        """Configure failure injection."""
        self.config.failure_mode = mode
        self.config.failure_rate = failure_rate

    def clear_cache(self):
        """Clear the query cache."""
        self._cache.clear()
        self._cache_order.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        latencies = self._stats["latencies"]
        return {
            "total_requests": self._stats["total_requests"],
            "cache_hits": self._stats["cache_hits"],
            "cache_misses": self._stats["cache_misses"],
            "cache_hit_rate": self._stats["cache_hits"] / max(1, self._stats["total_requests"]),
            "connection_waits": self._stats["connection_waits"],
            "failures": self._stats["failures"],
            "failure_rate": self._stats["failures"] / max(1, self._stats["total_requests"]),
            "latency_p50": sorted(latencies)[len(latencies) // 2] if latencies else 0,
            "latency_p95": sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
            "latency_p99": sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0,
            "index_size": len(self._documents),
        }

    def reset_stats(self):
        """Reset statistics counters."""
        self._stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "connection_waits": 0,
            "failures": 0,
            "latencies": [],
        }


class ConnectionPoolStats:
    """Track connection pool statistics."""
    
    def __init__(self, max_size: int):
        self.max_size = max_size
        self.active_connections = 0
        self.waiting_requests = 0
        self.total_acquired = 0
        self.total_released = 0
        self.timeouts = 0
    
    def acquire(self):
        self.total_acquired += 1
        if self.active_connections < self.max_size:
            self.active_connections += 1
            return True
        else:
            self.waiting_requests += 1
            return False
    
    def release(self):
        if self.active_connections > 0:
            self.active_connections -= 1
            self.total_released += 1
            if self.waiting_requests > 0:
                self.waiting_requests -= 1
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "active_connections": self.active_connections,
            "waiting_requests": self.waiting_requests,
            "max_size": self.max_size,
            "utilization": self.active_connections / self.max_size if self.max_size > 0 else 0,
            "total_acquired": self.total_acquired,
            "total_released": self.total_released,
            "timeouts": self.timeouts,
        }
