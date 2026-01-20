"""
Mock data generators for CONTRACT-007 custom validator testing.

This module provides mock data for testing various validation scenarios.
"""

from typing import Any
import json


class MockDataGenerator:
    """Generator for mock validation test data."""

    @staticmethod
    def valid_user_data() -> dict:
        """Generate valid user registration data."""
        return {
            "username": "john_doe",
            "email": "john.doe@example.com",
            "age": 25,
            "password": "SecurePass123!",
            "confirm_password": "SecurePass123!",
        }

    @staticmethod
    def invalid_email_data() -> dict:
        """Generate data with invalid email."""
        return {
            "username": "john_doe",
            "email": "not-an-email",
            "age": 25,
        }

    @staticmethod
    def underage_user_data() -> dict:
        """Generate data for underage user."""
        return {
            "username": "young_user",
            "email": "young@example.com",
            "age": 16,
        }

    @staticmethod
    def password_mismatch_data() -> dict:
        """Generate data with mismatched passwords."""
        return {
            "username": "user",
            "email": "user@example.com",
            "password": "Password123!",
            "confirm_password": "DifferentPassword123!",
        }

    @staticmethod
    def empty_username_data() -> dict:
        """Generate data with empty username."""
        return {
            "username": "",
            "email": "user@example.com",
        }

    @staticmethod
    def negative_number_data() -> dict:
        """Generate data with negative number."""
        return {
            "quantity": -5,
            "price": 10.99,
        }

    @staticmethod
    def too_long_string_data() -> dict:
        """Generate data with string exceeding max length."""
        return {
            "description": "x" * 1001,  # Max is 1000
        }

    @staticmethod
    def valid_order_data() -> dict:
        """Generate valid order data."""
        return {
            "order_id": "ORD-001",
            "customer_id": "CUST-001",
            "items": [
                {"product_id": "PROD-001", "quantity": 2, "price": 19.99},
                {"product_id": "PROD-002", "quantity": 1, "price": 29.99},
            ],
            "total": 69.97,
            "status": "pending",
            "shipping_address": {
                "street": "123 Main St",
                "city": "Anytown",
                "zip": "12345",
            },
        }

    @staticmethod
    def invalid_order_status_data() -> dict:
        """Generate order data with invalid status."""
        return {
            "order_id": "ORD-002",
            "customer_id": "CUST-001",
            "items": [{"product_id": "PROD-001", "quantity": 1, "price": 10.00}],
            "total": 10.00,
            "status": "invalid_status",  # Not in allowed values
        }

    @staticmethod
    def empty_order_items_data() -> dict:
        """Generate order with no items."""
        return {
            "order_id": "ORD-003",
            "customer_id": "CUST-001",
            "items": [],
            "total": 0,
            "status": "pending",
        }

    @staticmethod
    def valid_date_range_data() -> dict:
        """Generate valid date range data."""
        return {
            "event_name": "Conference",
            "start_date": "2024-01-01",
            "end_date": "2024-01-05",
        }

    @staticmethod
    def invalid_date_range_data() -> dict:
        """Generate invalid date range (end before start)."""
        return {
            "event_name": "Conference",
            "start_date": "2024-01-05",
            "end_date": "2024-01-01",  # Before start
        }

    @staticmethod
    def valid_product_data() -> dict:
        """Generate valid product data."""
        return {
            "product_id": "PROD-001",
            "name": "Widget Pro",
            "price": 49.99,
            "stock": 100,
            "category": "electronics",
            "sku": "WGT-PRO-001",
        }

    @staticmethod
    def invalid_product_data() -> dict:
        """Generate invalid product data (multiple issues)."""
        return {
            "product_id": "",  # Empty
            "name": "x" * 101,  # Too long (max 100)
            "price": -10,  # Negative
            "stock": "invalid",  # Wrong type
            "category": "invalid_category",  # Not allowed
        }

    @staticmethod
    def valid_shipping_data() -> dict:
        """Generate valid shipping data."""
        return {
            "address": {
                "street": "123 Main St",
                "city": "Anytown",
                "state": "CA",
                "zip": "12345",
                "country": "US",
            },
            "weight": 5.5,
            "carrier": "UPS",
            "service_level": "ground",
        }

    @staticmethod
    def invalid_shipping_zip_data() -> dict:
        """Generate shipping data with invalid zip code."""
        return {
            "address": {
                "street": "123 Main St",
                "city": "Anytown",
                "state": "CA",
                "zip": "invalid-zip",  # Invalid format
                "country": "US",
            },
            "weight": 5.5,
            "carrier": "UPS",
            "service_level": "ground",
        }

    @staticmethod
    def valid_payment_data() -> dict:
        """Generate valid payment data."""
        return {
            "amount": 99.99,
            "currency": "USD",
            "method": "credit_card",
            "card_last_four": "4242",
            "expiry_month": 12,
            "expiry_year": 2025,
        }

    @staticmethod
    def invalid_payment_data() -> dict:
        """Generate invalid payment data."""
        return {
            "amount": -50,  # Negative
            "currency": "INVALID",  # Not allowed
            "method": "bitcoin",  # Not supported
            "card_last_four": "123",  # Too short
            "expiry_month": 13,  # Invalid month
            "expiry_year": 2020,  # Expired
        }

    @staticmethod
    def edge_case_null_data() -> dict:
        """Generate data with null values."""
        return {
            "required_field": None,
            "optional_field": "value",
        }

    @staticmethod
    def edge_case_empty_data() -> dict:
        """Generate data with empty collections."""
        return {
            "items": [],
            "tags": [],
            "metadata": {},
        }

    @staticmethod
    def edge_case_boundary_values() -> dict:
        """Generate data at boundary values."""
        return {
            "age_min": 18,  # Exactly minimum
            "age_max": 120,  # Exactly maximum
            "quantity_min": 1,  # Exactly minimum
            "price_zero": 0.00,  # Exactly zero
            "percentage_100": 100,  # Exactly 100%
        }

    @staticmethod
    def edge_case_unicode_data() -> dict:
        """Generate data with unicode characters."""
        return {
            "name": "José García",
            "city": "München",
            "description": "Emoji test 🎉",
            "chinese": "中文测试",
        }

    @staticmethod
    def edge_case_whitespace_data() -> dict:
        """Generate data with excessive whitespace."""
        return {
            "name": "   John   ",
            "email": "  john@example.com  ",
            "description": "\t\nLeading and trailing whitespace\n\t",
        }

    @staticmethod
    def adversarial_sql_injection() -> dict:
        """Generate SQL injection attempt."""
        return {
            "username": "'; DROP TABLE users; --",
            "email": "admin'--@example.com",
            "search": "' OR '1'='1",
        }

    @staticmethod
    def adversarial_xss() -> dict:
        """Generate XSS attempt."""
        return {
            "comment": "<script>alert('xss')</script>",
            "name": "<img src=x onerror=alert(1)>",
            "bio": "javascript:alert('xss')",
        }

    @staticmethod
    def adversarial_unicode_overflow() -> dict:
        """Generate unicode boundary case."""
        return {
            "name": "Ü" * 10000,  # Long unicode string
            "description": "\u0000" * 100,  # Null bytes
        }

    @staticmethod
    def scale_data_batch(count: int) -> list[dict]:
        """Generate a batch of data for load testing."""
        return [
            {
                "id": i,
                "name": f"User {i}",
                "email": f"user{i}@example.com",
                "age": 20 + (i % 50),
            }
            for i in range(count)
        ]

    @staticmethod
    def concurrent_user_data() -> dict:
        """Generate data simulating concurrent users."""
        return {
            "session_id": "sess-abc123",
            "user_id": "user-001",
            "action": "purchase",
            "timestamp": "2024-01-19T10:00:00Z",
            "items": [
                {"product_id": f"PROD-{i:03d}", "quantity": 1}
                for i in range(10)
            ],
        }

    @staticmethod
    def complex_nested_data() -> dict:
        """Generate complex nested data structure."""
        return {
            "organization": {
                "name": "Acme Corp",
                "departments": [
                    {
                        "name": "Engineering",
                        "teams": [
                            {
                                "name": "Backend",
                                "members": [
                                    {
                                        "id": f"emp-{i}",
                                        "name": f"Engineer {i}",
                                        "role": "developer",
                                        "skills": ["python", "go", "rust"],
                                    }
                                    for i in range(5)
                                ],
                            }
                        ],
                    }
                ],
            }
        }
