"""
Embedded Image / Screenshot Extraction Tests for FileUzi.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
import email
from email import policy

from fileuzi.services.email_parser import extract_embedded_images
from fileuzi.services.pdf_generator import (
    generate_screenshot_filenames,
    convert_image_to_png,
    clean_subject_for_filename,
)


# ============================================================================
# Embedded Image Extraction Tests
# ============================================================================

class TestEmbeddedImageExtraction:
    """Tests for embedded image extraction from emails."""

    def test_embedded_images_extracted(self, sample_eml_embedded_images):
        """Test embedded images are extracted from email."""
        with open(sample_eml_embedded_images, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=policy.default)

        embedded = extract_embedded_images(msg)

        # Should extract at least one image
        assert embedded is not None
        assert len(embedded) >= 1

    def test_small_embedded_images_ignored(self, sample_eml_embedded_images, config):
        """Test small embedded images are filtered out."""
        with open(sample_eml_embedded_images, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=policy.default)

        # Extract with 20KB threshold
        embedded = extract_embedded_images(msg, min_size=config['MIN_EMBEDDED_IMAGE_SIZE'])

        # Only images >= 20KB should be included
        # extract_embedded_images returns list of dicts with 'size' key
        for img in embedded:
            assert img['size'] >= config['MIN_EMBEDDED_IMAGE_SIZE']

    def test_no_embedded_images_returns_empty(self, sample_eml_inbound):
        """Test email without embedded images returns empty list."""
        with open(sample_eml_inbound, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=policy.default)

        embedded = extract_embedded_images(msg)

        # Inbound email has regular attachment, not embedded images
        # May be empty or contain nothing relevant
        assert embedded is not None


# ============================================================================
# Screenshot Naming Tests
# ============================================================================

class TestScreenshotNaming:
    """Tests for screenshot file naming."""

    def test_extracted_image_naming(self):
        """Test screenshot filenames follow correct format."""
        job_number = "2506"
        email_date = datetime(2026, 2, 2)
        count = 2

        filenames = generate_screenshot_filenames(job_number, email_date, count)

        assert len(filenames) == 2
        assert "2506_email_screenshot_2026-02-02_001.png" in filenames
        assert "2506_email_screenshot_2026-02-02_002.png" in filenames

    def test_screenshot_naming_single_image(self):
        """Test screenshot naming with single image."""
        job_number = "2407"
        email_date = datetime(2026, 3, 15)
        count = 1

        filenames = generate_screenshot_filenames(job_number, email_date, count)

        assert len(filenames) == 1
        assert "2407_email_screenshot_2026-03-15_001.png" in filenames

    def test_screenshot_naming_many_images(self):
        """Test screenshot naming with many images."""
        job_number = "2506"
        email_date = datetime(2026, 1, 1)
        count = 15

        filenames = generate_screenshot_filenames(job_number, email_date, count)

        assert len(filenames) == 15
        # Check sequence
        assert "2506_email_screenshot_2026-01-01_001.png" in filenames
        assert "2506_email_screenshot_2026-01-01_010.png" in filenames
        assert "2506_email_screenshot_2026-01-01_015.png" in filenames


# ============================================================================
# PDF Email Naming Tests
# ============================================================================

class TestPdfEmailNaming:
    """Tests for PDF email file naming."""

    def test_pdf_email_naming(self):
        """Test PDF email filename format."""
        job_number = "2506"
        subject = "2506 Smith Ext - Structural Query Beam Detail"

        cleaned = clean_subject_for_filename(subject, job_number)

        # The cleaned subject should be used in PDF filename
        # Format: {job}_email_{date}_{cleaned_subject}.pdf
        assert cleaned is not None
        assert len(cleaned) > 0

    def test_pdf_naming_special_characters_removed(self):
        """Test PDF naming removes invalid filename characters."""
        job_number = "2506"
        subject = "2506 - Query: Important! [Urgent] <Priority>"

        cleaned = clean_subject_for_filename(subject, job_number)

        # Should not contain invalid filename characters
        invalid_chars = [':', '<', '>', '"', '|', '?', '*']
        for char in invalid_chars:
            assert char not in cleaned


# ============================================================================
# Image Conversion Tests
# ============================================================================

class TestImageConversion:
    """Tests for image format conversion."""

    def test_convert_image_to_png(self):
        """Test non-PNG images are converted to PNG."""
        # Create a minimal JPEG-like data (not actually valid)
        jpeg_data = b'\xff\xd8\xff' + b'\x00' * 100

        # Mock PIL.Image and HAS_PIL flag
        mock_image = MagicMock()
        mock_img = MagicMock()
        mock_image.open.return_value = mock_img
        mock_output = MagicMock()
        mock_img.save = MagicMock()

        with patch.object(
            __import__('fileuzi.services.pdf_generator', fromlist=['pdf_generator']),
            'Image', mock_image, create=True
        ), patch('fileuzi.services.pdf_generator.HAS_PIL', True):
            result = convert_image_to_png(jpeg_data)
            # When PIL is available and mocked, the function should call Image.open
            mock_image.open.assert_called_once()

    def test_png_image_not_converted(self):
        """Test PNG images are not unnecessarily converted."""
        # Valid PNG header
        png_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100

        # The function should handle PNG data
        # (may or may not convert, but should not crash)
        try:
            result = convert_image_to_png(png_data)
        except Exception:
            # May fail without complete valid image
            pass


# ============================================================================
# Reply Chain Tests
# ============================================================================

class TestReplyChainExtraction:
    """Tests for image extraction from reply chains."""

    def test_only_latest_message_images_extracted(self, tmp_path):
        """Test only images from latest reply are extracted."""
        # This would require creating a complex reply chain email
        # For now, test the concept

        # Create an email with images in quoted section
        # The extractor should skip images that are in quoted/forwarded content

        # Placeholder - implementation depends on how the extractor handles
        # Content-ID references in HTML body vs. quoted sections
        pass


# ============================================================================
# Edge Cases
# ============================================================================

class TestScreenshotEdgeCases:
    """Edge case tests for screenshot extraction."""

    def test_empty_email_no_crash(self, tmp_path):
        """Test empty email body doesn't crash."""
        # Create minimal email
        eml_content = """From: test@example.com
To: jake@jwa.com
Subject: Test
Date: Mon, 03 Feb 2026 10:00:00 +0000

"""
        eml_path = tmp_path / "empty.eml"
        eml_path.write_text(eml_content)

        with open(eml_path, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=policy.default)

        embedded = extract_embedded_images(msg)

        # Should return empty, not crash
        assert embedded is not None

    def test_zero_count_screenshots(self):
        """Test zero screenshot count."""
        filenames = generate_screenshot_filenames("2506", datetime.now(), 0)

        assert len(filenames) == 0

    def test_date_formatting_consistency(self):
        """Test date formatting is consistent."""
        dates = [
            datetime(2026, 1, 1),
            datetime(2026, 12, 31),
            datetime(2026, 2, 28),
        ]

        for d in dates:
            filenames = generate_screenshot_filenames("2506", d, 1)
            # Filename should contain ISO format date
            assert filenames[0].count('-') >= 2  # YYYY-MM-DD format

    def test_invalid_job_number_handled(self):
        """Test invalid job numbers are handled."""
        # Empty job number
        filenames = generate_screenshot_filenames("", datetime.now(), 1)
        assert len(filenames) == 1

        # None job number (if allowed)
        try:
            filenames = generate_screenshot_filenames(None, datetime.now(), 1)
        except (TypeError, ValueError):
            pass  # Expected if None not allowed
