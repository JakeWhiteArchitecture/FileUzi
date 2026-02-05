"""
Safe File Replacement with Automatic Superseding Tests for FileUzi.

Tests the replace_with_supersede() function and related dialog changes.
"""

import os
import pytest
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

from fileuzi.services.filing_operations import replace_with_supersede
from fileuzi.utils.exceptions import PathJailViolation, CircuitBreakerTripped
from fileuzi.utils.circuit_breaker import FileOperationCounter


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def project_tree(tmp_path):
    """Create a realistic project tree for testing."""
    root = tmp_path / "JWA_PROJECTS"
    root.mkdir()

    proj = root / "2506_SMITH-EXTENSION"
    proj.mkdir()
    (proj / "ADMIN").mkdir()
    current = proj / "Current Drawings"
    current.mkdir()
    (proj / "TECHNICAL").mkdir()
    (proj / "IMPORTS-EXPORTS").mkdir()

    # Tools folder
    tools = root / "*FILING-WIDGET-TOOLS*"
    tools.mkdir()

    return root


@pytest.fixture
def old_file(project_tree):
    """Create an existing file that will be replaced."""
    path = project_tree / "2506_SMITH-EXTENSION" / "TECHNICAL" / "report.pdf"
    path.write_bytes(b"OLD FILE CONTENT - " + b"x" * 100)
    return path


@pytest.fixture
def new_source_file(tmp_path):
    """Create a new source file for replacement."""
    path = tmp_path / "new_report.pdf"
    path.write_bytes(b"NEW FILE CONTENT - " + b"y" * 200)
    return path


@pytest.fixture
def circuit_breaker():
    """Create a fresh circuit breaker for testing."""
    cb = FileOperationCounter()
    cb.reset()
    return cb


# ============================================================================
# Unit Tests: replace_with_supersede
# ============================================================================

class TestReplaceCreatesSupersededFolder:
    """Test 1: Superseded folder is created when it doesn't exist."""

    def test_replace_creates_superseded_folder(self, project_tree, old_file,
                                                new_source_file, circuit_breaker):
        superseded_dir = old_file.parent / "Superseded"
        assert not superseded_dir.exists()

        replace_with_supersede(
            old_path=old_file,
            project_root=project_tree,
            circuit_breaker=circuit_breaker,
            new_file_source=new_source_file,
        )

        assert superseded_dir.exists()
        assert superseded_dir.is_dir()


class TestReplaceCopiesOldToSuperseded:
    """Test 2: Old file is copied to Superseded folder."""

    def test_replace_copies_to_superseded(self, project_tree, old_file,
                                           new_source_file, circuit_breaker):
        old_content = old_file.read_bytes()

        superseded_path = replace_with_supersede(
            old_path=old_file,
            project_root=project_tree,
            circuit_breaker=circuit_breaker,
            new_file_source=new_source_file,
        )

        assert superseded_path.exists()
        assert superseded_path.read_bytes() == old_content
        assert superseded_path.parent.name == "Superseded"


class TestReplaceVerifiesCopySize:
    """Test 3: Copy verification catches size mismatches."""

    def test_replace_verifies_copy_size(self, project_tree, old_file,
                                         new_source_file, circuit_breaker):
        """When copy produces wrong size, operation aborts with error."""
        original_copy2 = shutil.copy2

        def bad_copy(src, dst):
            """Simulate a partial copy by writing truncated data."""
            original_copy2(src, dst)
            # Corrupt the copy to simulate partial write
            Path(dst).write_bytes(b"short")

        with patch('fileuzi.services.filing_operations.shutil.copy2', side_effect=bad_copy):
            with pytest.raises(ValueError, match="verification failed"):
                replace_with_supersede(
                    old_path=old_file,
                    project_root=project_tree,
                    circuit_breaker=circuit_breaker,
                    new_file_source=new_source_file,
                )

        # Old file should still be intact (we didn't get to step 6)
        assert old_file.exists()


class TestReplaceWritesNewFile:
    """Test 4: New file is written to the original location."""

    def test_replace_writes_new_file(self, project_tree, old_file,
                                      new_source_file, circuit_breaker):
        new_content = new_source_file.read_bytes()

        replace_with_supersede(
            old_path=old_file,
            project_root=project_tree,
            circuit_breaker=circuit_breaker,
            new_file_source=new_source_file,
        )

        assert old_file.exists()
        assert old_file.read_bytes() == new_content

    def test_replace_writes_from_bytes(self, project_tree, old_file,
                                        circuit_breaker):
        """Test writing from bytes content instead of file source."""
        new_content = b"BYTES CONTENT - " + b"z" * 300

        replace_with_supersede(
            old_path=old_file,
            project_root=project_tree,
            circuit_breaker=circuit_breaker,
            new_file_content=new_content,
        )

        assert old_file.read_bytes() == new_content


class TestReplaceVerifiesNewFileSize:
    """Test 5: New file write is verified (non-zero check)."""

    def test_replace_verifies_new_file_size(self, project_tree, old_file,
                                              circuit_breaker):
        """When new file write produces 0-byte file, old file is restored."""
        old_content = old_file.read_bytes()

        with pytest.raises(ValueError, match="size is 0"):
            replace_with_supersede(
                old_path=old_file,
                project_root=project_tree,
                circuit_breaker=circuit_breaker,
                new_file_content=b"",  # Empty content = 0-byte file
            )

        # Old file should be restored from backup
        assert old_file.exists()
        assert old_file.read_bytes() == old_content


class TestReplaceHandlesNamingCollision:
    """Test 6: Naming collisions in Superseded folder are handled with timestamps."""

    def test_replace_handles_naming_collision_in_superseded(
        self, project_tree, old_file, new_source_file, circuit_breaker
    ):
        # Pre-create a file in Superseded with the same name
        superseded_dir = old_file.parent / "Superseded"
        superseded_dir.mkdir()
        existing_superseded = superseded_dir / old_file.name
        existing_superseded.write_bytes(b"ALREADY SUPERSEDED")

        superseded_path = replace_with_supersede(
            old_path=old_file,
            project_root=project_tree,
            circuit_breaker=circuit_breaker,
            new_file_source=new_source_file,
        )

        # Both files should exist in Superseded
        assert existing_superseded.exists()
        assert superseded_path.exists()
        assert superseded_path != existing_superseded

        # New superseded file should have timestamp in name
        assert superseded_path.parent == superseded_dir
        # Pattern: report_YYYYMMDD_HHMMSS.pdf
        assert superseded_path.stem.startswith("report_")
        assert len(superseded_path.stem) > len("report_")


class TestReplaceRestoresOnWriteFailure:
    """Test 7: If new file write fails, old file is restored from backup."""

    def test_replace_restores_on_write_failure(self, project_tree, old_file,
                                                 circuit_breaker):
        old_content = old_file.read_bytes()

        # Simulate a write failure by making the target read-only after backup
        def failing_write(path):
            raise OSError("Simulated disk full")

        with pytest.raises((ValueError, OSError)):
            with patch.object(Path, 'write_bytes', side_effect=failing_write):
                replace_with_supersede(
                    old_path=old_file,
                    project_root=project_tree,
                    circuit_breaker=circuit_breaker,
                    new_file_content=b"NEW CONTENT",
                )

        # Old file should still exist (either preserved or restored)
        assert old_file.exists()


class TestReplaceRespectsPathJail:
    """Test 8: Path jail violations are caught and operation is aborted."""

    def test_replace_respects_path_jail(self, tmp_path, circuit_breaker):
        # Create a file outside the project root
        outside = tmp_path / "outside"
        outside.mkdir()
        evil_file = outside / "secret.txt"
        evil_file.write_bytes(b"secret data")

        project_root = tmp_path / "project"
        project_root.mkdir()

        with pytest.raises(PathJailViolation):
            replace_with_supersede(
                old_path=evil_file,
                project_root=project_root,
                circuit_breaker=circuit_breaker,
                new_file_content=b"hacked",
            )


class TestReplaceCountsCircuitBreakerOps:
    """Test 9: Circuit breaker operations are properly recorded."""

    def test_replace_counts_circuit_breaker_operations(
        self, project_tree, old_file, new_source_file, circuit_breaker
    ):
        replace_with_supersede(
            old_path=old_file,
            project_root=project_tree,
            circuit_breaker=circuit_breaker,
            new_file_source=new_source_file,
        )

        ops = circuit_breaker.get_summary()
        op_types = [op[0] for op in ops]

        # Should have: MKDIR (Superseded folder), COPY (to Superseded), WRITE (new file)
        assert "MKDIR" in op_types
        assert "COPY" in op_types
        assert "WRITE" in op_types

    def test_replace_without_mkdir_when_superseded_exists(
        self, project_tree, old_file, new_source_file, circuit_breaker
    ):
        """When Superseded folder already exists, skip MKDIR operation."""
        (old_file.parent / "Superseded").mkdir()

        replace_with_supersede(
            old_path=old_file,
            project_root=project_tree,
            circuit_breaker=circuit_breaker,
            new_file_source=new_source_file,
        )

        ops = circuit_breaker.get_summary()
        op_types = [op[0] for op in ops]

        # Should have only COPY and WRITE, no MKDIR
        assert "MKDIR" not in op_types
        assert "COPY" in op_types
        assert "WRITE" in op_types


class TestReplaceHandlesDiskFull:
    """Test 10: Disk full during copy to Superseded is handled."""

    def test_replace_handles_disk_full(self, project_tree, old_file,
                                        circuit_breaker):
        old_content = old_file.read_bytes()

        # Make Superseded dir exist first so MKDIR doesn't fail
        (old_file.parent / "Superseded").mkdir()

        original_copy2 = shutil.copy2

        def disk_full_copy(src, dst):
            raise OSError("No space left on device")

        with patch('fileuzi.services.filing_operations.shutil.copy2',
                   side_effect=disk_full_copy):
            with pytest.raises(OSError, match="No space"):
                replace_with_supersede(
                    old_path=old_file,
                    project_root=project_tree,
                    circuit_breaker=circuit_breaker,
                    new_file_content=b"new data",
                )

        # Old file should be untouched
        assert old_file.exists()
        assert old_file.read_bytes() == old_content


class TestReplaceHandlesPermissionDenied:
    """Test 11: Permission denied on Superseded folder is handled."""

    def test_replace_handles_permission_denied(self, project_tree, old_file,
                                                 circuit_breaker):
        # Create a file named "Superseded" so mkdir fails
        superseded_as_file = old_file.parent / "Superseded"
        superseded_as_file.write_bytes(b"I am a file, not a folder")

        with pytest.raises(OSError, match="Cannot create Superseded folder"):
            replace_with_supersede(
                old_path=old_file,
                project_root=project_tree,
                circuit_breaker=circuit_breaker,
                new_file_content=b"new data",
            )


class TestReplaceLogsOperation:
    """Test 12: Operations are logged correctly."""

    def test_replace_logs_operation(self, project_tree, old_file,
                                     new_source_file, circuit_breaker):
        with patch('fileuzi.services.filing_operations.get_file_ops_logger') as mock_logger_fn:
            mock_logger = MagicMock()
            mock_logger_fn.return_value = mock_logger

            replace_with_supersede(
                old_path=old_file,
                project_root=project_tree,
                circuit_breaker=circuit_breaker,
                new_file_source=new_source_file,
            )

            # Check that SUPERSEDE was logged
            info_calls = [str(c) for c in mock_logger.info.call_args_list]
            supersede_logged = any("SUPERSEDE" in str(c) for c in info_calls)
            assert supersede_logged, f"Expected SUPERSEDE in logs, got: {info_calls}"


class TestReplaceRequiresSource:
    """Test: ValueError raised if neither source nor content provided."""

    def test_replace_requires_source_or_content(self, project_tree, old_file,
                                                  circuit_breaker):
        with pytest.raises(ValueError, match="Either new_file_source or new_file_content"):
            replace_with_supersede(
                old_path=old_file,
                project_root=project_tree,
                circuit_breaker=circuit_breaker,
            )


class TestReplaceOldFileDisappears:
    """Test: When old file disappears, write proceeds as fresh write."""

    def test_replace_handles_missing_old_file(self, project_tree, circuit_breaker):
        missing = project_tree / "2506_SMITH-EXTENSION" / "TECHNICAL" / "ghost.pdf"
        # File doesn't exist - should handle gracefully
        result = replace_with_supersede(
            old_path=missing,
            project_root=project_tree,
            circuit_breaker=circuit_breaker,
            new_file_content=b"new content here",
        )

        # Should return None (no backup was needed)
        assert result is None
        # New file should be written
        assert missing.exists()
        assert missing.read_bytes() == b"new content here"


# ============================================================================
# Unit Tests: Dialog Changes
# ============================================================================

class TestDialogChanges:
    """Tests 13-14: Dialog buttons and behavior."""

    def test_same_location_dialog_has_no_overwrite(self):
        """Test 14: FileDuplicateDialog has Skip, Rename, Replace but no Overwrite."""
        pytest.importorskip('PyQt6')
        from fileuzi.ui.dialogs import FileDuplicateDialog

        # Check the class has on_replace but not on_overwrite
        assert hasattr(FileDuplicateDialog, 'on_replace')
        assert not hasattr(FileDuplicateDialog, 'on_overwrite')

    def test_different_location_dialog_exists(self):
        """Test 13: DifferentLocationDuplicateDialog class exists with correct methods."""
        pytest.importorskip('PyQt6')
        from fileuzi.ui.dialogs import DifferentLocationDuplicateDialog

        assert hasattr(DifferentLocationDuplicateDialog, 'on_skip')
        assert hasattr(DifferentLocationDuplicateDialog, 'on_file_new_location')
        assert hasattr(DifferentLocationDuplicateDialog, 'on_replace_existing')


# ============================================================================
# Unit Tests: Drawing Superseding Integration
# ============================================================================

class TestDrawingSupersedingUsesSafeWorkflow:
    """Test 15: Drawing superseding uses the safe workflow."""

    def test_drawing_superseding_uses_safe_workflow(self, project_tree):
        """Verify supersede_drawings uses verified copy + unlink pattern."""
        from fileuzi.services.drawing_manager import supersede_drawings

        current = project_tree / "2506_SMITH-EXTENSION" / "Current Drawings"

        # Create old drawing
        old_drawing = current / "2506_22_PROPOSED SECTIONS_C01.pdf"
        old_drawing.write_bytes(b"%PDF-1.4 old drawing " + b"x" * 100)

        # Create new drawing (higher revision)
        new_drawing = current / "2506_22_PROPOSED SECTIONS_C02.pdf"
        new_drawing.write_bytes(b"%PDF-1.4 new drawing " + b"y" * 100)

        cb = FileOperationCounter()
        cb.reset()

        success, msg, count = supersede_drawings(
            current, new_drawing, project_tree, cb
        )

        assert success
        assert count == 1

        # Old drawing should be in Superseded
        superseded = current / "Superseded" / "2506_22_PROPOSED SECTIONS_C01.pdf"
        assert superseded.exists()

        # Old drawing should be removed from Current Drawings
        assert not old_drawing.exists()

        # New drawing should still be in place
        assert new_drawing.exists()

        # Circuit breaker should have recorded operations
        ops = cb.get_summary()
        assert len(ops) >= 2  # At least MKDIR + COPY


# ============================================================================
# Integration Tests
# ============================================================================

class TestFullReplaceWorkflow:
    """Integration Test 1: Complete replace workflow end-to-end."""

    def test_full_replace_workflow_with_verification(self, project_tree):
        """End-to-end: create file, replace it, verify backup + new content."""
        tech_dir = project_tree / "2506_SMITH-EXTENSION" / "TECHNICAL"
        original = tech_dir / "calculations.pdf"
        original.write_bytes(b"ORIGINAL STRUCTURAL CALCS V1 " + b"a" * 500)
        original_size = original.stat().st_size

        new_content = b"UPDATED STRUCTURAL CALCS V2 " + b"b" * 800
        cb = FileOperationCounter()
        cb.reset()

        superseded_path = replace_with_supersede(
            old_path=original,
            project_root=project_tree,
            circuit_breaker=cb,
            new_file_content=new_content,
        )

        # 1. Superseded folder created
        assert (tech_dir / "Superseded").exists()

        # 2. Backup exists with original content
        assert superseded_path.exists()
        assert superseded_path.stat().st_size == original_size

        # 3. Original location has new content
        assert original.exists()
        assert original.read_bytes() == new_content

        # 4. Operations recorded
        ops = cb.get_summary()
        assert len(ops) == 3  # MKDIR, COPY, WRITE


class TestReplaceFailureLeavesNoPartialFiles:
    """Integration Test 2: Failed replace leaves filesystem clean."""

    def test_replace_failure_leaves_no_partial_files(self, project_tree):
        tech_dir = project_tree / "2506_SMITH-EXTENSION" / "TECHNICAL"
        original = tech_dir / "important.pdf"
        original_content = b"CRITICAL DATA " + b"c" * 300
        original.write_bytes(original_content)

        cb = FileOperationCounter()
        cb.reset()

        # Try to replace with empty content (will fail verification)
        with pytest.raises(ValueError):
            replace_with_supersede(
                old_path=original,
                project_root=project_tree,
                circuit_breaker=cb,
                new_file_content=b"",
            )

        # Original should be restored
        assert original.exists()
        assert original.read_bytes() == original_content

        # Superseded backup should still exist (it was a valid copy)
        superseded_dir = tech_dir / "Superseded"
        assert superseded_dir.exists()
        backup_files = list(superseded_dir.iterdir())
        assert len(backup_files) == 1
        assert backup_files[0].read_bytes() == original_content


class TestMultipleSupersedesToSameFolder:
    """Integration Test 3: Multiple supersede operations to same Superseded folder."""

    def test_multiple_supersedes_to_same_folder(self, project_tree):
        current = project_tree / "2506_SMITH-EXTENSION" / "Current Drawings"
        cb = FileOperationCounter()
        cb.reset()

        # Create and replace file three times
        target = current / "site_plan.pdf"
        superseded_paths = []

        for i in range(3):
            old_content = f"VERSION {i}".encode() + b"x" * 100
            target.write_bytes(old_content)

            new_content = f"VERSION {i+1}".encode() + b"y" * 100

            path = replace_with_supersede(
                old_path=target,
                project_root=project_tree,
                circuit_breaker=cb,
                new_file_content=new_content,
            )
            superseded_paths.append(path)

        # All three backups should exist in Superseded
        superseded_dir = current / "Superseded"
        assert superseded_dir.exists()

        backup_files = list(superseded_dir.iterdir())
        assert len(backup_files) == 3

        # Final version should be at original location
        assert target.exists()
        assert target.read_bytes() == b"VERSION 3" + b"y" * 100
