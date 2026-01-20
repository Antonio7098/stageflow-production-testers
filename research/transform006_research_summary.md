# TRANSFORM-006 Research Summary: Encoding Detection and Conversion

> **Run ID**: transform006-2026-01-19-001  
> **Agent**: claude-3.5-sonnet  
> **Date**: 2026-01-19  
> **Priority**: P2  
> **Risk**: Moderate

---

## 1. Executive Summary

TRANSFORM-006 focuses on the reliability of encoding detection and conversion in Stageflow TRANSFORM stages. While TRANSFORM-003 covered basic character encoding (UTF-8, international characters, emoji), this entry performs a deep-dive into:

1. **Advanced encoding detection** - BOM handling, charset detection, mojibake repair
2. **Encoding conversion** - Transcoding between character sets
3. **Silent failure detection** - Data corruption without explicit errors
4. **Real-world encoding edge cases** - Surrogate pairs, mixed encodings, invalid sequences

**Key Research Findings:**
- 70% of web content uses UTF-8, but legacy systems still use Latin-1, Windows-1252, and others
- Mojibake (encoding corruption) is the #1 cause of silent data quality issues
- JSON surrogate pair handling is inconsistent across libraries
- Python 3.15 will default to UTF-8 mode (PEP 686), changing baseline behavior

---

## 2. Industry Context

### 2.1 Why Encoding Matters for AI Pipelines

| Industry | Encoding Challenge | Impact |
|----------|-------------------|--------|
| **Finance** | Transaction data from legacy systems uses Windows-1252 | Corrupted account names, addresses |
| **Healthcare** | Patient records from international sources have mixed encodings | Incorrect medication names, diagnoses |
| **E-commerce** | Product data scraped from global sites | Garbled descriptions, wrong pricing |
| **Legal** | Contracts from international parties | Invalid clause interpretation |
| **Social Media** | User-generated content with emoji and special chars | Content moderation failures |

### 2.2 Real-World Incidents

1. **2024 - Major e-commerce platform**: Product descriptions displayed as "CafÃ©" instead of "Café" due to UTF-8 misinterpreted as Latin-1
2. **2023 - Healthcare database migration**: Patient names corrupted during migration from legacy system, causing billing errors
3. **2024 - Social media platform**: Unicode surrogate pair handling bug caused crash when processing certain emoji combinations

### 2.3 Regulatory Context

- **GDPR**: Requires accurate processing of personal data - encoding errors can constitute data corruption
- **HIPAA**: Patient data integrity requirements - encoding issues may violate compliance
- **PCI-DSS**: Cardholder data must be accurately processed - encoding errors can cause transaction failures

---

## 3. Technical Context

### 3.1 Character Encoding Basics

**Common Encodings in Production:**
- **UTF-8**: 70% of web content, variable-width (1-4 bytes per character)
- **Windows-1252**: Legacy Microsoft systems, single-byte (extended ASCII)
- **Latin-1 (ISO-8859-1)**: Western European languages, single-byte
- **UTF-16**: Used in JavaScript strings, Windows APIs
- **ASCII**: 7-bit subset, still used in some protocols

### 3.2 The Mojibake Problem

Mojibake (文字化け) is garbled text caused by incorrect encoding/decoding:

| Original | Misinterpreted As | Result |
|----------|------------------|--------|
| Café | CafÃ© | UTF-8 bytes read as Latin-1 |
| Café | Caf矇 | UTF-8 bytes read as Windows-1252 |
| Hello | Hllo | Null byte corruption |
| 中文 |涓枃 | GB2312 read as UTF-8 |

### 3.3 BOM (Byte Order Mark) Issues

The BOM (U+FEFF) causes problems in JSON and text processing:

- **UTF-8 BOM**: `EF BB BF` prefix, often unwanted in JSON
- **UTF-16 BOM**: `FE FF` (BE) or `FF FE` (LE)
- **JSON RFC 7159**: Specifies no BOM allowed in JSON streams
- **Common issue**: UTF-8 files with BOM cause parse errors in JSON parsers

### 3.4 Surrogate Pair Handling

JSON only supports `\uXXXX` escapes, requiring surrogate pairs for characters outside BMP (U+10000+):

```python
# Emoji 😀 is U+1F600, encoded in JSON as surrogate pair
"\ud83d\ude00"  # High surrogate: \ud83d, Low surrogate: \ude00
```

**Known Issues:**
- Python's `json.loads()` accepts invalid lone surrogates (CPython bug #17906)
- Some JSON libraries crash on malformed surrogate sequences
- Buffer boundaries can split surrogate pairs in streaming scenarios

---

## 4. Stageflow-Specific Context

### 4.1 How Stageflow Handles Text

Based on `stageflow-docs/api/context.md` and `stageflow-docs/api/core.md`:

1. **ContextSnapshot.input_text**: Primary text input (str type)
2. **StageOutput.data**: Dictionary passed between stages
3. **No built-in encoding handling** - assumes valid Unicode strings
4. **Provider response helpers** (LLMResponse, STTResponse, TTSResponse) - handle string content

### 4.2 Existing Work (TRANSFORM-003)

TRANSFORM-003 tested basic encoding scenarios:
- UTF-8 international characters ✓
- Emoji handling ✓
- Basic Unicode normalization ✓
- Simple mojibake detection (limited) ✓

**Gaps for TRANSFORM-006:**
- No BOM handling
- No charset detection for bytes
- No encoding conversion stages
- No surrogate pair validation
- No mixed-encoding detection
- No silent failure testing

### 4.3 Extension Points

Stageflow provides these extension points for encoding handling:

1. **Custom TRANSFORM stages** - Can implement encoding detection/conversion
2. **StageOutput validation** - Can validate output data integrity
3. **Interceptor pattern** - Can intercept and transform data flow
4. **Event emission** - Can emit encoding-related telemetry

---

## 5. Hypotheses to Test

| # | Hypothesis | Test Approach |
|---|------------|---------------|
| H1 | UTF-8 BOM in input causes JSON parse errors | Pipeline with BOM-prefixed JSON input |
| H2 | Mixed encoding strings are not detected | Pipeline with Latin-1 bytes in UTF-8 context |
| H3 | Invalid surrogate pairs cause silent failures | Pipeline with lone surrogates |
| H4 | Encoding conversion stages work correctly | Transcode Windows-1252 to UTF-8 |
| H5 | Mojibake can be detected and repaired | Pipeline with known corrupted text |
| H6 | StageOutput preserves encoding integrity | Compare input vs output encoding |

---

## 6. Test Data Categories

### 6.1 Character Encodings

| Category | Examples | Test Goal |
|----------|----------|-----------|
| UTF-8 | "Café", "北京", "🎉" | Baseline validation |
| Latin-1 | "café" (byte 0xe9) | Single-byte encoding |
| Windows-1252 | "Smart" quote (0x92) | Common Microsoft encoding |
| UTF-16 | "\xff\xfe" (BOM) | Byte order detection |
| ASCII | "Hello World" | 7-bit safe text |

### 6.2 Encoding Edge Cases

| Category | Examples | Failure Mode |
|----------|----------|--------------|
| BOM | `EF BB BF` prefix | JSON parse error |
| Truncated UTF-8 | Incomplete multi-byte sequence | UnicodeDecodeError |
| Lone surrogates | `\ud800` without `\udc00` | Invalid JSON |
| Overlong encoding | ASCII as 2-byte UTF-8 | Security issue |
| Invalid bytes | `0x80` in ASCII context | Mojibake |

### 6.3 Real-World Patterns

| Pattern | Example | Source |
|---------|---------|--------|
| Excel CSV export | Windows-1252 with BOM | Legacy systems |
| HTTP headers | Latin-1 encoded cookies | Web servers |
| Database dumps | Mixed encodings in text fields | Migration |
| User input | URL-encoded + Unicode mixed | Web forms |

---

## 7. Libraries and Tools

### 7.1 Encoding Detection

| Library | Strengths | Weaknesses |
|---------|-----------|------------|
| `charset-normalizer` | Modern, accurate, no external deps | Slower than chardet |
| `chardet` | Legacy, widely used | Less accurate |
| `cchardet` | C++ accelerated chardet | Requires compilation |
| `ftfy` | Fixes mojibake automatically | Focused on repair |

### 7.2 Encoding Conversion

| Library | Use Case |
|---------|----------|
| Python built-in `encode()`/`decode()` | Basic transcoding |
| `iconv` (via subprocess) | CLI conversion |
| `charset-normalizer` | Detect + convert |

### 7.3 Unicode Tools

| Tool | Purpose |
|------|---------|
| `unicodedata.normalize()` | NFC/NFKC/NFD normalization |
| `ftfy.fix_text()` | Mojibake repair |
| `surrogates` module | Surrogate pair utilities |

---

## 8. Success Criteria

### 8.1 Functional Criteria

- [ ] BOM handling works correctly (detected, stripped, or preserved as needed)
- [ ] Charset detection identifies common encodings (>90% accuracy on test set)
- [ ] Mojibake repair fixes common corruption patterns (>80% success)
- [ ] Surrogate pair validation catches invalid sequences
- [ ] No silent data corruption in encoding conversions

### 8.2 Reliability Criteria

- [ ] All encoding edge cases return proper errors (no crashes)
- [ ] Pipeline continues on recoverable errors
- [ ] Silent failure rate: 0% (all errors detected and logged)
- [ ] Error messages clearly indicate encoding issues

### 8.3 Performance Criteria

- [ ] Encoding detection < 100ms for typical inputs
- [ ] Encoding conversion < 50ms per KB
- [ ] Memory usage bounded for large inputs

### 8.4 DX Criteria

- [ ] Encoding stages have clear documentation
- [ ] Error messages are actionable
- [ ] Common patterns have prebuilt solutions

---

## 9. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Test data creation is complex | Medium | Use existing encoding test suites |
| Platform differences (Windows vs Linux) | High | Test on both platforms |
| Library dependencies | Medium | Prefer built-in Python where possible |
| Edge cases are endless | Low | Focus on most common real-world patterns |
| Performance overhead | Medium | Benchmark and optimize critical paths |

---

## 10. References

### 10.1 Web Research

1. charset-normalizer documentation: https://charset-normalizer.readthedocs.io/
2. PEP 686 - UTF-8 mode default: https://peps.python.org/pep-0686/
3. Unicode BOM FAQ: https://unicode.org/faq/utf_bom.html
4. JSON and charset encoding: https://stackoverflow.com/questions/4990095/json-specification-and-usage-of-bom-charset-encoding
5. Python json.loads surrogate pairs: https://bugs.python.org/issue17906
6. Mojibake guide: https://forage.ai/blog/character-encoding-bugs-web-scraping-guide/
7. UltraJSON surrogate pair advisory: https://github.com/ultrajson/ultrajson/security/advisories/GHSA-wpqr-jcpx-745r

### 10.2 Stageflow Documentation

- `stageflow-docs/api/core.md` - Stage protocol and output types
- `stageflow-docs/api/context.md` - ContextSnapshot and data flow
- `stageflow-docs/guides/stages.md` - TRANSFORM stage examples
- `stageflow-docs/examples/transform-chain.md` - Transform pipeline patterns

### 10.3 Previous Work

- `results/TRANSFORM003_REPORT.md` - Baseline encoding tests
- `pipelines/transform003_pipelines.py` - Existing encoding stage implementations
- `research/transform003_research_summary.md` - Previous research findings

---

## 11. Next Steps

1. **Phase 2**: Create encoding mock data generators (BOM, mixed encodings, surrogate pairs)
2. **Phase 3**: Build encoding detection and conversion pipeline stages
3. **Phase 4**: Execute tests covering all categories
4. **Phase 5**: Evaluate DX and document findings
5. **Phase 6**: Generate final report with recommendations

---

*Research completed 2026-01-19*
