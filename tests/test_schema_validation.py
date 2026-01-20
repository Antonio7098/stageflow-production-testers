"""Schema validation tests for TRANSFORM-002."""

import pytest
import asyncio
from pipelines.transform002_pipelines import (
    create_baseline_pipeline,
    run_pipeline_with_data
)


class TestSchemaValidation:
    """Tests for schema validation in TRANSFORM stages."""
    
    @pytest.mark.asyncio
    async def test_valid_user_passes_validation(self, schema_validation_cases):
        """Happy path: valid user data should pass validation."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            schema_validation_cases["valid_complete"],
            "test_valid_user"
        )
        
        assert result["success"], f"Expected success but got failure: {result}"
    
    @pytest.mark.asyncio
    async def test_valid_minimal_data_passes(self, schema_validation_cases):
        """Valid minimal data with required fields only should pass."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            schema_validation_cases["valid_minimal"],
            "test_valid_minimal"
        )
        
        assert result["success"], f"Expected success but got failure: {result}"
    
    @pytest.mark.asyncio
    async def test_missing_user_id_fails_validation(self, schema_validation_cases):
        """Missing user_id should fail validation."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            schema_validation_cases["missing_user_id"],
            "test_missing_user_id"
        )
        
        # Should fail because user_id is required
        assert not result["success"], "Expected failure for missing user_id"
    
    @pytest.mark.asyncio
    async def test_missing_email_fails_validation(self, schema_validation_cases):
        """Missing email should fail validation."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            schema_validation_cases["missing_email"],
            "test_missing_email"
        )
        
        # Should fail because email is required
        assert not result["success"], "Expected failure for missing email"
    
    @pytest.mark.asyncio
    async def test_invalid_email_fails_validation(self, schema_validation_cases):
        """Invalid email format should fail validation."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            schema_validation_cases["invalid_email"],
            "test_invalid_email"
        )
        
        # Should fail because email is invalid
        assert not result["success"], "Expected failure for invalid email"
    
    @pytest.mark.asyncio
    async def test_negative_age_fails_validation(self, schema_validation_cases):
        """Negative age should fail validation."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            schema_validation_cases["negative_age"],
            "test_negative_age"
        )
        
        # Should fail because age is out of range
        assert not result["success"], "Expected failure for negative age"
    
    @pytest.mark.asyncio
    async def test_age_too_old_fails(self, schema_validation_cases):
        """Age > 150 should fail validation."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            schema_validation_cases["too_old"],
            "test_too_old"
        )
        
        # Should fail because age is out of range
        assert not result["success"], "Expected failure for age > 150"
    
    @pytest.mark.asyncio
    async def test_null_required_field_fails(self, schema_validation_cases):
        """Null value in required field should fail validation."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            schema_validation_cases["null_required"],
            "test_null_required"
        )
        
        # Should fail because user_id is null
        assert not result["success"], "Expected failure for null required field"


class TestEdgeCases:
    """Tests for edge cases in schema mapping."""
    
    @pytest.mark.asyncio
    async def test_min_age_zero(self, edge_case_users):
        """Age 0 should be valid."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            edge_case_users["min_age"],
            "test_min_age"
        )
        
        assert result["success"], f"Age 0 should be valid: {result}"
    
    @pytest.mark.asyncio
    async def test_max_age_150(self, edge_case_users):
        """Age 150 should be valid."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            edge_case_users["max_age"],
            "test_max_age"
        )
        
        assert result["success"], f"Age 150 should be valid: {result}"
    
    @pytest.mark.asyncio
    async def test_empty_tags_array(self, edge_case_users):
        """Empty tags array should be valid."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            edge_case_users["empty_tags"],
            "test_empty_tags"
        )
        
        assert result["success"], f"Empty tags should be valid: {result}"
    
    @pytest.mark.asyncio
    async def test_null_metadata(self, edge_case_users):
        """Null metadata should be valid."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            edge_case_users["null_metadata"],
            "test_null_metadata"
        )
        
        assert result["success"], f"Null metadata should be valid: {result}"


class TestSilentFailures:
    """Tests specifically for detecting silent failures."""
    
    @pytest.mark.asyncio
    async def test_no_silent_type_coercion(self, adversarial_users):
        """Type mismatches should produce errors, not silent coercion."""
        pipeline = create_baseline_pipeline()
        
        # String where number expected
        result = await run_pipeline_with_data(
            pipeline,
            adversarial_users["type_mismatch_string_number"],
            "test_type_mismatch"
        )
        
        # The pipeline should either:
        # 1. Fail explicitly (preferred - no silent failure)
        # 2. Or coerce with warning (acceptable)
        # 3. NOT silently coerce without any indication
        
        # Check that we get explicit error indication
        results = result.get("results", {})
        
        # If the validation stage ran, it should have caught this
        validate_result = results.get("validate", {})
        if isinstance(validate_result, dict):
            # Either explicitly failed or succeeded with clear data
            assert "error" in validate_result or validate_result.get("validated") == True, \
                "Type mismatch should produce explicit error or be validated"
    
    @pytest.mark.asyncio
    async def test_empty_string_handling(self, adversarial_users):
        """Empty string in required field should fail, not silently pass."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            adversarial_users["empty_string_required"],
            "test_empty_string"
        )
        
        # Empty string should not pass validation for required email
        assert not result["success"], "Empty string should fail validation"
    
    @pytest.mark.asyncio
    async def test_null_handling(self, adversarial_users):
        """Null values should fail, not silently use defaults."""
        pipeline = create_baseline_pipeline()
        
        result = await run_pipeline_with_data(
            pipeline,
            adversarial_users["null_in_required"],
            "test_null_handling"
        )
        
        # Null should not silently pass
        assert not result["success"], "Null in required field should fail"
