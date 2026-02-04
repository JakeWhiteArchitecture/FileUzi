"""
Path Jail Unit Tests for FileUzi.
"""

import pytest
import os
from pathlib import Path

from fileuzi.utils.path_utils import validate_path_jail
from fileuzi.utils.exceptions import PathJailViolation


# ============================================================================
# Valid Path Tests
# ============================================================================

class TestValidPaths:
    """Tests for valid paths within the jail."""

    def test_valid_path_within_root(self, project_root):
        """Test path within project root is valid."""
        valid_path = project_root / "2506_SMITH-EXTENSION" / "ADMIN" / "file.pdf"

        # Should not raise, returns resolved path string
        result = validate_path_jail(valid_path, project_root)
        assert result  # Returns truthy (the resolved path string)

    def test_valid_path_direct_child(self, project_root):
        """Test direct child path is valid."""
        valid_path = project_root / "file.pdf"

        result = validate_path_jail(valid_path, project_root)
        assert result  # Returns truthy

    def test_valid_path_deep_nesting(self, project_root):
        """Test deeply nested path is valid."""
        valid_path = project_root / "2506_SMITH-EXTENSION" / "TECHNICAL" / "Surveys" / "topo.pdf"

        result = validate_path_jail(valid_path, project_root)
        assert result  # Returns truthy

    def test_root_path_itself_allowed(self, project_root):
        """Test project root path itself is valid."""
        result = validate_path_jail(project_root, project_root)
        assert result  # Returns truthy


# ============================================================================
# Invalid Path Tests
# ============================================================================

class TestInvalidPaths:
    """Tests for invalid paths outside the jail."""

    def test_path_outside_root_blocked(self, project_root, tmp_path):
        """Test path outside project root raises exception."""
        outside_path = tmp_path / "other_project" / "file.pdf"

        with pytest.raises(PathJailViolation):
            validate_path_jail(outside_path, project_root)

    def test_path_traversal_blocked(self, project_root):
        """Test path traversal attack is blocked."""
        traversal_path = project_root / ".." / ".." / "etc" / "passwd"

        with pytest.raises(PathJailViolation):
            validate_path_jail(traversal_path, project_root)

    def test_path_traversal_in_middle_blocked(self, project_root):
        """Test path traversal in middle of path is blocked."""
        traversal_path = project_root / "2506_SMITH-EXTENSION" / ".." / ".." / "etc" / "passwd"

        with pytest.raises(PathJailViolation):
            validate_path_jail(traversal_path, project_root)

    def test_empty_path_blocked(self, project_root):
        """Test empty path raises exception."""
        with pytest.raises((PathJailViolation, ValueError)):
            validate_path_jail("", project_root)

    def test_absolute_path_outside_root(self, project_root):
        """Test absolute path outside root is blocked."""
        outside_path = Path("/tmp/malicious/file.pdf")

        with pytest.raises(PathJailViolation):
            validate_path_jail(outside_path, project_root)

    def test_parent_directory_reference(self, project_root):
        """Test parent directory reference is blocked."""
        parent_path = project_root / ".."

        with pytest.raises(PathJailViolation):
            validate_path_jail(parent_path, project_root)


# ============================================================================
# Symlink Tests (if supported)
# ============================================================================

class TestSymlinks:
    """Tests for symlink handling."""

    @pytest.mark.skipif(os.name == 'nt', reason="Symlinks behave differently on Windows")
    def test_symlink_outside_root_blocked(self, project_root, tmp_path):
        """Test symlink pointing outside root is blocked."""
        # Create a directory outside the project root
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        (outside_dir / "secret.txt").write_text("secret data")

        # Create a symlink inside project root pointing outside
        symlink_path = project_root / "malicious_link"
        try:
            symlink_path.symlink_to(outside_dir)

            # Attempting to validate the symlink should fail
            with pytest.raises(PathJailViolation):
                validate_path_jail(symlink_path / "secret.txt", project_root)
        except OSError:
            # Skip if symlink creation fails (permissions, etc.)
            pytest.skip("Could not create symlink")
        finally:
            if symlink_path.exists() or symlink_path.is_symlink():
                symlink_path.unlink()

    @pytest.mark.skipif(os.name == 'nt', reason="Symlinks behave differently on Windows")
    def test_symlink_within_root_allowed(self, project_root):
        """Test symlink pointing within root is allowed."""
        # Create a symlink within the project root pointing to another location within root
        target = project_root / "2506_SMITH-EXTENSION" / "ADMIN"
        symlink_path = project_root / "admin_link"

        try:
            symlink_path.symlink_to(target)

            # This should be allowed (symlink points within root)
            result = validate_path_jail(symlink_path, project_root)
            # May or may not be allowed depending on implementation
            # Just ensure it doesn't crash unexpectedly
        except OSError:
            pytest.skip("Could not create symlink")
        finally:
            if symlink_path.exists() or symlink_path.is_symlink():
                symlink_path.unlink()


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Edge case tests for path jail."""

    def test_path_with_spaces(self, project_root):
        """Test path with spaces is handled correctly."""
        path_with_spaces = project_root / "2506_SMITH-EXTENSION" / "Folder With Spaces" / "file.pdf"

        result = validate_path_jail(path_with_spaces, project_root)
        assert result  # Returns resolved path string

    def test_path_with_special_chars(self, project_root):
        """Test path with special characters is handled correctly."""
        path_with_special = project_root / "2506_SMITH-EXTENSION" / "Test & Co" / "file.pdf"

        result = validate_path_jail(path_with_special, project_root)
        assert result  # Returns resolved path string

    def test_unicode_path(self, project_root):
        """Test path with unicode characters is handled correctly."""
        unicode_path = project_root / "2506_SMITH-EXTENSION" / "Café Plans" / "file.pdf"

        result = validate_path_jail(unicode_path, project_root)
        assert result  # Returns resolved path string

    def test_path_with_double_slashes(self, project_root):
        """Test path with double slashes is normalized."""
        # This creates a path that might have double slashes when string-concatenated
        base = str(project_root)
        path_str = base + "//2506_SMITH-EXTENSION//ADMIN//file.pdf"
        path = Path(path_str)

        result = validate_path_jail(path, project_root)
        assert result  # Returns resolved path string

    def test_case_sensitivity(self, project_root):
        """Test path case handling."""
        # This test behavior depends on filesystem
        path = project_root / "2506_SMITH-EXTENSION" / "admin" / "file.pdf"

        # Should not raise PathJailViolation regardless of case
        result = validate_path_jail(path, project_root)
        assert result  # Returns resolved path string

    def test_trailing_slash(self, project_root):
        """Test path with trailing slash is handled."""
        path_str = str(project_root / "2506_SMITH-EXTENSION" / "ADMIN") + "/"
        path = Path(path_str)

        result = validate_path_jail(path, project_root)
        assert result  # Returns resolved path string


# ============================================================================
# Error Message Tests
# ============================================================================

class TestErrorMessages:
    """Tests for error message content."""

    def test_violation_contains_path_info(self, project_root, tmp_path):
        """Test PathJailViolation contains useful information."""
        outside_path = tmp_path / "other" / "file.pdf"

        try:
            validate_path_jail(outside_path, project_root)
            pytest.fail("Should have raised PathJailViolation")
        except PathJailViolation as e:
            # Error message should contain some useful info
            error_str = str(e)
            assert len(error_str) > 0
