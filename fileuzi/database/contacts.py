"""
Contact database operations for FileUzi.
"""

import sqlite3
from pathlib import Path


def get_contacts_from_database(db_path, job_number=None):
    """
    Get unique contact names from the database for a specific project.

    Args:
        db_path: Path to the database
        job_number: Filter contacts to this job only (if provided)

    Returns:
        list: List of unique contact_name values from filed emails
    """
    if not db_path or not Path(db_path).exists():
        return []

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        if job_number:
            # Get contacts for this specific job only
            cursor.execute("""
                SELECT DISTINCT contact_name
                FROM emails
                WHERE contact_name IS NOT NULL
                  AND contact_name != ''
                  AND job_number = ?
                ORDER BY contact_name
            """, (job_number,))
        else:
            # No job specified - return empty (require project selection)
            conn.close()
            return []

        results = cursor.fetchall()
        conn.close()
        return [r[0] for r in results]
    except Exception:
        return []


def get_contact_for_sender(db_path, sender_address, job_number=None):
    """
    Look up the most recently used contact name for an email sender.

    If the user previously filed an email from this sender with a custom
    contact name, return that name so it can be reused.

    Args:
        db_path: Path to the database
        sender_address: Email address of the sender
        job_number: Optionally filter by job number

    Returns:
        str or None: The most recently used contact_name for this sender
    """
    if not db_path or not Path(db_path).exists() or not sender_address:
        return None

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        if job_number:
            # Look for contact name used for this sender on this job
            cursor.execute("""
                SELECT contact_name
                FROM emails
                WHERE LOWER(sender_address) = LOWER(?)
                  AND job_number = ?
                  AND contact_name IS NOT NULL
                  AND contact_name != ''
                ORDER BY filed_at DESC
                LIMIT 1
            """, (sender_address, job_number))
        else:
            # Look for any contact name used for this sender
            cursor.execute("""
                SELECT contact_name
                FROM emails
                WHERE LOWER(sender_address) = LOWER(?)
                  AND contact_name IS NOT NULL
                  AND contact_name != ''
                ORDER BY filed_at DESC
                LIMIT 1
            """, (sender_address,))

        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception:
        return None
