"""
Circuit breaker for preventing runaway file operations.
"""

from pathlib import Path

from .exceptions import CircuitBreakerTripped


class FileOperationCounter:
    """
    Counts file operations per destination during a single filing action.
    Trips the circuit breaker if any destination exceeds its expected file count.
    """

    def __init__(self):
        self.operations = []
        self.destination_limits = {}  # folder_path -> expected file count
        self.destination_counts = {}  # folder_path -> actual file count

    def reset(self, destination_limits=None):
        """
        Reset the counter at the start of a new filing action.

        Args:
            destination_limits: Dict mapping folder paths to expected file counts.
                               e.g., {'/path/to/IMPORTS': 20, '/path/to/Current Drawings': 19}
        """
        self.operations = []
        self.destination_limits = destination_limits or {}
        self.destination_counts = {}

    def record(self, operation_type, source, destination):
        """
        Record a file operation and check per-destination limits.

        Args:
            operation_type: Type of operation (COPY, MOVE, WRITE, MKDIR)
            source: Source path or description
            destination: Destination path

        Raises:
            CircuitBreakerTripped: If any destination exceeds its expected count
        """
        self.operations.append((operation_type, str(source), str(destination)))

        # Only count WRITE and COPY operations toward destination limits
        if operation_type in ('WRITE', 'COPY'):
            dest_path = Path(destination)
            dest_folder = str(dest_path.parent)

            # Increment count for this destination folder
            self.destination_counts[dest_folder] = self.destination_counts.get(dest_folder, 0) + 1
            actual_count = self.destination_counts[dest_folder]

            # Check if this destination has a limit set
            if dest_folder in self.destination_limits:
                # Allow small overhead (2) for edge cases like renamed duplicates
                limit = self.destination_limits[dest_folder] + 2
                if actual_count > limit:
                    ops_summary = "\n".join([f"  {i+1}. {op[0]}: {op[1]} -> {op[2]}"
                                             for i, op in enumerate(self.operations)])
                    raise CircuitBreakerTripped(
                        f"STOPPED: Too many files written to one destination.\n"
                        f"Folder: {dest_folder}\n"
                        f"Expected: {self.destination_limits[dest_folder]}, Actual: {actual_count}\n\n"
                        f"Operations attempted:\n{ops_summary}"
                    )

    def get_summary(self):
        """Get a summary of all operations recorded."""
        return self.operations.copy()


# Global circuit breaker instance - reset at start of each filing action
_circuit_breaker = FileOperationCounter()


def get_circuit_breaker():
    """Get the global circuit breaker instance."""
    return _circuit_breaker
