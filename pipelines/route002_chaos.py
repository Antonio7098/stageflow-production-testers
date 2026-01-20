"""
Chaos pipeline for ROUTE-002: Routing decision explainability stress testing.

This pipeline tests routing behavior under adverse conditions including:
- LLM failures and timeouts
- Malformed inputs
- Policy violations
- High load scenarios
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import random
import uuid

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow import Pipeline, StageContext, StageKind, StageOutput
from stageflow.context import ContextSnapshot
from stageflow.helpers import LLMResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FaultyRouterStage:
    """
    ROUTE stage that simulates various failure modes.
    
    Failure modes:
    - High latency responses
    - Random failures
    - Malformed outputs
    - Confidence manipulation
    """
    
    name = "faulty_router"
    kind = StageKind.ROUTE
    
    def __init__(
        self,
        failure_rate: float = 0.1,
        latency_ms: int = 100,
        corrupt_output: bool = False,
        fake_confidence: bool = False,
    ):
        self.failure_rate = failure_rate
        self.latency_ms = latency_ms
        self.corrupt_output = corrupt_output
        self.fake_confidence = fake_confidence
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute routing with potential failures."""
        input_text = ctx.snapshot.input_text or ""
        scenario_id = ctx.snapshot.metadata.get("scenario_id", "unknown")
        
        # Simulate latency
        await asyncio.sleep(self.latency_ms / 1000)
        
        # Simulate random failures
        if random.random() < self.failure_rate:
            ctx.emit_event("routing.failure", {
                "type": "random_failure",
                "scenario_id": scenario_id,
            })
            return StageOutput.fail(
                error="Simulated routing failure",
                data={"failure_type": "random"},
            )
        
        # Determine route
        input_lower = input_text.lower()
        if "help" in input_lower or "issue" in input_lower:
            route = "support"
            base_confidence = 0.85
        elif "buy" in input_lower or "pricing" in input_lower:
            route = "sales"
            base_confidence = 0.85
        elif "billing" in input_lower or "charge" in input_lower:
            route = "billing"
            base_confidence = 0.90
        else:
            route = "general"
            base_confidence = 0.50
        
        # Apply failures
        if self.corrupt_output:
            # Return malformed output
            return StageOutput.ok(
                route=route,
                malformed_data="THIS_IS_CORRUPTED_DATA",
                # Missing confidence and reason_codes
            )
        
        if self.fake_confidence:
            # Return artificially high confidence
            confidence = 0.99
        else:
            confidence = base_confidence
        
        return StageOutput.ok(
            route=route,
            confidence=confidence,
            reason_codes=["keyword_match", "policy:v1.0"],
            explanation=f"Route determined: {route}",
        )


class TimeoutRouterStage:
    """ROUTE stage that simulates timeout conditions."""
    
    name = "timeout_router"
    kind = StageKind.ROUTE
    
    def __init__(self, timeout_ms: int = 5000, execute_time_ms: int = 10000):
        self.timeout_ms = timeout_ms
        self.execute_time_ms = execute_time_ms
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute routing with timeout simulation."""
        input_text = ctx.snapshot.input_text or ""
        
        # Simulate long-running operation
        await asyncio.sleep(self.execute_time_ms / 1000)
        
        return StageOutput.ok(
            route="general",
            confidence=0.5,
            reason_codes=["timeout_fallback"],
        )


class AdversarialInputStage:
    """Stage that processes adversarial inputs designed to test routing robustness."""
    
    name = "adversarial_processor"
    kind = StageKind.TRANSFORM
    
    def __init__(self, attack_type: str = "injection"):
        self.attack_type = attack_type
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        """Process adversarial input and report detection."""
        input_text = ctx.snapshot.input_text or ""
        scenario_id = ctx.snapshot.metadata.get("scenario_id", "unknown")
        
        detected = False
        attack_details = {}
        
        if self.attack_type == "injection":
            # Check for prompt injection patterns
            injection_patterns = [
                "ignore previous instructions",
                "system prompt",
                "developer mode",
                "jailbreak",
                "you are now",
            ]
            for pattern in injection_patterns:
                if pattern.lower() in input_text.lower():
                    detected = True
                    attack_details["pattern"] = pattern
                    attack_details["type"] = "prompt_injection"
                    break
        
        elif self.attack_type == "manipulation":
            # Check for confidence manipulation
            manipulation_patterns = [
                "i am certain",
                "trust me",
                "believe me",
                "very confident",
            ]
            for pattern in manipulation_patterns:
                if pattern.lower() in input_text.lower():
                    detected = True
                    attack_details["pattern"] = pattern
                    attack_details["type"] = "confidence_manipulation"
                    break
        
        elif self.attack_type == "stuffing":
            # Check for context stuffing (keyword repetition)
            words = input_text.lower().split()
            if len(words) > 10:
                word_counts = {}
                for word in words:
                    word_counts[word] = word_counts.get(word, 0) + 1
                max_count = max(word_counts.values())
                if max_count > len(words) / 3:
                    detected = True
                    attack_details["type"] = "context_stuffing"
                    attack_details["max_repeat"] = max_count
        
        ctx.emit_event("adversarial.detection", {
            "detected": detected,
            "attack_type": self.attack_type,
            "scenario_id": scenario_id,
            "details": attack_details,
        })
        
        if detected:
            return StageOutput.cancel(
                reason=f"Adversarial input detected: {attack_details.get('type', 'unknown')}",
                data={"attack_detected": True, **attack_details},
            )
        
        return StageOutput.ok(
            processed=True,
            attack_detected=False,
        )


class ErrorHandlerStage:
    """Stage that handles errors from upstream stages."""
    
    name = "error_handler"
    kind = StageKind.GUARD
    
    def __init__(self, max_retries: int = 3, fallback_route: str = "general"):
        self.max_retries = max_retries
        self.fallback_route = fallback_route
        self.retry_count = 0
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        """Handle errors from upstream."""
        # Check for errors in upstream outputs
        router_output = ctx.inputs.get("router")
        
        if router_output is None:
            # No router output - use fallback
            ctx.emit_event("error.fallback", {
                "reason": "no_router_output",
                "fallback_route": self.fallback_route,
            })
            return StageOutput.ok(
                route=self.fallback_route,
                confidence=0.3,
                reason_codes=["error_fallback"],
                fallback_applied=True,
            )
        
        if isinstance(router_output, dict):
            if router_output.get("error"):
                # Error occurred - increment retry count
                self.retry_count += 1
                ctx.emit_event("error.retry", {
                    "retry": self.retry_count,
                    "error": router_output.get("error"),
                })
                
                if self.retry_count >= self.max_retries:
                    return StageOutput.ok(
                        route=self.fallback_route,
                        confidence=0.2,
                        reason_codes=["max_retries_exceeded"],
                        fallback_applied=True,
                    )
                else:
                    # Let it retry
                    return StageOutput.fail(
                        error=f"Retry {self.retry_count}/{self.max_retries}",
                    )
        
        return StageOutput.ok(
            handled=True,
            retry_count=self.retry_count,
        )


class SilentFailureDetectorStage:
    """Stage that detects silent failures in routing."""
    
    name = "silent_failure_detector"
    kind = StageKind.GUARD
    
    def __init__(self, golden_outputs: Dict[str, Any]):
        self.golden_outputs = golden_outputs
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        """Detect silent failures by comparing to golden outputs."""
        scenario_id = ctx.snapshot.metadata.get("scenario_id", "unknown")
        
        if scenario_id not in self.golden_outputs:
            return StageOutput.skip(reason="No golden output for this scenario")
        
        golden = self.golden_outputs[scenario_id]
        actual = ctx.inputs.get("router", {})
        
        silent_failures = []
        
        # Check if expected route was selected
        expected_route = golden.get("route")
        actual_route = actual.get("route")
        if expected_route != actual_route:
            silent_failures.append({
                "type": "route_mismatch",
                "expected": expected_route,
                "actual": actual_route,
            })
        
        # Check if confidence is provided
        expected_confidence = golden.get("confidence", 0.0)
        actual_confidence = actual.get("confidence", 0.0)
        if actual_confidence is None:
            silent_failures.append({
                "type": "missing_confidence",
                "expected": expected_confidence,
            })
        
        # Check if explanation is provided
        expected_explain = golden.get("should_explain", True)
        actual_explanation = actual.get("explanation")
        if expected_explain and not actual_explanation:
            silent_failures.append({
                "type": "missing_explanation",
                "expected": True,
            })
        
        # Check if reason codes are provided
        expected_reason_codes = golden.get("reason_codes", [])
        actual_reason_codes = actual.get("reason_codes", [])
        if not actual_reason_codes and expected_reason_codes:
            silent_failures.append({
                "type": "missing_reason_codes",
                "expected": expected_reason_codes,
            })
        
        ctx.emit_event("silent_failure.check", {
            "scenario_id": scenario_id,
            "silent_failures_count": len(silent_failures),
            "silent_failures": silent_failures,
        })
        
        if silent_failures:
            return StageOutput.cancel(
                reason=f"Silent failures detected: {len(silent_failures)}",
                data={
                    "silent_failures": silent_failures,
                    "scenario_id": scenario_id,
                },
            )
        
        return StageOutput.ok(
            no_silent_failures=True,
            silent_failures_count=0,
        )


async def run_chaos_test(
    scenario_id: str,
    failure_config: Dict[str, Any],
    results_dir: str = "results/route002",
) -> Dict[str, Any]:
    """Run a chaos test with specified failure configuration."""
    from mocks.route002_mock_data import get_scenario_by_id
    
    scenario = get_scenario_by_id(scenario_id)
    if not scenario:
        raise ValueError(f"Unknown scenario: {scenario_id}")
    
    # Create pipeline based on failure config
    pipeline = Pipeline()
    
    # Add stages based on config
    if failure_config.get("faulty_router"):
        pipeline = pipeline.with_stage(
            "router",
            FaultyRouterStage(
                failure_rate=failure_config.get("failure_rate", 0.1),
                latency_ms=failure_config.get("latency_ms", 100),
                corrupt_output=failure_config.get("corrupt_output", False),
                fake_confidence=failure_config.get("fake_confidence", False),
            ),
            StageKind.ROUTE,
        )
    
    if failure_config.get("adversarial_processor"):
        pipeline = pipeline.with_stage(
            "processor",
            AdversarialInputStage(attack_type=failure_config.get("attack_type", "injection")),
            StageKind.TRANSFORM,
            dependencies=("router",) if failure_config.get("faulty_router") else None,
        )
    
    if failure_config.get("error_handler"):
        pipeline = pipeline.with_stage(
            "handler",
            ErrorHandlerStage(
                max_retries=failure_config.get("max_retries", 3),
                fallback_route=failure_config.get("fallback_route", "general"),
            ),
            StageKind.GUARD,
            dependencies=("router",) if failure_config.get("faulty_router") else None,
        )
    
    # Create snapshot
    from stageflow.context import RunIdentity, Conversation
    
    run_id = RunIdentity(
        pipeline_run_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        interaction_id=uuid.uuid4(),
    )
    
    snapshot = ContextSnapshot(
        run_id=run_id,
        conversation=Conversation(messages=[]),
        input_text=scenario.input_text,
        topology="routing_chaos_test",
        execution_mode="chaos_test",
        metadata={
            "scenario_id": scenario.id,
            "scenario_name": scenario.name,
            "failure_config": failure_config,
        },
    )
    
    # Run pipeline
    result = await pipeline.run(snapshot)
    
    # Collect outputs
    outputs = {}
    if result.output_bag:
        for key in ["router", "processor", "handler"]:
            if result.output_bag.has(key):
                entry = result.output_bag.get(key)
                outputs[key] = entry.output.data
    
    return {
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "failure_config": failure_config,
        "status": result.status.name,
        "duration_ms": result.duration_ms,
        "outputs": outputs,
        "error": str(result.error) if result.error else None,
    }


async def run_all_chaos_tests(
    golden_outputs: Dict[str, Any],
    results_dir: str = "results/route002",
) -> List[Dict[str, Any]]:
    """Run comprehensive chaos tests."""
    from mocks.route002_mock_data import ADVERSARIAL_SCENARIOS, EDGE_CASE_SCENARIOS
    
    scenarios = ADVERSARIAL_SCENARIOS + EDGE_CASE_SCENARIOS
    results = []
    
    results_path = Path(results_dir)
    results_path.mkdir(parents=True, exist_ok=True)
    
    # Define chaos test configurations
    chaos_configs = [
        {
            "name": "faulty_router_high_failure",
            "faulty_router": True,
            "failure_rate": 0.3,
            "latency_ms": 200,
        },
        {
            "name": "faulty_router_corrupt_output",
            "faulty_router": True,
            "failure_rate": 0.0,
            "corrupt_output": True,
        },
        {
            "name": "faulty_router_fake_confidence",
            "faulty_router": True,
            "failure_rate": 0.0,
            "fake_confidence": True,
        },
        {
            "name": "adversarial_injection",
            "faulty_router": True,
            "adversarial_processor": True,
            "attack_type": "injection",
        },
        {
            "name": "adversarial_manipulation",
            "faulty_router": True,
            "adversarial_processor": True,
            "attack_type": "manipulation",
        },
        {
            "name": "adversarial_stuffing",
            "faulty_router": True,
            "adversarial_processor": True,
            "attack_type": "stuffing",
        },
        {
            "name": "error_handler_recovery",
            "faulty_router": True,
            "error_handler": True,
            "failure_rate": 0.5,
            "max_retries": 3,
            "fallback_route": "general",
        },
    ]
    
    for scenario in scenarios:
        for config in chaos_configs:
            logger.info(f"Running chaos test: {scenario.id} - {config['name']}")
            try:
                result = await run_chaos_test(
                    scenario.id,
                    config,
                    results_dir,
                )
                result["config_name"] = config["name"]
                results.append(result)
            except Exception as e:
                logger.error(f"Chaos test failed: {scenario.id} - {config['name']} - {e}")
                results.append({
                    "scenario_id": scenario.id,
                    "config_name": config["name"],
                    "status": "FAILED",
                    "error": str(e),
                })
    
    # Write results
    results_file = results_path / "chaos_results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info(f"Chaos tests completed: {len(results)} test runs")
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run ROUTE-002 chaos tests")
    parser.add_argument("--scenario", type=str, help="Run specific scenario")
    parser.add_argument("--config", type=str, help="JSON config for failure mode")
    parser.add_argument("--all", action="store_true", help="Run all chaos tests")
    parser.add_argument("--results-dir", type=str, default="results/route002")
    
    args = parser.parse_args()
    
    if args.all:
        from mocks.route002_mock_data import ADVERSARIAL_SCENARIOS, EDGE_CASE_SCENARIOS
        golden = {}
        results = asyncio.run(run_all_chaos_tests(golden, args.results_dir))
        print(f"Completed {len(results)} chaos tests")
    elif args.scenario and args.config:
        import json
        config = json.loads(args.config)
        result = asyncio.run(run_chaos_test(args.scenario, config, args.results_dir))
        print(json.dumps(result, indent=2, default=str))
    else:
        # Run a sample chaos test
        result = asyncio.run(run_chaos_test(
            "route-adv-001",
            {"faulty_router": True, "failure_rate": 0.1},
            args.results_dir,
        ))
        print(json.dumps(result, indent=2, default=str))
