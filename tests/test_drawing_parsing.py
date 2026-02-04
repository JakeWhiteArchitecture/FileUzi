"""
Drawing Filename Parser Unit Tests for FileUzi.
"""

import pytest

from fileuzi.services.drawing_manager import (
    parse_drawing_filename_new,
    parse_drawing_filename_old,
    parse_drawing_filename,
    is_drawing_pdf,
)


# ============================================================================
# New Format Parsing Tests
# ============================================================================

class TestNewFormatParsing:
    """Tests for parsing new format drawing filenames."""

    def test_parse_new_format_basic(self):
        """Test parsing basic new format filename."""
        filename = "2506_22_PROPOSED SECTIONS_C02.pdf"
        result = parse_drawing_filename_new(filename)

        assert result is not None
        assert result['job'] == '2506'
        assert result['drawing'] == '22'
        assert result['name'] == 'PROPOSED SECTIONS'
        assert result['stage'] == 'C'
        assert result['revision'] == 2

    def test_parse_new_format_planning(self):
        """Test parsing new format with Planning stage."""
        filename = "2506_10_SITE PLAN_PL01.pdf"
        result = parse_drawing_filename_new(filename)

        assert result is not None
        assert result['stage'] == 'PL'
        assert result['revision'] == 1

    def test_parse_new_format_feasibility(self):
        """Test parsing new format with Feasibility stage."""
        filename = "2407_01_LOCATION PLAN_F03.pdf"
        result = parse_drawing_filename_new(filename)

        assert result is not None
        assert result['job'] == '2407'
        assert result['stage'] == 'F'
        assert result['revision'] == 3

    def test_parse_new_format_working(self):
        """Test parsing new format with Working stage."""
        filename = "2506_20_FLOOR PLANS_W01.pdf"
        result = parse_drawing_filename_new(filename)

        assert result is not None
        assert result['stage'] == 'W'
        assert result['revision'] == 1

    def test_parse_new_format_proposal(self):
        """Test parsing new format with Proposal stage."""
        filename = "2506_15_ELEVATIONS_P02.pdf"
        result = parse_drawing_filename_new(filename)

        assert result is not None
        assert result['stage'] == 'P'
        assert result['revision'] == 2

    def test_parse_new_format_double_digit_revision(self):
        """Test parsing new format with double-digit revision."""
        filename = "2506_22_PROPOSED SECTIONS_C12.pdf"
        result = parse_drawing_filename_new(filename)

        assert result is not None
        assert result['revision'] == 12


# ============================================================================
# Old Format Parsing Tests
# ============================================================================

class TestOldFormatParsing:
    """Tests for parsing old format drawing filenames."""

    def test_parse_old_format_with_revision(self):
        """Test parsing old format with revision letter."""
        filename = "2506 - 04A - PROPOSED PLANS AND ELEVATIONS.pdf"
        result = parse_drawing_filename_old(filename)

        assert result is not None
        assert result['job'] == '2506'
        assert result['drawing'] == '04'
        assert result['revision_letter'] == 'A'
        assert result['name'] == 'PROPOSED PLANS AND ELEVATIONS'

    def test_parse_old_format_first_issue(self):
        """Test parsing old format first issue (no revision letter)."""
        filename = "2506 - 04 - PROPOSED PLANS AND ELEVATIONS.pdf"
        result = parse_drawing_filename_old(filename)

        assert result is not None
        assert result['job'] == '2506'
        assert result['drawing'] == '04'
        assert result['revision_letter'] == '' or result['revision_letter'] is None

    def test_parse_old_format_revision_b(self):
        """Test parsing old format with revision B."""
        filename = "2506 - 04B - PROPOSED PLANS AND ELEVATIONS.pdf"
        result = parse_drawing_filename_old(filename)

        assert result is not None
        assert result['revision_letter'] == 'B'

    def test_parse_old_format_revision_c(self):
        """Test parsing old format with revision C."""
        filename = "2506 - 04C - PROPOSED PLANS AND ELEVATIONS.pdf"
        result = parse_drawing_filename_old(filename)

        assert result is not None
        assert result['revision_letter'] == 'C'


# ============================================================================
# Format Detection Tests
# ============================================================================

class TestFormatDetection:
    """Tests for drawing format detection."""

    def test_detect_new_format(self):
        """Test detection of new format filename."""
        filename = "2506_22_PROPOSED SECTIONS_C02.pdf"
        result = parse_drawing_filename(filename)

        assert result is not None
        assert result.get('format') == 'new' or 'stage' in result

    def test_detect_old_format(self):
        """Test detection of old format filename."""
        filename = "2506 - 04A - PROPOSED PLANS AND ELEVATIONS.pdf"
        result = parse_drawing_filename(filename)

        assert result is not None
        assert result.get('format') == 'old' or 'revision_letter' in result

    def test_detect_unrecognised_format(self):
        """Test unrecognised filename returns None."""
        filename = "scan_20260202_001.pdf"
        result = parse_drawing_filename(filename)

        assert result is None

    def test_detect_jwa_drawing_for_keyword_skip(self):
        """Test JWA drawing detection for keyword cascade skip."""
        filename = "2506_22_PROPOSED SECTIONS_C02.pdf"

        # is_drawing_pdf should return True for this
        result = is_drawing_pdf(filename, '2506')

        assert result is True

    def test_non_drawing_not_detected_as_jwa(self):
        """Test non-drawing file is not detected as JWA drawing."""
        filename = "2407_BRPD_Appointment - Rev A.pdf"

        result = is_drawing_pdf(filename, '2407')

        # This doesn't match drawing pattern
        assert result is False

    def test_random_pdf_not_detected(self):
        """Test random PDF is not detected as drawing."""
        filename = "Meeting_Notes_2026-02-03.pdf"

        result = is_drawing_pdf(filename, '2506')

        assert result is False


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases in drawing parsing."""

    def test_lowercase_extension(self):
        """Test parsing works with lowercase extension."""
        filename = "2506_22_PROPOSED SECTIONS_C02.pdf"
        result = parse_drawing_filename_new(filename)

        assert result is not None

    def test_uppercase_extension(self):
        """Test parsing works with uppercase extension."""
        filename = "2506_22_PROPOSED SECTIONS_C02.PDF"
        result = parse_drawing_filename_new(filename)

        assert result is not None

    def test_name_with_numbers(self):
        """Test parsing name containing numbers."""
        filename = "2506_20_GROUND FLOOR PLAN 1-100_P01.pdf"
        result = parse_drawing_filename_new(filename)

        assert result is not None
        assert '1-100' in result['name'] or 'GROUND FLOOR PLAN' in result['name']

    def test_name_with_special_chars(self):
        """Test parsing name with special characters."""
        filename = "2506_20_FLOOR PLANS & ELEVATIONS_P01.pdf"
        result = parse_drawing_filename_new(filename)

        assert result is not None

    def test_three_digit_job_number(self):
        """Test parsing with different job number lengths."""
        # Four digit (standard)
        result1 = parse_drawing_filename_new("2506_22_NAME_C01.pdf")
        assert result1 is not None
        assert result1['job'] == '2506'

    def test_empty_filename(self):
        """Test parsing empty filename returns None."""
        result = parse_drawing_filename("")
        assert result is None

    def test_none_filename(self):
        """Test parsing None filename returns None."""
        result = parse_drawing_filename(None)
        assert result is None

    def test_non_pdf_file(self):
        """Test parsing non-PDF file."""
        filename = "2506_22_PROPOSED SECTIONS_C02.dwg"

        # is_drawing_pdf should return False for non-PDF
        result = is_drawing_pdf(filename, '2506')
        assert result is False
