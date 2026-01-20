"""Schema mapping accuracy mock data generators for TRANSFORM-002 testing.

This module provides mock data for testing schema mapping accuracy in TRANSFORM stages,
covering happy paths, edge cases, adversarial inputs, and schema drift scenarios.
"""

from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import json
import uuid
import random


class DataCategory(Enum):
    """Categories of test data for schema mapping."""
    HAPPY_PATH = "happy_path"
    EDGE_CASE = "edge_case"
    ADVERSARIAL = "adversarial"
    SCHEMA_DRIFT = "schema_drift"


@dataclass
class UserProfile:
    """A user profile record for testing schema mapping."""
    user_id: str
    email: str
    full_name: str
    age: int
    account_balance: Decimal
    is_active: bool
    created_at: datetime
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, handling Decimal serialization."""
        data = asdict(self)
        data['account_balance'] = str(self.account_balance)
        data['created_at'] = self.created_at.isoformat()
        return data


class SchemaMappingMockData:
    """Mock data generator for schema mapping accuracy tests."""
    
    # Target schema definition (what we expect after transformation)
    TARGET_SCHEMA = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "minLength": 1},
            "email": {"type": "string", "format": "email"},
            "full_name": {"type": "string", "minLength": 1},
            "age": {"type": "integer", "minimum": 0, "maximum": 150},
            "account_balance": {"type": "number"},
            "is_active": {"type": "boolean"},
            "created_at": {"type": "string", "format": "date-time"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "metadata": {"type": "object"}
        },
        "required": ["user_id", "email", "full_name", "age", "account_balance", "is_active", "created_at"]
    }
    
    # Source schema variations (simulating different source systems)
    SOURCE_SCHEMAS = {
        "legacy": {
            "user_id": "uid",
            "email": "email_address",
            "full_name": "name",
            "age": "years_old",
            "account_balance": "balance",
            "is_active": "active_flag",
            "created_at": "registration_date"
        },
        "modern": {
            "user_id": "id",
            "email": "contact_email",
            "full_name": "display_name",
            "age": "age_in_years",
            "account_balance": "current_balance",
            "is_active": "status",
            "created_at": "timestamp"
        },
        "external": {
            "user_id": "external_user_id",
            "email": "user_email",
            "full_name": "fullname",
            "age": "age",
            "account_balance": "amt",
            "is_active": "enabled",
            "created_at": "entry_date"
        }
    }
    
    @staticmethod
    def generate_user_id() -> str:
        """Generate a unique user ID."""
        return f"user_{uuid.uuid4().hex[:12]}"
    
    @staticmethod
    def generate_email() -> str:
        """Generate a valid email address."""
        domains = ["example.com", "test.org", "sample.net", "demo.io"]
        return f"user_{random.randint(1000, 9999)}@{random.choice(domains)}"
    
    @staticmethod
    def generate_valid_user(
        include_optional: bool = True,
        category: DataCategory = DataCategory.HAPPY_PATH
    ) -> dict[str, Any]:
        """Generate a valid user record for happy path testing."""
        user_id = SchemaMappingMockData.generate_user_id()
        email = SchemaMappingMockData.generate_email()
        
        base = {
            "user_id": user_id,
            "email": email,
            "full_name": "John Doe",
            "age": random.randint(18, 99),
            "account_balance": round(random.uniform(0, 10000), 2),
            "is_active": random.choice([True, False]),
            "created_at": datetime.now().isoformat(),
        }
        
        if include_optional:
            base["tags"] = ["premium", "newsletter"]
            base["metadata"] = {"source": "web", "version": "1.0"}
        
        return base
    
    @staticmethod
    def generate_edge_case_user(case_type: str) -> dict[str, Any]:
        """Generate edge case user records for boundary testing."""
        base = {
            "user_id": SchemaMappingMockData.generate_user_id(),
            "email": SchemaMappingMockData.generate_email(),
            "full_name": "John Doe",
            "created_at": datetime.now().isoformat(),
        }
        
        edge_cases = {
            "min_age": {**base, "age": 0, "account_balance": 0.0, "is_active": False},
            "max_age": {**base, "age": 150, "account_balance": 999999.99, "is_active": True},
            "empty_name": {**base, "full_name": "", "age": 25, "account_balance": 100.0, "is_active": True},
            "negative_balance": {**base, "full_name": "Negative Test", "age": 30, "account_balance": -500.0, "is_active": True},
            "empty_tags": {**base, "age": 35, "account_balance": 200.0, "is_active": True, "tags": []},
            "null_metadata": {**base, "age": 40, "account_balance": 300.0, "is_active": True, "metadata": None},
            "future_date": {**base, "age": 45, "account_balance": 400.0, "is_active": True, 
                          "created_at": (datetime.now() + timedelta(days=365)).isoformat()},
            "special_chars_name": {**base, "full_name": "José María García-López", "age": 50, "account_balance": 500.0, "is_active": True},
            "unicode_email": {**base, "email": "用户@example.com", "full_name": "Unicode Test", "age": 25, "account_balance": 100.0, "is_active": True},
            "very_long_email": {**base, "email": "a" * 200 + "@example.com", "full_name": "Long Email Test", "age": 30, "account_balance": 150.0, "is_active": True},
        }
        
        return edge_cases.get(case_type, SchemaMappingMockData.generate_valid_user())
    
    @staticmethod
    def generate_adversarial_user(attack_type: str) -> dict[str, Any]:
        """Generate adversarial/malformed user records for security testing."""
        base = {
            "user_id": SchemaMappingMockData.generate_user_id(),
            "email": SchemaMappingMockData.generate_email(),
            "full_name": "Test User",
            "created_at": datetime.now().isoformat(),
        }
        
        adversarial_cases = {
            "type_mismatch_string_number": {**base, "age": "not_a_number", "account_balance": 100.0, "is_active": True},
            "type_mismatch_boolean_string": {**base, "age": 25, "account_balance": 200.0, "is_active": "yes"},
            "type_mismatch_number_boolean": {**base, "age": 30, "account_balance": 300.0, "is_active": 1},
            "invalid_email_format": {**base, "email": "not_an_email", "age": 35, "account_balance": 400.0, "is_active": True},
            "empty_string_required": {**base, "email": "", "age": 40, "account_balance": 500.0, "is_active": True},
            "whitespace_only_name": {**base, "full_name": "   ", "email": "test@test.com", "age": 45, "account_balance": 600.0, "is_active": True},
            "null_in_required": {**base, "email": None, "age": 50, "account_balance": 700.0, "is_active": True},
            "float_in_integer_field": {**base, "age": 25.7, "account_balance": 800.0, "is_active": True},
            "negative_age": {**base, "age": -5, "account_balance": 900.0, "is_active": True},
            "array_in_string_field": {**base, "email": ["test@test.com"], "age": 55, "account_balance": 1000.0, "is_active": True},
            "nested_object_in_string": {**base, "email": "test@test.com", "full_name": {"first": "John", "last": "Doe"}, "age": 60, "account_balance": 1100.0, "is_active": True},
            "sql_injection_name": {**base, "full_name": "'; DROP TABLE users; --", "email": "test@test.com", "age": 65, "account_balance": 1200.0, "is_active": True},
            "xss_script_name": {**base, "full_name": "<script>alert('xss')</script>", "email": "test@test.com", "age": 70, "account_balance": 1300.0, "is_active": True},
            "extremely_large_number": {**base, "age": 75, "account_balance": 1e308, "is_active": True},
            "scientific_notation": {**base, "age": 80, "account_balance": "1.23e5", "is_active": True},
            "date_as_string": {**base, "age": 85, "account_balance": 1500.0, "is_active": True, "created_at": "2024-01-15"},
            "boolean_as_string": {**base, "age": 90, "account_balance": 1600.0, "is_active": "true"},
        }
        
        return adversarial_cases.get(attack_type, SchemaMappingMockData.generate_valid_user())
    
    @staticmethod
    def generate_schema_drift_case(drift_type: str) -> dict[str, Any]:
        """Generate records with schema drift (source schema changes)."""
        base = {
            "user_id": SchemaMappingMockData.generate_user_id(),
            "email": SchemaMappingMockData.generate_email(),
            "full_name": "Test User",
            "created_at": datetime.now().isoformat(),
        }
        
        drift_cases = {
            "new_optional_field": {
                **base, "age": 25, "account_balance": 100.0, "is_active": True,
                "new_field_added": "this field didn't exist before"
            },
            "new_required_field_missing": {
                **base, "age": 30, "account_balance": 200.0, "is_active": True
                # "required_new_field" is missing - this should cause issues
            },
            "field_renamed": {
                "uid": base["user_id"],
                "email_address": base["email"],
                "name": base["full_name"],
                "age": 35,
                "balance": 300.0,
                "active_flag": True,
                "registration_date": base["created_at"]
            },
            "field_type_changed": {
                **base, "age": "25",  # Changed from int to string
                "account_balance": "300.00",  # Changed from float to string
                "is_active": True
            },
            "nested_structure_added": {
                **base, "age": 40, "account_balance": 400.0, "is_active": True,
                "contact_info": {
                    "phone": "555-1234",
                    "address": {
                        "street": "123 Main St",
                        "city": "Anytown"
                    }
                }
            },
            "nested_structure_removed": {
                **base, "age": 45, "account_balance": 500.0, "is_active": True
                # Previously had contact_info, now it's gone
            },
            "array_became_object": {
                **base, "age": 50, "account_balance": 600.0, "is_active": True,
                "tags": {"primary": "vip", "secondary": "premium"}  # Was array, now object
            },
            "object_became_array": {
                **base, "age": 55, "account_balance": 700.0, "is_active": True,
                "metadata": ["item1", "item2", "item3"]  # Was object, now array
            },
            "field_order_changed": {
                "is_active": True,
                "account_balance": 800.0,
                "age": 60,
                "full_name": "Order Change Test",
                "email": "order@example.com",
                "user_id": base["user_id"],
                "created_at": base["created_at"]
            },
            "deep_nesting_added": {
                **base, "age": 65, "account_balance": 900.0, "is_active": True,
                "level1": {
                    "level2": {
                        "level3": {
                            "level4": {
                                "deep_value": "found it"
                            }
                        }
                    }
                }
            }
        }
        
        return drift_cases.get(drift_type, SchemaMappingMockData.generate_valid_user())
    
    @staticmethod
    def transform_legacy_to_target(record: dict, source_schema: dict) -> dict[str, Any]:
        """Transform a legacy record to target schema."""
        transformed = {}
        for target_field, source_field in source_schema.items():
            if source_field in record:
                value = record[source_field]
                # Apply type conversions based on target field
                if target_field == "age":
                    transformed[target_field] = int(value) if value else 0
                elif target_field == "account_balance":
                    transformed[target_field] = float(value) if value else 0.0
                elif target_field == "is_active":
                    if isinstance(value, bool):
                        transformed[target_field] = value
                    elif isinstance(value, str):
                        transformed[target_field] = value.lower() in ("true", "1", "yes")
                    else:
                        transformed[target_field] = bool(value)
                elif target_field == "created_at":
                    # Handle various date formats
                    if isinstance(value, str):
                        try:
                            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                            transformed[target_field] = dt.isoformat()
                        except ValueError:
                            transformed[target_field] = value
                    else:
                        transformed[target_field] = str(value)
                else:
                    transformed[target_field] = value
        return transformed
    
    @staticmethod
    def generate_batch(category: DataCategory, count: int, **kwargs) -> list[dict[str, Any]]:
        """Generate a batch of mock records."""
        generators = {
            DataCategory.HAPPY_PATH: lambda: SchemaMappingMockData.generate_valid_user(**kwargs),
            DataCategory.EDGE_CASE: lambda: SchemaMappingMockData.generate_edge_case_user(
                random.choice(list(SchemaMappingMockData.generate_edge_case_user("").keys()))
            ),
            DataCategory.ADVERSARIAL: lambda: SchemaMappingMockData.generate_adversarial_user(
                random.choice(list(SchemaMappingMockData.generate_adversarial_user("").keys()))
            ),
            DataCategory.SCHEMA_DRIFT: lambda: SchemaMappingMockData.generate_schema_drift_case(
                random.choice(list(SchemaMappingMockData.generate_schema_drift_case("").keys()))
            ),
        }
        
        generator = generators.get(category, generators[DataCategory.HAPPY_PATH])
        return [generator() for _ in range(count)]
    
    @staticmethod
    def get_expected_schema() -> dict[str, Any]:
        """Return the expected target schema for validation."""
        return SchemaMappingMockData.TARGET_SCHEMA


class NestedDataGenerator:
    """Generator for testing nested structure schema mapping."""
    
    @staticmethod
    def generate_nested_record(depth: int = 3, include_all_levels: bool = True) -> dict[str, Any]:
        """Generate a deeply nested record for testing."""
        def create_level(level: int, max_depth: int) -> dict[str, Any]:
            if level > max_depth:
                return f"leaf_value_{level}"
            
            return {
                f"field_{level}_a": create_level(level + 1, max_depth),
                f"field_{level}_b": create_level(level + 1, max_depth),
                f"field_{level}_list": [
                    create_level(level + 1, max_depth) for _ in range(2)
                ] if level < max_depth else ["item1", "item2"]
            }
        
        return create_level(1, depth)
    
    @staticmethod
    def generate_mixed_type_record() -> dict[str, Any]:
        """Generate a record with various data types."""
        return {
            "string_field": "hello world",
            "number_field": 42.5,
            "boolean_field": True,
            "null_field": None,
            "array_field": [1, 2, 3, "four", True],
            "nested_object": {
                "inner_string": "nested_value",
                "inner_number": 123,
                "inner_array": [{"a": 1}, {"b": 2}]
            },
            "deep_nesting": {
                "level1": {
                    "level2": {
                        "level3": {
                            "value": "deep"
                        }
                    }
                }
            }
        }


class StreamingDataGenerator:
    """Generator for streaming/real-time schema mapping tests."""
    
    @staticmethod
    def generate_stream_record(sequence: int) -> dict[str, Any]:
        """Generate a record for streaming test."""
        return {
            "sequence": sequence,
            "timestamp": datetime.now().isoformat(),
            "event_type": random.choice(["login", "purchase", "view", "click"]),
            "user_id": f"user_{random.randint(1, 1000)}",
            "data": {
                "key": f"value_{sequence}",
                "metadata": {"source": "stream", "version": "1.0"}
            }
        }
    
    @staticmethod
    def generate_stream_with_schema_drift(sequence: int, drift_start: int = 50) -> dict[str, Any]:
        """Generate streaming record with schema drift after sequence 50."""
        base = StreamingDataGenerator.generate_stream_record(sequence)
        
        if sequence >= drift_start:
            # Add new field
            base["new_field"] = f"drift_value_{sequence}"
            # Rename a field
            base["old_field_renamed"] = base.pop("event_type", "unknown")
        
        return base


def create_test_datasets() -> dict[str, list[dict]]:
    """Create all test datasets for schema mapping accuracy testing."""
    return {
        "happy_path_valid": SchemaMappingMockData.generate_batch(DataCategory.HAPPY_PATH, 50),
        "happy_path_optional": SchemaMappingMockData.generate_batch(DataCategory.HAPPY_PATH, 20, include_optional=False),
        "edge_cases": SchemaMappingMockData.generate_batch(DataCategory.EDGE_CASE, 30),
        "adversarial_type_mismatch": [
            SchemaMappingMockData.generate_adversarial_user("type_mismatch_string_number"),
            SchemaMappingMockData.generate_adversarial_user("type_mismatch_boolean_string"),
            SchemaMappingMockData.generate_adversarial_user("type_mismatch_number_boolean"),
        ],
        "adversarial_invalid": [
            SchemaMappingMockData.generate_adversarial_user("invalid_email_format"),
            SchemaMappingMockData.generate_adversarial_user("empty_string_required"),
            SchemaMappingMockData.generate_adversarial_user("null_in_required"),
        ],
        "schema_drift_new_fields": [
            SchemaMappingMockData.generate_schema_drift_case("new_optional_field"),
            SchemaMappingMockData.generate_schema_drift_case("new_required_field_missing"),
        ],
        "schema_drift_renamed": [
            SchemaMappingMockData.generate_schema_drift_case("field_renamed"),
        ],
        "schema_drift_type_changes": [
            SchemaMappingMockData.generate_schema_drift_case("field_type_changed"),
        ],
        "nested_structures": [NestedDataGenerator.generate_mixed_type_record()],
        "deep_nesting": [NestedDataGenerator.generate_nested_record(depth=5)],
        "streaming_normal": [StreamingDataGenerator.generate_stream_record(i) for i in range(100)],
        "streaming_with_drift": [StreamingDataGenerator.generate_stream_with_schema_drift(i) for i in range(100)],
    }


if __name__ == "__main__":
    # Generate and save test datasets
    datasets = create_test_datasets()
    
    for name, records in datasets.items():
        filename = f"mocks/data/{name}.json"
        with open(filename, "w") as f:
            json.dump(records, f, indent=2)
        print(f"Generated {len(records)} records for {name}")
    
    print("\nAll test datasets generated successfully!")
