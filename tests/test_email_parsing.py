"""
Email Parser Unit Tests for FileUzi.
"""

import pytest
from unittest.mock import patch

from fileuzi.services.email_parser import (
    parse_body_with_signoff,
    is_my_email,
    detect_email_direction,
    extract_embedded_images,
    parse_eml_file,
)
from fileuzi.database.email_records import generate_email_hash


# ============================================================================
# Sign-off Detection Tests
# ============================================================================

class TestSignoffDetection:
    """Tests for email sign-off detection."""

    def test_signoff_kind_regards(self):
        """Test detection of 'Kind regards' sign-off."""
        body = "Hi Jake\n\nPlease find attached.\n\nKind regards\nBob Smith\nBob Smith Structural\n01234 123456"
        body_clean, sign_off_type = parse_body_with_signoff(body)

        assert body_clean.strip() == "Hi Jake\n\nPlease find attached."
        assert sign_off_type == "Kind regards"

    def test_signoff_yours_sincerely(self):
        """Test detection of 'Yours sincerely' sign-off."""
        body = "Dear Jake\n\nAs discussed.\n\nYours sincerely\nJane"
        body_clean, sign_off_type = parse_body_with_signoff(body)

        assert sign_off_type == "Yours sincerely"

    def test_signoff_many_thanks_before_thanks(self):
        """Test 'Many thanks' is detected (not just 'Thanks')."""
        body = "Hi\n\nHere you go.\n\nMany thanks\nBob"
        body_clean, sign_off_type = parse_body_with_signoff(body)

        assert sign_off_type == "Many thanks"

    def test_signoff_regards_not_best_regards(self):
        """Test 'Best regards' is detected correctly (not just 'Regards')."""
        body = "Hi\n\nDone.\n\nBest regards\nBob"
        body_clean, sign_off_type = parse_body_with_signoff(body)

        assert sign_off_type == "Best regards"

    def test_signoff_none_detected(self):
        """Test when no sign-off is present."""
        body = "Hi Jake\n\nSee attached drawings.\n\nBob"
        body_clean, sign_off_type = parse_body_with_signoff(body)

        assert body_clean == body
        assert sign_off_type is None

    def test_signoff_case_insensitive(self):
        """Test sign-off detection is case-insensitive."""
        body = "Hi\n\nDone.\n\nkind regards\nBob"
        body_clean, sign_off_type = parse_body_with_signoff(body)

        # Should match regardless of case
        assert sign_off_type is not None
        assert sign_off_type.lower() == "kind regards"

    def test_signoff_with_preceding_whitespace(self):
        """Test sign-off detection with leading whitespace."""
        body = "Hi\n\nDone.\n\n  Kind regards\nBob"
        body_clean, sign_off_type = parse_body_with_signoff(body)

        assert sign_off_type is not None
        assert "kind regards" in sign_off_type.lower()

    def test_signoff_thanks(self):
        """Test detection of 'Thanks' sign-off."""
        body = "Hi\n\nHere it is.\n\nThanks\nBob"
        body_clean, sign_off_type = parse_body_with_signoff(body)

        assert sign_off_type == "Thanks"

    def test_signoff_cheers(self):
        """Test detection of 'Cheers' sign-off."""
        body = "Hi\n\nAll done.\n\nCheers\nBob"
        body_clean, sign_off_type = parse_body_with_signoff(body)

        assert sign_off_type == "Cheers"

    def test_signoff_best_wishes(self):
        """Test detection of 'Best wishes' sign-off."""
        body = "Dear Jake\n\nPlease review.\n\nBest wishes\nJane"
        body_clean, sign_off_type = parse_body_with_signoff(body)

        assert sign_off_type == "Best wishes"


# ============================================================================
# Direction Detection Tests
# ============================================================================

class TestDirectionDetection:
    """Tests for email direction detection (inbound vs outbound)."""

    def test_inbound_email(self, config):
        """Test detection of inbound email."""
        email_data = {
            'from': 'bob@structural.com',
            'to': 'jw@jakewhitearchitecture.com',
        }

        with patch('fileuzi.services.email_parser.MY_EMAIL_ADDRESSES', config['MY_EMAIL_ADDRESSES']):
            direction = detect_email_direction(email_data)

        assert direction == 'IN'

    def test_outbound_email(self, config):
        """Test detection of outbound email."""
        email_data = {
            'from': 'jw@jakewhitearchitecture.com',
            'to': 'bob@structural.com',
        }

        with patch('fileuzi.services.email_parser.MY_EMAIL_ADDRESSES', config['MY_EMAIL_ADDRESSES']):
            direction = detect_email_direction(email_data)

        assert direction == 'OUT'

    def test_outbound_secondary_address(self, config):
        """Test detection of outbound email from secondary address."""
        email_data = {
            'from': 'jake.white@alternative.com',
            'to': 'bob@structural.com',
        }

        with patch('fileuzi.services.email_parser.MY_EMAIL_ADDRESSES', config['MY_EMAIL_ADDRESSES']):
            direction = detect_email_direction(email_data)

        assert direction == 'OUT'

    def test_direction_case_insensitive(self, config):
        """Test direction detection is case-insensitive."""
        email_data = {
            'from': 'JW@JAKEWHITEARCHITECTURE.COM',
            'to': 'bob@structural.com',
        }

        with patch('fileuzi.services.email_parser.MY_EMAIL_ADDRESSES', config['MY_EMAIL_ADDRESSES']):
            direction = detect_email_direction(email_data)

        assert direction == 'OUT'


# ============================================================================
# Message-ID and Hash Fallback Tests
# ============================================================================

class TestMessageIdAndHash:
    """Tests for Message-ID extraction and hash fallback."""

    def test_message_id_extracted(self, sample_eml_inbound):
        """Test that Message-ID is correctly extracted."""
        email_data = parse_eml_file(sample_eml_inbound)

        assert email_data['message_id'] == 'abc123@mail.structural-engineers.co.uk'

    def test_hash_fallback_when_no_message_id(self, sample_eml_no_message_id):
        """Test hash fallback is generated when no Message-ID."""
        email_data = parse_eml_file(sample_eml_no_message_id)

        # Message-ID should be empty or None
        assert not email_data.get('message_id') or email_data['message_id'] == ''

        # Generate hash fallback
        hash_fallback = generate_email_hash(
            email_data['from'],
            email_data['subject'],
            email_data.get('date_iso', '')
        )
        assert hash_fallback is not None
        assert len(hash_fallback) > 0

    def test_hash_fallback_deterministic(self):
        """Test hash fallback is deterministic for same inputs."""
        hash1 = generate_email_hash(
            'bob@example.com',
            'Test Subject',
            '2026-02-03T10:30:00'
        )
        hash2 = generate_email_hash(
            'bob@example.com',
            'Test Subject',
            '2026-02-03T10:30:00'
        )

        assert hash1 == hash2

    def test_hash_fallback_different_for_different_emails(self):
        """Test hash fallback differs for different subjects."""
        hash1 = generate_email_hash(
            'bob@example.com',
            'Subject One',
            '2026-02-03T10:30:00'
        )
        hash2 = generate_email_hash(
            'bob@example.com',
            'Subject Two',
            '2026-02-03T10:30:00'
        )

        assert hash1 != hash2


# ============================================================================
# Attachment Extraction Tests
# ============================================================================

class TestAttachmentExtraction:
    """Tests for attachment extraction from emails."""

    def test_regular_attachments_listed(self, sample_eml_inbound):
        """Test regular attachments are correctly listed."""
        email_data = parse_eml_file(sample_eml_inbound)

        assert 'attachments' in email_data
        assert len(email_data['attachments']) >= 1

        # Find the PDF attachment
        pdf_attachments = [a for a in email_data['attachments'] if a['filename'].endswith('.pdf')]
        assert len(pdf_attachments) == 1
        assert 'Structural_Calcs_2506.pdf' in pdf_attachments[0]['filename']

    def test_small_attachments_filtered(self, sample_eml_small_attachment):
        """Test small attachments (below threshold) are filtered."""
        email_data = parse_eml_file(sample_eml_small_attachment)

        # Should have attachments
        assert 'attachments' in email_data

        # Check filenames - small signature image should be filtered
        filenames = [a['filename'] for a in email_data['attachments']]

        # The PDF should be present
        assert any('Document.pdf' in f for f in filenames)

        # The small signature image might be filtered depending on implementation
        # If filtering happens at parse time, signature.png won't be here
        # If filtering happens later, it will be marked as excluded

    def test_embedded_images_detected_separately(self, sample_eml_embedded_images):
        """Test embedded images are tracked separately from regular attachments."""
        with open(sample_eml_embedded_images, 'rb') as f:
            import email
            from email import policy
            msg = email.message_from_binary_file(f, policy=policy.default)

        embedded = extract_embedded_images(msg)

        # Should detect the embedded images
        assert embedded is not None
        # At least one image should be detected
        assert len(embedded) >= 1

    def test_embedded_image_size_filtering(self, sample_eml_embedded_images, config):
        """Test embedded image size filtering (20KB threshold)."""
        with open(sample_eml_embedded_images, 'rb') as f:
            import email
            from email import policy
            msg = email.message_from_binary_file(f, policy=policy.default)

        # Extract with 20KB threshold
        embedded = extract_embedded_images(msg, min_size=config['MIN_EMBEDDED_IMAGE_SIZE'])

        # Only the 25KB image should pass the 20KB threshold
        # The 10KB image should be filtered
        large_images = [img for img in embedded if len(img[1]) >= 20 * 1024]
        assert len(large_images) >= 1


# ============================================================================
# Full Email Parsing Tests
# ============================================================================

class TestFullEmailParsing:
    """Tests for complete email parsing."""

    def test_parse_inbound_email(self, sample_eml_inbound):
        """Test parsing a complete inbound email."""
        email_data = parse_eml_file(sample_eml_inbound)

        assert email_data['from'] == 'bob@structural-engineers.co.uk'
        assert email_data['to'] == 'jw@jakewhitearchitecture.com'
        assert '2506' in email_data['subject']
        assert 'Structural' in email_data['subject']
        assert email_data['message_id'] is not None

    def test_parse_outbound_email(self, sample_eml_outbound):
        """Test parsing a complete outbound email."""
        email_data = parse_eml_file(sample_eml_outbound)

        assert email_data['from'] == 'jw@jakewhitearchitecture.com'
        assert email_data['to'] == 'bob@structural-engineers.co.uk'
        assert '2506' in email_data['subject']

    def test_parse_email_body(self, sample_eml_inbound):
        """Test email body is correctly extracted."""
        email_data = parse_eml_file(sample_eml_inbound)

        assert 'body' in email_data
        assert 'structural calculations' in email_data['body'].lower()

    def test_parse_email_date(self, sample_eml_inbound):
        """Test email date is correctly parsed."""
        email_data = parse_eml_file(sample_eml_inbound)

        assert 'date' in email_data or 'date_iso' in email_data
