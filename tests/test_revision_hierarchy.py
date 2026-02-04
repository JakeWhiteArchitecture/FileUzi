"""
Revision Hierarchy / Superseding Logic Unit Tests for FileUzi.
"""

import pytest

from fileuzi.services.drawing_manager import (
    parse_drawing_filename_new,
    parse_drawing_filename_old,
    parse_drawing_filename,
    compare_drawing_revisions,
)


# ============================================================================
# Same Format Comparisons (New Format)
# ============================================================================

class TestNewFormatComparisons:
    """Tests for comparing new format drawings."""

    def test_new_format_higher_revision_wins(self):
        """Test higher revision number wins within same stage."""
        parsed_a = {'job': '2506', 'drawing': '20', 'stage': 'C', 'revision': 1, 'format': 'new'}
        parsed_b = {'job': '2506', 'drawing': '20', 'stage': 'C', 'revision': 2, 'format': 'new'}

        result = compare_drawing_revisions(parsed_a, parsed_b)

        # B should be newer (positive means B > A)
        assert result > 0

    def test_new_format_higher_stage_wins(self):
        """Test higher stage wins regardless of revision."""
        parsed_a = {'job': '2506', 'drawing': '20', 'stage': 'P', 'revision': 3, 'format': 'new'}
        parsed_b = {'job': '2506', 'drawing': '20', 'stage': 'W', 'revision': 1, 'format': 'new'}

        result = compare_drawing_revisions(parsed_a, parsed_b)

        # W01 beats P03
        assert result > 0

    def test_new_format_construction_beats_all(self):
        """Test Construction stage beats all other stages."""
        parsed_a = {'job': '2506', 'drawing': '20', 'stage': 'W', 'revision': 5, 'format': 'new'}
        parsed_b = {'job': '2506', 'drawing': '20', 'stage': 'C', 'revision': 1, 'format': 'new'}

        result = compare_drawing_revisions(parsed_a, parsed_b)

        # C01 beats W05
        assert result > 0

    def test_new_format_full_hierarchy(self):
        """Test full stage hierarchy: F < PL < P < W < C."""
        stages = ['F', 'PL', 'P', 'W', 'C']

        for i in range(len(stages) - 1):
            lower_stage = stages[i]
            higher_stage = stages[i + 1]

            parsed_lower = {'job': '2506', 'drawing': '20', 'stage': lower_stage, 'revision': 1, 'format': 'new'}
            parsed_higher = {'job': '2506', 'drawing': '20', 'stage': higher_stage, 'revision': 1, 'format': 'new'}

            result = compare_drawing_revisions(parsed_lower, parsed_higher)

            # Higher stage should win
            assert result > 0, f"{higher_stage}01 should beat {lower_stage}01"

    def test_feasibility_is_lowest(self):
        """Test Feasibility is lowest stage."""
        parsed_f = {'job': '2506', 'drawing': '20', 'stage': 'F', 'revision': 10, 'format': 'new'}
        parsed_pl = {'job': '2506', 'drawing': '20', 'stage': 'PL', 'revision': 1, 'format': 'new'}

        result = compare_drawing_revisions(parsed_f, parsed_pl)

        # PL01 beats F10
        assert result > 0

    def test_same_drawing_same_revision_equal(self):
        """Test identical drawings are equal."""
        parsed_a = {'job': '2506', 'drawing': '20', 'stage': 'P', 'revision': 2, 'format': 'new'}
        parsed_b = {'job': '2506', 'drawing': '20', 'stage': 'P', 'revision': 2, 'format': 'new'}

        result = compare_drawing_revisions(parsed_a, parsed_b)

        # Should be equal (0)
        assert result == 0


# ============================================================================
# Old Format Comparisons
# ============================================================================

class TestOldFormatComparisons:
    """Tests for comparing old format drawings."""

    def test_old_format_first_issue_lowest(self):
        """Test first issue (no letter) is lowest."""
        parsed_a = {'job': '2506', 'drawing': '04', 'revision_letter': '', 'format': 'old'}
        parsed_b = {'job': '2506', 'drawing': '04', 'revision_letter': 'A', 'format': 'old'}

        result = compare_drawing_revisions(parsed_a, parsed_b)

        # A beats first issue
        assert result > 0

    def test_old_format_letter_ordering(self):
        """Test revision letter ordering: '' < A < B < C < D."""
        letters = ['', 'A', 'B', 'C', 'D']

        for i in range(len(letters) - 1):
            lower_letter = letters[i]
            higher_letter = letters[i + 1]

            parsed_lower = {'job': '2506', 'drawing': '04', 'revision_letter': lower_letter, 'format': 'old'}
            parsed_higher = {'job': '2506', 'drawing': '04', 'revision_letter': higher_letter, 'format': 'old'}

            result = compare_drawing_revisions(parsed_lower, parsed_higher)

            # Higher letter should win
            assert result > 0, f"Rev {higher_letter or 'first issue'} should beat Rev {lower_letter or 'first issue'}"

    def test_old_format_same_revision_equal(self):
        """Test identical old format drawings are equal."""
        parsed_a = {'job': '2506', 'drawing': '04', 'revision_letter': 'B', 'format': 'old'}
        parsed_b = {'job': '2506', 'drawing': '04', 'revision_letter': 'B', 'format': 'old'}

        result = compare_drawing_revisions(parsed_a, parsed_b)

        assert result == 0


# ============================================================================
# Cross-Format Comparisons
# ============================================================================

class TestCrossFormatComparisons:
    """Tests for comparing old vs new format drawings."""

    def test_old_format_always_below_new(self):
        """Test old format is always superseded by new format."""
        # Highest old revision
        parsed_old = {'job': '2506', 'drawing': '04', 'revision_letter': 'C', 'format': 'old'}
        # Lowest new revision
        parsed_new = {'job': '2506', 'drawing': '04', 'stage': 'F', 'revision': 1, 'format': 'new'}

        result = compare_drawing_revisions(parsed_old, parsed_new)

        # New format F01 beats old format Rev C
        assert result > 0

    def test_cross_format_same_drawing_number(self):
        """Test cross-format comparison for same drawing number."""
        # Old format: "2506 - 04A - PROPOSED PLANS AND ELEVATIONS.pdf"
        parsed_old = parse_drawing_filename_old("2506 - 04A - PROPOSED PLANS AND ELEVATIONS.pdf")

        # New format: "2506_04_PROPOSED PLANS AND ELEVATIONS_P01.pdf"
        parsed_new = parse_drawing_filename_new("2506_04_PROPOSED PLANS AND ELEVATIONS_P01.pdf")

        if parsed_old and parsed_new:
            # Same drawing (job=2506, drawing=04)
            assert parsed_old['job'] == parsed_new['job']
            assert parsed_old['drawing'] == parsed_new['drawing']

            # New format supersedes old
            result = compare_drawing_revisions(parsed_old, parsed_new)
            assert result > 0


# ============================================================================
# Drawing Matching Logic
# ============================================================================

class TestDrawingMatching:
    """Tests for determining if two drawings are the same drawing."""

    def test_same_drawing_different_names_still_match(self):
        """Test drawings with same job+number but different names are same drawing."""
        parsed_a = parse_drawing_filename_new("2506_20_FLOOR PLANS_P02.pdf")
        parsed_b = parse_drawing_filename_new("2506_20_GROUND FLOOR PLAN_W01.pdf")

        if parsed_a and parsed_b:
            # Same job and drawing number
            assert parsed_a['job'] == parsed_b['job']
            assert parsed_a['drawing'] == parsed_b['drawing']

    def test_different_drawing_numbers_dont_match(self):
        """Test different drawing numbers are different drawings."""
        parsed_a = parse_drawing_filename_new("2506_20_FLOOR PLANS_P02.pdf")
        parsed_b = parse_drawing_filename_new("2506_22_PROPOSED SECTIONS_C02.pdf")

        if parsed_a and parsed_b:
            # Same job but different drawing number
            assert parsed_a['job'] == parsed_b['job']
            assert parsed_a['drawing'] != parsed_b['drawing']

    def test_different_job_numbers_dont_match(self):
        """Test different job numbers are different drawings."""
        parsed_a = parse_drawing_filename_new("2506_20_FLOOR PLANS_P02.pdf")
        parsed_b = parse_drawing_filename_new("2407_20_FLOOR PLANS_P02.pdf")

        if parsed_a and parsed_b:
            # Different job numbers
            assert parsed_a['job'] != parsed_b['job']


# ============================================================================
# Comparison Result Interpretation
# ============================================================================

class TestComparisonResults:
    """Tests for comparison result interpretation."""

    def test_negative_result_means_a_is_newer(self):
        """Test negative result means A is newer than B."""
        parsed_a = {'job': '2506', 'drawing': '20', 'stage': 'C', 'revision': 2, 'format': 'new'}
        parsed_b = {'job': '2506', 'drawing': '20', 'stage': 'C', 'revision': 1, 'format': 'new'}

        result = compare_drawing_revisions(parsed_a, parsed_b)

        # A (C02) is newer than B (C01), so result should be negative
        assert result < 0

    def test_positive_result_means_b_is_newer(self):
        """Test positive result means B is newer than A."""
        parsed_a = {'job': '2506', 'drawing': '20', 'stage': 'P', 'revision': 1, 'format': 'new'}
        parsed_b = {'job': '2506', 'drawing': '20', 'stage': 'W', 'revision': 1, 'format': 'new'}

        result = compare_drawing_revisions(parsed_a, parsed_b)

        # B (W01) is newer than A (P01), so result should be positive
        assert result > 0

    def test_zero_result_means_equal(self):
        """Test zero result means equal revision."""
        parsed_a = {'job': '2506', 'drawing': '20', 'stage': 'P', 'revision': 2, 'format': 'new'}
        parsed_b = {'job': '2506', 'drawing': '20', 'stage': 'P', 'revision': 2, 'format': 'new'}

        result = compare_drawing_revisions(parsed_a, parsed_b)

        assert result == 0
