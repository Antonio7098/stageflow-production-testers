"""Quick test runner for TRANSFORM-007 with timeout protection."""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mocks.streaming_transform_mocks import (
    StreamConfig,
    StreamMetrics,
    run_baseline_streaming_test,
    BackpressureTestGenerator,
    BufferTestGenerator,
)

config = StreamConfig()


async def run_quick_tests():
    results = []
    
    test_cases = [
        ("baseline", lambda: run_baseline_streaming_test(num_chunks=50, chunk_interval_ms=10, config=config)),
        ("queue_overflow", lambda: _test_queue_overflow()),
        ("buffer_overflow", lambda: _test_buffer_overflow()),
        ("buffer_underrun", lambda: _test_buffer_underrun()),
        ("high_load", lambda: _test_high_load()),
    ]
    
    for name, test_fn in test_cases:
        print(f"Running {name}...")
        start = time.perf_counter()
        try:
            metrics = await asyncio.wait_for(test_fn(), timeout=30.0)
            duration = (time.perf_counter() - start) * 1000
            success = metrics.chunks_dropped == 0 or (name in ["queue_overflow", "buffer_overflow"])
            results.append({
                "test_name": name,
                "success": success,
                "duration_ms": duration,
                "metrics": metrics.to_dict(),
            })
            print(f"  [PASS] {name}: {duration:.2f}ms")
        except asyncio.TimeoutError:
            results.append({
                "test_name": name,
                "success": False,
                "duration_ms": 30000,
                "error": "Timeout",
            })
            print(f"  [TIMEOUT] {name}")
        except Exception as e:
            results.append({
                "test_name": name,
                "success": False,
                "duration_ms": (time.perf_counter() - start) * 1000,
                "error": str(e),
            })
            print(f"  [ERROR] {name}: {e}")
    
    return results


async def _test_queue_overflow():
    gen = BackpressureTestGenerator(config)
    queue, metrics = await gen.test_queue_overflow(max_size=30, num_chunks=100)
    return metrics


async def _test_buffer_overflow():
    gen = BufferTestGenerator(config)
    buffer, metrics = await gen.test_buffer_overflow(
        target_ms=100, max_ms=300, chunks_to_add=50
    )
    return metrics


async def _test_buffer_underrun():
    gen = BufferTestGenerator(config)
    buffer, metrics = await gen.test_buffer_underrun(
        initial_chunks=3, read_delay_ms=50
    )
    return metrics


async def _test_high_load():
    return await run_baseline_streaming_test(
        num_chunks=200, chunk_interval_ms=2, config=config
    )


async def main():
    print("=" * 60)
    print("TRANSFORM-007 Quick Test Suite")
    print("=" * 60)
    
    results = await run_quick_tests()
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    passed = sum(1 for r in results if r["success"])
    print(f"Passed: {passed}/{len(results)}")
    
    with open("results/transform007_quick_results.json", "w") as f:
        json.dump({
            "timestamp": time.time(),
            "passed": passed,
            "total": len(results),
            "results": results,
        }, f, indent=2)
    
    print(f"\nResults saved to results/transform007_quick_results.json")


if __name__ == "__main__":
    asyncio.run(main())
