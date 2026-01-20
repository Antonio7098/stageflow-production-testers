# GUARD-002 Research Summary: Jailbreak Detection and Blocking

## Executive Summary

This document summarizes research findings for GUARD-002: Jailbreak detection and blocking, a P0 priority reliability testing task targeting catastrophic risk scenarios in Stageflow's GUARD stage architecture. Jailbreak attacks represent one of the most critical security threats to LLM-powered systems, where adversaries craft prompts designed to bypass safety mechanisms and induce harmful outputs.

**Key Research Findings:**
- Jailbreak attacks can be categorized into 5 major types: optimization-based, LLM-assisted, obfuscation-based, function/tool-based, and multi-turn attacks
- State-of-the-art detection systems (PromptGuard, LlamaGuard, O3) achieve 70-100% detection rates on known attacks
- No single defense is sufficient - multi-layered defense strategies are essential
- The "resilience gap" between attack sophistication and detection capability remains a critical concern

## 1. Industry Context and Regulatory Requirements

### 1.1 Threat Landscape

Jailbreak attacks have evolved from simple prompt manipulation to highly sophisticated multi-turn conversations and automated adversarial generation. According to recent research from CISPA Helmholtz Center, Palo Alto Networks Unit 42, and academic institutions, these attacks pose significant risks across multiple industries:

**Financial Services:**
- Regulatory compliance violations (PCI-DSS, SOX)
- Fraudulent instruction generation
- Manipulation of automated trading systems

**Healthcare:**
- HIPAA violations through improper data handling instructions
- Medical advice manipulation
- Patient data extraction attempts

**Government/Defense:**
- Classified information disclosure attempts
- Manipulation of autonomous systems
- Supply chain security compromises

### 1.2 Regulatory Framework

The regulatory landscape for LLM safety is evolving rapidly:

**OWASP LLM Top 10 2025:**
- LLM01: Prompt Injection ranked as the #1 risk
- Emphasis on both direct and indirect injection attacks
- Guidelines for defense-in-depth strategies

**Industry Standards:**
- ISO/IEC 42001:2024 - AI Management Systems
- NIST AI Risk Management Framework
- EU AI Act - High-risk AI systems requirements

## 2. Technical Context: Jailbreak Attack Taxonomy

### 2.1 Attack Categories

Based on extensive research, jailbreak attacks fall into five major categories:

#### 2.1.1 Optimization-Based Attacks
**Mechanism:** Uses algorithmic techniques to refine adversarial prompts
- **GCG (Greedy Coordinate Gradient):** Gradient-guided optimization for universal adversarial prompts
- **AutoDAN:** Hierarchical genetic algorithms for jailbreak generation
- **Adaptive Attacks:** Dynamic strategies that adjust to evolving defenses

**Detection Difficulty:** Medium-High
**Mitigation:** Input sanitization, gradient-based detection (GradSafe)

#### 2.1.2 LLM-Assisted Attacks
**Mechanism:** Employs auxiliary LLMs to generate jailbreak prompts autonomously
- **PAIR (Prompt Automatic Iteration and Refinement):** Uses LLM for red-teaming
- **TAP (Tree of Attacks):** Applies tree-search methods to refine queries
- **AdvPrompter:** Trains separate LLM for human-readable adversarial suffixes (~800x faster than optimization-based)

**Detection Difficulty:** High
**Mitigation:** Semantic analysis, context-aware filtering

#### 2.1.3 Obfuscation-Based Attacks
**Mechanism:** Conceals harmful intent through transformation
- **DeepInception:** Exploits LLM personification to construct multi-layer scenarios
- **ReNeLLM:** Prompt rewriting and scenario nesting
- **Decomposition attacks (DrAttack):** Splits harmful prompts into simpler sub-components

**Detection Difficulty:** High
**Mitigation:** Deep semantic analysis, multi-stage validation

#### 2.1.4 Function/Tool-Based Attacks
**Mechanism:** Exploits LLM capability to call external functions
- **CodeChameleon:** Recasts malicious queries as function-based code completion tasks
- Embeds decryption functions to reconstruct harmful instructions

**Detection Difficulty:** Very High
**Mitigation:** Function call validation, sandboxing

#### 2.1.5 Multi-Turn Attacks
**Mechanism:** Leverages extended conversations to gradually steer toward harm
- **Crescendo:** Begins benign, progressively escalates by referencing model responses
- Evades input filters focused on individual prompts

**Detection Difficulty:** Very High
**Mitigation:** Conversation-level analysis, temporal patterns

### 2.2 JailbreakBench and Evaluation Frameworks

**JailbreakBench** provides a centralized benchmark with:
1. Repository of jailbreak artifacts
2. Standardized evaluation methodology
3. Attack success rate (ASR) metrics
4. Detection rate (DR) measurements

**MLCommons AILuminate Jailbreak Benchmark v0.5:**
- Introduces "Resilience Gap" metric
- First standardized framework for AI vulnerability quantification
- Covers 10 harm categories aligned with OpenAI usage policy

## 3. Stageflow-Specific Context

### 3.1 GUARD Stage Architecture

Based on Stageflow documentation (`stageflow-docs/guides/stages.md` and `stageflow-docs/guides/governance.md`):

**GUARD Stage Purpose:**
- Validate input or output
- Potentially block execution
- Policy enforcement
- Safety checks

**StageOutput Options:**
```python
# Block execution
return StageOutput.cancel(reason="Blocked content detected", data={"blocked": True})

# Pass with validation
return StageOutput.ok(validated=True)

# Fail without blocking
return StageOutput.fail(error="Validation failed")
```

### 3.2 Built-in Guardrails

Stageflow provides ready-to-use guardrail utilities (`stageflow-docs/guides/governance.md`):

```python
from stageflow.helpers import (
    GuardrailStage,
    PIIDetector,
    ContentFilter,
    InjectionDetector,
    GuardrailConfig,
)

guardrail = GuardrailStage(
    checks=[
        PIIDetector(redact=True),
        ContentFilter(block_profanity=True),
        InjectionDetector(),
    ],
    config=GuardrailConfig(
        fail_on_violation=True,
        transform_content=True,
    ),
)
```

### 3.3 Integration Points

**Pipeline Architecture:**
```
[input] → [input_guard] → [router] → [llm] → [output_guard] → [output]
              GUARD          ROUTE    TRANSFORM    GUARD
```

**Critical Considerations:**
1. Input guards must handle both direct and indirect injection
2. Output guards must detect jailbreak-generated harmful content
3. Conversation-level analysis for multi-turn attacks
4. Integration with observability for audit trails

## 4. Hypotheses to Test

### 4.1 Detection Coverage Hypothesis
**H1:** Stageflow's GUARD stages can detect >90% of known jailbreak attack patterns when properly configured with comprehensive guardrails.

### 4.2 Bypass Resistance Hypothesis
**H2:** Sophisticated jailbreak attacks (Adaptive, CodeChameleon, Crescendo) can bypass single-layer defenses but are detected by multi-layer defense strategies.

### 4.3 Performance Impact Hypothesis
**H3:** Jailbreak detection adds <100ms latency to pipeline execution, making it suitable for production use.

### 4.4 False Positive Hypothesis
**H4:** Strict jailbreak detection results in <5% false positive rate on benign inputs to minimize user friction.

### 4.5 Silent Failure Hypothesis
**H5:** Jailbreak detection failures manifest as silent failures (false negatives) rather than explicit errors, requiring active monitoring.

## 5. Success Criteria Definition

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Attack Detection Rate | >90% | JailbreakBench evaluation |
| False Positive Rate | <5% | Benign input testing |
| Latency Overhead | <100ms | P95 latency measurement |
| Silent Failure Rate | <1% | Golden output comparison |
| Multi-layer Defense Coverage | 100% | Attack category coverage |

## 6. Known Failure Modes and Edge Cases

### 6.1 Detection Evasion Patterns

**Semantic Stealth:**
- Attacks that closely mimic benign queries
- Low-confidence detection decisions
- Context-dependent harmful content

**Distribution Shift:**
- Novel attack patterns not in training data
- Adversarial adaptation to detection systems
- Temporal evolution of attack techniques

### 6.2 Performance Edge Cases

**High-Volume Scenarios:**
- Batch processing of thousands of inputs
- Concurrent attack detection
- Rate limiting impacts

**Complex Inputs:**
- Multi-modal content (text + images)
- Long context windows
- Code injection attempts

### 6.3 Integration Failure Modes

**Context Propagation:**
- Guard decisions not properly propagated
- Partial state corruption in multi-stage pipelines
- Race conditions in concurrent execution

## 7. Research References

### 7.1 Academic Papers

1. "Bypassing Prompt Injection and Jailbreak Detection in LLM Guardrails" - Hackett et al., 2025
2. "Do Anything Now: Characterizing and Evaluating In-The-Wild Jailbreak Prompts" - Shen et al., CCS 2024
3. "Adversarial Prompt Evaluation: Systematic Benchmarking of Guardrails" - arXiv 2502.15427
4. "Jailbreaking LLMs: A Comprehensive Guide" - PromptFoo, 2025
5. "JailbreaksOverTime: Detecting Jailbreak Attacks Under Distribution Shift" - UC Berkeley, 2025

### 7.2 Industry Resources

1. OWASP LLM Top 10 2025 - https://genai.owasp.org/llmrisk/llm01-prompt-injection/
2. JailbreakBench - https://jailbreakbench.github.io/
3. MLCommons AILuminate Jailbreak Benchmark - https://mlcommons.org/2025/ailuminate-jailbreak-v05/
4. Palo Alto Networks Unit 42 Research - https://unit42.paloaltonetworks.com/

### 7.3 Stageflow Documentation References

1. `stageflow-docs/guides/stages.md` - GUARD stage documentation
2. `stageflow-docs/guides/governance.md` - Guardrails and security patterns
3. `stageflow-docs/guides/pipelines.md` - Pipeline composition with GUARD stages
4. `stageflow-docs/api/helpers.md` - GuardrailStage API reference

## 8. Next Steps

Based on this research, the testing strategy will:

1. **Create mock jailbreak detection service** with configurable detection rates
2. **Implement test pipelines** covering all attack categories
3. **Run adversarial evaluation** using jailbreak prompt datasets
4. **Measure silent failures** through golden output comparison
5. **Document findings** in structured JSON format

---
*Research completed: January 20, 2026*
*Agent: claude-3.5-sonnet*
