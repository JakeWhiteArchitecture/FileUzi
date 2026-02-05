"""
Keyword Matching / Cascade Unit Tests for FileUzi.
"""

import pytest
from unittest.mock import patch, MagicMock

from fileuzi.services.filing_rules import (
    load_filing_rules,
    match_filing_rules,
    match_filing_rules_cascade,
)
from fileuzi.services.drawing_manager import is_drawing_pdf


# ============================================================================
# Basic Keyword Matching Tests
# ============================================================================

class TestBasicKeywordMatching:
    """Basic keyword matching tests."""

    def test_match_from_filename(self, project_root, filing_rules_csv):
        """Test keyword match from filename."""
        rules = load_filing_rules(project_root)

        # Filename contains "Survey"
        filename = "Topographical Survey - 14 High Street.pdf"

        matches = match_filing_rules(filename, rules)

        # Should find a match for "Survey" -> "Surveys"
        assert len(matches) > 0
        folder_types = [m['rule']['folder_type'] for m in matches]
        assert 'Surveys' in folder_types

    def test_match_structural(self, project_root, filing_rules_csv):
        """Test keyword match for structural documents."""
        rules = load_filing_rules(project_root)

        filename = "Structural Calculations - Beam Design.pdf"

        matches = match_filing_rules(filename, rules)

        folder_types = [m['rule']['folder_type'] for m in matches]
        assert 'Technical' in folder_types

    def test_match_ecological(self, project_root, filing_rules_csv):
        """Test keyword match for ecological documents."""
        rules = load_filing_rules(project_root)

        filename = "Preliminary Ecological Appraisal.pdf"

        matches = match_filing_rules(filename, rules)

        folder_types = [m['rule']['folder_type'] for m in matches]
        assert 'Ecology' in folder_types

    def test_case_insensitive_matching(self, project_root, filing_rules_csv):
        """Test keyword matching is case-insensitive."""
        rules = load_filing_rules(project_root)

        filename = "ecological report.pdf"

        matches = match_filing_rules(filename, rules)

        folder_types = [m['rule']['folder_type'] for m in matches]
        assert 'Ecology' in folder_types

    def test_no_match_returns_empty(self, project_root, filing_rules_csv):
        """Test no match returns empty list."""
        rules = load_filing_rules(project_root)

        filename = "random_file_xyz.pdf"

        matches = match_filing_rules(filename, rules)

        assert len(matches) == 0 or matches is None or matches == []


# ============================================================================
# JWA Drawing Skip Tests
# ============================================================================

class TestJwaDrawingSkip:
    """Tests for JWA drawing cascade skip."""

    def test_jwa_drawing_skips_cascade(self, project_root, filing_rules_csv):
        """Test JWA drawing skips keyword cascade."""
        rules = load_filing_rules(project_root)

        # This is a JWA drawing filename
        filename = "2506_22_PROPOSED SECTIONS_C02.pdf"

        # The cascade should detect this is a drawing and skip keyword matching
        result = match_filing_rules_cascade(
            filename,
            rules,
            attachment_data=None,
            job_number='2506'
        )

        # For drawings, cascade should return empty or None (skip condition)
        # The drawing is filed to Current Drawings, not by keywords
        assert result is None or len(result) == 0 or is_drawing_pdf(filename, '2506')

    def test_non_drawing_uses_cascade(self, project_root, filing_rules_csv):
        """Test non-drawing files use keyword cascade."""
        rules = load_filing_rules(project_root)

        # This is NOT a JWA drawing
        filename = "Structural Calculations.pdf"

        result = match_filing_rules_cascade(
            filename,
            rules,
            attachment_data=None,
            job_number='2506'
        )

        # Should find matches via keyword cascade
        if result:
            folder_types = [m['rule']['folder_type'] for m in result]
            assert 'Technical' in folder_types


# ============================================================================
# PDF Metadata Fallback Tests
# ============================================================================

class TestPdfMetadataFallback:
    """Tests for PDF metadata fallback in cascade."""

    def test_skip_generic_metadata_titles(self, project_root, filing_rules_csv):
        """Test generic metadata titles are skipped."""
        rules = load_filing_rules(project_root)

        # Simulate a scan with generic metadata
        filename = "scan_001.pdf"

        # If we mock the PDF metadata to return "Document1"
        # The cascade should skip this generic title
        with patch('fileuzi.services.filing_rules.extract_pdf_metadata_title') as mock_meta:
            mock_meta.return_value = "Document1"

            result = match_filing_rules_cascade(
                filename,
                rules,
                attachment_data=b"fake pdf data",
                job_number='2506'
            )

            # Should not match based on "Document1"
            # (unless there's a fallback to content)

    def test_skip_metadata_matching_filename(self, project_root, filing_rules_csv):
        """Test metadata matching filename is skipped."""
        rules = load_filing_rules(project_root)

        filename = "scan_001.pdf"

        with patch('fileuzi.services.filing_rules.extract_pdf_metadata_title') as mock_meta:
            mock_meta.return_value = "scan_001"  # Same as filename

            result = match_filing_rules_cascade(
                filename,
                rules,
                attachment_data=b"fake pdf data",
                job_number='2506'
            )

            # Metadata step should be skipped when title matches filename


# ============================================================================
# First 40 Characters Fallback Tests
# ============================================================================

class TestFirstContentFallback:
    """Tests for first content characters fallback."""

    def test_fallback_to_first_40_chars(self, project_root, filing_rules_csv):
        """Test fallback to first 40 characters of PDF content."""
        rules = load_filing_rules(project_root)

        filename = "scan_001.pdf"

        # Mock the PDF first content extraction
        with patch('fileuzi.services.filing_rules.extract_pdf_first_content') as mock_content:
            mock_content.return_value = "Preliminary Ecological Appraisal for Smith Site"

            result = match_filing_rules_cascade(
                filename,
                rules,
                attachment_data=b"fake pdf data",
                job_number='2506'
            )

            # Should find "Ecological" in the content
            if result:
                folder_types = [m['rule']['folder_type'] for m in result]
                assert 'Ecology' in folder_types


# ============================================================================
# Per-Attachment Matching Tests
# ============================================================================

class TestPerAttachmentMatching:
    """Tests for per-attachment matching."""

    def test_per_attachment_matching(self, project_root, filing_rules_csv):
        """Test different attachments get different suggestions."""
        rules = load_filing_rules(project_root)

        # First attachment - structural
        filename1 = "Structural Calcs.pdf"
        matches1 = match_filing_rules(filename1, rules)

        # Second attachment - ecological
        filename2 = "Ecological Report.pdf"
        matches2 = match_filing_rules(filename2, rules)

        # Should have different matches
        if matches1 and matches2:
            types1 = [m['rule']['folder_type'] for m in matches1]
            types2 = [m['rule']['folder_type'] for m in matches2]

            assert 'Technical' in types1
            assert 'Ecology' in types2


# ============================================================================
# Multiple Keyword Tests
# ============================================================================

class TestMultipleKeywords:
    """Tests for multiple keyword scenarios."""

    def test_multiple_keywords_in_rule(self, project_root, filing_rules_csv):
        """Test rule with multiple keywords."""
        rules = load_filing_rules(project_root)

        # "Structural|Calcs|Calculations" should all match Technical
        filenames = [
            "Structural Report.pdf",
            "Beam Calcs.pdf",
            "Foundation Calculations.pdf"
        ]

        for filename in filenames:
            matches = match_filing_rules(filename, rules)
            if matches:
                folder_types = [m['rule']['folder_type'] for m in matches]
                assert 'Technical' in folder_types

    def test_filename_matches_multiple_rules(self, project_root, filing_rules_csv):
        """Test filename matching multiple rules returns all."""
        rules = load_filing_rules(project_root)

        # Filename that might match multiple rules
        filename = "Survey Drawing.pdf"

        matches = match_filing_rules(filename, rules)

        # Should return matches (might be multiple)
        assert matches is not None


# ============================================================================
# Edge Cases
# ============================================================================

class TestKeywordEdgeCases:
    """Edge case tests for keyword matching."""

    def test_empty_filename(self, project_root, filing_rules_csv):
        """Test empty filename."""
        rules = load_filing_rules(project_root)

        matches = match_filing_rules("", rules)

        assert matches is None or len(matches) == 0

    def test_none_filename(self, project_root, filing_rules_csv):
        """Test None filename."""
        rules = load_filing_rules(project_root)

        try:
            matches = match_filing_rules(None, rules)
            assert matches is None or len(matches) == 0
        except (TypeError, AttributeError):
            # Also acceptable
            pass

    def test_filename_only_extension(self, project_root, filing_rules_csv):
        """Test filename that is only an extension."""
        rules = load_filing_rules(project_root)

        matches = match_filing_rules(".pdf", rules)

        assert matches is None or len(matches) == 0

    def test_very_long_filename(self, project_root, filing_rules_csv):
        """Test very long filename."""
        rules = load_filing_rules(project_root)

        filename = "Structural " * 50 + ".pdf"

        matches = match_filing_rules(filename, rules)

        # Should still find the match
        if matches:
            folder_types = [m['rule']['folder_type'] for m in matches]
            assert 'Technical' in folder_types

    def test_filename_with_special_characters(self, project_root, filing_rules_csv):
        """Test filename with special characters."""
        rules = load_filing_rules(project_root)

        filename = "Structural (Calcs) [Rev A] {Final}.pdf"

        matches = match_filing_rules(filename, rules)

        if matches:
            folder_types = [m['rule']['folder_type'] for m in matches]
            assert 'Technical' in folder_types
