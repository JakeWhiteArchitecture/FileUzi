"""
Superseding Filesystem Integration Tests for FileUzi.
"""

import pytest
from pathlib import Path
import shutil

from fileuzi.services.drawing_manager import supersede_drawings, is_current_drawings_folder


def _create_fake_pdf(path, size_kb=10):
    """Create a fake PDF file at the given path."""
    pdf_content = b"%PDF-1.4\n" + b" " * (size_kb * 1024 - 10) + b"\n%%EOF"
    path.write_bytes(pdf_content)


# ============================================================================
# Basic Superseding Tests
# ============================================================================

class TestSupersedingBasics:
    """Basic superseding functionality tests."""

    def test_supersede_moves_old_to_subfolder(self, project_root):
        """Test superseding moves old revision to Superseded folder."""
        current_drawings = project_root / "2506_SMITH-EXTENSION" / "Current Drawings"

        # Create old revision
        old_file = current_drawings / "2506_20_FLOOR PLANS_P02.pdf"
        _create_fake_pdf(old_file)

        # Create new revision file (to be filed)
        new_file_path = project_root / "incoming" / "2506_20_FLOOR PLANS_W01.pdf"
        new_file_path.parent.mkdir(exist_ok=True)
        _create_fake_pdf(new_file_path)

        # Perform superseding
        supersede_drawings(current_drawings, new_file_path, project_root)

        # Assert old file moved to Superseded
        superseded_folder = current_drawings / "Superseded"
        assert (superseded_folder / "2506_20_FLOOR PLANS_P02.pdf").exists()

        # Assert old file no longer in Current Drawings
        assert not old_file.exists()

    def test_supersede_creates_superseded_folder(self, project_root):
        """Test superseding creates Superseded folder if it doesn't exist."""
        current_drawings = project_root / "2407_JONES-HOUSE" / "Current Drawings"

        # Remove Superseded folder if it exists
        superseded = current_drawings / "Superseded"
        if superseded.exists():
            shutil.rmtree(superseded)

        # Create old revision
        old_file = current_drawings / "2407_10_SITE PLAN_P01.pdf"
        _create_fake_pdf(old_file)

        # Create new revision file
        new_file_path = project_root / "incoming" / "2407_10_SITE PLAN_P02.pdf"
        new_file_path.parent.mkdir(exist_ok=True)
        _create_fake_pdf(new_file_path)

        # Perform superseding
        supersede_drawings(current_drawings, new_file_path, project_root)

        # Assert Superseded folder was created
        assert superseded.exists()

    def test_supersede_multiple_old_revisions(self, project_root):
        """Test superseding moves all old revisions."""
        current_drawings = project_root / "2506_SMITH-EXTENSION" / "Current Drawings"

        # Create multiple old revisions
        p01 = current_drawings / "2506_20_FLOOR PLANS_P01.pdf"
        p02 = current_drawings / "2506_20_FLOOR PLANS_P02.pdf"
        _create_fake_pdf(p01)
        _create_fake_pdf(p02)

        # Create new revision file
        new_file_path = project_root / "incoming" / "2506_20_FLOOR PLANS_W01.pdf"
        new_file_path.parent.mkdir(exist_ok=True)
        _create_fake_pdf(new_file_path)

        # Perform superseding
        supersede_drawings(current_drawings, new_file_path, project_root)

        # Assert both old files moved to Superseded
        superseded_folder = current_drawings / "Superseded"
        assert (superseded_folder / "2506_20_FLOOR PLANS_P01.pdf").exists()
        assert (superseded_folder / "2506_20_FLOOR PLANS_P02.pdf").exists()

        # Assert old files no longer in Current Drawings
        assert not p01.exists()
        assert not p02.exists()


# ============================================================================
# Cross-Format Superseding Tests
# ============================================================================

class TestCrossFormatSuperseding:
    """Tests for superseding across old and new formats."""

    def test_supersede_cross_format(self, project_root):
        """Test new format supersedes old format."""
        current_drawings = project_root / "2506_SMITH-EXTENSION" / "Current Drawings"

        # Create old format file
        old_file = current_drawings / "2506 - 04A - PROPOSED PLANS AND ELEVATIONS.pdf"
        _create_fake_pdf(old_file)

        # Create new format file
        new_file_path = project_root / "incoming" / "2506_04_PROPOSED PLANS AND ELEVATIONS_P01.pdf"
        new_file_path.parent.mkdir(exist_ok=True)
        _create_fake_pdf(new_file_path)

        # Perform superseding
        supersede_drawings(current_drawings, new_file_path, project_root)

        # Assert old format file moved to Superseded
        superseded_folder = current_drawings / "Superseded"
        assert (superseded_folder / "2506 - 04A - PROPOSED PLANS AND ELEVATIONS.pdf").exists()


# ============================================================================
# Edge Cases
# ============================================================================

class TestSupersedingEdgeCases:
    """Edge case tests for superseding."""

    def test_unrecognised_filename_no_superseding(self, project_root):
        """Test unrecognised filenames don't trigger superseding."""
        current_drawings = project_root / "2506_SMITH-EXTENSION" / "Current Drawings"

        # Create a random document
        random_doc = current_drawings / "random_document.pdf"
        _create_fake_pdf(random_doc)

        # Create another random document to "file"
        new_file_path = project_root / "incoming" / "another_random.pdf"
        new_file_path.parent.mkdir(exist_ok=True)
        _create_fake_pdf(new_file_path)

        # Perform superseding (should not move anything)
        supersede_drawings(current_drawings, new_file_path, project_root)

        # Assert random_document is still in place
        assert random_doc.exists()

        # Assert Superseded folder is empty or contains nothing new
        superseded_folder = current_drawings / "Superseded"
        if superseded_folder.exists():
            assert not (superseded_folder / "random_document.pdf").exists()

    def test_supersede_doesnt_rename_old_file(self, project_root):
        """Test superseded files keep their original names."""
        current_drawings = project_root / "2506_SMITH-EXTENSION" / "Current Drawings"

        # Create old revision with specific name
        original_name = "2506_20_FLOOR PLANS_P02.pdf"
        old_file = current_drawings / original_name
        _create_fake_pdf(old_file)

        # Create new revision file
        new_file_path = project_root / "incoming" / "2506_20_FLOOR PLANS_W01.pdf"
        new_file_path.parent.mkdir(exist_ok=True)
        _create_fake_pdf(new_file_path)

        # Perform superseding
        supersede_drawings(current_drawings, new_file_path, project_root)

        # Assert file in Superseded has exact same name
        superseded_folder = current_drawings / "Superseded"
        assert (superseded_folder / original_name).exists()

    def test_no_superseding_when_no_match(self, project_root):
        """Test no superseding when drawing numbers don't match."""
        current_drawings = project_root / "2506_SMITH-EXTENSION" / "Current Drawings"

        # Create drawing 20
        drawing_20 = current_drawings / "2506_20_FLOOR PLANS_P02.pdf"
        _create_fake_pdf(drawing_20)

        # File drawing 22 (different drawing number)
        new_file_path = project_root / "incoming" / "2506_22_SECTIONS_P01.pdf"
        new_file_path.parent.mkdir(exist_ok=True)
        _create_fake_pdf(new_file_path)

        # Perform superseding
        supersede_drawings(current_drawings, new_file_path, project_root)

        # Assert drawing 20 is NOT moved (different drawing)
        assert drawing_20.exists()

    def test_no_superseding_when_job_doesnt_match(self, project_root):
        """Test no superseding when job numbers don't match."""
        current_drawings = project_root / "2506_SMITH-EXTENSION" / "Current Drawings"

        # Create drawing for job 2506
        old_drawing = current_drawings / "2506_20_FLOOR PLANS_P02.pdf"
        _create_fake_pdf(old_drawing)

        # File drawing for job 2407 (different job)
        new_file_path = project_root / "incoming" / "2407_20_FLOOR PLANS_P01.pdf"
        new_file_path.parent.mkdir(exist_ok=True)
        _create_fake_pdf(new_file_path)

        # Perform superseding
        supersede_drawings(current_drawings, new_file_path, project_root)

        # Assert job 2506 drawing is NOT moved
        assert old_drawing.exists()


# ============================================================================
# Folder Detection Tests
# ============================================================================

class TestCurrentDrawingsDetection:
    """Tests for Current Drawings folder detection."""

    def test_is_current_drawings_folder_standard_name(self, project_root):
        """Test detection of standard Current Drawings folder."""
        current_drawings = project_root / "2506_SMITH-EXTENSION" / "Current Drawings"

        assert is_current_drawings_folder(current_drawings) is True

    def test_is_current_drawings_folder_with_job_prefix(self, tmp_path):
        """Test detection with job number prefix."""
        folder = tmp_path / "2506_CURRENT-DRAWINGS"
        folder.mkdir()

        assert is_current_drawings_folder(folder) is True

    def test_not_current_drawings_folder(self, project_root):
        """Test non-Current-Drawings folders are not detected."""
        admin_folder = project_root / "2506_SMITH-EXTENSION" / "ADMIN"

        assert is_current_drawings_folder(admin_folder) is False

    def test_technical_folder_not_current_drawings(self, project_root):
        """Test TECHNICAL folder is not detected as Current Drawings."""
        technical = project_root / "2506_SMITH-EXTENSION" / "TECHNICAL"

        assert is_current_drawings_folder(technical) is False
