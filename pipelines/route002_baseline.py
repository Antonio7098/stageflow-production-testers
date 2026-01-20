"""
Baseline pipeline for ROUTE-002: Routing decision explainability testing.

This pipeline tests basic routing functionality with explainability features.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from stageflow import Pipeline, StageContext, StageKind, StageOutput
from stageflow.context import ContextSnapshot, Conversation, RunIdentity, Message

from mocks.route002_mock_data import (
    get_all_scenarios,
    get_scenario_by_id,
    RouteType,
    GOLDEN_OUTPUTS,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ExplainableRouterStage:
    """
    ROUTE stage with enhanced explainability features.
    
    Features:
    - Confidence scoring
    - Reason codes
    - Policy attribution
    - Explanation generation
    
    Uses keyword-based routing for reliability (no external API calls).
    """
    
    name = "explainable_router"
    kind = StageKind.ROUTE
    
    def __init__(
        self,
        confidence_threshold: float = 0.7,
        policy_version: str = "v1.0",
    ):
        self.confidence_threshold = confidence_threshold
        self.policy_version = policy_version
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        """Execute routing with full explainability."""
        input_text = ctx.snapshot.input_text or ""
        scenario_id = ctx.snapshot.metadata.get("scenario_id", "unknown")
        
        logger.info(f"Routing request: {scenario_id}", extra={
            "input_length": len(input_text),
            "scenario_id": scenario_id,
        })
        
        # Analyze input and make routing decision
        routing_decision = self._analyze_and_route(input_text)
        
        # Generate explanation
        explanation = self._generate_explanation(routing_decision, input_text)
        
        # Emit routing event for observability
        ctx.try_emit_event("routing.decision", {
            "route": routing_decision["route"].value,
            "confidence": routing_decision["confidence"],
            "reason_codes": routing_decision["reason_codes"],
            "policy_version": self.policy_version,
            "scenario_id": scenario_id,
        })
        
        return StageOutput.ok(
            route=routing_decision["route"].value,
            confidence=routing_decision["confidence"],
            reason_codes=routing_decision["reason_codes"],
            policy_version=self.policy_version,
            explanation=explanation,
            routing_timestamp=datetime.utcnow().isoformat(),
        )
    
    def _analyze_and_route(self, input_text: str) -> Dict[str, Any]:
        """Analyze input and determine route."""
        input_lower = input_text.lower()
        
        # Keyword-based routing with confidence
        route = RouteType.GENERAL
        confidence = 0.5
        reason_codes = []
        
        # Support keywords
        support_keywords = ["help", "login", "account", "password", "access", "issue", "problem"]
        if any(kw in input_lower for kw in support_keywords):
            route = RouteType.SUPPORT
            confidence = 0.85
            reason_codes = ["keyword_match:support"]
        
        # Sales keywords
        sales_keywords = ["pricing", "plan", "buy", "purchase", "enterprise", "quote", "demo"]
        if any(kw in input_lower for kw in sales_keywords):
            if route == RouteType.GENERAL:
                route = RouteType.SALES
                confidence = 0.85
                reason_codes = ["keyword_match:sales"]
        
        # Billing keywords
        billing_keywords = ["charge", "bill", "payment", "invoice", "subscription"]
        if any(kw in input_lower for kw in billing_keywords):
            if route == RouteType.GENERAL:
                route = RouteType.BILLING
                confidence = 0.90
                reason_codes = ["keyword_match:billing"]
        
        # Technical keywords
        technical_keywords = ["api", "error", "bug", "crash", "not working", "500", "404"]
        if any(kw in input_lower for kw in technical_keywords):
            if route == RouteType.GENERAL:
                route = RouteType.TECHNICAL
                confidence = 0.90
                reason_codes = ["keyword_match:technical"]
        
        # Refund keywords
        refund_keywords = ["refund", "money back", "return"]
        if any(kw in input_lower for kw in refund_keywords):
            if route == RouteType.GENERAL:
                route = RouteType.REFUND
                confidence = 0.85
                reason_codes = ["keyword_match:refund"]
        
        # Escalation triggers
        escalation_keywords = ["urgent", "lawsuit", "lawyer", "attorney"]
        if any(kw in input_lower for kw in escalation_keywords):
            route = RouteType.ESCALATION
            confidence = 0.95
            reason_codes = ["escalation_trigger"]
        
        # Check for empty or very short input
        if len(input_text.strip()) == 0:
            route = RouteType.GENERAL
            confidence = 0.3
            reason_codes = ["empty_input_default"]
        elif len(input_text) < 10:
            confidence = max(0.4, confidence - 0.2)
            reason_codes.append("short_input_reduced_confidence")
        
        # Add policy attribution
        reason_codes.append(f"policy:{self.policy_version}")
        
        return {
            "route": route,
            "confidence": confidence,
            "reason_codes": reason_codes,
        }
    
    def _generate_explanation(
        self,
        decision: Dict[str, Any],
        input_text: str,
    ) -> str:
        """Generate human-readable explanation of routing decision."""
        route = decision["route"]
        return (
            f"Request routed to {route.value}_pipeline with confidence {decision['confidence']:.2f}. "
            f"Reason: {', '.join(decision['reason_codes'])}. "
            f"Policy version: {self.policy_version}. "
            f"Input length: {len(input_text)} characters."
        )


class ConfidenceValidatorStage:
    """Stage to validate routing confidence scores."""
    
    name = "confidence_validator"
    kind = StageKind.GUARD
    
    def __init__(self, min_confidence: float = 0.0):
        self.min_confidence = min_confidence
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        """Validate confidence scores."""
        route = ctx.inputs.get("route")
        confidence = ctx.inputs.get("confidence", 0.0)
        
        if confidence < self.min_confidence:
            return StageOutput.cancel(
                reason=f"Confidence {confidence:.2f} below threshold {self.min_confidence}",
                data={"confidence": confidence, "threshold": self.min_confidence},
            )
        
        ctx.try_emit_event("validation.confidence", {
            "passed": True,
            "confidence": confidence,
        })
        
        return StageOutput.ok(
            validated=True,
            confidence=confidence,
        )


class ExplainabilityAuditStage:
    """Stage to audit routing explainability metrics."""
    
    name = "explainability_audit"
    kind = StageKind.WORK
    
    def __init__(self, results_dir: str = "results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
    
    async def execute(self, ctx: StageContext) -> StageOutput:
        """Audit routing explainability."""
        route = ctx.inputs.get("route")
        confidence = ctx.inputs.get("confidence", 0.0)
        reason_codes = ctx.inputs.get("reason_codes", [])
        explanation = ctx.inputs.get("explanation", "")
        policy_version = ctx.inputs.get("policy_version", "unknown")
        
        # Check explainability criteria
        has_explanation = bool(explanation)
        has_reason_codes = len(reason_codes) > 0
        has_policy = policy_version != "unknown"
        
        # Calculate quality score
        quality_score = 0.0
        if has_explanation:
            quality_score += 0.4
        if has_reason_codes:
            quality_score += 0.3
        if has_policy:
            quality_score += 0.3
        
        audit_data = {
            "route": route,
            "confidence": confidence,
            "explanation_provided": has_explanation,
            "explanation_length": len(explanation) if explanation else 0,
            "reason_codes": reason_codes,
            "reason_codes_count": len(reason_codes),
            "policy_attributed": has_policy,
            "policy_version": policy_version,
            "quality_score": quality_score,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Emit audit event
        ctx.try_emit_event("audit.explainability", audit_data)
        
        return StageOutput.ok(
            audit_passed=quality_score >= 0.7,
            quality_score=quality_score,
            audit_data=audit_data,
        )


async def run_baseline_test(
    scenario_id: str,
    results_dir: str = "results/route002",
) -> Dict[str, Any]:
    """Run a single baseline test for a scenario."""
    from mocks.route002_mock_data import get_scenario_by_id
    
    scenario = get_scenario_by_id(scenario_id)
    if not scenario:
        raise ValueError(f"Unknown scenario: {scenario_id}")
    
    # Create pipeline
    pipeline = Pipeline()
    pipeline = (
        pipeline
        .with_stage("router", ExplainableRouterStage(), StageKind.ROUTE)
        .with_stage("validator", ConfidenceValidatorStage(min_confidence=0.3), StageKind.GUARD, dependencies=("router",))
        .with_stage("auditor", ExplainabilityAuditStage(results_dir=results_dir), StageKind.WORK, dependencies=("validator",))
    )
    
    # Create snapshot
    from stageflow.context import RunIdentity, Conversation
    from stageflow.stages.inputs import StageInputs
    from stageflow import PipelineTimer
    from uuid import uuid4
    
    run_id = RunIdentity(
        pipeline_run_id=uuid4(),
        request_id=uuid4(),
        session_id=uuid4(),
        user_id=uuid4(),
        org_id=uuid4(),
        interaction_id=uuid4(),
    )
    
    snapshot = ContextSnapshot(
        run_id=run_id,
        conversation=Conversation(messages=[]),
        input_text=scenario.input_text,
        topology="explainable_routing_baseline",
        execution_mode="test",
        metadata={
            "scenario_id": scenario.id,
            "scenario_name": scenario.name,
            "adversarial": scenario.adversarial,
            "edge_case": scenario.edge_case,
        },
    )
    
    # Create stage context
    ctx = StageContext(
        snapshot=snapshot,
        inputs=StageInputs(snapshot=snapshot),
        stage_name="pipeline_entry",
        timer=PipelineTimer(),
    )
    
    # Build pipeline graph
    graph = pipeline.build()
    
    # Run pipeline
    outputs = await graph.run(ctx)
    
    # Collect outputs
    result_outputs = {}
    for key in ["router", "validator", "auditor"]:
        if key in outputs:
            result_outputs[key] = outputs[key].data
    
    return {
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "input_text": scenario.input_text,
        "expected_route": scenario.expected_route.value,
        "actual_route": result_outputs.get("router", {}).get("route"),
        "confidence": result_outputs.get("router", {}).get("confidence"),
        "reason_codes": result_outputs.get("router", {}).get("reason_codes", []),
        "explanation": result_outputs.get("router", {}).get("explanation"),
        "quality_score": result_outputs.get("auditor", {}).get("quality_score"),
        "passed": result_outputs.get("auditor", {}).get("audit_passed", False),
        "status": "COMPLETED",
    }


async def run_all_baseline_tests(
    results_dir: str = "results/route002",
) -> List[Dict[str, Any]]:
    """Run all baseline routing tests."""
    from mocks.route002_mock_data import get_all_scenarios
    
    scenarios = get_all_scenarios()
    results = []
    
    results_path = Path(results_dir)
    results_path.mkdir(parents=True, exist_ok=True)
    
    for scenario in scenarios:
        logger.info(f"Running baseline test: {scenario.id}")
        try:
            result = await run_baseline_test(scenario.id, results_dir)
            results.append(result)
        except Exception as e:
            logger.error(f"Test failed: {scenario.id} - {e}")
            results.append({
                "scenario_id": scenario.id,
                "scenario_name": scenario.name,
                "status": "FAILED",
                "error": str(e),
            })
    
    # Write results
    results_file = results_path / "baseline_results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info(f"Baseline tests completed: {len(results)} scenarios")
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run ROUTE-002 baseline tests")
    parser.add_argument("--scenario", type=str, help="Run specific scenario")
    parser.add_argument("--all", action="store_true", help="Run all scenarios")
    parser.add_argument("--results-dir", type=str, default="results/route002")
    
    args = parser.parse_args()
    
    if args.all:
        results = asyncio.run(run_all_baseline_tests(args.results_dir))
        print(f"Completed {len(results)} baseline tests")
    elif args.scenario:
        result = asyncio.run(run_baseline_test(args.scenario, args.results_dir))
        print(json.dumps(result, indent=2, default=str))
    else:
        # Run a sample test
        result = asyncio.run(run_baseline_test("route-001", args.results_dir))
        print(json.dumps(result, indent=2, default=str))
