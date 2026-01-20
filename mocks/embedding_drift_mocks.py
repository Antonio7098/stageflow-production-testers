"""
Embedding Drift and Index Desync Mocks for Stageflow ENRICH Stage Testing

This module provides mock implementations for:
- Embedding models with configurable drift
- Vector stores with index desync simulation
- Document enrichment with drift detection
- Ground truth for testing retrieval quality
"""

import asyncio
import hashlib
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


class DriftType(Enum):
    """Types of embedding drift that can be simulated."""
    NONE = "none"
    TEXT_SHAPE = "text_shape"
    HIDDEN_CHARS = "hidden_chars"
    PREPROCESSING = "preprocessing"
    CHUNK_BOUNDARY = "chunk_boundary"
    MODEL_VERSION = "model_version"
    INDEX_REBUILD = "index_rebuild"
    PARTIAL_REEMBED = "partial_reembed"
    MIXED_VERSIONS = "mixed_versions"


class VectorStoreMode(Enum):
    """Mode of the mock vector store."""
    SYNCED = "synced"
    DESYNCED = "desynced"
    DRIFTING = "drifting"
    PARTIAL = "partial"


@dataclass
class DocumentMetadata:
    """Metadata for a document in the index."""
    document_id: str
    chunk_id: str
    content: str
    embedding_version: str
    preprocessing_hash: str
    text_checksum: str
    chunking_config: str
    index_version: str
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "content": self.content,
            "embedding_version": self.embedding_version,
            "preprocessing_hash": self.preprocessing_hash,
            "text_checksum": self.text_checksum,
            "chunking_config": self.chunking_config,
            "index_version": self.index_version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class EmbeddingResult:
    """Result of embedding generation."""
    vector: list[float]
    model_version: str
    preprocessing_hash: str
    text_checksum: str
    drift_detected: bool = False
    drift_type: DriftType = DriftType.NONE
    drift_magnitude: float = 0.0
    generation_time_ms: float = 0.0


@dataclass
class RetrievalResult:
    """Result of similarity search."""
    documents: list[dict]
    query_embedding: list[float]
    search_time_ms: float
    neighbor_overlap_with_previous: float = 1.0
    drift_score: float = 0.0
    index_version: str = ""
    is_desynced: bool = False
    silent_failure: bool = False
    failure_reason: Optional[str] = None


class MockEmbeddingModel:
    """
    Mock embedding model with configurable drift simulation.
    
    This model can simulate various drift scenarios:
    - Text shape differences (whitespace, markdown)
    - Hidden characters (OCR noise, HTML)
    - Non-deterministic preprocessing
    - Chunk boundary changes
    - Model version updates
    """

    def __init__(
        self,
        model_version: str = "v1.0",
        embedding_dim: int = 384,
        base_seed: int = 42,
        enable_drift: bool = False,
        drift_probability: float = 0.1,
    ):
        self.model_version = model_version
        self.embedding_dim = embedding_dim
        self.base_seed = base_seed
        self.enable_drift = enable_drift
        self.drift_probability = drift_probability
        self.call_count = 0
        self.drift_events = []
        self._text_hash_cache = {}

    def _compute_embedding(self, text: str, seed: int) -> list[float]:
        """Generate deterministic embedding from text."""
        np.random.seed(seed + hash(text) % (2**31))
        # Generate embedding with some structure based on text content
        base = np.random.randn(self.embedding_dim).astype(np.float32)
        
        # Add content-based variation
        content_hash = hashlib.md5(text.encode()).hexdigest()
        np.random.seed(int(content_hash[:8], 16))
        content_mod = np.random.randn(self.embedding_dim).astype(np.float32) * 0.1
        
        # Add position-based variation for chunk boundary simulation
        pos_hash = hashlib.md5(f"{text[:100]}".encode()).hexdigest()
        np.random.seed(int(pos_hash[:8], 16))
        pos_mod = np.random.randn(self.embedding_dim).astype(np.float32) * 0.05
        
        return ((base + content_mod + pos_mod) / 3).tolist()

    def _apply_drift(self, text: str, embedding: list[float]) -> tuple[str, list[float], DriftType, float]:
        """Apply drift transformation to text and embedding."""
        if not self.enable_drift or random.random() > self.drift_probability:
            return text, embedding, DriftType.NONE, 0.0

        drift_type = random.choice([
            DriftType.TEXT_SHAPE,
            DriftType.HIDDEN_CHARS,
            DriftType.PREPROCESSING,
            DriftType.CHUNK_BOUNDARY,
        ])

        original_embedding = embedding.copy()
        drifted_text = text
        magnitude = 0.0

        if drift_type == DriftType.TEXT_SHAPE:
            # Add whitespace variations, markdown remnants
            variations = [
                text.replace(" ", "  "),  # Double spaces
                text.replace("\n", "\n\n"),  # Double newlines
                text.replace("#", " #"),  # Space before hash
                text.replace("**", " ** "),  # Space around bold
            ]
            drifted_text = random.choice(variations)
            magnitude = 0.02 + random.random() * 0.03

        elif drift_type == DriftType.HIDDEN_CHARS:
            # Add non-breaking spaces, zero-width characters
            hidden_chars = [
                "\u00A0",  # Non-breaking space
                "\u200B",  # Zero-width space
                "\u200C",  # Zero-width non-joiner
                "\uFEFF",  # BOM
            ]
            for _ in range(random.randint(1, 3)):
                pos = random.randint(0, len(drifted_text))
                drifted_text = drifted_text[:pos] + random.choice(hidden_chars) + drifted_text[pos:]
            magnitude = 0.015 + random.random() * 0.025

        elif drift_type == DriftType.PREPROCESSING:
            # Simulate preprocessing differences
            variations = [
                text.lower(),  # Different case
                text.strip(),  # Stripped whitespace
                " ".join(text.split()),  # Normalized whitespace
            ]
            drifted_text = random.choice(variations)
            magnitude = 0.03 + random.random() * 0.04

        elif drift_type == DriftType.CHUNK_BOUNDARY:
            # Add context from before/after
            prefix = "Previous context: " + " ".join(text.split()[:5])
            suffix = " ".join(text.split()[-5:])
            drifted_text = f"{prefix} {text} {suffix}"
            magnitude = 0.04 + random.random() * 0.06

        # Apply magnitude to embedding
        np.random.seed(int(time.time() * 1000) % (2**31))
        drift_noise = np.random.randn(self.embedding_dim).astype(np.float32) * magnitude
        drifted_embedding = (np.array(embedding) + drift_noise).tolist()

        self.drift_events.append({
            "timestamp": datetime.now().isoformat(),
            "drift_type": drift_type.value,
            "magnitude": magnitude,
            "original_length": len(text),
            "drifted_length": len(drifted_text),
        })

        return drifted_text, drifted_embedding, drift_type, magnitude

    async def embed_text(self, text: str, apply_drift: bool = False) -> EmbeddingResult:
        """Generate embedding for text with optional drift."""
        start_time = time.perf_counter()
        self.call_count += 1

        # Compute base embedding
        seed = self.base_seed + self.call_count
        embedding = self._compute_embedding(text, seed)

        # Apply drift if requested
        drift_type = DriftType.NONE
        drift_magnitude = 0.0
        drifted_text = text

        if apply_drift and self.enable_drift:
            drifted_text, embedding, drift_type, drift_magnitude = self._apply_drift(text, embedding)

        # Compute checksums
        preprocessing_hash = hashlib.md5(drifted_text.encode()).hexdigest()
        text_checksum = hashlib.md5(text.encode()).hexdigest()

        generation_time_ms = (time.perf_counter() - start_time) * 1000

        return EmbeddingResult(
            vector=embedding,
            model_version=self.model_version,
            preprocessing_hash=preprocessing_hash,
            text_checksum=text_checksum,
            drift_detected=drift_type != DriftType.NONE,
            drift_type=drift_type,
            drift_magnitude=drift_magnitude,
            generation_time_ms=generation_time_ms,
        )

    async def embed_batch(self, texts: list[str], apply_drift: bool = False) -> list[EmbeddingResult]:
        """Generate embeddings for batch of texts."""
        results = []
        for text in texts:
            result = await self.embed_text(text, apply_drift)
            results.append(result)
        return results

    def reset(self):
        """Reset model state."""
        self.call_count = 0
        self.drift_events = []
        self._text_hash_cache = {}


class MockVectorStore:
    """
    Mock vector store with index desync simulation.
    
    Capabilities:
    - Simulate synced, desynced, drifting, and partial indices
    - Track index version and embedding version
    - Report neighbor overlap and drift metrics
    - Simulate silent failures
    """

    def __init__(
        self,
        embedding_model: MockEmbeddingModel,
        mode: VectorStoreMode = VectorStoreMode.SYNCED,
        index_version: str = "v1",
        desync_severity: float = 0.1,
        silent_failure_rate: float = 0.0,
    ):
        self.embedding_model = embedding_model
        self.mode = mode
        self.index_version = index_version
        self.desync_severity = desync_severity
        self.silent_failure_rate = silent_failure_rate
        
        # Index data
        self.documents: dict[str, DocumentMetadata] = {}
        self.embeddings: dict[str, list[float]] = {}
        self._previous_query_results: dict[str, list[str]] = {}
        
        # Metrics
        self.search_count = 0
        self.silent_failures = 0
        self.drift_detected_count = 0

    def add_document(
        self,
        document_id: str,
        chunk_id: str,
        content: str,
        embedding_version: Optional[str] = None,
        index_version: Optional[str] = None,
    ):
        """Add document to the index."""
        if embedding_version is None:
            embedding_version = self.embedding_model.model_version
        if index_version is None:
            index_version = self.index_version

        preprocessing_hash = hashlib.md5(content.encode()).hexdigest()
        text_checksum = hashlib.md5(content.encode()).hexdigest()

        metadata = DocumentMetadata(
            document_id=document_id,
            chunk_id=chunk_id,
            content=content,
            embedding_version=embedding_version,
            preprocessing_hash=preprocessing_hash,
            text_checksum=text_checksum,
            chunking_config="default",
            index_version=index_version,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        self.documents[chunk_id] = metadata

        # Generate embedding (sync version for setup)
        embedding = self.embedding_model._compute_embedding(content, len(self.documents))
        self.embeddings[chunk_id] = embedding

    async def add_document_async(
        self,
        document_id: str,
        chunk_id: str,
        content: str,
        embedding_version: Optional[str] = None,
        index_version: Optional[str] = None,
    ):
        """Add document to the index asynchronously."""
        if embedding_version is None:
            embedding_version = self.embedding_model.model_version
        if index_version is None:
            index_version = self.index_version

        preprocessing_hash = hashlib.md5(content.encode()).hexdigest()
        text_checksum = hashlib.md5(content.encode()).hexdigest()

        metadata = DocumentMetadata(
            document_id=document_id,
            chunk_id=chunk_id,
            content=content,
            embedding_version=embedding_version,
            preprocessing_hash=preprocessing_hash,
            text_checksum=text_checksum,
            chunking_config="default",
            index_version=index_version,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        self.documents[chunk_id] = metadata

        # Generate embedding asynchronously
        embedding_result = await self.embedding_model.embed_text(content)
        self.embeddings[chunk_id] = embedding_result.vector

    async def similarity_search(
        self,
        query: str,
        k: int = 5,
        include_metadata: bool = True,
    ) -> RetrievalResult:
        """
        Perform similarity search with configurable failure modes.
        
        This method simulates various retrieval scenarios:
        - Normal retrieval (synced index)
        - Retrieval with desync (embeddings don't match documents)
        - Retrieval with drift (gradually degrading results)
        - Partial retrieval (some documents missing)
        - Silent failures (empty results without error)
        """
        self.search_count += 1
        start_time = time.perf_counter()

        # Check for silent failure
        if random.random() < self.silent_failure_rate:
            self.silent_failures += 1
            return RetrievalResult(
                documents=[],
                query_embedding=[],
                search_time_ms=(time.perf_counter() - start_time) * 1000,
                silent_failure=True,
                failure_reason="Simulated silent failure",
            )

        # Generate query embedding
        query_embedding_result = await self.embedding_model.embed_text(query)
        query_embedding = query_embedding_result.vector

        # Calculate similarities
        query_vec = np.array(query_embedding)
        similarities = {}
        for chunk_id, doc_embedding in self.embeddings.items():
            doc_vec = np.array(doc_embedding)
            # Cosine similarity
            sim = np.dot(query_vec, doc_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(doc_vec) + 1e-8)
            similarities[chunk_id] = float(sim)

        # Sort by similarity
        sorted_docs = sorted(similarities.items(), key=lambda x: x[1], reverse=True)
        top_k = sorted_docs[:k]

        # Apply mode-specific modifications
        neighbor_overlap = 1.0
        drift_score = 0.0
        is_desynced = False
        failure_reason = None

        if self.mode == VectorStoreMode.DESYNCED:
            # Introduce desync: swap some embeddings or return wrong documents
            is_desynced = True
            drift_score = self.desync_severity
            neighbor_overlap = 1.0 - self.desync_severity
            
            # Randomly swap some results with lower-ranked documents
            if len(top_k) > 2 and random.random() < self.desync_severity:
                swap_idx = random.randint(1, len(top_k) - 1)
                top_k[0], top_k[swap_idx] = top_k[swap_idx], top_k[0]
                failure_reason = "Embedding desync: results swapped"

        elif self.mode == VectorStoreMode.DRIFTING:
            # Gradually degrade retrieval quality
            degradation_factor = min(1.0, self.search_count * 0.01)
            drift_score = degradation_factor * 0.1
            neighbor_overlap = 1.0 - (degradation_factor * 0.1)
            
            # Reduce similarity scores for correct documents
            for i, (chunk_id, sim) in enumerate(top_k):
                top_k[i] = (chunk_id, sim * (1 - degradation_factor * 0.1))

        elif self.mode == VectorStoreMode.PARTIAL:
            # Return fewer results than requested
            actual_k = max(1, k - random.randint(1, k - 1))
            top_k = top_k[:actual_k]
            neighbor_overlap = actual_k / k
            failure_reason = f"Partial result: requested {k}, got {actual_k}"

        # Build result documents
        documents = []
        for chunk_id, similarity in top_k:
            if chunk_id in self.documents:
                doc = self.documents[chunk_id]
                doc_data = {
                    "chunk_id": chunk_id,
                    "document_id": doc.document_id,
                    "content": doc.content,
                    "similarity": similarity,
                    "embedding_version": doc.embedding_version,
                    "index_version": doc.index_version,
                }
                if include_metadata:
                    doc_data["metadata"] = doc.to_dict()
                documents.append(doc_data)

        # Track for neighbor overlap calculation
        query_key = hash(query) % (2**31)
        self._previous_query_results[query_key] = [d["chunk_id"] for d in documents]

        search_time_ms = (time.perf_counter() - start_time) * 1000

        if drift_score > 0.05:
            self.drift_detected_count += 1

        return RetrievalResult(
            documents=documents,
            query_embedding=query_embedding,
            search_time_ms=search_time_ms,
            neighbor_overlap_with_previous=neighbor_overlap,
            drift_score=drift_score,
            index_version=self.index_version,
            is_desynced=is_desynced,
            silent_failure=False,
            failure_reason=failure_reason,
        )

    def get_index_stats(self) -> dict:
        """Get statistics about the index."""
        embeddings_by_version = {}
        for doc in self.documents.values():
            version = doc.embedding_version
            if version not in embeddings_by_version:
                embeddings_by_version[version] = 0
            embeddings_by_version[version] += 1

        return {
            "total_documents": len(self.documents),
            "total_embeddings": len(self.embeddings),
            "embeddings_by_version": embeddings_by_version,
            "mode": self.mode.value,
            "index_version": self.index_version,
            "search_count": self.search_count,
            "silent_failures": self.silent_failures,
            "drift_detected_count": self.drift_detected_count,
        }

    def set_mode(self, mode: VectorStoreMode, severity: float = 0.1):
        """Change the vector store mode."""
        self.mode = mode
        self.desync_severity = severity

    def reset(self):
        """Reset vector store state."""
        self.documents.clear()
        self.embeddings.clear()
        self._previous_query_results.clear()
        self.search_count = 0
        self.silent_failures = 0
        self.drift_detected_count = 0
        self.embedding_model.reset()


class EmbeddingDriftDetector:
    """
    Detector for embedding drift in retrieval results.
    
    This class provides methods to detect:
    - Embedding distribution drift
    - Nearest-neighbor stability issues
    - Vector norm variance
    - Index recall degradation
    """

    def __init__(self, threshold_js: float = 0.05, threshold_overlap: float = 0.75):
        self.threshold_js = threshold_js
        self.threshold_overlap = threshold_overlap
        self.baseline_embeddings: Optional[np.ndarray] = None
        self.baseline_query_pack: list[str] = []

    def set_baseline(self, embeddings: list[list[float]]):
        """Set baseline embedding distribution."""
        self.baseline_embeddings = np.array(embeddings, dtype=np.float32)

    def set_query_pack(self, queries: list[str]):
        """Set baseline query pack for stability testing."""
        self.baseline_query_pack = queries

    def compute_js_divergence(
        self,
        current_embeddings: list[list[float]],
        baseline_embeddings: Optional[np.ndarray] = None,
    ) -> float:
        """
        Compute Jensen-Shannon divergence between embedding distributions.
        
        Returns:
            JS divergence (0 = same, higher = more drift)
        """
        if baseline_embeddings is None:
            baseline_embeddings = self.baseline_embeddings
        
        if baseline_embeddings is None or len(current_embeddings) == 0:
            return 0.0

        current_arr = np.array(current_embeddings, dtype=np.float32)
        
        # Use MiniBatchKMeans for clustering
        n_clusters = min(24, len(baseline_embeddings))
        if n_clusters < 2:
            return 0.0

        try:
            from sklearn.cluster import MiniBatchKMeans
            from scipy.spatial.distance import jensenshannon

            kmeans = MiniBatchKMeans(n_clusters=n_clusters, random_state=42)
            baseline_clusters = kmeans.fit_predict(baseline_embeddings)
            current_clusters = kmeans.predict(current_arr)

            # Create histograms
            baseline_hist, _ = np.histogram(
                baseline_clusters, 
                bins=np.arange(n_clusters + 1), 
                density=True
            )
            current_hist, _ = np.histogram(
                current_clusters,
                bins=np.arange(n_clusters + 1),
                density=True
            )

            # Compute JS divergence
            js_div = jensenshannon(baseline_hist, current_hist) ** 2
            return float(js_div)

        except ImportError:
            # Fallback without sklearn
            return 0.0

    def compute_nn_overlap(
        self,
        old_neighbors: list[list[str]],
        new_neighbors: list[list[str]],
        k: int = 10,
    ) -> float:
        """
        Compute nearest-neighbor overlap between old and new results.
        
        Returns:
            Mean overlap fraction (1.0 = identical, 0.0 = completely different)
        """
        if not old_neighbors or not new_neighbors:
            return 1.0

        overlaps = []
        for old, new in zip(old_neighbors, new_neighbors):
            if len(old) == 0 or len(new) == 0:
                overlaps.append(0.0)
                continue
            old_set = set(old[:k])
            new_set = set(new[:k])
            overlap = len(old_set & new_set) / len(old_set | new_set)
            overlaps.append(overlap)

        return float(np.mean(overlays)) if overlaps else 1.0

    def compute_norm_variance(self, embeddings: list[list[float]]) -> float:
        """
        Compute variance in embedding norms.
        
        High variance indicates different preprocessing/model versions.
        """
        if not embeddings:
            return 0.0

        norms = [np.linalg.norm(e) for e in embeddings]
        return float(np.var(norms))

    def detect_drift(
        self,
        current_embeddings: list[list[float]],
        old_neighbors: Optional[list[list[str]]] = None,
        new_neighbors: Optional[list[list[str]]] = None,
    ) -> dict:
        """
        Run comprehensive drift detection.
        
        Returns:
            Drift detection report with metrics and recommendations.
        """
        js_div = self.compute_js_divergence(current_embeddings)
        norm_var = self.compute_norm_variance(current_embeddings)
        
        overlap = 1.0
        if old_neighbors is not None and new_neighbors is not None:
            overlap = self.compute_nn_overlap(old_neighbors, new_neighbors)

        drift_detected = (
            js_div > self.threshold_js or
            overlap < self.threshold_overlap or
            norm_var > 0.1
        )

        recommendations = []
        if js_div > self.threshold_js:
            recommendations.append("Embedding distribution has shifted significantly")
            recommendations.append("Consider re-embedding entire corpus with new model")
        if overlap < self.threshold_overlap:
            recommendations.append(f"NN overlap ({overlap:.2f}) below threshold ({self.threshold_overlap})")
            recommendations.append("Check for chunk boundary changes or preprocessing drift")
        if norm_var > 0.1:
            recommendations.append("High variance in embedding norms detected")
            recommendations.append("Verify preprocessing is deterministic across runs")

        return {
            "drift_detected": drift_detected,
            "js_divergence": js_div,
            "nn_overlap": overlap,
            "norm_variance": norm_var,
            "thresholds": {
                "js_divergence": self.threshold_js,
                "nn_overlap": self.threshold_overlap,
            },
            "recommendations": recommendations,
            "timestamp": datetime.now().isoformat(),
        }


# Factory functions for common mock configurations

def create_drift_injector(
    model_version: str = "v1.0",
    drift_probability: float = 0.2,
) -> tuple[MockEmbeddingModel, MockVectorStore, EmbeddingDriftDetector]:
    """
    Create a complete drift injection test environment.
    
    Returns:
        Tuple of (embedding_model, vector_store, drift_detector)
    """
    embedding_model = MockEmbeddingModel(
        model_version=model_version,
        enable_drift=True,
        drift_probability=drift_probability,
    )
    
    vector_store = MockVectorStore(embedding_model)
    
    detector = EmbeddingDriftDetector()
    
    return embedding_model, vector_store, detector


def create_synced_test_environment(
    document_count: int = 100,
    embedding_dim: int = 384,
) -> tuple[MockEmbeddingModel, MockVectorStore, EmbeddingDriftDetector]:
    """
    Create a synced (normal) test environment with documents.
    """
    embedding_model = MockEmbeddingModel(embedding_dim=embedding_dim)
    vector_store = MockVectorStore(embedding_model)
    detector = EmbeddingDriftDetector()

    # Add test documents (sync version)
    for i in range(document_count):
        doc_id = f"doc_{i}"
        chunk_id = f"chunk_{i}"
        content = f"Test document {i} with some content about topic {i % 5}. " * 3
        vector_store.add_document(doc_id, chunk_id, content)

    return embedding_model, vector_store, detector


async def create_synced_test_environment_async(
    document_count: int = 100,
    embedding_dim: int = 384,
) -> tuple[MockEmbeddingModel, MockVectorStore, EmbeddingDriftDetector]:
    """
    Create a synced (normal) test environment with documents (async version).
    """
    embedding_model = MockEmbeddingModel(embedding_dim=embedding_dim)
    vector_store = MockVectorStore(embedding_model)
    detector = EmbeddingDriftDetector()

    # Add test documents (async version)
    for i in range(document_count):
        doc_id = f"doc_{i}"
        chunk_id = f"chunk_{i}"
        content = f"Test document {i} with some content about topic {i % 5}. " * 3
        await vector_store.add_document_async(doc_id, chunk_id, content)

    return embedding_model, vector_store, detector


def create_drift_test_environment(
    document_count: int = 100,
    drift_document_ratio: float = 0.3,
    embedding_dim: int = 384,
) -> tuple[MockEmbeddingModel, MockVectorStore, EmbeddingDriftDetector]:
    """
    Create a test environment with embedded drift.
    """
    embedding_model = MockEmbeddingModel(
        embedding_dim=embedding_dim,
        enable_drift=True,
        drift_probability=drift_document_ratio,
    )
    vector_store = MockVectorStore(embedding_model)
    detector = EmbeddingDriftDetector()

    # Add documents - some with drift, some without (sync version)
    for i in range(document_count):
        doc_id = f"doc_{i}"
        chunk_id = f"chunk_{i}"
        content = f"Test document {i} with some content about topic {i % 5}. " * 3
        
        # Apply drift to some documents
        if i < int(document_count * drift_document_ratio):
            # Add some text that might cause drift
            content_with_drift = f"\u00A0{content}\u200B"  # Add hidden characters
            vector_store.add_document(doc_id, chunk_id, content_with_drift)
        else:
            vector_store.add_document(doc_id, chunk_id, content)

    return embedding_model, vector_store, detector


async def create_drift_test_environment_async(
    document_count: int = 100,
    drift_document_ratio: float = 0.3,
    embedding_dim: int = 384,
) -> tuple[MockEmbeddingModel, MockVectorStore, EmbeddingDriftDetector]:
    """
    Create a test environment with embedded drift (async version).
    """
    embedding_model = MockEmbeddingModel(
        embedding_dim=embedding_dim,
        enable_drift=True,
        drift_probability=drift_document_ratio,
    )
    vector_store = MockVectorStore(embedding_model)
    detector = EmbeddingDriftDetector()

    # Add documents - some with drift, some without (async version)
    for i in range(document_count):
        doc_id = f"doc_{i}"
        chunk_id = f"chunk_{i}"
        content = f"Test document {i} with some content about topic {i % 5}. " * 3
        
        # Apply drift to some documents
        if i < int(document_count * drift_document_ratio):
            # Add some text that might cause drift
            content_with_drift = f"\u00A0{content}\u200B"  # Add hidden characters
            await vector_store.add_document_async(doc_id, chunk_id, content_with_drift)
        else:
            await vector_store.add_document_async(doc_id, chunk_id, content)

    return embedding_model, vector_store, detector
