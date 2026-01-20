"""Format-induced misinterpretation test pipelines for TRANSFORM-003.

This module contains test pipelines to verify Stageflow's handling of:
- Date format parsing
- Number format handling  
- Character encoding
- Structured output parsing from LLM stages
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from stageflow import (
    Pipeline,
    StageContext,
    StageKind,
    StageOutput,
    PipelineTimer,
)
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow.helpers import LLMResponse
from stageflow.stages import StageInputs


# =============================================================================
# Test Data Generators
# =============================================================================

class FormatTestData:
    """Generator for format-induced misinterpretation test data."""

    @staticmethod
    def generate_dates() -> List[Dict[str, Any]]:
        """Generate date strings in various formats."""
        base_date = datetime(2023, 10, 5, 14, 48, 0, tzinfo=timezone.utc)

        return [
            # ISO 8601 standard formats
            {"value": "2023-10-05", "description": "Date only"},
            {"value": "2023-10-05T14:48:00Z", "description": "With Z timezone"},
            {"value": "2023-10-05T14:48:00+00:00", "description": "With explicit offset"},
            {"value": "2023-10-05T14:48:00.000Z", "description": "With milliseconds"},
            {"value": "2023-10-05T14:48:00.000000Z", "description": "With microseconds"},

            # RFC 2822 formats
            {"value": "Thu, 05 Oct 2023 14:48:00 GMT", "description": "RFC 2822"},

            # US formats (MM/DD/YYYY)
            {"value": "10/05/2023", "description": "US date format"},
            {"value": "10-05-2023", "description": "US date with dashes"},
            {"value": "10.05.2023", "description": "US date with dots"},

            # EU formats (DD/MM/YYYY)
            {"value": "05/10/2023", "description": "EU date format"},
            {"value": "05-10-2023", "description": "EU date with dashes"},

            # Ambiguous formats
            {"value": "01/02/2023", "description": "AMBIGUOUS: Jan 2 or Feb 1?"},
            {"value": "04/05/2023", "description": "AMBIGUOUS: Apr 5 or May 4?"},

            # Human-readable formats
            {"value": "October 5, 2023", "description": "Long month format"},
            {"value": "5 Oct 2023", "description": "Short month format"},
            {"value": "2023/10/05", "description": "YYYY/MM/DD format"},

            # Relative dates (should be handled specially)
            {"value": "yesterday", "description": "Relative date"},
            {"value": "next Tuesday", "description": "Vague relative date"},
        ]

    @staticmethod
    def generate_numbers() -> List[Dict[str, Any]]:
        """Generate number strings in various formats."""
        return [
            # Standard formats
            {"value": "42", "description": "Simple integer"},
            {"value": "-17", "description": "Negative integer"},
            {"value": "3.14159", "description": "Decimal"},
            {"value": "0.001", "description": "Small decimal"},

            # US number format (period as decimal, comma as thousands)
            {"value": "1,234.56", "description": "US thousands separator"},
            {"value": "1,234,567.89", "description": "US millions"},

            # EU number format (comma as decimal, period as thousands)
            {"value": "1.234,56", "description": "EU format"},
            {"value": "1.234.567,89", "description": "EU millions"},

            # Scientific notation
            {"value": "1.23e-4", "description": "Scientific notation"},
            {"value": "6.022e23", "description": "Large scientific"},

            # Currency (should be parsed as number)
            {"value": "$1,234.56", "description": "US currency"},
            {"value": "€1.234,56", "description": "EU currency"},
            {"value": "£1,000", "description": "UK currency"},

            # Percentage
            {"value": "42.5%", "description": "Percentage"},
            {"value": "100%", "description": "Full percentage"},

            # Fractional words
            {"value": "one and a half", "description": "Words fraction"},
            {"value": "two point five", "description": "Words decimal"},

            # Edge cases
            {"value": "0", "description": "Zero"},
            {"value": "-0", "description": "Negative zero"},
            {"value": ".5", "description": "Leading decimal"},
            {"value": "5.", "description": "Trailing decimal"},
            {"value": "99999999999999999999", "description": "Very large integer"},
            {"value": "0.00000000000000000001", "description": "Very small decimal"},

            # Floating point precision edge case
            {"value": "0.1", "description": "Floating point edge 1"},
            {"value": "0.2", "description": "Floating point edge 2"},
            {"value": "0.3", "description": "Floating point edge 3"},
        ]

    @staticmethod
    def generate_encoded_text() -> List[Dict[str, Any]]:
        """Generate text with various encoding challenges."""
        return [
            # Standard UTF-8
            {"value": "Hello, World!", "description": "Plain ASCII"},

            # International characters
            {"value": "Café", "description": "French accented"},
            {"value": "naïve", "description": "Umlaut"},
            {"value": "résumé", "description": "Accented resume"},
            {"value": "北京", "description": "Chinese characters"},
            {"value": "东京", "description": "Japanese characters"},
            {"value": "서울", "description": "Korean characters"},
            {"value": "Москва", "description": "Cyrillic"},
            {"value": "Αθήνα", "description": "Greek"},
            {"value": "مرحبا", "description": "Arabic RTL"},
            {"value": "שלום", "description": "Hebrew RTL"},

            # Emoji
            {"value": "Hello 🌍", "description": "Emoji"},
            {"value": "🎉 Happy Birthday! 🎂", "description": "Multiple emoji"},

            # Special characters
            {"value": "Line1\nLine2\tTabbed", "description": "Newlines and tabs"},
            {"value": "Quotes: \"double\" and 'single'", "description": "Quote types"},
            {"value": "Backslash: \\path\\to\\file", "description": "Backslashes"},

            # Potentially problematic
            {"value": "\x00Null byte", "description": "Null byte"},
            {"value": "Tab\t\tMultiple", "description": "Multiple tabs"},
        ]

    @staticmethod
    def generate_structured_outputs() -> List[Dict[str, Any]]:
        """Generate various structured output formats from LLMs."""
        base_data = {"name": "Test", "amount": 42.50, "date": "2023-10-05"}

        outputs = [
            # Standard JSON
            {
                "value": json.dumps(base_data),
                "description": "Standard JSON",
                "format": "json"
            },

            # JSON with extra whitespace
            {
                "value": json.dumps(base_data, indent=2),
                "description": "Pretty-printed JSON",
                "format": "json"
            },

            # JSON with trailing comma (invalid JSON but common from LLMs)
            {
                "value": json.dumps(base_data)[:-1] + ",}",
                "description": "JSON with trailing comma",
                "format": "json-trailing-comma"
            },

            # JSON5 (ES5 extension, allows trailing commas, comments)
            {
                "value": """{
                    name: "Test",
                    amount: 42.50,
                    date: "2023-10-05",
                }""",
                "description": "JSON5 without quotes",
                "format": "json5"
            },

            # Markdown code block (LLMs often output this way)
            {
                "value": """```json
{"name": "Test", "amount": 42.50, "date": "2023-10-05"}
```""",
                "description": "JSON in markdown code block",
                "format": "markdown-json"
            },

            # YAML-like (LLMs sometimes output this)
            {
                "value": """name: Test
amount: 42.50
date: 2023-10-05""",
                "description": "YAML-like format",
                "format": "yaml"
            },

            # Single-quoted JSON (invalid but occurs)
            {
                "value": base_data | {"name": "Test"},
                "description": "Single quotes (invalid)",
                "format": "invalid-quotes"
            },

            # With extra fields
            {
                "value": json.dumps({**base_data, "extra": "field"}),
                "description": "JSON with extra field",
                "format": "json-extended"
            },

            # Nested structure
            {
                "value": json.dumps({
                    "user": base_data,
                    "metadata": {"source": "test", "version": 1}
                }),
                "description": "Nested JSON",
                "format": "json-nested"
            },

            # Array format
            {
                "value": json.dumps([base_data]),
                "description": "JSON array",
                "format": "json-array"
            },
        ]
        return outputs


# =============================================================================
# TRANSFORM Stages for Testing
# =============================================================================

class DateParseStage:
    """TRANSFORM stage that parses date strings."""

    name = "date_parse"
    kind = StageKind.TRANSFORM

    def __init__(self, expected_format: str = "ISO8601") -> None:
        self.expected_format = expected_format

    async def execute(self, ctx: StageContext) -> StageOutput:
        date_str = ctx.snapshot.input_text or ""
        if not date_str:
            return StageOutput.fail(error="No date string provided")

        # Try to parse the date
        parsed = self._parse_date(date_str)
        if parsed is None:
            return StageOutput.fail(error=f"Could not parse date: {date_str}")

        return StageOutput.ok(
            original=date_str,
            parsed=parsed.isoformat(),
            timestamp=int(parsed.timestamp()),
            year=parsed.year,
            month=parsed.month,
            day=parsed.day,
        )

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string with various formats."""
        import dateutil.parser

        try:
            return dateutil.parser.parse(date_str)
        except (ValueError, TypeError):
            return None


class NumberParseStage:
    """TRANSFORM stage that parses number strings."""

    name = "number_parse"
    kind = StageKind.TRANSFORM

    def __init__(self, locale: str = "en_US") -> None:
        self.locale = locale

    async def execute(self, ctx: StageContext) -> StageOutput:
        num_str = ctx.snapshot.input_text or ""
        if not num_str:
            return StageOutput.fail(error="No number string provided")

        parsed = self._parse_number(num_str)
        if parsed is None:
            return StageOutput.fail(error=f"Could not parse number: {num_str}")

        return StageOutput.ok(
            original=num_str,
            parsed=float(parsed),
            is_integer=parsed == int(parsed),
            is_negative=parsed < 0,
        )

    def _parse_number(self, num_str: str) -> Optional[float]:
        """Parse number string with various formats."""
        import locale as locale_module

        # Clean the string
        cleaned = num_str.strip()

        # Try direct float parsing first (for standard formats)
        try:
            return float(cleaned)
        except ValueError:
            pass

        # Try locale-aware parsing
        try:
            saved_locale = locale_module.getlocale(locale_module.LC_ALL)
            locale_module.setlocale(locale_module.LC_ALL, self.locale)

            # Handle currency symbols
            for char in "$€£¥":
                cleaned = cleaned.replace(char, "")

            # Handle thousands separators based on locale
            if self.locale.startswith("en"):
                cleaned = cleaned.replace(",", "")
            else:
                cleaned = cleaned.replace(".", "").replace(",", ".")

            result = float(cleaned)
            locale_module.setlocale(locale_module.LC_ALL, saved_locale)
            return result
        except (ValueError, locale_module.Error):
            pass

        return None


class EncodingDetectStage:
    """TRANSFORM stage that detects and handles encoding."""

    name = "encoding_detect"
    kind = StageKind.TRANSFORM

    async def execute(self, ctx: StageContext) -> StageOutput:
        text = ctx.snapshot.input_text or ""
        if not text:
            return StageOutput.skip(reason="No text provided")

        # Try to detect encoding and normalize
        detected, normalized = self._detect_and_normalize(text)

        return StageOutput.ok(
            original=text,
            detected_encoding=detected,
            normalized=normalized,
            is_ascii=text.isascii() if text else True,
            length_original=len(text),
            length_normalized=len(normalized),
        )

    def _detect_and_normalize(self, text: str) -> tuple[str, str]:
        """Detect encoding and normalize text."""
        import unicodedata

        # Try to detect mojibake
        if "Ã©" in text or "Â" in text:
            # Likely UTF-8 misinterpreted as Latin-1
            try:
                fixed = text.encode("latin-1").decode("utf-8")
                return "latin-1-misinterpreted-utf8", fixed
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass

        # Normalize Unicode
        normalized = unicodedata.normalize("NFC", text)
        return "detected", normalized


class StructuredParseStage:
    """TRANSFORM stage that parses structured output from LLM."""

    name = "structured_parse"
    kind = StageKind.TRANSFORM

    async def execute(self, ctx: StageContext) -> StageOutput:
        raw_output = ctx.snapshot.input_text or ""
        if not raw_output:
            return StageOutput.fail(error="No structured output provided")

        parsed, format_detected = self._parse_structured(raw_output)

        if parsed is None:
            return StageOutput.fail(
                error=f"Could not parse structured output (format: {format_detected})",
                data={"raw": raw_output[:100], "format": format_detected}
            )

        return StageOutput.ok(
            raw=raw_output,
            parsed=parsed,
            format_detected=format_detected,
            is_valid=True,
        )

    def _parse_structured(self, raw_output: str) -> tuple[Optional[Dict], str]:
        """Parse structured output with format detection."""
        # Detect markdown code block
        if raw_output.startswith("```") and "```" in raw_output[3:]:
            # Extract content from code block
            lines = raw_output.split("\n")
            if len(lines) >= 2:
                # Find the closing ```
                for i, line in enumerate(lines[1:], start=1):
                    if line.strip() == "```":
                        content = "\n".join(lines[1:i])
                        # Remove "json" or other language specifier
                        if content.startswith("json"):
                            content = content[4:].strip()
                        raw_output = content
                        break
            format_type = "markdown-code-block"
        else:
            format_type = "plain"

        # Try JSON5 (allows trailing commas, unquoted keys)
        try:
            import json5
            parsed = json5.loads(raw_output)
            format_type = "json5"
            return parsed, format_type
        except ImportError:
            pass
        except (ValueError, SyntaxError):
            pass

        # Try standard JSON
        try:
            parsed = json.loads(raw_output)
            format_type = "json"
            return parsed, format_type
        except json.JSONDecodeError:
            pass

        # Try fixing trailing comma
        try:
            fixed = raw_output.rstrip(",") + "}"
            parsed = json.loads(fixed)
            format_type = "json-with-trailing-comma"
            return parsed, format_type
        except json.JSONDecodeError:
            pass

        return None, format_type


# =============================================================================
# Pipeline Builders
# =============================================================================

def create_date_format_pipeline() -> Pipeline:
    """Create a pipeline to test date format handling."""
    return (
        Pipeline()
        .with_stage("date_parse", DateParseStage(), StageKind.TRANSFORM)
    )


def create_number_format_pipeline() -> Pipeline:
    """Create a pipeline to test number format handling."""
    return (
        Pipeline()
        .with_stage("number_parse", NumberParseStage(), StageKind.TRANSFORM)
    )


def create_encoding_pipeline() -> Pipeline:
    """Create a pipeline to test encoding handling."""
    return (
        Pipeline()
        .with_stage("encoding_detect", EncodingDetectStage(), StageKind.TRANSFORM)
    )


def create_structured_parse_pipeline() -> Pipeline:
    """Create a pipeline to test structured output parsing."""
    return (
        Pipeline()
        .with_stage("structured_parse", StructuredParseStage(), StageKind.TRANSFORM)
    )


def create_comprehensive_format_pipeline() -> Pipeline:
    """Create a comprehensive format handling pipeline."""
    return (
        Pipeline()
        .with_stage("date_parse", DateParseStage(), StageKind.TRANSFORM)
        .with_stage(
            "number_parse",
            NumberParseStage(),
            StageKind.TRANSFORM,
            dependencies=["date_parse"],
        )
        .with_stage(
            "encoding_detect",
            EncodingDetectStage(),
            StageKind.TRANSFORM,
            dependencies=["number_parse"],
        )
        .with_stage(
            "structured_parse",
            StructuredParseStage(),
            StageKind.TRANSFORM,
            dependencies=["encoding_detect"],
        )
    )


# =============================================================================
# Test Runner
# =============================================================================

async def run_format_test(
    pipeline: Pipeline,
    test_data: List[Dict[str, Any]],
    stage_name: str = "test",
) -> List[Dict[str, Any]]:
    """Run format tests with the given pipeline and data."""
    results = []

    for item in test_data:
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
            topology="format_test",
            execution_mode="test",
            input_text=item["value"],
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

            # Output is dict with stage names as keys
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

            results.append({
                "test_id": test_id,
                "description": item["description"],
                "input": item["value"],
                "success": success,
                "output": {
                    "status": output_status,
                    "data": output_data,
                    "error": output_error,
                },
            })

        except Exception as e:
            # Stage failed with an exception - this is expected for format errors
            # The error message is the "result" of the format parsing failure
            error_msg = str(e)
            # Check if this is a Stageflow execution error
            if "Stage" in error_msg and "failed" in error_msg:
                # Extract the actual error from the exception message
                # Format: "Stage 'xxx' failed: yyy"
                success = False
                output_status = "failed"
                # Try to extract the actual error message
                if "failed:" in error_msg:
                    output_error = error_msg.split("failed:")[-1].strip()
                else:
                    output_error = error_msg
                output_data = {}
            else:
                success = False
                output_status = "error"
                output_error = error_msg
                output_data = {}

            results.append({
                "test_id": test_id,
                "description": item["description"],
                "input": item["value"],
                "success": success,
                "output": {
                    "status": output_status,
                    "data": output_data,
                    "error": output_error,
                },
            })

    return results


if __name__ == "__main__":
    async def main():
        # Test date parsing
        print("Testing date parsing...")
        date_pipeline = create_date_format_pipeline()
        date_results = await run_format_test(
            date_pipeline,
            FormatTestData.generate_dates(),
            "date_parse"
        )
        print(f"Date parsing: {sum(1 for r in date_results if r['success'])}/{len(date_results)}")

        # Test number parsing
        print("\nTesting number parsing...")
        num_pipeline = create_number_format_pipeline()
        num_results = await run_format_test(
            num_pipeline,
            FormatTestData.generate_numbers(),
            "number_parse"
        )
        print(f"Number parsing: {sum(1 for r in num_results if r['success'])}/{len(num_results)}")

        # Test encoding detection
        print("\nTesting encoding detection...")
        encoding_pipeline = create_encoding_pipeline()
        encoding_results = await run_format_test(
            encoding_pipeline,
            FormatTestData.generate_encoded_text(),
            "encoding_detect"
        )
        print(f"Encoding detection: {sum(1 for r in encoding_results if r['success'])}/{len(encoding_results)}")

        # Test structured output parsing
        print("\nTesting structured output parsing...")
        struct_pipeline = create_structured_parse_pipeline()
        struct_results = await run_format_test(
            struct_pipeline,
            FormatTestData.generate_structured_outputs(),
            "structured_parse"
        )
        print(f"Structured parsing: {sum(1 for r in struct_results if r['success'])}/{len(struct_results)}")

    asyncio.run(main())
