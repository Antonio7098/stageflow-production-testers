"""
Rate Limit Test Data Generators

Generates realistic test data for Stageflow rate limit handling tests.
Includes happy path, edge cases, adversarial inputs, and scale scenarios.
"""

import random
import string
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timedelta


@dataclass
class RateLimitTestCase:
    """Single test case for rate limit handling."""
    name: str
    description: str
    rpm: int
    burst: int
    request_count: int
    expected_behavior: str
    severity: str = "normal"  # normal, edge, adversarial
    notes: str = ""


@dataclass
class RateLimitScenario:
    """Collection of related test cases."""
    name: str
    description: str
    test_cases: list[RateLimitTestCase]


class RateLimitTestDataGenerator:
    """Generates test data for rate limit handling scenarios."""
    
    # Standard test scenarios
    SCENARIOS = {
        "happy_path": RateLimitScenario(
            name="happy_path",
            description="Normal operation within rate limits",
            test_cases=[
                RateLimitTestCase(
                    name="single_request",
                    description="Single request within limits",
                    rpm=60, burst=10, request_count=1,
                    expected_behavior="all_requests_succeed"
                ),
                RateLimitTestCase(
                    name="burst_normal",
                    description="Normal burst within burst size",
                    rpm=60, burst=10, request_count=5,
                    expected_behavior="all_requests_succeed"
                ),
                RateLimitTestCase(
                    name="sustained_load",
                    description="Sustained load at 50% capacity",
                    rpm=60, burst=10, request_count=30,
                    expected_behavior="all_requests_succeed"
                ),
            ]
        ),
        "rate_limit_edge_cases": RateLimitScenario(
            name="rate_limit_edge_cases",
            description="Edge cases around rate limit boundaries",
            test_cases=[
                RateLimitTestCase(
                    name="at_limit",
                    description="Requests exactly at limit",
                    rpm=5, burst=5, request_count=5,
                    expected_behavior="all_requests_succeed"
                ),
                RateLimitTestCase(
                    name="over_limit_single",
                    description="Single request over limit",
                    rpm=5, burst=5, request_count=6,
                    expected_behavior="last_request_rate_limited"
                ),
                RateLimitTestCase(
                    name="burst_at_boundary",
                    description="Burst exactly at boundary",
                    rpm=60, burst=10, request_count=10,
                    expected_behavior="all_requests_succeed"
                ),
                RateLimitTestCase(
                    name="burst_over_boundary",
                    description="Burst over boundary",
                    rpm=60, burst=10, request_count=11,
                    expected_behavior="last_request_rate_limited"
                ),
                RateLimitTestCase(
                    name="rapid_succession",
                    description="Back-to-back requests",
                    rpm=60, burst=10, request_count=20,
                    expected_behavior="initial_succeed_then_rate_limited"
                ),
            ]
        ),
        "retry_scenarios": RateLimitScenario(
            name="retry_scenarios",
            description="Retry behavior with exponential backoff",
            test_cases=[
                RateLimitTestCase(
                    name="immediate_retry_success",
                    description="Retry succeeds on first attempt",
                    rpm=5, burst=1, request_count=2,
                    expected_behavior="retry_succeeds",
                    notes="First request rate limited, second succeeds"
                ),
                RateLimitTestCase(
                    name="multiple_retry_success",
                    description="Multiple retries before success",
                    rpm=5, burst=1, request_count=4,
                    expected_behavior="multiple_retries_succeed",
                    notes="Requires 3 retries before success"
                ),
                RateLimitTestCase(
                    name="retry_exhaustion",
                    description="Max retries exceeded",
                    rpm=5, burst=1, request_count=10,
                    expected_behavior="all_retries_exhausted",
                    notes="All retries fail, final error"
                ),
            ]
        ),
        "adversarial_inputs": RateLimitScenario(
            name="adversarial_inputs",
            description="Adversarial and malformed inputs",
            test_cases=[
                RateLimitTestCase(
                    name="malformed_retry_header",
                    description="Malformed Retry-After header",
                    rpm=5, burst=1, request_count=2,
                    expected_behavior="graceful_fallback",
                    severity="adversarial"
                ),
                RateLimitTestCase(
                    name="zero_retry_after",
                    description="Zero Retry-After value",
                    rpm=5, burst=1, request_count=2,
                    expected_behavior="uses_default_backoff",
                    severity="adversarial"
                ),
                RateLimitTestCase(
                    name="negative_retry_after",
                    description="Negative Retry-After value",
                    rpm=5, burst=1, request_count=2,
                    expected_behavior="uses_default_backoff",
                    severity="adversarial"
                ),
                RateLimitTestCase(
                    name="very_large_retry_after",
                    description="Very large Retry-After value",
                    rpm=5, burst=1, request_count=2,
                    expected_behavior="respects_large_backoff",
                    severity="adversarial"
                ),
                RateLimitTestCase(
                    name="spam_requests",
                    description="Rapid spam requests",
                    rpm=5, burst=1, request_count=50,
                    expected_behavior="controlled_degradation",
                    severity="adversarial"
                ),
            ]
        ),
        "concurrency_scenarios": RateLimitScenario(
            name="concurrency_scenarios",
            description="Concurrent request handling",
            test_cases=[
                RateLimitTestCase(
                    name="concurrent_burst",
                    description="Burst of concurrent requests",
                    rpm=10, burst=10, request_count=10,
                    expected_behavior="all_concurrent_succeed",
                    notes="All 10 requests concurrent within burst"
                ),
                RateLimitTestCase(
                    name="concurrent_over_limit",
                    description="Concurrent requests over limit",
                    rpm=10, burst=5, request_count=10,
                    expected_behavior="partial_concurrent_success",
                    notes="5 succeed, 5 rate limited"
                ),
                RateLimitTestCase(
                    name="high_concurrency",
                    description="High concurrency stress test",
                    rpm=100, burst=20, request_count=50,
                    expected_behavior="managed_high_concurrency",
                    notes="50 concurrent requests"
                ),
            ]
        ),
        "performance_scale": RateLimitScenario(
            name="performance_scale",
            description="Performance and scale scenarios",
            test_cases=[
                RateLimitTestCase(
                    name="sustained_high_load",
                    description="Sustained high load",
                    rpm=1000, burst=100, request_count=500,
                    expected_behavior="sustained_high_throughput",
                    notes="500 requests over 5 minutes"
                ),
                RateLimitTestCase(
                    name="stress_test",
                    description="Maximum stress test",
                    rpm=5000, burst=500, request_count=2000,
                    expected_behavior="maximum_throughput",
                    notes="2000 requests at high rate"
                ),
                RateLimitTestCase(
                    name="memory_pressure",
                    description="Memory under sustained load",
                    rpm=1000, burst=100, request_count=5000,
                    expected_behavior="bounded_memory_usage",
                    notes="Monitor memory during extended test"
                ),
            ]
        ),
        "algorithm_comparison": RateLimitScenario(
            name="algorithm_comparison",
            description="Compare different rate limiting algorithms",
            test_cases=[
                RateLimitTestCase(
                    name="token_bucket_burst",
                    description="Token bucket with burst",
                    rpm=60, burst=20, request_count=20,
                    expected_behavior="burst_tolerated",
                    notes="Higher burst tolerance expected"
                ),
                RateLimitTestCase(
                    name="fixed_window_boundary",
                    description="Fixed window boundary behavior",
                    rpm=10, burst=10, request_count=20,
                    expected_behavior="window_boundary_spike",
                    notes="May see spike at window boundary"
                ),
                RateLimitTestCase(
                    name="sliding_window_smooth",
                    description="Sliding window smoothness",
                    rpm=10, burst=10, request_count=20,
                    expected_behavior="smooth_distribution",
                    notes="More even distribution expected"
                ),
            ]
        ),
    }
    
    def __init__(self, seed: int = 42):
        """Initialize with optional seed for reproducibility."""
        self.seed = seed
        random.seed(seed)
    
    def generate_scenario(self, scenario_name: str) -> RateLimitScenario:
        """Generate a specific scenario by name."""
        if scenario_name not in self.SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario_name}")
        return self.SCENARIOS[scenario_name]
    
    def generate_all_scenarios(self) -> list[RateLimitScenario]:
        """Generate all defined scenarios."""
        return list(self.SCENARIOS.values())
    
    def generate_test_messages(self, count: int = 1) -> list[list[dict]]:
        """Generate test message sets."""
        messages = [
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": self._random_text(50, 200)}
            ]
            for _ in range(count)
        ]
        return messages
    
    def _random_text(self, min_words: int, max_words: int) -> str:
        """Generate random text for test messages."""
        words = []
        word_count = random.randint(min_words, max_words)
        for _ in range(word_count):
            length = random.randint(3, 12)
            word = ''.join(random.choices(string.ascii_lowercase, k=length))
            words.append(word)
        return ' '.join(words)
    
    def get_expected_results(self, test_case: RateLimitTestCase) -> dict[str, Any]:
        """Get expected results for a test case."""
        behavior = test_case.expected_behavior
        
        expected = {
            "all_requests_succeed": {
                "success_rate": 1.0,
                "rate_limited_count": 0,
                "retry_count": 0
            },
            "last_request_rate_limited": {
                "success_rate": (test_case.request_count - 1) / test_case.request_count,
                "rate_limited_count": 1,
                "retry_count": 0
            },
            "initial_succeed_then_rate_limited": {
                "success_rate": min(test_case.burst, test_case.request_count) / test_case.request_count,
                "rate_limited_count": test_case.request_count - min(test_case.burst, test_case.request_count),
                "retry_count": 0
            },
            "retry_succeeds": {
                "success_rate": 1.0,
                "rate_limited_count": 0,
                "retry_count": 1
            },
            "multiple_retries_succeed": {
                "success_rate": 1.0,
                "rate_limited_count": 0,
                "retry_count": 2
            },
            "all_retries_exhausted": {
                "success_rate": 0.0,
                "rate_limited_count": test_case.request_count,
                "retry_count": test_case.request_count * 5  # 5 retries per request
            },
            "graceful_fallback": {
                "success_rate": 0.5,
                "rate_limited_count": 1,
                "retry_count": 1
            },
            "uses_default_backoff": {
                "success_rate": 0.5,
                "rate_limited_count": 1,
                "retry_count": 1
            },
            "respects_large_backoff": {
                "success_rate": 0.5,
                "rate_limited_count": 1,
                "retry_count": 1,
                "wait_time": ">60s"
            },
            "controlled_degradation": {
                "success_rate": 0.0,
                "rate_limited_count": 50,
                "retry_count": 250,
                "notes": "All spam requests properly rate limited"
            },
            "all_concurrent_succeed": {
                "success_rate": 1.0,
                "rate_limited_count": 0,
                "retry_count": 0
            },
            "partial_concurrent_success": {
                "success_rate": 0.5,
                "rate_limited_count": 5,
                "retry_count": 0
            },
            "managed_high_concurrency": {
                "success_rate": 1.0,
                "rate_limited_count": 0,
                "retry_count": 0
            },
            "sustained_high_throughput": {
                "success_rate": 0.99,
                "rate_limited_count": 5,
                "retry_count": 5
            },
            "maximum_throughput": {
                "success_rate": 0.98,
                "rate_limited_count": 40,
                "retry_count": 40
            },
            "bounded_memory_usage": {
                "success_rate": 0.99,
                "rate_limited_count": 50,
                "retry_count": 50,
                "memory_delta_mb": "<50"
            },
            "burst_tolerated": {
                "success_rate": 1.0,
                "rate_limited_count": 0,
                "retry_count": 0
            },
            "window_boundary_spike": {
                "success_rate": 0.9,
                "rate_limited_count": 2,
                "retry_count": 0,
                "notes": "Spike at window boundary expected"
            },
            "smooth_distribution": {
                "success_rate": 1.0,
                "rate_limited_count": 0,
                "retry_count": 0,
                "notes": "Smooth rate distribution expected"
            }
        }
        
        return expected.get(behavior, {
            "success_rate": 0.0,
            "rate_limited_count": test_case.request_count,
            "retry_count": 0
        })


def create_test_data(seed: int = 42) -> RateLimitTestDataGenerator:
    """Factory function to create test data generator."""
    return RateLimitTestDataGenerator(seed)


# Example usage
if __name__ == "__main__":
    generator = create_test_data()
    
    print("Rate Limit Test Data Generator")
    print("=" * 50)
    print()
    
    # List all scenarios
    print("Available scenarios:")
    for scenario in generator.generate_all_scenarios():
        print(f"  - {scenario.name}: {scenario.description}")
        for test_case in scenario.test_cases:
            print(f"    * {test_case.name}: {test_case.description}")
    print()
    
    # Generate test data for happy path
    scenario = generator.generate_scenario("happy_path")
    print(f"Generating data for: {scenario.name}")
    print("-" * 40)
    
    for test_case in scenario.test_cases:
        messages = generator.generate_test_messages(test_case.request_count)
        expected = generator.get_expected_results(test_case)
        print(f"\nTest: {test_case.name}")
        print(f"  Requests: {test_case.request_count}")
        print(f"  RPM: {test_case.rpm}, Burst: {test_case.burst}")
        print(f"  Expected: {test_case.expected_behavior}")
        print(f"  Expected results: {expected}")
