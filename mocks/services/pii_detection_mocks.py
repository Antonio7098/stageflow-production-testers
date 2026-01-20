"""
GUARD-003 PII/PHI Detection Mock Service

This module provides a mock PII detection service with configurable detection
rates for testing redaction accuracy in Stageflow GUARD stages.

The mock simulates realistic PII detection behavior including:
- Configurable detection rates by PII category
- Probabilistic false positives and false negatives
- Various edge case handling
- Comprehensive logging and statistics
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


class PIICategory(Enum):
    """PII/PHI categories for detection testing."""
    PERSON_NAME = "person_name"
    PHONE_NUMBER = "phone_number"
    EMAIL = "email"
    SSN = "ssn"
    DATE_OF_BIRTH = "date_of_birth"
    ADDRESS = "address"
    MEDICAL_RECORD_NUMBER = "mrn"
    HEALTH_PLAN_ID = "health_plan_id"
    ACCOUNT_NUMBER = "account_number"
    LICENSE_NUMBER = "license_number"
    VEHICLE_ID = "vehicle_id"
    DEVICE_ID = "device_id"
    WEB_URL = "web_url"
    IP_ADDRESS = "ip_address"
    BIOMETRIC_ID = "biometric_id"
    PHOTO_ID = "photo_id"
    ZIP_CODE = "zip_code"
    AGE_OVER_89 = "age_over_89"
    OTHER_PHI = "other_phi"

    @classmethod
    def from_string(cls, value: str) -> "PIICategory":
        """Convert string to PIICategory."""
        mapping = {
            "PERSON": cls.PERSON_NAME,
            "PERSON_NAME": cls.PERSON_NAME,
            "NAME": cls.PERSON_NAME,
            "PHONE": cls.PHONE_NUMBER,
            "PHONE_NUMBER": cls.PHONE_NUMBER,
            "EMAIL": cls.EMAIL,
            "EMAIL_ADDRESS": cls.EMAIL,
            "SSN": cls.SSN,
            "US_SSN": cls.SSN,
            "DOB": cls.DATE_OF_BIRTH,
            "DATE_OF_BIRTH": cls.DATE_OF_BIRTH,
            "ADDRESS": cls.ADDRESS,
            "MRN": cls.MEDICAL_RECORD_NUMBER,
            "MEDICAL_RECORD": cls.MEDICAL_RECORD_NUMBER,
            "HEALTH_PLAN": cls.HEALTH_PLAN_ID,
            "ACCOUNT": cls.ACCOUNT_NUMBER,
            "LICENSE": cls.LICENSE_NUMBER,
            "VEHICLE": cls.VEHICLE_ID,
            "DEVICE": cls.DEVICE_ID,
            "URL": cls.WEB_URL,
            "WEB_URL": cls.WEB_URL,
            "IP": cls.IP_ADDRESS,
            "IP_ADDRESS": cls.IP_ADDRESS,
            "ZIP": cls.ZIP_CODE,
            "ZIP_CODE": cls.ZIP_CODE,
            "AGE": cls.AGE_OVER_89,
        }
        return mapping.get(value.upper(), cls.OTHER_PHI)


class DetectionResult(Enum):
    """Result of PII detection."""
    PASSED = "passed"
    REDACTED = "redacted"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class PIIDetectionConfig:
    """Configuration for PII detection behavior."""

    detection_rates: dict[str, float] = field(default_factory=lambda: {
        "person_name": 0.95,
        "phone_number": 0.98,
        "email": 0.99,
        "ssn": 0.99,
        "date_of_birth": 0.97,
        "address": 0.92,
        "medical_record_number": 0.90,
        "health_plan_id": 0.88,
        "account_number": 0.93,
        "license_number": 0.85,
        "vehicle_id": 0.80,
        "device_id": 0.82,
        "web_url": 0.96,
        "ip_address": 0.95,
        "zip_code": 0.94,
        "age_over_89": 0.70,
        "other_phi": 0.75,
    })

    false_positive_rate: float = 0.02
    partial_detection_rate: float = 0.05
    redact_on_detection: bool = True
    redaction_char: str = "*"
    enable_adversarial_vulnerability: bool = False
    enable_edge_case_vulnerability: bool = False

    def get_detection_rate(self, category: str) -> float:
        """Get detection rate for a specific category."""
        return self.detection_rates.get(category.lower(), 0.75)


@dataclass
class PIIDetectionResult:
    """Result of a single PII detection operation."""
    result: DetectionResult
    detected_entities: list[dict[str, Any]]
    redacted_text: str
    processing_time_ms: float
    confidence: float = 0.0
    error: Optional[str] = None


@dataclass
class PIIEntity:
    """Represents a detected PII entity."""
    category: str
    text: str
    start: int
    end: int
    confidence: float
    redacted: bool = True
    redaction_method: str = "char_replacement"


class PIIDetectionService:
    """
    Mock PII detection service with configurable detection rates.

    This service simulates realistic PII detection behavior for testing
    Stageflow GUARD stages without requiring actual NER/LLM calls.
    """

    def __init__(self, config: Optional[PIIDetectionConfig] = None):
        self.config = config or PIIDetectionConfig()
        self._stats = {
            "total_checks": 0,
            "passed": 0,
            "redacted": 0,
            "partial": 0,
            "failed": 0,
            "entities_detected": 0,
            "entities_missed": 0,
            "false_positives": 0,
        }
        self._random_seed = 42

    def _seed(self, seed: int) -> None:
        """Set random seed for reproducibility."""
        self._random_seed = seed
        random.seed(seed)

    def _detect_entities(self, text: str) -> list[dict[str, Any]]:
        """
        Simulate entity detection in text.

        In a real implementation, this would use NER models or LLM calls.
        Here we use regex patterns and probabilistic simulation.
        """
        entities = []

        patterns = {
            "person_name": [
                r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b",
                r"\b[A-Z][a-z]+\s+[A-Z]\.\s*[A-Z][a-z]+\b",
                r"\bDr\.\s*[A-Z][a-z]+\b",
                r"\bMr\.\s*[A-Z][a-z]+\b",
                r"\bMrs\.\s*[A-Z][a-z]+\b",
                r"\bMs\.\s*[A-Z][a-z]+\b",
                r"\bPatient\s+[A-Z][a-z]+\b",
                r"\b[A-Z][a-z]+,\s+[A-Z][a-z]+\b",
            ],
            "phone_number": [
                r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
                r"\b\(\d{3}\)\s*\d{3}[-.]?\d{4}\b",
                r"\b\d{3}\s+\d{3}\s+\d{4}\b",
                r"tel:\s*\d{3}[-]?\d{3}[-]?\d{4}",
            ],
            "email": [
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            ],
            "ssn": [
                r"\b\d{3}[-]?\d{2}[-]?\d{4}\b",
                r"\bSSN\s*[:=]?\s*\d{3}[-]?\d{2}[-]?\d{4}\b",
            ],
            "date_of_birth": [
                r"\bDOB\s*[:=]?\s*(0?[1-9]|1[0-2])[-/](0?[1-9]|[12][0-9]|3[01])[-/]\d{2,4}\b",
                r"\b(0?[1-9]|1[0-2])[-/](0?[1-9]|[12][0-9]|3[01])[-/]\d{2,4}\b",
                r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b",
            ],
            "address": [
                r"\b\d+\s+[A-Z][a-z]+\s+(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|Way|Circle|Cir)\b",
                r"\b\d+\s+[A-Z][a-z]+,\s+[A-Z][a-z]+,\s+[A-Z]{2}\s+\d{5}\b",
            ],
            "medical_record_number": [
                r"\bMRN\s*[:=]?\s*\d+\b",
                r"\bmedical record number\s*[:=]?\s*\d+\b",
            ],
            "health_plan_id": [
                r"\b(?:Health Plan|Insurance|Policy)\s*(?:ID|Number)?\s*[:=]?\s*\d+\b",
            ],
            "account_number": [
                r"\b(?:Account|Acct)\s*(?:Number|No\\.?)?\s*[:=]?\s*\d+\b",
            ],
            "web_url": [
                r"https?://[^\s<>\"]+",
                r"www\.[^\s<>\"]+",
            ],
            "ip_address": [
                r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
            ],
            "zip_code": [
                r"\b\d{5}(?:-\d{4})?\b",
                r"\bZIP\s*[:=]?\s*\d{5}(?:-\d{4})?\b",
            ],
        }

        for category, pattern_list in patterns.items():
            for pattern in pattern_list:
                for match in re.finditer(pattern, text):
                    entities.append({
                        "category": category,
                        "text": match.group(),
                        "start": match.start(),
                        "end": match.end(),
                    })

        return entities

    def _simulate_detection(
        self,
        entity: dict[str, Any],
        text_length: int,
    ) -> tuple[bool, bool]:
        """
        Simulate detection outcome for an entity.

        Returns:
            tuple: (should_detect, is_false_positive)
        """
        category = entity["category"].lower()
        base_rate = self.config.get_detection_rate(category)

        if self.config.enable_adversarial_vulnerability:
            if text_length < 3:  # Very short text may hide PII
                base_rate *= 0.5

        if self.config.enable_edge_case_vulnerability:
            if entity["start"] < 10 or entity["end"] > text_length - 10:
                base_rate *= 0.8

        should_detect = random.random() < base_rate
        is_false_positive = random.random() < self.config.false_positive_rate

        return should_detect, is_false_positive

    def _redact_entity(
        self,
        text: str,
        entity: dict[str, Any],
        method: str = "char_replacement",
    ) -> str:
        """Redact an entity in text."""
        start = entity["start"]
        end = entity["end"]
        original = text[start:end]

        if method == "char_replacement":
            char = self.config.redaction_char
            if len(original) <= 2:
                redacted = char * len(original)
            else:
                redacted = char * (len(original) - 2) + original[-2:]
        elif method == "full_mask":
            redacted = "[REDACTED]"
        elif method == "hash":
            redacted = f"#HASH#{hash(original) % 100000}#"
        else:
            redacted = self.config.redaction_char * len(original)

        return text[:start] + redacted + text[end:]

    async def detect(
        self,
        content: str,
        context: Optional[dict[str, Any]] = None,
    ) -> PIIDetectionResult:
        """
        Detect and optionally redact PII in content.

        Args:
            content: Text content to analyze
            context: Optional context (user_id, session_id, etc.)

        Returns:
            PIIDetectionResult with detection outcome
        """
        import time
        start_time = time.perf_counter()
        self._stats["total_checks"] += 1

        detected_entities: list[dict[str, Any]] = []
        missed_entities: list[dict[str, Any]] = []

        all_entities = self._detect_entities(content)

        for entity in all_entities:
            should_detect, is_fp = self._simulate_detection(
                entity, len(content)
            )

            if should_detect:
                if is_fp:
                    self._stats["false_positives"] += 1
                else:
                    detected_entities.append(entity)
                    self._stats["entities_detected"] += 1
            else:
                missed_entities.append(entity)
                self._stats["entities_missed"] += 1

        redacted_text = content
        if self.config.redact_on_detection and detected_entities:
            for entity in sorted(detected_entities, key=lambda x: x["start"], reverse=True):
                redacted_text = self._redact_entity(redacted_text, entity)

        processing_time_ms = (time.perf_counter() - start_time) * 1000

        if not detected_entities and not missed_entities:
            self._stats["passed"] += 1
            result = DetectionResult.PASSED
        elif missed_entities and not detected_entities:
            self._stats["partial"] += 1
            result = DetectionResult.PARTIAL
        elif missed_entities and detected_entities:
            self._stats["partial"] += 1
            result = DetectionResult.PARTIAL
        else:
            self._stats["redacted"] += 1
            result = DetectionResult.REDACTED

        confidence = (
            len(detected_entities) /
            max(len(detected_entities) + len(missed_entities), 1)
        )

        return PIIDetectionResult(
            result=result,
            detected_entities=detected_entities,
            redacted_text=redacted_text,
            processing_time_ms=processing_time_ms,
            confidence=confidence,
        )

    def get_stats(self) -> dict:
        """Get service statistics."""
        total = self._stats["total_checks"]
        detected = self._stats["entities_detected"]
        missed = self._stats["entities_missed"]
        recall = detected / max(detected + missed, 1)

        return {
            **self._stats,
            "recall_rate": recall,
            "false_positive_rate": self._stats["false_positives"] / max(total, 1),
        }

    def reset_stats(self) -> None:
        """Reset service statistics."""
        self._stats = {
            "total_checks": 0,
            "passed": 0,
            "redacted": 0,
            "partial": 0,
            "failed": 0,
            "entities_detected": 0,
            "entities_missed": 0,
            "false_positives": 0,
        }


class PIITestDataGenerator:
    """Generator for PII test data in various categories."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)

    def generate_person_names(self, count: int) -> list[str]:
        """Generate test person names."""
        first_names = [
            "John", "Jane", "Michael", "Emily", "David", "Sarah",
            "Robert", "Lisa", "William", "Jennifer", "James", "Amanda",
            "Charles", "Jessica", "Thomas", "Ashley", "Daniel", "Stephanie",
        ]
        last_names = [
            "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
            "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez",
            "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore",
        ]
        return [
            f"{random.choice(first_names)} {random.choice(last_names)}"
            for _ in range(count)
        ]

    def generate_phone_numbers(self, count: int) -> list[str]:
        """Generate test phone numbers in various formats."""
        formats = [
            "XXX-XXX-XXXX",
            "XXX.XXX.XXXX",
            "(XXX) XXX-XXXX",
            "XXX XXX XXXX",
            "XXXXXXXXXX",
        ]
        results = []
        for _ in range(count):
            fmt = random.choice(formats)
            num = "".join(str(random.randint(0, 9)) for _ in range(10))
            results.append(num.join(fmt.replace("XXX", "{}").split("{}")))
        return results

    def generate_emails(self, count: int) -> list[str]:
        """Generate test email addresses."""
        domains = ["gmail.com", "yahoo.com", "outlook.com", "company.org", "hospital.net"]
        names = ["john.doe", "jane_doe", "johndoe", "jdoe123", "dr_smith"]
        return [f"{random.choice(names)}{i}@{random.choice(domains)}" for i in range(count)]

    def generate_ssn(self, count: int) -> list[str]:
        """Generate test SSNs."""
        formats = ["XXX-XX-XXXX", "XXXXXXXXX"]
        results = []
        for _ in range(count):
            fmt = random.choice(formats)
            nums = "".join(str(random.randint(0, 9)) for _ in range(9))
            if fmt == "XXX-XX-XXXX":
                results.append(f"{nums[:3]}-{nums[3:5]}-{nums[5:]}")
            else:
                results.append(nums)
        return results

    def generate_dates_of_birth(self, count: int) -> list[str]:
        """Generate test dates of birth."""
        formats = [
            "%m/%d/%Y",
            "%m-%d-%Y",
            "%B %d, %Y",
            "%Y-%m-%d",
        ]
        results = []
        for _ in range(count):
            year = random.randint(1950, 2005)
            month = random.randint(1, 12)
            day = random.randint(1, 28)
            from datetime import date
            dob = date(year, month, day)
            fmt = random.choice(formats)
            results.append(dob.strftime(fmt))
        return results

    def generate_addresses(self, count: int) -> list[str]:
        """Generate test addresses."""
        streets = ["Main St", "Oak Ave", "Park Rd", "Broadway", "Maple Dr", "Cedar Ln"]
        cities = ["Springfield", "Riverside", "Georgetown", "Franklin", "Clinton", "Fairview"]
        results = []
        for i in range(count):
            num = random.randint(100, 9999)
            street = random.choice(streets)
            city = random.choice(cities)
            state = random.choice(["NY", "CA", "TX", "FL", "IL", "PA"])
            zip_code = f"{random.randint(10000, 99999)}"
            results.append(f"{num} {street}, {city}, {state} {zip_code}")
        return results

    def generate_clinical_text(self, include_phi: bool = True) -> str:
        """Generate realistic clinical text with optional PHI."""
        templates = [
            "Patient {name} presented with {symptom}. History includes {condition}. Last seen on {date}.",
            "Assessment: {name}, DOB: {dob}. Chief complaint: {symptom}. Plan: {treatment}",
            "Consultation note for {name}. Contact: {phone}. Insurance: {insurance_id}",
            "Discharge summary for {name}. MRN: {mrn}. Admitted: {date}. Discharged: {date2}.",
        ]

        name = random.choice(self.generate_person_names(1)) if include_phi else "[NAME]"
        phone = random.choice(self.generate_phone_numbers(1)) if include_phi else "XXX-XXX-XXXX"
        dob = random.choice(self.generate_dates_of_birth(1)) if include_phi else "XX/XX/XXXX"
        date = random.choice(self.generate_dates_of_birth(1)).replace(str(random.randint(1950, 2005)), "2024")
        mrn = f"MRN{random.randint(100000, 999999)}" if include_phi else "XXXXXX"
        insurance_id = f"{random.randint(100000000, 999999999)}" if include_phi else "XXXXXXXXX"

        symptoms = ["chest pain", "shortness of breath", "headache", "fatigue", "abdominal pain"]
        conditions = ["hypertension", "diabetes type 2", "asthma", "anxiety", "GERD"]
        treatments = ["medication adjustment", "follow-up in 2 weeks", "referral to specialist", "lifestyle changes"]

        template = random.choice(templates)
        return template.format(
            name=name,
            phone=phone,
            dob=dob,
            date=date,
            date2=date,
            symptom=random.choice(symptoms),
            condition=random.choice(conditions),
            treatment=random.choice(treatments),
            mrn=mrn,
            insurance_id=insurance_id,
        )

    def generate_happy_path_dataset(self, count: int = 100) -> list[dict[str, Any]]:
        """Generate happy path test data with standard PII formats."""
        data = []

        for i in range(count):
            phi_type = random.choice([
                "person_name", "phone_number", "email", "ssn",
                "date_of_birth", "address", "web_url", "ip_address"
            ])

            if phi_type == "person_name":
                text = f"Patient: {random.choice(self.generate_person_names(1))}"
            elif phi_type == "phone_number":
                text = f"Phone: {random.choice(self.generate_phone_numbers(1))}"
            elif phi_type == "email":
                text = f"Email: {random.choice(self.generate_emails(1))}"
            elif phi_type == "ssn":
                text = f"SSN: {random.choice(self.generate_ssn(1))}"
            elif phi_type == "date_of_birth":
                text = f"DOB: {random.choice(self.generate_dates_of_birth(1))}"
            elif phi_type == "address":
                text = f"Address: {random.choice(self.generate_addresses(1))}"
            elif phi_type == "web_url":
                text = f"Visit: {random.choice(['https://example.com', 'www.test.org', 'http://demo.net'])}"
            else:
                text = f"IP: {random.randint(1, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"

            data.append({
                "text": text,
                "category": phi_type,
                "has_phi": True,
                "expected_redaction": True,
            })

        return data

    def generate_edge_case_dataset(self, count: int = 50) -> list[dict[str, Any]]:
        """Generate edge case test data with unusual PII formats."""
        data = []

        edge_cases = [
            {
                "text": "My number is one two three four five six seven eight nine zero",
                "category": "phone_number",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Spelled out phone number",
            },
            {
                "text": "Contact at john at doe dot com",
                "category": "email",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Obfuscated email",
            },
            {
                "text": "SSN is 1 2 3 - 4 5 - 6 7 8 9",
                "category": "ssn",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Spaced SSN",
            },
            {
                "text": "Patient J.D. for short, full name John David Smith",
                "category": "person_name",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Multiple name formats in same text",
            },
            {
                "text": "ZIP code 12345-6789 and also 12345",
                "category": "zip_code",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Multiple ZIP formats",
            },
            {
                "text": "Born on the 5th of January, 1985",
                "category": "date_of_birth",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Written date format",
            },
            {
                "text": "Email: user@domain.co.uk",
                "category": "email",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Multi-level domain email",
            },
            {
                "text": "IP address two fifty five dot one hundred one dot zero dot one",
                "category": "ip_address",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Written IP address",
            },
        ]

        for case in edge_cases:
            data.append(case)

        for i in range(count - len(edge_cases)):
            phi_type = random.choice([
                "person_name", "phone_number", "email", "ssn",
                "date_of_birth", "address"
            ])
            data.append({
                "text": self.generate_clinical_text(include_phi=True),
                "category": phi_type,
                "has_phi": True,
                "expected_redaction": True,
                "description": f"Clinical text with {phi_type}",
            })

        return data

    def generate_adversarial_dataset(self, count: int = 50) -> list[dict[str, Any]]:
        """Generate adversarial test data designed to evade detection."""
        data = []

        adversarial_cases = [
            {
                "text": "C0ntact at j0hn-d03@examp13.com",
                "category": "email",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Leetspeak email",
            },
            {
                "text": "Ph0n3 numb3r: 5-5-5-1-2-3-4-5-6-7",
                "category": "phone_number",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Numeric substitution phone",
            },
            {
                "text": "S-S-S-N: 1-2-3-4-5-6-7-8-9",
                "category": "ssn",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Word-separated SSN",
            },
            {
                "text": "Jo\u0301hn Doe",  # Unicode combining accent
                "category": "person_name",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Unicode homoglyph name",
            },
            {
                "text": "John D00e for short",
                "category": "person_name",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Numeric substitution name",
            },
            {
                "text": "Call at +1 (555) 123-4567 ext 1234",
                "category": "phone_number",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Phone with extension",
            },
            {
                "text": "Email: u s e r @ e x a m p l e . c o m",
                "category": "email",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Spaced email",
            },
            {
                "text": "SSN: 1\n2\n3\n-\n4\n5\n-\n6\n7\n8\n9",
                "category": "ssn",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Newline-separated SSN",
            },
            {
                "text": "Patient lives at 123 Main St. in 90210",
                "category": "zip_code",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Address with ZIP in text",
            },
            {
                "text": "My number is <phone>555-123-4567</phone>",
                "category": "phone_number",
                "has_phi": True,
                "expected_redaction": True,
                "description": "XML-tagged phone",
            },
        ]

        for case in adversarial_cases:
            data.append(case)

        for i in range(count - len(adversarial_cases)):
            data.append({
                "text": self.generate_clinical_text(include_phi=True),
                "category": "other_phi",
                "has_phi": True,
                "expected_redaction": True,
                "description": "Adversarial clinical text",
            })

        return data

    def generate_no_phi_dataset(self, count: int = 30) -> list[dict[str, Any]]:
        """Generate test data with no PII (for false positive testing)."""
        data = []
        no_phi_texts = [
            "The patient presented with general symptoms of fatigue.",
            "Please schedule a follow-up appointment.",
            "Review of systems was unremarkable.",
            "The weather was sunny today.",
            "Laboratory results are within normal limits.",
            "Continue current medication regimen.",
            "Patient education materials provided.",
            "Vital signs stable.",
            "No acute distress noted.",
            "Please consult the standard protocols.",
        ]

        for i in range(count):
            data.append({
                "text": random.choice(no_phi_texts),
                "category": "none",
                "has_phi": False,
                "expected_redaction": False,
            })

        return data

    def generate_full_test_dataset(
        self,
        happy_path_count: int = 100,
        edge_case_count: int = 50,
        adversarial_count: int = 50,
        no_phi_count: int = 30,
    ) -> dict[str, list[dict[str, Any]]]:
        """Generate complete test dataset."""
        return {
            "happy_path": self.generate_happy_path_dataset(happy_path_count),
            "edge_cases": self.generate_edge_case_dataset(edge_case_count),
            "adversarial": self.generate_adversarial_dataset(adversarial_count),
            "no_phi": self.generate_no_phi_dataset(no_phi_count),
        }


def create_low_recall_config() -> PIIDetectionConfig:
    """Create config with intentionally low recall for chaos testing."""
    return PIIDetectionConfig(
        detection_rates={
            "person_name": 0.70,
            "phone_number": 0.80,
            "email": 0.85,
            "ssn": 0.85,
            "date_of_birth": 0.75,
            "address": 0.60,
            "medical_record_number": 0.55,
            "health_plan_id": 0.50,
            "account_number": 0.65,
            "license_number": 0.50,
            "vehicle_id": 0.45,
            "device_id": 0.48,
            "web_url": 0.90,
            "ip_address": 0.88,
            "zip_code": 0.75,
            "age_over_89": 0.40,
            "other_phi": 0.50,
        },
        false_positive_rate=0.05,
        partial_detection_rate=0.15,
    )


def create_high_recall_config() -> PIIDetectionConfig:
    """Create config optimized for high recall (>99%)."""
    return PIIDetectionConfig(
        detection_rates={
            "person_name": 0.995,
            "phone_number": 0.998,
            "email": 0.999,
            "ssn": 0.999,
            "date_of_birth": 0.997,
            "address": 0.990,
            "medical_record_number": 0.990,
            "health_plan_id": 0.988,
            "account_number": 0.992,
            "license_number": 0.985,
            "vehicle_id": 0.980,
            "device_id": 0.980,
            "web_url": 0.998,
            "ip_address": 0.997,
            "zip_code": 0.995,
            "age_over_89": 0.970,
            "other_phi": 0.980,
        },
        false_positive_rate=0.10,
        partial_detection_rate=0.02,
    )
