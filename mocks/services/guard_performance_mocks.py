"""
GUARD-008 Performance Mock Services

Mock implementations of guard services with configurable latency
for performance testing of Stageflow GUARD stages.
"""

import asyncio
import time
import random
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum


class GuardType(Enum):
    INPUT_VALIDATION = "input_validation"
    PII_DETECTION = "pii_detection"
    INJECTION_DETECTION = "injection_detection"
    CONTENT_FILTER = "content_filter"
    OUTPUT_VALIDATION = "output_validation"


@dataclass
class GuardConfig:
    """Configuration for mock guard service behavior."""
    base_latency_ms: float = 5.0
    latency_variance_ms: float = 2.0
    error_rate: float = 0.0
    timeout_rate: float = 0.0
    cache_hit_rate: float = 0.0
    detection_rate: float = 0.02
    block_on_detection: bool = True


@dataclass
class GuardResult:
    """Result of a guard check."""
    passed: bool
    blocked: bool = False
    violations: List[Dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    from_cache: bool = False
    error: Optional[str] = None


class MockGuardService:
    """
    Mock guard service with configurable latency and behavior.
    
    Simulates real-world guard services like:
    - Llama Guard for content moderation
    - PII detection services
    - Injection detection systems
    """

    def __init__(self, config: Optional[GuardConfig] = None):
        self._config = config or GuardConfig()
        self._cache: Dict[str, GuardResult] = {}
        self._stats = {
            "checks": 0,
            "blocked": 0,
            "passed": 0,
            "errors": 0,
            "timeouts": 0,
            "cache_hits": 0,
            "total_latency_ms": 0.0,
        }

    def reset_stats(self):
        """Reset statistics counters."""
        self._stats = {
            "checks": 0,
            "blocked": 0,
            "passed": 0,
            "errors": 0,
            "timeouts": 0,
            "cache_hits": 0,
            "total_latency_ms": 0.0,
        }
        self._cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        total = self._stats["checks"]
        return {
            **self._stats,
            "avg_latency_ms": (
                self._stats["total_latency_ms"] / total 
                if total > 0 else 0
            ),
            "cache_size": len(self._cache),
        }

    async def check_input(
        self, 
        content: str, 
        guard_type: GuardType = GuardType.INPUT_VALIDATION,
        context: Optional[Dict[str, Any]] = None
    ) -> GuardResult:
        """
        Check input content for policy violations.
        
        Args:
            content: Text content to check
            guard_type: Type of guard check to perform
            context: Optional context (user_id, etc.)
            
        Returns:
            GuardResult with pass/fail status and details
        """
        self._stats["checks"] += 1
        
        # Check cache first
        cache_key = f"{guard_type.value}:{hash(content)}"
        if cache_key in self._cache and random.random() < self._config.cache_hit_rate:
            self._stats["cache_hits"] += 1
            self._stats["passed"] += 1
            return self._cache[cache_key]

        # Simulate latency
        await self._simulate_latency()

        # Check for errors
        if random.random() < self._config.error_rate:
            self._stats["errors"] += 1
            return GuardResult(
                passed=False,
                error="Service temporarily unavailable",
                latency_ms=self._get_latency(),
            )

        # Check for timeouts
        if random.random() < self._config.timeout_rate:
            self._stats["timeouts"] += 1
            return GuardResult(
                passed=False,
                error="Request timeout",
                latency_ms=self._get_latency(),
            )

        # Perform actual check (simulated)
        violations = self._perform_check(content, guard_type)
        blocked = len(violations) > 0 and self._config.block_on_detection
        passed = not blocked

        result = GuardResult(
            passed=passed,
            blocked=blocked,
            violations=violations,
            latency_ms=self._get_latency(),
        )

        # Cache result
        self._cache[cache_key] = result

        if blocked:
            self._stats["blocked"] += 1
        else:
            self._stats["passed"] += 1

        self._stats["total_latency_ms"] += result.latency_ms

        return result

    async def check_output(
        self, 
        content: str, 
        guard_type: GuardType = GuardType.OUTPUT_VALIDATION,
        context: Optional[Dict[str, Any]] = None
    ) -> GuardResult:
        """Check output content for policy violations."""
        return await self.check_input(content, guard_type, context)

    async def check_multiple(
        self, 
        content: str, 
        guard_types: List[GuardType],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[GuardType, GuardResult]:
        """
        Run multiple guard checks on the same content.
        
        Args:
            content: Text content to check
            guard_types: List of guard types to run
            context: Optional context
            
        Returns:
            Dictionary mapping guard type to result
        """
        results = {}
        for guard_type in guard_types:
            results[guard_type] = await self.check_input(content, guard_type, context)
        return results

    def _perform_check(
        self, 
        content: str, 
        guard_type: GuardType
    ) -> List[Dict[str, Any]]:
        """Perform the actual content check (simulated)."""
        violations = []
        content_lower = content.lower()

        if guard_type == GuardType.INPUT_VALIDATION:
            # Check for empty or very short content
            if len(content.strip()) == 0:
                violations.append({
                    "type": "EMPTY_CONTENT",
                    "message": "Input content is empty",
                    "severity": "low",
                })
            elif len(content) > 100000:
                violations.append({
                    "type": "CONTENT_TOO_LONG",
                    "message": "Input exceeds maximum length",
                    "severity": "medium",
                })

        elif guard_type == GuardType.PII_DETECTION:
            # Simulate PII detection
            import re
            email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
            phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
            ssn_pattern = r'\b\d{3}-\d{2}-\d{4}\b'
            
            emails = re.findall(email_pattern, content)
            if emails:
                violations.append({
                    "type": "PII_EMAIL",
                    "message": f"Detected {len(emails)} email(s)",
                    "severity": "high",
                    "detections": emails[:3],
                })
            
            phones = re.findall(phone_pattern, content)
            if phones:
                violations.append({
                    "type": "PII_PHONE",
                    "message": f"Detected {len(phones)} phone number(s)",
                    "severity": "high",
                    "detections": phones[:3],
                })
            
            if re.search(ssn_pattern, content):
                violations.append({
                    "type": "PII_SSN",
                    "message": "Possible SSN detected",
                    "severity": "critical",
                })

        elif guard_type == GuardType.INJECTION_DETECTION:
            # Check for injection patterns
            injection_patterns = [
                (r'ignore\s+previous\s+instructions', 'INSTRUCTION_IGNORE'),
                (r'system\s*[:=]', 'SYSTEM_PROMPT_LEAK'),
                (r'disregard\s+.*?instructions', 'INSTRUCTION_DISREGARD'),
                (r'<[^>]+>', 'HTML_INJECTION'),
                (r'\{[^{]+\}', 'JSON_INJECTION'),
                (r'sql\s*injection', 'KEYWORD_DETECTION'),
                (r'drop\s+table', 'SQL_DESTRUCTIVE'),
            ]
            
            for pattern, violation_type in injection_patterns:
                if re.search(pattern, content_lower):
                    violations.append({
                        "type": violation_type,
                        "message": f"Potential {violation_type.replace('_', ' ').lower()} detected",
                        "severity": "critical" if "DESTRUCTIVE" in violation_type else "high",
                        "pattern": pattern,
                    })

        elif guard_type == GuardType.CONTENT_FILTER:
            # Check for inappropriate content
            blocked_terms = [
                ("violence", "Violence-related content"),
                ("weapon", "Weapon-related content"),
                ("illegal", "Illegal activity"),
                ("harmful", "Harmful content"),
            ]
            
            for term, description in blocked_terms:
                if term in content_lower:
                    violations.append({
                        "type": "CONTENT_BLOCKED",
                        "message": description,
                        "severity": "high",
                        "term": term,
                    })

        elif guard_type == GuardType.OUTPUT_VALIDATION:
            # Check for sensitive information in outputs
            import re
            if re.search(r'api[_-]?key', content_lower):
                violations.append({
                    "type": "SENSITIVE_API_KEY",
                    "message": "Possible API key in output",
                    "severity": "critical",
                })
            if re.search(r'secret', content_lower):
                violations.append({
                    "type": "SENSITIVE_SECRET",
                    "message": "Possible secret in output",
                    "severity": "high",
                })

        # Simulate detection rate (not all violations are caught)
        if violations and random.random() > self._config.detection_rate:
            # False negative - violation not detected
            violations = []

        return violations

    async def _simulate_latency(self):
        """Simulate network and processing latency."""
        latency = self._get_latency()
        await asyncio.sleep(latency / 1000)

    def _get_latency(self) -> float:
        """Get simulated latency value."""
        base = self._config.base_latency_ms
        variance = self._config.latency_variance_ms
        return max(0, random.gauss(base, variance / 3))


class ParallelGuardService:
    """
    Guard service that runs multiple checks in parallel.
    Useful for testing concurrent guard execution.
    """

    def __init__(self, services: Dict[GuardType, MockGuardService]):
        self._services = services

    async def check_all(
        self,
        content: str,
        guard_types: List[GuardType],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[GuardType, GuardResult]:
        """
        Run all specified guard checks in parallel.
        
        Args:
            content: Text content to check
            guard_types: Types of guards to run
            context: Optional context
            
        Returns:
            Dictionary mapping guard type to result
        """
        tasks = []
        for guard_type in guard_types:
            service = self._services.get(guard_type)
            if service:
                tasks.append(service.check_input(content, guard_type, context))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Convert exceptions to failed results
        final_results = {}
        for i, guard_type in enumerate(guard_types):
            if isinstance(results[i], Exception):
                final_results[guard_type] = GuardResult(
                    passed=False,
                    error=str(results[i]),
                )
            else:
                final_results[guard_type] = results[i]
        
        return final_results


def create_guard_service(
    guard_type: GuardType,
    base_latency_ms: float = 5.0,
    error_rate: float = 0.0,
    timeout_rate: float = 0.0,
) -> MockGuardService:
    """Factory function to create a configured guard service."""
    config = GuardConfig(
        base_latency_ms=base_latency_ms,
        error_rate=error_rate,
        timeout_rate=timeout_rate,
    )
    return MockGuardService(config)


def create_parallel_guard_services(
    guard_types: List[GuardType],
    base_latency_ms: float = 5.0,
) -> ParallelGuardService:
    """Factory function to create parallel guard services."""
    services = {}
    for guard_type in guard_types:
        services[guard_type] = create_guard_service(guard_type, base_latency_ms)
    return ParallelGuardService(services)
