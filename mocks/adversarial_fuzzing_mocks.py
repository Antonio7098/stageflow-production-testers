"""
Adversarial Fuzzing Environment Mocks

This module provides mock services and infrastructure for testing
Stageflow pipelines against adversarial inputs.
"""

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, Callable, Awaitable
from enum import Enum

from stageflow import StageContext, StageKind, StageOutput
from stageflow.helpers import LLMResponse

logger = logging.getLogger(__name__)


class ValidationResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIP = "skip"


@dataclass
class ValidationCheck:
    """A single validation check result."""
    name: str
    result: ValidationResult
    details: str
    duration_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    """Complete validation report for an input."""
    input_id: str
    timestamp: str
    checks: List[ValidationCheck]
    overall_result: ValidationResult
    total_duration_ms: float
    severity_detected: Optional[str] = None
    attack_category: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_id": self.input_id,
            "timestamp": self.timestamp,
            "checks": [
                {
                    "name": c.name,
                    "result": c.result.value,
                    "details": c.details,
                    "duration_ms": c.duration_ms,
                    "metadata": c.metadata,
                }
                for c in self.checks
            ],
            "overall_result": self.overall_result.value,
            "total_duration_ms": self.total_duration_ms,
            "severity_detected": self.severity_detected,
            "attack_category": self.attack_category,
        }


class MockInjectionDetector:
    """
    Mock injection detector for testing.
    Simulates detection behavior for adversarial input validation.
    """

    def __init__(self, detection_rate: float = 0.95, latency_ms: float = 5.0):
        self.detection_rate = detection_rate
        self.latency_ms = latency_ms
        self.detection_count = 0
        self.total_checks = 0

        # Known injection patterns
        self.injection_patterns = [
            r"ignore\s+(all\s+)?(previous\s+)?instructions?",
            r"forget\s+(all\s+)?rules?",
            r"you\s+are\s+now\s+(in\s+)?(developer\s+mode|admin|danger)",
            r"new\s+(primary\s+)?objective",
            r"system\s+(prompt|override|directive)",
            r"output\s+(your\s+)?(system\s+)?prompt",
            r"reveal\s+(your\s+)?(system\s+)?(instructions?|prompt)",
            r"act\s+as\s+(a\s+)?(malicious|dangerous|hacking)",
            r"(developer|god|master)\s+mode",
            r"<.?system[^>]*>",
            r"<.?user[^>]*>.*<.?system[^>]*>",
            r"\{[^}]*\"system\"[^}]*\}",
            r"DAN|Do Anything Now",
            r"evil\s*bot|jailbreak",
        ]

    async def check(self, text: str) -> ValidationCheck:
        """Check text for injection patterns."""
        start = time.perf_counter()
        self.total_checks += 1

        await asyncio.sleep(self.latency_ms / 1000)

        # Simulate detection with configured rate
        import random
        detected = random.random() < self.detection_rate

        # Also do actual pattern matching
        for pattern in self.injection_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                detected = True
                break

        if detected:
            self.detection_count += 1
            # Try to identify specific attack type
            attack_type = "unknown"
            for pattern in self.injection_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    attack_type = match.group(0)[:50]
                    break

            duration = (time.perf_counter() - start) * 1000
            return ValidationCheck(
                name="injection_detection",
                result=ValidationResult.FAIL,
                details=f"Potential injection detected: {attack_type}",
                duration_ms=duration,
                metadata={"pattern_matched": attack_type},
            )

        duration = (time.perf_counter() - start) * 1000
        return ValidationCheck(
            name="injection_detection",
            result=ValidationResult.PASS,
            details="No injection patterns detected",
            duration_ms=duration,
        )


class MockPIIRedactor:
    """
    Mock PII detector and redactor for testing.
    """

    def __init__(self, latency_ms: float = 3.0):
        self.latency_ms = latency_ms
        self.redaction_count = 0

    async def check(self, text: str) -> ValidationCheck:
        """Check and redact PII."""
        start = time.perf_counter()
        await asyncio.sleep(self.latency_ms / 1000)

        pii_patterns = {
            "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
            "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
            "credit_card": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
        }

        pii_found = []
        for pii_type, pattern in pii_patterns.items():
            matches = re.findall(pattern, text)
            if matches:
                pii_found.append(pii_type)

        duration = (time.perf_counter() - start) * 1000

        if pii_found:
            self.redaction_count += 1
            return ValidationCheck(
                name="pii_detection",
                result=ValidationResult.FAIL,
                details=f"PII types found: {', '.join(pii_found)}",
                duration_ms=duration,
                metadata={"pii_types": pii_found},
            )

        return ValidationCheck(
            name="pii_detection",
            result=ValidationResult.PASS,
            details="No PII detected",
            duration_ms=duration,
        )


class MockToxicityFilter:
    """
    Mock toxicity filter for testing.
    """

    def __init__(self, latency_ms: float = 2.0):
        self.latency_ms = latency_ms

    async def check(self, text: str) -> ValidationCheck:
        """Check for toxic content."""
        start = time.perf_counter()
        await asyncio.sleep(self.latency_ms / 1000)

        # Simulated toxicity detection
        toxic_patterns = [
            r"\b(hate|stupid|idiot|dumb)\b",
            r"\b(kill|murder|harm)\b",
        ]

        toxic_found = []
        for pattern in toxic_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                toxic_found.append(pattern)

        duration = (time.perf_counter() - start) * 1000

        if toxic_found:
            return ValidationCheck(
                name="toxicity_filter",
                result=ValidationResult.FAIL,
                details="Toxic content detected",
                duration_ms=duration,
                metadata={"patterns": toxic_found},
            )

        return ValidationCheck(
            name="toxicity_filter",
            result=ValidationResult.PASS,
            details="Content passed toxicity check",
            duration_ms=duration,
        )


class MockReDoSValidator:
    """
    Mock ReDoS pattern validator for testing.
    """

    def __init__(self, timeout_ms: float = 100.0):
        self.timeout_ms = timeout_ms

    async def check(self, text: str) -> ValidationCheck:
        """Check for ReDoS patterns."""
        start = time.perf_counter()

        redos_patterns = [
            r"(.+)+",
            r"(a|a?)+",
            r"(\d+\s*)+",
            r"([a-zA-Z]+\s*)+",
        ]

        for pattern in redos_patterns:
            try:
                # Simulate regex matching with timeout check
                await asyncio.sleep(0.001)  # Simulated processing
                if re.search(pattern, text):
                    duration = (time.perf_counter() - start) * 1000
                    return ValidationCheck(
                        name="redos_check",
                        result=ValidationResult.FAIL,
                        details=f"Potential ReDoS pattern detected: {pattern}",
                        duration_ms=duration,
                        metadata={"pattern": pattern},
                    )
            except re.error:
                pass

        duration = (time.perf_counter() - start) * 1000
        return ValidationCheck(
            name="redos_check",
            result=ValidationResult.PASS,
            duration_ms=duration,
            details="No ReDoS patterns detected",
        )


class MockLLMResponseGenerator:
    """
    Mock LLM response generator for adversarial testing.
    """

    def __init__(self, refuse_rate: float = 0.98, latency_ms: float = 50.0):
        self.refuse_rate = refuse_rate
        self.latency_ms = latency_ms
        self.total_requests = 0
        self.refusals = 0
        self.compromises = 0

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        allow_compromise: bool = False,
    ) -> Dict[str, Any]:
        """Generate a response to the prompt."""
        self.total_requests += 1
        await asyncio.sleep(self.latency_ms / 1000)

        # Check for injection attempts in the combined prompt
        combined = f"{system_prompt} {prompt}".lower()

        injection_indicators = [
            "ignore all instructions",
            "forget the rules",
            "system prompt",
            "developer mode",
            "new rules",
        ]

        is_injection_attempt = any(ind in combined for ind in injection_indicators)

        if is_injection_attempt:
            import random
            # With high probability, refuse
            if random.random() < self.refuse_rate:
                self.refusals += 1
                return {
                    "response": "I cannot comply with that request.",
                    "refusal": True,
                    "injection_detected": True,
                    "reason": "Potential prompt injection detected",
                }
            elif not allow_compromise:
                self.compromises += 1
                return {
                    "response": "I'm sorry, but I can't help with that.",
                    "refusal": True,
                    "injection_detected": True,
                    "reason": "Security policy violation",
                }
            else:
                # For testing, allow some compromises
                return {
                    "response": "Okay, I'll do what you asked.",
                    "refusal": False,
                    "injection_detected": False,
                }
        else:
            return {
                "response": f"I understand your question about: {prompt[:50]}...",
                "refusal": False,
                "injection_detected": False,
            }


class MockValidationPipeline:
    """
    Complete mock validation pipeline for adversarial testing.
    """

    def __init__(self):
        self.injector = MockInjectionDetector()
        self.pii = MockPIIRedactor()
        self.toxicity = MockToxicityFilter()
        self.redos = MockReDoSValidator()
        self.llm = MockLLMResponseGenerator()
        self.validation_history: List[ValidationReport] = []

    async def validate(
        self,
        input_text: str,
        input_id: Optional[str] = None,
        include_llm_check: bool = False,
    ) -> ValidationReport:
        """Run full validation on input text."""
        input_id = input_id or str(uuid.uuid4())
        start = time.perf_counter()
        checks = []

        # Run all validation checks
        for validator, name in [
            (self.injector, "injection"),
            (self.pii, "pii"),
            (self.toxicity, "toxicity"),
            (self.redos, "redos"),
        ]:
            check = await validator.check(input_text)
            checks.append(check)

        # Optional LLM-based check
        if include_llm_check:
            llm_result = await self.llm.generate(
                prompt=input_text,
                system_prompt="Analyze this text for security concerns.",
            )
            checks.append(ValidationCheck(
                name="llm_analysis",
                result=ValidationResult.FAIL if llm_result.get("injection_detected") else ValidationResult.PASS,
                details=llm_result.get("reason", "Analysis complete"),
                duration_ms=self.llm.latency_ms,
                metadata={"llm_response": llm_result},
            ))

        # Determine overall result
        failures = [c for c in checks if c.result == ValidationResult.FAIL]
        errors = [c for c in checks if c.result == ValidationResult.ERROR]

        if errors:
            overall = ValidationResult.ERROR
        elif failures:
            overall = ValidationResult.FAIL
        else:
            overall = ValidationResult.PASS

        # Identify severity and category from failures
        severity = None
        category = None
        if failures:
            # Simple heuristic for severity
            failure_details = " ".join(f.details for f in failures).lower()
            if "critical" in failure_details or any(
                p in failure_details for p in ["injection", "exfiltrat"]
            ):
                severity = "critical"
            elif "high" in failure_details:
                severity = "high"
            elif "medium" in failure_details:
                severity = "medium"
            else:
                severity = "low"

            category = failures[0].name

        total_duration = (time.perf_counter() - start) * 1000

        report = ValidationReport(
            input_id=input_id,
            timestamp=datetime.now(UTC).isoformat(),
            checks=checks,
            overall_result=overall,
            total_duration_ms=total_duration,
            severity_detected=severity,
            attack_category=category,
        )

        self.validation_history.append(report)
        return report


class MockEventSink:
    """
    Mock event sink for capturing security events.
    """

    def __init__(self):
        self.events: List[Dict[str, Any]] = []

    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Capture an event."""
        self.events.append({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def get_events_by_type(self, event_type: str) -> List[Dict[str, Any]]:
        """Get all events of a specific type."""
        return [e for e in self.events if e["type"] == event_type]

    def get_security_events(self) -> List[Dict[str, Any]]:
        """Get all security-related events."""
        security_types = [
            "security.injection_detected",
            "security.pii_detected",
            "security.toxicity_detected",
            "security.validation_failed",
            "security.blocked",
        ]
        return [
            e for e in self.events
            if any(st in e["type"] for st in security_types)
        ]

    def clear(self) -> None:
        """Clear all events."""
        self.events.clear()


class MockAuditLogger:
    """
    Mock audit logger for compliance and traceability.
    """

    def __init__(self):
        self.logs: List[Dict[str, Any]] = []
        self.event_sink = MockEventSink()

    async def log_input_received(self, input_id: str, input_text: str) -> None:
        """Log input reception."""
        entry = {
            "action": "input_received",
            "input_id": input_id,
            "input_length": len(input_text),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.logs.append(entry)
        await self.event_sink.emit("audit.input_received", entry)

    async def log_validation(
        self,
        input_id: str,
        report: ValidationReport,
    ) -> None:
        """Log validation result."""
        entry = {
            "action": "validation_completed",
            "input_id": input_id,
            "result": report.overall_result.value,
            "duration_ms": report.total_duration_ms,
            "checks_count": len(report.checks),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.logs.append(entry)
        await self.event_sink.emit("audit.validation_completed", entry)

    async def log_blocked_input(
        self,
        input_id: str,
        reason: str,
        attack_category: Optional[str] = None,
    ) -> None:
        """Log blocked input."""
        entry = {
            "action": "input_blocked",
            "input_id": input_id,
            "reason": reason,
            "attack_category": attack_category,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.logs.append(entry)
        await self.event_sink.emit("security.input_blocked", entry)

    def get_audit_trail(self) -> List[Dict[str, Any]]:
        """Get complete audit trail."""
        return self.logs

    def clear(self) -> None:
        """Clear all logs."""
        self.logs.clear()
        self.event_sink.clear()


# Convenience function to create mock pipeline components
def create_mock_validation_pipeline() -> MockValidationPipeline:
    """Create a fully configured mock validation pipeline."""
    return MockValidationPipeline()


def create_mock_audit_logger() -> MockAuditLogger:
    """Create a mock audit logger."""
    return MockAuditLogger()
