#!/usr/bin/env python3
"""
ENRICH-002 Test Runner: Embedding Drift and Index Desync

Usage:
    python run_enrich002_tests.py [--output-dir DIR] [--verbose]

This script executes comprehensive embedding drift tests for Stageflow's
ENRICH stage reliability.
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines.enrich002_pipelines import (
    run_all_enrich002_tests,
    run_comprehensive_tests,
    run_silent_failure_detection_tests,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def setup_output_directory(output_dir: str) -> Path:
    """Set up output directory structure."""
    base_path = Path(output_dir) / "enrich002"
    base_path.mkdir(parents=True, exist_ok=True)
    (base_path / "logs").mkdir(exist_ok=True)
    (base_path / "metrics").mkdir(exist_ok=True)
    return base_path


async def main():
    parser = argparse.ArgumentParser(description="ENRICH-002 Embedding Drift Test Runner")
    parser.add_argument(
        "--output-dir",
        default="results",
        help="Base output directory for results (default: results)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--test-type",
        choices=["all", "comprehensive", "silent-failures"],
        default="all",
        help="Type of tests to run (default: all)",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    output_dir = setup_output_directory(args.output_dir)
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Test type: {args.test_type}")
    logger.info("=" * 60)

    try:
        if args.test_type == "all":
            results = await run_all_enrich002_tests(output_dir)
        elif args.test_type == "comprehensive":
            results = await run_comprehensive_tests(
                result_file=str(output_dir / "comprehensive_results.json")
            )
        elif args.test_type == "silent-failures":
            results = await run_silent_failure_detection_tests(
                result_file=str(output_dir / "silent_failure_results.json")
            )

        # Log final summary
        logger.info("\n" + "=" * 60)
        logger.info("ENRICH-002 Test Execution Complete")
        logger.info("=" * 60)
        logger.info(f"Output directory: {output_dir}")
        logger.info("Results files:")
        for f in output_dir.glob("*.json"):
            logger.info(f"  - {f.name}")

        return 0

    except Exception as e:
        logger.error(f"Test execution failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
