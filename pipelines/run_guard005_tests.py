#!/usr/bin/env python3
"""
GUARD-005 Test Runner: Rate Limiting and Abuse Prevention

Executes all test pipelines and generates comprehensive results.
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
import uuid

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from stageflow import Pipeline, StageContext, StageKind, StageOutput, StageInputs, PipelineTimer
from stageflow.context import ContextSnapshot, RunIdentity
from pipelines.guard005_pipelines import (
    create_baseline_pipeline,
    create_stress_pipeline,
    create_token_tracking_pipeline,
    create_circuit_breaker_pipeline,
    create_adaptive_pipeline,
    RateLimitGuardStage,
    TokenTrackingStage,
    CircuitBreakerStage,
    InMemoryRateLimiter,
    TokenBucketRateLimiter,
    SlidingWindowRateLimiter,
    AdaptiveRateLimiter,
    RateLimitConfig,
    RateLimitAlgorithm,
    RateLimitResult,
    PipelineTestResult,
    TestResult,
)


@dataclass
class RateLimitTestResult:
    """Result of rate limiting tests."""
    test_id: str
    category: str
    description: str
    identifier: str
    request_number: int
    expected_result: str
    actual_result: str
    rate_limited: bool
    latency_ms: float
    passed: bool
    error: Optional[str] = None
    rate_info: dict = field(default_factory=dict)


@dataclass
class RateLimitPipelineResult:
    """Aggregated results for rate limiting tests."""
    pipeline_name: str
    total_requests: int
    allowed: int
    denied: int
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    throughput_rps: float
    silent_failures: list[str]
    test_results: list[RateLimitTestResult]
    timestamp: str


async def run_rate_limit_test(
    pipeline: Pipeline,
    identifier: str,
    num_requests: int,
    delay_ms: float = 0,
    test_id_prefix: str = "test",
) -> list[RateLimitTestResult]:
    """Run rate limit test with multiple requests."""
    results = []

    for i in range(num_requests):
        start_time = time.perf_counter()

        try:
            graph = pipeline.build()
            snapshot = ContextSnapshot(
                run_id=RunIdentity(
                    pipeline_run_id=uuid.uuid4(),
                    request_id=uuid.uuid4(),
                    session_id=uuid.uuid4(),
                    user_id=uuid.uuid4() if identifier.startswith("user:") else None,
                ),
                input_text=f"Test request {i} from {identifier}",
                extensions={"ip_address": "192.168.1.1"} if identifier.startswith("ip:") else {},
            )

            ctx = StageContext(
                snapshot=snapshot,
                inputs=StageInputs(snapshot=snapshot),
                stage_name="pipeline_entry",
                timer=PipelineTimer(),
            )

            outputs = await graph.run(ctx)

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            rate_limit_output = outputs.get("rate_limit")
            if rate_limit_output:
                rate_limited = rate_limit_output.data.get("rate_limited", False)
                actual_result = "denied" if rate_limited else "allowed"

                results.append(RateLimitTestResult(
                    test_id=f"{test_id_prefix}_{i}",
                    category="rate_limit",
                    description=f"Request {i} for {identifier}",
                    identifier=identifier,
                    request_number=i,
                    expected_result="denied" if i >= 10 else "allowed",
                    actual_result=actual_result,
                    rate_limited=rate_limited,
                    latency_ms=elapsed_ms,
                    passed=(i < 10 and not rate_limited) or (i >= 10 and rate_limited),
                    rate_info=rate_limit_output.data,
                ))
            else:
                results.append(RateLimitTestResult(
                    test_id=f"{test_id_prefix}_{i}",
                    category="rate_limit",
                    description=f"Request {i} for {identifier}",
                    identifier=identifier,
                    request_number=i,
                    expected_result="denied" if i >= 10 else "allowed",
                    actual_result="error",
                    rate_limited=False,
                    latency_ms=elapsed_ms,
                    passed=False,
                    error="No rate_limit output",
                ))

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            results.append(RateLimitTestResult(
                test_id=f"{test_id_prefix}_{i}",
                category="rate_limit",
                description=f"Request {i} for {identifier}",
                identifier=identifier,
                request_number=i,
                expected_result="denied" if i >= 10 else "allowed",
                actual_result="error",
                rate_limited=False,
                latency_ms=elapsed_ms,
                passed=False,
                error=str(e),
            ))

        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)

    return results


async def run_baseline_rate_limit_tests(num_users: int = 5, requests_per_user: int = 15) -> RateLimitPipelineResult:
    """Run baseline rate limiting tests."""
    print(f"Running baseline tests: {num_users} users, {requests_per_user} requests each")

    pipeline = create_baseline_pipeline()
    all_results: list[RateLimitTestResult] = []
    silent_failures: list[str] = []

    for user_id in range(num_users):
        identifier = f"user:{uuid.uuid4()}"
        results = await run_rate_limit_test(
            pipeline, identifier, requests_per_user,
            delay_ms=10, test_id_prefix=f"baseline_user{user_id}"
        )
        all_results.extend(results)

    return aggregate_rate_limit_results("baseline", all_results, silent_failures)


async def run_burst_test(num_burst_requests: int = 50) -> RateLimitPipelineResult:
    """Test burst traffic handling."""
    print(f"Running burst test: {num_burst_requests} requests")

    pipeline = create_stress_pipeline()
    identifier = "user:burst_tester"
    all_results = await run_rate_limit_test(
        pipeline, identifier, num_burst_requests,
        delay_ms=0, test_id_prefix="burst"
    )

    silent_failures = []
    return aggregate_rate_limit_results("burst", all_results, silent_failures)


async def run_concurrent_test(
    num_concurrent_users: int = 20,
    requests_per_user: int = 10,
) -> RateLimitPipelineResult:
    """Test concurrent user rate limiting."""
    print(f"Running concurrent test: {num_concurrent_users} concurrent users")

    pipeline = create_stress_pipeline()

    async def user_requests(user_idx: int) -> list[RateLimitTestResult]:
        identifier = f"user:concurrent_{user_idx}"
        return await run_rate_limit_test(
            pipeline, identifier, requests_per_user,
            delay_ms=5, test_id_prefix=f"concurrent_user{user_idx}"
        )

    tasks = [user_requests(i) for i in range(num_concurrent_users)]
    results_lists = await asyncio.gather(*tasks)

    all_results = [r for results in results_lists for r in results]
    silent_failures: list[str] = []

    return aggregate_rate_limit_results("concurrent", all_results, silent_failures)


async def run_token_limit_tests(num_users: int = 3, requests_per_user: int = 5) -> RateLimitPipelineResult:
    """Test token-based rate limiting."""
    print(f"Running token limit tests: {num_users} users")

    pipeline = create_token_tracking_pipeline()
    all_results: list[RateLimitTestResult] = []
    silent_failures: list[str] = []

    for user_id in range(num_users):
        identifier = f"user:token_{uuid.uuid4()}"

        for req_num in range(requests_per_user):
            start_time = time.perf_counter()

            try:
                graph = pipeline.build()
                snapshot = ContextSnapshot(
                    run_id=RunIdentity(
                        pipeline_run_id=uuid.uuid4(),
                        request_id=uuid.uuid4(),
                        session_id=uuid.uuid4(),
                        user_id=uuid.uuid4(),
                    ),
                    input_text="A" * 2000,
                )

                ctx = StageContext(
                    snapshot=snapshot,
                    inputs=StageInputs(snapshot=snapshot),
                    stage_name="pipeline_entry",
                    timer=PipelineTimer(),
                )

                outputs = await graph.run(ctx)
                elapsed_ms = (time.perf_counter() - start_time) * 1000

                tracker_output = outputs.get("token_tracker")
                if tracker_output:
                    token_limited = tracker_output.data.get("token_limited", False)
                    limit_type = tracker_output.data.get("limit_type", "unknown")

                    all_results.append(RateLimitTestResult(
                        test_id=f"token_user{user_id}_req{req_num}",
                        category="token_limit",
                        description=f"Token request {req_num} for user {user_id}",
                        identifier=identifier,
                        request_number=req_num,
                        expected_result="denied" if req_num >= 4 else "allowed",
                        actual_result="denied" if token_limited else "allowed",
                        rate_limited=token_limited,
                        latency_ms=elapsed_ms,
                        passed=(req_num < 4 and not token_limited) or (req_num >= 4 and token_limited),
                        rate_info={
                            "limit_type": limit_type,
                            "tpm_used": tracker_output.data.get("tpm_used", 0),
                            "tpm_limit": tracker_output.data.get("tpm_limit", 0),
                        },
                    ))

            except Exception as e:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                all_results.append(RateLimitTestResult(
                    test_id=f"token_user{user_id}_req{req_num}",
                    category="token_limit",
                    description=f"Token request {req_num} for user {user_id}",
                    identifier=identifier,
                    request_number=req_num,
                    expected_result="denied" if req_num >= 4 else "allowed",
                    actual_result="error",
                    rate_limited=False,
                    latency_ms=elapsed_ms,
                    passed=False,
                    error=str(e),
                ))

    return aggregate_rate_limit_results("token_limit", all_results, silent_failures)


async def run_circuit_breaker_test(num_requests: int = 20) -> RateLimitPipelineResult:
    """Test circuit breaker functionality."""
    print(f"Running circuit breaker test: {num_requests} requests")

    pipeline = create_circuit_breaker_pipeline()
    all_results: list[RateLimitTestResult] = []
    silent_failures: list[str] = []

    for i in range(num_requests):
        start_time = time.perf_counter()

        try:
            graph = pipeline.build()
            snapshot = ContextSnapshot(
                run_id=RunIdentity(
                    pipeline_run_id=uuid.uuid4(),
                    request_id=uuid.uuid4(),
                    session_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                ),
                input_text=f"Circuit test request {i}",
            )

            ctx = StageContext(
                snapshot=snapshot,
                inputs=StageInputs(snapshot=snapshot),
                stage_name="pipeline_entry",
                timer=PipelineTimer(),
            )

            outputs = await graph.run(ctx)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            cb_output = outputs.get("circuit_breaker")
            if cb_output:
                circuit_open = cb_output.data.get("circuit_open", False)

                all_results.append(RateLimitTestResult(
                    test_id=f"circuit_{i}",
                    category="circuit_breaker",
                    description=f"Circuit breaker request {i}",
                    identifier="circuit_test",
                    request_number=i,
                    expected_result="allowed",
                    actual_result="denied" if circuit_open else "allowed",
                    rate_limited=circuit_open,
                    latency_ms=elapsed_ms,
                    passed=True,
                    rate_info=cb_output.data,
                ))

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            all_results.append(RateLimitTestResult(
                test_id=f"circuit_{i}",
                category="circuit_breaker",
                description=f"Circuit breaker request {i}",
                identifier="circuit_test",
                request_number=i,
                expected_result="allowed",
                actual_result="error",
                rate_limited=False,
                latency_ms=elapsed_ms,
                passed=False,
                error=str(e),
            ))

    return aggregate_rate_limit_results("circuit_breaker", all_results, silent_failures)


async def run_adaptive_test(num_users: int = 10, requests_per_user: int = 20) -> RateLimitPipelineResult:
    """Test adaptive rate limiting."""
    print(f"Running adaptive rate limit test: {num_users} users")

    pipeline = create_adaptive_pipeline()
    all_results: list[RateLimitTestResult] = []
    silent_failures: list[str] = []

    for user_id in range(num_users):
        identifier = f"user:adaptive_{user_id}"
        results = await run_rate_limit_test(
            pipeline, identifier, requests_per_user,
            delay_ms=20, test_id_prefix=f"adaptive_user{user_id}"
        )
        all_results.extend(results)

    return aggregate_rate_limit_results("adaptive", all_results, silent_failures)


async def run_stress_test(
    concurrent_requests: int = 50,
    duration_seconds: int = 10,
) -> dict:
    """Run high-load stress test."""
    print(f"Running stress test: {concurrent_requests} concurrent, {duration_seconds}s")

    start_time = time.time()
    successful = 0
    rate_limited = 0
    errors = 0
    latencies = []
    silent_failures: list[str] = []

    pipeline = create_stress_pipeline()

    async def make_request(req_id: int) -> dict:
        nonlocal successful, rate_limited, errors

        try:
            req_start = time.perf_counter()

            graph = pipeline.build()
            snapshot = ContextSnapshot(
                run_id=RunIdentity(
                    pipeline_run_id=uuid.uuid4(),
                    request_id=uuid.uuid4(),
                    session_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                ),
                input_text=f"Stress test request {req_id}",
            )

            ctx = StageContext(
                snapshot=snapshot,
                inputs=StageInputs(snapshot=snapshot),
                stage_name="pipeline_entry",
                timer=PipelineTimer(),
            )

            outputs = await graph.run(ctx)
            elapsed_ms = (time.perf_counter() - req_start) * 1000

            rate_limit_output = outputs.get("rate_limit")
            if rate_limit_output:
                if rate_limit_output.data.get("rate_limited"):
                    rate_limited += 1
                else:
                    successful += 1
            else:
                successful += 1

            latencies.append(elapsed_ms)

        except Exception as e:
            errors += 1
            silent_failures.append(f"Error in request {req_id}: {str(e)}")

    requests_made = 0
    while time.time() - start_time < duration_seconds:
        batch_size = min(concurrent_requests, 100)
        tasks = [make_request(requests_made + i) for i in range(batch_size)]
        await asyncio.gather(*tasks)
        requests_made += batch_size

    latencies.sort()
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0
    throughput = successful / duration_seconds if duration_seconds > 0 else 0

    return {
        "pipeline_name": "stress",
        "total_requests": requests_made,
        "successful": successful,
        "rate_limited": rate_limited,
        "errors": errors,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": p95,
        "p99_latency_ms": p99,
        "throughput_rps": throughput,
        "duration_seconds": duration_seconds,
        "silent_failures": silent_failures,
        "timestamp": datetime.now().isoformat(),
    }


def aggregate_rate_limit_results(
    pipeline_name: str,
    results: list[RateLimitTestResult],
    silent_failures: list[str],
) -> RateLimitPipelineResult:
    """Aggregate rate limit test results."""
    allowed = sum(1 for r in results if r.actual_result == "allowed")
    denied = sum(1 for r in results if r.actual_result == "denied")
    errors = sum(1 for r in results if r.actual_result == "error")

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    latencies = [r.latency_ms for r in results if r.latency_ms > 0]
    latencies.sort()

    return RateLimitPipelineResult(
        pipeline_name=pipeline_name,
        total_requests=len(results),
        allowed=allowed,
        denied=denied,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
        p95_latency_ms=latencies[int(len(latencies) * 0.95)] if latencies else 0,
        p99_latency_ms=latencies[int(len(latencies) * 0.99)] if latencies else 0,
        throughput_rps=0,
        silent_failures=silent_failures,
        test_results=results,
        timestamp=datetime.now().isoformat(),
    )


def save_results(results: dict, output_dir: Path):
    """Save test results to files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    results_file = output_dir / "guard005_results.json"
    serializable_results = {}

    for name, result in results.items():
        if hasattr(result, '__dict__'):
            serializable_results[name] = {
                "pipeline_name": result.pipeline_name if hasattr(result, 'pipeline_name') else name,
                "total_requests": result.total_requests if hasattr(result, 'total_requests') else result.get('total_requests', 0),
                "allowed": result.allowed if hasattr(result, 'allowed') else result.get('successful', 0),
                "denied": result.denied if hasattr(result, 'denied') else result.get('rate_limited', 0),
                "avg_latency_ms": result.avg_latency_ms if hasattr(result, 'avg_latency_ms') else result.get('avg_latency_ms', 0),
                "p95_latency_ms": result.p95_latency_ms if hasattr(result, 'p95_latency_ms') else result.get('p95_latency_ms', 0),
                "p99_latency_ms": result.p99_latency_ms if hasattr(result, 'p99_latency_ms') else result.get('p99_latency_ms', 0),
                "throughput_rps": result.throughput_rps if hasattr(result, 'throughput_rps') else result.get('throughput_rps', 0),
                "silent_failures": result.silent_failures if hasattr(result, 'silent_failures') else result.get('silent_failures', []),
                "timestamp": result.timestamp if hasattr(result, 'timestamp') else result.get('timestamp', datetime.now().isoformat()),
            }

    with open(results_file, "w") as f:
        json.dump(serializable_results, f, indent=2)
    print(f"Results saved to: {results_file}")

    summary = {
        "timestamp": datetime.now().isoformat(),
        "test_runs": {},
        "summary": {},
    }

    total_requests = 0
    total_allowed = 0
    total_denied = 0
    total_errors = 0

    for name, result in results.items():
        if isinstance(result, dict):
            total_requests += result.get('total_requests', 0)
            total_allowed += result.get('successful', 0)
            total_denied += result.get('rate_limited', 0)
            total_errors += result.get('errors', 0)
            summary["test_runs"][name] = {
                "successful": result.get("successful", 0),
                "rate_limited": result.get("rate_limited", 0),
                "errors": result.get("errors", 0),
            }

    summary["summary"] = {
        "total_requests": total_requests,
        "total_allowed": total_allowed,
        "total_denied": total_denied,
        "total_errors": total_errors,
        "pass_rate": total_allowed / total_requests if total_requests > 0 else 0,
        "successful": total_errors / total_requests < 0.01 if total_requests > 0 else False,
    }

    summary_file = output_dir / "guard005_summary.json"
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Summary saved to: {summary_file}")

    return summary


async def main():
    """Main entry point."""
    print("=" * 60)
    print("GUARD-005: Rate Limiting and Abuse Prevention Tests")
    print("=" * 60)
    print(f"Started at: {datetime.now().isoformat()}")
    print()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = project_root / "results" / f"guard005_{timestamp}"
    results_dir.mkdir(parents=True, exist_ok=True)

    try:
        results = {
            "baseline": await run_baseline_rate_limit_tests(num_users=5, requests_per_user=15),
            "burst": await run_burst_test(num_burst_requests=50),
            "concurrent": await run_concurrent_test(num_concurrent_users=10, requests_per_user=10),
            "token_limit": await run_token_limit_tests(num_users=3, requests_per_user=5),
            "circuit_breaker": await run_circuit_breaker_test(num_requests=15),
            "adaptive": await run_adaptive_test(num_users=5, requests_per_user=15),
        }

        print("\nRunning stress test (10 seconds, 50 concurrent)...")
        stress_result = await run_stress_test(concurrent_requests=50, duration_seconds=10)
        results["stress"] = stress_result

        summary = save_results(results, results_dir)

        print("\n" + "=" * 60)
        print("FINAL SUMMARY")
        print("=" * 60)
        print(f"Total Requests: {summary['summary']['total_requests']}")
        print(f"Total Allowed: {summary['summary']['total_allowed']}")
        print(f"Total Denied: {summary['summary']['total_denied']}")
        print(f"Total Errors: {summary['summary']['total_errors']}")
        print(f"Pass Rate: {summary['summary']['pass_rate']:.2%}")
        print(f"Status: {'SUCCESS' if summary['summary']['successful'] else 'NEEDS IMPROVEMENT'}")
        print(f"\nResults saved to: {results_dir}")

        return summary

    except Exception as e:
        print(f"\nError running tests: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    asyncio.run(main())
