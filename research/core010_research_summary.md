# CORE-010: Cross-Tenant Context Isolation - Research Summary

## Mission Parameters

| Field | Value |
|-------|-------|
| **ROADMAP_ENTRY_ID** | CORE-010 |
| **TITLE** | Cross-tenant context isolation |
| **PRIORITY** | P0 |
| **RISK_CLASS** | Catastrophic |
| **INDUSTRY_VERTICAL** | 1.1 Context & State Management |
| **DEPLOYMENT_MODE** | N/A |

---

## 1. Industry Context

### 1.1 Cross-Tenant Data Leakage Risks

Multi-tenant SaaS applications face catastrophic security risks when tenant isolation fails. Key findings from industry research:

- **Row-Level Security (RLS) Failures**: Many systems rely on `tenant_id` column filtering, but bugs or misconfigurations can expose data between tenants
- **Cache Poisoning**: Shared caches can serve stale data from one tenant to another
- **Context Confusion**: When pipelines lose track of tenant context for even a split second, cross-tenant data access can occur
- **Real-World Incidents**: The Salesloft Drift breach (Sept 2025) affected 700+ organizations through supply chain attacks exploiting tenant isolation gaps

### 1.2 LLM-Specific Context Isolation Challenges

New attack vectors emerge in AI/LLM systems:

- **KV-Cache Side Channels**: Research shows "I Know What You Asked" - multi-tenant LLM serving via KV cache sharing can leak prompts through cache reconstruction attacks
- **Prompt Injection**: EchoLeak (CVE-2025-32711) demonstrated zero-click prompt injection in Microsoft 365 Copilot, enabling data exfiltration
- **Multi-Agent Prompt Infection**: Research shows LLM-to-LLM prompt injection within multi-agent systems can propagate malicious context across tenant boundaries
- **Context Boundary Degradation**: Performance degrades near context window edges, potentially causing LLM to leak previous tenant's data

### 1.3 Regulatory Requirements

- **HIPAA**: Healthcare tenant data must be strictly isolated; violations cost $50K-$1.5M per incident
- **GDPR**: Right-to-erasure requires complete tenant data purging across distributed systems
- **PCI-DSS**: Payment data requires strict tenant isolation in shared environments

---

## 2. Technical Context

### 2.1 Stageflow's Multi-Tenant Architecture

Stageflow provides several mechanisms for tenant isolation:

| Component | Purpose |
|-----------|---------|
| `PipelineContext.org_id` | Tenant identifier for the pipeline run |
| `TenantContext` | Validates tenant access to resources |
| `TenantIsolationValidator` | Tracks and validates isolation across execution |
| `OrgEnforcementInterceptor` | Interceptor that blocks cross-tenant access |
| `AuthInterceptor` | Validates JWT tokens and creates AuthContext |
| `TenantContext.from_snapshot()` | Creates TenantContext from ContextSnapshot |

### 2.2 Critical Context Fields

The following fields are critical for tenant isolation:

```python
# From ContextSnapshot
pipeline_run_id: UUID  # Unique per pipeline run
request_id: UUID       # HTTP/WebSocket request
session_id: UUID       # User session
user_id: UUID          # User identifier
org_id: UUID           # ORGANIZATION/TENANT identifier
interaction_id: UUID   # Specific interaction

# From PipelineContext (shared mutable data)
data: dict             # Shared state across stages
```

### 2.3 Potential Failure Modes

| Failure Mode | Mechanism | Risk Level |
|--------------|-----------|------------|
| Context leak during fork() | Child context inherits parent's data without tenant validation | Critical |
| org_id overwriting | Malicious actor manipulates org_id in shared data dict | Critical |
| Subpipeline tenant bypass | Child pipeline runs without org_id validation | Critical |
| Cache contamination | Shared state polluted by cross-tenant data | High |
| Extension data leakage | Extensions contain tenant-specific data accessed incorrectly | High |
| OutputBag cross-tenant read | Reading outputs from another tenant's stages | Critical |
| Auth context spoofing | Forging auth context to access other tenants | Critical |

---

## 3. Hypotheses to Test

### H1: org_id Inheritance in Forked Contexts
**Hypothesis**: When `PipelineContext.fork()` is called, child contexts correctly inherit org_id without modification.

### H2: Tenant Isolation Validator Detection
**Hypothesis**: `TenantIsolationValidator` correctly detects cross-tenant access attempts.

### H3: OrgEnforcement Interceptor Efficacy
**Hypothesis**: `OrgEnforcementInterceptor` blocks unauthorized cross-tenant resource access.

### H4: Subpipeline org_id Propagation
**Hypothesis**: Subpipelines correctly propagate or reset org_id based on configuration.

### H5: Cross-Tenant Output Access Prevention
**Hypothesis**: `StageInputs` prevents accessing outputs from another tenant's stages.

### H6: Extension Data Isolation
**Hypothesis**: Extensions containing tenant-specific data are properly isolated.

### H7: Silent Context Corruption
**Hypothesis**: No silent failures occur where tenant context is corrupted without raising errors.

### H8: Auth Context Impersonation Resistance
**Hypothesis**: Auth context cannot be spoofed to impersonate another tenant.

---

## 4. Success Criteria

| Criterion | Metric | Target |
|-----------|--------|--------|
| Tenant Isolation | Cross-tenant data access attempts blocked | 100% blocked |
| Context Integrity | org_id preserved across pipeline execution | 100% preserved |
| Subpipeline Isolation | Child pipelines correctly inherit or reset tenant context | 100% correct |
| Silent Failure Detection | Silent context corruption discovered | 0 silent failures |
| Error Handling | Cross-tenant attempts raise appropriate errors | 100% raises |
| Performance Overhead | Tenant isolation adds <5ms to pipeline execution | <5ms |

---

## 5. Test Data Generation

### 5.1 Multi-Tenant Scenarios

| Tenant | Description | Test Focus |
|--------|-------------|------------|
| Org-A | Large enterprise (1000+ users) | High-volume isolation |
| Org-B | Small business (10 users) | Minimal data isolation |
| Org-C | Healthcare tenant (HIPAA) | Strict compliance |
| Org-D | Financial services (PCI) | Audit requirements |

### 5.2 Adversarial Inputs

- Manipulated org_id in context.data
- Cross-tenant resource IDs in API calls
- Prompt injection attempts through input_text
- Malicious extensions containing cross-tenant data
- JWT token manipulation attempts

---

## 6. Environment Simulation

### 6.1 Mock Components Required

1. **MultiTenantStore**: Simulates database with tenant isolation
2. **MockAuthProvider**: Creates JWT tokens for different tenants
3. **TenantIsolationValidator**: Validates isolation during execution
4. **CrossTenant_attack_generator**: Generates adversarial test cases

### 6.2 Pipeline Configurations

1. **Baseline Pipeline**: Single tenant, normal operation
2. **Multi-Tenant Pipeline**: Multiple tenants in same process
3. **Nested Pipeline**: Parent-child pipeline with different tenants
4. **Adversarial Pipeline**: Intentional cross-tenant attack attempts

---

## 7. Research Citations

1. AWS SaaS Tenant Isolation Strategies (2020) - Foundational patterns
2. OWASP Multi-Tenant Security Cheat Sheet - Industry best practices
3. "EchoLeak: Zero-Click Prompt Injection" (2025) - LLM attack vectors
4. "I Know What You Asked: KV-Cache Leakage" (NDSS 2025) - Multi-tenant LLM risks
5. Salesloft Drift Breach Analysis (Sept 2025) - Real-world incident
6. Alien Giraffe: "The Five Tests Your Multi-Tenant System Is Probably Failing" (2025)
7. Stageflow Documentation - Framework-specific patterns

---

## 8. Next Steps

1. Create research directory structure
2. Build mock data generation utilities
3. Implement test pipelines for each hypothesis
4. Execute tests with comprehensive logging
5. Analyze results and document findings
6. Generate final report with recommendations

---

*Research completed: 2026-01-19*
*Agent: claude-3.5-sonnet*
