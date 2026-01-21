"""
Log Analysis System for WORK-006 Error Classification Tests

This module provides utilities for capturing, analyzing, and reporting
on logs from error classification test runs.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import Counter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class LogEntry:
    """Represents a single log entry."""
    timestamp: datetime
    level: str
    logger: str
    message: str
    raw_line: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "logger": self.logger,
            "message": self.message,
        }


@dataclass
class LogAnalysis:
    """Results of log analysis."""
    log_file: Path
    analysis_time: datetime
    total_entries: int = 0
    entries_by_level: Dict[str, int] = field(default_factory=dict)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    patterns: Dict[str, int] = field(default_factory=dict)
    findings: List[Dict[str, Any]] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "log_file": str(self.log_file),
            "analysis_time": self.analysis_time.isoformat(),
            "total_entries": self.total_entries,
            "entries_by_level": self.entries_by_level,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "patterns": self.patterns,
            "findings": self.findings,
        }


class LogParser:
    """Parses log files into structured entries."""
    
    LOG_PATTERN = re.compile(
        r'(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,\.]\d+)\s+-\s+'
        r'(?P<logger>[^\s]+)\s+-\s+'
        r'(?P<level>[^\s]+)\s+-\s+'
        r'(?P<message>.+)'
    )
    
    @classmethod
    def parse_line(cls, line: str) -> Optional[LogEntry]:
        """Parse a single log line."""
        match = cls.LOG_PATTERN.match(line.strip())
        if not match:
            return None
        
        timestamp_str = match.group("timestamp").replace(",", ".")
        try:
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
        
        return LogEntry(
            timestamp=timestamp,
            level=match.group("level"),
            logger=match.group("logger"),
            message=match.group("message"),
            raw_line=line,
        )
    
    @classmethod
    def parse_file(cls, log_file: Path) -> List[LogEntry]:
        """Parse all lines in a log file."""
        entries = []
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = cls.parse_line(line)
                if entry:
                    entries.append(entry)
        return entries


class LogAnalyzer:
    """Analyzes log entries for patterns and findings."""
    
    ERROR_PATTERNS = [
        (r"failed|error|exception", "error_keywords"),
        (r"timeout", "timeout_errors"),
        (r"retry", "retry_activity"),
        (r"rate limit", "rate_limiting"),
        (r"classif", "classification"),
        (r"silent", "silent_failures"),
        (r"cost", "cost_impact"),
    ]
    
    def __init__(self, entries: List[LogEntry]):
        self.entries = entries
    
    def analyze(self, log_file: Path) -> LogAnalysis:
        """Run complete log analysis."""
        analysis = LogAnalysis(log_file=log_file, analysis_time=datetime.now())
        
        # Count entries by level
        for entry in self.entries:
            analysis.entries_by_level[entry.level] = (
                analysis.entries_by_level.get(entry.level, 0) + 1
            )
            
            if entry.level == "ERROR":
                analysis.errors.append(entry.to_dict())
            elif entry.level == "WARNING":
                analysis.warnings.append(entry.to_dict())
        
        # Extract patterns
        for entry in self.entries:
            for pattern, name in self.ERROR_PATTERNS:
                if re.search(pattern, entry.message, re.IGNORECASE):
                    analysis.patterns[name] = analysis.patterns.get(name, 0) + 1
        
        analysis.total_entries = len(self.entries)
        
        # Generate findings
        analysis.findings = self._generate_findings(analysis)
        
        return analysis
    
    def _generate_findings(self, analysis: LogAnalysis) -> List[Dict[str, Any]]:
        """Generate findings from analysis."""
        findings = []
        
        # High error rate
        error_rate = analysis.entries_by_level.get("ERROR", 0) / max(1, analysis.total_entries)
        if error_rate > 0.1:
            findings.append({
                "type": "high_error_rate",
                "severity": "high",
                "description": f"Error rate ({error_rate*100:.1f}%) exceeds 10% threshold",
                "count": analysis.entries_by_level.get("ERROR", 0),
            })
        
        # Retry patterns
        retry_count = analysis.patterns.get("retry_activity", 0)
        if retry_count > 10:
            findings.append({
                "type": "high_retry_activity",
                "severity": "medium",
                "description": f"High retry activity detected ({retry_count} occurrences)",
                "recommendation": "Review retry logic for potential infinite loops or excessive retries",
            })
        
        # Classification issues
        class_count = analysis.patterns.get("classification", 0)
        if class_count > 0:
            findings.append({
                "type": "classification_activity",
                "severity": "info",
                "description": f"Classification-related logs found ({class_count} occurrences)",
            })
        
        # Silent failures
        silent_count = analysis.patterns.get("silent_failures", 0)
        if silent_count > 0:
            findings.append({
                "type": "silent_failures",
                "severity": "high",
                "description": f"Silent failure indicators found ({silent_count} occurrences)",
                "recommendation": "Investigate potential silent failures in error handling",
            })
        
        # Cost impact
        cost_count = analysis.patterns.get("cost_impact", 0)
        if cost_count > 0:
            findings.append({
                "type": "cost_impact",
                "severity": "medium",
                "description": f"Cost-related logs found ({cost_count} occurrences)",
                "recommendation": "Review for unnecessary retries consuming budget",
            })
        
        return findings


def capture_test_logs(test_output: str, log_file: Path) -> None:
    """Capture test output to log file."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "w") as f:
        f.write(test_output)
    logger.info(f"Logs captured to: {log_file}")


def analyze_logs(log_file: Path) -> LogAnalysis:
    """Analyze logs from a file."""
    entries = LogParser.parse_file(log_file)
    analyzer = LogAnalyzer(entries)
    return analyzer.analyze(log_file)


def generate_log_report(analysis: LogAnalysis) -> str:
    """Generate a human-readable report from log analysis."""
    lines = [
        "=" * 80,
        "LOG ANALYSIS REPORT",
        "=" * 80,
        f"Log file: {analysis.log_file}",
        f"Analysis time: {analysis.analysis_time.isoformat()}",
        "",
        "SUMMARY",
        "-" * 40,
        f"Total entries: {analysis.total_entries}",
        f"ERROR: {analysis.entries_by_level.get('ERROR', 0)}",
        f"WARNING: {analysis.entries_by_level.get('WARNING', 0)}",
        f"INFO: {analysis.entries_by_level.get('INFO', 0)}",
        "",
        "PATTERNS DETECTED",
        "-" * 40,
    ]
    
    for pattern, count in sorted(analysis.patterns.items(), key=lambda x: -x[1]):
        lines.append(f"  {pattern}: {count}")
    
    lines.extend([
        "",
        "FINDINGS",
        "-" * 40,
    ])
    
    for finding in analysis.findings:
        lines.append(f"[{finding['severity'].upper()}] {finding['description']}")
    
    lines.extend([
        "",
        "=" * 80,
    ])
    
    return "\n".join(lines)


def main():
    """Main entry point for log analysis."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze error classification logs")
    parser.add_argument("log_file", type=Path, help="Path to log file")
    parser.add_argument("--output", type=Path, help="Output path for analysis JSON")
    parser.add_argument("--report", action="store_true", help="Generate human-readable report")
    
    args = parser.parse_args()
    
    if not args.log_file.exists():
        logger.error(f"Log file not found: {args.log_file}")
        return
    
    analysis = analyze_logs(args.log_file)
    
    # Save JSON analysis
    if args.output:
        with open(args.output, "w") as f:
            json.dump(analysis.to_dict(), f, indent=2, default=str)
        logger.info(f"Analysis saved to: {args.output}")
    
    # Print report
    if args.report:
        report = generate_log_report(analysis)
        print("\n" + report)
    
    # Print summary
    print(f"\nLog Analysis Complete:")
    print(f"  Total entries: {analysis.total_entries}")
    print(f"  Errors: {analysis.entries_by_level.get('ERROR', 0)}")
    print(f"  Findings: {len(analysis.findings)}")


if __name__ == "__main__":
    main()
