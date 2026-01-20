"""
DAG-007 Test Runner: Dynamic DAG Modification During Execution

This script executes all DAG-007 test scenarios, captures results,
and logs findings to the structured reporting system.

Usage:
    python run_dag007_tests.py [--output-dir OUTPUT_DIR] [--verbose]
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"results/logs/dag007_test_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("dag007_runner")


def save_results(results: dict, output_dir: Path):
    """Save test results to JSON files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save full results
    results_file = output_dir / "dag007_results.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Results saved to {results_file}")
    
    # Save summary
    summary = {
        'test_suite': results.get('test_suite'),
        'target': results.get('target'),
        'completed_at': datetime.now().isoformat(),
        'summary': results.get('summary'),
    }
    summary_file = output_dir / "dag007_summary.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Summary saved to {summary_file}")
    
    return results_file, summary_file


def analyze_results(results: dict) -> list[dict]:
    """
    Analyze test results and extract findings.
    
    Returns a list of findings in the required format.
    """
    findings = []
    
    # Analyze baseline test
    baseline = results.get('tests', {}).get('baseline', {})
    if baseline.get('success'):
        findings.append({
            'type': 'strength',
            'title': 'Baseline pipeline execution works correctly',
            'description': 'Static pipelines without modification execute as expected',
            'component': 'Pipeline',
            'evidence': f"Executed {baseline.get('total_stages', 0)} stages successfully",
        })
    else:
        findings.append({
            'type': 'bug',
            'title': 'Baseline pipeline execution failed',
            'description': 'Static pipeline without modifications failed unexpectedly',
            'component': 'Pipeline',
            'severity': 'high',
            'error': baseline.get('error'),
        })
    
    # Analyze modification tests
    for test_name, test_result in results.get('tests', {}).items():
        if 'modification' in test_name:
            if test_result.get('success'):
                stats = test_result.get('modification_stats', {})
                findings.append({
                    'type': 'strength',
                    'title': f'{test_name} - Dynamic modification functional',
                    'description': 'Pipeline supports dynamic modification during execution',
                    'component': 'StageGraph',
                    'evidence': f"Modifications: {stats.get('total_modifications', 0)}, Success rate: {stats.get('success_rate', 0):.1f}%",
                })
            else:
                findings.append({
                    'type': 'finding',
                    'title': f'{test_name} - Dynamic modification has issues',
                    'description': test_result.get('error', 'Unknown error'),
                    'component': 'StageGraph',
                    'severity': 'medium',
                    'error_type': test_result.get('error_type'),
                })
    
    # Analyze pipeline replacement
    replacement = results.get('tests', {}).get('pipeline_replacement', {})
    if replacement.get('success'):
        findings.append({
            'type': 'dx',
            'title': 'Pipeline replacement attempts are handled gracefully',
            'description': 'Replacement attempts during execution do not crash the pipeline',
            'component': 'PipelineRegistry',
            'category': 'error_messages',
            'severity': 'low',
        })
    
    # Analyze cycle detection
    cycle_test = results.get('tests', {}).get('cycle_detection', {})
    if cycle_test.get('success'):
        findings.append({
            'type': 'strength',
            'title': 'Cycle detection utilities work correctly',
            'description': 'Helper functions properly detect potential cycles',
            'component': 'Utilities',
            'evidence': str(cycle_test.get('cycle_detection_tests', {})),
        })
    
    # Analyze concurrent modifications
    concurrent = results.get('tests', {}).get('concurrent_modifications', {})
    if concurrent.get('successful', 0) > 0:
        findings.append({
            'type': 'strength',
            'title': 'Concurrent modification attempts handled',
            'description': f"Successfully processed {concurrent.get('successful', 0)} concurrent modifications",
            'component': 'MockDAGModifier',
            'evidence': f"Failed: {concurrent.get('failed', 0)}, Time: {concurrent.get('execution_time_ms', 0):.1f}ms",
        })
    
    # Analyze invalid modifications
    invalid = results.get('tests', {}).get('invalid_modifications', {})
    if invalid.get('all_correctly_handled'):
        findings.append({
            'type': 'strength',
            'title': 'Invalid modification errors handled correctly',
            'description': 'Error handling for invalid modifications works as expected',
            'component': 'MockDAGModifier',
        })
    
    return findings


async def run_tests(verbose: bool = False) -> dict[str, Any]:
    """
    Run all DAG-007 tests.
    
    Returns a comprehensive results dictionary.
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("=" * 80)
    logger.info("DAG-007: Dynamic DAG Modification During Execution - Test Suite")
    logger.info("=" * 80)
    logger.info(f"Started at: {datetime.now().isoformat()}")
    logger.info(f"Run ID: {uuid.uuid4()}")
    
    # Import test modules
    from pipelines.dag007_pipelines import run_all_tests
    from mocks.dag007_mock_data import (
        MockDAGModifier,
        DynamicWorkloadGenerator,
        CycleDetector,
        DYNAMIC_DAG_TEST_CONFIGS,
    )
    
    start_time = time.perf_counter()
    
    try:
        # Run all test pipelines
        results = await run_all_tests()
        
        # Add metadata
        results['run_id'] = str(uuid.uuid4())
        results['started_at'] = datetime.now().isoformat()
        results['duration_seconds'] = time.perf_counter() - start_time
        
        # Analyze and extract findings
        findings = analyze_results(results)
        results['findings'] = findings
        
        # Log findings summary
        logger.info("\n" + "=" * 80)
        logger.info("FINDINGS SUMMARY")
        logger.info("=" * 80)
        for finding in findings:
            logger.info(f"[{finding.get('type', 'unknown').upper()}] {finding.get('title')}")
        
        return results
        
    except Exception as e:
        logger.error(f"Test suite failed: {e}", exc_info=True)
        return {
            'test_suite': 'DAG-007',
            'target': 'Dynamic DAG modification during execution',
            'error': str(e),
            'error_type': type(e).__name__,
            'success': False,
            'completed_at': datetime.now().isoformat(),
            'duration_seconds': time.perf_counter() - start_time,
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="DAG-007 Test Runner: Dynamic DAG modification during execution"
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path("results"),
        help='Output directory for results',
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging',
    )
    
    args = parser.parse_args()
    
    async def run():
        results = await run_tests(args.verbose)
        
        # Save results
        results_file, summary_file = save_results(results, args.output_dir)
        
        # Print summary
        print("\n" + "=" * 80)
        print("TEST SUITE COMPLETE")
        print("=" * 80)
        print(f"Results: {results_file}")
        print(f"Summary: {summary_file}")
        
        if 'summary' in results:
            summary = results['summary']
            print(f"\nPassed: {summary.get('passed', 0)}/{summary.get('total_tests', 0)}")
            print(f"Pass Rate: {summary.get('pass_rate', 0):.1f}%")
        
        return results
    
    results = asyncio.run(run())
    
    # Exit with appropriate code
    success = results.get('summary', {}).get('pass_rate', 0) >= 70 or results.get('success', False)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
