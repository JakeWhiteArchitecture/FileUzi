"""
Path validation and utility functions for FileUzi.
"""

import os
import logging
from pathlib import Path

from fileuzi.config import FILING_WIDGET_TOOLS_FOLDER, OPERATIONS_LOG_FILENAME
from .exceptions import PathJailViolation


def validate_path_jail(path, project_root):
    """
    Validate that a path is within the project root (path jail check).

    Uses os.path.realpath() to resolve symlinks and get the true absolute path.

    Args:
        path: Path to validate
        project_root: Project root that all paths must be within

    Returns:
        str: The resolved absolute path

    Raises:
        PathJailViolation: If the path is outside the project root
    """
    resolved = os.path.realpath(str(path))
    root_resolved = os.path.realpath(str(project_root))

    # Check if resolved path starts with root (with proper separator to avoid /project matching /project2)
    if not resolved.startswith(root_resolved + os.sep) and resolved != root_resolved:
        raise PathJailViolation(
            f"BLOCKED: {path} resolves to {resolved} which is outside project root {root_resolved}"
        )

    return resolved


def get_tools_folder_path(projects_root):
    """Get the path to the FILING-WIDGET-TOOLS folder."""
    return Path(projects_root) / FILING_WIDGET_TOOLS_FOLDER


def ensure_tools_folder(projects_root):
    """Ensure the FILING-WIDGET-TOOLS folder exists, create if not."""
    tools_folder = get_tools_folder_path(projects_root)
    if not tools_folder.exists():
        tools_folder.mkdir(parents=True, exist_ok=True)
    return tools_folder


def get_operations_log_path(projects_root):
    """Get the path to the filing operations log file."""
    return get_tools_folder_path(projects_root) / OPERATIONS_LOG_FILENAME


# File operations logger - initialized lazily
_file_ops_logger = None


def get_file_ops_logger(projects_root):
    """Get or create the file operations logger."""
    global _file_ops_logger
    if _file_ops_logger is None:
        log_path = get_operations_log_path(projects_root)
        _file_ops_logger = logging.getLogger('filing_operations')
        _file_ops_logger.setLevel(logging.INFO)
        # Prevent duplicate handlers
        if not _file_ops_logger.handlers:
            handler = logging.FileHandler(str(log_path), encoding='utf-8')
            handler.setFormatter(logging.Formatter(
                '%(asctime)s | %(levelname)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ))
            _file_ops_logger.addHandler(handler)
    return _file_ops_logger
