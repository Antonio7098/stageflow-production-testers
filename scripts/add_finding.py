#!/usr/bin/env python3
"""
Stageflow Findings Entry Script

Allows agents to add entries to structured JSON files without manual editing.
Agents run this script with a JSON entry and it inserts it with a unique ID.

Usage:
    python add_finding.py --file <type> --entry '<json_entry>' --agent <agent_model>

Examples:
    python add_finding.py --file bug --entry '{"title": "Memory leak", "severity": "high"}' --agent claude-3.5-sonnet
    python add_finding.py --file dx --entry '{"title": "Confusing error messages", "category": "error_messages"}' --agent claude-3.5-sonnet
    python add_finding.py --file improvement --entry '{"title": "Retry stage", "type": "component_suggestion"}' --agent claude-3.5-sonnet
    python add_finding.py --file strength --entry '{"title": "Clean API", "component": "Stage"}' --agent claude-3.5-sonnet
"""

import json
import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent

FILE_MAP = {
    "strength": "strengths.json",
    "bug": "bugs.json",
    "dx": "dx.json",
    "improvement": "improvements.json",
}

ID_PREFIXES = {
    "strength": "STR",
    "bug": "BUG",
    "dx": "DX",
    "improvement": "IMP",
}


def generate_id(entry_type: str, existing_ids: list[str]) -> str:
    prefix = ID_PREFIXES.get(entry_type, "ENT")
    max_num = 0
    for eid in existing_ids:
        if eid.startswith(prefix + "-"):
            try:
                num = int(eid.split("-")[1])
                if num > max_num:
                    max_num = num
            except (ValueError, IndexError):
                pass
    new_num = max_num + 1
    return f"{prefix}-{new_num:03d}"


def load_json_file(filepath: Path) -> dict:
    if filepath.exists():
        with open(filepath, "r") as f:
            return json.load(f)
    return {"template": {}, "entries": []}


def save_json_file(filepath: Path, data: dict) -> None:
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def add_entry(
    file_type: str, entry_json: str, agent: str, title: str | None = None
) -> dict:
    filepath = BASE_DIR / FILE_MAP[file_type]
    data = load_json_file(filepath)

    entry = json.loads(entry_json)
    existing_ids = [e.get("id", "") for e in data.get("entries", [])]

    entry_id = generate_id(file_type, existing_ids)

    entry["id"] = entry_id
    entry["agent"] = agent
    entry["created_at"] = datetime.utcnow().isoformat() + "Z"

    if title and "title" not in entry:
        entry["title"] = title

    if "entries" not in data:
        data["entries"] = []

    data["entries"].append(entry)

    save_json_file(filepath, data)

    return {"id": entry_id, "status": "success", "file": FILE_MAP[file_type]}


def main():
    parser = argparse.ArgumentParser(
        description="Add entries to Stageflow JSON finding files"
    )
    parser.add_argument(
        "--file",
        "-f",
        required=True,
        choices=["strength", "bug", "dx", "improvement"],
        help="Type of entry to add",
    )
    parser.add_argument(
        "--entry",
        "-e",
        required=True,
        help="JSON string of the entry to add",
    )
    parser.add_argument(
        "--agent",
        "-a",
        required=True,
        help="Agent model identifier",
    )
    parser.add_argument(
        "--title",
        "-t",
        help="Title for the entry (optional, uses existing title if not provided)",
    )

    args = parser.parse_args()

    try:
        result = add_entry(args.file, args.entry, args.agent, args.title)
        print(json.dumps(result, indent=2))
        print(f"\nEntry {result['id']} added to {result['file']}")
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON entry: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
