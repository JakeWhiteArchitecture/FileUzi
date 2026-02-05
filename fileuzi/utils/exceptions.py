"""
Custom exceptions for FileUzi safety features.
"""


class PathJailViolation(Exception):
    """Raised when a file operation attempts to access a path outside the project root."""
    pass


class CircuitBreakerTripped(Exception):
    """Raised when too many file operations occur in a single filing action."""
    pass
