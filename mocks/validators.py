"""
Mock validators for CONTRACT-007 custom validator integration testing.

This module provides various validator implementations to test
Stageflow's custom validator integration capabilities.
"""

from typing import Any, Callable, Optional
from dataclasses import dataclass
from enum import Enum
import re


class ValidationSeverity(Enum):
    """Severity levels for validation errors."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationResult:
    """Result of a validation check."""
    is_valid: bool
    message: str
    field_name: Optional[str] = None
    severity: ValidationSeverity = ValidationSeverity.ERROR
    error_code: Optional[str] = None

    @classmethod
    def ok(cls, field_name: str = None) -> "ValidationResult":
        return cls(is_valid=True, message="Valid", field_name=field_name)

    @classmethod
    def fail(
        cls,
        message: str,
        field_name: str = None,
        error_code: str = None,
    ) -> "ValidationResult":
        return cls(
            is_valid=False,
            message=message,
            field_name=field_name,
            error_code=error_code,
        )


class Validator:
    """Base class for custom validators."""

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def validate(self, value: Any, context: dict = None) -> ValidationResult:
        """Validate a value. Override in subclasses."""
        raise NotImplementedError


class StringValidator(Validator):
    """Validator for string values."""

    def __init__(
        self,
        min_length: int = 0,
        max_length: Optional[int] = None,
        pattern: Optional[str] = None,
        allow_empty: bool = True,
    ):
        self.min_length = min_length
        self.max_length = max_length
        self.pattern = re.compile(pattern) if pattern else None
        self.allow_empty = allow_empty

    def validate(self, value: Any, context: dict = None) -> ValidationResult:
        if value is None:
            if self.allow_empty:
                return ValidationResult.ok()
            return ValidationResult.fail(
                "Value cannot be None",
                error_code="NULL_VALUE",
            )

        if not isinstance(value, str):
            return ValidationResult.fail(
                f"Expected string, got {type(value).__name__}",
                error_code="TYPE_MISMATCH",
            )

        if not self.allow_empty and len(value) == 0:
            return ValidationResult.fail(
                "String cannot be empty",
                error_code="EMPTY_STRING",
            )

        if len(value) < self.min_length:
            return ValidationResult.fail(
                f"String must be at least {self.min_length} characters",
                error_code="TOO_SHORT",
            )

        if self.max_length and len(value) > self.max_length:
            return ValidationResult.fail(
                f"String must be at most {self.max_length} characters",
                error_code="TOO_LONG",
            )

        if self.pattern and not self.pattern.match(value):
            return ValidationResult.fail(
                f"String does not match pattern {self.pattern.pattern}",
                error_code="PATTERN_MISMATCH",
            )

        return ValidationResult.ok()


class EmailValidator(Validator):
    """Email format validator."""

    EMAIL_PATTERN = re.compile(
        r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    )

    def validate(self, value: Any, context: dict = None) -> ValidationResult:
        if not isinstance(value, str):
            return ValidationResult.fail(
                "Email must be a string",
                error_code="TYPE_MISMATCH",
            )

        if not self.EMAIL_PATTERN.match(value):
            return ValidationResult.fail(
                "Invalid email format",
                error_code="INVALID_FORMAT",
            )

        return ValidationResult.ok()


class NumberValidator(Validator):
    """Validator for numeric values."""

    def __init__(
        self,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        integer_only: bool = False,
    ):
        self.min_value = min_value
        self.max_value = max_value
        self.integer_only = integer_only

    def validate(self, value: Any, context: dict = None) -> ValidationResult:
        if value is None:
            return ValidationResult.fail(
                "Value cannot be None",
                error_code="NULL_VALUE",
            )

        if not isinstance(value, (int, float)):
            return ValidationResult.fail(
                f"Expected number, got {type(value).__name__}",
                error_code="TYPE_MISMATCH",
            )

        if self.integer_only and not isinstance(value, int):
            return ValidationResult.fail(
                "Value must be an integer",
                error_code="NOT_INTEGER",
            )

        if self.min_value is not None and value < self.min_value:
            return ValidationResult.fail(
                f"Value must be at least {self.min_value}",
                error_code="BELOW_MIN",
            )

        if self.max_value is not None and value > self.max_value:
            return ValidationResult.fail(
                f"Value must be at most {self.max_value}",
                error_code="ABOVE_MAX",
            )

        return ValidationResult.ok()


class RangeValidator(Validator):
    """Validator for range/end date relationships."""

    def __init__(
        self,
        start_field: str,
        end_field: str,
        allow_equal: bool = False,
    ):
        self.start_field = start_field
        self.end_field = end_field
        self.allow_equal = allow_equal

    def validate(self, data: dict, context: dict = None) -> ValidationResult:
        """Validate that end >= start."""
        if not isinstance(data, dict):
            return ValidationResult.fail(
                "Range validation requires a dict",
                error_code="TYPE_MISMATCH",
            )

        start = data.get(self.start_field)
        end = data.get(self.end_field)

        if start is None or end is None:
            return ValidationResult.ok()  # Let other validators handle missing fields

        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            return ValidationResult.ok()  # Not numeric, skip

        if self.allow_equal:
            if end < start:
                return ValidationResult.fail(
                    f"End must be >= start ({self.end_field} < {self.start_field})",
                    error_code="END_BEFORE_START",
                )
        else:
            if end <= start:
                return ValidationResult.fail(
                    f"End must be > start ({self.end_field} <= {self.start_field})",
                    error_code="END_NOT_AFTER_START",
                )

        return ValidationResult.ok()


class DependentFieldValidator(Validator):
    """Validator for field dependencies."""

    def __init__(
        self,
        field: str,
        depends_on: str,
        condition: Callable = lambda dep, val: True,
    ):
        self.field = field
        self.depends_on = depends_on
        self.condition = condition

    def validate(self, data: dict, context: dict = None) -> ValidationResult:
        if not isinstance(data, dict):
            return ValidationResult.fail(
                "Dependent field validation requires a dict",
                error_code="TYPE_MISMATCH",
            )

        field_value = data.get(self.field)
        dep_value = data.get(self.depends_on)

        if dep_value is None:
            return ValidationResult.ok()  # Skip if dependency not met

        if not self.condition(dep_value, field_value):
            return ValidationResult.fail(
                f"Field '{self.field}' has invalid value given '{self.depends_on}'",
                error_code="DEPENDENCY_VIOLATION",
            )

        return ValidationResult.ok()


class ChoiceValidator(Validator):
    """Validator for allowed values."""

    def __init__(self, allowed_values: list, case_sensitive: bool = True):
        self.allowed_values = allowed_values
        self.case_sensitive = case_sensitive

    def validate(self, value: Any, context: dict = None) -> ValidationResult:
        if not self.case_sensitive and isinstance(value, str):
            value = value.lower()
            allowed = [v.lower() if isinstance(v, str) else v for v in self.allowed_values]
        else:
            allowed = self.allowed_values

        if value not in allowed:
            return ValidationResult.fail(
                f"Value must be one of {self.allowed_values}, got {value}",
                error_code="NOT_ALLOWED",
            )

        return ValidationResult.ok()


class LengthValidator(Validator):
    """Validator for collection/string length."""

    def __init__(
        self,
        min_items: int = 0,
        max_items: Optional[int] = None,
    ):
        self.min_items = min_items
        self.max_items = max_items

    def validate(self, value: Any, context: dict = None) -> ValidationResult:
        try:
            length = len(value)
        except TypeError:
            return ValidationResult.fail(
                f"Value must be countable, got {type(value).__name__}",
                error_code="NOT_COUNTABLE",
            )

        if length < self.min_items:
            return ValidationResult.fail(
                f"Must have at least {self.min_items} items, got {length}",
                error_code="TOO_FEW",
            )

        if self.max_items is not None and length > self.max_items:
            return ValidationResult.fail(
                f"Must have at most {self.max_items} items, got {length}",
                error_code="TOO_MANY",
            )

        return ValidationResult.ok()


class AsyncValidator(Validator):
    """Base class for async validators (simulated)."""

    async def validate_async(self, value: Any, context: dict = None) -> ValidationResult:
        """Async validation. Override in subclasses."""
        raise NotImplementedError


class DatabaseLookupValidator(AsyncValidator):
    """Simulated database lookup validator."""

    def __init__(self, valid_ids: set):
        self.valid_ids = valid_ids

    async def validate_async(
        self,
        value: Any,
        context: dict = None,
    ) -> ValidationResult:
        """Simulate async database lookup."""
        import asyncio
        await asyncio.sleep(0.001)  # Simulate DB latency

        if value not in self.valid_ids:
            return ValidationResult.fail(
                f"ID {value} not found in database",
                error_code="NOT_FOUND",
            )

        return ValidationResult.ok()

    def validate(self, value: Any, context: dict = None) -> ValidationResult:
        """Sync wrapper for async validator."""
        import asyncio
        return asyncio.run(self.validate_async(value, context))


class APIValidator(AsyncValidator):
    """Simulated external API validator."""

    def __init__(self, valid_prefixes: list):
        self.valid_prefixes = valid_prefixes

    async def validate_async(
        self,
        value: Any,
        context: dict = None,
    ) -> ValidationResult:
        """Simulate async API call."""
        import asyncio
        await asyncio.sleep(0.001)  # Simulate API latency

        if not isinstance(value, str):
            return ValidationResult.fail(
                "Value must be a string",
                error_code="TYPE_MISMATCH",
            )

        for prefix in self.valid_prefixes:
            if value.startswith(prefix):
                return ValidationResult.ok()

        return ValidationResult.fail(
            f"Value must start with one of {self.valid_prefixes}",
            error_code="INVALID_PREFIX",
        )

    def validate(self, value: Any, context: dict = None) -> ValidationResult:
        """Sync wrapper for async validator."""
        import asyncio
        return asyncio.run(self.validate_async(value, context))


class CompositeValidator(Validator):
    """Validator that chains multiple validators."""

    def __init__(self, validators: list[Validator]):
        self.validators = validators

    def validate(self, value: Any, context: dict = None) -> ValidationResult:
        for validator in self.validators:
            result = validator.validate(value, context)
            if not result.is_valid:
                return result
        return ValidationResult.ok()


class ConditionalValidator(Validator):
    """Validator that only runs under certain conditions."""

    def __init__(
        self,
        condition: Callable[[dict], bool],
        validator: Validator,
        else_result: ValidationResult = None,
    ):
        self.condition = condition
        self.validator = validator
        self.else_result = else_result or ValidationResult.ok()

    def validate(self, data: dict, context: dict = None) -> ValidationResult:
        if self.condition(data):
            return self.validator.validate(data, context)
        return self.else_result


class ContextAwareValidator(Validator):
    """Validator that uses pipeline context."""

    def __init__(self, required_context_keys: list[str]):
        self.required_context_keys = required_context_keys

    def validate(self, value: Any, context: dict = None) -> ValidationResult:
        if context is None:
            return ValidationResult.fail(
                "Context required for validation",
                error_code="NO_CONTEXT",
            )

        for key in self.required_context_keys:
            if key not in context:
                return ValidationResult.fail(
                    f"Missing required context key: {key}",
                    error_code="MISSING_CONTEXT",
                )

        return ValidationResult.ok()


# Validator factory functions for easy creation
def create_string_validator(
    min_length: int = 0,
    max_length: Optional[int] = None,
    pattern: Optional[str] = None,
) -> StringValidator:
    return StringValidator(min_length, max_length, pattern)


def create_email_validator() -> EmailValidator:
    return EmailValidator()


def create_number_validator(
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    integer_only: bool = False,
) -> NumberValidator:
    return NumberValidator(min_value, max_value, integer_only)


def create_range_validator(
    start_field: str,
    end_field: str,
    allow_equal: bool = False,
) -> RangeValidator:
    return RangeValidator(start_field, end_field, allow_equal)


def create_choice_validator(allowed_values: list) -> ChoiceValidator:
    return ChoiceValidator(allowed_values)


def create_length_validator(
    min_items: int = 0,
    max_items: Optional[int] = None,
) -> LengthValidator:
    return LengthValidator(min_items, max_items)
