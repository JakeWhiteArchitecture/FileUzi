"""
Database connection and management functions for FileUzi.
"""

import sqlite3

from fileuzi.config import DATABASE_FILENAME, DATABASE_BACKUP_FILENAME, DATABASE_SCHEMA
from fileuzi.utils import get_tools_folder_path, get_file_ops_logger, safe_copy


def get_database_path(projects_root):
    """Get the path to the filing widget database in the tools folder."""
    return get_tools_folder_path(projects_root) / DATABASE_FILENAME


def get_database_backup_path(projects_root):
    """Get the path to the filing widget database backup in the tools folder."""
    return get_tools_folder_path(projects_root) / DATABASE_BACKUP_FILENAME


def check_database_integrity(db_path):
    """
    Run PRAGMA integrity_check on the database.

    Returns:
        bool: True if database passes integrity check, False otherwise
    """
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        conn.close()
        return result[0] == 'ok'
    except Exception:
        return False


def backup_database(projects_root):
    """
    Create a rolling backup of the database before writes.

    Copies filing_widget.db to filing_widget_backup.db.

    Returns:
        bool: True if backup successful (or no db to backup), False on error
    """
    db_path = get_database_path(projects_root)
    backup_path = get_database_backup_path(projects_root)

    # If no database exists yet, nothing to backup
    if not db_path.exists():
        return True

    # First check integrity of the source database
    if not check_database_integrity(db_path):
        logger = get_file_ops_logger(projects_root)
        logger.error(f"DB INTEGRITY FAILED | {db_path} - skipping backup")
        return False

    # Create backup
    return safe_copy(db_path, backup_path, projects_root)


def init_database(db_path):
    """Initialize the database with the schema."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(DATABASE_SCHEMA)
    conn.commit()
    conn.close()


def check_database_exists(projects_root):
    """Check if the database file exists at the given root."""
    db_path = get_database_path(projects_root)
    return db_path.exists()


def verify_database_schema(db_path):
    """Verify the database has the expected schema."""
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='emails'")
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception:
        return False
