"""
Safe file replacement with automatic superseding for FileUzi.

Provides the replace_with_supersede() function that safely replaces a file
by backing up the old version to a Superseded folder before writing the new one.
"""

import shutil
from datetime import datetime
from pathlib import Path

from fileuzi.utils import (
    get_file_ops_logger,
    get_circuit_breaker,
    validate_path_jail,
    PathJailViolation,
    CircuitBreakerTripped,
)


def replace_with_supersede(
    old_path,
    project_root,
    circuit_breaker=None,
    new_file_source=None,
    new_file_content=None,
):
    """
    Safely replace a file by moving old version to Superseded folder.

    Args:
        old_path: Path to existing file to be replaced
        project_root: Project root for path jail validation
        circuit_breaker: Circuit breaker instance for operation counting
        new_file_source: Path to new file (if copying from file)
        new_file_content: Bytes content of new file (if writing from memory)

    Returns:
        Path where old file was backed up (in Superseded folder)

    Raises:
        ValueError: If copy/write verification fails
        PathJailViolation: If any path escapes project root
        CircuitBreakerTripped: If operation limit exceeded
        OSError: If disk full or permission denied
    """
    if new_file_source is None and new_file_content is None:
        raise ValueError("Either new_file_source or new_file_content must be provided")

    logger = get_file_ops_logger(project_root)
    cb = circuit_breaker or get_circuit_breaker()
    old_path = Path(old_path)

    # Step 1: Path Setup
    old_dir = old_path.parent
    superseded_dir = old_dir / "Superseded"
    superseded_path = superseded_dir / old_path.name

    # Step 4 early check: Handle old file disappearing
    if not old_path.exists():
        logger.warning(
            f"SUPERSEDE SKIP | Old file does not exist: {old_path} - "
            f"treating as fresh write"
        )
        # Write new file to the location directly
        _write_new_file(old_path, new_file_source, new_file_content,
                        project_root, cb, logger)
        return None

    # Validate all paths against path jail BEFORE any filesystem operations
    validate_path_jail(superseded_dir, project_root)
    validate_path_jail(superseded_path, project_root)
    validate_path_jail(old_path, project_root)

    # Step 2: Create Superseded Folder
    if superseded_dir.exists() and not superseded_dir.is_dir():
        raise OSError(
            f"Cannot create Superseded folder - a file with that name "
            f"already exists: {superseded_dir}"
        )

    if not superseded_dir.exists():
        try:
            superseded_dir.mkdir(exist_ok=True)
            cb.record("MKDIR", str(old_dir), str(superseded_dir))
            logger.info(f"MKDIR | Created Superseded folder: {superseded_dir}")
        except CircuitBreakerTripped:
            raise
        except OSError as e:
            logger.error(
                f"SUPERSEDE FAILED | Cannot create Superseded folder: "
                f"{superseded_dir} - {e}"
            )
            raise

    # Step 3: Handle naming collisions in Superseded
    if superseded_path.exists():
        stem = old_path.stem
        suffix = old_path.suffix
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        superseded_path = superseded_dir / f"{stem}_{timestamp}{suffix}"
        validate_path_jail(superseded_path, project_root)

    # Step 4: Copy old file to Superseded
    old_size = old_path.stat().st_size
    try:
        cb.record("COPY", str(old_path), str(superseded_path))
        shutil.copy2(str(old_path), str(superseded_path))
    except CircuitBreakerTripped:
        # Clean up partial copy if it was created
        if superseded_path.exists():
            superseded_path.unlink()
        raise
    except OSError as e:
        logger.error(
            f"SUPERSEDE FAILED | {old_path} - Copy to Superseded failed: {e}"
        )
        raise

    # Step 5: Verify copy succeeded
    superseded_size = superseded_path.stat().st_size
    if old_size != superseded_size:
        superseded_path.unlink()  # Clean up bad copy
        error_msg = (
            f"Supersede copy verification failed: "
            f"{old_size} != {superseded_size}"
        )
        logger.error(f"SUPERSEDE FAILED | {old_path} - {error_msg}")
        raise ValueError(error_msg)

    # Step 6: Write new file to original location
    try:
        _write_new_file(old_path, new_file_source, new_file_content,
                        project_root, cb, logger)
    except Exception:
        # Step 7: If write failed, check and restore from backup
        if not old_path.exists() or old_path.stat().st_size == 0:
            shutil.copy2(str(superseded_path), str(old_path))
            logger.error(
                f"SUPERSEDE RESTORED | Original file restored from backup: "
                f"{old_path}"
            )
            raise ValueError(
                "New file write failed - restored from Superseded backup"
            )
        raise

    # Step 7: Verify new file write succeeded
    new_size = old_path.stat().st_size
    if new_size == 0:
        # CRITICAL: Restore from backup
        shutil.copy2(str(superseded_path), str(old_path))
        logger.error(
            f"SUPERSEDE RESTORED | Original file restored from backup "
            f"(new file was 0 bytes): {old_path}"
        )
        raise ValueError(
            "New file write failed (size is 0) - restored from Superseded backup"
        )

    # Step 8: Log the operation
    logger.info(
        f"SUPERSEDE | {old_path} -> {superseded_path} "
        f"(old: {old_size} bytes, new: {new_size} bytes)"
    )

    # Step 9: Return success
    return superseded_path


def _write_new_file(target_path, source_path, content, project_root, cb, logger):
    """
    Write a new file either by copying from source or writing bytes content.

    Args:
        target_path: Where to write the file
        source_path: Path to source file (if copying)
        content: Bytes content (if writing from memory)
        project_root: Project root for path jail validation
        cb: Circuit breaker instance
        logger: Logger instance
    """
    target_path = Path(target_path)
    validate_path_jail(target_path, project_root)

    if source_path is not None:
        source_path = Path(source_path)
        cb.record("WRITE", str(source_path), str(target_path))
        shutil.copy2(str(source_path), str(target_path))
    else:
        cb.record("WRITE", "memory", str(target_path))
        target_path.write_bytes(content)
