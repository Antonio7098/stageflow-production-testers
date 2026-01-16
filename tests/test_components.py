import base64
import os

import pytest
from stageflow import StageStatus, StageOutput
from stageflow.stages.inputs import StageInputs
from stageflow.testing import create_test_stage_context, create_test_snapshot

from components.llm import GroqChatSettings, GroqChatStage, GroqLLMClient
from components.audio.stages import STTStage, TTSStage


@pytest.mark.asyncio
async def test_groq_llm_stage_streams():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        pytest.skip("GROQ_API_KEY not set; skipping live Groq call")

    client = GroqLLMClient(
        api_key=api_key,
        settings=GroqChatSettings(stream=False, max_tokens=64, temperature=0.1),
    )
    stage = GroqChatStage(client=client)
    snapshot = create_test_snapshot(input_text="Hi", extensions={"roadmap_entry_id": "CORE-001"})
    ctx = create_test_stage_context(snapshot=snapshot)

    try:
        output = await stage.execute(ctx)
        assert output.status == StageStatus.OK
        assert output.data["response"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_stt_tts_round_trip():
    stt_stage = STTStage()
    tts_stage = TTSStage()

    audio_bytes = b"\x00" * 3200
    stt_ctx = create_test_stage_context(
        snapshot=create_test_snapshot(extensions={"audio_input": base64.b64encode(audio_bytes).decode("ascii")})
    )

    stt_output = await stt_stage.execute(stt_ctx)
    assert stt_output.status == StageStatus.OK
    assert "transcript" in stt_output.data

    tts_snapshot = create_test_snapshot()
    tts_inputs = StageInputs(
        snapshot=tts_snapshot,
        prior_outputs={"groq_llm": StageOutput.ok(response=stt_output.data["transcript"])},
    )
    tts_ctx = create_test_stage_context(snapshot=tts_snapshot, inputs=tts_inputs)
    tts_output = await tts_stage.execute(tts_ctx)
    assert tts_output.status == StageStatus.OK
    assert "audio" in tts_output.data
