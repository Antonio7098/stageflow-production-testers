"""Streaming mock data generators for TRANSFORM-007 stress testing.

This module provides mock data generators for testing streaming transforms
under various conditions including normal operation, high load, edge cases,
and adversarial scenarios.
"""

import asyncio
import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple
from contextlib import asynccontextmanager

from stageflow.helpers import AudioChunk, ChunkQueue, StreamingBuffer


@dataclass
class StreamConfig:
    """Configuration for streaming test data generation."""
    sample_rate: int = 16000
    chunk_size_bytes: int = 320  # 20ms at 16kHz mono 16-bit
    chunk_interval_ms: int = 20
    max_queue_size: int = 1000
    buffer_target_ms: int = 200
    buffer_max_ms: int = 2000


@dataclass
class StreamMetrics:
    """Metrics collected during streaming operations."""
    chunks_produced: int = 0
    chunks_consumed: int = 0
    chunks_dropped: int = 0
    underrun_events: int = 0
    overflow_events: int = 0
    total_bytes: int = 0
    latency_samples: List[float] = field(default_factory=list)
    queue_sizes: List[int] = field(default_factory=list)
    buffer_levels: List[int] = field(default_factory=list)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "chunks_produced": self.chunks_produced,
            "chunks_consumed": self.chunks_consumed,
            "chunks_dropped": self.chunks_dropped,
            "underrun_events": self.underrun_events,
            "overflow_events": self.overflow_events,
            "total_bytes": self.total_bytes,
            "latency_samples": self.latency_samples,
            "queue_sizes": self.queue_sizes,
            "buffer_levels": self.buffer_levels,
            "duration_ms": self.duration_ms,
            "avg_latency_ms": sum(self.latency_samples) / len(self.latency_samples) if self.latency_samples else 0,
            "p50_latency_ms": self._percentile(50),
            "p95_latency_ms": self._percentile(95),
            "p99_latency_ms": self._percentile(99),
            "max_queue_size": max(self.queue_sizes) if self.queue_sizes else 0,
            "avg_buffer_level": sum(self.buffer_levels) / len(self.buffer_levels) if self.buffer_levels else 0,
        }

    def _percentile(self, p: int) -> float:
        """Calculate percentile of latency samples."""
        if not self.latency_samples:
            return 0.0
        sorted_samples = sorted(self.latency_samples)
        idx = int(len(sorted_samples) * p / 100)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]

    def reset(self) -> None:
        """Reset metrics for reuse."""
        self.chunks_produced = 0
        self.chunks_consumed = 0
        self.chunks_dropped = 0
        self.underrun_events = 0
        self.overflow_events = 0
        self.total_bytes = 0
        self.latency_samples = []
        self.queue_sizes = []
        self.buffer_levels = []
        self.duration_ms = 0.0


class StreamingMockDataGenerator:
    """Generates streaming mock data for testing."""

    def __init__(self, config: Optional[StreamConfig] = None):
        self.config = config or StreamConfig()

    def generate_audio_chunk(
        self,
        sequence: int,
        timestamp_ms: Optional[float] = None,
        data: Optional[bytes] = None,
    ) -> AudioChunk:
        """Generate a single audio chunk."""
        return AudioChunk(
            data=data or self._generate_audio_data(),
            sample_rate=self.config.sample_rate,
            timestamp_ms=timestamp_ms or (sequence * self.config.chunk_interval_ms),
        )

    def _generate_audio_data(self, size: Optional[int] = None) -> bytes:
        """Generate deterministic audio-like data."""
        size = size or self.config.chunk_size_bytes
        return bytes([i % 256 for i in range(size)])

    async def generate_chunks_stream(
        self,
        num_chunks: int,
        interval_ms: Optional[int] = None,
        on_chunk: Optional[Callable[[AudioChunk], asyncio.Future]] = None,
    ) -> AsyncIterator[AudioChunk]:
        """Generate a stream of audio chunks."""
        interval = interval_ms or self.config.chunk_interval_ms
        for i in range(num_chunks):
            chunk = self.generate_audio_chunk(i)
            if on_chunk:
                await on_chunk(chunk)
            yield chunk
            if interval > 0:
                await asyncio.sleep(interval / 1000.0)

    async def generate_burst_stream(
        self,
        chunks_per_burst: int,
        num_bursts: int,
        burst_interval_ms: int = 100,
    ) -> AsyncIterator[AudioChunk]:
        """Generate bursts of chunks."""
        sequence = 0
        for _ in range(num_bursts):
            for _ in range(chunks_per_burst):
                yield self.generate_audio_chunk(sequence)
                sequence += 1
            if burst_interval_ms > 0:
                await asyncio.sleep(burst_interval_ms / 1000.0)

    async def generate_variable_chunk_stream(
        self,
        num_chunks: int,
        size_range: Tuple[int, int] = (1, 3200),
    ) -> AsyncIterator[AudioChunk]:
        """Generate chunks with variable sizes."""
        import random
        min_size, max_size = size_range
        for i in range(num_chunks):
            size = random.randint(min_size, max_size)
            yield self.generate_audio_chunk(i, data=self._generate_audio_data(size))


class BackpressureTestGenerator:
    """Generates test scenarios for backpressure testing."""

    def __init__(self, config: Optional[StreamConfig] = None):
        self.config = config or StreamConfig()

    async def produce_faster_than_consume(
        self,
        queue: ChunkQueue,
        duration_ms: int = 5000,
        producer_delay_ms: int = 5,
        consumer_delay_ms: int = 50,
        metrics: Optional[StreamMetrics] = None,
    ) -> StreamMetrics:
        """Produce chunks faster than they can be consumed."""
        metrics = metrics or StreamMetrics()
        start_time = time.perf_counter()

        async def producer():
            seq = 0
            while time.perf_counter() - start_time < duration_ms / 1000.0:
                chunk = AudioChunk(
                    data=bytes([seq % 256] * self.config.chunk_size_bytes),
                    sample_rate=self.config.sample_rate,
                    timestamp_ms=seq * self.config.chunk_interval_ms,
                )
                success = await queue.put(chunk)
                if not success:
                    metrics.chunks_dropped += 1
                else:
                    metrics.chunks_produced += 1
                    metrics.queue_sizes.append(queue.size())
                seq += 1
                await asyncio.sleep(producer_delay_ms / 1000.0)

        async def consumer():
            nonlocal metrics
            while time.perf_counter() - start_time < duration_ms / 1000.0:
                try:
                    chunk = await asyncio.wait_for(queue.get(), timeout=0.1)
                    metrics.chunks_consumed += 1
                    metrics.total_bytes += len(chunk.data)
                except asyncio.TimeoutError:
                    pass
                await asyncio.sleep(consumer_delay_ms / 1000.0)

        producer_task = asyncio.create_task(producer())
        consumer_task = asyncio.create_task(consumer())

        await asyncio.gather(producer_task, consumer_task)

        metrics.duration_ms = (time.perf_counter() - start_time) * 1000
        return metrics

    async def test_queue_overflow(
        self,
        max_size: int,
        num_chunks: int,
        drop_on_overflow: bool = True,
    ) -> Tuple[ChunkQueue, StreamMetrics]:
        """Test queue overflow behavior."""
        metrics = StreamMetrics()
        queue = ChunkQueue(max_size=max_size, drop_on_overflow=drop_on_overflow)

        async def fast_producer():
            for i in range(num_chunks):
                chunk = AudioChunk(
                    data=bytes([i % 256] * self.config.chunk_size_bytes),
                    sample_rate=self.config.sample_rate,
                )
                success = await queue.put(chunk)
                if not success:
                    metrics.chunks_dropped += 1
                else:
                    metrics.chunks_produced += 1

        await fast_producer()
        metrics.duration_ms = 0
        return queue, metrics


class BufferTestGenerator:
    """Generates test scenarios for streaming buffer testing."""

    def __init__(self, config: Optional[StreamConfig] = None):
        self.config = config or StreamConfig()

    async def test_buffer_overflow(
        self,
        target_ms: int = 200,
        max_ms: int = 2000,
        chunk_size: int = 320,
        chunks_to_add: int = 100,
    ) -> Tuple[StreamingBuffer, StreamMetrics]:
        """Test buffer overflow handling."""
        metrics = StreamMetrics()
        buffer = StreamingBuffer(
            target_duration_ms=target_ms,
            max_duration_ms=max_ms,
            sample_rate=self.config.sample_rate,
        )

        buffer_level = 0
        for i in range(chunks_to_add):
            chunk = AudioChunk(
                data=bytes([i % 256] * chunk_size),
                sample_rate=self.config.sample_rate,
            )
            dropped = buffer.add_chunk(chunk)
            if dropped:
                metrics.chunks_dropped += dropped
                metrics.overflow_events += 1
            metrics.chunks_produced += 1
            buffer_level += 1 - dropped
            metrics.buffer_levels.append(buffer_level)

        metrics.duration_ms = 0
        return buffer, metrics

    async def test_buffer_underrun(
        self,
        target_ms: int = 200,
        max_ms: int = 2000,
        chunk_size: int = 320,
        initial_chunks: int = 5,
        read_delay_ms: int = 100,
    ) -> Tuple[StreamingBuffer, StreamMetrics]:
        """Test buffer underrun detection."""
        metrics = StreamMetrics()
        buffer = StreamingBuffer(
            target_duration_ms=target_ms,
            max_duration_ms=max_ms,
            sample_rate=self.config.sample_rate,
        )

        for i in range(initial_chunks):
            chunk = AudioChunk(
                data=bytes([i % 256] * chunk_size),
                sample_rate=self.config.sample_rate,
            )
            buffer.add_chunk(chunk)
            metrics.chunks_produced += 1

        reads = 0
        while buffer.is_ready() and reads < 20:
            data = buffer.read(chunk_size)
            if not data:
                metrics.underrun_events += 1
                break
            metrics.chunks_consumed += 1
            reads += 1
            await asyncio.sleep(read_delay_ms / 1000.0)

        metrics.duration_ms = 0
        return buffer, metrics


class LatencyTestGenerator:
    """Generates test scenarios for latency testing."""

    def __init__(self, config: Optional[StreamConfig] = None):
        self.config = config or StreamConfig()

    async def measure_processing_latency(
        self,
        num_operations: int = 100,
        base_latency_ms: float = 10,
        jitter_ms: float = 5,
    ) -> List[float]:
        """Measure processing latency with controlled jitter."""
        latencies = []

        for i in range(num_operations):
            start = time.perf_counter()
            latency = base_latency_ms + (i % 3 - 1) * jitter_ms
            await asyncio.sleep(latency / 1000.0)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)

        return latencies

    async def measure_end_to_end_latency(
        self,
        num_messages: int = 50,
        queue_size: int = 100,
        process_time_ms: int = 5,
    ) -> Tuple[ChunkQueue, List[float]]:
        """Measure end-to-end latency through a queue."""
        queue = ChunkQueue(max_size=queue_size)
        latencies = []

        async def measure():
            start = time.perf_counter()
            chunk = await queue.get()
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
            return chunk

        for i in range(num_messages):
            chunk = AudioChunk(
                data=bytes([i % 256] * self.config.chunk_size_bytes),
                sample_rate=self.config.sample_rate,
            )
            await queue.put(chunk)
            await asyncio.sleep(process_time_ms / 1000.0)
            await measure()

        return queue, latencies


class AdversarialTestGenerator:
    """Generates adversarial test scenarios for security and robustness."""

    def __init__(self, config: Optional[StreamConfig] = None):
        self.config = config or StreamConfig()

    async def generate_malformed_chunks(
        self,
        num_chunks: int = 10,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Generate malformed chunk data for testing robustness."""
        for i in range(num_chunks):
            yield {
                "sequence": i,
                "data": None,  # Missing data
                "sample_rate": -1,  # Invalid sample rate
                "timestamp_ms": float('inf'),  # Invalid timestamp
            }

    async def generate_empty_chunks(
        self,
        num_chunks: int = 20,
    ) -> AsyncIterator[AudioChunk]:
        """Generate empty chunks to test handling."""
        for i in range(num_chunks):
            yield AudioChunk(
                data=b"",  # Empty data
                sample_rate=self.config.sample_rate,
                timestamp_ms=i * self.config.chunk_interval_ms,
            )

    async def generate_oversized_chunks(
        self,
        num_chunks: int = 5,
        size_bytes: int = 1024 * 1024,  # 1MB
    ) -> AsyncIterator[AudioChunk]:
        """Generate very large chunks to test memory handling."""
        for i in range(num_chunks):
            yield AudioChunk(
                data=bytes([i % 256] * size_bytes),
                sample_rate=self.config.sample_rate,
                timestamp_ms=i * self.config.chunk_interval_ms,
            )

    async def generate_rapid_open_close(
        self,
        num_cycles: int = 10,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Generate rapid queue open/close cycles."""
        for i in range(num_cycles):
            yield {
                "action": "open" if i % 2 == 0 else "close",
                "sequence": i,
                "timestamp": time.perf_counter(),
            }


class StreamingMetricsCollector:
    """Collects and aggregates streaming metrics."""

    def __init__(self):
        self.runs: List[StreamMetrics] = []
        self.current_run: Optional[StreamMetrics] = None

    def start_run(self) -> None:
        """Start a new metrics collection run."""
        self.current_run = StreamMetrics()

    def record_chunk_produced(self, queue_size: int = 0) -> None:
        """Record a chunk was produced."""
        if self.current_run:
            self.current_run.chunks_produced += 1
            self.current_run.queue_sizes.append(queue_size)

    def record_chunk_consumed(self, buffer_available: int = 0) -> None:
        """Record a chunk was consumed."""
        if self.current_run:
            self.current_run.chunks_consumed += 1
            self.current_run.buffer_levels.append(buffer_available)

    def record_chunk_dropped(self) -> None:
        """Record a chunk was dropped."""
        if self.current_run:
            self.current_run.chunks_dropped += 1

    def record_underrun(self) -> None:
        """Record a buffer underrun event."""
        if self.current_run:
            self.current_run.underrun_events += 1

    def record_overflow(self) -> None:
        """Record a buffer overflow event."""
        if self.current_run:
            self.current_run.overflow_events += 1

    def record_latency(self, latency_ms: float) -> None:
        """Record a latency sample."""
        if self.current_run:
            self.current_run.latency_samples.append(latency_ms)

    def end_run(self, duration_ms: float = 0.0) -> StreamMetrics:
        """End the current run and store metrics."""
        if self.current_run:
            self.current_run.duration_ms = duration_ms
            self.runs.append(self.current_run)
            result = self.current_run
            self.current_run = None
            return result
        return StreamMetrics()

    def get_aggregate_metrics(self) -> Dict[str, Any]:
        """Get aggregate metrics across all runs."""
        if not self.runs:
            return {}

        total_chunks = sum(r.chunks_produced for r in self.runs)
        total_dropped = sum(r.chunks_dropped for r in self.runs)

        return {
            "total_runs": len(self.runs),
            "total_chunks_produced": total_chunks,
            "total_chunks_consumed": sum(r.chunks_consumed for r in self.runs),
            "total_chunks_dropped": total_dropped,
            "total_underrun_events": sum(r.underrun_events for r in self.runs),
            "total_overflow_events": sum(r.overflow_events for r in self.runs),
            "drop_rate_percent": (total_dropped / total_chunks * 100) if total_chunks > 0 else 0,
            "runs": [r.to_dict() for r in self.runs],
        }


async def run_baseline_streaming_test(
    num_chunks: int = 100,
    chunk_interval_ms: int = 20,
    config: Optional[StreamConfig] = None,
) -> StreamMetrics:
    """Run a baseline streaming test with normal conditions."""
    config = config or StreamConfig()
    metrics = StreamMetrics()
    queue = ChunkQueue(max_size=config.max_queue_size)
    start_time = time.perf_counter()

    async def producer():
        for i in range(num_chunks):
            chunk = AudioChunk(
                data=bytes([i % 256] * config.chunk_size_bytes),
                sample_rate=config.sample_rate,
                timestamp_ms=i * config.chunk_interval_ms,
            )
            await queue.put(chunk)
            metrics.chunks_produced += 1
            await asyncio.sleep(chunk_interval_ms / 1000.0)

    async def consumer():
        for _ in range(num_chunks):
            chunk = await queue.get()
            metrics.chunks_consumed += 1
            metrics.total_bytes += len(chunk.data)

    await asyncio.gather(producer(), consumer())
    metrics.duration_ms = (time.perf_counter() - start_time) * 1000
    return metrics


async def run_high_load_streaming_test(
    num_chunks: int = 1000,
    producer_delay_ms: int = 1,
    consumer_delay_ms: int = 10,
    config: Optional[StreamConfig] = None,
) -> StreamMetrics:
    """Run a high-load streaming test."""
    config = config or StreamConfig()
    metrics = StreamMetrics()
    queue = ChunkQueue(max_size=config.max_queue_size)
    start_time = time.perf_counter()

    async def producer():
        for i in range(num_chunks):
            chunk = AudioChunk(
                data=bytes([i % 256] * config.chunk_size_bytes),
                sample_rate=config.sample_rate,
            )
            success = await queue.put(chunk)
            if not success:
                metrics.chunks_dropped += 1
            else:
                metrics.chunks_produced += 1
            await asyncio.sleep(producer_delay_ms / 1000.0)

    async def consumer():
        consumed = 0
        while consumed < num_chunks:
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=0.1)
                metrics.chunks_consumed += 1
                metrics.total_bytes += len(chunk.data)
                consumed += 1
            except asyncio.TimeoutError:
                pass
            await asyncio.sleep(consumer_delay_ms / 1000.0)

    await asyncio.gather(producer(), consumer())
    metrics.duration_ms = (time.perf_counter() - start_time) * 1000
    return metrics


async def run_burst_streaming_test(
    bursts: int = 10,
    chunks_per_burst: int = 50,
    burst_interval_ms: int = 200,
    config: Optional[StreamConfig] = None,
) -> StreamMetrics:
    """Run a burst streaming test."""
    config = config or StreamConfig()
    metrics = StreamMetrics()
    queue = ChunkQueue(max_size=config.max_queue_size)
    generator = StreamingMockDataGenerator(config)

    start_time = time.perf_counter()

    async def producer():
        async for chunk in generator.generate_burst_stream(
            chunks_per_burst, bursts, burst_interval_ms
        ):
            success = await queue.put(chunk)
            if not success:
                metrics.chunks_dropped += 1
            metrics.chunks_produced += 1

    async def consumer():
        consumed = 0
        target = bursts * chunks_per_burst
        while consumed < target:
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=0.5)
                metrics.chunks_consumed += 1
                metrics.total_bytes += len(chunk.data)
                consumed += 1
            except asyncio.TimeoutError:
                pass

    await asyncio.gather(producer(), consumer())
    metrics.duration_ms = (time.perf_counter() - start_time) * 1000
    return metrics
