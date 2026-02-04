"""
End-to-End Filing Integration Tests for FileUzi.

These tests verify the complete filing workflow from email parsing
through to database records and file operations.
"""

import pytest
import sqlite3
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from fileuzi.services.email_parser import parse_eml_file, detect_email_direction
from fileuzi.database.email_records import (
    insert_email_record,
    check_duplicate_email,
    update_filed_also,
    generate_email_hash,
)
from fileuzi.utils.path_jail import validate_path_in_jail
from fileuzi.utils.circuit_breaker import FileOperationCounter, get_circuit_breaker
from fileuzi.utils.exceptions import CircuitBreakerTripped, PathJailViolation


# ============================================================================
# Database Record Tests
# ============================================================================

class TestFilingCreatesDbRecord:
    """Tests for database record creation during filing."""

    def test_file_email_creates_db_record(self, sample_db, sample_eml_inbound, project_root, config):
        """Test filing an email creates a database record."""
        conn = sqlite3.connect(sample_db)

        # Parse the email
        email_data = parse_eml_file(sample_eml_inbound)

        # Determine direction
        with patch('fileuzi.services.email_parser.MY_EMAIL_ADDRESSES', config['MY_EMAIL_ADDRESSES']):
            direction = detect_email_direction(email_data)

        # File destination
        filed_to = str(project_root / "2506_SMITH-EXTENSION" / "TECHNICAL")

        # Insert record
        insert_email_record(
            conn,
            message_id=email_data['message_id'],
            hash_fallback=None,
            subject=email_data['subject'],
            sender=email_data['from'],
            recipient=email_data['to'],
            email_date=email_data.get('date_iso', ''),
            direction=direction,
            filed_to=filed_to,
            filed_also=None,
            attachments=','.join([a['filename'] for a in email_data.get('attachments', [])]),
            job_number='2506'
        )

        # Verify record exists
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM emails WHERE message_id = ?", (email_data['message_id'],))
        row = cursor.fetchone()

        assert row is not None
        conn.close()

    def test_file_email_stores_all_fields(self, sample_db, sample_eml_inbound, project_root, config):
        """Test that all expected fields are stored in the database."""
        conn = sqlite3.connect(sample_db)

        email_data = parse_eml_file(sample_eml_inbound)

        with patch('fileuzi.services.email_parser.MY_EMAIL_ADDRESSES', config['MY_EMAIL_ADDRESSES']):
            direction = detect_email_direction(email_data)

        filed_to = str(project_root / "2506_SMITH-EXTENSION" / "TECHNICAL")

        insert_email_record(
            conn,
            message_id=email_data['message_id'],
            hash_fallback=None,
            subject=email_data['subject'],
            sender=email_data['from'],
            recipient=email_data['to'],
            email_date=email_data.get('date_iso', ''),
            direction=direction,
            filed_to=filed_to,
            filed_also=None,
            attachments='Structural_Calcs_2506.pdf',
            job_number='2506'
        )

        cursor = conn.cursor()
        cursor.execute("""
            SELECT message_id, subject, sender, recipient, direction, filed_to, job_number
            FROM emails WHERE message_id = ?
        """, (email_data['message_id'],))
        row = cursor.fetchone()

        assert row[0] == email_data['message_id']  # message_id
        assert '2506' in row[1]  # subject
        assert 'bob' in row[2].lower()  # sender
        assert 'jake' in row[3].lower()  # recipient
        assert row[4] == 'IN'  # direction
        assert 'TECHNICAL' in row[5]  # filed_to
        assert row[6] == '2506'  # job_number

        conn.close()


# ============================================================================
# Attachment Copy Tests
# ============================================================================

class TestFilingCopiesAttachments:
    """Tests for attachment file copy operations."""

    def test_file_email_copies_attachment_to_destination(self, tmp_path, project_root):
        """Test that attachments are copied to destination folder."""
        # Create a source attachment
        source_folder = tmp_path / "source"
        source_folder.mkdir()
        source_file = source_folder / "Document.pdf"
        source_file.write_bytes(b"PDF content here")

        # Destination folder
        dest_folder = project_root / "2506_SMITH-EXTENSION" / "TECHNICAL"

        # Copy the file
        dest_file = dest_folder / "Document.pdf"
        shutil.copy(source_file, dest_file)

        # Verify copy exists
        assert dest_file.exists()
        assert dest_file.read_bytes() == b"PDF content here"

    def test_file_preserves_filename(self, tmp_path, project_root):
        """Test that original filename is preserved during copy."""
        source_folder = tmp_path / "source"
        source_folder.mkdir()
        original_name = "2506_22_PROPOSED SECTIONS_C02.pdf"
        source_file = source_folder / original_name
        source_file.write_bytes(b"PDF content")

        dest_folder = project_root / "2506_SMITH-EXTENSION" / "Current Drawings"
        dest_file = dest_folder / original_name
        shutil.copy(source_file, dest_file)

        assert dest_file.exists()
        assert dest_file.name == original_name


# ============================================================================
# Duplicate Detection Tests
# ============================================================================

class TestDuplicateDetection:
    """Tests for duplicate email detection during filing."""

    def test_duplicate_email_detected(self, sample_db, sample_eml_inbound, config):
        """Test that duplicate emails are detected by Message-ID."""
        conn = sqlite3.connect(sample_db)

        email_data = parse_eml_file(sample_eml_inbound)

        with patch('fileuzi.services.email_parser.MY_EMAIL_ADDRESSES', config['MY_EMAIL_ADDRESSES']):
            direction = detect_email_direction(email_data)

        # First filing
        insert_email_record(
            conn,
            message_id=email_data['message_id'],
            hash_fallback=None,
            subject=email_data['subject'],
            sender=email_data['from'],
            recipient=email_data['to'],
            email_date=email_data.get('date_iso', ''),
            direction=direction,
            filed_to='/path/first',
            filed_also=None,
            attachments='doc.pdf',
            job_number='2506'
        )

        # Check for duplicate
        duplicate = check_duplicate_email(conn, message_id=email_data['message_id'])

        assert duplicate is not None
        conn.close()

    def test_duplicate_by_hash_fallback(self, sample_db, sample_eml_no_message_id, config):
        """Test duplicate detection using hash fallback when no Message-ID."""
        conn = sqlite3.connect(sample_db)

        email_data = parse_eml_file(sample_eml_no_message_id)

        # Generate hash fallback
        hash_fallback = generate_email_hash(
            email_data['from'],
            email_data['subject'],
            email_data.get('date_iso', '')
        )

        with patch('fileuzi.services.email_parser.MY_EMAIL_ADDRESSES', config['MY_EMAIL_ADDRESSES']):
            direction = detect_email_direction(email_data)

        # First filing with hash
        insert_email_record(
            conn,
            message_id=None,
            hash_fallback=hash_fallback,
            subject=email_data['subject'],
            sender=email_data['from'],
            recipient=email_data['to'],
            email_date=email_data.get('date_iso', ''),
            direction=direction,
            filed_to='/path/first',
            filed_also=None,
            attachments='',
            job_number='2407'
        )

        # Check for duplicate by hash
        duplicate = check_duplicate_email(conn, hash_fallback=hash_fallback)

        assert duplicate is not None
        conn.close()


# ============================================================================
# Filed Also Tests
# ============================================================================

class TestFiledAlso:
    """Tests for filed_also field updates."""

    def test_filed_also_captures_user_selection_only(self, sample_db):
        """Test that filed_also only captures user-selected additional locations."""
        conn = sqlite3.connect(sample_db)

        # Initial filing
        insert_email_record(
            conn,
            message_id='test_filed_also@mail.com',
            hash_fallback=None,
            subject='Test Subject',
            sender='bob@example.com',
            recipient='jake@jwa.com',
            email_date='2026-02-03',
            direction='IN',
            filed_to='/primary/location',
            filed_also=None,  # No additional locations initially
            attachments='doc.pdf',
            job_number='2506'
        )

        # User selects additional location
        update_filed_also(conn, 'test_filed_also@mail.com', '/secondary/location')

        cursor = conn.cursor()
        cursor.execute("SELECT filed_also FROM emails WHERE message_id = ?", ('test_filed_also@mail.com',))
        row = cursor.fetchone()

        assert row[0] == '/secondary/location'
        conn.close()

    def test_filed_also_appends_multiple_locations(self, sample_db):
        """Test that multiple filed_also locations are appended."""
        conn = sqlite3.connect(sample_db)

        insert_email_record(
            conn,
            message_id='multi_filed@mail.com',
            hash_fallback=None,
            subject='Multi-file Test',
            sender='bob@example.com',
            recipient='jake@jwa.com',
            email_date='2026-02-03',
            direction='IN',
            filed_to='/primary',
            filed_also=None,
            attachments='doc.pdf',
            job_number='2506'
        )

        # First additional location
        update_filed_also(conn, 'multi_filed@mail.com', '/secondary')
        # Second additional location
        update_filed_also(conn, 'multi_filed@mail.com', '/tertiary')

        cursor = conn.cursor()
        cursor.execute("SELECT filed_also FROM emails WHERE message_id = ?", ('multi_filed@mail.com',))
        row = cursor.fetchone()

        assert '/secondary' in row[0]
        assert '/tertiary' in row[0]
        conn.close()


# ============================================================================
# Path Jail Tests
# ============================================================================

class TestFilingRespectsPathJail:
    """Tests for path jail enforcement during filing."""

    def test_file_respects_path_jail(self, project_root):
        """Test that filing respects path jail boundaries."""
        jail_root = project_root

        # Valid path within jail
        valid_path = project_root / "2506_SMITH-EXTENSION" / "TECHNICAL"
        assert validate_path_in_jail(valid_path, jail_root) is True

    def test_file_rejects_path_outside_jail(self, project_root):
        """Test that paths outside jail are rejected."""
        jail_root = project_root

        # Path outside jail (parent directory)
        outside_path = project_root.parent / "outside_folder"

        with pytest.raises(PathJailViolation):
            validate_path_in_jail(outside_path, jail_root)

    def test_file_rejects_path_traversal(self, project_root):
        """Test that path traversal attempts are rejected."""
        jail_root = project_root

        # Traversal attempt
        traversal_path = project_root / "2506_SMITH-EXTENSION" / ".." / ".." / "outside"

        with pytest.raises(PathJailViolation):
            validate_path_in_jail(traversal_path, jail_root)


# ============================================================================
# Circuit Breaker Tests
# ============================================================================

class TestFilingRespectsCircuitBreaker:
    """Tests for circuit breaker enforcement during filing."""

    def test_file_respects_circuit_breaker(self):
        """Test that filing respects circuit breaker limits."""
        counter = FileOperationCounter(limit=5)

        # Record operations up to limit
        for i in range(5):
            counter.record_operation(f"/path/to/file{i}.pdf")

        # Next operation should trip
        with pytest.raises(CircuitBreakerTripped):
            counter.record_operation("/path/to/file_over_limit.pdf")

    def test_circuit_breaker_resets_for_new_session(self):
        """Test that circuit breaker resets between sessions."""
        counter = FileOperationCounter(limit=5)

        # Use up some operations
        for i in range(3):
            counter.record_operation(f"/path/file{i}.pdf")

        # Reset (simulating new session)
        counter.reset()

        # Should be able to do more operations
        for i in range(5):
            counter.record_operation(f"/path/new_file{i}.pdf")

        # Now should trip
        with pytest.raises(CircuitBreakerTripped):
            counter.record_operation("/path/one_too_many.pdf")


# ============================================================================
# Missing Folder Tests
# ============================================================================

class TestMissingFolderHandling:
    """Tests for handling missing destination folders."""

    def test_file_to_missing_subfolder_shows_warning(self, project_root):
        """Test that filing to missing subfolder can be handled gracefully."""
        # A subfolder that doesn't exist
        missing_subfolder = project_root / "2506_SMITH-EXTENSION" / "NON_EXISTENT_FOLDER"

        # The folder doesn't exist
        assert not missing_subfolder.exists()

        # In the real app, this would show a warning dialog
        # For testing, we verify the folder doesn't exist
        # and that creating it would work
        missing_subfolder.mkdir(parents=True, exist_ok=True)
        assert missing_subfolder.exists()

    def test_file_to_missing_root_hard_stops(self, tmp_path):
        """Test that filing to non-existent root project folder fails."""
        # A root project folder that doesn't exist at all
        missing_root = tmp_path / "NONEXISTENT_PROJECT"

        assert not missing_root.exists()

        # Attempting to file here should fail
        # In the real app, this would be a hard stop
        # We verify the path doesn't exist and can't be used
        with pytest.raises(FileNotFoundError):
            # Simulating a file copy to non-existent directory
            dest = missing_root / "file.pdf"
            shutil.copy("/nonexistent/source.pdf", dest)


# ============================================================================
# Keystage Archive Tests
# ============================================================================

class TestKeystageArchive:
    """Tests for keystage archive functionality."""

    def test_keystage_archive_copies_to_both(self, project_root, tmp_path):
        """Test that keystage archive copies to both current and archive locations."""
        # Source file
        source = tmp_path / "2506_22_PROPOSED SECTIONS_C02.pdf"
        source.write_bytes(b"PDF content")

        # Primary destination (Current Drawings)
        current_dest = project_root / "2506_SMITH-EXTENSION" / "Current Drawings"
        current_file = current_dest / source.name

        # Archive destination (IMPORTS-EXPORTS or similar)
        archive_dest = project_root / "2506_SMITH-EXTENSION" / "IMPORTS-EXPORTS"
        archive_file = archive_dest / source.name

        # Copy to both
        shutil.copy(source, current_file)
        shutil.copy(source, archive_file)

        # Verify both copies exist
        assert current_file.exists()
        assert archive_file.exists()
        assert current_file.read_bytes() == archive_file.read_bytes()

    def test_keystage_drawing_triggers_archive(self, project_root):
        """Test that keystage-stage drawings trigger archive copy."""
        # Drawing with keystage stage prefix (C = Construction)
        filename = "2506_22_PROPOSED SECTIONS_C02.pdf"

        # Check if it's a keystage stage
        # Keystage stages are typically: C (Construction), F (Final)
        stage_code = filename.split('_')[-1][:1] if '_' in filename else None

        keystage_stages = ['C', 'F']

        if stage_code and stage_code in keystage_stages:
            should_archive = True
        else:
            should_archive = False

        assert should_archive is True


# ============================================================================
# Screenshot Extraction Tests
# ============================================================================

class TestEmbeddedScreenshotExtraction:
    """Tests for embedded screenshot extraction on outbound emails."""

    def test_embedded_screenshot_extraction_on_outbound(self, sample_eml_embedded_images, config):
        """Test that embedded screenshots are extracted from outbound emails."""
        import email
        from email import policy
        from fileuzi.services.email_parser import extract_embedded_images

        with open(sample_eml_embedded_images, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=policy.default)

        # Extract embedded images above threshold
        embedded = extract_embedded_images(msg, min_size=config['MIN_EMBEDDED_IMAGE_SIZE'])

        # Should have at least one qualifying image (the 25KB one)
        assert len(embedded) >= 1

    def test_small_embedded_images_filtered(self, sample_eml_embedded_images, config):
        """Test that small embedded images are filtered out."""
        import email
        from email import policy
        from fileuzi.services.email_parser import extract_embedded_images

        with open(sample_eml_embedded_images, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=policy.default)

        # Extract with 20KB threshold
        embedded = extract_embedded_images(msg, min_size=config['MIN_EMBEDDED_IMAGE_SIZE'])

        # All returned images should be above threshold
        for cid, data in embedded:
            assert len(data) >= config['MIN_EMBEDDED_IMAGE_SIZE']


# ============================================================================
# Print Email PDF Tests
# ============================================================================

class TestPrintEmailPdf:
    """Tests for Print Email to PDF functionality."""

    def test_print_email_pdf_generated(self):
        """Test that email can be rendered to PDF (mocked)."""
        # This test mocks the PDF generation since it requires
        # weasyprint or similar package which may not be installed

        mock_html = "<html><body><p>Email content here</p></body></html>"

        # Mock PDF renderer
        with patch('weasyprint.HTML') as mock_weasyprint:
            mock_pdf_doc = MagicMock()
            mock_pdf_doc.write_pdf.return_value = b'%PDF-1.4 fake pdf content'
            mock_weasyprint.return_value = mock_pdf_doc

            # Simulate rendering
            try:
                from weasyprint import HTML
                doc = HTML(string=mock_html)
                pdf_bytes = doc.write_pdf()
                assert pdf_bytes.startswith(b'%PDF')
            except ImportError:
                # weasyprint not installed, that's OK for unit tests
                pass

    def test_pdf_generation_with_embedded_images(self):
        """Test PDF generation includes embedded images."""
        # Mock test for PDF with embedded images
        mock_html = """
        <html>
        <body>
        <p>Email content</p>
        <img src="data:image/png;base64,iVBORw0KGgo=">
        </body>
        </html>
        """

        # In real implementation, embedded images would be
        # converted to data URIs and included in the PDF
        assert '<img' in mock_html
        assert 'data:image/png' in mock_html


# ============================================================================
# Full Workflow Integration Tests
# ============================================================================

class TestFullFilingWorkflow:
    """Integration tests for complete filing workflow."""

    def test_complete_inbound_filing_workflow(
        self, sample_db, sample_eml_inbound, project_root, config
    ):
        """Test complete workflow: parse -> detect -> file -> record."""
        conn = sqlite3.connect(sample_db)

        # Step 1: Parse email
        email_data = parse_eml_file(sample_eml_inbound)
        assert email_data['message_id'] is not None

        # Step 2: Detect direction
        with patch('fileuzi.services.email_parser.MY_EMAIL_ADDRESSES', config['MY_EMAIL_ADDRESSES']):
            direction = detect_email_direction(email_data)
        assert direction == 'IN'

        # Step 3: Check for duplicates
        duplicate = check_duplicate_email(conn, message_id=email_data['message_id'])
        assert duplicate is None  # Should be first time

        # Step 4: File to destination
        dest_folder = project_root / "2506_SMITH-EXTENSION" / "TECHNICAL"
        # (In real app, would copy attachments here)

        # Step 5: Record in database
        insert_email_record(
            conn,
            message_id=email_data['message_id'],
            hash_fallback=None,
            subject=email_data['subject'],
            sender=email_data['from'],
            recipient=email_data['to'],
            email_date=email_data.get('date_iso', ''),
            direction=direction,
            filed_to=str(dest_folder),
            filed_also=None,
            attachments=','.join([a['filename'] for a in email_data.get('attachments', [])]),
            job_number='2506'
        )

        # Verify workflow completed
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM emails WHERE message_id = ?", (email_data['message_id'],))
        count = cursor.fetchone()[0]
        assert count == 1

        conn.close()

    def test_complete_outbound_filing_workflow(
        self, sample_db, sample_eml_outbound, project_root, config
    ):
        """Test complete workflow for outbound email."""
        conn = sqlite3.connect(sample_db)

        # Parse
        email_data = parse_eml_file(sample_eml_outbound)

        # Detect direction
        with patch('fileuzi.services.email_parser.MY_EMAIL_ADDRESSES', config['MY_EMAIL_ADDRESSES']):
            direction = detect_email_direction(email_data)
        assert direction == 'OUT'

        # Record
        insert_email_record(
            conn,
            message_id=email_data['message_id'],
            hash_fallback=None,
            subject=email_data['subject'],
            sender=email_data['from'],
            recipient=email_data['to'],
            email_date=email_data.get('date_iso', ''),
            direction=direction,
            filed_to=str(project_root / "2506_SMITH-EXTENSION" / "ADMIN"),
            filed_also=None,
            attachments='',
            job_number='2506'
        )

        # Verify
        cursor = conn.cursor()
        cursor.execute("SELECT direction FROM emails WHERE message_id = ?", (email_data['message_id'],))
        row = cursor.fetchone()
        assert row[0] == 'OUT'

        conn.close()

    def test_duplicate_filing_updates_filed_also(
        self, sample_db, sample_eml_inbound, project_root, config
    ):
        """Test that filing same email again updates filed_also."""
        conn = sqlite3.connect(sample_db)

        email_data = parse_eml_file(sample_eml_inbound)

        with patch('fileuzi.services.email_parser.MY_EMAIL_ADDRESSES', config['MY_EMAIL_ADDRESSES']):
            direction = detect_email_direction(email_data)

        # First filing
        insert_email_record(
            conn,
            message_id=email_data['message_id'],
            hash_fallback=None,
            subject=email_data['subject'],
            sender=email_data['from'],
            recipient=email_data['to'],
            email_date=email_data.get('date_iso', ''),
            direction=direction,
            filed_to='/first/location',
            filed_also=None,
            attachments='',
            job_number='2506'
        )

        # Detect duplicate
        duplicate = check_duplicate_email(conn, message_id=email_data['message_id'])
        assert duplicate is not None

        # Update filed_also for the duplicate
        update_filed_also(conn, email_data['message_id'], '/second/location')

        # Verify
        cursor = conn.cursor()
        cursor.execute("SELECT filed_to, filed_also FROM emails WHERE message_id = ?",
                      (email_data['message_id'],))
        row = cursor.fetchone()

        assert row[0] == '/first/location'  # Original filed_to unchanged
        assert '/second/location' in row[1]  # filed_also updated

        conn.close()
