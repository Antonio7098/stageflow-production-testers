"""
Mock Data Generators for CONTRACT-006: Nested Object Validation Depth Testing

This module provides test data generators for various nested object scenarios.
"""

import json
import random
from typing import Any


def generate_nested_dict(
    depth: int,
    max_width: int = 3,
    current_depth: int = 0
) -> dict[str, Any]:
    """Generate a nested dictionary to specified depth.
    
    Args:
        depth: Maximum nesting depth
        max_width: Maximum number of keys at each level
        current_depth: Current recursion depth
    """
    if current_depth >= depth:
        return {"value": f"leaf_{current_depth}"}
    
    num_keys = random.randint(1, max_width)
    result = {}
    for i in range(num_keys):
        key = f"field_{i}"
        if current_depth < depth - 1:
            result[key] = generate_nested_dict(depth, max_width, current_depth + 1)
        else:
            result[key] = f"value_{i}_{current_depth}"
    
    return result


def generate_deeply_nested_with_type_mismatch(depth: int) -> dict[str, Any]:
    """Generate deeply nested dict with intentional type mismatch at specified depth.
    
    Args:
        depth: Target depth for type mismatch
    """
    def build(current_depth: int) -> Any:
        if current_depth == depth:
            return "string_should_be_dict"  # Type mismatch!
        
        return {f"level_{current_depth}": build(current_depth + 1)}
    
    return {"root": build(0)}


def generate_circular_reference() -> dict[str, Any]:
    """Generate a structure with circular reference."""
    result = {"name": "parent", "children": []}
    child = {"name": "child", "parent": result}  # Circular ref
    result["children"].append(child)
    return result


def generate_mixed_type_nesting(depth: int) -> dict[str, Any]:
    """Generate nesting with mixed types (dict, list, primitives).
    
    Args:
        depth: Number of nesting levels
    """
    result = {}
    for i in range(depth):
        level_type = i % 3
        key = f"level_{i}"
        
        if level_type == 0:
            result[key] = {f"sub_{i}": f"value_{i}"}
        elif level_type == 1:
            result[key] = [f"item_{i}_0", f"item_{i}_1"]
        else:
            result[key] = f"primitive_{i}"
    
    return result


def generate_empty_structure_nesting(depth: int) -> dict[str, Any]:
    """Generate nesting with empty dicts and lists at various levels.
    
    Args:
        depth: Number of nesting levels
    """
    result = {}
    for i in range(depth):
        if i % 2 == 0:
            result[f"empty_dict_{i}"] = {}
        else:
            result[f"empty_list_{i}"] = []
    return result


def generate_max_depth_structure() -> dict[str, Any]:
    """Generate maximum depth structure (15 levels)."""
    result = {}
    current = result
    for i in range(15):
        current[f"level_{i}"] = {}
        current = current[f"level_{i}"]
    current["deep_value"] = "reached_15_levels"
    return result


def generate_healthcare_fhir_pattern() -> dict[str, Any]:
    """Generate HL7 FHIR-like nested structure for healthcare."""
    return {
        "resourceType": "Patient",
        "id": "patient-123",
        "identifier": [
            {
                "system": "http://hospital.example.org",
                "value": "MRN-456789"
            }
        ],
        "name": [
            {
                "use": "official",
                "family": "Smith",
                "given": ["John", "David"]
            }
        ],
        "telecom": [
            {
                "system": "phone",
                "value": "555-123-4567",
                "use": "home"
            }
        ],
        "address": [
            {
                "use": "home",
                "line": ["123 Main St"],
                "city": "Boston",
                "state": "MA",
                "postalCode": "02101",
                "country": "USA"
            }
        ]
    }


def generate_financial_portfolio_pattern() -> dict[str, Any]:
    """Generate financial portfolio-like nested structure."""
    return {
        "portfolio_id": "PF-001",
        "holdings": [
            {
                "security": {
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "exchange": "NASDAQ"
                },
                "quantity": 100,
                "pricing": {
                    "current": 175.50,
                    "history": [
                        {"date": "2024-01-01", "close": 170.00},
                        {"date": "2024-01-02", "close": 172.50}
                    ],
                    "adjustments": {
                        "dividend": 0.24,
                        "splits": [4, 1]
                    }
                }
            }
        ],
        "valuation": {
            "total": 17550.00,
            "currency": "USD",
            "as_of": "2024-01-19T12:00:00Z"
        }
    }


def generate_schema_validation_test_case(
    depth: int,
    include_invalid: bool = True
) -> dict[str, Any]:
    """Generate test case for schema validation testing.
    
    Args:
        depth: Nesting depth
        include_invalid: Whether to include invalid data
    """
    structure = generate_nested_dict(depth, max_width=2)
    
    if include_invalid:
        # Inject invalid data at various levels
        current = structure
        for i in range(min(depth, 5)):
            keys = list(current.keys())
            if keys:
                current[keys[0]] = "should_be_dict_not_string"
                break
    
    return structure


class MockNestedDataGenerator:
    """Generator for various nested data test scenarios."""
    
    def __init__(self, seed: int = 42):
        random.seed(seed)
    
    def get_happy_path_data(self) -> dict[str, Any]:
        """Generate valid nested data for happy path tests."""
        return {
            "user": {
                "profile": {
                    "name": "John Doe",
                    "email": "john@example.com",
                    "settings": {
                        "theme": "dark",
                        "notifications": True
                    }
                },
                "history": [
                    {"action": "login", "timestamp": "2024-01-19T10:00:00Z"},
                    {"action": "purchase", "timestamp": "2024-01-19T10:30:00Z"}
                ]
            }
        }
    
    def get_edge_case_data(self) -> list[dict[str, Any]]:
        """Generate edge case test data."""
        return [
            generate_max_depth_structure(),
            generate_empty_structure_nesting(10),
            generate_mixed_type_nesting(5),
            {"": {"valid_key": "value"}},  # Empty string key
            {"key.with.dots": {"nested": "value"}},  # Keys with dots
            {"key": [1, 2, 3]},  # Array at leaf
        ]
    
    def get_adversarial_data(self) -> list[dict[str, Any]]:
        """Generate adversarial/malformed test data."""
        return [
            generate_circular_reference(),
            generate_deeply_nested_with_type_mismatch(10),
            {"valid": "string"},  # Key with dict value, but dict has wrong type
            {"nested": {"deep": {"array": "should_be_dict"}}},  # Type mismatch at depth
            {"unicode_key_你好": "value"},  # Non-ASCII key
            {"key": None},  # Null value
        ]
    
    def get_scale_data(self, count: int = 1000) -> list[dict[str, Any]]:
        """Generate large volume of nested data for scale testing."""
        return [generate_nested_dict(depth=5, max_width=3) for _ in range(count)]
    
    def get_depth_benchmark_data(self) -> dict[int, dict[str, Any]]:
        """Generate data at various depths for benchmarking."""
        return {
            depth: generate_nested_dict(depth, max_width=2)
            for depth in [1, 3, 5, 7, 10, 15, 20]
        }


if __name__ == "__main__":
    generator = MockNestedDataGenerator()
    
    # Save test data to files
    import os
    
    output_dir = "mocks/data"
    os.makedirs(output_dir, exist_ok=True)
    
    # Happy path
    with open(f"{output_dir}/happy_path.json", "w") as f:
        json.dump(generator.get_happy_path_data(), f, indent=2)
    
    # Edge cases
    with open(f"{output_dir}/edge_cases.json", "w") as f:
        json.dump(generator.get_edge_case_data(), f, indent=2)
    
    # Adversarial
    with open(f"{output_dir}/adversarial.json", "w") as f:
        json.dump(generator.get_adversarial_data(), f, indent=2)
    
    # Scale data
    scale_data = generator.get_scale_data(100)
    with open(f"{output_dir}/scale_sample.json", "w") as f:
        json.dump(scale_data[:10], f, indent=2)  # Save first 10 for preview
    
    print("Mock data generated successfully!")
    print(f"  - Happy path: {output_dir}/happy_path.json")
    print(f"  - Edge cases: {output_dir}/edge_cases.json")
    print(f"  - Adversarial: {output_dir}/adversarial.json")
    print(f"  - Scale sample: {output_dir}/scale_sample.json")
