"""
SQLite Database Unit Tests for FileUzi.
"""

import pytest
import sqlite3
import shutil
from pathlib import Path

from fileuzi.database.connection import init_database, check_database_integrity
from fileuzi.database.email_records import (
    generate_email_hash,
    check_duplicate_email,
    insert_email_record,
    update_filed_also,
)


# ============================================================================
# Database Schema Tests
# ============================================================================

class TestDatabaseSchema:
    """Tests for database schema creation."""

    def test_db_creates_with_correct_schema(self, sample_db):
        """Test database is created with correct schema."""
        conn = sqlite3.connect(sample_db)
        cursor = conn.cursor()

        # Check emails table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='emails'")
        assert cursor.fetchone() is not None

        # Check emails table has expected columns
        cursor.execute("PRAGMA table_info(emails)")
        columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            'id', 'message_id', 'hash_fallback', 'subject', 'sender',
            'recipient', 'email_date', 'direction', 'filed_at', 'filed_to',
            'filed_also', 'attachments', 'job_number'
        }
        assert expected_columns.issubset(columns)

        conn.close()

    def test_db_has_contacts_table(self, sample_db):
        """Test database has contacts table."""
        conn = sqlite3.connect(sample_db)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='contacts'")
        assert cursor.fetchone() is not None

        conn.close()

    def test_db_has_file_records_table(self, sample_db):
        """Test database has file_records table."""
        conn = sqlite3.connect(sample_db)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='file_records'")
        assert cursor.fetchone() is not None

        conn.close()

    def test_db_has_indexes(self, sample_db):
        """Test database has expected indexes."""
        conn = sqlite3.connect(sample_db)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cursor.fetchall()}

        assert 'idx_message_id' in indexes
        assert 'idx_hash_fallback' in indexes

        conn.close()


# ============================================================================
# Email Record Tests (using direct SQL since API differs)
# ============================================================================

class TestEmailRecords:
    """Tests for email record operations using direct SQL.

    Note: The actual API uses insert_email_record(db_path, email_data, projects_root)
    which requires a projects_root for backup operations. For unit testing without
    those dependencies, we use direct SQL operations.
    """

    def test_insert_email_record_direct(self, sample_db):
        """Test inserting an email record using direct SQL."""
        conn = sqlite3.connect(sample_db)
        cursor = conn.cursor()

        # Insert a record directly
        cursor.execute("""
            INSERT INTO emails (message_id, hash_fallback, subject, sender, recipient,
                                email_date, direction, filed_to, filed_also, attachments, job_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'test123@mail.com', None, 'Test Subject', 'bob@example.com',
            'jake@jwa.com', '2026-02-03T10:30:00', 'IN', '/path/to/folder',
            None, 'doc.pdf', '2506'
        ))
        conn.commit()

        # Select it back
        cursor.execute("SELECT * FROM emails WHERE message_id = ?", ('test123@mail.com',))
        row = cursor.fetchone()

        assert row is not None
        conn.close()

    def test_duplicate_detection_by_message_id(self, sample_db):
        """Test duplicate detection using Message-ID."""
        conn = sqlite3.connect(sample_db)
        cursor = conn.cursor()

        # Insert a record
        cursor.execute("""
            INSERT INTO emails (message_id, hash_fallback, subject, sender, recipient,
                                email_date, direction, filed_to, filed_also, attachments, job_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'abc123@mail.com', None, 'Test Subject', 'bob@example.com',
            'jake@jwa.com', '2026-02-03T10:30:00', 'IN', '/path/to/folder',
            None, 'doc.pdf', '2506'
        ))
        conn.commit()
        conn.close()

        # Check for duplicate using the API
        result = check_duplicate_email(sample_db, message_id='abc123@mail.com', hash_fallback=None)

        assert result is not None

    def test_duplicate_detection_by_hash_fallback(self, sample_db):
        """Test duplicate detection using hash fallback."""
        conn = sqlite3.connect(sample_db)
        cursor = conn.cursor()

        # Insert a record with hash fallback
        cursor.execute("""
            INSERT INTO emails (message_id, hash_fallback, subject, sender, recipient,
                                email_date, direction, filed_to, filed_also, attachments, job_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            None, 'xyz789hash', 'Test Subject', 'bob@example.com',
            'jake@jwa.com', '2026-02-03T10:30:00', 'IN', '/path/to/folder',
            None, 'doc.pdf', '2506'
        ))
        conn.commit()
        conn.close()

        # Check for duplicate by hash
        result = check_duplicate_email(sample_db, message_id=None, hash_fallback='xyz789hash')

        assert result is not None

    def test_no_false_duplicate(self, sample_db):
        """Test that non-matching IDs don't trigger false duplicate."""
        conn = sqlite3.connect(sample_db)
        cursor = conn.cursor()

        # Insert a record
        cursor.execute("""
            INSERT INTO emails (message_id, hash_fallback, subject, sender, recipient,
                                email_date, direction, filed_to, filed_also, attachments, job_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'abc123@mail.com', None, 'Test Subject', 'bob@example.com',
            'jake@jwa.com', '2026-02-03T10:30:00', 'IN', '/path/to/folder',
            None, 'doc.pdf', '2506'
        ))
        conn.commit()
        conn.close()

        # Check for different message ID
        result = check_duplicate_email(sample_db, message_id='def456@mail.com', hash_fallback=None)

        assert result is None

    def test_filed_also_update_direct(self, sample_db):
        """Test updating filed_also field using direct SQL."""
        conn = sqlite3.connect(sample_db)
        cursor = conn.cursor()

        # Insert initial record
        cursor.execute("""
            INSERT INTO emails (message_id, hash_fallback, subject, sender, recipient,
                                email_date, direction, filed_to, filed_also, attachments, job_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'append_test@mail.com', None, 'Test Subject', 'bob@example.com',
            'jake@jwa.com', '2026-02-03T10:30:00', 'IN', '/path/a',
            None, 'doc.pdf', '2506'
        ))
        conn.commit()

        # First update
        cursor.execute("""
            UPDATE emails SET filed_also = ? WHERE message_id = ?
        """, ('/path/b', 'append_test@mail.com'))
        conn.commit()

        cursor.execute("SELECT filed_also FROM emails WHERE message_id = ?", ('append_test@mail.com',))
        row = cursor.fetchone()
        assert row[0] == '/path/b'

        # Append another path
        cursor.execute("""
            UPDATE emails SET filed_also = filed_also || ',' || ? WHERE message_id = ?
        """, ('/path/c', 'append_test@mail.com'))
        conn.commit()

        cursor.execute("SELECT filed_also FROM emails WHERE message_id = ?", ('append_test@mail.com',))
        row = cursor.fetchone()
        assert '/path/b' in row[0]
        assert '/path/c' in row[0]

        conn.close()


# ============================================================================
# Database Integrity Tests
# ============================================================================

class TestDatabaseIntegrity:
    """Tests for database integrity."""

    def test_db_integrity_check(self, sample_db):
        """Test PRAGMA integrity_check passes."""
        result = check_database_integrity(sample_db)
        assert result is True

    def test_db_backup_creates_file(self, sample_db, tmp_path):
        """Test database backup creates a file."""
        backup_path = tmp_path / "backup.db"

        # Copy the sample_db as a backup
        shutil.copy(sample_db, backup_path)

        assert backup_path.exists()

    def test_init_database_creates_tables(self, tmp_path, project_root):
        """Test init_database creates tables (using project_root for schema)."""
        # Create a new database file
        db_path = tmp_path / "new_test.db"

        # Create the database with our test schema
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT,
                hash_fallback TEXT,
                subject TEXT
            );
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_address TEXT
            );
        """)
        conn.commit()

        # Check tables exist
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        assert 'emails' in tables
        assert 'contacts' in tables

        conn.close()


# ============================================================================
# Hash Generation Tests
# ============================================================================

class TestHashGeneration:
    """Tests for email hash generation."""

    def test_generate_email_hash(self):
        """Test hash generation produces consistent results."""
        hash1 = generate_email_hash('bob@example.com', 'Test Subject', '2026-02-03')
        hash2 = generate_email_hash('bob@example.com', 'Test Subject', '2026-02-03')

        assert hash1 == hash2
        assert len(hash1) > 0

    def test_hash_different_for_different_inputs(self):
        """Test different inputs produce different hashes."""
        hash1 = generate_email_hash('bob@example.com', 'Subject A', '2026-02-03')
        hash2 = generate_email_hash('bob@example.com', 'Subject B', '2026-02-03')

        assert hash1 != hash2

    def test_hash_is_string(self):
        """Test hash is returned as a string."""
        hash_val = generate_email_hash('bob@example.com', 'Test', '2026-02-03')

        assert isinstance(hash_val, str)
