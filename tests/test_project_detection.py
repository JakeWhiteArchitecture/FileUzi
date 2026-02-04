"""
Project Number Detection Unit Tests for FileUzi.
"""

import pytest
from unittest.mock import patch

from fileuzi.services.job_detector import (
    extract_job_number_from_filename,
    find_job_number_from_path,
    detect_project_from_subject,
    scan_projects_folder,
    parse_folder_name,
)
from fileuzi.services.filing_rules import (
    load_project_mapping,
    apply_project_mapping,
)
from fileuzi.services.pdf_generator import clean_subject_for_filename


# ============================================================================
# Job Number From Subject Tests
# ============================================================================

class TestJobNumberFromSubject:
    """Tests for job number detection from email subjects."""

    def test_detect_job_number_from_subject(self, project_root):
        """Test basic job number detection from subject."""
        known_projects = ['2506', '2407']
        subject = "2506 Smith Extension - Structural Query"

        detected = detect_project_from_subject(subject, known_projects)

        assert detected == '2506'

    def test_detect_job_number_after_RE_prefix(self, project_root):
        """Test job number detection after RE: prefix."""
        known_projects = ['2506', '2407']
        subject = "RE: 2506 Smith Extension - Structural Query"

        detected = detect_project_from_subject(subject, known_projects)

        assert detected == '2506'

    def test_detect_job_number_after_FW_prefix(self, project_root):
        """Test job number detection after FW: prefix."""
        known_projects = ['2506', '2407']
        subject = "FW: 2506 Smith Extension - Drawing Issue"

        detected = detect_project_from_subject(subject, known_projects)

        assert detected == '2506'

    def test_detect_job_number_after_Fwd_prefix(self, project_root):
        """Test job number detection after Fwd: prefix."""
        known_projects = ['2506', '2407']
        subject = "Fwd: 2506 Smith Extension - Drawing Issue"

        detected = detect_project_from_subject(subject, known_projects)

        assert detected == '2506'

    def test_no_project_number_returns_none(self, project_root):
        """Test subject without project number returns None."""
        known_projects = ['2506', '2407']
        subject = "Meeting next Tuesday"

        detected = detect_project_from_subject(subject, known_projects)

        assert detected is None

    def test_unknown_number_returns_none(self, project_root):
        """Test unknown project number returns None."""
        known_projects = ['2506', '2407']
        subject = "9999 Random Project - Update"

        detected = detect_project_from_subject(subject, known_projects)

        assert detected is None

    def test_first_number_used_when_multiple(self, project_root):
        """Test first project number is used when multiple present."""
        known_projects = ['2506', '2407']
        subject = "2506 and 2407 - Combined Query"

        detected = detect_project_from_subject(subject, known_projects)

        assert detected == '2506'


# ============================================================================
# Client Reference Mapping Tests
# ============================================================================

class TestClientReferenceMapping:
    """Tests for client reference to JWA job number mapping."""

    def test_client_reference_mapping(self, project_root, project_mapping_csv):
        """Test client reference maps to JWA job number."""
        mapping = load_project_mapping(project_root)

        # Subject with client reference
        subject = "JB/2024/0847 - Structural Calculations"

        # Apply mapping
        result = apply_project_mapping(subject, mapping)

        # Should find the mapped job number
        assert '2506' in result or result == '2506'

    def test_load_project_mapping(self, project_root, project_mapping_csv):
        """Test loading project mapping from CSV."""
        mapping = load_project_mapping(project_root)

        assert mapping is not None
        assert len(mapping) > 0
        assert 'JB/2024/0847' in mapping or any('JB/2024/0847' in str(k) for k in mapping.keys())


# ============================================================================
# Subject Cleaning Tests
# ============================================================================

class TestSubjectCleaning:
    """Tests for email subject cleaning."""

    def test_subject_cleaning_strips_job_prefix(self):
        """Test subject cleaning removes job number prefix."""
        subject = "2506 Smith Extension - Structural Query Beam Detail"
        job_number = "2506"

        cleaned = clean_subject_for_filename(subject, job_number)

        # Should remove "2506 Smith Extension - " prefix
        assert "2506" not in cleaned or cleaned.startswith("2506") is False
        assert "Structural Query" in cleaned or "Beam Detail" in cleaned

    def test_subject_cleaning_removes_re_prefix(self):
        """Test subject cleaning removes RE: prefix."""
        subject = "RE: 2506 Smith Extension - Query"
        job_number = "2506"

        cleaned = clean_subject_for_filename(subject, job_number)

        assert "RE:" not in cleaned

    def test_subject_cleaning_removes_fw_prefix(self):
        """Test subject cleaning removes FW: prefix."""
        subject = "FW: 2506 Smith Extension - Query"
        job_number = "2506"

        cleaned = clean_subject_for_filename(subject, job_number)

        assert "FW:" not in cleaned

    def test_subject_cleaning_special_characters(self):
        """Test subject cleaning handles special characters."""
        subject = "2506 - Query: Important! [Urgent]"
        job_number = "2506"

        cleaned = clean_subject_for_filename(subject, job_number)

        # Should be safe for filename (no colons, etc.)
        assert ':' not in cleaned or cleaned.count(':') == 0


# ============================================================================
# Job Number From Filename Tests
# ============================================================================

class TestJobNumberFromFilename:
    """Tests for job number extraction from filenames."""

    def test_extract_from_standard_filename(self):
        """Test extraction from standard filename format."""
        filename = "2506_20_FLOOR PLANS_P01.pdf"

        job_number = extract_job_number_from_filename(filename)

        assert job_number == '2506'

    def test_extract_from_old_format(self):
        """Test extraction from old format filename."""
        filename = "2506 - 04A - PROPOSED PLANS.pdf"

        job_number = extract_job_number_from_filename(filename)

        assert job_number == '2506'

    def test_extract_from_generic_filename(self):
        """Test extraction from filename with job number."""
        filename = "2407_Structural_Calcs.pdf"

        job_number = extract_job_number_from_filename(filename)

        assert job_number == '2407'

    def test_no_job_number_in_filename(self):
        """Test filename without job number returns None."""
        filename = "random_document.pdf"

        job_number = extract_job_number_from_filename(filename)

        assert job_number is None


# ============================================================================
# Job Number From Path Tests
# ============================================================================

class TestJobNumberFromPath:
    """Tests for job number extraction from file paths."""

    def test_extract_from_project_folder_path(self, project_root):
        """Test extraction from path containing project folder."""
        file_path = project_root / "2506_SMITH-EXTENSION" / "ADMIN" / "doc.pdf"

        job_number = find_job_number_from_path(str(file_path))

        assert job_number == '2506'

    def test_extract_from_deep_path(self, project_root):
        """Test extraction from deeply nested path."""
        file_path = project_root / "2407_JONES-HOUSE" / "TECHNICAL" / "Surveys" / "topo.pdf"

        job_number = find_job_number_from_path(str(file_path))

        assert job_number == '2407'


# ============================================================================
# Project Folder Scanning Tests
# ============================================================================

class TestProjectFolderScanning:
    """Tests for project folder scanning."""

    def test_scan_projects_folder(self, project_root):
        """Test scanning project folders returns correct list."""
        projects = scan_projects_folder(project_root)

        # Should find both test projects
        job_numbers = [p[0] for p in projects]

        assert '2506' in job_numbers
        assert '2407' in job_numbers

    def test_parse_folder_name_standard(self):
        """Test parsing standard folder name format."""
        folder_name = "2506_SMITH-EXTENSION"

        job_number, project_name = parse_folder_name(folder_name)

        assert job_number == '2506'
        assert 'SMITH' in project_name.upper()

    def test_parse_folder_name_with_spaces(self):
        """Test parsing folder name with spaces."""
        folder_name = "2407_JONES HOUSE"

        job_number, project_name = parse_folder_name(folder_name)

        assert job_number == '2407'

    def test_scan_excludes_tools_folder(self, project_root):
        """Test scanning excludes _FILING-WIDGET-TOOLS folder."""
        projects = scan_projects_folder(project_root)

        job_numbers = [p[0] for p in projects]
        folder_names = [p[1] for p in projects]

        # Tools folder should not be included
        assert '_FILING-WIDGET-TOOLS' not in folder_names
        assert 'FILING' not in job_numbers


# ============================================================================
# Edge Cases
# ============================================================================

class TestProjectDetectionEdgeCases:
    """Edge case tests for project detection."""

    def test_empty_subject(self):
        """Test empty subject returns None."""
        known_projects = ['2506', '2407']

        detected = detect_project_from_subject("", known_projects)

        assert detected is None

    def test_subject_only_numbers(self):
        """Test subject with only numbers (not matching projects)."""
        known_projects = ['2506', '2407']
        subject = "1234567890"

        detected = detect_project_from_subject(subject, known_projects)

        assert detected is None

    def test_three_digit_job_number(self):
        """Test three-digit job numbers are handled."""
        known_projects = ['506', '2407']
        subject = "506 Small Project - Query"

        detected = detect_project_from_subject(subject, known_projects)

        # May or may not match depending on implementation
        # Just ensure no crash

    def test_five_digit_job_number(self):
        """Test five-digit job numbers are handled."""
        known_projects = ['25061', '2407']
        subject = "25061 Large Project - Query"

        detected = detect_project_from_subject(subject, known_projects)

        # May or may not match depending on implementation

    def test_job_number_at_end_of_subject(self):
        """Test job number at end of subject."""
        known_projects = ['2506', '2407']
        subject = "Structural Query for project 2506"

        detected = detect_project_from_subject(subject, known_projects)

        # Should still detect
        assert detected == '2506'

    def test_multiple_re_prefixes(self):
        """Test multiple RE: prefixes."""
        known_projects = ['2506', '2407']
        subject = "RE: RE: RE: 2506 Smith - Query"

        detected = detect_project_from_subject(subject, known_projects)

        assert detected == '2506'
