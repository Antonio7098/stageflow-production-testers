#!/usr/bin/env python3
"""
ENRICH-007 Test Runner: Vector DB Connection Resilience

This script runs the comprehensive test suite for vector DB connection
resilience in Stageflow ENRICH stages.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from pipelines.enrich007_pipelines import (
    run_all_enrich007_tests,
    run_comprehensive_tests,
    run_silent_failure_detection_tests,
    run_retry_pattern_tests,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Main entry point for test execution."""
    logger.info("=" * 70)
    logger.info("ENRICH-007: Vector DB Connection Resilience Test Suite")
    logger.info(f"Started at: {datetime.now().isoformat()}")
    logger.info("=" * 70)
    
    try:
        results = await run_all_enrich007_tests()
        
        logger.info("\n" + "=" * 70)
        logger.info("All Tests Completed Successfully")
        logger.info("=" * 70)
        logger.info(f"Output directory: {results['output_dir']}")
        
        # Print summary
        comprehensive = results.get('comprehensive', {})
        summary = comprehensive.get('summary', {})
        
        logger.info(f"\nTest Summary:")
        logger.info(f"  Total Tests: {summary.get('total_tests', 0)}")
        logger.info(f"  Passed: {summary.get('passed', 0)}")
        logger.info(f"  Failed: {summary.get('failed', 0)}")
        logger.info(f"  Silent Failures: {summary.get('silent_failures', 0)}")
        
        return results
        
    except Exception as e:
        logger.error(f"Test execution failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
