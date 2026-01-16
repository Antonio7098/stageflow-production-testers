#!/usr/bin/env python3
"""Script for logging findings to structured JSON files.

Usage:
    python add_finding.py --file <type> --entry '<json_entry>' --agent <agent_model>

File type mappings:
    - strength: strengths.json (Positive aspects)
    - bug: bugs.json (Defects and incorrect behavior)
    - dx: dx.json (Developer experience issues)
    - improvement: improvements.json (Enhancement suggestions)

Examples:
    python add_finding.py --file bug --entry '{"title": "...", "description": "..."}' --agent claude-3.5-sonnet
    python add_finding.py --file improvement --entry '{"title": "...", "type": "stagekind_suggestion"}' --agent claude-3.5-sonnet
"""

import argparse
import json
import os
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

# Base directory for findings files
BASE_DIR = Path(__file__).parent

# File mappings
FILE_MAPPINGS = {
    "strength": "strengths.json",
    "bug": "bugs.json",
    "dx": "dx.json",
    "improvement": "improvements.json",
}

# ID prefixes
ID_PREFIXES = {
    "strength": "STR",
    "bug": "BUG",
    "dx": "DX",
    "improvement": "IMP",
}


def load_json_file(filepath: Path) -> dict[str, Any]:
    """Load a JSON file, returning empty template if it doesn't exist."""
    if filepath.exists():
        with open(filepath, "r") as f:
            return json.load(f)
    return {"template": {}, "entries": []}


def save_json_file(filepath: Path, data: dict[str, Any]) -> None:
    """Save data to a JSON file."""
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def generate_id(finding_type: str, entries: list[dict]) -> str:
    """Generate a unique ID for a new finding."""
    prefix = ID_PREFIXES.get(finding_type, "FIND")
    # Count existing entries with this prefix
    count = len([e for e in entries if e.get("id", "").startswith(prefix)])
    return f"{prefix}-{count + 1:03d}"


def add_finding(
    finding_type: str,
    entry_data: dict[str, Any],
    agent_model: str,
) -> dict[str, Any]:
    """Add a finding to the appropriate JSON file."""
    filepath = BASE_DIR / FILE_MAPPINGS[finding_type]
    data = load_json_file(filepath)

    # Generate ID
    entry_id = generate_id(finding_type, data.get("entries", []))

    # Add metadata
    entry = {
        "id": entry_id,
        "agent": agent_model,
        "created_at": datetime.now(UTC).isoformat(),
        **entry_data,
    }

    # Add to entries
    if "entries" not in data:
        data["entries"] = []
    data["entries"].append(entry)

    # Save
    save_json_file(filepath, data)

    return entry


def main():
    parser = argparse.ArgumentParser(
        description="Log findings to structured JSON files"
    )
    parser.add_argument(
        "--file",
        type=str,
        required=True,
        choices=["strength", "bug", "dx", "improvement"],
        help="Type of finding to log",
    )
    parser.add_argument(
        "--entry",
        type=str,
        required=True,
        help="JSON string containing the finding entry",
    )
    parser.add_argument(
        "--agent",
        type=str,
        required=True,
        help="Agent model that discovered the finding",
    )

    args = parser.parse_args()

    try:
        entry_data = json.loads(args.entry)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in entry: {e}", file=sys.stderr)
        sys.exit(1)

    entry = add_finding(args.file, entry_data, args.agent)

    print(f"Added finding: {entry['id']}")
    print(json.dumps(entry, indent=2))


if __name__ == "__main__":
    main()
