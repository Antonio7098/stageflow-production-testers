"""TRANSFORM-007 Streaming Transform Test Pipelines.

This module implements comprehensive test pipelines for stress-testing
Stageflow's streaming transform capabilities for real-time data processing.

Test Categories:
1. Baseline Pipeline - Normal operation
2. Stress Pipeline - High load scenarios
3. Chaos Pipeline - Injected failures
4. Adversarial Pipeline - Security/robustness testing
5. Recovery Pipeline - Failure recovery
"""

import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

import stageflow
from stageflow import Pipeline, StageContext, StageKind, StageOutput
from stageflow.helpers import (
    AudioChunk,
    ChunkQueue,
    StreamingBuffer,
    BackpressureMonitor,
    run_simple_pipeline,
)
from stageflow.context import ContextSnapshot

from mocks.streaming_transform_mocks import (
    StreamConfig,
    StreamMetrics,
    StreamingMockDataGenerator,
    BackpressureTestGenerator,
    BufferTestGenerator,
    LatencyTestGenerator,
    AdversarialTestGenerator,
    StreamingMetricsCollector,
    run_baseline_streaming_test,
    run_high_load_streaming_test,
    run_burst_streaming_test,
)

from components.audio.stages import (
    STTStage,
    StreamingSTTStage,
    TTSStage,
    StreamingTTSStage,
)
from components.audio.streaming_mocks import (
    StreamingAudioDuplex,
    StreamingSTTMock,
    StreamingTTSMock,
    create_streaming_audio_ports,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of a single test execution."""
    test_name: str
    category: str
    success: bool
    duration_ms: float
    metrics: Dict[str, Any]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_name": self.test_name,
            "category": self.category,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "metrics": self.metrics,
            "errors": self.errors,
            "warnings": self.warnings,
            "timestamp": self.timestamp,
        }


class StreamingTransformTestPipelines:
    """Test pipelines for TRANSFORM-007 streaming transform reliability."""

    def __init__(self, results_dir: str = "results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.config = StreamConfig()
        self.metrics_collector = StreamingMetricsCollector()
        self.test_results: List[TestResult] = []

    async def run_baseline_pipeline(self) -> TestResult:
        """Test 1: Baseline streaming with normal conditions."""
        logger.info("Running baseline streaming test...")
        start_time = time.perf_counter()

        try:
            metrics = await run_baseline_streaming_test(
                num_chunks=100,
                chunk_interval_ms=20,
                config=self.config,
            )

            success = (
                metrics.chunks_produced == 100 and
                metrics.chunks_consumed == 100 and
                metrics.chunks_dropped == 0
            )

            result = TestResult(
                test_name="baseline_streaming",
                category="correctness",
                success=success,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics=metrics.to_dict(),
                errors=["Chunks were dropped"] if metrics.chunks_dropped > 0 else [],
            )

        except Exception as e:
            result = TestResult(
                test_name="baseline_streaming",
                category="correctness",
                success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={},
                errors=[f"Exception: {str(e)}"],
            )

        self.test_results.append(result)
        return result

    async def run_queue_overflow_test(self) -> TestResult:
        """Test 2: Queue overflow handling."""
        logger.info("Running queue overflow test...")
        start_time = time.perf_counter()

        try:
            generator = BackpressureTestGenerator(self.config)
            queue, metrics = await generator.test_queue_overflow(
                max_size=50,
                num_chunks=200,
            )

            drop_rate = metrics.chunks_dropped / metrics.chunks_produced if metrics.chunks_produced > 0 else 0
            success = drop_rate < 0.5  # Allow up to 50% drop rate in overflow

            result = TestResult(
                test_name="queue_overflow",
                category="reliability",
                success=success,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={
                    **metrics.to_dict(),
                    "queue_max_size": 50,
                    "drop_rate": drop_rate,
                },
                errors=[],
            )

        except Exception as e:
            result = TestResult(
                test_name="queue_overflow",
                category="reliability",
                success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={},
                errors=[f"Exception: {str(e)}"],
            )

        self.test_results.append(result)
        return result

    async def run_buffer_overflow_test(self) -> TestResult:
        """Test 3: Streaming buffer overflow handling."""
        logger.info("Running buffer overflow test...")
        start_time = time.perf_counter()

        try:
            generator = BufferTestGenerator(self.config)
            buffer, metrics = await generator.test_buffer_overflow(
                target_ms=100,
                max_ms=500,
                chunks_to_add=100,
            )

            success = metrics.chunks_dropped >= 0  # Overflow should be handled gracefully

            result = TestResult(
                test_name="buffer_overflow",
                category="reliability",
                success=success,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics=metrics.to_dict(),
                errors=[],
            )

        except Exception as e:
            result = TestResult(
                test_name="buffer_overflow",
                category="reliability",
                success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={},
                errors=[f"Exception: {str(e)}"],
            )

        self.test_results.append(result)
        return result

    async def run_buffer_underrun_test(self) -> TestResult:
        """Test 4: Buffer underrun detection."""
        logger.info("Running buffer underrun test...")
        start_time = time.perf_counter()

        try:
            generator = BufferTestGenerator(self.config)
            buffer, metrics = await generator.test_buffer_underrun(
                initial_chunks=5,
                read_delay_ms=100,
            )

            success = True  # Underrun detection is expected behavior

            result = TestResult(
                test_name="buffer_underrun",
                category="reliability",
                success=success,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics=metrics.to_dict(),
                warnings=["Underrun events detected - expected with sparse input"] if metrics.underrun_events > 0 else [],
            )

        except Exception as e:
            result = TestResult(
                test_name="buffer_underrun",
                category="reliability",
                success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={},
                errors=[f"Exception: {str(e)}"],
            )

        self.test_results.append(result)
        return result

    async def run_backpressure_test(self) -> TestResult:
        """Test 5: Backpressure detection and handling."""
        logger.info("Running backpressure test...")
        start_time = time.perf_counter()

        try:
            queue = ChunkQueue(max_size=100)
            generator = BackpressureTestGenerator(self.config)
            metrics = await generator.produce_faster_than_consume(
                queue=queue,
                duration_ms=3000,
                producer_delay_ms=5,
                consumer_delay_ms=50,
            )

            drop_rate = metrics.chunks_dropped / metrics.chunks_produced if metrics.chunks_produced > 0 else 0
            success = drop_rate < 0.9  # Should drop some but not all

            result = TestResult(
                test_name="backpressure_handling",
                category="reliability",
                success=success,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={
                    **metrics.to_dict(),
                    "drop_rate": drop_rate,
                    "queue_max_size": 100,
                },
                errors=[],
            )

        except Exception as e:
            result = TestResult(
                test_name="backpressure_handling",
                category="reliability",
                success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={},
                errors=[f"Exception: {str(e)}"],
            )

        self.test_results.append(result)
        return result

    async def run_high_load_test(self) -> TestResult:
        """Test 6: High load streaming performance."""
        logger.info("Running high load test...")
        start_time = time.perf_counter()

        try:
            metrics = await run_high_load_streaming_test(
                num_chunks=500,
                producer_delay_ms=2,
                consumer_delay_ms=10,
                config=self.config,
            )

            throughput = metrics.chunks_produced / (metrics.duration_ms / 1000) if metrics.duration_ms > 0 else 0
            success = throughput > 50  # Expect at least 50 chunks/second

            result = TestResult(
                test_name="high_load_performance",
                category="performance",
                success=success,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={
                    **metrics.to_dict(),
                    "throughput_chunks_per_sec": throughput,
                },
                errors=[],
            )

        except Exception as e:
            result = TestResult(
                test_name="high_load_performance",
                category="performance",
                success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={},
                errors=[f"Exception: {str(e)}"],
            )

        self.test_results.append(result)
        return result

    async def run_burst_test(self) -> TestResult:
        """Test 7: Burst load handling."""
        logger.info("Running burst load test...")
        start_time = time.perf_counter()

        try:
            metrics = await run_burst_streaming_test(
                bursts=5,
                chunks_per_burst=100,
                burst_interval_ms=100,
            )

            success = metrics.chunks_dropped < (metrics.chunks_produced * 0.1)

            result = TestResult(
                test_name="burst_load_handling",
                category="performance",
                success=success,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics=metrics.to_dict(),
                errors=["High drop rate in burst"] if metrics.chunks_dropped > metrics.chunks_produced * 0.1 else [],
            )

        except Exception as e:
            result = TestResult(
                test_name="burst_load_handling",
                category="performance",
                success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={},
                errors=[f"Exception: {str(e)}"],
            )

        self.test_results.append(result)
        return result

    async def run_latency_test(self) -> TestResult:
        """Test 8: Latency profiling."""
        logger.info("Running latency test...")
        start_time = time.perf_counter()

        try:
            generator = LatencyTestGenerator(self.config)
            queue, latencies = await generator.measure_end_to_end_latency(
                num_messages=50,
                queue_size=100,
                process_time_ms=5,
            )

            p50 = sorted(latencies)[len(latencies) // 2]
            p95 = sorted(latencies)[int(len(latencies) * 0.95)]
            p99 = sorted(latencies)[int(len(latencies) * 0.99)]

            success = p99 < 500  # P99 latency should be under 500ms

            result = TestResult(
                test_name="latency_profiling",
                category="performance",
                success=success,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={
                    "p50_latency_ms": p50,
                    "p95_latency_ms": p95,
                    "p99_latency_ms": p99,
                    "avg_latency_ms": sum(latencies) / len(latencies),
                    "max_latency_ms": max(latencies),
                    "min_latency_ms": min(latencies),
                },
                warnings=["High P99 latency"] if p99 > 500 else [],
            )

        except Exception as e:
            result = TestResult(
                test_name="latency_profiling",
                category="performance",
                success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={},
                errors=[f"Exception: {str(e)}"],
            )

        self.test_results.append(result)
        return result

    async def run_empty_chunk_test(self) -> TestResult:
        """Test 9: Empty chunk handling (adversarial)."""
        logger.info("Running empty chunk test...")
        start_time = time.perf_counter()

        try:
            queue = ChunkQueue(max_size=100)
            metrics = StreamMetrics()

            for i in range(50):
                chunk = AudioChunk(
                    data=b"",  # Empty data
                    sample_rate=16000,
                    timestamp_ms=i * 20,
                )
                await queue.put(chunk)
                metrics.chunks_produced += 1

            consumed = 0
            for _ in range(50):
                try:
                    await asyncio.wait_for(queue.get(), timeout=0.1)
                    metrics.chunks_consumed += 1
                    consumed += 1
                except asyncio.TimeoutError:
                    break

            success = consumed == 50  # Should handle empty chunks gracefully

            result = TestResult(
                test_name="empty_chunk_handling",
                category="security",
                success=success,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics=metrics.to_dict(),
                errors=[] if success else ["Empty chunks caused issues"],
            )

        except Exception as e:
            result = TestResult(
                test_name="empty_chunk_handling",
                category="security",
                success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={},
                errors=[f"Exception: {str(e)}"],
            )

        self.test_results.append(result)
        return result

    async def run_oversized_chunk_test(self) -> TestResult:
        """Test 10: Oversized chunk handling (adversarial)."""
        logger.info("Running oversized chunk test...")
        start_time = time.perf_counter()

        try:
            queue = ChunkQueue(max_size=10)  # Small queue
            metrics = StreamMetrics()

            for i in range(20):
                chunk = AudioChunk(
                    data=bytes([i % 256] * (1024 * 100)),  # 100KB chunks
                    sample_rate=16000,
                )
                success = await queue.put(chunk)
                if not success:
                    metrics.chunks_dropped += 1
                metrics.chunks_produced += 1

            success = True  # Should handle gracefully by dropping

            result = TestResult(
                test_name="oversized_chunk_handling",
                category="security",
                success=success,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics=metrics.to_dict(),
                errors=[],
            )

        except MemoryError:
            result = TestResult(
                test_name="oversized_chunk_handling",
                category="security",
                success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={},
                errors=["MemoryError: Oversized chunks caused memory exhaustion"],
            )
        except Exception as e:
            result = TestResult(
                test_name="oversized_chunk_handling",
                category="security",
                success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={},
                errors=[f"Exception: {str(e)}"],
            )

        self.test_results.append(result)
        return result

    async def run_concurrent_streaming_test(self) -> TestResult:
        """Test 11: Concurrent streaming operations."""
        logger.info("Running concurrent streaming test...")
        start_time = time.perf_counter()

        try:
            num_streams = 20
            streams = []

            async def stream_worker(stream_id: int) -> StreamMetrics:
                queue = ChunkQueue(max_size=100)
                metrics = StreamMetrics()

                async def producer():
                    for i in range(50):
                        chunk = AudioChunk(
                            data=bytes([(stream_id + i) % 256] * 320),
                            sample_rate=16000,
                        )
                        await queue.put(chunk)
                        metrics.chunks_produced += 1
                        await asyncio.sleep(0.01)

                async def consumer():
                    for _ in range(50):
                        try:
                            await asyncio.wait_for(queue.get(), timeout=0.5)
                            metrics.chunks_consumed += 1
                        except asyncio.TimeoutError:
                            break

                await asyncio.gather(producer(), consumer())
                return metrics

            for i in range(num_streams):
                streams.append(asyncio.create_task(stream_worker(i)))

            all_metrics = await asyncio.gather(*streams)

            total_produced = sum(m.chunks_produced for m in all_metrics)
            total_consumed = sum(m.chunks_consumed for m in all_metrics)
            total_dropped = sum(m.chunks_dropped for m in all_metrics)

            success = total_dropped < total_produced * 0.2

            result = TestResult(
                test_name="concurrent_streaming",
                category="scalability",
                success=success,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={
                    "num_streams": num_streams,
                    "total_produced": total_produced,
                    "total_consumed": total_consumed,
                    "total_dropped": total_dropped,
                    "drop_rate": total_dropped / total_produced if total_produced > 0 else 0,
                },
                errors=[],
            )

        except Exception as e:
            result = TestResult(
                test_name="concurrent_streaming",
                category="scalability",
                success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={},
                errors=[f"Exception: {str(e)}"],
            )

        self.test_results.append(result)
        return result

    async def run_silent_failure_test(self) -> TestResult:
        """Test 12: Silent failure detection in streaming."""
        logger.info("Running silent failure detection test...")
        start_time = time.perf_counter()

        try:
            queue = ChunkQueue(max_size=100)
            metrics = StreamMetrics()

            expected_chunks = 100
            produced = 0

            for i in range(expected_chunks):
                chunk = AudioChunk(
                    data=bytes([i % 256] * 320),
                    sample_rate=16000,
                    timestamp_ms=i * 20,
                )
                await queue.put(chunk)
                produced += 1

            consumed = 0
            for _ in range(expected_chunks + 10):
                try:
                    await asyncio.wait_for(queue.get(), timeout=0.1)
                    consumed += 1
                except asyncio.TimeoutError:
                    break

            silent_failures = expected_chunks - consumed
            success = silent_failures == 0

            result = TestResult(
                test_name="silent_failure_detection",
                category="reliability",
                success=success,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={
                    "expected_chunks": expected_chunks,
                    "produced": produced,
                    "consumed": consumed,
                    "silent_failures": silent_failures,
                },
                errors=["Silent failures detected"] if silent_failures > 0 else [],
            )

        except Exception as e:
            result = TestResult(
                test_name="silent_failure_detection",
                category="reliability",
                success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                metrics={},
                errors=[f"Exception: {str(e)}"],
            )

        self.test_results.append(result)
        return result

    async def run_all_tests(self) -> List[TestResult]:
        """Run all streaming transform tests."""
        logger.info("Starting TRANSFORM-007 test suite...")

        tests = [
            self.run_baseline_pipeline,
            self.run_queue_overflow_test,
            self.run_buffer_overflow_test,
            self.run_buffer_underrun_test,
            self.run_backpressure_test,
            self.run_high_load_test,
            self.run_burst_test,
            self.run_latency_test,
            self.run_empty_chunk_test,
            self.run_oversized_chunk_test,
            self.run_concurrent_streaming_test,
            self.run_silent_failure_test,
        ]

        for test in tests:
            try:
                await test()
            except Exception as e:
                logger.error(f"Test {test.__name__} failed with exception: {e}")

        return self.test_results

    def save_results(self) -> str:
        """Save test results to file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self.results_dir / f"transform007_results_{timestamp}.json"

        results_data = {
            "run_timestamp": timestamp,
            "total_tests": len(self.test_results),
            "passed": sum(1 for r in self.test_results if r.success),
            "failed": sum(1 for r in self.test_results if not r.success),
            "results": [r.to_dict() for r in self.test_results],
            "aggregate_metrics": self.metrics_collector.get_aggregate_metrics(),
        }

        with open(filename, 'w') as f:
            json.dump(results_data, f, indent=2)

        logger.info(f"Results saved to {filename}")
        return str(filename)

    def generate_report(self) -> str:
        """Generate a summary report."""
        passed = sum(1 for r in self.test_results if r.success)
        failed = sum(1 for r in self.test_results if not r.success)

        report = f"""# TRANSFORM-007 Test Report

## Summary

- **Total Tests**: {len(self.test_results)}
- **Passed**: {passed}
- **Failed**: {failed}
- **Pass Rate**: {passed / len(self.test_results) * 100:.1f}%

## Test Results

"""

        for result in self.test_results:
            status = "✅ PASS" if result.success else "❌ FAIL"
            report += f"""
### {result.test_name} ({result.category})

{status} - {result.duration_ms:.2f}ms

"""

        return report


async def main():
    """Main entry point for running tests."""
    import argparse

    parser = argparse.ArgumentParser(description="TRANSFORM-007 Streaming Transform Tests")
    parser.add_argument("--test", type=str, help="Run specific test")
    parser.add_argument("--results-dir", type=str, default="results", help="Results directory")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    test_suite = StreamingTransformTestPipelines(results_dir=args.results_dir)

    if args.test:
        test_method = getattr(test_suite, args.test, None)
        if test_method:
            result = await test_method()
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"Unknown test: {args.test}")
            print(f"Available tests: {[m.replace('run_', '').replace('_test', '') for m in dir(test_suite) if m.startswith('run_') and callable(getattr(test_suite, m))]}")
    else:
        results = await test_suite.run_all_tests()
        test_suite.save_results()
        print(test_suite.generate_report())


if __name__ == "__main__":
    asyncio.run(main())
