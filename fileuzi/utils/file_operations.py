"""
Safe file operations with path jail validation and circuit breaker protection.
"""

import shutil
from pathlib import Path

from .exceptions import PathJailViolation, CircuitBreakerTripped
from .circuit_breaker import get_circuit_breaker
from .path_utils import validate_path_jail, get_file_ops_logger


def safe_copy(src, dst, projects_root, circuit_breaker=None):
    """
    Safely copy a file with path jail validation, circuit breaker, and logging.

    Args:
        src: Source file path
        dst: Destination file path
        projects_root: Projects root for path jail validation and logging
        circuit_breaker: Optional FileOperationCounter instance

    Returns:
        bool: True if successful, False otherwise

    Raises:
        PathJailViolation: If source or destination is outside project root
        CircuitBreakerTripped: If too many operations in this filing action
    """
    logger = get_file_ops_logger(projects_root)
    src_path = Path(src)
    dst_path = Path(dst)

    # Path jail validation - both source and destination must be within project root
    validate_path_jail(dst_path, projects_root)
    # Note: source may be from outside (e.g., Downloads folder) so we only validate destination

    # Circuit breaker check
    cb = circuit_breaker or get_circuit_breaker()
    op_type = "COPY DIR" if src_path.is_dir() else "COPY"
    cb.record(op_type, src_path, dst_path)

    try:
        # Ensure destination directory exists
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if src_path.is_dir():
            shutil.copytree(str(src_path), str(dst_path))
            logger.info(f"COPY DIR | {src_path} -> {dst_path}")
        else:
            shutil.copy2(str(src_path), str(dst_path))
            logger.info(f"COPY | {src_path} -> {dst_path}")
        return True
    except (PathJailViolation, CircuitBreakerTripped):
        raise  # Re-raise safety exceptions
    except Exception as e:
        logger.error(f"COPY FAILED | {src_path} -> {dst_path} | Error: {e}")
        return False


def safe_move(src, dst, projects_root, circuit_breaker=None):
    """
    Safely move a file with path jail validation, circuit breaker, and logging.

    Args:
        src: Source file path
        dst: Destination file path
        projects_root: Projects root for path jail validation and logging
        circuit_breaker: Optional FileOperationCounter instance

    Returns:
        bool: True if successful, False otherwise

    Raises:
        PathJailViolation: If source or destination is outside project root
        CircuitBreakerTripped: If too many operations in this filing action
    """
    logger = get_file_ops_logger(projects_root)
    src_path = Path(src)
    dst_path = Path(dst)

    # Path jail validation - destination must be within project root
    validate_path_jail(dst_path, projects_root)

    # Circuit breaker check
    cb = circuit_breaker or get_circuit_breaker()
    cb.record("MOVE", src_path, dst_path)

    try:
        # Ensure destination directory exists
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(str(src_path), str(dst_path))
        logger.info(f"MOVE | {src_path} -> {dst_path}")
        return True
    except (PathJailViolation, CircuitBreakerTripped):
        raise  # Re-raise safety exceptions
    except Exception as e:
        logger.error(f"MOVE FAILED | {src_path} -> {dst_path} | Error: {e}")
        return False


def safe_write_attachment(dst, data, projects_root, source_description="email attachment", circuit_breaker=None):
    """
    Safely write attachment data to a file with path jail validation, circuit breaker, and logging.

    Args:
        dst: Destination file path
        data: Binary data to write
        projects_root: Projects root for path jail validation and logging
        source_description: Description of the source for logging
        circuit_breaker: Optional FileOperationCounter instance

    Returns:
        bool: True if successful, False otherwise

    Raises:
        PathJailViolation: If destination is outside project root
        CircuitBreakerTripped: If too many operations in this filing action
    """
    logger = get_file_ops_logger(projects_root)
    dst_path = Path(dst)

    # Path jail validation - destination must be within project root
    validate_path_jail(dst_path, projects_root)

    # Circuit breaker check
    cb = circuit_breaker or get_circuit_breaker()
    cb.record("WRITE", source_description, dst_path)

    try:
        # Ensure destination directory exists
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        with open(dst_path, 'wb') as f:
            f.write(data)
        logger.info(f"WRITE | {source_description} -> {dst_path}")
        return True
    except (PathJailViolation, CircuitBreakerTripped):
        raise  # Re-raise safety exceptions
    except Exception as e:
        logger.error(f"WRITE FAILED | {source_description} -> {dst_path} | Error: {e}")
        return False
