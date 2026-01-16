"""
Stageflow Stress-Testing: Shared Pytest Configuration

Common fixtures and utilities for all stress tests.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

import pytest


# =============================================================================
# Path Fixtures
# =============================================================================

@pytest.fixture
def run_dir() -> Path:
    """Get the current run directory."""
    # Assumes tests are run from within a run directory
    return Path.cwd()


@pytest.fixture
def results_dir(run_dir: Path) -> Path:
    """Get or create the results directory."""
    results = run_dir / "results"
    results.mkdir(exist_ok=True)
    return results


@pytest.fixture
def metrics_dir(results_dir: Path) -> Path:
    """Get or create the metrics directory."""
    metrics = results_dir / "metrics"
    metrics.mkdir(exist_ok=True)
    return metrics


@pytest.fixture
def traces_dir(results_dir: Path) -> Path:
    """Get or create the traces directory."""
    traces = results_dir / "traces"
    traces.mkdir(exist_ok=True)
    return traces


@pytest.fixture
def logs_dir(results_dir: Path) -> Path:
    """Get or create the logs directory."""
    logs = results_dir / "logs"
    logs.mkdir(exist_ok=True)
    return logs


# =============================================================================
# Configuration Fixtures
# =============================================================================

@pytest.fixture
def run_config(run_dir: Path) -> dict[str, Any]:
    """Load the run configuration."""
    config_path = run_dir / "config" / "run_config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


@pytest.fixture
def environment_config(run_dir: Path) -> dict[str, Any]:
    """Load the environment configuration."""
    config_path = run_dir / "config" / "environment.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


# =============================================================================
# Timing Fixtures
# =============================================================================

class Timer:
    """Simple timer for measuring execution time."""
    
    def __init__(self):
        self.start_time: float | None = None
        self.end_time: float | None = None
        self.checkpoints: list[tuple[str, float]] = []
    
    def start(self) -> "Timer":
        self.start_time = time.perf_counter()
        return self
    
    def stop(self) -> float:
        self.end_time = time.perf_counter()
        return self.elapsed_ms
    
    def checkpoint(self, name: str) -> float:
        now = time.perf_counter()
        self.checkpoints.append((name, now))
        return (now - (self.start_time or now)) * 1000
    
    @property
    def elapsed_ms(self) -> float:
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.perf_counter()
        return (end - self.start_time) * 1000
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "elapsed_ms": self.elapsed_ms,
            "checkpoints": [
                {"name": name, "time": t, "elapsed_ms": (t - (self.start_time or t)) * 1000}
                for name, t in self.checkpoints
            ],
        }


@pytest.fixture
def timer() -> Timer:
    """Provide a fresh timer instance."""
    return Timer()


# =============================================================================
# Metrics Collection
# =============================================================================

class MetricsCollector:
    """Collect and aggregate metrics during test execution."""
    
    def __init__(self):
        self.metrics: dict[str, list[float]] = {}
        self.events: list[dict[str, Any]] = []
    
    def record(self, name: str, value: float) -> None:
        """Record a metric value."""
        if name not in self.metrics:
            self.metrics[name] = []
        self.metrics[name].append(value)
    
    def event(self, name: str, data: dict[str, Any] | None = None) -> None:
        """Record an event."""
        self.events.append({
            "name": name,
            "timestamp": datetime.now().isoformat(),
            "data": data or {},
        })
    
    def get_stats(self, name: str) -> dict[str, float]:
        """Get statistics for a metric."""
        values = self.metrics.get(name, [])
        if not values:
            return {}
        
        sorted_values = sorted(values)
        n = len(sorted_values)
        
        return {
            "count": n,
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / n,
            "p50": sorted_values[int(n * 0.5)],
            "p95": sorted_values[int(n * 0.95)] if n >= 20 else sorted_values[-1],
            "p99": sorted_values[int(n * 0.99)] if n >= 100 else sorted_values[-1],
        }
    
    def to_dict(self) -> dict[str, Any]:
        """Export all metrics as a dictionary."""
        return {
            "metrics": {
                name: self.get_stats(name)
                for name in self.metrics
            },
            "raw_values": self.metrics,
            "events": self.events,
        }
    
    def save(self, filepath: Path) -> None:
        """Save metrics to a JSON file."""
        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


@pytest.fixture
def metrics() -> MetricsCollector:
    """Provide a fresh metrics collector."""
    return MetricsCollector()


# =============================================================================
# Findings Collection
# =============================================================================

class FindingsCollector:
    """Collect findings during test execution."""
    
    def __init__(self, roadmap_entry_id: str):
        self.roadmap_entry_id = roadmap_entry_id
        self.findings: list[dict[str, Any]] = []
        self._counter: dict[str, int] = {}
    
    def _next_id(self, finding_type: str) -> str:
        """Generate the next finding ID."""
        type_abbrev = {
            "bug": "BUG",
            "security": "SEC",
            "performance": "PERF",
            "reliability": "REL",
            "dx": "DX",
            "improvement": "IMP",
            "documentation": "DOC",
            "feature_request": "FEAT",
        }
        abbrev = type_abbrev.get(finding_type, "OTHER")
        count = self._counter.get(abbrev, 0) + 1
        self._counter[abbrev] = count
        return f"{self.roadmap_entry_id}-{abbrev}-{count:03d}"
    
    def add(
        self,
        finding_type: str,
        severity: str,
        title: str,
        description: str,
        **kwargs: Any,
    ) -> str:
        """Add a new finding."""
        finding_id = self._next_id(finding_type)
        
        finding = {
            "id": finding_id,
            "type": finding_type,
            "severity": severity,
            "title": title,
            "description": description,
            "status": "open",
            "created_at": datetime.now().isoformat() + "Z",
            **kwargs,
        }
        
        self.findings.append(finding)
        return finding_id
    
    def bug(self, severity: str, title: str, description: str, **kwargs: Any) -> str:
        return self.add("bug", severity, title, description, **kwargs)
    
    def security(self, severity: str, title: str, description: str, **kwargs: Any) -> str:
        return self.add("security", severity, title, description, **kwargs)
    
    def performance(self, severity: str, title: str, description: str, **kwargs: Any) -> str:
        return self.add("performance", severity, title, description, **kwargs)
    
    def dx(self, severity: str, title: str, description: str, **kwargs: Any) -> str:
        return self.add("dx", severity, title, description, **kwargs)
    
    def improvement(self, severity: str, title: str, description: str, **kwargs: Any) -> str:
        return self.add("improvement", severity, title, description, **kwargs)
    
    def to_list(self) -> list[dict[str, Any]]:
        return self.findings


@pytest.fixture
def findings(run_config: dict[str, Any]) -> FindingsCollector:
    """Provide a findings collector for the current run."""
    entry_id = run_config.get("roadmap_entry_id", "UNKNOWN")
    return FindingsCollector(entry_id)


# =============================================================================
# Mock Data Fixtures
# =============================================================================

@pytest.fixture
def mock_data_dir(run_dir: Path) -> Path:
    """Get the mock data directory."""
    return run_dir / "mocks" / "data"


@pytest.fixture
def happy_path_data(mock_data_dir: Path) -> list[dict[str, Any]]:
    """Load happy path test data."""
    data_dir = mock_data_dir / "happy_path"
    if not data_dir.exists():
        return []
    
    data = []
    for file in data_dir.glob("*.json"):
        with open(file) as f:
            content = json.load(f)
            if isinstance(content, list):
                data.extend(content)
            else:
                data.append(content)
    return data


@pytest.fixture
def edge_case_data(mock_data_dir: Path) -> list[dict[str, Any]]:
    """Load edge case test data."""
    data_dir = mock_data_dir / "edge_cases"
    if not data_dir.exists():
        return []
    
    data = []
    for file in data_dir.glob("*.json"):
        with open(file) as f:
            content = json.load(f)
            if isinstance(content, list):
                data.extend(content)
            else:
                data.append(content)
    return data


@pytest.fixture
def adversarial_data(mock_data_dir: Path) -> list[dict[str, Any]]:
    """Load adversarial test data."""
    data_dir = mock_data_dir / "adversarial"
    if not data_dir.exists():
        return []
    
    data = []
    for file in data_dir.glob("*.json"):
        with open(file) as f:
            content = json.load(f)
            if isinstance(content, list):
                data.extend(content)
            else:
                data.append(content)
    return data


# =============================================================================
# Assertion Helpers
# =============================================================================

def assert_latency_within(actual_ms: float, target_ms: float, tolerance: float = 0.1) -> None:
    """Assert latency is within target with tolerance."""
    max_allowed = target_ms * (1 + tolerance)
    assert actual_ms <= max_allowed, f"Latency {actual_ms}ms exceeds target {target_ms}ms (max {max_allowed}ms)"


def assert_error_rate_below(errors: int, total: int, max_rate: float) -> None:
    """Assert error rate is below threshold."""
    if total == 0:
        return
    rate = errors / total
    assert rate <= max_rate, f"Error rate {rate:.2%} exceeds max {max_rate:.2%}"


def assert_no_data_loss(expected_count: int, actual_count: int) -> None:
    """Assert no data was lost."""
    assert actual_count == expected_count, f"Data loss detected: expected {expected_count}, got {actual_count}"


# =============================================================================
# Test Markers
# =============================================================================

# Register custom markers
def pytest_configure(config):
    config.addinivalue_line("markers", "correctness: marks tests as correctness tests")
    config.addinivalue_line("markers", "reliability: marks tests as reliability tests")
    config.addinivalue_line("markers", "performance: marks tests as performance tests")
    config.addinivalue_line("markers", "security: marks tests as security tests")
    config.addinivalue_line("markers", "scalability: marks tests as scalability tests")
    config.addinivalue_line("markers", "observability: marks tests as observability tests")
    config.addinivalue_line("markers", "slow: marks tests as slow running")
    config.addinivalue_line("markers", "chaos: marks tests that inject chaos")
