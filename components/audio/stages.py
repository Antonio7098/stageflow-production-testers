from __future__ import annotations

import asyncio
import base64
from typing import AsyncIterator, Dict, Optional

from stageflow import StageContext, StageKind, StageOutput
from stageflow.helpers import AudioChunk, STTResponse, TTSResponse
from stageflow.stages.ports import AudioPorts, create_audio_ports

from .streaming_mocks import (
    StreamingAudioDuplex,
    StreamingSTTMock,
    StreamingTTSMock,
    create_streaming_audio_ports,
)


class STTStage:
    """Speech-to-text stage built on the streaming mocks."""

    name = "stt"
    kind = StageKind.TRANSFORM

    def __init__(self, stt_provider: StreamingSTTMock | None = None) -> None:
        self._stt = stt_provider or StreamingSTTMock()

    async def execute(self, ctx: StageContext) -> StageOutput:
        audio_data = ctx.snapshot.extensions.get("audio_input")
        if not audio_data:
            return StageOutput.skip(reason="No audio input provided")

        if isinstance(audio_data, str):
            audio_data = base64.b64decode(audio_data)

        try:
            result = await self._stt.transcribe(audio_data)
            stt = STTResponse(
                text=result.get("text", ""),
                confidence=result.get("confidence", 0.0),
                duration_ms=result.get("duration_ms", 0.0),
                provider=result.get("provider", "mock-stt"),
                model=result.get("model", "streaming"),
            )
            return StageOutput.ok(
                transcript=stt.text,
                stt=stt.to_dict(),
            )
        except Exception as exc:  # noqa: BLE001
            return StageOutput.fail(error=f"STT failed: {exc}")


class StreamingSTTStage:
    """Streaming STT that consumes audio chunks from a duplex."""

    name = "streaming_stt"
    kind = StageKind.TRANSFORM

    def __init__(
        self,
        duplex: StreamingAudioDuplex | None = None,
        stt_provider: StreamingSTTMock | None = None,
    ) -> None:
        self._duplex = duplex or StreamingAudioDuplex(
            queue=create_streaming_audio_ports().ports.queue,  # type: ignore[attr-defined]
            buffer=create_streaming_audio_ports().ports.buffer,  # type: ignore[attr-defined]
        )
        self._stt = stt_provider or StreamingSTTMock()

    async def execute(self, ctx: StageContext) -> StageOutput:
        async def chunk_iter() -> AsyncIterator[AudioChunk]:
            async for chunk in self._duplex.iter_consumer_chunks():
                yield chunk

        try:
            partial_text = ""
            async for text in self._stt.stream(chunk_iter()):
                partial_text = text
                ctx.emit_event("stt.partial", {"text": partial_text})

            if not partial_text:
                return StageOutput.skip(reason="No transcript produced")

            return StageOutput.ok(transcript=partial_text)
        except Exception as exc:  # noqa: BLE001
            return StageOutput.fail(error=f"Streaming STT failed: {exc}")


class TTSStage:
    """Text-to-speech stage that emits encoded audio."""

    name = "tts"
    kind = StageKind.TRANSFORM

    def __init__(self, tts_provider: StreamingTTSMock | None = None) -> None:
        self._tts = tts_provider or StreamingTTSMock()

    async def execute(self, ctx: StageContext) -> StageOutput:
        response_text = None
        inputs = ctx.inputs
        if hasattr(inputs, "get_from"):
            response_text = inputs.get_from("groq_llm", "response") or inputs.get("response")
        elif isinstance(inputs, dict):
            response_text = inputs.get("response")
        if not response_text:
            return StageOutput.skip(reason="No response text to synthesize")

        try:
            audio_bytes = await self._tts.synthesize(response_text)
            audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
            tts = TTSResponse(
                audio=audio_bytes,
                duration_ms=len(audio_bytes) / (16000 * 2) * 1000,
                provider="mock-tts",
                model=self._tts.voice,
            )
            return StageOutput.ok(
                audio=audio_b64,
                text=response_text,
                tts=tts.to_dict(),
            )
        except Exception as exc:  # noqa: BLE001
            return StageOutput.fail(error=f"TTS failed: {exc}")


class StreamingTTSStage:
    """Streaming TTS that feeds a duplex buffer chunk-by-chunk."""

    name = "streaming_tts"
    kind = StageKind.TRANSFORM

    def __init__(
        self,
        duplex: StreamingAudioDuplex | None = None,
        tts_provider: StreamingTTSMock | None = None,
    ) -> None:
        self._duplex = duplex or StreamingAudioDuplex(
            queue=create_streaming_audio_ports().ports.queue,  # type: ignore[attr-defined]
            buffer=create_streaming_audio_ports().ports.buffer,  # type: ignore[attr-defined]
        )
        self._tts = tts_provider or StreamingTTSMock()

    async def execute(self, ctx: StageContext) -> StageOutput:
        response_text = ctx.inputs.get_from("groq_llm", "response") or ctx.inputs.get("response")
        if not response_text:
            return StageOutput.skip(reason="No response text to stream")

        try:
            total_bytes = 0
            chunks_sent = 0
            async for chunk in self._tts.stream(response_text):
                self._duplex.feed_tts(chunk)
                total_bytes += len(chunk.data)
                chunks_sent += 1
                ctx.emit_event(
                    "tts.chunk_sent",
                    {"bytes": len(chunk.data), "chunks_sent": chunks_sent},
                )

            return StageOutput.ok(
                text=response_text,
                total_bytes=total_bytes,
                chunks_sent=chunks_sent,
            )
        except Exception as exc:  # noqa: BLE001
            return StageOutput.fail(error=f"Streaming TTS failed: {exc}")


__all__ = [
    "STTStage",
    "StreamingSTTStage",
    "TTSStage",
    "StreamingTTSStage",
]
