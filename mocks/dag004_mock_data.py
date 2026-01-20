"""
DAG-004: Starvation of Low-Priority Jobs - Mock Data Generation

This module provides realistic mock data for simulating starvation scenarios
in the Stageflow framework.

Industry Persona: Financial Services - Compliance & Risk Management
"""

import asyncio
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class TransactionRequest:
    """Mock high-priority transaction data."""
    transaction_id: str
    amount: float
    timestamp: datetime
    merchant_id: str
    customer_id: str
    risk_score: float = 0.0
    priority: int = 10  # High priority (lower = higher)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "amount": self.amount,
            "timestamp": self.timestamp.isoformat(),
            "merchant_id": self.merchant_id,
            "customer_id": self.customer_id,
            "risk_score": self.risk_score,
            "priority": self.priority,
        }


@dataclass
class ComplianceReport:
    """Mock low-priority compliance audit data."""
    report_id: str
    transaction_batch_id: str
    created_at: datetime
    status: str = "pending"
    priority: int = 100  # Low priority (higher = lower)
    data_size_kb: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "transaction_batch_id": self.transaction_batch_id,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
            "priority": self.priority,
            "data_size_kb": self.data_size_kb,
        }


class MockTransactionGenerator:
    """Generates continuous stream of high-priority transaction data."""

    def __init__(self, rate_per_second: int = 100):
        self.rate_per_second = rate_per_second
        self.running = False
        self._counter = 0

    async def start(self):
        """Start generating transactions."""
        self.running = True

    async def stop(self):
        """Stop generating transactions."""
        self.running = False

    async def generate_batch(self, count: int) -> list[TransactionRequest]:
        """Generate a batch of transactions."""
        batch = []
        for i in range(count):
            self._counter += 1
            tx = TransactionRequest(
                transaction_id=f"txn_{uuid.uuid4().hex[:12]}",
                amount=round(random.uniform(10.0, 10000.0), 2),
                timestamp=datetime.now(),
                merchant_id=f"merchant_{random.randint(1, 1000):04d}",
                customer_id=f"cust_{random.randint(1, 10000):05d}",
                risk_score=random.uniform(0.0, 1.0),
                priority=random.randint(1, 10),  # Always high priority
            )
            batch.append(tx)
        return batch

    def generate_single(self) -> TransactionRequest:
        """Generate a single transaction."""
        self._counter += 1
        return TransactionRequest(
            transaction_id=f"txn_{uuid.uuid4().hex[:12]}",
            amount=round(random.uniform(10.0, 10000.0), 2),
            timestamp=datetime.now(),
            merchant_id=f"merchant_{random.randint(1, 1000):04d}",
            customer_id=f"cust_{random.randint(1, 10000):05d}",
            risk_score=random.uniform(0.0, 1.0),
            priority=random.randint(1, 10),
        )


class MockComplianceGenerator:
    """Generates low-priority compliance report data."""

    def __init__(self):
        self._counter = 0

    def generate_report(self, batch_id: str) -> ComplianceReport:
        """Generate a compliance report for a transaction batch."""
        self._counter += 1
        return ComplianceReport(
            report_id=f"rpt_{uuid.uuid4().hex[:12]}",
            transaction_batch_id=batch_id,
            created_at=datetime.now(),
            status="pending",
            priority=100,  # Low priority
            data_size_kb=random.randint(100, 5000),
        )


class MockRateLimiter:
    """
    Simulates rate limiting for external API calls.
    Used to create resource contention scenarios.
    """

    def __init__(self, max_concurrent: int = 10, rate_per_second: int = 50):
        self.max_concurrent = max_concurrent
        self.rate_per_second = rate_per_second
        self._available_slots = asyncio.Semaphore(max_concurrent)
        self._rate_limit = asyncio.Semaphore(rate_per_second)
        self._usage_stats = {
            "total_requests": 0,
            "rate_limited": 0,
            "concurrent_limited": 0,
            "successful": 0,
        }

    async def acquire(self, timeout: float = 5.0) -> bool:
        """Acquire both concurrent and rate limit slots."""
        try:
            await asyncio.wait_for(self._available_slots.acquire(), timeout=timeout)
            try:
                await asyncio.wait_for(self._rate_limit.acquire(), timeout=timeout)
                self._usage_stats["total_requests"] += 1
                self._usage_stats["successful"] += 1
                return True
            except asyncio.TimeoutError:
                self._available_slots.release()
                self._usage_stats["total_requests"] += 1
                self._usage_stats["rate_limited"] += 1
                return False
        except asyncio.TimeoutError:
            self._usage_stats["total_requests"] += 1
            self._usage_stats["concurrent_limited"] += 1
            return False

    def release(self):
        """Release slots back to the pool."""
        self._available_slots.release()
        self._rate_limit.release()

    def get_stats(self) -> dict[str, int]:
        return self._usage_stats.copy()

    def reset(self):
        self._available_slots = asyncio.Semaphore(self.max_concurrent)
        self._rate_limit = asyncio.Semaphore(self.rate_per_second)
        self._usage_stats = {
            "total_requests": 0,
            "rate_limited": 0,
            "concurrent_limited": 0,
            "successful": 0,
        }


class WorkloadSimulator:
    """
    Simulates realistic workload patterns with mixed priorities.
    Used for starvation testing.
    """

    def __init__(
        self,
        high_priority_rate: int = 100,  # transactions per second
        low_priority_rate: int = 5,      # reports per second
        burst_probability: float = 0.3,
    ):
        self.high_priority_rate = high_priority_rate
        self.low_priority_rate = low_priority_rate
        self.burst_probability = burst_probability
        self.transaction_gen = MockTransactionGenerator(high_priority_rate)
        self.compliance_gen = MockComplianceGenerator()
        self._running = False

    async def start(self):
        """Start the workload simulator."""
        self._running = True
        await self.transaction_gen.start()

    async def stop(self):
        """Stop the workload simulator."""
        self._running = False
        await self.transaction_gen.stop()

    async def generate_high_priority_work(self) -> list[TransactionRequest]:
        """Generate high-priority transaction work."""
        if not self._running:
            return []

        # Simulate burst behavior
        if random.random() < self.burst_probability:
            count = random.randint(10, 50)
        else:
            count = random.randint(1, 10)

        return await self.transaction_gen.generate_batch(count)

    async def generate_low_priority_work(self, batch_id: str) -> ComplianceReport:
        """Generate low-priority compliance work."""
        if not self._running:
            return None

        # Throttle low-priority work
        await asyncio.sleep(1.0 / self.low_priority_rate)
        return self.compliance_gen.generate_report(batch_id)

    def get_stats(self) -> dict[str, Any]:
        return {
            "high_priority_rate": self.high_priority_rate,
            "low_priority_rate": self.low_priority_rate,
            "burst_probability": self.burst_probability,
        }


# Test scenarios configuration
STARVATION_TEST_CONFIGS = {
    "baseline": {
        "description": "Normal operation - equal priority",
        "high_priority_rate": 10,
        "low_priority_rate": 10,
        "burst_probability": 0.1,
    },
    "moderate_load": {
        "description": "High load with priority difference",
        "high_priority_rate": 50,
        "low_priority_rate": 5,
        "burst_probability": 0.2,
    },
    "severe_load": {
        "description": "Severe starvation conditions",
        "high_priority_rate": 200,
        "low_priority_rate": 2,
        "burst_probability": 0.5,
    },
    "resource_contention": {
        "description": "Rate-limited resource pool contention",
        "high_priority_rate": 100,
        "low_priority_rate": 10,
        "max_concurrent": 5,
        "rate_per_second": 20,
    },
}
