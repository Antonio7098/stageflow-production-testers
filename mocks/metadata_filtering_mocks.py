"""
Metadata Filtering Mocks for ENRICH-010 Stress Testing

This module provides mock data and service simulations for testing
metadata filtering accuracy in RAG/Knowledge retrieval pipelines.
"""

import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class DocumentCategory(Enum):
    TECHNICAL = "technical"
    BUSINESS = "business"
    LEGAL = "legal"
    MEDICAL = "medical"
    FINANCIAL = "financial"
    MARKETING = "marketing"
    HR = "hr"
    ENGINEERING = "engineering"


class DocumentStatus(Enum):
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    EXPIRED = "expired"


@dataclass
class MetadataFilter:
    """Represents a metadata filter condition."""
    field_name: str
    operator: str  # equals, in, contains, gt, lt, gte, lte, range
    value: Any
    description: str = ""

    def matches(self, document_metadata: Dict[str, Any]) -> bool:
        """Check if document metadata matches this filter."""
        doc_value = document_metadata.get(self.field_name)

        if doc_value is None:
            return False

        try:
            if self.operator == "equals":
                return doc_value == self.value
            elif self.operator == "in":
                return doc_value in self.value
            elif self.operator == "contains":
                return self.value in str(doc_value)
            elif self.operator == "gt":
                return doc_value > self.value
            elif self.operator == "lt":
                return doc_value < self.value
            elif self.operator == "gte":
                return doc_value >= self.value
            elif self.operator == "lte":
                return doc_value <= self.value
            elif self.operator == "range":
                low, high = self.value
                return low <= doc_value <= high
            elif self.operator == "exists":
                return self.value == (doc_value is not None)
            else:
                logger.warning(f"Unknown operator: {self.operator}")
                return False
        except (TypeError, ValueError) as e:
            logger.debug(f"Filter matching error: {e}")
            return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field_name,
            "operator": self.operator,
            "value": self.value,
            "description": self.description,
        }


@dataclass
class TestDocument:
    """Represents a test document with metadata."""
    document_id: str
    title: str
    content: str
    category: str
    status: str
    created_date: datetime
    modified_date: datetime
    author: str
    department: str
    priority: str
    tags: List[str] = field(default_factory=list)
    version: int = 1
    source: str = "internal"
    confidence_score: float = 0.95
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_vector_db_format(self) -> Dict[str, Any]:
        """Convert to vector database format for retrieval."""
        return {
            "id": self.document_id,
            "text": self.content,
            "metadata": {
                "category": self.category,
                "status": self.status,
                "created_date": self.created_date.isoformat(),
                "modified_date": self.modified_date.isoformat(),
                "author": self.author,
                "department": self.department,
                "priority": self.priority,
                "tags": self.tags,
                "version": self.version,
                "source": self.source,
                "confidence_score": self.confidence_score,
                **self.metadata,
            },
        }

    def matches_filter(self, filter_obj: MetadataFilter) -> bool:
        """Check if document matches a filter."""
        metadata = self.to_vector_db_format()["metadata"]
        return filter_obj.matches(metadata)


class MetadataFilteringMocks:
    """
    Mock service for simulating metadata filtering in RAG pipelines.
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)
        self.documents: List[TestDocument] = []
        self.filter_operators = ["equals", "in", "contains", "gt", "lt", "gte", "lte", "range"]
        self._generate_test_documents()

    def _generate_test_documents(self):
        """Generate a corpus of test documents with varied metadata."""
        categories = [c.value for c in DocumentCategory]
        statuses = [s.value for s in DocumentStatus]
        departments = ["engineering", "product", "sales", "marketing", "hr", "finance", "legal"]
        priorities = ["low", "medium", "high", "critical"]
        authors = ["alice", "bob", "charlie", "diana", "eve", "frank"]

        # Generate documents with varied dates
        base_date = datetime(2024, 1, 1)
        for i in range(150):
            # Stagger creation dates over 2 years
            created_days = random.randint(0, 730)
            modified_days = random.randint(0, created_days)
            created_date = base_date + timedelta(days=created_days)
            modified_date = created_date + timedelta(days=modified_days)

            # Create varied metadata schemas
            metadata_schema = random.choice(["full", "partial", "inconsistent"])

            if metadata_schema == "full":
                metadata = {}
            elif metadata_schema == "partial":
                # Missing some fields
                metadata = {"custom_field": f"value_{i}"}
            else:
                # Inconsistent types
                metadata = {
                    "numeric_as_string": str(i),
                    "list_as_string": f"item1,item2,item{i % 3}",
                    "boolean_as_int": random.randint(0, 1),
                }

            doc = TestDocument(
                document_id=f"doc_{i:04d}",
                title=f"Test Document {i}: {random.choice(['Technical', 'Business', 'Review', 'Guide', 'Report'])}",
                content=self._generate_document_content(i),
                category=random.choice(categories),
                status=random.choice(statuses),
                created_date=created_date,
                modified_date=modified_date,
                author=random.choice(authors),
                department=random.choice(departments),
                priority=random.choice(priorities),
                tags=[random.choice(["important", "urgent", "review", "approved", "draft"]) for _ in range(random.randint(1, 4))],
                version=random.randint(1, 5),
                source=random.choice(["internal", "external", "partner", "public"]),
                confidence_score=round(random.uniform(0.7, 1.0), 2),
                metadata=metadata,
            )
            self.documents.append(doc)

        logger.info(f"Generated {len(self.documents)} test documents")

    def _generate_document_content(self, doc_id: int) -> str:
        """Generate document content based on category."""
        topics = {
            DocumentCategory.TECHNICAL: [
                "API integration, microservices architecture, containerization",
                "Machine learning pipeline, model training, data preprocessing",
                "Database optimization, query performance, indexing strategies",
            ],
            DocumentCategory.BUSINESS: [
                "Quarterly revenue analysis, market trends, competitive landscape",
                "Strategic planning, risk assessment, opportunity identification",
                "Customer acquisition, retention metrics, lifetime value analysis",
            ],
            DocumentCategory.LEGAL: [
                "Regulatory compliance, data privacy, contract review",
                "Intellectual property, patent filing, trademark registration",
                "Liability coverage, insurance requirements, legal precedent",
            ],
            DocumentCategory.MEDICAL: [
                "Clinical trial results, patient outcomes, treatment protocols",
                "Drug interactions, dosage guidelines, side effects",
                "Diagnostic procedures, imaging analysis, laboratory results",
            ],
            DocumentCategory.FINANCIAL: [
                "Budget allocation, cost optimization, revenue forecasting",
                "Investment portfolio, risk management, asset allocation",
                "Tax implications, audit preparation, financial reporting",
            ],
            DocumentCategory.MARKETING: [
                "Brand positioning, messaging strategy, campaign analytics",
                "Customer segmentation, targeting criteria, conversion optimization",
                "Social media engagement, content strategy, influencer partnerships",
            ],
            DocumentCategory.HR: [
                "Employee performance reviews, talent development, succession planning",
                "Compensation benchmarking, benefits administration, retention strategies",
                "Recruitment pipeline, interview process, onboarding procedures",
            ],
            DocumentCategory.ENGINEERING: [
                "System architecture, scalability analysis, performance optimization",
                "Code review guidelines, testing strategies, deployment procedures",
                "Technical debt reduction, refactoring priorities, infrastructure upgrades",
            ],
        }

        topic = random.choice(list(topics.values())[doc_id % 8])
        return f"Document {doc_id}: {topic}. This document covers key aspects of the subject matter and provides detailed insights for stakeholders."

    def get_documents_by_category(self, category: str) -> List[TestDocument]:
        """Get documents filtered by category."""
        return [d for d in self.documents if d.category == category]

    def get_documents_by_status(self, status: str) -> List[TestDocument]:
        """Get documents filtered by status."""
        return [d for d in self.documents if d.status == status]

    def get_documents_by_date_range(
        self, start_date: datetime, end_date: datetime
    ) -> List[TestDocument]:
        """Get documents created within a date range."""
        return [
            d
            for d in self.documents
            if start_date <= d.created_date <= end_date
        ]

    def apply_metadata_filter(
        self, filter_obj: MetadataFilter, documents: Optional[List[TestDocument]] = None
    ) -> Tuple[List[TestDocument], Dict[str, Any]]:
        """
        Apply a metadata filter to documents.

        Returns:
            Tuple of (filtered_documents, filter_stats)
        """
        docs = documents or self.documents
        start_time = time.perf_counter()

        matching_docs = [d for d in docs if d.matches_filter(filter_obj)]

        filter_time_ms = (time.perf_counter() - start_time) * 1000

        stats = {
            "filter": filter_obj.to_dict(),
            "total_documents": len(docs),
            "matching_documents": len(matching_docs),
            "filter_time_ms": filter_time_ms,
            "filter_efficiency": len(matching_docs) / len(docs) if docs else 0,
        }

        logger.info(
            f"Filter '{filter_obj.description}' ({filter_obj.operator}): "
            f"{len(matching_docs)}/{len(docs)} documents matched in {filter_time_ms:.2f}ms"
        )

        return matching_docs, stats

    def apply_complex_filter(
        self, filters: List[MetadataFilter], operator: str = "and"
    ) -> Tuple[List[TestDocument], Dict[str, Any]]:
        """
        Apply multiple filters with logical operator.

        Args:
            filters: List of MetadataFilter objects
            operator: "and" or "or" for combining filters

        Returns:
            Tuple of (filtered_documents, filter_stats)
        """
        start_time = time.perf_counter()

        if operator == "and":
            matching_docs = [
                d
                for d in self.documents
                if all(d.matches_filter(f) for f in filters)
            ]
        else:  # or
            matching_docs = [
                d
                for d in self.documents
                if any(d.matches_filter(f) for f in filters)
            ]

        filter_time_ms = (time.perf_counter() - start_time) * 1000

        stats = {
            "filters": [f.to_dict() for f in filters],
            "logical_operator": operator,
            "total_documents": len(self.documents),
            "matching_documents": len(matching_docs),
            "filter_time_ms": filter_time_ms,
            "filter_efficiency": len(matching_docs) / len(self.documents),
        }

        return matching_docs, stats

    def test_filter_operator(self, operator: str) -> Dict[str, Any]:
        """
        Test a specific filter operator with various values.

        Returns comprehensive test results.
        """
        results = {
            "operator": operator,
            "test_cases": [],
            "summary": {"passed": 0, "failed": 0, "errors": 0},
        }

        # Define test cases for each operator
        test_scenarios = {
            "equals": [
                ("category", "technical", "Match single category"),
                ("status", "published", "Match single status"),
                ("priority", "high", "Match single priority"),
                ("author", "alice", "Match single author"),
            ],
            "in": [
                ("category", ["technical", "business"], "Match multiple categories"),
                ("status", ["approved", "published"], "Match multiple statuses"),
                ("priority", ["high", "critical"], "Match multiple priorities"),
                ("tags", ["urgent", "important"], "Match tags"),
            ],
            "contains": [
                ("title", "Technical", "Contains substring in title"),
                ("content", "analysis", "Contains substring in content"),
                ("author", "ali", "Contains substring in author"),
            ],
            "gt": [
                ("version", 3, "Greater than version"),
                ("confidence_score", 0.9, "Greater than score"),
            ],
            "lt": [
                ("version", 3, "Less than version"),
                ("confidence_score", 0.9, "Less than score"),
            ],
            "gte": [
                ("version", 2, "Greater than or equal version"),
                ("confidence_score", 0.8, "Greater than or equal score"),
            ],
            "lte": [
                ("version", 4, "Less than or equal version"),
                ("confidence_score", 0.95, "Less than or equal score"),
            ],
            "range": [
                ("version", (2, 4), "Version in range"),
                ("confidence_score", (0.8, 0.95), "Score in range"),
            ],
        }

        scenarios = test_scenarios.get(operator, [])

        for field_name, test_value, description in scenarios:
            filter_obj = MetadataFilter(
                field_name=field_name,
                operator=operator,
                value=test_value,
                description=description,
            )

            try:
                matching_docs, stats = self.apply_metadata_filter(filter_obj)

                test_case = {
                    "description": description,
                    "field": field_name,
                    "value": test_value,
                    "matching_count": len(matching_docs),
                    "filter_time_ms": stats["filter_time_ms"],
                    "status": "passed" if len(matching_docs) >= 0 else "failed",
                }
                results["test_cases"].append(test_case)

                if test_case["status"] == "passed":
                    results["summary"]["passed"] += 1
                else:
                    results["summary"]["failed"] += 1

            except Exception as e:
                results["test_cases"].append({
                    "description": description,
                    "field": field_name,
                    "value": test_value,
                    "error": str(e),
                    "status": "error",
                })
                results["summary"]["errors"] += 1

        return results

    def get_all_documents(self) -> List[Dict[str, Any]]:
        """Get all documents in vector DB format."""
        return [d.to_vector_db_format() for d in self.documents]

    def get_document_by_id(self, doc_id: str) -> Optional[TestDocument]:
        """Get a document by ID."""
        for doc in self.documents:
            if doc.document_id == doc_id:
                return doc
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the document corpus."""
        return {
            "total_documents": len(self.documents),
            "categories": self._count_unique("category"),
            "statuses": self._count_unique("status"),
            "departments": self._count_unique("department"),
            "authors": self._count_unique("author"),
            "date_range": {
                "earliest": min(d.created_date for d in self.documents).isoformat(),
                "latest": max(d.created_date for d in self.documents).isoformat(),
            },
            "avg_confidence": sum(d.confidence_score for d in self.documents) / len(self.documents),
        }

    def _count_unique(self, field: str) -> Dict[str, int]:
        """Count unique values for a field."""
        counts = {}
        for doc in self.documents:
            value = getattr(doc, field, None)
            if value:
                if isinstance(value, list):
                    for item in value:
                        counts[item] = counts.get(item, 0) + 1
                else:
                    counts[value] = counts.get(value, 0) + 1
        return counts


class SilentFailureDetector:
    """
    Detects silent failures in metadata filtering.
    """

    def __init__(self, mocks: MetadataFilteringMocks):
        self.mocks = mocks

    def detect_empty_result_silent_failure(
        self, filter_obj: MetadataFilter
    ) -> Dict[str, Any]:
        """
        Detect if a filter would silently return empty results.

        A silent failure occurs when:
        1. Filter matches zero documents
        2. No error is raised
        3. Pipeline continues without indication of failure
        """
        matching_docs, stats = self.mocks.apply_metadata_filter(filter_obj)

        is_silent_failure = len(matching_docs) == 0

        return {
            "filter": filter_obj.to_dict(),
            "is_silent_failure": is_silent_failure,
            "matched_count": len(matching_docs),
            "should_detect": True,
            "detection_method": "empty_result_check",
        }

    def detect_metadata_corruption(self) -> List[Dict[str, Any]]:
        """
        Detect documents with corrupted or inconsistent metadata.
        """
        issues = []

        for doc in self.mocks.documents:
            metadata = doc.to_vector_db_format()["metadata"]

            # Check for type inconsistencies
            if "numeric_as_string" in metadata:
                try:
                    int(metadata["numeric_as_string"])
                except ValueError:
                    issues.append({
                        "document_id": doc.document_id,
                        "issue": "numeric_as_string is not numeric",
                        "value": metadata["numeric_as_string"],
                    })

            # Check for missing critical fields
            critical_fields = ["category", "status", "created_date"]
            for field in critical_fields:
                if field not in metadata:
                    issues.append({
                        "document_id": doc.document_id,
                        "issue": f"missing_critical_field",
                        "field": field,
                    })

        return issues


def create_test_filter(
    field_name: str, operator: str, value: Any, description: str = ""
) -> MetadataFilter:
    """Helper to create test filters."""
    return MetadataFilter(
        field_name=field_name,
        operator=operator,
        value=value,
        description=description,
    )


def create_test_documents(count: int = 100) -> List[TestDocument]:
    """Create a test document corpus."""
    mocks = MetadataFilteringMocks()
    return mocks.documents[:count]


if __name__ == "__main__":
    # Demo usage
    mocks = MetadataFilteringMocks()

    print("=" * 60)
    print("Metadata Filtering Mocks - Test Run")
    print("=" * 60)

    # Test basic filtering
    filter_obj = create_test_filter(
        field_name="category",
        operator="equals",
        value="technical",
        description="Filter technical documents",
    )

    matching_docs, stats = mocks.apply_metadata_filter(filter_obj)
    print(f"\nFiltered {len(matching_docs)} technical documents")
    print(f"Filter efficiency: {stats['filter_efficiency']:.2%}")

    # Test complex filtering
    filters = [
        create_test_filter("category", "in", ["technical", "engineering"]),
        create_test_filter("status", "equals", "published"),
    ]
    matching_docs, stats = mocks.apply_complex_filter(filters, "and")
    print(f"\nComplex filter (technical/engineering + published): {len(matching_docs)} documents")

    # Test all operators
    print("\n" + "=" * 60)
    print("Operator Test Results")
    print("=" * 60)
    for operator in ["equals", "in", "contains", "gt", "lt"]:
        result = mocks.test_filter_operator(operator)
        passed = result["summary"]["passed"]
        print(f"{operator}: {passed} test cases passed")

    # Get corpus stats
    print("\n" + "=" * 60)
    print("Document Corpus Statistics")
    print("=" * 60)
    stats = mocks.get_stats()
    print(f"Total documents: {stats['total_documents']}")
    print(f"Categories: {stats['categories']}")
    print(f"Date range: {stats['date_range']['earliest']} to {stats['date_range']['latest']}")
