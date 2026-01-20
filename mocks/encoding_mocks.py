"""Encoding detection and conversion mock data for TRANSFORM-006.

This module provides comprehensive test data for encoding scenarios:
- BOM (Byte Order Mark) handling
- Character set detection
- Mojibake patterns
- Surrogate pairs
- Mixed encodings
- Invalid byte sequences
"""

from __future__ import annotations

from typing import Any


class EncodingMockData:
    """Generator for encoding test data."""

    @staticmethod
    def bom_test_cases() -> list[dict[str, Any]]:
        """Test cases for BOM handling."""
        return [
            {
                "description": "UTF-8 BOM prefix",
                "raw_bytes": b'\xef\xbb\xbf{"key": "value"}',
                "expected_encoding": "utf-8-bom",
                "expected_content": '{"key": "value"}',
                "should_strip_bom": True,
            },
            {
                "description": "UTF-16 BE BOM",
                "raw_bytes": b'\xfe\xff' + '{"key": "value"}'.encode('utf-16-be'),
                "expected_encoding": "utf-16-be",
                "expected_content": '{"key": "value"}',
                "should_detect_bom": True,
            },
            {
                "description": "UTF-16 LE BOM",
                "raw_bytes": b'\xff\xfe' + '{"key": "value"}'.encode('utf-16-le'),
                "expected_encoding": "utf-16-le",
                "expected_content": '{"key": "value"}',
                "should_detect_bom": True,
            },
            {
                "description": "UTF-32 BE BOM",
                "raw_bytes": b'\x00\x00\xfe\xff' + '{"key": "value"}'.encode('utf-32-be'),
                "expected_encoding": "utf-32-be",
                "expected_content": '{"key": "value"}',
                "should_detect_bom": True,
            },
            {
                "description": "UTF-32 LE BOM",
                "raw_bytes": b'\xff\xfe\x00\x00' + '{"key": "value"}'.encode('utf-32-le'),
                "expected_encoding": "utf-32-le",
                "expected_content": '{"key": "value"}',
                "should_detect_bom": True,
            },
            {
                "description": "No BOM (plain UTF-8)",
                "raw_bytes": b'{"key": "value"}',
                "expected_encoding": "utf-8",
                "expected_content": '{"key": "value"}',
                "should_strip_bom": False,
            },
        ]

    @staticmethod
    def mojibake_test_cases() -> list[dict[str, Any]]:
        """Test cases for mojibake detection and repair."""
        return [
            {
                "description": "UTF-8 bytes misinterpreted as Latin-1 (Cafe)",
                "original": "Cafe",
                "corrupted_bytes": "CafÃ©".encode("utf-8").decode("latin-1"),
                "encoding_chain": "utf-8->latin-1",
                "expected_repaired": "Cafe",
            },
            {
                "description": "UTF-8 bytes misinterpreted as Windows-1252",
                "original": "Cafe",
                "corrupted_bytes": "Caf\x82".encode("utf-8").decode("windows-1252"),
                "encoding_chain": "utf-8->windows-1252",
                "expected_repaired": "Cafe",
            },
            {
                "description": "Windows-1252 misinterpreted as UTF-8",
                "original": 'Smart quotes: "test"',
                "corrupted_bytes": 'Smart quotes: \xc2\x93test\xc2\x94'.encode("utf-8").decode("latin-1"),
                "encoding_chain": "windows-1252->utf-8->latin-1",
                "expected_repaired": 'Smart quotes: "test"',
            },
            {
                "description": "Mixed mojibake with multiple characters",
                "original": "Crepe, naive, facade",
                "corrupted_bytes": "Cr\xc3\xaape, na\xc3\xafve, fa\xc3\xa7ade".encode("utf-8").decode("latin-1"),
                "encoding_chain": "utf-8->latin-1",
                "expected_repaired": "Crepe, naive, facade",
            },
            {
                "description": "Chinese characters corrupted",
                "original": "Beijing",
                "corrupted_bytes": "\xe5\x8c\x97\xe4\xba\xac".encode("utf-8").decode("latin-1"),
                "encoding_chain": "utf-8->latin-1",
                "expected_repaired": "Beijing",
            },
        ]

    @staticmethod
    def surrogate_pair_test_cases() -> list[dict[str, Any]]:
        """Test cases for surrogate pair handling."""
        return [
            {
                "description": "Valid emoji (😀) as surrogate pair",
                "json_string": r'"\ud83d\ude00"',
                "should_parse": True,
                "expected_result": "😀",
            },
            {
                "description": "Valid emoji (🎉) as surrogate pair",
                "json_string": r'"\ud83c\udf89"',
                "should_parse": True,
                "expected_result": "🎉",
            },
            {
                "description": "Lone high surrogate (invalid)",
                "json_string": r'"\ud83d"',
                "should_parse": False,
                "expected_error": "lone surrogate",
            },
            {
                "description": "Lone low surrogate (invalid)",
                "json_string": r'"\ude00"',
                "should_parse": False,
                "expected_error": "lone surrogate",
            },
        ]

    @staticmethod
    def charset_detection_test_cases() -> list[dict[str, Any]]:
        """Test cases for character set detection."""
        return [
            {
                "description": "Pure ASCII",
                "input": "Hello, World!",
                "expected_detection": "ascii",
                "confidence": "high",
            },
            {
                "description": "UTF-8 with Western European characters",
                "input": "Cafe resume naive",
                "expected_detection": "utf-8",
                "confidence": "high",
            },
            {
                "description": "UTF-8 with Chinese characters",
                "input": "Beijing Tokyo Seoul",
                "expected_detection": "utf-8",
                "confidence": "high",
            },
            {
                "description": "UTF-8 with emoji",
                "input": "Hello 🎉 World",
                "expected_detection": "utf-8",
                "confidence": "high",
            },
        ]

    @staticmethod
    def encoding_conversion_test_cases() -> list[dict[str, Any]]:
        """Test cases for encoding conversion."""
        return [
            {
                "description": "Windows-1252 to UTF-8",
                "source_encoding": "windows-1252",
                "target_encoding": "utf-8",
                "input_text": 'Smart "test"',
                "expected_success": True,
            },
            {
                "description": "Latin-1 to UTF-8",
                "source_encoding": "latin-1",
                "target_encoding": "utf-8",
                "input_text": "Caf\xe9",
                "expected_success": True,
            },
            {
                "description": "Round-trip UTF-8",
                "source_encoding": "utf-8",
                "target_encoding": "utf-8",
                "input_text": "Cafe Beijing 🎉",
                "expected_success": True,
                "expected_preserved": True,
            },
        ]

    @staticmethod
    def json_encoding_test_cases() -> list[dict[str, Any]]:
        """Test cases for JSON with encoding issues."""
        return [
            {
                "description": "JSON with UTF-8 BOM",
                "json_bytes": b'\xef\xbb\xbf{"key": "value"}',
                "should_parse": True,
                "expected_value": {"key": "value"},
            },
            {
                "description": "JSON with escaped surrogate",
                "json_string": r'{"emoji": "\ud83d\ude00"}',
                "should_parse": True,
                "expected_value": {"emoji": "😀"},
            },
            {
                "description": "JSON with invalid lone surrogate",
                "json_string": r'{"bad": "\ud83d"}',
                "should_parse": False,
                "expected_error": "lone surrogate",
            },
            {
                "description": "JSON with Unicode escape",
                "json_string": r'{"char": "\u00e9"}',
                "should_parse": True,
                "expected_value": {"char": "e"},
            },
        ]


def generate_all_test_data() -> dict[str, list[dict[str, Any]]]:
    """Generate all test data for TRANSFORM-006."""
    return {
        "bom": EncodingMockData.bom_test_cases(),
        "mojibake": EncodingMockData.mojibake_test_cases(),
        "surrogates": EncodingMockData.surrogate_pair_test_cases(),
        "charset_detection": EncodingMockData.charset_detection_test_cases(),
        "encoding_conversion": EncodingMockData.encoding_conversion_test_cases(),
        "json_encoding": EncodingMockData.json_encoding_test_cases(),
    }


if __name__ == "__main__":
    all_data = generate_all_test_data()
    print("TRANSFORM-006 Test Data Summary")
    print("=" * 50)
    for category, cases in all_data.items():
        print(f"{category}: {len(cases)} test cases")
    print("=" * 50)
    print(f"Total: {sum(len(c) for c in all_data.values())} test cases")
