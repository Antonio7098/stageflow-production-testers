from __future__ import annotations

import asyncio
import base64
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from stageflow.helpers import AudioChunk, ChunkQueue, StreamingBuffer
from stageflow.stages.ports import AudioPorts, create_audio_ports
from stageflow import StageContext, StageKind, StageOutput

ChunkConsumer = Callable[[AudioChunk], Awaitable[None]]


def _default_event_emitter(event: str, attrs: dict | None = None) -> None:
    pass


@dataclass(slots=True)
class StreamingAudioDuplex:
    """Bidirectional audio helper with independent STT and TTS flows."""

    queue: ChunkQueue
    buffer: StreamingBuffer

    async def push_microphone_chunk(self, chunk: AudioChunk) -> None:
        await self.queue.put(chunk)

    async def iter_consumer_chunks(self) -> AsyncIterator[AudioChunk]:
        async for chunk in self.queue:
            yield chunk

    def feed_tts(self, chunk: AudioChunk) -> None:
        dropped = self.buffer.add_chunk(chunk)
        if dropped:
            self.buffer.emit_event("stream.buffer_overflow", {"dropped": dropped})

    def read_tts_audio(self, duration_ms: int = 20) -> bytes:
        if not self.buffer.is_ready():
            return b""
        return self.buffer.read(duration_ms=duration_ms)


class StreamingSTTMock:
    """Mock Speech-to-Text provider that supports streaming chunks via queues."""

    def __init__(
        self,
        *,
        latency_ms: int = 120,
        transcript: str = "Hello from STT mock",
        confidence: float = 0.92,
        event_emitter: Callable[[str, dict | None], None] | None = None,
    ) -> None:
        self.latency_ms = latency_ms
        self.transcript = transcript
        self.confidence = confidence
        self.event_emitter = event_emitter or _default_event_emitter

    async def transcribe(self, audio_data: bytes, language: str = "en") -> dict:
        await asyncio.sleep(self.latency_ms / 1000)
        self.event_emitter("stt.transcribe", {"bytes": len(audio_data), "language": language})
        return {
            "text": self.transcript,
            "confidence": self.confidence,
            "duration_ms": (len(audio_data) / (16000 * 2)) * 1000,
            "provider": "mock-stt",
            "model": "streaming",
        }

    async def stream(self, chunks: AsyncIterator[AudioChunk], language: str = "en") -> AsyncIterator[str]:
        accumulator = []
        async for chunk in chunks:
            await asyncio.sleep(self.latency_ms / 1000)
            self.event_emitter("stt.chunk", {"bytes": len(chunk.data), "language": language})
            accumulator.append("la")
            yield "".join(accumulator)


class StreamingTTSMock:
    """Mock Text-to-Speech provider with chunked streaming support."""

    def __init__(
        self,
        *,
        latency_ms: int = 60,
        sample_rate: int = 16000,
        voice: str = "stageflow",
        event_emitter: Callable[[str, dict | None], None] | None = None,
    ) -> None:
        self.latency_ms = latency_ms
        self.sample_rate = sample_rate
        self.voice = voice
        self.event_emitter = event_emitter or _default_event_emitter

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        await asyncio.sleep(self.latency_ms / 1000)
        payload = f"{voice or self.voice}:{text}".encode("utf-8")
        self.event_emitter("tts.synthesize", {"bytes": len(payload), "voice": voice or self.voice})
        return payload

    async def stream(self, text: str, chunk_ms: int = 40) -> AsyncIterator[AudioChunk]:
        encoded = text.encode("utf-8")
        chunk_size = max(1, int(len(encoded) * (chunk_ms / 1000)))
        for offset in range(0, len(encoded), chunk_size):
            await asyncio.sleep(chunk_ms / 1000)
            data = encoded[offset : offset + chunk_size]
            chunk = AudioChunk(
                data=data,
                sample_rate=self.sample_rate,
                timestamp_ms=offset / self.sample_rate,
            )
            self.event_emitter("tts.chunk", {"bytes": len(data), "voice": self.voice})
            yield chunk


def create_streaming_audio_ports(
    *,
    stt: StreamingSTTMock | None = None,
    tts: StreamingTTSMock | None = None,
    duplex: StreamingAudioDuplex | None = None,
) -> AudioPorts:
    queue = ChunkQueue(max_size=200, event_emitter=_default_event_emitter)
    buffer = StreamingBuffer(
        target_duration_ms=200,
        max_duration_ms=2000,
        sample_rate=16000,
        event_emitter=_default_event_emitter,
    )
    duplex = duplex or StreamingAudioDuplex(queue=queue, buffer=buffer)
    return create_audio_ports(
        stt_client=stt or StreamingSTTMock(),
        tts_client=tts or StreamingTTSMock(),
        audio_callback=lambda chunk: duplex.feed_tts(chunk),
    )
