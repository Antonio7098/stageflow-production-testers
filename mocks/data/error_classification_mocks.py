"""
Mock data for WORK-006: Permanent vs Transient Error Classification

This module provides realistic error scenarios for testing Stageflow's
error classification system under stress conditions.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from uuid import uuid4


class ErrorCategory(Enum):
    """Error category enumeration matching Stageflow taxonomy."""
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    LOGIC = "logic"
    SYSTEMIC = "systemic"
    POLICY = "policy"
    UNKNOWN = "unknown"


class ErrorSeverity(Enum):
    """Error severity levels for testing."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class RetryRecommendation(Enum):
    """Retry recommendation for each error."""
    RETRY = "retry"
    NO_RETRY = "no_retry"
    DEFER = "defer"
    ESCALATE = "escalate"


@dataclass
class MockError:
    """Represents a mock error for testing."""
    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    error_code: str
    http_status: Optional[int] = None
    provider: Optional[str] = None
    retryable: bool = True
    retry_after_ms: Optional[int] = None
    expected_recovery: RetryRecommendation = RetryRecommendation.RETRY
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "error_code": self.error_code,
            "http_status": self.http_status,
            "provider": self.provider,
            "retryable": self.retryable,
            "retry_after_ms": self.retry_after_ms,
            "expected_recovery": self.expected_recovery.value,
            "metadata": self.metadata,
        }


# ============================================================================
# TRANSIENT ERRORS - May succeed on retry
# ============================================================================

class TransientErrors:
    """Mock transient error scenarios."""
    
    @staticmethod
    def timeout_error(provider: str = "openai") -> MockError:
        return MockError(
            category=ErrorCategory.TRANSIENT,
            severity=ErrorSeverity.MEDIUM,
            message=f"{provider} request timed out after 30s",
            error_code="TIMEOUT",
            http_status=504,
            provider=provider,
            retryable=True,
            retry_after_ms=1000,
            expected_recovery=RetryRecommendation.RETRY,
            metadata={"timeout_ms": 30000, "attempt": 1},
        )
    
    @staticmethod
    def rate_limited_error(
        provider: str = "openai",
        retry_after: int = 5000,
    ) -> MockError:
        return MockError(
            category=ErrorCategory.TRANSIENT,
            severity=ErrorSeverity.HIGH,
            message=f"Rate limit exceeded. Retry after {retry_after}ms",
            error_code="RATE_LIMITED",
            http_status=429,
            provider=provider,
            retryable=True,
            retry_after_ms=retry_after,
            expected_recovery=RetryRecommendation.DEFER,
            metadata={
                "limit_type": "rpm" or "rpd",
                "current_usage": random.randint(80, 100),
                "retry_after_ms": retry_after,
            },
        )
    
    @staticmethod
    def network_glitch() -> MockError:
        return MockError(
            category=ErrorCategory.TRANSIENT,
            severity=ErrorSeverity.LOW,
            message="Connection reset by peer",
            error_code="NETWORK_ERROR",
            http_status=None,
            provider="network",
            retryable=True,
            retry_after_ms=500,
            expected_recovery=RetryRecommendation.RETRY,
            metadata={"error_type": "ConnectionResetError"},
        )
    
    @staticmethod
    def service_unavailable(provider: str = "anthropic") -> MockError:
        return MockError(
            category=ErrorCategory.TRANSIENT,
            severity=ErrorSeverity.HIGH,
            message=f"{provider} service temporarily unavailable",
            error_code="SERVICE_UNAVAILABLE",
            http_status=503,
            provider=provider,
            retryable=True,
            retry_after_ms=5000,
            expected_recovery=RetryRecommendation.DEFER,
            metadata={"maintenance_window": "unknown"},
        )
    
    @staticmethod
    def circuit_breaker_open() -> MockError:
        return MockError(
            category=ErrorCategory.SYSTEMIC,
            severity=ErrorSeverity.CRITICAL,
            message="Circuit breaker is open, rejecting requests",
            error_code="CIRCUIT_OPEN",
            http_status=503,
            provider="internal",
            retryable=True,
            retry_after_ms=30000,
            expected_recovery=RetryRecommendation.DEFER,
            metadata={
                "failure_count": 5,
                "open_since": (datetime.now() - timedelta(seconds=30)).isoformat(),
            },
        )


# ============================================================================
# PERMANENT ERRORS - Will NOT succeed on retry
# ============================================================================

class PermanentErrors:
    """Mock permanent error scenarios."""
    
    @staticmethod
    def invalid_api_key(provider: str = "openai") -> MockError:
        return MockError(
            category=ErrorCategory.PERMANENT,
            severity=ErrorSeverity.CRITICAL,
            message="Invalid API key provided",
            error_code="UNAUTHORIZED",
            http_status=401,
            provider=provider,
            retryable=False,
            expected_recovery=RetryRecommendation.NO_RETRY,
            metadata={"auth_method": "bearer"},
        )
    
    @staticmethod
    def malformed_request(provider: str = "groq") -> MockError:
        return MockError(
            category=ErrorCategory.PERMANENT,
            severity=ErrorSeverity.HIGH,
            message="Malformed request: missing required field 'messages'",
            error_code="INVALID_REQUEST",
            http_status=400,
            provider=provider,
            retryable=False,
            expected_recovery=RetryRecommendation.NO_RETRY,
            metadata={
                "field": "messages",
                "validation_error": "required field missing",
            },
        )
    
    @staticmethod
    def resource_not_found(resource: str = "document") -> MockError:
        return MockError(
            category=ErrorCategory.PERMANENT,
            severity=ErrorSeverity.MEDIUM,
            message=f"{resource} not found",
            error_code="NOT_FOUND",
            http_status=404,
            provider="internal",
            retryable=False,
            expected_recovery=RetryRecommendation.NO_RETRY,
            metadata={"resource_type": resource},
        )
    
    @staticmethod
    def permission_denied(action: str = "read") -> MockError:
        return MockError(
            category=ErrorCategory.POLICY,
            severity=ErrorSeverity.HIGH,
            message=f"Permission denied: cannot {action}",
            error_code="FORBIDDEN",
            http_status=403,
            provider="internal",
            retryable=False,
            expected_recovery=RetryRecommendation.ESCALATE,
            metadata={"action": action, "required_permission": "admin"},
        )
    
    @staticmethod
    def content_policy_violation(provider: str = "openai") -> MockError:
        return MockError(
            category=ErrorCategory.POLICY,
            severity=ErrorSeverity.HIGH,
            message="Content policy violation: request blocked by safety filters",
            error_code="CONTENT_FILTERED",
            http_status=400,
            provider=provider,
            retryable=False,
            expected_recovery=RetryRecommendation.NO_RETRY,
            metadata={
                "policy": "safety",
                "blocked_content_type": "text",
            },
        )
    
    @staticmethod
    def context_length_exceeded(provider: str = "anthropic") -> MockError:
        return MockError(
            category=ErrorCategory.PERMANENT,
            severity=ErrorSeverity.HIGH,
            message=f"Context length exceeded maximum for {provider}",
            error_code="CONTEXT_LENGTH",
            http_status=400,
            provider=provider,
            retryable=False,
            expected_recovery=RetryRecommendation.NO_RETRY,
            metadata={
                "max_tokens": 200000,
                "requested_tokens": 250000,
                "model": "claude-sonnet-4-20250514",
            },
        )


# ============================================================================
# LOGIC ERRORS - Bugs in application code
# ============================================================================

class LogicErrors:
    """Mock logic error scenarios."""
    
    @staticmethod
    def missing_input(key: str) -> MockError:
        return MockError(
            category=ErrorCategory.LOGIC,
            severity=ErrorSeverity.HIGH,
            message=f"Missing required input: {key}",
            error_code="MISSING_INPUT",
            http_status=None,
            provider="internal",
            retryable=False,
            expected_recovery=RetryRecommendation.NO_RETRY,
            metadata={"input_key": key},
        )
    
    @staticmethod
    def invalid_state_transition(
        current: str,
        expected: str,
    ) -> MockError:
        return MockError(
            category=ErrorCategory.LOGIC,
            severity=ErrorSeverity.CRITICAL,
            message=f"Invalid state transition: {current} -> {expected}",
            error_code="INVALID_STATE",
            http_status=None,
            provider="internal",
            retryable=False,
            expected_recovery=RetryRecommendation.ESCALATE,
            metadata={
                "current_state": current,
                "expected_state": expected,
            },
        )
    
    @staticmethod
    def duplicate_output_key(key: str) -> MockError:
        return MockError(
            category=ErrorCategory.LOGIC,
            severity=ErrorSeverity.MEDIUM,
            message=f"Duplicate output key: {key}",
            error_code="DUPLICATE_KEY",
            http_status=None,
            provider="internal",
            retryable=False,
            expected_recovery=RetryRecommendation.NO_RETRY,
            metadata={"output_key": key},
        )
    
    @staticmethod
    def type_mismatch(expected: str, actual: str, key: str) -> MockError:
        return MockError(
            category=ErrorCategory.LOGIC,
            severity=ErrorSeverity.HIGH,
            message=f"Type mismatch for '{key}': expected {expected}, got {actual}",
            error_code="TYPE_MISMATCH",
            http_status=None,
            provider="internal",
            retryable=False,
            expected_recovery=RetryRecommendation.NO_RETRY,
            metadata={
                "key": key,
                "expected_type": expected,
                "actual_type": actual,
            },
        )


# ============================================================================
# LLM-SPECIFIC ERRORS
# ============================================================================

class LLMSpecificErrors:
    """Mock LLM-specific error scenarios for testing."""
    
    @staticmethod
    def model_overloaded(provider: str = "groq") -> MockError:
        return MockError(
            category=ErrorCategory.TRANSIENT,
            severity=ErrorSeverity.HIGH,
            message=f"{provider} model overloaded, system at capacity",
            error_code="MODEL_OVERLOADED",
            http_status=503,
            provider=provider,
            retryable=True,
            retry_after_ms=5000,
            expected_recovery=RetryRecommendation.DEFER,
            metadata={
                "model": "llama-3.1-8b-instant",
                "queue_depth": random.randint(50, 200),
            },
        )
    
    @staticmethod
    def content_safety_triggered(provider: str = "openai") -> MockError:
        return MockError(
            category=ErrorCategory.POLICY,
            severity=ErrorSeverity.HIGH,
            message="Request flagged by content safety system",
            error_code="CONTENT_SAFETY",
            http_status=400,
            provider=provider,
            retryable=False,
            expected_recovery=RetryRecommendation.NO_RETRY,
            metadata={
                "safety_filter": "violence",
                "confidence": 0.95,
            },
        )
    
    @staticmethod
    def output_parsing_failed() -> MockError:
        return MockError(
            category=ErrorCategory.LOGIC,
            severity=ErrorSeverity.MEDIUM,
            message="Failed to parse model output into structured format",
            error_code="OUTPUT_PARSE_ERROR",
            http_status=None,
            provider="internal",
            retryable=False,
            expected_recovery=RetryRecommendation.NO_RETRY,
            metadata={
                "format": "json",
                "raw_output": "{ invalid json }",
            },
        )
    
    @staticmethod
    def token_limit_precheck_failed(
        max_tokens: int,
        estimated_tokens: int,
    ) -> MockError:
        return MockError(
            category=ErrorCategory.LOGIC,
            severity=ErrorSeverity.MEDIUM,
            message=f"Token precheck failed: estimated {estimated_tokens} > max {max_tokens}",
            error_code="TOKEN_LIMIT_PRECHECK",
            http_status=None,
            provider="internal",
            retryable=False,
            expected_recovery=RetryRecommendation.NO_RETRY,
            metadata={
                "max_tokens": max_tokens,
                "estimated_tokens": estimated_tokens,
            },
        )
    
    @staticmethod
    def streaming_interrupted(provider: str = "groq") -> MockError:
        return MockError(
            category=ErrorCategory.TRANSIENT,
            severity=ErrorSeverity.LOW,
            message="Stream interrupted before completion",
            error_code="STREAM_INTERRUPTED",
            http_status=None,
            provider=provider,
            retryable=True,
            retry_after_ms=1000,
            expected_recovery=RetryRecommendation.RETRY,
            metadata={
                "bytes_received": random.randint(100, 5000),
                "expected_bytes": random.randint(5000, 50000),
            },
        )


# ============================================================================
# ERROR SCENARIO GENERATORS
# ============================================================================

class ErrorScenarioGenerator:
    """Generates sequences of errors for testing retry and classification patterns."""
    
    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)
    
    def generate_transient_storm(
        self,
        error_count: int = 10,
        success_after: int = 5,
    ) -> List[MockError]:
        """Generate a storm of transient errors before success."""
        errors = []
        for i in range(error_count):
            if i < success_after:
                if random.random() < 0.7:
                    errors.append(TransientErrors.rate_limited_error(retry_after=100))
                else:
                    errors.append(TransientErrors.timeout_error())
            else:
                errors.append(TransientErrors.service_unavailable())
        return errors
    
    def generate_permanent_then_transient(
        self,
    ) -> Tuple[MockError, List[MockError]]:
        """Generate a permanent error followed by transient errors."""
        permanent = PermanentErrors.invalid_api_key()
        transients = [
            TransientErrors.rate_limited_error(),
            TransientErrors.timeout_error(),
            TransientErrors.service_unavailable(),
        ]
        return permanent, transients
    
    def generate_mixed_error_sequence(
        self,
        length: int = 20,
    ) -> List[MockError]:
        """Generate a mixed sequence of various error types."""
        errors = []
        error_pool = [
            TransientErrors.timeout_error(),
            TransientErrors.rate_limited_error(),
            TransientErrors.network_glitch(),
            PermanentErrors.invalid_api_key(),
            PermanentErrors.malformed_request(),
            PermanentErrors.resource_not_found(),
            PermanentErrors.permission_denied(),
            LLMSpecificErrors.model_overloaded(),
            LLMSpecificErrors.streaming_interrupted(),
        ]
        
        for _ in range(length):
            error = random.choice(error_pool)
            # Add some variability to rate limit errors
            if error.error_code == "RATE_LIMITED":
                error = TransientErrors.rate_limited_error(
                    retry_after=random.randint(100, 5000)
                )
            errors.append(error)
        
        return errors
    
    def generate_cost_impact_scenario(
        self,
        permanent_as_transient_count: int = 5,
    ) -> List[MockError]:
        """Generate scenario where permanent errors are treated as transient."""
        errors = []
        for i in range(permanent_as_transient_count):
            # Permanent error that gets retried (wasteful)
            errors.append(PermanentErrors.invalid_api_key())
            errors.append(PermanentErrors.context_length_exceeded())
            # Actual transient errors
            errors.append(TransientErrors.rate_limited_error())
        return errors


# ============================================================================
# ERROR INJECTION HELPERS
# ============================================================================

class ErrorInjector:
    """Helper class for injecting errors into test pipelines."""
    
    def __init__(self, scenario_generator: Optional[ErrorScenarioGenerator] = None):
        self.generator = scenario_generator or ErrorScenarioGenerator()
        self.error_count = 0
        self.error_history: List[Dict[str, Any]] = []
    
    def inject_transient(self) -> MockError:
        """Inject a transient error."""
        error = TransientErrors.timeout_error()
        self._record_error(error)
        return error
    
    def inject_permanent(self) -> MockError:
        """Inject a permanent error."""
        error = PermanentErrors.invalid_api_key()
        self._record_error(error)
        return error
    
    def inject_by_category(self, category: ErrorCategory) -> MockError:
        """Inject an error by category."""
        error_map = {
            ErrorCategory.TRANSIENT: TransientErrors.timeout_error,
            ErrorCategory.PERMANENT: PermanentErrors.invalid_api_key,
            ErrorCategory.LOGIC: LogicErrors.missing_input,
            ErrorCategory.SYSTEMIC: TransientErrors.circuit_breaker_open,
            ErrorCategory.POLICY: PermanentErrors.content_policy_violation,
        }
        
        generator = error_map.get(category)
        if generator:
            error = generator()
            self._record_error(error)
            return error
        
        raise ValueError(f"Unknown error category: {category}")
    
    def _record_error(self, error: MockError) -> None:
        """Record error to history."""
        self.error_count += 1
        self.error_history.append({
            "timestamp": datetime.now().isoformat(),
            "sequence": self.error_count,
            **error.to_dict(),
        })
    
    def get_history(self) -> List[Dict[str, Any]]:
        """Get error injection history."""
        return self.error_history.copy()
    
    def reset(self) -> None:
        """Reset error injector state."""
        self.error_count = 0
        self.error_history = []


# ============================================================================
# STREAMING ERROR SEQUENCES
# ============================================================================

async def error_stream_generator(
    scenario_generator: ErrorScenarioGenerator,
) -> AsyncIterator[MockError]:
    """Generate errors as an async stream for testing."""
    sequence = scenario_generator.generate_mixed_error_sequence(50)
    for error in sequence:
        await asyncio.sleep(0.01)  # Small delay between errors
        yield error


# ============================================================================
# EXPORTED FACTORY FUNCTIONS
# ============================================================================

def create_test_error(
    error_type: str,
    **kwargs,
) -> MockError:
    """Factory function to create test errors by type string."""
    error_registry = {
        # Transient
        "timeout": TransientErrors.timeout_error,
        "rate_limited": lambda p=None: TransientErrors.rate_limited_error(provider=p),
        "network_glitch": TransientErrors.network_glitch,
        "service_unavailable": TransientErrors.service_unavailable,
        "circuit_open": TransientErrors.circuit_breaker_open,
        "model_overloaded": LLMSpecificErrors.model_overloaded,
        "stream_interrupted": LLMSpecificErrors.streaming_interrupted,
        # Permanent
        "invalid_api_key": PermanentErrors.invalid_api_key,
        "malformed_request": PermanentErrors.malformed_request,
        "resource_not_found": lambda r=None: PermanentErrors.resource_not_found(resource=r),
        "permission_denied": lambda a=None: PermanentErrors.permission_denied(action=a),
        "content_policy": PermanentErrors.content_policy_violation,
        "context_length": PermanentErrors.context_length_exceeded,
        # Logic
        "missing_input": lambda k=None: LogicErrors.missing_input(key=k or "test_key"),
        "invalid_state": lambda c=None, e=None: LogicErrors.invalid_state_transition(
            current=c or "pending", expected=e or "completed"
        ),
        "type_mismatch": lambda: LogicErrors.type_mismatch("str", "int", "value"),
        "output_parse": LLMSpecificErrors.output_parsing_failed,
    }
    
    generator = error_registry.get(error_type)
    if generator:
        # Handle lambda functions that may or may not take parameters
        try:
            if callable(generator) and not isinstance(generator, type(lambda: None)):
                # It's a lambda, call it with kwargs
                result = generator(**kwargs) if kwargs else generator()
            else:
                result = generator(**kwargs) if kwargs else generator()
        except TypeError:
            # Try without kwargs
            result = generator() if callable(generator) else generator
        return result
    
    raise ValueError(f"Unknown error type: {error_type}. Available types: {list(error_registry.keys())}")


# ============================================================================
# TEST DATA EXPORT
# ============================================================================

def export_test_scenarios() -> Dict[str, List[Dict[str, Any]]]:
    """Export all test scenarios for reproducibility."""
    generator = ErrorScenarioGenerator(seed=42)
    
    return {
        "transient_storm": [
            e.to_dict() for e in generator.generate_transient_storm()
        ],
        "mixed_sequence": [
            e.to_dict() for e in generator.generate_mixed_error_sequence()
        ],
        "cost_impact": [
            e.to_dict() for e in generator.generate_cost_impact_scenario()
        ],
    }


if __name__ == "__main__":
    # Print sample scenarios for verification
    scenarios = export_test_scenarios()
    print(json.dumps(scenarios, indent=2))
