"""Utility modules for FileUzi."""

from .exceptions import PathJailViolation, CircuitBreakerTripped
from .circuit_breaker import FileOperationCounter, get_circuit_breaker
from .path_utils import (
    validate_path_jail,
    get_tools_folder_path,
    ensure_tools_folder,
    get_operations_log_path,
    get_file_ops_logger,
)
from .file_operations import safe_copy, safe_move, safe_write_attachment
from .text_utils import HTMLTextExtractor

__all__ = [
    'PathJailViolation',
    'CircuitBreakerTripped',
    'FileOperationCounter',
    'get_circuit_breaker',
    'validate_path_jail',
    'get_tools_folder_path',
    'ensure_tools_folder',
    'get_operations_log_path',
    'get_file_ops_logger',
    'safe_copy',
    'safe_move',
    'safe_write_attachment',
    'HTMLTextExtractor',
]
