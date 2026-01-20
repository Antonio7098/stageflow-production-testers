"""
ENRICH-007 Vector DB Connection Resilience Mocks

This module provides mock vector database services with configurable
connection failure injection for stress-testing Stageflow pipelines.

Features:
- Simulate various connection failure modes
- Configurable latency injection
- Circuit breaker state simulation
- Connection pool exhaustion simulation
- Silent failure patterns
- Retry tracking and metrics
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """Vector DB connection states."""
    CONNECTING = "connecting"
    ACTIVE = "active"
    IDLE = "idle"
    STALE = "stale"
    FAILED = "failed"
    CLOSED = "closed"


class FailureMode(Enum):
    """Types of connection failures to simulate."""
    NONE = "none"
    TIMEOUT = "timeout"
    CONNECTION_REFUSED = "connection_refused"
    AUTH_FAILURE = "auth_failure"
    SERVICE_UNAVAILABLE = "service_unavailable"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    NETWORK_PARTITION = "network_partition"
    QUERY_TIMEOUT = "query_timeout"
    PARTIAL_WRITE = "partial_write"
    SILENT_EMPTY = "silent_empty"
    VERSION_MISMATCH = "version_mismatch"


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class VectorDocument:
    """Represents a document in the vector store."""
    document_id: str
    chunk_id: str
    content: str
    embedding: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    embedding_version: str = "v1.0"
    index_version: str = "v1.0"


@dataclass
class SearchResult:
    """Result of a similarity search operation."""
    documents: List[Dict[str, Any]]
    search_time_ms: float
    drift_score: float = 0.0
    neighbor_overlap_with_previous: float = 1.0
    is_desynced: bool = False
    silent_failure: bool = False
    error_message: Optional[str] = None
    connection_attempts: int = 1
    retry_count: int = 0
    cb_state: CircuitBreakerState = CircuitBreakerState.CLOSED


@dataclass
class WriteResult:
    """Result of a write operation."""
    success: bool
    documents_written: int
    documents_total: int
    error_message: Optional[str] = None
    latency_ms: float = 0.0
    partial_failure: bool = False


@dataclass
class ConnectionMetrics:
    """Metrics for connection pool and operations."""
    total_connections_created: int = 0
    total_connections_closed: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    failed_connections: int = 0
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    total_retries: int = 0
    circuit_breaker_trips: int = 0
    circuit_breaker_resets: int = 0
    avg_query_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0


class VectorDBFailureInjector:
    """
    Configurable failure injector for vector DB operations.
    
    This class simulates various failure modes that can occur in production
    vector database deployments, allowing comprehensive resilience testing.
    """
    
    def __init__(
        self,
        base_latency_ms: float = 50.0,
        failure_rate: float = 0.0,
        timeout_ms: float = 5000.0,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_timeout_ms: float = 30000.0,
    ):
        self.base_latency_ms = base_latency_ms
        self.failure_rate = failure_rate
        self.timeout_ms = timeout_ms
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_timeout_ms = circuit_breaker_timeout_ms
        
        # Circuit breaker state
        self._circuit_state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_successes = 0
        
        # Failure tracking
        self._failure_mode = FailureMode.NONE
        self._failure_message: Optional[str] = None
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        
        # Latency injection
        self._latency_jitter = 0.2  # 20% jitter
        self._latency_spike_probability = 0.0
        self._latency_spike_multiplier = 10.0
        
        # Metrics
        self._metrics = ConnectionMetrics()
        self._query_latencies: List[float] = []
        self._max_latency_samples = 1000
        
        # Silent failure tracking
        self._silent_failure_count = 0
        self._total_operations = 0
        
    @property
    def circuit_state(self) -> CircuitBreakerState:
        return self._circuit_state
    
    @property
    def metrics(self) -> ConnectionMetrics:
        return self._metrics
    
    def set_failure_mode(
        self,
        mode: FailureMode,
        message: Optional[str] = None,
        probability: float = 1.0,
    ):
        """Set the current failure mode."""
        self._failure_mode = mode
        self._failure_message = message
        self.failure_rate = probability
        logger.info(f"Failure mode set to: {mode.value} (prob={probability})")
    
    def set_latency(
        self,
        base_ms: float,
        jitter: float = 0.2,
        spike_probability: float = 0.0,
        spike_multiplier: float = 10.0,
    ):
        """Configure latency injection."""
        self.base_latency_ms = base_ms
        self._latency_jitter = jitter
        self._latency_spike_probability = spike_probability
        self._latency_spike_multiplier = spike_multiplier
        logger.info(f"Latency configured: base={base_ms}ms, jitter={jitter}")
    
    def reset(self):
        """Reset failure injector to initial state."""
        self._circuit_state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        self._half_open_successes = 0
        self._failure_mode = FailureMode.NONE
        self._failure_message = None
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._query_latencies.clear()
        self._silent_failure_count = 0
        self._total_operations = 0
        logger.info("Failure injector reset to initial state")
    
    def _should_fail(self) -> bool:
        """Determine if current operation should fail."""
        if self._failure_mode == FailureMode.NONE:
            return random.random() < self.failure_rate
        return random.random() < self.failure_rate
    
    def _calculate_latency(self) -> float:
        """Calculate latency with jitter and spikes."""
        latency = self.base_latency_ms
        
        # Add jitter
        jitter_factor = 1.0 + random.uniform(-self._latency_jitter, self._latency_jitter)
        latency *= jitter_factor
        
        # Check for latency spike
        if random.random() < self._latency_spike_probability:
            latency *= self._latency_spike_multiplier
        
        # Add small random variation
        latency += random.uniform(-5, 5)
        
        return max(0, latency)
    
    async def _execute_with_failure_handling(
        self,
        operation: str,
        coro,
        is_write: bool = False,
    ) -> Tuple[Any, bool]:  # Returns (result, is_success)
        """
        Execute an operation with failure injection and circuit breaker handling.
        
        Returns:
            Tuple of (result, is_success) where is_success indicates if operation
            completed without critical failure.
        """
        self._total_operations += 1
        start_time = time.perf_counter()
        
        # Check circuit breaker state
        if self._circuit_state == CircuitBreakerState.OPEN:
            # Check if timeout has elapsed for half-open transition
            if self._last_failure_time:
                elapsed = (time.perf_counter() - self._last_failure_time) * 1000
                if elapsed >= self.circuit_breaker_timeout_ms:
                    self._circuit_state = CircuitBreakerState.HALF_OPEN
                    self._half_open_successes = 0
                    logger.info("Circuit breaker transitioning to HALF_OPEN")
                else:
                    self._metrics.failed_queries += 1
                    return (
                        SearchResult(
                            documents=[],
                            search_time_ms=0,
                            error_message="Circuit breaker OPEN",
                            silent_failure=True,
                        )
                        if not is_write
                        else WriteResult(
                            success=False,
                            documents_written=0,
                            documents_total=0,
                            error_message="Circuit breaker OPEN",
                        ),
                        False,
                    )
        
        # Check for timeout in HALF_OPEN state (only allow limited operations)
        if self._circuit_state == CircuitBreakerState.HALF_OPEN:
            # Only allow 3 test operations
            pass  # Allow through, track separately
        
        # Apply failure injection
        should_fail = self._should_fail()
        
        if should_fail and self._failure_mode != FailureMode.NONE:
            # Simulate specific failure mode
            await self._simulate_failure(is_write)
            return None, False
        
        # Execute operation with timeout
        try:
            # Check for timeout (simulation)
            if random.random() < (self.failure_rate * 0.3):
                await asyncio.sleep(self.timeout_ms / 1000 + 0.1)
                raise asyncio.TimeoutError()
            
            result = await asyncio.wait_for(
                coro,
                timeout=self.timeout_ms / 1000,
            )
            
            # Record success
            latency_ms = (time.perf_counter() - start_time) * 1000
            self._record_success(latency_ms)
            
            # Handle circuit breaker state transitions
            self._handle_success()
            
            return result, True
            
        except asyncio.TimeoutError:
            self._metrics.failed_queries += 1
            self._record_failure()
            self._handle_failure(f"Timeout after {self.timeout_ms}ms")
            
            return (
                SearchResult(
                    documents=[],
                    search_time_ms=self.timeout_ms,
                    error_message="Query timeout",
                    silent_failure=self._failure_mode == FailureMode.SILENT_EMPTY,
                )
                if not is_write
                else WriteResult(
                    success=False,
                    documents_written=0,
                    documents_total=0,
                    error_message="Write timeout",
                ),
                False,
            )
            
        except Exception as e:
            self._metrics.failed_queries += 1
            self._record_failure()
            self._handle_failure(str(e))
            
            return (
                SearchResult(
                    documents=[],
                    search_time_ms=(time.perf_counter() - start_time) * 1000,
                    error_message=str(e),
                )
                if not is_write
                else WriteResult(
                    success=False,
                    documents_written=0,
                    documents_total=0,
                    error_message=str(e),
                ),
                False,
            )
    
    async def _simulate_failure(self, is_write: bool):
        """Simulate specific failure mode."""
        failure_messages = {
            FailureMode.TIMEOUT: "Connection timeout",
            FailureMode.CONNECTION_REFUSED: "Connection refused by remote host",
            FailureMode.AUTH_FAILURE: "Authentication failed: invalid credentials",
            FailureMode.SERVICE_UNAVAILABLE: "Service temporarily unavailable",
            FailureMode.RESOURCE_EXHAUSTED: "Resource exhausted: memory/disk limit",
            FailureMode.NETWORK_PARTITION: "Network partition detected",
            FailureMode.QUERY_TIMEOUT: "Query execution timeout",
            FailureMode.PARTIAL_WRITE: "Partial write: some documents failed",
            FailureMode.SILENT_EMPTY: "Silent empty result (no error)",
            FailureMode.VERSION_MISMATCH: "Index version mismatch",
        }
        
        message = self._failure_message or failure_messages.get(
            self._failure_mode,
            "Unknown failure",
        )
        
        # Simulate latency for failure
        await asyncio.sleep(self._calculate_latency() / 1000)
        
        # Raise appropriate exception or return silently
        if self._failure_mode == FailureMode.SILENT_EMPTY:
            self._silent_failure_count += 1
            # Don't raise, just return empty
            return
        elif self._failure_mode == FailureMode.PARTIAL_WRITE:
            # Partial failure
            raise PartialWriteError(message, written=5, total=10)
        else:
            # Raise exception for other failures
            error_classes = {
                FailureMode.TIMEOUT: asyncio.TimeoutError,
                FailureMode.CONNECTION_REFUSED: ConnectionRefusedError,
                FailureMode.AUTH_FAILURE: AuthenticationError,
                FailureMode.SERVICE_UNAVAILABLE: ServiceUnavailableError,
                FailureMode.RESOURCE_EXHAUSTED: ResourceExhaustedError,
                FailureMode.NETWORK_PARTITION: NetworkPartitionError,
                FailureMode.QUERY_TIMEOUT: asyncio.TimeoutError,
                FailureMode.VERSION_MISMATCH: VersionMismatchError,
            }
            
            error_class = error_classes.get(self._failure_mode, Exception)
            raise error_class(message)
    
    def _record_success(self, latency_ms: float):
        """Record a successful operation."""
        self._metrics.successful_queries += 1
        self._metrics.total_queries += 1
        self._query_latencies.append(latency_ms)
        
        # Keep only recent latencies
        if len(self._query_latencies) > self._max_latency_samples:
            self._query_latencies = self._query_latencies[-self._max_latency_samples:]
        
        # Update average latency
        if self._query_latencies:
            self._metrics.avg_query_latency_ms = sum(self._query_latencies) / len(self._query_latencies)
            sorted_latencies = sorted(self._query_latencies)
            n = len(sorted_latencies)
            self._metrics.p50_latency_ms = sorted_latencies[n // 2]
            self._metrics.p95_latency_ms = sorted_latencies[int(n * 0.95)]
            self._metrics.p99_latency_ms = sorted_latencies[int(n * 0.99)]
    
    def _record_failure(self):
        """Record a failed operation."""
        self._failure_count += 1
        self._consecutive_failures += 1
        self._consecutive_successes = 0
        self._last_failure_time = time.perf_counter()
    
    def _handle_success(self):
        """Handle successful operation for circuit breaker."""
        self._consecutive_successes += 1
        
        if self._circuit_state == CircuitBreakerState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= 3:
                self._circuit_state = CircuitBreakerState.CLOSED
                self._failure_count = 0
                self._metrics.circuit_breaker_resets += 1
                logger.info("Circuit breaker transitioning to CLOSED")
    
    def _handle_failure(self, error_message: str):
        """Handle failed operation for circuit breaker."""
        self._consecutive_failures += 1
        self._consecutive_successes = 0
        
        if self._circuit_state == CircuitBreakerState.HALF_OPEN:
            # Any failure in half-open returns to open
            self._circuit_state = CircuitBreakerState.OPEN
            self._last_failure_time = time.perf_counter()
            logger.info(f"Circuit breaker returned to OPEN due to: {error_message}")
        elif self._circuit_state == CircuitBreakerState.CLOSED:
            if self._consecutive_failures >= self.circuit_breaker_threshold:
                self._circuit_state = CircuitBreakerState.OPEN
                self._metrics.circuit_breaker_trips += 1
                self._last_failure_time = time.perf_counter()
                logger.warning(
                    f"Circuit breaker OPEN after {self._consecutive_failures} failures"
                )
    
    def get_drift_metrics(self) -> Dict[str, Any]:
        """Get current drift and silent failure metrics."""
        return {
            "total_operations": self._total_operations,
            "silent_failures": self._silent_failure_count,
            "silent_failure_rate": (
                self._silent_failure_count / self._total_operations
                if self._total_operations > 0 else 0
            ),
            "circuit_state": self._circuit_state.value,
            "consecutive_failures": self._consecutive_failures,
            "consecutive_successes": self._consecutive_successes,
            "latency_p50_ms": self._metrics.p50_latency_ms,
            "latency_p95_ms": self._metrics.p95_latency_ms,
            "latency_p99_ms": self._metrics.p99_latency_ms,
            "failure_rate": self._failure_count / self._total_operations if self._total_operations > 0 else 0,
        }


# Custom exception classes for failure simulation
class VectorDBError(Exception):
    """Base exception for vector DB errors."""
    pass


class ConnectionError(VectorDBError):
    """Connection-related error."""
    pass


class ConnectionRefusedError(ConnectionError):
    """Connection was refused by remote host."""
    pass


class AuthenticationError(VectorDBError):
    """Authentication failed."""
    pass


class ServiceUnavailableError(VectorDBError):
    """Service is temporarily unavailable."""
    pass


class ResourceExhaustedError(VectorDBError):
    """Resource (memory/disk) exhausted."""
    pass


class NetworkPartitionError(VectorDBError):
    """Network partition detected."""
    pass


class TimeoutError(VectorDBError):
    """Operation timed out."""
    pass


class QueryTimeoutError(TimeoutError):
    """Query execution timed out."""
    pass


class PartialWriteError(VectorDBError):
    """Partial write failure."""
    
    def __init__(self, message: str, written: int, total: int):
        super().__init__(message)
        self.written = written
        self.total = total


class VersionMismatchError(VectorDBError):
    """Index version mismatch."""
    pass


class MockVectorStore:
    """
    Mock vector database store with configurable failure modes.
    
    This class simulates a production vector database with:
    - Document storage and similarity search
    - Configurable failure injection
    - Connection state management
    - Metrics collection
    """
    
    def __init__(
        self,
        failure_injector: Optional[VectorDBFailureInjector] = None,
        embedding_dim: int = 384,
    ):
        self.failure_injector = failure_injector or VectorDBFailureInjector()
        self.embedding_dim = embedding_dim
        
        # Document storage
        self._documents: Dict[str, VectorDocument] = {}
        self._index: Dict[str, List[Tuple[str, float]]] = {}  # chunk_id -> [(doc_id, similarity)]
        
        # Connection state
        self._connection_state = ConnectionState.ACTIVE
        self._connection_pool_size = 10
        self._active_connections = 0
        self._idle_connections = 10
        
        # Metrics
        self._search_count = 0
        self._write_count = 0
        
        logger.info(f"MockVectorStore initialized with dim={embedding_dim}")
    
    @property
    def connection_state(self) -> ConnectionState:
        return self._connection_state
    
    @property
    def metrics(self) -> ConnectionMetrics:
        return self.failure_injector.metrics
    
    def set_connection_state(self, state: ConnectionState):
        """Set the connection state."""
        self._connection_state = state
        logger.info(f"Connection state set to: {state.value}")
    
    def set_failure_mode(
        self,
        mode: FailureMode,
        message: Optional[str] = None,
        probability: float = 1.0,
    ):
        """Set the failure mode for operations."""
        self.failure_injector.set_failure_mode(mode, message, probability)
    
    def reset(self):
        """Reset the mock store to initial state."""
        self._documents.clear()
        self._index.clear()
        self._connection_state = ConnectionState.ACTIVE
        self._active_connections = 0
        self._idle_connections = self._connection_pool_size
        self._search_count = 0
        self._write_count = 0
        self.failure_injector.reset()
        logger.info("MockVectorStore reset to initial state")
    
    def _generate_embedding(self, text: str, version: str = "v1.0") -> List[float]:
        """Generate a deterministic embedding for text."""
        # Use hash-based seeding for determinism
        seed = hash(text + version) % (2**31)
        rng = random.Random(seed)
        return [rng.gauss(0, 1) for _ in range(self.embedding_dim)]
    
    def _normalize_embedding(self, embedding: List[float]) -> List[float]:
        """Normalize embedding to unit vector."""
        norm = np.linalg.norm(embedding)
        if norm == 0:
            return embedding
        return [x / norm for x in embedding]
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two embeddings."""
        a_norm = self._normalize_embedding(a)
        b_norm = self._normalize_embedding(b)
        return sum(x * y for x, y in zip(a_norm, b_norm))
    
    async def add_document(
        self,
        document_id: str,
        chunk_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        embedding_version: str = "v1.0",
    ) -> bool:
        """Add a document to the vector store."""
        self._write_count += 1
        
        # Generate embedding
        embedding = self._generate_embedding(content, embedding_version)
        
        # Create document
        doc = VectorDocument(
            document_id=document_id,
            chunk_id=chunk_id,
            content=content,
            embedding=embedding,
            metadata=metadata or {},
            embedding_version=embedding_version,
        )
        
        # Store document
        self._documents[chunk_id] = doc
        
        # Update index (simplified - in production would use proper index)
        if chunk_id not in self._index:
            self._index[chunk_id] = []
        
        logger.debug(f"Added document {document_id} chunk {chunk_id}")
        return True
    
    async def similarity_search(
        self,
        query: str,
        k: int = 10,
        embedding_version: str = "v1.0",
        include_metadata: bool = True,
    ) -> SearchResult:
        """
        Perform similarity search.
        
        Args:
            query: Query text
            k: Number of results to return
            embedding_version: Embedding model version
            include_metadata: Include document metadata in results
            
        Returns:
            SearchResult with documents and metadata
        """
        self._search_count += 1
        
        # Get query embedding
        query_embedding = self._generate_embedding(query, embedding_version)
        
        # Execute with failure handling
        result, success = await self.failure_injector._execute_with_failure_handling(
            operation="similarity_search",
            coro=self._perform_search(query_embedding, k, include_metadata),
        )
        
        if not success:
            return result or SearchResult(
                documents=[],
                search_time_ms=0,
                silent_failure=self.failure_injector._failure_mode == FailureMode.SILENT_EMPTY,
                error_message=self.failure_injector._failure_message,
            )
        
        return result
    
    async def _perform_search(
        self,
        query_embedding: List[float],
        k: int,
        include_metadata: bool,
    ) -> SearchResult:
        """Perform the actual search operation."""
        start_time = time.perf_counter()
        
        # Calculate similarities
        similarities = []
        for chunk_id, doc in self._documents.items():
            similarity = self._cosine_similarity(query_embedding, doc.embedding)
            similarities.append((chunk_id, similarity))
        
        # Sort by similarity
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        # Take top k
        top_k = similarities[:k]
        
        # Build results
        documents = []
        for chunk_id, similarity in top_k:
            doc = self._documents.get(chunk_id)
            if doc:
                result_doc = {
                    "document_id": doc.document_id,
                    "chunk_id": doc.chunk_id,
                    "content": doc.content,
                    "similarity": similarity,
                }
                if include_metadata:
                    result_doc["metadata"] = doc.metadata
                    result_doc["embedding_version"] = doc.embedding_version
                    result_doc["index_version"] = doc.index_version
                documents.append(result_doc)
        
        search_time_ms = (time.perf_counter() - start_time) * 1000
        
        return SearchResult(
            documents=documents,
            search_time_ms=search_time_ms,
            drift_score=0.0,
            neighbor_overlap_with_previous=1.0,
            is_desynced=False,
            cb_state=self.failure_injector.circuit_state,
        )
    
    async def batch_write(
        self,
        documents: List[Tuple[str, str, str]],  # (doc_id, chunk_id, content)
        metadata: Optional[List[Dict[str, Any]]] = None,
        embedding_version: str = "v1.0",
    ) -> WriteResult:
        """
        Batch write documents to the vector store.
        
        Args:
            documents: List of (document_id, chunk_id, content) tuples
            metadata: Optional list of metadata dicts
            embedding_version: Embedding model version
            
        Returns:
            WriteResult with success status and counts
        """
        self._write_count += 1
        
        # Execute with failure handling
        result, success = await self.failure_injector._execute_with_failure_handling(
            operation="batch_write",
            coro=self._perform_batch_write(documents, metadata, embedding_version),
            is_write=True,
        )
        
        if not success:
            return result or WriteResult(
                success=False,
                documents_written=0,
                documents_total=len(documents),
                error_message=self.failure_injector._failure_message,
            )
        
        return result
    
    async def _perform_batch_write(
        self,
        documents: List[Tuple[str, str, str]],
        metadata: Optional[List[Dict[str, Any]]],
        embedding_version: str,
    ) -> WriteResult:
        """Perform the actual batch write operation."""
        start_time = time.perf_counter()
        
        written = 0
        for i, (doc_id, chunk_id, content) in enumerate(documents):
            doc_metadata = metadata[i] if metadata else {}
            success = await self.add_document(
                document_id=doc_id,
                chunk_id=chunk_id,
                content=content,
                metadata=doc_metadata,
                embedding_version=embedding_version,
            )
            if success:
                written += 1
        
        latency_ms = (time.perf_counter() - start_time) * 1000
        
        return WriteResult(
            success=True,
            documents_written=written,
            documents_total=len(documents),
            latency_ms=latency_ms,
        )
    
    def get_drift_metrics(self) -> Dict[str, Any]:
        """Get current drift and silent failure metrics."""
        return self.failure_injector.get_drift_metrics()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get store statistics."""
        return {
            "document_count": len(self._documents),
            "index_size": sum(len(v) for v in self._index.values()),
            "connection_state": self._connection_state.value,
            "search_count": self._search_count,
            "write_count": self._write_count,
            "failure_metrics": self.get_drift_metrics(),
        }


# Convenience functions for creating test environments
def create_vector_db_test_environment(
    document_count: int = 100,
    failure_probability: float = 0.0,
    base_latency_ms: float = 50.0,
) -> Tuple[MockVectorStore, VectorDBFailureInjector]:
    """
    Create a test environment with mock vector store and failure injector.
    
    Returns:
        Tuple of (MockVectorStore, VectorDBFailureInjector)
    """
    failure_injector = VectorDBFailureInjector(
        base_latency_ms=base_latency_ms,
        failure_rate=failure_probability,
    )
    
    vector_store = MockVectorStore(failure_injector=failure_injector)
    
    return vector_store, failure_injector


async def create_vector_db_test_environment_async(
    document_count: int = 100,
    failure_probability: float = 0.0,
    base_latency_ms: float = 50.0,
) -> Tuple[MockVectorStore, VectorDBFailureInjector]:
    """
    Create a test environment asynchronously with mock vector store.
    
    Returns:
        Tuple of (MockVectorStore, VectorDBFailureInjector)
    """
    vector_store, failure_injector = create_vector_db_test_environment(
        document_count=document_count,
        failure_probability=failure_probability,
        base_latency_ms=base_latency_ms,
    )
    
    # Add test documents
    for i in range(document_count):
        doc_id = f"doc_{i}"
        chunk_id = f"chunk_{i}"
        content = f"Test document {i} about topic {i % 5}. " * 5
        await vector_store.add_document(doc_id, chunk_id, content)
    
    return vector_store, failure_injector


def create_resilience_test_environment(
    document_count: int = 100,
    failure_probability: float = 0.1,
    base_latency_ms: float = 50.0,
    timeout_ms: float = 5000.0,
    circuit_breaker_threshold: int = 5,
) -> Tuple[MockVectorStore, VectorDBFailureInjector]:
    """
    Create a test environment optimized for resilience testing.
    
    Includes:
    - Configurable failure injection
    - Circuit breaker simulation
    - Latency injection
    - Metrics collection
    """
    failure_injector = VectorDBFailureInjector(
        base_latency_ms=base_latency_ms,
        failure_rate=failure_probability,
        timeout_ms=timeout_ms,
        circuit_breaker_threshold=circuit_breaker_threshold,
    )
    
    vector_store = MockVectorStore(failure_injector=failure_injector)
    
    return vector_store, failure_injector


# Factory functions for specific test scenarios
def create_baseline_environment() -> Tuple[MockVectorStore, VectorDBFailureInjector]:
    """Create a baseline environment with no failures."""
    return create_vector_db_test_environment(
        document_count=100,
        failure_probability=0.0,
        base_latency_ms=20.0,
    )


def create_timeout_environment(
    timeout_ms: float = 1000.0,
) -> Tuple[MockVectorStore, VectorDBFailureInjector]:
    """Create an environment that simulates timeouts."""
    failure_injector = VectorDBFailureInjector(
        base_latency_ms=100.0,
        failure_rate=0.3,
        timeout_ms=timeout_ms,
    )
    failure_injector.set_failure_mode(FailureMode.TIMEOUT)
    return MockVectorStore(failure_injector=failure_injector), failure_injector


def create_circuit_breaker_environment(
    threshold: int = 5,
    timeout_ms: float = 5000.0,
) -> Tuple[MockVectorStore, VectorDBFailureInjector]:
    """Create an environment for circuit breaker testing."""
    failure_injector = VectorDBFailureInjector(
        base_latency_ms=50.0,
        failure_rate=1.0,  # Always fail to trigger circuit breaker
        timeout_ms=timeout_ms,
        circuit_breaker_threshold=threshold,
    )
    failure_injector.set_failure_mode(FailureMode.SERVICE_UNAVAILABLE)
    return MockVectorStore(failure_injector=failure_injector), failure_injector


def create_silent_failure_environment() -> Tuple[MockVectorStore, VectorDBFailureInjector]:
    """Create an environment that produces silent failures."""
    failure_injector = VectorDBFailureInjector(
        base_latency_ms=50.0,
        failure_rate=0.5,
    )
    failure_injector.set_failure_mode(FailureMode.SILENT_EMPTY, probability=0.3)
    return MockVectorStore(failure_injector=failure_injector), failure_injector


# Export commonly used items
__all__ = [
    "ConnectionState",
    "FailureMode",
    "CircuitBreakerState",
    "VectorDocument",
    "SearchResult",
    "WriteResult",
    "ConnectionMetrics",
    "VectorDBFailureInjector",
    "MockVectorStore",
    "VectorDBError",
    "ConnectionError",
    "ConnectionRefusedError",
    "AuthenticationError",
    "ServiceUnavailableError",
    "ResourceExhaustedError",
    "NetworkPartitionError",
    "TimeoutError",
    "QueryTimeoutError",
    "PartialWriteError",
    "VersionMismatchError",
    "create_vector_db_test_environment",
    "create_vector_db_test_environment_async",
    "create_resilience_test_environment",
    "create_baseline_environment",
    "create_timeout_environment",
    "create_circuit_breaker_environment",
    "create_silent_failure_environment",
]
