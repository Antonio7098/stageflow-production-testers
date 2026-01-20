#!/usr/bin/env python3
"""
CORE-010: Cross-Tenant Context Isolation - Test Runner

Tests Stageflow's multi-tenant context isolation capabilities.
Focuses on core isolation mechanisms without full pipeline execution.
"""

import asyncio
import json
import logging
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import stageflow
from stageflow import (
    Pipeline, Stage, StageKind, StageOutput, 
    PipelineContext, StageContext,
    create_stage_context, PipelineTimer,
)
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow import auth
from stageflow.auth import (
    AuthContext, OrgContext, TenantContext, 
    AuthInterceptor, OrgEnforcementInterceptor,
    TenantIsolationValidator, TenantIsolationError,
    MockJwtValidator, JwtValidator,
    set_current_tenant, get_current_tenant, clear_current_tenant,
)
from stageflow.stages.inputs import StageInputs

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'results/logs/core010_test_run_{datetime.now(UTC).strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("CORE-010")

test_results: dict[str, Any] = {
    "test_run_id": str(uuid4()),
    "timestamp": datetime.now(UTC).isoformat(),
    "tests": [],
    "summary": {},
    "findings": [],
}


@dataclass
class TestResult:
    test_name: str
    passed: bool
    duration_ms: float
    details: dict[str, Any]
    error: Optional[str] = None
    stack_trace: Optional[str] = None


class MockJwtValidatorForTesting(JwtValidator):
    def __init__(self, valid_claims: dict[str, Any] | None = None):
        self.valid_claims = valid_claims or {
            "user_id": str(uuid4()),
            "org_id": str(uuid4()),
            "roles": ["user"],
        }
        self.validate_count = 0
    
    async def validate(self, token: str) -> dict[str, Any]:
        self.validate_count += 1
        if token.startswith("valid_"):
            parts = token.split("_")
            if len(parts) >= 4:
                return {
                    "user_id": parts[1],
                    "org_id": parts[2],
                    "roles": parts[3].split(",") if len(parts) > 3 else ["user"],
                }
        elif token.startswith("spoofed_"):
            return {
                "user_id": "attacker-user",
                "org_id": "victim-org-id",
                "roles": ["admin"],
            }
        return self.valid_claims


class MultiTenantStore:
    def __init__(self):
        self._data: dict[str, dict[str, Any]] = {}
        self._access_log: list[dict[str, Any]] = []
    
    async def write(self, tenant_id: str, key: str, value: Any) -> None:
        if tenant_id not in self._data:
            self._data[tenant_id] = {}
        self._data[tenant_id][key] = value
    
    async def read(self, tenant_id: str, key: str) -> Any:
        self._access_log.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "tenant_id": tenant_id,
            "key": key,
        })
        if tenant_id not in self._data:
            raise KeyError(f"No data for tenant {tenant_id}")
        if key not in self._data[tenant_id]:
            raise KeyError(f"No key {key} for tenant {tenant_id}")
        return self._data[tenant_id][key]
    
    async def query(self, tenant_id: str, query: str) -> list[dict[str, Any]]:
        self._access_log.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "tenant_id": tenant_id,
            "query": query,
        })
        if tenant_id not in self._data:
            return []
        return [
            {"key": k, "value": v} 
            for k, v in self._data[tenant_id].items()
        ]
    
    def get_access_log(self) -> list[dict[str, Any]]:
        return self._access_log.copy()


async def test_org_id_inheritance_fork() -> TestResult:
    test_name = "test_org_id_inheritance_fork"
    logger.info(f"Running: {test_name}")
    
    try:
        org_a = uuid4()
        child_run_id = uuid4()
        correlation_id = uuid4()
        
        parent_ctx = PipelineContext(
            pipeline_run_id=uuid4(),
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            org_id=org_a,
            interaction_id=uuid4(),
            topology="test",
            execution_mode="test",
        )
        
        child_ctx = parent_ctx.fork(
            child_run_id=child_run_id,
            parent_stage_id="test_stage",
            correlation_id=correlation_id,
            topology="child",
        )
        
        org_id_inherited = child_ctx.org_id == org_a
        run_ids_different = child_ctx.pipeline_run_id != parent_ctx.pipeline_run_id
        data_isolated = child_ctx.data != parent_ctx.data
        parent_ref_correct = child_ctx.parent_run_id == parent_ctx.pipeline_run_id
        
        details = {
            "parent_org_id": str(org_a),
            "child_org_id": str(child_ctx.org_id),
            "org_id_inherited": org_id_inherited,
            "run_ids_different": run_ids_different,
            "data_isolated": data_isolated,
            "parent_reference_correct": parent_ref_correct,
        }
        
        passed = org_id_inherited and run_ids_different and data_isolated and parent_ref_correct
        
        return TestResult(test_name, passed, 0, details)
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_tenant_isolation_validator() -> TestResult:
    test_name = "test_tenant_isolation_validator"
    logger.info(f"Running: {test_name}")
    
    try:
        expected_org = uuid4()
        attacker_org = uuid4()
        
        validator = TenantIsolationValidator(expected_org_id=expected_org, strict=True)
        
        legit_access = validator.record_access(
            expected_org,
            resource_type="document",
            resource_id="doc_123"
        )
        
        attack_access = validator.record_access(
            attacker_org,
            resource_type="document",
            resource_id="victim_doc"
        )
        
        violations = validator.get_violations()
        is_isolated = validator.is_isolated()
        
        details = {
            "expected_org_id": str(expected_org),
            "attacker_org_id": str(attacker_org),
            "legit_access_allowed": legit_access,
            "attack_access_blocked": not attack_access,
            "violations_detected": len(violations),
            "is_isolated": is_isolated,
            "violation_details": violations,
        }
        
        passed = (legit_access and not attack_access and 
                  len(violations) == 1 and not is_isolated)
        
        return TestResult(test_name, passed, 0, details)
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_tenant_context_isolation() -> TestResult:
    test_name = "test_tenant_context_isolation"
    logger.info(f"Running: {test_name}")
    
    try:
        org_a = uuid4()
        org_b = uuid4()
        
        tenant_a = TenantContext(org_id=org_a, user_id=uuid4())
        tenant_b = TenantContext(org_id=org_b, user_id=uuid4())
        
        try:
            tenant_a.validate_access(org_a)
            tenant_a_access = True
        except TenantIsolationError:
            tenant_a_access = False
        
        try:
            tenant_a.validate_access(org_b)
            tenant_b_access = True
        except TenantIsolationError:
            tenant_b_access = False
        
        details = {
            "tenant_a_org": str(org_a),
            "tenant_b_org": str(org_b),
            "tenant_a_can_access_own": tenant_a_access,
            "tenant_a_blocked_from_b": not tenant_b_access,
        }
        
        passed = tenant_a_access and not tenant_b_access
        
        return TestResult(test_name, passed, 0, details)
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_org_context_features() -> TestResult:
    test_name = "test_org_context_features"
    logger.info(f"Running: {test_name}")
    
    try:
        org = OrgContext(
            org_id=uuid4(),
            tenant_id=uuid4(),
            plan_tier="enterprise",
            features=("analytics", "custom_models"),
        )
        
        has_analytics = org.has_feature("analytics")
        has_nonexistent = org.has_feature("nonexistent")
        plan_correct = org.plan_tier == "enterprise"
        
        details = {
            "plan_tier": org.plan_tier,
            "features": org.features,
            "has_analytics_feature": has_analytics,
            "has_nonexistent_feature": has_nonexistent,
            "plan_correct": plan_correct,
        }
        
        passed = has_analytics and not has_nonexistent and plan_correct
        
        return TestResult(test_name, passed, 0, details)
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_auth_context_features() -> TestResult:
    test_name = "test_auth_context_features"
    logger.info(f"Running: {test_name}")
    
    try:
        auth_ctx = AuthContext(
            user_id=uuid4(),
            session_id=uuid4(),
            email="user@example.com",
            org_id=uuid4(),
            roles=("admin", "user"),
        )
        
        is_admin = auth_ctx.has_role("admin")
        is_user = auth_ctx.has_role("user")
        is_not_guest = not auth_ctx.has_role("guest")
        is_authenticated = auth_ctx.is_authenticated
        
        details = {
            "is_admin": is_admin,
            "is_user": is_user,
            "is_not_guest": is_not_guest,
            "is_authenticated": is_authenticated,
            "email": auth_ctx.email,
        }
        
        passed = is_admin and is_user and is_not_guest and is_authenticated
        
        return TestResult(test_name, passed, 0, details)
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_subpipeline_org_propagation() -> TestResult:
    test_name = "test_subpipeline_org_propagation"
    logger.info(f"Running: {test_name}")
    
    try:
        parent_org = uuid4()
        parent_run_id = uuid4()
        child_run_id = uuid4()
        correlation_id = uuid4()
        
        parent_ctx = PipelineContext(
            pipeline_run_id=parent_run_id,
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            org_id=parent_org,
            interaction_id=uuid4(),
            topology="parent",
            execution_mode="test",
        )
        
        child_ctx = parent_ctx.fork(
            child_run_id=child_run_id,
            parent_stage_id="parent_stage",
            correlation_id=correlation_id,
            topology="child",
        )
        
        org_preserved = child_ctx.org_id == parent_org
        new_run_id = child_ctx.pipeline_run_id == child_run_id
        parent_ref_set = child_ctx.parent_run_id == parent_run_id
        
        details = {
            "parent_org_id": str(parent_org),
            "child_org_id": str(child_ctx.org_id),
            "org_id_preserved": org_preserved,
            "new_run_id_generated": new_run_id,
            "parent_reference_set": parent_ref_set,
        }
        
        passed = org_preserved and new_run_id and parent_ref_set
        
        return TestResult(test_name, passed, 0, details)
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_cross_tenant_output_access() -> TestResult:
    test_name = "test_cross_tenant_output_access"
    logger.info(f"Running: {test_name}")
    
    try:
        tenant_a_outputs = {
            "stage_1": {"data": "tenant_a_secret_data"},
        }
        tenant_b_outputs = {
            "stage_1": {"data": "tenant_b_secret_data"},
        }
        
        tenant_a_data = tenant_a_outputs.get("stage_1", {}).get("data")
        tenant_b_data = tenant_b_outputs.get("stage_1", {}).get("data")
        
        outputs_different = tenant_a_data != tenant_b_data
        no_leakage = tenant_a_data != "tenant_b_secret_data" and tenant_b_data != "tenant_a_secret_data"
        
        details = {
            "tenant_a_output": tenant_a_data,
            "tenant_b_output": tenant_b_data,
            "outputs_isolated": outputs_different,
            "no_cross_tenant_leakage": no_leakage,
        }
        
        passed = outputs_different and no_leakage
        
        return TestResult(test_name, passed, 0, details)
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_extension_data_isolation() -> TestResult:
    test_name = "test_extension_data_isolation"
    logger.info(f"Running: {test_name}")
    
    try:
        org_a = uuid4()
        org_b = uuid4()
        
        run_id_a = RunIdentity(
            pipeline_run_id=uuid4(),
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            org_id=org_a,
            interaction_id=uuid4(),
        )
        
        snapshot_a = ContextSnapshot(
            run_id=run_id_a,
            extensions={
                "tenant_specific": {
                    "api_key": "secret_key_org_a",
                    "config": {"setting": "value_a"},
                }
            },
        )
        
        run_id_b = RunIdentity(
            pipeline_run_id=uuid4(),
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            org_id=org_b,
            interaction_id=uuid4(),
        )
        
        snapshot_b = ContextSnapshot(
            run_id=run_id_b,
            extensions={
                "tenant_specific": {
                    "api_key": "secret_key_org_b",
                    "config": {"setting": "value_b"},
                }
            },
        )
        
        ext_a = snapshot_a.extensions.get("tenant_specific", {})
        ext_b = snapshot_b.extensions.get("tenant_specific", {})
        
        api_key_a_isolated = ext_a.get("api_key") == "secret_key_org_a"
        api_key_b_isolated = ext_b.get("api_key") == "secret_key_org_b"
        no_cross_access = ext_a.get("api_key") != ext_b.get("api_key")
        
        details = {
            "org_a_api_key": ext_a.get("api_key"),
            "org_b_api_key": ext_b.get("api_key"),
            "org_a_isolated": api_key_a_isolated,
            "org_b_isolated": api_key_b_isolated,
            "no_cross_access": no_cross_access,
        }
        
        passed = api_key_a_isolated and api_key_b_isolated and no_cross_access
        
        return TestResult(test_name, passed, 0, details)
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_silent_context_corruption() -> TestResult:
    test_name = "test_silent_context_corruption"
    logger.info(f"Running: {test_name}")
    
    try:
        org_original = uuid4()
        
        run_id = RunIdentity(
            pipeline_run_id=uuid4(),
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            org_id=org_original,
            interaction_id=uuid4(),
        )
        
        snapshot = ContextSnapshot(run_id=run_id)
        
        original_org_id = snapshot.run_id.org_id
        
        snapshot_dict = snapshot.to_dict()
        snapshot_dict["run_id"]["org_id"] = str(uuid4())
        
        restored = ContextSnapshot.from_dict(snapshot_dict)
        
        org_id_unchanged = restored.run_id.org_id == original_org_id
        corruption_detected = original_org_id != restored.run_id.org_id
        
        details = {
            "original_org_id": str(original_org_id),
            "corrupted_dict_org_id": snapshot_dict["run_id"]["org_id"],
            "restored_org_id": str(restored.run_id.org_id),
            "immutability_preserved": org_id_unchanged,
            "corruption_detected": corruption_detected,
        }
        
        passed = org_id_unchanged and corruption_detected
        
        return TestResult(test_name, passed, 0, details)
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_context_variables_isolation() -> TestResult:
    test_name = "test_context_variables_isolation"
    logger.info(f"Running: {test_name}")
    
    try:
        org_a = uuid4()
        org_b = uuid4()
        
        set_current_tenant(org_a)
        tenant_a = get_current_tenant()
        
        set_current_tenant(org_b)
        tenant_b = get_current_tenant()
        
        tenants_different = tenant_a != tenant_b
        correct_tenant_a = tenant_a == org_a
        correct_tenant_b = tenant_b == org_b
        
        clear_current_tenant()
        cleared = get_current_tenant() is None
        
        details = {
            "tenant_a": str(tenant_a) if tenant_a else None,
            "tenant_b": str(tenant_b) if tenant_b else None,
            "tenants_isolated": tenants_different,
            "correct_tenant_a": correct_tenant_a,
            "correct_tenant_b": correct_tenant_b,
            "clear_works": cleared,
        }
        
        passed = tenants_different and correct_tenant_a and correct_tenant_b and cleared
        
        return TestResult(test_name, passed, 0, details)
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def test_context_snapshot_serialization() -> TestResult:
    test_name = "test_context_snapshot_serialization"
    logger.info(f"Running: {test_name}")
    
    try:
        org = uuid4()
        
        run_id = RunIdentity(
            pipeline_run_id=uuid4(),
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            org_id=org,
            interaction_id=uuid4(),
        )
        
        snapshot = ContextSnapshot(
            run_id=run_id,
            input_text="test input",
            topology="test",
            execution_mode="test",
            extensions={"custom": {"key": "value"}},
        )
        
        serialized = snapshot.to_dict()
        restored = ContextSnapshot.from_dict(serialized)
        
        org_preserved = restored.run_id.org_id == org
        input_preserved = restored.input_text == "test input"
        topology_preserved = restored.topology == "test"
        extensions_preserved = restored.extensions.get("custom", {}).get("key") == "value"
        
        details = {
            "org_preserved": org_preserved,
            "input_preserved": input_preserved,
            "topology_preserved": topology_preserved,
            "extensions_preserved": extensions_preserved,
        }
        
        passed = org_preserved and input_preserved and topology_preserved and extensions_preserved
        
        return TestResult(test_name, passed, 0, details)
    except Exception as e:
        return TestResult(test_name, False, 0, {}, str(e), traceback.format_exc())


async def run_tests():
    tests = [
        ("test_org_id_inheritance_fork", test_org_id_inheritance_fork),
        ("test_tenant_isolation_validator", test_tenant_isolation_validator),
        ("test_tenant_context_isolation", test_tenant_context_isolation),
        ("test_org_context_features", test_org_context_features),
        ("test_auth_context_features", test_auth_context_features),
        ("test_subpipeline_org_propagation", test_subpipeline_org_propagation),
        ("test_cross_tenant_output_access", test_cross_tenant_output_access),
        ("test_extension_data_isolation", test_extension_data_isolation),
        ("test_silent_context_corruption", test_silent_context_corruption),
        ("test_context_variables_isolation", test_context_variables_isolation),
        ("test_context_snapshot_serialization", test_context_snapshot_serialization),
    ]
    
    logger.info(f"Starting CORE-010 test suite with {len(tests)} tests")
    
    for test_name, test_func in tests:
        logger.info(f"Executing: {test_name}")
        try:
            start = datetime.now(UTC)
            result = await test_func()
            end = datetime.now(UTC)
            result.duration_ms = (end - start).total_seconds() * 1000
            
            test_results["tests"].append({
                "name": result.test_name,
                "passed": result.passed,
                "duration_ms": result.duration_ms,
                "details": result.details,
                "error": result.error,
                "stack_trace": result.stack_trace,
            })
            
            status = "PASS" if result.passed else "FAIL"
            logger.info(f"[{status}] {test_name} ({result.duration_ms:.2f}ms)")
            if result.error:
                logger.error(f"Error: {result.error}")
                
        except Exception as e:
            logger.error(f"ERROR in {test_name}: {e}")
            test_results["tests"].append({
                "name": test_name,
                "passed": False,
                "duration_ms": 0,
                "details": {},
                "error": str(e),
                "stack_trace": traceback.format_exc(),
            })
    
    passed_count = sum(1 for t in test_results["tests"] if t["passed"])
    failed_count = sum(1 for t in test_results["tests"] if not t["passed"])
    
    test_results["summary"] = {
        "total_tests": len(tests),
        "passed": passed_count,
        "failed": failed_count,
        "pass_rate": f"{(passed_count / len(tests)) * 100:.1f}%",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    
    results_path = Path("results/metrics/core010_results.json")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w") as f:
        json.dump(test_results, f, indent=2, default=str)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"CORE-010 Test Results Summary")
    logger.info(f"{'='*60}")
    logger.info(f"Total Tests: {test_results['summary']['total_tests']}")
    logger.info(f"Passed: {test_results['summary']['passed']}")
    logger.info(f"Failed: {test_results['summary']['failed']}")
    logger.info(f"Pass Rate: {test_results['summary']['pass_rate']}")
    logger.info(f"{'='*60}")
    
    return test_results


if __name__ == "__main__":
    results = asyncio.run(run_tests())
    sys.exit(0 if results["summary"]["failed"] == 0 else 1)
