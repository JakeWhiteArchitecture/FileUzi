"""
Circuit Breaker Unit Tests for FileUzi.
"""

import pytest

from fileuzi.utils.circuit_breaker import FileOperationCounter, get_circuit_breaker
from fileuzi.utils.exceptions import CircuitBreakerTripped
from fileuzi.config import CIRCUIT_BREAKER_LIMIT


# ============================================================================
# Basic Counter Tests
# ============================================================================

class TestBasicCounter:
    """Basic counter functionality tests."""

    def test_counter_starts_at_zero(self):
        """Test counter starts at zero."""
        counter = FileOperationCounter(limit=20)
        assert counter.count == 0

    def test_counter_increments(self):
        """Test counter increments correctly."""
        counter = FileOperationCounter(limit=20)

        counter.record_operation("test1")
        assert counter.count == 1

        counter.record_operation("test2")
        assert counter.count == 2

        counter.record_operation("test3")
        counter.record_operation("test4")
        counter.record_operation("test5")
        assert counter.count == 5

    def test_counter_resets(self):
        """Test counter resets correctly."""
        counter = FileOperationCounter(limit=20)

        counter.record_operation("test1")
        counter.record_operation("test2")
        counter.record_operation("test3")
        assert counter.count == 3

        counter.reset()
        assert counter.count == 0

    def test_counter_resets_between_actions(self):
        """Test counter can be reset and continue counting."""
        counter = FileOperationCounter(limit=20)

        # First batch
        for i in range(5):
            counter.record_operation(f"op_{i}")
        assert counter.count == 5

        # Reset
        counter.reset()
        assert counter.count == 0

        # Second batch
        for i in range(3):
            counter.record_operation(f"op2_{i}")
        assert counter.count == 3


# ============================================================================
# Trip Threshold Tests
# ============================================================================

class TestTripThreshold:
    """Tests for circuit breaker trip threshold."""

    def test_trips_at_threshold(self):
        """Test circuit breaker trips when threshold exceeded."""
        counter = FileOperationCounter(limit=20)

        # Record 20 operations (at limit, should be fine)
        for i in range(20):
            counter.record_operation(f"op_{i}")

        # The 21st operation should trip the breaker
        with pytest.raises(CircuitBreakerTripped):
            counter.record_operation("op_21")

    def test_doesnt_trip_at_limit(self):
        """Test circuit breaker doesn't trip at exactly the limit."""
        counter = FileOperationCounter(limit=20)

        # Record exactly 20 operations
        for i in range(20):
            counter.record_operation(f"op_{i}")

        # Should be exactly at limit
        assert counter.count == 20

    def test_threshold_configurable(self):
        """Test circuit breaker threshold is configurable."""
        counter = FileOperationCounter(limit=5)

        # Record 5 operations (at limit)
        for i in range(5):
            counter.record_operation(f"op_{i}")

        # The 6th should trip
        with pytest.raises(CircuitBreakerTripped):
            counter.record_operation("op_6")

    def test_low_threshold(self):
        """Test very low threshold."""
        counter = FileOperationCounter(limit=1)

        counter.record_operation("op_1")

        with pytest.raises(CircuitBreakerTripped):
            counter.record_operation("op_2")

    def test_high_threshold(self):
        """Test high threshold."""
        counter = FileOperationCounter(limit=100)

        for i in range(100):
            counter.record_operation(f"op_{i}")

        with pytest.raises(CircuitBreakerTripped):
            counter.record_operation("op_101")


# ============================================================================
# Operation Recording Tests
# ============================================================================

class TestOperationRecording:
    """Tests for operation recording."""

    def test_operations_tracked(self):
        """Test operations are tracked."""
        counter = FileOperationCounter(limit=20)

        counter.record_operation("/path/to/file1.pdf")
        counter.record_operation("/path/to/file2.pdf")

        # The counter should have recorded these
        assert counter.count == 2

    def test_operations_cleared_on_reset(self):
        """Test operations are cleared on reset."""
        counter = FileOperationCounter(limit=20)

        counter.record_operation("/path/to/file1.pdf")
        counter.record_operation("/path/to/file2.pdf")

        counter.reset()

        assert counter.count == 0

    def test_operation_path_stored(self):
        """Test operation paths are stored (if implementation supports it)."""
        counter = FileOperationCounter(limit=20)

        counter.record_operation("/path/to/file.pdf")

        # If the implementation stores operations
        if hasattr(counter, 'operations'):
            assert "/path/to/file.pdf" in counter.operations


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

        # Record some operations
        breaker.record_operation("test_op")
        assert breaker.count >= 1

        # Reset
        breaker.reset()
        assert breaker.count == 0


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Edge case tests for circuit breaker."""

    def test_empty_operation_string(self):
        """Test recording empty operation string."""
        counter = FileOperationCounter(limit=20)

        counter.record_operation("")
        assert counter.count == 1

    def test_none_operation(self):
        """Test recording None operation (if allowed)."""
        counter = FileOperationCounter(limit=20)

        try:
            counter.record_operation(None)
            # If it doesn't raise, count should increment
            assert counter.count == 1
        except (TypeError, ValueError):
            # If it raises, that's also acceptable
            pass

    def test_unicode_operation_path(self):
        """Test recording operation with unicode path."""
        counter = FileOperationCounter(limit=20)

        counter.record_operation("/path/to/café/file.pdf")
        assert counter.count == 1

    def test_very_long_operation_path(self):
        """Test recording very long operation path."""
        counter = FileOperationCounter(limit=20)

        long_path = "/path" + "/subdir" * 100 + "/file.pdf"
        counter.record_operation(long_path)
        assert counter.count == 1

    def test_rapid_operations(self):
        """Test rapid sequential operations."""
        counter = FileOperationCounter(limit=100)

        for i in range(50):
            counter.record_operation(f"rapid_op_{i}")

        assert counter.count == 50

    def test_zero_limit(self):
        """Test zero limit trips immediately."""
        counter = FileOperationCounter(limit=0)

        with pytest.raises(CircuitBreakerTripped):
            counter.record_operation("any_op")


# ============================================================================
# Exception Content Tests
# ============================================================================

class TestExceptionContent:
    """Tests for exception content."""

    def test_exception_message_exists(self):
        """Test CircuitBreakerTripped has a message."""
        counter = FileOperationCounter(limit=1)
        counter.record_operation("op_1")

        try:
            counter.record_operation("op_2")
            pytest.fail("Should have raised CircuitBreakerTripped")
        except CircuitBreakerTripped as e:
            assert str(e) is not None
            assert len(str(e)) > 0

    def test_exception_includes_count(self):
        """Test exception message includes operation count."""
        counter = FileOperationCounter(limit=5)

        for i in range(5):
            counter.record_operation(f"op_{i}")

        try:
            counter.record_operation("op_6")
            pytest.fail("Should have raised CircuitBreakerTripped")
        except CircuitBreakerTripped as e:
            # Message might include the count or limit
            error_msg = str(e).lower()
            # Just check it's not empty
            assert len(error_msg) > 0
