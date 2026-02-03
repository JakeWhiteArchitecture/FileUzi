"""
Email record database operations for FileUzi.
"""

import sqlite3
import hashlib

from .connection import backup_database


def generate_email_hash(sender_address, subject, date_sent):
    """Generate a fallback hash from sender + subject + date when Message-ID is missing."""
    hash_input = f"{sender_address}|{subject}|{date_sent}".encode('utf-8')
    return hashlib.sha256(hash_input).hexdigest()[:32]


def check_duplicate_email(db_path, message_id, hash_fallback):
    """
    Check if an email already exists in the database.

    Returns:
        dict with filed_at, filed_to if found, None if not found
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check by message_id first
    if message_id:
        cursor.execute(
            "SELECT filed_at, filed_to, filed_also FROM emails WHERE message_id = ?",
            (message_id,)
        )
        result = cursor.fetchone()
        if result:
            conn.close()
            return dict(result)

    # Fall back to hash
    if hash_fallback:
        cursor.execute(
            "SELECT filed_at, filed_to, filed_also FROM emails WHERE hash_fallback = ?",
            (hash_fallback,)
        )
        result = cursor.fetchone()
        if result:
            conn.close()
            return dict(result)

    conn.close()
    return None


def update_filed_also(db_path, message_id, hash_fallback, new_destination, projects_root):
    """Update the filed_also field for an existing email record."""
    # Create rolling backup before write
    backup_database(projects_root)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Find by message_id or hash
    if message_id:
        cursor.execute("SELECT filed_also FROM emails WHERE message_id = ?", (message_id,))
    else:
        cursor.execute("SELECT filed_also FROM emails WHERE hash_fallback = ?", (hash_fallback,))

    result = cursor.fetchone()
    if result:
        current_also = result[0] or ''
        if current_also:
            new_also = f"{current_also},{new_destination}"
        else:
            new_also = new_destination

        if message_id:
            cursor.execute(
                "UPDATE emails SET filed_also = ? WHERE message_id = ?",
                (new_also, message_id)
            )
        else:
            cursor.execute(
                "UPDATE emails SET filed_also = ? WHERE hash_fallback = ?",
                (new_also, hash_fallback)
            )

    conn.commit()
    conn.close()


def insert_email_record(db_path, email_data, projects_root):
    """
    Insert a new email record into the database.

    Args:
        db_path: Path to the database
        email_data: dict with all the email fields
        projects_root: Projects root for backup operations
    """
    # Create rolling backup before write
    backup_database(projects_root)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO emails (
            message_id, hash_fallback,
            sender_address, sender_name, recipient_to, recipient_cc,
            subject, date_sent,
            body_clean, sign_off_type,
            is_inbound,
            filed_to, filed_also, tags,
            has_attachments, attachment_names,
            source_path,
            contact_name, job_number
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        email_data.get('message_id'),
        email_data.get('hash_fallback'),
        email_data.get('sender_address'),
        email_data.get('sender_name'),
        email_data.get('recipient_to'),
        email_data.get('recipient_cc'),
        email_data.get('subject'),
        email_data.get('date_sent'),
        email_data.get('body_clean'),
        email_data.get('sign_off_type'),
        email_data.get('is_inbound', 1),
        email_data.get('filed_to'),
        email_data.get('filed_also'),
        email_data.get('tags'),
        email_data.get('has_attachments', 0),
        email_data.get('attachment_names'),
        email_data.get('source_path'),
        email_data.get('contact_name'),
        email_data.get('job_number'),
    ))

    conn.commit()
    conn.close()
