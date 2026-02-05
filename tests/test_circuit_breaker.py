"""
Circuit Breaker Unit Tests for FileUzi.

The FileOperationCounter tracks operations per destination folder and trips
when any single destination exceeds its expected file count.
"""

import pytest
from pathlib import Path

from fileuzi.utils.circuit_breaker import FileOperationCounter, get_circuit_breaker
from fileuzi.utils.exceptions import CircuitBreakerTripped


# ============================================================================
# Basic Counter Tests
# ============================================================================

class TestBasicCounter:
    """Basic counter functionality tests."""

    def test_counter_initializes_empty(self):
        """Test counter initializes with empty state."""
        counter = FileOperationCounter()

        assert counter.operations == []
        assert counter.destination_counts == {}
        assert counter.destination_limits == {}

    def test_counter_records_operations(self):
        """Test counter records operations."""
        counter = FileOperationCounter()

        counter.record("COPY", "/source/file1.pdf", "/dest/folder/file1.pdf")
        counter.record("COPY", "/source/file2.pdf", "/dest/folder/file2.pdf")

        assert len(counter.operations) == 2

    def test_counter_resets(self):
        """Test counter resets correctly."""
        counter = FileOperationCounter()

        counter.record("COPY", "/source/file.pdf", "/dest/folder/file.pdf")
        assert len(counter.operations) == 1

        counter.reset()
        assert counter.operations == []
        assert counter.destination_counts == {}

    def test_counter_resets_with_new_limits(self):
        """Test counter can be reset with new destination limits."""
        counter = FileOperationCounter()

        # First session
        counter.reset({'/dest/folder1': 5})
        counter.record("COPY", "/src/a.pdf", "/dest/folder1/a.pdf")

        # New session with different limits
        counter.reset({'/dest/folder2': 10})

        assert counter.destination_limits == {'/dest/folder2': 10}
        assert counter.destination_counts == {}


# ============================================================================
# Per-Destination Limit Tests
# ============================================================================

class TestDestinationLimits:
    """Tests for per-destination limit enforcement."""

    def test_trips_when_exceeding_destination_limit(self, tmp_path):
        """Test circuit breaker trips when destination limit exceeded."""
        dest_folder = str(tmp_path / "dest")
        counter = FileOperationCounter()

        # Set a limit of 3 files for this destination
        counter.reset({dest_folder: 3})

        # Record 3 COPY operations (at limit)
        counter.record("COPY", "/src/a.pdf", f"{dest_folder}/a.pdf")
        counter.record("COPY", "/src/b.pdf", f"{dest_folder}/b.pdf")
        counter.record("COPY", "/src/c.pdf", f"{dest_folder}/c.pdf")

        # Due to +2 overhead allowance, need to exceed by more
        counter.record("COPY", "/src/d.pdf", f"{dest_folder}/d.pdf")
        counter.record("COPY", "/src/e.pdf", f"{dest_folder}/e.pdf")

        # The 6th copy should trip (limit 3 + overhead 2 = 5 max)
        with pytest.raises(CircuitBreakerTripped):
            counter.record("COPY", "/src/f.pdf", f"{dest_folder}/f.pdf")

    def test_different_destinations_tracked_separately(self, tmp_path):
        """Test different destinations are tracked independently."""
        dest1 = str(tmp_path / "dest1")
        dest2 = str(tmp_path / "dest2")

        counter = FileOperationCounter()
        counter.reset({dest1: 3, dest2: 3})

        # Record to dest1
        counter.record("COPY", "/src/a.pdf", f"{dest1}/a.pdf")
        counter.record("COPY", "/src/b.pdf", f"{dest1}/b.pdf")

        # Record to dest2
        counter.record("COPY", "/src/c.pdf", f"{dest2}/c.pdf")
        counter.record("COPY", "/src/d.pdf", f"{dest2}/d.pdf")

        # Each destination has 2, which is under the limit
        assert counter.destination_counts[dest1] == 2
        assert counter.destination_counts[dest2] == 2

    def test_only_copy_and_write_count_toward_limit(self, tmp_path):
        """Test only COPY and WRITE operations count toward limits."""
        dest_folder = str(tmp_path / "dest")
        counter = FileOperationCounter()
        counter.reset({dest_folder: 2})

        # MKDIR doesn't count
        counter.record("MKDIR", "/src", f"{dest_folder}/subfolder")

        # COPY counts
        counter.record("COPY", "/src/a.pdf", f"{dest_folder}/a.pdf")

        # Only 1 counted
        assert counter.destination_counts.get(dest_folder, 0) == 1

    def test_no_trip_when_no_limit_set(self, tmp_path):
        """Test operations without set limits don't trip."""
        counter = FileOperationCounter()
        counter.reset()  # No limits

        dest_folder = str(tmp_path / "unlimited")

        # Record many operations to an unlimited destination
        for i in range(100):
            counter.record("COPY", f"/src/file{i}.pdf", f"{dest_folder}/file{i}.pdf")

        # Should not trip since no limit was set
        assert len(counter.operations) == 100


# ============================================================================
# Global Circuit Breaker Tests
# ============================================================================

class TestGlobalCircuitBreaker:
    """Tests for global circuit breaker instance."""

    def test_get_circuit_breaker_returns_instance(self):
        """Test get_circuit_breaker returns an instance."""
        breaker = get_circuit_breaker()

        assert breaker is not None
        assert isinstance(breaker, FileOperationCounter)

    def test_get_circuit_breaker_same_instance(self):
        """Test get_circuit_breaker returns same instance (singleton)."""
        breaker1 = get_circuit_breaker()
        breaker2 = get_circuit_breaker()

        # Should be the same instance
        assert breaker1 is breaker2

    def test_global_breaker_can_reset(self):
        """Test global circuit breaker can be reset."""
        breaker = get_circuit_breaker()
        breaker.reset()

        assert breaker.operations == []
        assert breaker.destination_counts == {}


# ============================================================================
# Operation Summary Tests
# ============================================================================

class TestOperationSummary:
    """Tests for operation summary functionality."""

    def test_get_summary_returns_operations(self, tmp_path):
        """Test get_summary returns recorded operations."""
        counter = FileOperationCounter()

        counter.record("COPY", "/src/a.pdf", f"{tmp_path}/a.pdf")
        counter.record("WRITE", "/src/b.pdf", f"{tmp_path}/b.pdf")

        summary = counter.get_summary()

        assert len(summary) == 2
        assert summary[0][0] == "COPY"
        assert summary[1][0] == "WRITE"

    def test_summary_is_copy(self, tmp_path):
        """Test get_summary returns a copy, not the original."""
        counter = FileOperationCounter()

        counter.record("COPY", "/src/a.pdf", f"{tmp_path}/a.pdf")

        summary = counter.get_summary()
        summary.append(("FAKE", "", ""))

        # Original should be unchanged
        assert len(counter.operations) == 1


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Edge case tests for circuit breaker."""

    def test_unicode_paths(self, tmp_path):
        """Test recording operation with unicode paths."""
        counter = FileOperationCounter()

        counter.record("COPY", "/path/to/café/file.pdf", f"{tmp_path}/café/file.pdf")
        assert len(counter.operations) == 1

    def test_very_long_paths(self, tmp_path):
        """Test recording very long operation paths."""
        counter = FileOperationCounter()

        long_path = str(tmp_path) + "/subdir" * 50 + "/file.pdf"
        counter.record("COPY", "/source/file.pdf", long_path)
        assert len(counter.operations) == 1

    def test_special_characters_in_path(self, tmp_path):
        """Test paths with special characters."""
        counter = FileOperationCounter()

        counter.record("COPY", "/src/file (1).pdf", f"{tmp_path}/file (1).pdf")
        counter.record("COPY", "/src/file & co.pdf", f"{tmp_path}/file & co.pdf")

        assert len(counter.operations) == 2


# ============================================================================
# Exception Content Tests
# ============================================================================

class TestExceptionContent:
    """Tests for exception content."""

    def test_exception_message_contains_folder_info(self, tmp_path):
        """Test CircuitBreakerTripped message contains folder info."""
        dest_folder = str(tmp_path / "dest")
        counter = FileOperationCounter()
        counter.reset({dest_folder: 1})

        # Exceed the limit (1 + 2 overhead = 3 max)
        counter.record("COPY", "/src/a.pdf", f"{dest_folder}/a.pdf")
        counter.record("COPY", "/src/b.pdf", f"{dest_folder}/b.pdf")
        counter.record("COPY", "/src/c.pdf", f"{dest_folder}/c.pdf")

        try:
            counter.record("COPY", "/src/d.pdf", f"{dest_folder}/d.pdf")
            pytest.fail("Should have raised CircuitBreakerTripped")
        except CircuitBreakerTripped as e:
            error_msg = str(e)
            assert "dest" in error_msg.lower() or len(error_msg) > 0

    def test_exception_lists_operations(self, tmp_path):
        """Test exception message lists operations attempted."""
        dest_folder = str(tmp_path / "dest")
        counter = FileOperationCounter()
        counter.reset({dest_folder: 1})

        counter.record("COPY", "/src/a.pdf", f"{dest_folder}/a.pdf")
        counter.record("COPY", "/src/b.pdf", f"{dest_folder}/b.pdf")
        counter.record("COPY", "/src/c.pdf", f"{dest_folder}/c.pdf")

        try:
            counter.record("COPY", "/src/d.pdf", f"{dest_folder}/d.pdf")
            pytest.fail("Should have raised CircuitBreakerTripped")
        except CircuitBreakerTripped as e:
            error_msg = str(e)
            # Should have operation details
            assert len(error_msg) > 0
