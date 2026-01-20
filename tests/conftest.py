"""Test fixtures and configuration for TRANSFORM-002 schema mapping tests."""

import pytest
import asyncio
from typing import Any
from uuid import uuid4

from stageflow import StageContext, StageKind, StageOutput
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow.stages.inputs import StageInputs

from mocks.schema_mapping_mocks import (
    SchemaMappingMockData,
    NestedDataGenerator,
    StreamingDataGenerator,
    create_test_datasets,
    DataCategory
)


@pytest.fixture
def valid_user_data():
    """Return a valid user record for happy path testing."""
    return SchemaMappingMockData.generate_valid_user()


@pytest.fixture
def valid_user_with_optional():
    """Return a valid user record with optional fields."""
    return SchemaMappingMockData.generate_valid_user(include_optional=True)


@pytest.fixture
def edge_case_users():
    """Return edge case user records."""
    return {
        case: SchemaMappingMockData.generate_edge_case_user(case)
        for case in ["min_age", "max_age", "empty_name", "negative_balance", "empty_tags", "null_metadata"]
    }


@pytest.fixture
def adversarial_users():
    """Return adversarial/malformed user records."""
    return {
        case: SchemaMappingMockData.generate_adversarial_user(case)
        for case in ["type_mismatch_string_number", "invalid_email_format", "empty_string_required", "null_in_required"]
    }


@pytest.fixture
def schema_drift_cases():
    """Return schema drift test cases."""
    return {
        case: SchemaMappingMockData.generate_schema_drift_case(case)
        for case in ["new_optional_field", "field_renamed", "field_type_changed", "nested_structure_added"]
    }


@pytest.fixture
def nested_records():
    """Return nested structure records."""
    return [
        NestedDataGenerator.generate_mixed_type_record(),
        NestedDataGenerator.generate_nested_record(depth=3),
        NestedDataGenerator.generate_nested_record(depth=5),
    ]


@pytest.fixture
def streaming_records():
    """Return streaming data records."""
    return [StreamingDataGenerator.generate_stream_record(i) for i in range(20)]


@pytest.fixture
def streaming_with_drift():
    """Return streaming records with schema drift."""
    return [StreamingDataGenerator.generate_stream_with_schema_drift(i) for i in range(100)]


@pytest.fixture
def all_test_datasets():
    """Return all test datasets."""
    return create_test_datasets()


@pytest.fixture
def mock_context():
    """Create a mock stage context for testing."""
    def _create_context(input_data: dict, stage_name: str = "test_stage"):
        snapshot = ContextSnapshot(
            run_id=RunIdentity(
                pipeline_run_id=uuid4(),
                request_id=uuid4(),
                session_id=uuid4(),
                user_id=uuid4(),
                org_id=None,
                interaction_id=uuid4(),
            ),
            topology="test_topology",
            execution_mode="test",
            input_data=input_data,
        )
        
        ctx = StageContext(
            snapshot=snapshot,
            inputs=StageInputs(snapshot=snapshot),
            stage_name=stage_name,
        )
        return ctx
    
    return _create_context


@pytest.fixture
def schema_validation_cases():
    """Return cases for schema validation testing."""
    return {
        "valid_complete": {
            "user_id": "user_001",
            "email": "test@example.com",
            "full_name": "John Doe",
            "age": 30,
            "account_balance": 100.50,
            "is_active": True,
            "created_at": "2024-01-15T10:30:00Z"
        },
        "valid_minimal": {
            "user_id": "user_002",
            "email": "test2@example.com",
            "full_name": "Jane Doe",
            "age": 25,
            "account_balance": 200.75,
            "is_active": False,
            "created_at": "2024-01-16T14:45:00Z"
        },
        "missing_user_id": {
            "email": "test@example.com",
            "full_name": "John Doe",
            "age": 30,
            "account_balance": 100.50,
            "is_active": True,
            "created_at": "2024-01-15T10:30:00Z"
        },
        "missing_email": {
            "user_id": "user_001",
            "full_name": "John Doe",
            "age": 30,
            "account_balance": 100.50,
            "is_active": True,
            "created_at": "2024-01-15T10:30:00Z"
        },
        "invalid_email": {
            "user_id": "user_001",
            "email": "not-an-email",
            "full_name": "John Doe",
            "age": 30,
            "account_balance": 100.50,
            "is_active": True,
            "created_at": "2024-01-15T10:30:00Z"
        },
        "negative_age": {
            "user_id": "user_001",
            "email": "test@example.com",
            "full_name": "John Doe",
            "age": -5,
            "account_balance": 100.50,
            "is_active": True,
            "created_at": "2024-01-15T10:30:00Z"
        },
        "too_old": {
            "user_id": "user_001",
            "email": "test@example.com",
            "full_name": "John Doe",
            "age": 200,
            "account_balance": 100.50,
            "is_active": True,
            "created_at": "2024-01-15T10:30:00Z"
        },
        "non_boolean_is_active": {
            "user_id": "user_001",
            "email": "test@example.com",
            "full_name": "John Doe",
            "age": 30,
            "account_balance": 100.50,
            "is_active": "yes",
            "created_at": "2024-01-15T10:30:00Z"
        },
        "null_required": {
            "user_id": None,
            "email": "test@example.com",
            "full_name": "John Doe",
            "age": 30,
            "account_balance": 100.50,
            "is_active": True,
            "created_at": "2024-01-15T10:30:00Z"
        },
    }


@pytest.fixture
def field_mapping_test_cases():
    """Return test cases for field mapping."""
    return {
        "legacy_to_modern": {
            "mapping": {
                "user_id": "uid",
                "email": "email_address",
                "full_name": "name",
                "age": "years_old",
                "account_balance": "balance",
                "is_active": "active_flag",
                "created_at": "registration_date"
            },
            "input": {
                "uid": "user_001",
                "email_address": "test@example.com",
                "name": "John Doe",
                "years_old": 30,
                "balance": 100.50,
                "active_flag": True,
                "registration_date": "2024-01-15T10:30:00Z"
            },
            "expected": {
                "user_id": "user_001",
                "email": "test@example.com",
                "full_name": "John Doe",
                "age": 30,
                "account_balance": 100.50,
                "is_active": True,
                "created_at": "2024-01-15T10:30:00Z"
            }
        },
        "missing_source_field": {
            "mapping": {
                "user_id": "uid",
                "email": "email_address",
                "full_name": "name",
                "age": "years_old"
            },
            "input": {
                "uid": "user_001",
                "email_address": "test@example.com",
                "name": "John Doe"
                # "years_old" is missing
            },
            "expected_missing": ["age"]
        },
        "type_coercion": {
            "mapping": {
                "age": "age_string",
                "account_balance": "balance_string",
                "is_active": "active_string"
            },
            "input": {
                "age_string": "30",
                "balance_string": "100.50",
                "active_string": "true"
            },
            "expected": {
                "age": 30,
                "account_balance": 100.50,
                "is_active": True
            }
        }
    }


@pytest.fixture
def nested_path_test_cases():
    """Return test cases for nested path access."""
    return {
        "valid_path": {
            "data": {
                "user": {
                    "profile": {
                        "name": "John Doe"
                    }
                }
            },
            "path": "user.profile.name",
            "expected": "John Doe"
        },
        "deep_path": {
            "data": {
                "a": {
                    "b": {
                        "c": {
                            "d": {
                                "e": "deep value"
                            }
                        }
                    }
                }
            },
            "path": "a.b.c.d.e",
            "expected": "deep value"
        },
        "path_not_found": {
            "data": {
                "user": {
                    "profile": {
                        "name": "John Doe"
                    }
                }
            },
            "path": "user.profile.email",
            "expected_error": "Nested path not found"
        },
        "path_partial": {
            "data": {
                "level1": {
                    "level2": "value"
                }
            },
            "path": "level1.level2.level3",
            "expected_error": "Nested path not found"
        }
    }


@pytest.fixture
def schema_drift_test_cases():
    """Return test cases for schema drift detection."""
    return {
        "no_drift": {
            "data": {
                "user_id": "user_001",
                "email": "test@example.com",
                "full_name": "John Doe",
                "age": 30,
                "account_balance": 100.50,
                "is_active": True,
                "created_at": "2024-01-15T10:30:00Z"
            },
            "expected_fields": ["user_id", "email", "full_name", "age", "account_balance", "is_active", "created_at"],
            "required_fields": ["user_id", "email"],
            "expect_drift": False
        },
        "new_optional_field": {
            "data": {
                "user_id": "user_001",
                "email": "test@example.com",
                "full_name": "John Doe",
                "age": 30,
                "account_balance": 100.50,
                "is_active": True,
                "created_at": "2024-01-15T10:30:00Z",
                "new_field": "added value"  # New field
            },
            "expected_fields": ["user_id", "email", "full_name", "age", "account_balance", "is_active", "created_at"],
            "required_fields": ["user_id", "email"],
            "expect_drift": True,
            "expected_added": ["new_field"]
        },
        "missing_required": {
            "data": {
                # "user_id" is missing (required)
                "email": "test@example.com",
                "full_name": "John Doe",
                "age": 30,
                "account_balance": 100.50,
                "is_active": True,
                "created_at": "2024-01-15T10:30:00Z"
            },
            "expected_fields": ["user_id", "email", "full_name", "age", "account_balance", "is_active", "created_at"],
            "required_fields": ["user_id", "email"],
            "expect_drift": True,
            "expect_failure": True
        },
        "field_renamed": {
            "data": {
                "uid": "user_001",  # Renamed from user_id
                "email_address": "test@example.com",  # Renamed
                "full_name": "John Doe",
                "age": 30,
                "account_balance": 100.50,
                "is_active": True,
                "created_at": "2024-01-15T10:30:00Z"
            },
            "expected_fields": ["user_id", "email", "full_name", "age", "account_balance", "is_active", "created_at"],
            "required_fields": ["user_id", "email"],
            "expect_drift": True,
            "expected_missing": ["user_id", "email"],
            "expected_added": ["uid", "email_address"]
        }
    }
