# GUARD-003 Research Summary: PII/PHI Redaction Accuracy

> **Mission ID**: GUARD-003  
> **Target**: PII/PHI redaction accuracy (>99% recall)  
> **Priority**: P0  
> **Risk**: Severe  
> **Date**: January 20, 2026

---

## 1. Industry Context

### 1.1 Regulatory Requirements

**HIPAA (Health Insurance Portability and Accountability Act)**:
- Requires de-identification of Protected Health Information (PHI)
- Two safe harbor methods: Expert Determination or Safe Harbor
- Safe Harbor requires removal of 18 identifiers
- HIPAA violations: $100-$50,000 per violation, up to $1.5M annually

**GDPR (General Data Protection Regulation)**:
- Right to erasure and data minimization
- Pseudonymization requirements
- Fines up to €20M or 4% of global revenue

**PCI-DSS (Payment Card Industry Data Security Standard)**:
- Cardholder data protection requirements
- PAN masking and truncation requirements

### 1.2 Industry Pain Points

1. **Recall vs Precision Trade-off**:
   - False negatives (missed PII) are catastrophic (data breaches, compliance violations)
   - False positives (over-redaction) reduce data utility but are less harmful
   - Target: >99% recall, accepting some false positives

2. **Clinical Text Challenges**:
   - Unstructured clinical notes contain dense PHI
   - Medical terminology can mask or resemble PII
   - Family history may contain relative names/dates

3. **Scale Challenges**:
   - High-volume document processing
   - Real-time streaming requirements
   - Multi-language support needs

---

## 2. Technical Context

### 2.1 State-of-the-Art Approaches

| Approach | Strengths | Weaknesses |
|----------|-----------|------------|
| **Rule-based (Regex)** | Fast, deterministic, no FP on unseen patterns | High FN on variations, maintenance burden |
| **NER Models (spaCy, HuggingFace)** | Good generalization, context-aware | Training data dependent, misses unusual formats |
| **LLM-based (GPT, Llama)** | Context understanding, handles edge cases | Latency, cost, potential for hallucination |
| **Hybrid Approaches** | Combines strengths, best results | Complexity, maintenance |

### 2.2 Key Research Findings

**From John Snow Labs Research (2025)**:
- Open-source LLM-based de-identification misses over 50% of clinical PHI
- GLiNER and OpenPipe perform well on general text but fail on clinical data
- Hybrid approaches outperform single methods

**From RedactOR Paper (Oracle Health & AI, 2025)**:
- LLM-powered framework for clinical data de-identification
- Existing methods suffer from recall errors
- New approaches needed for better precision/recall balance

**From arXiv Research on Text Sanitization**:
- Current sanitization evaluated only on explicit identifiers
- Nuanced textual markers can lead to re-identification
- Need comprehensive evaluation beyond surface-level

### 2.3 Common PII/PHI Categories

| Category | Examples | Detection Difficulty |
|----------|----------|---------------------|
| **Direct Identifiers** | Name, SSN, Phone, Email, Address | Medium |
| **Medical Identifiers** | MRN, Medicare ID, Health Plan ID | High |
| **Geographic** | City, State, ZIP (with <20k population) | Medium |
| **Dates** | Birth, Admission, Discharge, Death | Low |
| **Ages > 89** | Any age over 89 (special handling) | Medium |
| **Contact** | Phone, Fax, Email, IP Address | Low |
| **Web Identifiers** | URLs, Domain, IP addresses | Low |
| **Biometric** | Fingerprints, photos, voice prints | High |
| **Device Identifiers** | Device serial numbers, MAC | High |

### 2.4 Known Failure Modes

1. **Format Variations**:
   - SSN: XXX-XX-XXXX, XXXXXXXXX, (XXX) XXX-XXXX
   - Phone: Multiple international formats
   - Email: Case sensitivity, special characters

2. **Context Blindness**:
   - Names in quotes that aren't PII
   - Fictional character names in text
   - Common words that are also names

3. **Composite Data**:
   - Names embedded in addresses
   - Dates combined with names
   - IDs in URLs or file paths

4. **Adversarial Obfuscation**:
   - Intentional misspellings
   - Leetspeak substitutions
   - Unicode lookalikes (homoglyphs)

---

## 3. Stageflow-Specific Context

### 3.1 Relevant Stageflow APIs

Based on `stageflow-docs/guides/governance.md`:

```python
from stageflow.helpers import (
    GuardrailStage,
    PIIDetector,
    GuardrailConfig,
)
```

**PIIDetector Interface**:
```python
PIIDetector(
    redact=True,
    redaction_char="*",
    detect_types={"email", "phone", "ssn"},
)
```

### 3.2 Guard Stage Architecture

GUARD stages run as policy enforcement barriers:
- **Input Guard**: Filters PII before LLM processing
- **Output Guard**: Redacts PII from LLM outputs
- **Both stages** critical for end-to-end protection

### 3.3 Integration Points

From `stageflow-docs/guides/interceptors.md`:
- Can use interceptors for cross-cutting redaction
- Event sinks for audit logging
- Correlation IDs for trace linking

---

## 4. Hypotheses to Test

| # | Hypothesis | Test Approach |
|---|------------|---------------|
| H1 | Standard NER models achieve <95% recall on clinical PHI | Compare detection rates on clinical dataset |
| H2 | Regex-based detection has higher precision but lower recall than ML | Compare hybrid approaches |
| H3 | Multi-pass detection (regex + NER + LLM) improves recall | Test incremental improvement |
| H4 | Context-aware rules reduce false positives without increasing FNs | Evaluate precision/recall tradeoff |
| H5 | Adversarial inputs (obfuscation, typos) significantly reduce recall | Test with adversarial dataset |
| H6 | >99% recall requires combining multiple detection methods | Verify if any single method can achieve target |

---

## 5. Success Criteria Definition

### 5.1 Primary Metrics

| Metric | Target | Critical Threshold |
|--------|--------|-------------------|
| **Recall** | >99% | >97% minimum |
| **Precision** | >80% (acceptable) | >60% minimum |
| **F1 Score** | >89% | >75% minimum |
| **False Negative Rate** | <1% | <3% maximum |

### 5.2 Silent Failure Detection

Critical silent failures to detect:
1. PII that passes through without any redaction
2. PII partially redacted (first 3 chars only)
3. PII detected but wrong entity type
4. Context-dependent PII missed due to lack of awareness

### 5.3 Test Categories

1. **Baseline Tests** (Happy path):
   - Standard PII formats
   - Clear entity boundaries
   - Single PII type per instance

2. **Edge Cases** (Boundary conditions):
   - Unusual formats
   - Multiple PII in single text
   - PII in complex contexts

3. **Adversarial Tests** (Security testing):
   - Obfuscated PII
   - Typos and misspellings
   - Unicode homoglyphs
   - Context-based evasion

4. **Scale Tests** (Performance):
   - Large document processing
   - High-throughput scenarios
   - Memory usage bounds

---

## 6. Implementation Plan

### Phase 1: Mock Service Creation
- Create PII detection mock with configurable recall rates
- Build test data generators for all categories
- Implement pipeline stages for input/output redaction

### Phase 2: Pipeline Construction
- Baseline pipeline for normal operation
- Adversarial pipeline for security testing
- Chaos pipeline for failure injection
- Stress pipeline for performance testing

### Phase 3: Test Execution
- Run all test categories
- Capture detailed metrics
- Analyze silent failures

### Phase 4: Evaluation & Reporting
- DX evaluation
- Final report generation
- Recommendations for Stageflow

---

## 7. References

1. John Snow Labs: "How Good Are Open-Source LLM-Based De-identification Tools in a Medical Context?" (2025)
2. RedactOR: "An LLM-Powered Framework for Automatic Clinical Data De-Identification" (Oracle Health & AI, 2025)
3. HHS: "Guidance Regarding Methods for De-identification of PHI" (2023)
4. Microsoft Presidio: PII Detection and Anonymization Framework
5. OpenPipe: PII Redaction Library (GitHub)
6. Protecto AI: "Comparing Best NER Models for PII Identification" (2025)
7. arXiv: "A False Sense of Privacy: Evaluating Textual Data Sanitization" (2025)
8. arXiv: "PRvL: Quantifying the Capabilities and Risks of LLMs for PII Redaction" (2025)

---

*Research completed: January 20, 2026*
