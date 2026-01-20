"""TRANSFORM-006: Encoding detection and conversion test pipelines.

This module contains test pipelines for:
- BOM detection and stripping
- Character set detection
- Mojibake repair
- Surrogate pair validation
- Encoding conversion
- Silent failure detection
"""

from __future__ import annotations

import asyncio
import json
import logging
import unicodedata
from typing import Any, Optional
from uuid import uuid4

from stageflow import (
    Pipeline,
    StageContext,
    StageKind,
    StageOutput,
    PipelineTimer,
)
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow.stages import StageInputs

from mocks.encoding_mocks import EncodingMockData

logger = logging.getLogger(__name__)


# =============================================================================
# Encoding Detection Stage
# =============================================================================

class EncodingDetectStage:
    """TRANSFORM stage that detects and reports on text encoding."""

    name = "encoding_detect"
    kind = StageKind.TRANSFORM

    async def execute(self, ctx: StageContext) -> StageOutput:
        text = ctx.snapshot.input_text or ""
        if not text:
            return StageOutput.skip(reason="No text provided")

        detection = self._detect_encoding(text)

        return StageOutput.ok(
            original=text,
            encoding=detection["encoding"],
            confidence=detection["confidence"],
            is_ascii=text.isascii(),
            has_bom=detection.get("has_bom", False),
            byte_length=len(text.encode("utf-8")),
            char_length=len(text),
        )

    def _detect_encoding(self, text: str) -> dict[str, Any]:
        """Detect encoding of the input text."""
        result = {
            "encoding": "unknown",
            "confidence": "low",
            "has_bom": False,
        }

        # Check for BOM
        encoded = text.encode("utf-8")
        if encoded.startswith(b"\xef\xbb\xbf"):
            result["encoding"] = "utf-8-bom"
            result["has_bom"] = True
            result["confidence"] = "high"
            return result
        elif encoded.startswith(b"\xfe\xff"):
            result["encoding"] = "utf-16-be"
            result["has_bom"] = True
            result["confidence"] = "high"
            return result
        elif encoded.startswith(b"\xff\xfe"):
            result["encoding"] = "utf-16-le"
            result["has_bom"] = True
            result["confidence"] = "high"
            return result

        # Check for pure ASCII
        if text.isascii():
            result["encoding"] = "ascii"
            result["confidence"] = "high"
            return result

        # Check for UTF-8 validity
        try:
            text.encode("utf-8")
            result["encoding"] = "utf-8"
            result["confidence"] = "high"
        except UnicodeEncodeError:
            result["encoding"] = "unknown-8bit"
            result["confidence"] = "low"

        return result


# =============================================================================
# BOM Strip Stage
# =============================================================================

class BOMStripStage:
    """TRANSFORM stage that strips BOM from text."""

    name = "bom_strip"
    kind = StageKind.TRANSFORM

    async def execute(self, ctx: StageContext) -> StageOutput:
        text = ctx.snapshot.input_text or ""
        if not text:
            return StageOutput.skip(reason="No text provided")

        stripped, bom_type = self._strip_bom(text)

        return StageOutput.ok(
            original=text,
            stripped_text=stripped,
            bom_detected=bom_type is not None,
            bom_type=bom_type,
            original_length=len(text),
            stripped_length=len(stripped),
        )

    def _strip_bom(self, text: str) -> tuple[str, Optional[str]]:
        """Strip BOM from text and return BOM type."""
        encoded = text.encode("utf-8")

        if encoded.startswith(b"\xef\xbb\xbf"):
            return encoded[3:].decode("utf-8"), "utf-8"
        elif encoded.startswith(b"\xfe\xff"):
            return encoded[2:].decode("utf-16-be"), "utf-16-be"
        elif encoded.startswith(b"\xff\xfe"):
            return encoded[2:].decode("utf-16-le"), "utf-16-le"

        return text, None


# =============================================================================
# Mojibake Repair Stage
# =============================================================================

class MojibakeRepairStage:
    """TRANSFORM stage that attempts to repair mojibake (encoding corruption)."""

    name = "mojibake_repair"
    kind = StageKind.TRANSFORM

    def __init__(self, aggressive: bool = False) -> None:
        self.aggressive = aggressive

    async def execute(self, ctx: StageContext) -> StageOutput:
        text = ctx.snapshot.input_text or ""
        if not text:
            return StageOutput.skip(reason="No text provided")

        repaired, repairs = self._repair_mojibake(text)

        return StageOutput.ok(
            original=text,
            repaired=repaired,
            repairs_made=len(repairs),
            repair_details=repairs,
            was_modified=repaired != text,
        )

    def _repair_mojibake(self, text: str) -> tuple[str, list[dict[str, Any]]]:
        """Attempt to detect and repair mojibake in text."""
        repairs: list[dict[str, Any]] = []
        result = text

        # Check for UTF-8 misinterpreted as Latin-1
        # Pattern: Ã©, Â, Ã±, etc.
        if "Ã" in text or "Â" in text:
            try:
                fixed = text.encode("latin-1").decode("utf-8")
                if fixed != text:
                    repairs.append({
                        "type": "utf8-as-latin1",
                        "original_preview": text[:50],
                        "repaired_preview": fixed[:50],
                    })
                    result = fixed
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass

        # Check for Windows-1252 misinterpreted as UTF-8
        # Pattern: Smart quotes, special dashes
        windows_1252_chars = ["\x92", "\x93", "\x94", "\x96", "\x97"]
        has_windows_chars = any(c in text for c in windows_1252_chars)

        if has_windows_chars or self.aggressive:
            try:
                fixed = text.encode("utf-8", errors="replace").decode("windows-1252", errors="replace")
                if fixed != text:
                    repairs.append({
                        "type": "windows1252-as-utf8",
                        "original_preview": text[:50],
                        "repaired_preview": fixed[:50],
                    })
                    result = fixed
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass

        # Normalize Unicode (NFC)
        normalized = unicodedata.normalize("NFC", result)
        if normalized != result:
            repairs.append({
                "type": "unicode_normalization",
                "original_preview": result[:50],
                "repaired_preview": normalized[:50],
            })
            result = normalized

        return result, repairs


# =============================================================================
# Surrogate Pair Validation Stage
# =============================================================================

class SurrogateValidateStage:
    """TRANSFORM stage that validates surrogate pairs in text."""

    name = "surrogate_validate"
    kind = StageKind.TRANSFORM

    async def execute(self, ctx: StageContext) -> StageOutput:
        text = ctx.snapshot.input_text or ""
        if not text:
            return StageOutput.skip(reason="No text provided")

        validation = self._validate_surrogates(text)

        return StageOutput.ok(
            original=text,
            is_valid=validation["is_valid"],
            has_surrogates=validation["has_surrogates"],
            surrogate_count=validation["surrogate_count"],
            invalid_surrogates=validation["invalid_surrogates"],
            emoji_count=validation["emoji_count"],
            details=validation["details"],
        )

    def _validate_surrogates(self, text: str) -> dict[str, Any]:
        """Validate surrogate pairs in text."""
        result = {
            "is_valid": True,
            "has_surrogates": False,
            "surrogate_count": 0,
            "invalid_surrogates": [],
            "emoji_count": 0,
            "details": [],
        }

        for i, char in enumerate(text):
            code = ord(char)

            # Check for surrogate range
            if 0xD800 <= code <= 0xDFFF:
                result["has_surrogates"] = True
                result["surrogate_count"] += 1

                # Check if it's a high surrogate
                if 0xD800 <= code <= 0xDBFF:
                    # High surrogate - should be followed by low surrogate
                    if i + 1 < len(text):
                        next_code = ord(text[i + 1])
                        if not (0xDC00 <= next_code <= 0xDFFF):
                            result["is_valid"] = False
                            result["invalid_surrogates"].append({
                                "position": i,
                                "type": "lone_high_surrogate",
                                "hex": f"U+{code:04X}",
                            })
                    else:
                        result["is_valid"] = False
                        result["invalid_surrogates"].append({
                            "position": i,
                            "type": "unpaired_high_surrogate",
                            "hex": f"U+{code:04X}",
                        })

                # Check if it's a low surrogate
                elif 0xDC00 <= code <= 0xDFFF:
                    # Low surrogate - should be preceded by high surrogate
                    if i == 0:
                        result["is_valid"] = False
                        result["invalid_surrogates"].append({
                            "position": i,
                            "type": "lone_low_surrogate",
                            "hex": f"U+{code:04X}",
                        })
                    else:
                        prev_code = ord(text[i - 1])
                        if not (0xD800 <= prev_code <= 0xDBFF):
                            result["is_valid"] = False
                            result["invalid_surrogates"].append({
                                "position": i,
                                "type": "lone_low_surrogate",
                                "hex": f"U+{code:04X}",
                            })

                # Check for emoji (common surrogate pair patterns)
                if result["has_surrogates"]:
                    try:
                        char.encode("utf-8")
                        # If single char encodes to 4 bytes, it's likely an emoji
                        if len(char.encode("utf-8")) == 4:
                            result["emoji_count"] += 1
                    except UnicodeEncodeError:
                        pass

        if result["invalid_surrogates"]:
            result["is_valid"] = False

        return result


# =============================================================================
# Encoding Conversion Stage
# =============================================================================

class EncodingConvertStage:
    """TRANSFORM stage that converts text between encodings."""

    name = "encoding_convert"
    kind = StageKind.TRANSFORM

    def __init__(
        self,
        target_encoding: str = "utf-8",
        source_encoding: Optional[str] = None,
        replacement_char: str = "?",
    ) -> None:
        self.target_encoding = target_encoding
        self.source_encoding = source_encoding
        self.replacement_char = replacement_char

    async def execute(self, ctx: StageContext) -> StageOutput:
        text = ctx.snapshot.input_text or ""
        if not text:
            return StageOutput.skip(reason="No text provided")

        conversion = self._convert_encoding(text)

        return StageOutput.ok(
            original=text,
            converted=conversion["result"],
            source_encoding=conversion["source_encoding"],
            target_encoding=self.target_encoding,
            success=conversion["success"],
            error=conversion.get("error"),
            original_size=conversion["original_size"],
            converted_size=conversion["converted_size"],
        )

    def _convert_encoding(self, text: str) -> dict[str, Any]:
        """Convert text to target encoding."""
        result = {
            "result": None,
            "source_encoding": self.source_encoding or "utf-8",
            "success": False,
            "original_size": len(text.encode("utf-8")),
            "converted_size": 0,
        }

        try:
            # Decode from source (if specified)
            if self.source_encoding:
                decoded = text.encode(self.source_encoding).decode(self.target_encoding)
            else:
                decoded = text

            # Encode to target
            encoded = decoded.encode(
                self.target_encoding,
                errors="replace",
                replacecharacter=self.replacement_char,
            )
            result["result"] = encoded.decode(self.target_encoding)
            result["success"] = True
            result["converted_size"] = len(encoded)

        except (UnicodeDecodeError, UnicodeEncodeError) as e:
            result["error"] = str(e)
            result["result"] = text

        return result


# =============================================================================
# JSON Parse with Encoding Stage
# =============================================================================

class JSONParseStage:
    """TRANSFORM stage that parses JSON with encoding handling."""

    name = "json_parse"
    kind = StageKind.TRANSFORM

    def __init__(self, strict: bool = False) -> None:
        self.strict = strict

    async def execute(self, ctx: StageContext) -> StageOutput:
        text = ctx.snapshot.input_text or ""
        if not text:
            return StageOutput.skip(reason="No JSON text provided")

        parse_result = self._parse_json(text)

        if parse_result["success"]:
            return StageOutput.ok(
                raw=text,
                parsed=parse_result["parsed"],
                format_detected=parse_result.get("format", "json"),
                is_valid=True,
            )
        else:
            return StageOutput.fail(
                error=parse_result.get("error", "Parse failed"),
                data={
                    "raw_preview": text[:100],
                    "format": parse_result.get("format", "unknown"),
                },
            )

    def _parse_json(self, text: str) -> dict[str, Any]:
        """Parse JSON with encoding handling."""
        result = {
            "success": False,
            "parsed": None,
            "format": "plain",
        }

        # Strip BOM if present
        cleaned = text
        if text.encode("utf-8").startswith(b"\xef\xbb\xbf"):
            cleaned = text.encode("utf-8")[3:].decode("utf-8")
            result["format"] = "json-with-bom"

        # Try standard JSON
        try:
            result["parsed"] = json.loads(cleaned)
            result["success"] = True
            return result
        except json.JSONDecodeError:
            pass

        # Try fixing trailing comma
        try:
            fixed = cleaned.rstrip(",").rstrip() + "}"
            result["parsed"] = json.loads(fixed)
            result["success"] = True
            result["format"] = "json-with-trailing-comma"
            return result
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        if cleaned.startswith("```") and "```" in cleaned[3:]:
            lines = cleaned.split("\n")
            for i, line in enumerate(lines[1:], start=1):
                if line.strip() == "```":
                    code_content = "\n".join(lines[1:i])
                    # Remove language specifier
                    if code_content.startswith("json"):
                        code_content = code_content[4:].strip()
                    try:
                        result["parsed"] = json.loads(code_content)
                        result["success"] = True
                        result["format"] = "markdown-json"
                        return result
                    except json.JSONDecodeError:
                        pass
                    break

        result["error"] = f"Could not parse JSON (format: {result.get('format', 'unknown')})"
        return result


# =============================================================================
# Pipeline Builders
# =============================================================================

def create_bom_pipeline() -> Pipeline:
    """Create pipeline for BOM detection and stripping."""
    return (
        Pipeline()
        .with_stage("encoding_detect", EncodingDetectStage(), StageKind.TRANSFORM)
        .with_stage(
            "bom_strip",
            BOMStripStage(),
            StageKind.TRANSFORM,
            dependencies=["encoding_detect"],
        )
    )


def create_mojibake_pipeline(aggressive: bool = False) -> Pipeline:
    """Create pipeline for mojibake repair."""
    return (
        Pipeline()
        .with_stage(
            "mojibake_repair",
            MojibakeRepairStage(aggressive=aggressive),
            StageKind.TRANSFORM,
        )
    )


def create_surrogate_pipeline() -> Pipeline:
    """Create pipeline for surrogate pair validation."""
    return (
        Pipeline()
        .with_stage(
            "surrogate_validate",
            SurrogateValidateStage(),
            StageKind.TRANSFORM,
        )
    )


def create_encoding_conversion_pipeline(
    target_encoding: str = "utf-8",
    source_encoding: Optional[str] = None,
) -> Pipeline:
    """Create pipeline for encoding conversion."""
    return (
        Pipeline()
        .with_stage(
            "encoding_convert",
            EncodingConvertStage(
                target_encoding=target_encoding,
                source_encoding=source_encoding,
            ),
            StageKind.TRANSFORM,
        )
    )


def create_json_encoding_pipeline() -> Pipeline:
    """Create pipeline for JSON parsing with encoding handling."""
    return (
        Pipeline()
        .with_stage("encoding_detect", EncodingDetectStage(), StageKind.TRANSFORM)
        .with_stage(
            "json_parse",
            JSONParseStage(),
            StageKind.TRANSFORM,
            dependencies=["encoding_detect"],
        )
    )


def create_comprehensive_encoding_pipeline() -> Pipeline:
    """Create comprehensive encoding handling pipeline."""
    return (
        Pipeline()
        .with_stage("encoding_detect", EncodingDetectStage(), StageKind.TRANSFORM)
        .with_stage(
            "bom_strip",
            BOMStripStage(),
            StageKind.TRANSFORM,
            dependencies=["encoding_detect"],
        )
        .with_stage(
            "mojibake_repair",
            MojibakeRepairStage(),
            StageKind.TRANSFORM,
            dependencies=["bom_strip"],
        )
        .with_stage(
            "surrogate_validate",
            SurrogateValidateStage(),
            StageKind.TRANSFORM,
            dependencies=["mojibake_repair"],
        )
    )


# =============================================================================
# Test Runner
# =============================================================================

async def run_encoding_test(
    pipeline: Pipeline,
    test_input: str,
    stage_name: str = "test",
) -> dict[str, Any]:
    """Run a single encoding test."""
    test_id = str(uuid4())[:8]

    snapshot = ContextSnapshot(
        run_id=RunIdentity(
            pipeline_run_id=uuid4(),
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            org_id=None,
            interaction_id=uuid4(),
        ),
        topology="encoding_test",
        execution_mode="test",
        input_text=test_input,
    )

    ctx = StageContext(
        snapshot=snapshot,
        inputs=StageInputs(snapshot=snapshot),
        stage_name=stage_name,
        timer=PipelineTimer(),
    )

    try:
        graph = pipeline.build()
        output = await graph.run(ctx)

        stage_output = output.get(stage_name)
        if stage_output:
            success = stage_output.status.value == "ok"
            output_status = stage_output.status.value
            output_data = stage_output.data if stage_output else {}
            output_error = str(stage_output.error) if stage_output and stage_output.error else None
        else:
            success = False
            output_status = "unknown"
            output_data = {}
            output_error = "Stage not found in output"

        return {
            "test_id": test_id,
            "success": success,
            "status": output_status,
            "data": output_data,
            "error": output_error,
        }

    except Exception as e:
        return {
            "test_id": test_id,
            "success": False,
            "status": "error",
            "data": {},
            "error": str(e),
        }


async def run_bom_tests() -> list[dict[str, Any]]:
    """Run BOM handling tests."""
    pipeline = create_bom_pipeline()
    results = []

    for case in EncodingMockData.bom_test_cases():
        result = await run_encoding_test(
            pipeline,
            case["raw_bytes"].decode("utf-8", errors="replace"),
            "bom_strip",
        )
        result["description"] = case["description"]
        result["expected"] = case["expected_content"]
        results.append(result)

    return results


async def run_mojibake_tests() -> list[dict[str, Any]]:
    """Run mojibake repair tests."""
    pipeline = create_mojibake_pipeline()
    results = []

    for case in EncodingMockData.mojibake_test_cases():
        result = await run_encoding_test(
            pipeline,
            case["corrupted_bytes"],
            "mojibake_repair",
        )
        result["description"] = case["description"]
        result["expected_repair"] = case["expected_repaired"]
        results.append(result)

    return results


async def run_surrogate_tests() -> list[dict[str, Any]]:
    """Run surrogate pair validation tests."""
    pipeline = create_surrogate_pipeline()
    results = []

    for case in EncodingMockData.surrogate_pair_test_cases():
        # For JSON strings, wrap in a JSON object for testing
        test_input = f'{{"test": {case["json_string"]}}}'

        result = await run_encoding_test(
            pipeline,
            test_input,
            "surrogate_validate",
        )
        result["description"] = case["description"]
        result["should_parse"] = case["should_parse"]
        results.append(result)

    return results


async def run_charset_detection_tests() -> list[dict[str, Any]]:
    """Run charset detection tests."""
    pipeline = create_bom_pipeline()
    results = []

    for case in EncodingMockData.charset_detection_test_cases():
        result = await run_encoding_test(
            pipeline,
            case["input"],
            "encoding_detect",
        )
        result["description"] = case["description"]
        result["expected_detection"] = case["expected_detection"]
        results.append(result)

    return results


async def run_encoding_conversion_tests() -> list[dict[str, Any]]:
    """Run encoding conversion tests."""
    results = []

    for case in EncodingMockData.encoding_conversion_test_cases():
        pipeline = create_encoding_conversion_pipeline(
            target_encoding=case["target_encoding"],
            source_encoding=case.get("source_encoding"),
        )

        result = await run_encoding_test(
            pipeline,
            case["input_text"],
            "encoding_convert",
        )
        result["description"] = case["description"]
        result["expected_success"] = case["expected_success"]
        results.append(result)

    return results


async def run_json_encoding_tests() -> list[dict[str, Any]]:
    """Run JSON encoding tests."""
    pipeline = create_json_encoding_pipeline()
    results = []

    for case in EncodingMockData.json_encoding_test_cases():
        result = await run_encoding_test(
            pipeline,
            case.get("json_string", case.get("json_bytes", "")),
            "json_parse",
        )
        result["description"] = case["description"]
        result["should_parse"] = case["should_parse"]
        results.append(result)

    return results


# =============================================================================
# Main
# =============================================================================

async def main():
    """Run all encoding tests."""
    print("TRANSFORM-006 Encoding Tests")
    print("=" * 60)

    # BOM Tests
    print("\nRunning BOM tests...")
    bom_results = await run_bom_tests()
    bom_passed = sum(1 for r in bom_results if r["success"])
    print(f"BOM tests: {bom_passed}/{len(bom_results)} passed")

    # Mojibake Tests
    print("\nRunning mojibake tests...")
    mojibake_results = await run_mojibake_tests()
    mojibake_passed = sum(1 for r in mojibake_results if r["success"])
    print(f"Mojibake tests: {mojibake_passed}/{len(mojibake_results)} passed")

    # Surrogate Tests
    print("\nRunning surrogate tests...")
    surrogate_results = await run_surrogate_tests()
    surrogate_passed = sum(1 for r in surrogate_results if r["success"])
    print(f"Surrogate tests: {surrogate_passed}/{len(surrogate_results)} passed")

    # Charset Detection Tests
    print("\nRunning charset detection tests...")
    charset_results = await run_charset_detection_tests()
    charset_passed = sum(1 for r in charset_results if r["success"])
    print(f"Charset detection tests: {charset_passed}/{len(charset_results)} passed")

    # Encoding Conversion Tests
    print("\nRunning encoding conversion tests...")
    conversion_results = await run_encoding_conversion_tests()
    conversion_passed = sum(1 for r in conversion_results if r["success"])
    print(f"Encoding conversion tests: {conversion_passed}/{len(conversion_results)} passed")

    # JSON Encoding Tests
    print("\nRunning JSON encoding tests...")
    json_results = await run_json_encoding_tests()
    json_passed = sum(1 for r in json_results if r["success"])
    print(f"JSON encoding tests: {json_passed}/{len(json_results)} passed")

    print("\n" + "=" * 60)
    total_passed = sum([
        bom_passed, mojibake_passed, surrogate_passed,
        charset_passed, conversion_passed, json_passed,
    ])
    total_tests = sum([
        len(bom_results), len(mojibake_results), len(surrogate_results),
        len(charset_results), len(conversion_results), len(json_results),
    ])
    print(f"Total: {total_passed}/{total_tests} tests passed")

    return {
        "bom": bom_results,
        "mojibake": mojibake_results,
        "surrogates": surrogate_results,
        "charset": charset_results,
        "conversion": conversion_results,
        "json": json_results,
    }


if __name__ == "__main__":
    asyncio.run(main())
