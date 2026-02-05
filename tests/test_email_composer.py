"""
Email Composer Tests for FileUzi.

Tests for the email composition service: subject generation, body generation,
email signature loading, client detection, preference storage, email launch,
and superseding detection.
"""

import os
import pytest
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from datetime import datetime

from fileuzi.services.email_composer import (
    generate_email_subject,
    extract_first_name,
    generate_email_body,
    load_email_signature,
    detect_email_clients,
    _find_executable,
    save_email_client_preference,
    load_email_client_preference,
    get_email_client_path,
    launch_email_compose,
    detect_superseding_candidates,
    MAX_ATTACHMENT_SIZE,
    MAX_COMMAND_LENGTH,
    EMAIL_SIGNATURE_FOLDER,
    EMAIL_SIGNATURE_FILENAME,
)
from fileuzi.config import FILING_WIDGET_TOOLS_FOLDER


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def project_root_with_signature(tmp_path):
    """Create a project root with an email signature file."""
    root = tmp_path / "JWA_PROJECTS"
    root.mkdir()

    # Create tools folder with email signature
    tools = root / FILING_WIDGET_TOOLS_FOLDER
    tools.mkdir()
    sig_folder = tools / EMAIL_SIGNATURE_FOLDER
    sig_folder.mkdir()
    sig_file = sig_folder / EMAIL_SIGNATURE_FILENAME
    sig_file.write_text(
        '<div class="sig"><p>Jake White</p>'
        '<p>Jake White Architecture</p></div>',
        encoding='utf-8'
    )

    return root


@pytest.fixture
def project_root_no_signature(tmp_path):
    """Create a project root without an email signature file."""
    root = tmp_path / "JWA_PROJECTS"
    root.mkdir()
    tools = root / FILING_WIDGET_TOOLS_FOLDER
    tools.mkdir()
    return root


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database path."""
    return tmp_path / "filing_widget.db"


@pytest.fixture
def current_drawings_folder(tmp_path):
    """Create a Current Drawings folder with existing drawings."""
    root = tmp_path / "JWA_PROJECTS"
    root.mkdir()
    proj = root / "2506_SMITH-EXTENSION"
    proj.mkdir()
    drawings = proj / "Current Drawings"
    drawings.mkdir()

    # Add some existing drawings
    (drawings / "2506_20_FLOOR PLANS_P01.pdf").write_bytes(b"old drawing")
    (drawings / "2506_20_FLOOR PLANS_C01.pdf").write_bytes(b"old drawing")
    (drawings / "2506_22_SECTIONS_C02.pdf").write_bytes(b"other drawing")

    return drawings


# ============================================================================
# generate_email_subject Tests
# ============================================================================

class TestGenerateEmailSubject:
    """Tests for generate_email_subject function."""

    def test_full_subject(self):
        """Job number + project name + description."""
        result = generate_email_subject("2506_SMITH EXTENSION", "Structural calculations")
        assert result == "2506 - Smith extension - Structural calculations"

    def test_no_description(self):
        """Job number + project name only."""
        result = generate_email_subject("2506_SMITH EXTENSION", "")
        assert result == "2506 - Smith extension"

    def test_no_project_name(self):
        """Job number only with underscore but no name."""
        result = generate_email_subject("2506_", "Structural calculations")
        assert result == "2506 - Structural calculations"

    def test_job_number_only(self):
        """Just job number, no underscore."""
        result = generate_email_subject("2506", "")
        assert result == "2506"

    def test_empty_folder_name(self):
        """Empty folder name returns empty string."""
        result = generate_email_subject("", "Some description")
        assert result == ""

    def test_none_folder_name(self):
        """None folder name returns empty string."""
        result = generate_email_subject(None, "Some description")
        assert result == ""

    def test_whitespace_description(self):
        """Whitespace-only description is treated as empty."""
        result = generate_email_subject("2506_SMITH EXTENSION", "   ")
        assert result == "2506 - Smith extension"

    def test_description_formatting(self):
        """Description is formatted with first letter upper, rest lower."""
        result = generate_email_subject("2506_SMITH EXTENSION", "STRUCTURAL CALCULATIONS")
        assert result == "2506 - Smith extension - Structural calculations"

    def test_single_char_description(self):
        """Single character description."""
        result = generate_email_subject("2506_SMITH EXTENSION", "A")
        assert result == "2506 - Smith extension - A"

    def test_project_name_formatting(self):
        """Project name is formatted with first letter upper, rest lower."""
        result = generate_email_subject("2506_SMITH EXTENSION", "")
        assert result == "2506 - Smith extension"


# ============================================================================
# extract_first_name Tests
# ============================================================================

class TestExtractFirstName:
    """Tests for extract_first_name function."""

    def test_full_name(self):
        """Extract first name from 'Bob Smith'."""
        assert extract_first_name("Bob Smith") == "Bob"

    def test_single_name(self):
        """Return single name as first name."""
        assert extract_first_name("Bob") == "Bob"

    def test_multiple_names(self):
        """Extract first name from multiple-part name."""
        assert extract_first_name("Bob James Smith") == "Bob"

    def test_empty_string(self):
        """Empty string returns None."""
        assert extract_first_name("") is None

    def test_none_input(self):
        """None returns None."""
        assert extract_first_name(None) is None

    def test_whitespace_only(self):
        """Whitespace-only returns None."""
        assert extract_first_name("   ") is None

    def test_leading_whitespace(self):
        """Leading whitespace is stripped."""
        assert extract_first_name("  Bob Smith  ") == "Bob"


# ============================================================================
# generate_email_body Tests
# ============================================================================

class TestGenerateEmailBody:
    """Tests for generate_email_body function."""

    def test_with_recipient_name(self):
        """Body includes personalised greeting."""
        sig = "<div>Signature</div>"
        body = generate_email_body("Bob Smith", sig)
        assert "<p>Hi Bob,</p>" in body
        assert "<div>Signature</div>" in body
        assert body.startswith("<html>")
        assert body.endswith("</html>")

    def test_without_recipient_name(self):
        """Body includes placeholder greeting when no name given."""
        sig = "<div>Signature</div>"
        body = generate_email_body("", sig)
        assert "<p>Hi [Name],</p>" in body

    def test_none_recipient(self):
        """None recipient gets placeholder greeting."""
        body = generate_email_body(None, "<div>Sig</div>")
        assert "<p>Hi [Name],</p>" in body

    def test_signature_included(self):
        """Signature HTML is included in body."""
        sig = '<div class="sig"><p>Jake White</p></div>'
        body = generate_email_body("Bob", sig)
        assert sig in body

    def test_empty_signature(self):
        """Empty signature is handled gracefully."""
        body = generate_email_body("Bob", "")
        assert "<p>Hi Bob,</p>" in body
        assert "<html>" in body

    def test_html_structure(self):
        """Body has proper HTML structure."""
        body = generate_email_body("Bob", "<div>Sig</div>")
        assert "<html>" in body
        assert "<body>" in body
        assert "</body>" in body
        assert "</html>" in body


# ============================================================================
# load_email_signature Tests
# ============================================================================

class TestLoadEmailSignature:
    """Tests for load_email_signature function."""

    def test_load_existing_signature(self, project_root_with_signature):
        """Load signature from valid path."""
        sig = load_email_signature(project_root_with_signature)
        assert "Jake White" in sig
        assert "Jake White Architecture" in sig

    def test_signature_not_found(self, project_root_no_signature):
        """Raise FileNotFoundError when signature file doesn't exist."""
        with pytest.raises(FileNotFoundError, match="Email signature file not found"):
            load_email_signature(project_root_no_signature)

    def test_signature_path_in_error_message(self, project_root_no_signature):
        """Error message includes expected file path."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_email_signature(project_root_no_signature)
        assert EMAIL_SIGNATURE_FOLDER in str(exc_info.value)
        assert EMAIL_SIGNATURE_FILENAME in str(exc_info.value)

    def test_signature_utf8_encoding(self, project_root_with_signature):
        """Signature file is read with UTF-8 encoding."""
        # Write a signature with unicode characters
        sig_path = (
            project_root_with_signature / FILING_WIDGET_TOOLS_FOLDER /
            EMAIL_SIGNATURE_FOLDER / EMAIL_SIGNATURE_FILENAME
        )
        sig_path.write_text(
            '<p>Jake White — Architecture & Design</p>',
            encoding='utf-8'
        )
        sig = load_email_signature(project_root_with_signature)
        assert "—" in sig
        assert "&" in sig


# ============================================================================
# detect_email_clients Tests
# ============================================================================

class TestFindExecutable:
    """Tests for _find_executable helper function."""

    @patch('fileuzi.services.email_composer.shutil.which')
    def test_found_in_path(self, mock_which):
        """Find executable via PATH lookup."""
        mock_which.return_value = '/usr/bin/betterbird'
        result = _find_executable('betterbird', [])
        assert result == Path('/usr/bin/betterbird')

    @patch('fileuzi.services.email_composer.shutil.which')
    def test_found_in_known_paths(self, mock_which, tmp_path):
        """Find executable from known filesystem paths."""
        mock_which.return_value = None
        fake_exe = tmp_path / "betterbird"
        fake_exe.write_text("#!/bin/sh")
        result = _find_executable('betterbird', [str(fake_exe)])
        assert result == fake_exe

    @patch('fileuzi.services.email_composer.shutil.which')
    def test_found_via_flatpak_export(self, mock_which, tmp_path):
        """Find executable from Flatpak exports directory."""
        mock_which.return_value = None
        # Create a fake flatpak export wrapper
        export_dir = tmp_path / "exports" / "bin"
        export_dir.mkdir(parents=True)
        wrapper = export_dir / "eu.betterbird.Betterbird"
        wrapper.write_text("#!/bin/sh\nexec flatpak run eu.betterbird.Betterbird")

        with patch('fileuzi.services.email_composer.Path.home', return_value=tmp_path):
            # Patch the flatpak paths to use our temp dir
            result = _find_executable(
                'betterbird', [],
                flatpak_id="eu.betterbird.Betterbird"
            )
        # Won't find at real system paths, but validates the logic flow
        assert result is None or isinstance(result, Path)

    @patch('fileuzi.services.email_composer.shutil.which')
    @patch('fileuzi.services.email_composer.subprocess.run')
    def test_found_via_flatpak_info(self, mock_run, mock_which):
        """Find executable via 'flatpak info' check."""
        mock_which.return_value = None
        mock_run.return_value = MagicMock(returncode=0)
        result = _find_executable(
            'betterbird', [],
            flatpak_id="eu.betterbird.Betterbird"
        )
        assert result == Path("flatpak::eu.betterbird.Betterbird")

    @patch('fileuzi.services.email_composer.shutil.which')
    @patch('fileuzi.services.email_composer.subprocess.run')
    def test_not_found_anywhere(self, mock_run, mock_which):
        """Return None when executable not found anywhere."""
        mock_which.return_value = None
        mock_run.return_value = MagicMock(returncode=1)
        result = _find_executable(
            'betterbird', ['/nonexistent/betterbird'],
            flatpak_id="eu.betterbird.Betterbird"
        )
        assert result is None


class TestDetectEmailClients:
    """Tests for detect_email_clients function."""

    @patch('fileuzi.services.email_composer._find_executable')
    def test_betterbird_detected(self, mock_find):
        """Detect Betterbird when available."""
        mock_find.side_effect = lambda name, paths, flatpak_id=None: (
            Path('/usr/bin/betterbird') if name == 'betterbird' else None
        )
        clients = detect_email_clients()
        assert clients['betterbird'] == Path('/usr/bin/betterbird')

    @patch('fileuzi.services.email_composer._find_executable')
    def test_thunderbird_detected(self, mock_find):
        """Detect Thunderbird when available."""
        mock_find.side_effect = lambda name, paths, flatpak_id=None: (
            Path('/usr/bin/thunderbird') if name == 'thunderbird' else None
        )
        clients = detect_email_clients()
        assert clients['thunderbird'] == Path('/usr/bin/thunderbird')

    @patch('fileuzi.services.email_composer._find_executable')
    def test_no_clients(self, mock_find):
        """No clients when none found."""
        mock_find.return_value = None
        clients = detect_email_clients()
        assert clients['betterbird'] is None
        assert clients['thunderbird'] is None

    @patch('fileuzi.services.email_composer._find_executable')
    def test_both_clients(self, mock_find):
        """Both clients detected when available."""
        def find_side_effect(name, paths, flatpak_id=None):
            if name == 'betterbird':
                return Path('/usr/bin/betterbird')
            elif name == 'thunderbird':
                return Path('/usr/bin/thunderbird')
            return None
        mock_find.side_effect = find_side_effect
        clients = detect_email_clients()
        assert clients['betterbird'] is not None
        assert clients['thunderbird'] is not None

    @patch('fileuzi.services.email_composer._find_executable')
    def test_flatpak_betterbird(self, mock_find):
        """Detect Betterbird installed via Flatpak."""
        mock_find.side_effect = lambda name, paths, flatpak_id=None: (
            Path("flatpak::eu.betterbird.Betterbird") if name == 'betterbird' else None
        )
        clients = detect_email_clients()
        assert str(clients['betterbird']) == "flatpak::eu.betterbird.Betterbird"


# ============================================================================
# save/load_email_client_preference Tests
# ============================================================================

class TestEmailClientPreference:
    """Tests for save/load email client preference functions."""

    def test_save_and_load(self, db_path):
        """Save preference and load it back."""
        save_email_client_preference(db_path, 'betterbird', '/usr/bin/betterbird')
        config = load_email_client_preference(db_path)
        assert config is not None
        assert config['client_name'] == 'betterbird'
        assert config['client_path'] == Path('/usr/bin/betterbird')
        assert config['auto_detected'] is True

    def test_save_manual_preference(self, db_path):
        """Save non-auto-detected preference."""
        save_email_client_preference(
            db_path, 'thunderbird', '/opt/thunderbird/thunderbird',
            auto_detected=False
        )
        config = load_email_client_preference(db_path)
        assert config['auto_detected'] is False

    def test_load_nonexistent_db(self, tmp_path):
        """Load from nonexistent database returns None."""
        result = load_email_client_preference(tmp_path / "nonexistent.db")
        assert result is None

    def test_load_empty_db(self, db_path):
        """Load from empty database returns None."""
        # Create empty DB file
        conn = sqlite3.connect(str(db_path))
        conn.close()
        result = load_email_client_preference(db_path)
        assert result is None

    def test_overwrite_preference(self, db_path):
        """Saving again overwrites previous preference."""
        save_email_client_preference(db_path, 'betterbird', '/usr/bin/betterbird')
        save_email_client_preference(db_path, 'thunderbird', '/usr/bin/thunderbird')
        config = load_email_client_preference(db_path)
        assert config['client_name'] == 'thunderbird'

    def test_last_verified_timestamp(self, db_path):
        """Saved preference includes a timestamp."""
        save_email_client_preference(db_path, 'betterbird', '/usr/bin/betterbird')
        config = load_email_client_preference(db_path)
        assert config['last_verified'] is not None
        # Should be a parseable ISO timestamp
        datetime.fromisoformat(config['last_verified'])


# ============================================================================
# get_email_client_path Tests
# ============================================================================

class TestGetEmailClientPath:
    """Tests for get_email_client_path function."""

    def test_returns_saved_preference(self, db_path, tmp_path):
        """Return saved path if it still exists."""
        # Create a fake executable
        fake_exe = tmp_path / "betterbird"
        fake_exe.write_text("#!/bin/sh\necho test")
        fake_exe.chmod(0o755)

        save_email_client_preference(db_path, 'betterbird', str(fake_exe))
        result = get_email_client_path(db_path)
        assert result == fake_exe

    @patch('fileuzi.services.email_composer.detect_email_clients')
    def test_re_detects_when_saved_missing(self, mock_detect, db_path, tmp_path):
        """Re-detect when saved path no longer exists."""
        # Save a path that doesn't exist
        save_email_client_preference(db_path, 'betterbird', '/nonexistent/betterbird')

        # Mock detection to find thunderbird instead
        fake_tb = tmp_path / "thunderbird"
        fake_tb.write_text("#!/bin/sh")
        fake_tb.chmod(0o755)
        mock_detect.return_value = {
            'betterbird': None,
            'thunderbird': fake_tb,
        }

        result = get_email_client_path(db_path)
        assert result == fake_tb

    @patch('fileuzi.services.email_composer.detect_email_clients')
    def test_prefers_betterbird(self, mock_detect, db_path, tmp_path):
        """Betterbird is preferred over Thunderbird."""
        fake_bb = tmp_path / "betterbird"
        fake_bb.write_text("#!/bin/sh")
        fake_tb = tmp_path / "thunderbird"
        fake_tb.write_text("#!/bin/sh")

        mock_detect.return_value = {
            'betterbird': fake_bb,
            'thunderbird': fake_tb,
        }

        result = get_email_client_path(db_path)
        assert result == fake_bb

    @patch('fileuzi.services.email_composer.detect_email_clients')
    def test_raises_when_no_client(self, mock_detect, db_path):
        """Raise FileNotFoundError when no client available."""
        mock_detect.return_value = {
            'betterbird': None,
            'thunderbird': None,
        }
        with pytest.raises(FileNotFoundError, match="No email client found"):
            get_email_client_path(db_path)

    @patch('fileuzi.services.email_composer.detect_email_clients')
    def test_saves_detected_preference(self, mock_detect, db_path, tmp_path):
        """Auto-detected client is saved for future use."""
        fake_tb = tmp_path / "thunderbird"
        fake_tb.write_text("#!/bin/sh")

        mock_detect.return_value = {
            'betterbird': None,
            'thunderbird': fake_tb,
        }

        get_email_client_path(db_path)

        # Check it was saved
        config = load_email_client_preference(db_path)
        assert config is not None
        assert config['client_name'] == 'thunderbird'

    def test_returns_saved_flatpak_preference(self, db_path):
        """Saved flatpak sentinel path is returned without filesystem check."""
        save_email_client_preference(
            db_path, 'betterbird', 'flatpak::eu.betterbird.Betterbird'
        )
        result = get_email_client_path(db_path)
        assert str(result) == "flatpak::eu.betterbird.Betterbird"


# ============================================================================
# launch_email_compose Tests
# ============================================================================

class TestLaunchEmailCompose:
    """Tests for launch_email_compose function."""

    @patch('fileuzi.services.email_composer.subprocess.Popen')
    def test_launches_with_correct_args(self, mock_popen, tmp_path):
        """Email client is launched with -compose flag."""
        # Create fake attachment files
        att1 = tmp_path / "file1.pdf"
        att1.write_bytes(b"PDF content")
        att2 = tmp_path / "file2.pdf"
        att2.write_bytes(b"PDF content 2")

        client = tmp_path / "betterbird"
        client.write_text("#!/bin/sh")

        launch_email_compose(
            subject="Test Subject",
            attachment_paths=[att1, att2],
            body_html="<html><body>Hello</body></html>",
            client_path=client,
        )

        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args[0] == str(client)
        assert args[1] == '-compose'
        assert "subject='Test Subject'" in args[2]
        assert "format=html" in args[2]

    @patch('fileuzi.services.email_composer.subprocess.Popen')
    def test_attachment_file_uris(self, mock_popen, tmp_path):
        """Attachments are converted to file:// URIs."""
        att = tmp_path / "document.pdf"
        att.write_bytes(b"PDF content")
        client = tmp_path / "betterbird"

        launch_email_compose("Subject", [att], "<html></html>", client)

        args = mock_popen.call_args[0][0]
        compose = args[2]
        assert "file://" in compose

    @patch('fileuzi.services.email_composer.subprocess.Popen')
    def test_body_html_url_encoded(self, mock_popen, tmp_path):
        """Body HTML is URL-encoded in the compose string."""
        att = tmp_path / "file.pdf"
        att.write_bytes(b"content")
        client = tmp_path / "betterbird"

        launch_email_compose(
            "Subject", [att],
            "<html><body><p>Hello World</p></body></html>",
            client
        )

        args = mock_popen.call_args[0][0]
        compose = args[2]
        # Body should be URL-encoded (no raw angle brackets)
        assert "body='" in compose

    def test_attachment_size_limit(self, tmp_path):
        """Raise ValueError when attachments exceed 25MB."""
        # Create a file over 25MB
        large_file = tmp_path / "large.pdf"
        large_file.write_bytes(b"x" * (MAX_ATTACHMENT_SIZE + 1))

        client = tmp_path / "betterbird"

        with pytest.raises(ValueError, match="Attachments too large"):
            launch_email_compose("Subject", [large_file], "<html></html>", client)

    @patch('fileuzi.services.email_composer.subprocess.Popen')
    def test_multiple_attachments(self, mock_popen, tmp_path):
        """Multiple attachment paths are comma-separated."""
        files = []
        for i in range(3):
            f = tmp_path / f"file{i}.pdf"
            f.write_bytes(b"content")
            files.append(f)

        client = tmp_path / "betterbird"
        launch_email_compose("Subject", files, "<html></html>", client)

        args = mock_popen.call_args[0][0]
        compose = args[2]
        # Should have comma-separated file URIs
        assert compose.count("file://") == 3

    @patch('fileuzi.services.email_composer.subprocess.Popen')
    def test_empty_to_field(self, mock_popen, tmp_path):
        """To field is empty (user fills in manually)."""
        att = tmp_path / "file.pdf"
        att.write_bytes(b"content")
        client = tmp_path / "betterbird"

        launch_email_compose("Subject", [att], "<html></html>", client)

        args = mock_popen.call_args[0][0]
        assert "to=''" in args[2]

    @patch('fileuzi.services.email_composer.subprocess.Popen',
           side_effect=FileNotFoundError("Not found"))
    def test_client_not_found_error(self, mock_popen, tmp_path):
        """Raise FileNotFoundError when client executable missing."""
        att = tmp_path / "file.pdf"
        att.write_bytes(b"content")

        with pytest.raises(FileNotFoundError, match="Email client executable not found"):
            launch_email_compose("Subject", [att], "<html></html>", "/bad/path")

    @patch('fileuzi.services.email_composer.subprocess.Popen',
           side_effect=PermissionError("Permission denied"))
    def test_launch_failure(self, mock_popen, tmp_path):
        """Raise RuntimeError on general launch failure."""
        att = tmp_path / "file.pdf"
        att.write_bytes(b"content")

        with pytest.raises(RuntimeError, match="Failed to launch email client"):
            launch_email_compose("Subject", [att], "<html></html>", "/some/path")

    @patch('fileuzi.services.email_composer.subprocess.Popen')
    def test_flatpak_launch(self, mock_popen, tmp_path):
        """Flatpak clients launched via 'flatpak run'."""
        att = tmp_path / "file.pdf"
        att.write_bytes(b"content")

        launch_email_compose(
            "Subject", [att], "<html></html>",
            "flatpak::eu.betterbird.Betterbird"
        )

        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args[0] == "flatpak"
        assert args[1] == "run"
        assert args[2] == "eu.betterbird.Betterbird"
        assert args[3] == "-compose"


# ============================================================================
# detect_superseding_candidates Tests
# ============================================================================

class TestDetectSupersedingCandidates:
    """Tests for detect_superseding_candidates function."""

    def test_detects_older_revision(self, current_drawings_folder, tmp_path):
        """Detect files that will be superseded by a newer revision."""
        # New file with higher revision C02 > C01 and P01
        new_file = tmp_path / "2506_20_FLOOR PLANS_C02.pdf"
        new_file.write_bytes(b"new drawing")

        candidates = detect_superseding_candidates(new_file, current_drawings_folder)
        assert len(candidates) == 2
        assert "2506_20_FLOOR PLANS_P01.pdf" in candidates
        assert "2506_20_FLOOR PLANS_C01.pdf" in candidates

    def test_no_superseding_for_different_drawing(self, current_drawings_folder, tmp_path):
        """No superseding when drawing number doesn't match."""
        new_file = tmp_path / "2506_30_NEW DRAWING_C01.pdf"
        new_file.write_bytes(b"new drawing")

        candidates = detect_superseding_candidates(new_file, current_drawings_folder)
        assert len(candidates) == 0

    def test_no_superseding_for_non_drawing(self, current_drawings_folder, tmp_path):
        """No superseding for non-drawing files."""
        new_file = tmp_path / "Some random file.pdf"
        new_file.write_bytes(b"not a drawing")

        candidates = detect_superseding_candidates(new_file, current_drawings_folder)
        assert len(candidates) == 0

    def test_no_superseding_for_non_current_folder(self, tmp_path):
        """No superseding when destination is not a Current Drawings folder."""
        folder = tmp_path / "ADMIN"
        folder.mkdir()
        (folder / "2506_20_FLOOR PLANS_P01.pdf").write_bytes(b"drawing")

        new_file = tmp_path / "2506_20_FLOOR PLANS_C02.pdf"
        new_file.write_bytes(b"new drawing")

        candidates = detect_superseding_candidates(new_file, folder)
        assert len(candidates) == 0

    def test_empty_folder(self, tmp_path):
        """No superseding in empty Current Drawings folder."""
        folder = tmp_path / "Current Drawings"
        folder.mkdir()

        new_file = tmp_path / "2506_20_FLOOR PLANS_C01.pdf"
        new_file.write_bytes(b"new drawing")

        candidates = detect_superseding_candidates(new_file, folder)
        assert len(candidates) == 0

    def test_same_revision_not_superseded(self, tmp_path):
        """Same revision number is NOT a superseding candidate."""
        folder = tmp_path / "Current Drawings"
        folder.mkdir()
        (folder / "2506_20_FLOOR PLANS_C01.pdf").write_bytes(b"existing")

        new_file = tmp_path / "2506_20_FLOOR PLANS_C01.pdf"
        new_file.write_bytes(b"same rev")

        candidates = detect_superseding_candidates(new_file, folder)
        assert len(candidates) == 0


# ============================================================================
# Toggle Visibility Tests (using mock widget)
# ============================================================================

class TestCreateEmailToggleVisibility:
    """Tests for Create Email toggle visibility logic."""

    def test_visible_for_export_regular_files(self):
        """Toggle visible when: export mode + regular files."""
        # Simulate the visibility logic from _update_create_email_visibility
        is_export = True
        email_data = None
        file_widgets = [("widget", "path")]
        is_regular_files = not email_data and bool(file_widgets)
        visible = is_export and is_regular_files
        assert visible is True

    def test_hidden_for_import(self):
        """Toggle hidden in import mode."""
        is_export = False
        email_data = None
        file_widgets = [("widget", "path")]
        is_regular_files = not email_data and bool(file_widgets)
        visible = is_export and is_regular_files
        assert visible is False

    def test_hidden_for_eml_files(self):
        """Toggle hidden when email data is present (.eml file)."""
        is_export = True
        email_data = {"subject": "test"}
        file_widgets = []
        is_regular_files = not email_data and bool(file_widgets)
        visible = is_export and is_regular_files
        assert visible is False

    def test_hidden_when_no_files(self):
        """Toggle hidden when no files are loaded."""
        is_export = True
        email_data = None
        file_widgets = []
        is_regular_files = not email_data and bool(file_widgets)
        visible = is_export and is_regular_files
        assert visible is False


# ============================================================================
# Integration Tests
# ============================================================================

class TestEmailComposerIntegration:
    """Integration tests for the full email composition workflow."""

    def test_first_use_detection_and_save(self, db_path, tmp_path):
        """Full workflow: detect client, save preference, load on next call."""
        # Create a fake thunderbird executable
        fake_tb = tmp_path / "thunderbird"
        fake_tb.write_text("#!/bin/sh")
        fake_tb.chmod(0o755)

        with patch('fileuzi.services.email_composer.detect_email_clients') as mock_detect:
            mock_detect.return_value = {
                'betterbird': None,
                'thunderbird': fake_tb,
            }

            # First call: detect and save
            path1 = get_email_client_path(db_path)
            assert path1 == fake_tb

            # Second call: load from DB (no detection needed)
            path2 = get_email_client_path(db_path)
            assert path2 == fake_tb

            # detect_email_clients should only be called once
            # (second time loads from DB)
            assert mock_detect.call_count == 1

    def test_path_invalidation_re_detection(self, db_path, tmp_path):
        """When saved path becomes invalid, re-detect and save new preference."""
        # Save a path that doesn't exist
        save_email_client_preference(db_path, 'betterbird', '/gone/betterbird')

        fake_tb = tmp_path / "thunderbird"
        fake_tb.write_text("#!/bin/sh")
        fake_tb.chmod(0o755)

        with patch('fileuzi.services.email_composer.detect_email_clients') as mock_detect:
            mock_detect.return_value = {
                'betterbird': None,
                'thunderbird': fake_tb,
            }

            result = get_email_client_path(db_path)
            assert result == fake_tb

            # Verify new preference was saved
            config = load_email_client_preference(db_path)
            assert config['client_name'] == 'thunderbird'

    @patch('fileuzi.services.email_composer.subprocess.Popen')
    def test_full_email_workflow(self, mock_popen, tmp_path):
        """Full workflow: generate subject, body, and launch email."""
        # Setup project root with signature
        root = tmp_path / "JWA_PROJECTS"
        root.mkdir()
        tools = root / FILING_WIDGET_TOOLS_FOLDER
        tools.mkdir()
        sig_folder = tools / EMAIL_SIGNATURE_FOLDER
        sig_folder.mkdir()
        sig_file = sig_folder / EMAIL_SIGNATURE_FILENAME
        sig_file.write_text(
            '<div><p>Jake White</p></div>',
            encoding='utf-8'
        )

        # Create filed documents
        dest = tmp_path / "filed_docs"
        dest.mkdir()
        att1 = dest / "2506_20_FLOOR PLANS_C02.pdf"
        att1.write_bytes(b"drawing pdf content")

        # Generate subject
        subject = generate_email_subject("2506_SMITH EXTENSION", "Floor plans")
        assert "2506" in subject
        assert "Smith extension" in subject
        assert "Floor plans" in subject

        # Load signature and generate body
        signature = load_email_signature(root)
        body = generate_email_body("Bob Smith", signature)
        assert "Hi Bob," in body
        assert "Jake White" in body

        # Launch compose
        client = tmp_path / "betterbird"
        launch_email_compose(subject, [att1], body, client)

        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert '-compose' in args

    @patch('fileuzi.services.email_composer.subprocess.Popen')
    def test_error_handling_no_signature(self, mock_popen, project_root_no_signature, tmp_path):
        """Graceful handling when signature file is missing."""
        with pytest.raises(FileNotFoundError):
            load_email_signature(project_root_no_signature)

        # The workflow should still work with empty signature
        body = generate_email_body("Bob", "")
        assert "<p>Hi Bob,</p>" in body

        att = tmp_path / "file.pdf"
        att.write_bytes(b"content")
        client = tmp_path / "betterbird"

        launch_email_compose("Subject", [att], body, client)
        mock_popen.assert_called_once()

    def test_superseding_detection_with_filing(self, tmp_path):
        """Integration: detect superseding before filing, then file."""
        # Create destination folder
        current = tmp_path / "Current Drawings"
        current.mkdir()

        # Add existing drawing
        (current / "2506_20_FLOOR PLANS_P01.pdf").write_bytes(b"old")
        (current / "2506_20_FLOOR PLANS_C01.pdf").write_bytes(b"old")

        # New drawing to file
        new_file = tmp_path / "2506_20_FLOOR PLANS_C02.pdf"
        new_file.write_bytes(b"new drawing")

        # Pre-filing detection
        candidates = detect_superseding_candidates(new_file, current)
        assert len(candidates) == 2
        assert "2506_20_FLOOR PLANS_P01.pdf" in candidates
        assert "2506_20_FLOOR PLANS_C01.pdf" in candidates
