"""
Mock Data Generator for Chunk Overlap and Deduplication Testing

This module provides mock data generators for testing Stageflow ENRICH stages
that handle document chunking with overlap and deduplication.
"""

import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from difflib import SequenceMatcher

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """Represents a single document chunk."""
    chunk_id: str
    document_id: str
    content: str
    start_position: int
    end_position: int
    chunk_index: int
    total_chunks: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    overlap_with_previous: bool = False
    overlap_with_next: bool = False


@dataclass
class Document:
    """Represents a test document for chunking."""
    document_id: str
    title: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChunkingConfig:
    """Configuration for chunking behavior."""
    chunk_size_tokens: int = 512
    chunk_overlap_percent: float = 0.20
    min_chunk_size_tokens: int = 100
    overlap_strategy: str = "fixed"  # "fixed" or "semantic"
    dedup_threshold: float = 0.85
    dedup_strategy: str = "exact"  # "exact", "fuzzy", "semantic"


class SimpleTokenizer:
    """Simple token counter for testing (approximates tokenization)."""

    def __init__(self, tokens_per_word: float = 0.75):
        self.tokens_per_word = tokens_per_word

    def count_tokens(self, text: str) -> int:
        """Count approximate tokens in text."""
        words = len(text.split())
        return int(words / self.tokens_per_word)

    def split_by_tokens(self, text: str, max_tokens: int) -> List[str]:
        """Split text into chunks of approximately max_tokens."""
        words = text.split()
        tokens_per_word = self.tokens_per_word
        approx_words_per_chunk = int(max_tokens * tokens_per_word)

        chunks = []
        current_chunk = []

        for word in words:
            current_chunk.append(word)
            if len(current_chunk) >= approx_words_per_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = []

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks


class SemanticChunker:
    """Semantic-aware chunker that respects sentence/paragraph boundaries."""

    def __init__(self, tokenizer: SimpleTokenizer):
        self.tokenizer = tokenizer

    def split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        sentence_pattern = r'[.!?]+'
        sentences = re.split(sentence_pattern, text)
        return [s.strip() for s in sentences if s.strip()]

    def chunk(
        self,
        text: str,
        chunk_size_tokens: int,
        overlap_percent: float,
        min_chunk_size_tokens: int,
    ) -> List[Chunk]:
        """Create semantic chunks with overlap."""
        sentences = self.split_into_sentences(text)
        chunks = []
        current_chunk_sentences = []
        current_tokens = 0
        chunk_index = 0

        for sentence in sentences:
            sentence_tokens = self.tokenizer.count_tokens(sentence)

            if current_tokens + sentence_tokens > chunk_size_tokens:
                if current_tokens >= min_chunk_size_tokens:
                    chunk_content = " ".join(current_chunk_sentences)
                    chunks.append(self._create_chunk(
                        chunk_content, chunk_index, len(chunks), text
                    ))
                    chunk_index += 1

                current_chunk_sentences = [sentence]
                current_tokens = sentence_tokens
            else:
                current_chunk_sentences.append(sentence)
                current_tokens += sentence_tokens

        if current_chunk_sentences:
            chunk_content = " ".join(current_chunk_sentences)
            chunks.append(self._create_chunk(
                chunk_content, chunk_index, len(chunks), text
            ))

        return self._add_overlap(chunks, overlap_percent, text)

    def _create_chunk(
        self,
        content: str,
        chunk_index: int,
        total_chunks_estimate: int,
        full_text: str,
    ) -> Chunk:
        """Create a chunk object."""
        start_pos = full_text.find(content) if content in full_text else 0
        return Chunk(
            chunk_id=f"chunk_{chunk_index}",
            document_id="doc_0",
            content=content,
            start_position=start_pos,
            end_position=start_pos + len(content),
            chunk_index=chunk_index,
            total_chunks=total_chunks_estimate,
        )

    def _add_overlap(
        self,
        chunks: List[Chunk],
        overlap_percent: float,
        full_text: str,
    ) -> List[Chunk]:
        """Add overlap regions to chunks."""
        if not chunks:
            return chunks

        overlap_size = max(1, int(len(chunks) * overlap_percent))
        if overlap_size == 0:
            return chunks

        for i in range(len(chunks)):
            if i > 0:
                chunks[i].overlap_with_previous = True
            if i < len(chunks) - 1:
                chunks[i].overlap_with_next = True

        return chunks


class FixedSizeChunker:
    """Fixed-size chunker for baseline testing."""

    def __init__(self, tokenizer: SimpleTokenizer):
        self.tokenizer = tokenizer

    def chunk(
        self,
        text: str,
        chunk_size_tokens: int,
        overlap_percent: float,
        min_chunk_size_tokens: int,
    ) -> List[Chunk]:
        """Create fixed-size chunks with overlap."""
        words = text.split()
        tokens_per_word = self.tokenizer.tokens_per_word
        words_per_chunk = int(chunk_size_tokens * tokens_per_word)
        overlap_words = int(words_per_chunk * overlap_percent)

        if overlap_words >= words_per_chunk:
            overlap_words = words_per_chunk // 2

        chunks = []
        chunk_index = 0
        position = 0

        while position < len(words):
            chunk_end = min(position + words_per_chunk, len(words))
            chunk_words = words[position:chunk_end]
            chunk_content = " ".join(chunk_words)

            chunks.append(Chunk(
                chunk_id=f"chunk_{chunk_index}",
                document_id="doc_0",
                content=chunk_content,
                start_position=position,
                end_position=chunk_end,
                chunk_index=chunk_index,
                total_chunks=-1,
                metadata={"word_count": len(chunk_words)},
            ))

            chunk_index += 1
            position = chunk_end

            if overlap_words > 0 and position < len(words):
                position = max(position, position - overlap_words)
                if position >= chunk_end:
                    position = chunk_end - 1

        for i, chunk in enumerate(chunks):
            chunk.total_chunks = len(chunks)
            if i > 0:
                chunk.overlap_with_previous = True
            if i < len(chunks) - 1:
                chunk.overlap_with_next = True

        return chunks


class Deduplicator:
    """Deduplication utility for chunk processing."""

    def __init__(self, config: ChunkingConfig):
        self.config = config

    def deduplicate(self, chunks: List[Chunk]) -> Tuple[List[Chunk], Dict[str, Any]]:
        """Remove duplicate or near-duplicate chunks."""
        if self.config.dedup_strategy == "exact":
            return self._exact_deduplicate(chunks)
        elif self.config.dedup_strategy == "fuzzy":
            return self._fuzzy_deduplicate(chunks)
        else:
            return chunks, {"strategy": "none", "removed": 0}

    def _exact_deduplicate(self, chunks: List[Chunk]) -> Tuple[List[Chunk], Dict[str, Any]]:
        """Remove exact duplicate chunks."""
        seen_content = set()
        unique_chunks = []
        removed_count = 0

        for chunk in chunks:
            content_hash = hashlib.md5(chunk.content.encode()).hexdigest()
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                unique_chunks.append(chunk)
            else:
                removed_count += 1

        return unique_chunks, {
            "strategy": "exact",
            "removed": removed_count,
            "original_count": len(chunks),
            "final_count": len(unique_chunks),
        }

    def _fuzzy_deduplicate(self, chunks: List[Chunk]) -> Tuple[List[Chunk], Dict[str, Any]]:
        """Remove chunks with similarity above threshold."""
        if not chunks:
            return chunks, {"strategy": "fuzzy", "removed": 0}

        unique_chunks = []
        removed_count = 0
        threshold = self.config.dedup_threshold

        for chunk in chunks:
            is_duplicate = False
            for unique_chunk in unique_chunks:
                similarity = SequenceMatcher(
                    None, chunk.content, unique_chunk.content
                ).ratio()
                if similarity >= threshold:
                    is_duplicate = True
                    removed_count += 1
                    break

            if not is_duplicate:
                unique_chunks.append(chunk)

        return unique_chunks, {
            "strategy": "fuzzy",
            "threshold": threshold,
            "removed": removed_count,
            "original_count": len(chunks),
            "final_count": len(unique_chunks),
        }


class ChunkOverlapDeduplicationMocks:
    """Main mock class for chunk overlap and deduplication testing."""

    def __init__(self, config: Optional[ChunkingConfig] = None):
        self.config = config or ChunkingConfig()
        self.tokenizer = SimpleTokenizer()
        self.fixed_chunker = FixedSizeChunker(self.tokenizer)
        self.semantic_chunker = SemanticChunker(self.tokenizer)
        self.deduplicator = Deduplicator(self.config)

    def create_test_document(
        self,
        doc_id: str = "doc_test",
        content_type: str = "normal",
    ) -> Document:
        """Create a test document with specific characteristics."""
        if content_type == "normal":
            content = self._generate_normal_content()
        elif content_type == "repetitive":
            content = self._generate_repetitive_content()
        elif content_type == "technical":
            content = self._generate_technical_content()
        else:
            content = self._generate_normal_content()

        return Document(
            document_id=doc_id,
            title=f"Test Document {doc_id}",
            content=content,
            metadata={"content_type": content_type},
        )

    def _generate_normal_content(self) -> str:
        """Generate normal prose content for testing."""
        sentences = [
            "The quick brown fox jumps over the lazy dog.",
            "Machine learning enables computers to learn from data without explicit programming.",
            "Natural language processing helps machines understand human language.",
            "Vector databases store and retrieve high-dimensional data efficiently.",
            "Retrieval augmented generation combines search with language model generation.",
            "Chunking is essential for breaking down large documents into manageable pieces.",
            "Overlap ensures that context is not lost at chunk boundaries.",
            "Deduplication removes redundant information from search results.",
            "The optimal chunk size depends on the specific use case and data characteristics.",
            "Semantic chunking preserves meaning by splitting at logical boundaries.",
        ]
        return " ".join(sentences * 3)

    def _generate_repetitive_content(self) -> str:
        """Generate content with intentional repetitions for dedupe testing."""
        base_sentences = [
            "This is a repeated sentence for testing deduplication.",
            "Machine learning enables computers to learn from data.",
            "The same information appears multiple times in this document.",
        ]
        content = []
        for i in range(20):
            content.append(f"Document section {i}: " + " ".join(base_sentences))
        return " ".join(content)

    def _generate_technical_content(self) -> str:
        """Generate technical content with code blocks for testing."""
        code_snippet = """
        def process_data(input_data):
            # This is a code comment
            result = []
            for item in input_data:
                processed = item * 2
                result.append(processed)
            return result
        """
        prose_parts = [
            "The function above demonstrates data processing logic.",
            "It takes input data and transforms each element.",
            "The result is a list of processed items.",
        ]
        return code_snippet + " ".join(prose_parts * 5)

    def create_chunked_document(
        self,
        document: Document,
        chunk_size_tokens: Optional[int] = None,
        overlap_percent: Optional[float] = None,
        use_semantic: bool = False,
    ) -> Dict[str, Any]:
        """Create a chunked document from a source document."""
        chunk_size = chunk_size_tokens or self.config.chunk_size_tokens
        overlap = overlap_percent or self.config.chunk_overlap_percent
        min_size = self.config.min_chunk_size_tokens

        if use_semantic:
            chunks = self.semantic_chunker.chunk(
                document.content, chunk_size, overlap, min_size
            )
        else:
            chunks = self.fixed_chunker.chunk(
                document.content, chunk_size, overlap, min_size
            )

        for i, chunk in enumerate(chunks):
            chunk.document_id = document.document_id
            chunk.chunk_id = f"{document.document_id}_chunk_{i}"

        deduped_chunks, dedup_info = self.deduplicator.deduplicate(chunks)

        return {
            "document_id": document.document_id,
            "title": document.title,
            "original_content_length": len(document.content),
            "original_token_count": self.tokenizer.count_tokens(document.content),
            "chunk_count": len(chunks),
            "dedup_info": dedup_info,
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "content": c.content,
                    "token_count": self.tokenizer.count_tokens(c.content),
                    "start_position": c.start_position,
                    "end_position": c.end_position,
                    "chunk_index": c.chunk_index,
                    "overlap_with_previous": c.overlap_with_previous,
                    "overlap_with_next": c.overlap_with_next,
                }
                for c in deduped_chunks
            ],
            "config": {
                "chunk_size_tokens": chunk_size,
                "overlap_percent": overlap,
                "min_chunk_size_tokens": min_size,
                "use_semantic": use_semantic,
            },
        }

    def create_batch_test_documents(
        self, count: int = 10
    ) -> List[Document]:
        """Create a batch of test documents."""
        documents = []
        for i in range(count):
            content_type = ["normal", "repetitive", "technical"][i % 3]
            doc = self.create_test_document(
                doc_id=f"batch_doc_{i}",
                content_type=content_type,
            )
            documents.append(doc)
        return documents

    def create_vector_store_with_chunks(
        self,
        documents: List[Document],
        chunk_size_tokens: int = 512,
        overlap_percent: float = 0.20,
    ) -> Dict[str, Any]:
        """Create a simulated vector store with chunked documents."""
        all_chunks = []

        for doc in documents:
            chunked = self.create_chunked_document(
                doc,
                chunk_size_tokens=chunk_size_tokens,
                overlap_percent=overlap_percent,
            )
            all_chunks.extend(chunked["chunks"])

        return {
            "document_count": len(documents),
            "total_chunks": len(all_chunks),
            "chunks": all_chunks,
            "config": {
                "chunk_size_tokens": chunk_size_tokens,
                "overlap_percent": overlap_percent,
            },
        }


def create_mock_chunk_environment(
    document_count: int = 50,
    chunk_size_tokens: int = 512,
    overlap_percent: float = 0.20,
) -> Dict[str, Any]:
    """Create a complete mock environment for chunk testing."""
    mocks = ChunkOverlapDeduplicationMocks()
    documents = mocks.create_batch_test_documents(document_count)
    vector_store = mocks.create_vector_store_with_chunks(
        documents, chunk_size_tokens, overlap_percent
    )
    return {
        "documents": [
            {"id": d.document_id, "title": d.title}
            for d in documents
        ],
        "vector_store": vector_store,
        "config": {
            "chunk_size_tokens": chunk_size_tokens,
            "overlap_percent": overlap_percent,
        },
    }


if __name__ == "__main__":
    logger.info("Testing Chunk Overlap and Deduplication Mocks")

    mocks = ChunkOverlapDeduplicationMocks()

    doc = mocks.create_test_document("test_doc_1", "normal")
    logger.info(f"Created document: {doc.document_id}")
    logger.info(f"Content length: {len(doc.content)} tokens")

    result = mocks.create_chunked_document(doc, chunk_size_tokens=100, overlap_percent=0.20)
    logger.info(f"Chunked into {result['chunk_count']} chunks")
    logger.info(f"Deduplication info: {result['dedup_info']}")

    for chunk in result["chunks"][:3]:
        logger.info(f"Chunk {chunk['chunk_id']}: {len(chunk['content'])} chars, "
                   f"{chunk['token_count']} tokens, "
                   f"overlap={chunk['overlap_with_previous']}")

    batch_result = create_mock_chunk_environment(
        document_count=10,
        chunk_size_tokens=256,
        overlap_percent=0.25,
    )
    logger.info(f"Batch environment: {batch_result['vector_store']['total_chunks']} total chunks")
