# Stageflow Stress-Testing Reporting Schema

> **Purpose**: Defines the JSON schema for all findings reported by stress-testing agents.

---

## File: `findings.json`

Each agent run produces a `findings.json` file containing all discovered issues, improvements, and observations.

---

## Schema Definition

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "StageflowFindings",
  "type": "object",
  "required": ["metadata", "findings"],
  "properties": {
    "metadata": {
      "type": "object",
      "required": ["roadmap_entry_id", "agent_run_id", "started_at", "completed_at", "status"],
      "properties": {
        "roadmap_entry_id": {
          "type": "string",
          "description": "ID from the roadmap (e.g., 'FIN-001')"
        },
        "roadmap_entry_title": {
          "type": "string",
          "description": "Human-readable title of the roadmap entry"
        },
        "agent_run_id": {
          "type": "string",
          "description": "Unique identifier for this agent run (UUID)"
        },
        "started_at": {
          "type": "string",
          "format": "date-time",
          "description": "ISO 8601 timestamp when the run started"
        },
        "completed_at": {
          "type": "string",
          "format": "date-time",
          "description": "ISO 8601 timestamp when the run completed"
        },
        "status": {
          "type": "string",
          "enum": ["in_progress", "completed", "failed", "blocked"],
          "description": "Current status of the agent run"
        },
        "stageflow_version": {
          "type": "string",
          "description": "Version of Stageflow being tested"
        },
        "agent_model": {
          "type": "string",
          "description": "LLM model used by the agent"
        },
        "total_findings": {
          "type": "integer",
          "description": "Total number of findings"
        },
        "summary": {
          "type": "string",
          "description": "Brief summary of the run results"
        }
      }
    },
    "findings": {
      "type": "array",
      "items": {
        "$ref": "#/definitions/Finding"
      }
    }
  },
  "definitions": {
    "Finding": {
      "type": "object",
      "required": ["id", "type", "severity", "title", "description", "status", "created_at"],
      "properties": {
        "id": {
          "type": "string",
          "description": "Unique finding ID (e.g., 'FIN-001-BUG-001')"
        },
        "type": {
          "type": "string",
          "enum": ["bug", "security", "performance", "reliability", "dx", "improvement", "documentation", "feature_request"],
          "description": "Category of the finding"
        },
        "severity": {
          "type": "string",
          "enum": ["critical", "high", "medium", "low", "info"],
          "description": "Impact severity"
        },
        "title": {
          "type": "string",
          "description": "Short, descriptive title"
        },
        "description": {
          "type": "string",
          "description": "Detailed description of the finding"
        },
        "status": {
          "type": "string",
          "enum": ["open", "confirmed", "in_progress", "resolved", "wont_fix", "duplicate"],
          "description": "Current status of the finding"
        },
        "created_at": {
          "type": "string",
          "format": "date-time",
          "description": "When the finding was discovered"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time",
          "description": "When the finding was last updated"
        },
        "resolved_at": {
          "type": "string",
          "format": "date-time",
          "description": "When the finding was resolved"
        },
        "component": {
          "type": "string",
          "description": "Stageflow component affected (e.g., 'ContextBag', 'StageGraph', 'GUARD')"
        },
        "tags": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Searchable tags"
        },
        "reproduction": {
          "$ref": "#/definitions/Reproduction"
        },
        "impact": {
          "$ref": "#/definitions/Impact"
        },
        "recommendation": {
          "$ref": "#/definitions/Recommendation"
        },
        "resolution": {
          "$ref": "#/definitions/Resolution"
        },
        "related_findings": {
          "type": "array",
          "items": { "type": "string" },
          "description": "IDs of related findings"
        },
        "attachments": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": { "type": "string" },
              "path": { "type": "string" },
              "type": { "type": "string" }
            }
          },
          "description": "Related files (logs, screenshots, code)"
        }
      }
    },
    "Reproduction": {
      "type": "object",
      "properties": {
        "steps": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Step-by-step reproduction instructions"
        },
        "code_snippet": {
          "type": "string",
          "description": "Minimal code to reproduce"
        },
        "environment": {
          "type": "object",
          "properties": {
            "python_version": { "type": "string" },
            "os": { "type": "string" },
            "dependencies": {
              "type": "object",
              "additionalProperties": { "type": "string" }
            }
          }
        },
        "frequency": {
          "type": "string",
          "enum": ["always", "often", "sometimes", "rarely"],
          "description": "How often the issue occurs"
        },
        "conditions": {
          "type": "string",
          "description": "Specific conditions required to trigger"
        }
      }
    },
    "Impact": {
      "type": "object",
      "properties": {
        "affected_users": {
          "type": "string",
          "description": "Who is affected (e.g., 'All users', 'Healthcare vertical')"
        },
        "data_risk": {
          "type": "string",
          "enum": ["none", "low", "medium", "high", "critical"],
          "description": "Risk of data loss or corruption"
        },
        "security_risk": {
          "type": "string",
          "enum": ["none", "low", "medium", "high", "critical"],
          "description": "Security vulnerability risk"
        },
        "availability_risk": {
          "type": "string",
          "enum": ["none", "low", "medium", "high", "critical"],
          "description": "Risk of service disruption"
        },
        "business_impact": {
          "type": "string",
          "description": "Business consequences if not addressed"
        },
        "workaround_available": {
          "type": "boolean",
          "description": "Is there a workaround?"
        },
        "workaround_description": {
          "type": "string",
          "description": "Description of the workaround"
        }
      }
    },
    "Recommendation": {
      "type": "object",
      "properties": {
        "summary": {
          "type": "string",
          "description": "Brief recommendation"
        },
        "detailed_proposal": {
          "type": "string",
          "description": "Detailed fix proposal"
        },
        "code_suggestion": {
          "type": "string",
          "description": "Suggested code changes"
        },
        "estimated_effort": {
          "type": "string",
          "enum": ["trivial", "small", "medium", "large", "epic"],
          "description": "Estimated implementation effort"
        },
        "breaking_change": {
          "type": "boolean",
          "description": "Would this require a breaking change?"
        },
        "alternatives": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Alternative approaches considered"
        }
      }
    },
    "Resolution": {
      "type": "object",
      "properties": {
        "resolved_by": {
          "type": "string",
          "description": "Who resolved the issue"
        },
        "resolution_type": {
          "type": "string",
          "enum": ["fixed", "wont_fix", "duplicate", "by_design", "cannot_reproduce"],
          "description": "How it was resolved"
        },
        "resolution_details": {
          "type": "string",
          "description": "Details of the resolution"
        },
        "commit_hash": {
          "type": "string",
          "description": "Git commit that fixed the issue"
        },
        "pr_link": {
          "type": "string",
          "description": "Link to the pull request"
        },
        "release_version": {
          "type": "string",
          "description": "Version where fix was released"
        },
        "verification_steps": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Steps to verify the fix"
        }
      }
    }
  }
}
```

---

## Example `findings.json`

```json
{
  "metadata": {
    "roadmap_entry_id": "FIN-001",
    "roadmap_entry_title": "High-frequency fraud detection (5000 TPS)",
    "agent_run_id": "550e8400-e29b-41d4-a716-446655440000",
    "started_at": "2026-01-14T09:00:00Z",
    "completed_at": "2026-01-14T15:30:00Z",
    "status": "completed",
    "stageflow_version": "0.5.0",
    "agent_model": "claude-3.5-sonnet",
    "total_findings": 3,
    "summary": "Discovered 1 critical race condition, 1 performance bottleneck, and 1 DX improvement opportunity."
  },
  "findings": [
    {
      "id": "FIN-001-BUG-001",
      "type": "bug",
      "severity": "critical",
      "title": "OutputBag race condition under high fan-out",
      "description": "When 50+ parallel ENRICH stages complete within a 2ms window, the OutputBag merge logic drops keys silently. The final ContextSnapshot contains only a subset of the expected keys despite all stages reporting success.",
      "status": "open",
      "created_at": "2026-01-14T11:23:00Z",
      "component": "ContextBag",
      "tags": ["race-condition", "concurrency", "data-loss", "critical"],
      "reproduction": {
        "steps": [
          "Create a pipeline with a root node spawning 50 parallel ENRICH stages",
          "Each stage writes a unique key to the OutputBag",
          "Execute with high concurrency (>100 concurrent pipelines)",
          "Observe that final snapshot contains fewer keys than expected"
        ],
        "code_snippet": "# See pipelines/race_condition_repro.py",
        "environment": {
          "python_version": "3.11",
          "os": "Linux",
          "dependencies": {
            "stageflow": "0.5.0",
            "pydantic": "2.5.0"
          }
        },
        "frequency": "often",
        "conditions": ">5 stages completing within 2ms window"
      },
      "impact": {
        "affected_users": "All users with parallel fan-out patterns",
        "data_risk": "critical",
        "security_risk": "medium",
        "availability_risk": "high",
        "business_impact": "Silent data loss in production pipelines. In finance, this could mean missing fraud signals.",
        "workaround_available": true,
        "workaround_description": "Serialize stage execution or implement application-level locking"
      },
      "recommendation": {
        "summary": "Implement atomic CAS operations for OutputBag merges",
        "detailed_proposal": "Replace the current merge logic with an optimistic concurrency control pattern using fencing tokens. Each parallel stage should acquire a version token before reading, and the write should fail if the version has changed.",
        "code_suggestion": "# See recommendation in FINAL_REPORT.md",
        "estimated_effort": "medium",
        "breaking_change": false,
        "alternatives": [
          "Use pessimistic locking (higher overhead)",
          "Require explicit merge strategies from users"
        ]
      },
      "resolution": null,
      "related_findings": ["CORE-001-BUG-001"],
      "attachments": [
        {
          "name": "race_condition_repro.py",
          "path": "pipelines/race_condition_repro.py",
          "type": "code"
        },
        {
          "name": "execution_trace.json",
          "path": "results/trace_001.json",
          "type": "trace"
        }
      ]
    },
    {
      "id": "FIN-001-PERF-001",
      "type": "performance",
      "severity": "high",
      "title": "ContextSnapshot serialization bottleneck at >50MB",
      "description": "Serialization latency grows non-linearly when ContextSnapshot exceeds 50MB, causing p99 latency to spike from 50ms to 800ms.",
      "status": "open",
      "created_at": "2026-01-14T13:45:00Z",
      "component": "ContextSnapshot",
      "tags": ["performance", "serialization", "latency"],
      "reproduction": {
        "steps": [
          "Create a pipeline that accumulates >50MB in ContextSnapshot",
          "Measure serialization latency at each stage",
          "Observe non-linear growth pattern"
        ],
        "frequency": "always",
        "conditions": "ContextSnapshot > 50MB"
      },
      "impact": {
        "affected_users": "Users with large context payloads",
        "data_risk": "none",
        "security_risk": "none",
        "availability_risk": "medium",
        "business_impact": "SLA violations in latency-sensitive applications",
        "workaround_available": true,
        "workaround_description": "Implement context pruning or use external storage for large payloads"
      },
      "recommendation": {
        "summary": "Implement delta compression for large snapshots",
        "estimated_effort": "large",
        "breaking_change": false
      }
    },
    {
      "id": "FIN-001-DX-001",
      "type": "dx",
      "severity": "medium",
      "title": "Error messages don't indicate which parallel stage failed",
      "description": "When a stage fails in a parallel fan-out, the error message only shows the parent stage ID, not which specific child stage caused the failure. This makes debugging difficult.",
      "status": "open",
      "created_at": "2026-01-14T14:20:00Z",
      "component": "StageGraph",
      "tags": ["dx", "error-handling", "debugging"],
      "impact": {
        "affected_users": "All developers",
        "data_risk": "none",
        "security_risk": "none",
        "availability_risk": "none",
        "business_impact": "Increased debugging time, developer frustration",
        "workaround_available": true,
        "workaround_description": "Add manual logging in each stage"
      },
      "recommendation": {
        "summary": "Include child stage ID and index in error messages",
        "estimated_effort": "small",
        "breaking_change": false
      }
    }
  ]
}
```

---

## Aggregated Reports

For cross-run analysis, findings can be aggregated into:

### `aggregated_findings.json`

```json
{
  "generated_at": "2026-01-14T16:00:00Z",
  "total_runs": 15,
  "total_findings": 47,
  "by_type": {
    "bug": 12,
    "security": 3,
    "performance": 8,
    "reliability": 5,
    "dx": 10,
    "improvement": 6,
    "documentation": 2,
    "feature_request": 1
  },
  "by_severity": {
    "critical": 2,
    "high": 8,
    "medium": 20,
    "low": 12,
    "info": 5
  },
  "by_status": {
    "open": 35,
    "confirmed": 5,
    "in_progress": 3,
    "resolved": 4
  },
  "by_component": {
    "ContextBag": 8,
    "StageGraph": 12,
    "GUARD": 5,
    "AGENT": 7,
    "WORK": 6,
    "ENRICH": 5,
    "Other": 4
  },
  "findings": [
    "... all findings from all runs ..."
  ]
}
```

---

## CLI Commands (Future)

```bash
# View all open critical findings
stageflow-test findings list --status=open --severity=critical

# Mark a finding as resolved
stageflow-test findings resolve FIN-001-BUG-001 \
  --type=fixed \
  --commit=abc123 \
  --details="Implemented CAS in OutputBag"

# Generate aggregated report
stageflow-test findings aggregate --output=aggregated_findings.json

# Export to CSV for external tracking
stageflow-test findings export --format=csv --output=findings.csv
```
