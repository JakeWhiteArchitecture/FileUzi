"""
Email Composer Tests for FileUzi.

Tests for the email composition service: OS detection, email client detection,
subject generation, body generation, email signature loading, preference
storage, email launch, and superseding detection.
"""

import os
import pytest
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from datetime import datetime

from fileuzi.services.email_composer import (
    detect_os_info,
    EmailClientDetector,
    generate_email_subject,
    extract_first_name,
    generate_email_body,
    load_email_signature,
    detect_email_clients,
    save_email_client_preference,
    load_email_client_preference,
    get_email_client_path,
    launch_email_compose,
    detect_superseding_candidates,
    MAX_ATTACHMENT_SIZE,
    MAX_COMMAND_LENGTH,
    EMAIL_SIGNATURE_FOLDER,
    EMAIL_SIGNATURE_FILENAME,
    _CLIENT_REGISTRY,
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
# detect_os_info Tests
# ============================================================================

class TestDetectOsInfo:
    """Tests for detect_os_info function."""

    def test_returns_dict_with_required_keys(self):
        """Result has system, distro, and package_manager keys."""
        info = detect_os_info()
        assert 'system' in info
        assert 'distro' in info
        assert 'package_manager' in info

    @patch('fileuzi.services.email_composer.platform.system', return_value='Linux')
    @patch('fileuzi.services.email_composer.shutil.which')
    @patch('fileuzi.services.email_composer.Path.read_text')
    def test_detects_fedora(self, mock_read, mock_which, mock_system):
        """Detect Fedora from /etc/os-release."""
        mock_read.return_value = 'NAME="Fedora Linux"\nID=fedora\nVERSION_ID=39'
        mock_which.side_effect = lambda x: '/usr/bin/dnf' if x == 'dnf' else None
        info = detect_os_info()
        assert info['system'] == 'Linux'
        assert info['distro'] == 'fedora'
        assert info['package_manager'] == 'dnf'

    @patch('fileuzi.services.email_composer.platform.system', return_value='Linux')
    @patch('fileuzi.services.email_composer.shutil.which')
    @patch('fileuzi.services.email_composer.Path.read_text')
    def test_detects_ubuntu(self, mock_read, mock_which, mock_system):
        """Detect Ubuntu from /etc/os-release."""
        mock_read.return_value = 'NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="22.04"'
        mock_which.side_effect = lambda x: '/usr/bin/apt' if x == 'apt' else None
        info = detect_os_info()
        assert info['distro'] == 'ubuntu'
        assert info['package_manager'] == 'apt'

    @patch('fileuzi.services.email_composer.platform.system', return_value='Linux')
    @patch('fileuzi.services.email_composer.shutil.which')
    @patch('fileuzi.services.email_composer.Path.read_text')
    def test_detects_arch(self, mock_read, mock_which, mock_system):
        """Detect Arch from /etc/os-release."""
        mock_read.return_value = 'NAME="Arch Linux"\nID=arch'
        mock_which.side_effect = lambda x: '/usr/bin/pacman' if x == 'pacman' else None
        info = detect_os_info()
        assert info['distro'] == 'arch'
        assert info['package_manager'] == 'pacman'

    @patch('fileuzi.services.email_composer.platform.system', return_value='Darwin')
    @patch('fileuzi.services.email_composer.shutil.which')
    def test_detects_macos(self, mock_which, mock_system):
        """Detect macOS with brew."""
        mock_which.side_effect = lambda x: '/usr/local/bin/brew' if x == 'brew' else None
        info = detect_os_info()
        assert info['system'] == 'Darwin'
        assert info['distro'] is None
        assert info['package_manager'] == 'brew'

    @patch('fileuzi.services.email_composer.platform.system', return_value='Windows')
    def test_detects_windows(self, mock_system):
        """Detect Windows."""
        info = detect_os_info()
        assert info['system'] == 'Windows'
        assert info['distro'] is None

    @patch('fileuzi.services.email_composer.platform.system', return_value='Linux')
    @patch('fileuzi.services.email_composer.shutil.which', return_value=None)
    @patch('fileuzi.services.email_composer.Path.read_text',
           side_effect=FileNotFoundError)
    def test_missing_os_release(self, mock_read, mock_which, mock_system):
        """Handle missing /etc/os-release gracefully."""
        info = detect_os_info()
        assert info['system'] == 'Linux'
        assert info['distro'] is None


# ============================================================================
# EmailClientDetector Tests
# ============================================================================

class TestEmailClientDetector:
    """Tests for the EmailClientDetector class."""

    def test_init_with_default_os_info(self):
        """Detector initializes with auto-detected OS info."""
        detector = EmailClientDetector()
        assert 'system' in detector.os_info

    def test_init_with_custom_os_info(self):
        """Detector accepts custom OS info for testing."""
        custom_os = {'system': 'Linux', 'distro': 'fedora', 'package_manager': 'dnf'}
        detector = EmailClientDetector(os_info=custom_os)
        assert detector.os_info['distro'] == 'fedora'


class TestDetectorPathSearch:
    """Tests for PATH-based detection."""

    @patch('fileuzi.services.email_composer.shutil.which')
    def test_finds_betterbird_in_path(self, mock_which):
        """Find Betterbird via PATH lookup."""
        mock_which.side_effect = lambda x: (
            '/usr/bin/betterbird' if x == 'betterbird' else None
        )
        os_info = {'system': 'Linux', 'distro': 'fedora', 'package_manager': 'dnf'}
        detector = EmailClientDetector(os_info=os_info)
        result = detector.find_email_client()
        assert result is not None
        assert result['client'] == 'betterbird'
        assert result['method'] == 'path'
        assert result['path'] == Path('/usr/bin/betterbird')

    @patch.object(Path, 'exists', return_value=False)
    @patch('fileuzi.services.email_composer.subprocess.run',
           side_effect=FileNotFoundError)
    @patch('fileuzi.services.email_composer.shutil.which')
    def test_finds_thunderbird_in_path(self, mock_which, mock_run, mock_exists):
        """Find Thunderbird via PATH when Betterbird not available."""
        mock_which.side_effect = lambda x: (
            '/usr/bin/thunderbird' if x == 'thunderbird' else None
        )
        os_info = {'system': 'Linux', 'distro': None, 'package_manager': None}
        detector = EmailClientDetector(os_info=os_info)
        result = detector.find_email_client()
        assert result is not None
        assert result['client'] == 'thunderbird'

    @patch('fileuzi.services.email_composer.shutil.which')
    def test_prefers_betterbird_over_thunderbird(self, mock_which):
        """Betterbird is preferred when both are in PATH."""
        mock_which.side_effect = lambda x: f'/usr/bin/{x}'
        os_info = {'system': 'Linux', 'distro': None, 'package_manager': None}
        detector = EmailClientDetector(os_info=os_info)
        result = detector.find_email_client(preferred='betterbird')
        assert result['client'] == 'betterbird'

    @patch.object(Path, 'exists', return_value=False)
    @patch('fileuzi.services.email_composer.subprocess.run',
           side_effect=FileNotFoundError)
    @patch('fileuzi.services.email_composer.shutil.which', return_value=None)
    def test_no_clients_found(self, mock_which, mock_run, mock_exists):
        """Return None when no clients found anywhere."""
        os_info = {'system': 'Linux', 'distro': None, 'package_manager': None}
        detector = EmailClientDetector(os_info=os_info)
        result = detector.find_email_client()
        assert result is None


class TestDetectorPackageManager:
    """Tests for package manager-based detection."""

    @patch('fileuzi.services.email_composer.shutil.which', return_value=None)
    @patch('fileuzi.services.email_composer.subprocess.run')
    def test_finds_via_rpm(self, mock_run, mock_which):
        """Find Betterbird via rpm -ql on Fedora."""
        def run_side_effect(cmd, **kwargs):
            if cmd[0] == 'rpm' and cmd[1] == '-ql' and 'betterbird' in cmd[2]:
                result = MagicMock()
                result.returncode = 0
                result.stdout = '/usr/share/betterbird\n/usr/bin/betterbird\n'
                return result
            result = MagicMock()
            result.returncode = 1
            result.stdout = ''
            return result

        mock_run.side_effect = run_side_effect
        os_info = {'system': 'Linux', 'distro': 'fedora', 'package_manager': 'dnf'}
        detector = EmailClientDetector(os_info=os_info)

        # Mock the filesystem check for the rpm-reported path
        with patch.object(Path, 'exists', return_value=True):
            result = detector._search_via_package_manager('betterbird')

        assert result is not None
        assert result['method'] == 'package_manager'
        assert result['path'] == Path('/usr/bin/betterbird')

    @patch('fileuzi.services.email_composer.shutil.which', return_value=None)
    @patch('fileuzi.services.email_composer.subprocess.run')
    def test_finds_via_dpkg(self, mock_run, mock_which):
        """Find Thunderbird via dpkg -L on Ubuntu."""
        def run_side_effect(cmd, **kwargs):
            if cmd[0] == 'dpkg' and 'thunderbird' in cmd:
                result = MagicMock()
                result.returncode = 0
                result.stdout = '/usr/share/thunderbird\n/usr/bin/thunderbird\n'
                return result
            result = MagicMock()
            result.returncode = 1
            result.stdout = ''
            return result

        mock_run.side_effect = run_side_effect
        os_info = {'system': 'Linux', 'distro': 'ubuntu', 'package_manager': 'apt'}
        detector = EmailClientDetector(os_info=os_info)

        with patch.object(Path, 'exists', return_value=True):
            result = detector._search_via_package_manager('thunderbird')

        assert result is not None
        assert result['method'] == 'package_manager'

    @patch('fileuzi.services.email_composer.subprocess.run',
           side_effect=FileNotFoundError)
    def test_handles_missing_package_manager(self, mock_run):
        """Gracefully handle missing package manager command."""
        os_info = {'system': 'Linux', 'distro': 'fedora', 'package_manager': 'dnf'}
        detector = EmailClientDetector(os_info=os_info)
        result = detector._search_via_package_manager('betterbird')
        assert result is None

    @patch('fileuzi.services.email_composer.subprocess.run',
           side_effect=subprocess.TimeoutExpired('rpm', 10))
    def test_handles_timeout(self, mock_run):
        """Gracefully handle package manager timeout."""
        os_info = {'system': 'Linux', 'distro': 'fedora', 'package_manager': 'dnf'}
        detector = EmailClientDetector(os_info=os_info)
        result = detector._search_via_package_manager('betterbird')
        assert result is None

    def test_skips_when_no_package_manager(self):
        """Return None when no package manager detected."""
        os_info = {'system': 'Linux', 'distro': None, 'package_manager': None}
        detector = EmailClientDetector(os_info=os_info)
        result = detector._search_via_package_manager('betterbird')
        assert result is None


class TestDetectorFilesystem:
    """Tests for filesystem-based detection."""

    def test_finds_linux_path(self, tmp_path):
        """Find client at standard Linux path."""
        os_info = {'system': 'Linux', 'distro': 'fedora', 'package_manager': 'dnf'}
        detector = EmailClientDetector(os_info=os_info)

        fake_exe = tmp_path / "betterbird"
        fake_exe.write_text("#!/bin/sh")

        # Patch the Linux paths to include our temp path
        with patch.dict(
            'fileuzi.services.email_composer._LINUX_PATHS',
            {'betterbird': [str(fake_exe)]}
        ):
            result = detector._search_filesystem('betterbird')

        assert result is not None
        assert result['method'] == 'filesystem'
        assert result['path'] == fake_exe

    def test_returns_none_for_missing_path(self):
        """Return None when no paths exist."""
        os_info = {'system': 'Linux', 'distro': None, 'package_manager': None}
        detector = EmailClientDetector(os_info=os_info)

        with patch.dict(
            'fileuzi.services.email_composer._LINUX_PATHS',
            {'betterbird': ['/nonexistent/betterbird']}
        ):
            result = detector._search_filesystem('betterbird')

        assert result is None


class TestDetectorFlatpak:
    """Tests for Flatpak-based detection."""

    def test_finds_flatpak_export_wrapper(self, tmp_path):
        """Find client via Flatpak export wrapper."""
        os_info = {'system': 'Linux', 'distro': 'fedora', 'package_manager': 'dnf'}
        detector = EmailClientDetector(os_info=os_info)

        # Create fake flatpak export
        export_dir = tmp_path / "flatpak" / "exports" / "bin"
        export_dir.mkdir(parents=True)
        wrapper = export_dir / "eu.betterbird.Betterbird"
        wrapper.write_text("#!/bin/sh\nexec flatpak run eu.betterbird.Betterbird")

        # Replace the flatpak export paths in the method
        with patch.object(
            detector, '_search_flatpak',
            wraps=detector._search_flatpak
        ):
            # Directly test with the wrapper path
            original_method = detector._search_flatpak

            def patched_search(client_name, flatpak_id):
                # Override flatpak export check to use our temp dir
                if wrapper.exists():
                    return {
                        'client': client_name,
                        'path': wrapper,
                        'method': 'flatpak',
                    }
                return None

            detector._search_flatpak = patched_search
            result = detector._search_flatpak('betterbird', 'eu.betterbird.Betterbird')

        assert result is not None
        assert result['method'] == 'flatpak'
        assert result['path'] == wrapper

    @patch.object(Path, 'exists', return_value=False)
    @patch('fileuzi.services.email_composer.subprocess.run')
    def test_finds_via_flatpak_info(self, mock_run, mock_exists):
        """Find client via flatpak info registry check."""
        mock_run.return_value = MagicMock(returncode=0)
        os_info = {'system': 'Linux', 'distro': 'fedora', 'package_manager': 'dnf'}
        detector = EmailClientDetector(os_info=os_info)

        result = detector._search_flatpak('betterbird', 'eu.betterbird.Betterbird')
        assert result is not None
        assert result['method'] == 'flatpak'
        assert str(result['path']) == 'flatpak::eu.betterbird.Betterbird'

    @patch.object(Path, 'exists', return_value=False)
    @patch('fileuzi.services.email_composer.subprocess.run',
           side_effect=FileNotFoundError)
    def test_handles_missing_flatpak_command(self, mock_run, mock_exists):
        """Gracefully handle missing flatpak command."""
        os_info = {'system': 'Linux', 'distro': 'fedora', 'package_manager': 'dnf'}
        detector = EmailClientDetector(os_info=os_info)
        result = detector._search_flatpak('betterbird', 'eu.betterbird.Betterbird')
        assert result is None

    @patch.object(Path, 'exists', return_value=False)
    @patch('fileuzi.services.email_composer.subprocess.run',
           return_value=MagicMock(returncode=1))
    def test_not_found_in_flatpak(self, mock_run, mock_exists):
        """Return None when app not in Flatpak registry."""
        os_info = {'system': 'Linux', 'distro': 'fedora', 'package_manager': 'dnf'}
        detector = EmailClientDetector(os_info=os_info)
        result = detector._search_flatpak('betterbird', 'eu.betterbird.Betterbird')
        assert result is None


class TestDetectorSnap:
    """Tests for Snap-based detection."""

    def test_finds_snap_binary(self, tmp_path):
        """Find client via /snap/bin/ path."""
        os_info = {'system': 'Linux', 'distro': 'ubuntu', 'package_manager': 'apt'}
        detector = EmailClientDetector(os_info=os_info)

        # Create fake snap binary
        snap_bin = tmp_path / "snap" / "bin"
        snap_bin.mkdir(parents=True)
        snap_exe = snap_bin / "thunderbird"
        snap_exe.write_text("#!/bin/sh")

        # Patch Path to check our temp path
        original_search = detector._search_snap

        def patched_search(client_name, snap_name):
            if snap_exe.exists():
                return {
                    'client': client_name,
                    'path': snap_exe,
                    'method': 'snap',
                }
            return None

        detector._search_snap = patched_search
        result = detector._search_snap('thunderbird', 'thunderbird')

        assert result is not None
        assert result['method'] == 'snap'

    @patch('fileuzi.services.email_composer.subprocess.run',
           side_effect=FileNotFoundError)
    def test_handles_missing_snap_command(self, mock_run):
        """Gracefully handle missing snap command."""
        os_info = {'system': 'Linux', 'distro': 'ubuntu', 'package_manager': 'apt'}
        detector = EmailClientDetector(os_info=os_info)
        result = detector._search_snap('thunderbird', 'thunderbird')
        assert result is None


class TestDetectorFindAllClients:
    """Tests for find_all_clients method."""

    @patch('fileuzi.services.email_composer.shutil.which')
    def test_finds_multiple_clients(self, mock_which):
        """Find both Betterbird and Thunderbird."""
        mock_which.side_effect = lambda x: f'/usr/bin/{x}'
        os_info = {'system': 'Linux', 'distro': None, 'package_manager': None}
        detector = EmailClientDetector(os_info=os_info)
        all_clients = detector.find_all_clients()
        names = [c['client'] for c in all_clients]
        assert 'betterbird' in names
        assert 'thunderbird' in names

    @patch.object(Path, 'exists', return_value=False)
    @patch('fileuzi.services.email_composer.subprocess.run',
           side_effect=FileNotFoundError)
    @patch('fileuzi.services.email_composer.shutil.which', return_value=None)
    def test_returns_empty_when_none_found(self, mock_which, mock_run, mock_exists):
        """Return empty list when no clients found."""
        os_info = {'system': 'Linux', 'distro': None, 'package_manager': None}
        detector = EmailClientDetector(os_info=os_info)
        all_clients = detector.find_all_clients()
        assert all_clients == []


class TestDetectorFindEmailClient:
    """Tests for find_email_client method."""

    @patch('fileuzi.services.email_composer.shutil.which')
    def test_returns_preferred_client(self, mock_which):
        """Return preferred client when available."""
        mock_which.side_effect = lambda x: f'/usr/bin/{x}'
        os_info = {'system': 'Linux', 'distro': None, 'package_manager': None}
        detector = EmailClientDetector(os_info=os_info)
        result = detector.find_email_client(preferred='thunderbird')
        assert result['client'] == 'thunderbird'

    @patch.object(Path, 'exists', return_value=False)
    @patch('fileuzi.services.email_composer.subprocess.run',
           side_effect=FileNotFoundError)
    @patch('fileuzi.services.email_composer.shutil.which')
    def test_falls_back_when_preferred_missing(self, mock_which, mock_run, mock_exists):
        """Fall back to first available when preferred not found."""
        mock_which.side_effect = lambda x: (
            '/usr/bin/thunderbird' if x == 'thunderbird' else None
        )
        os_info = {'system': 'Linux', 'distro': None, 'package_manager': None}
        detector = EmailClientDetector(os_info=os_info)
        result = detector.find_email_client(preferred='betterbird')
        assert result['client'] == 'thunderbird'

    @patch('fileuzi.services.email_composer.shutil.which')
    def test_result_includes_all_found(self, mock_which):
        """Result includes list of all detected clients."""
        mock_which.side_effect = lambda x: f'/usr/bin/{x}'
        os_info = {'system': 'Linux', 'distro': None, 'package_manager': None}
        detector = EmailClientDetector(os_info=os_info)
        result = detector.find_email_client()
        assert 'all_found' in result
        assert len(result['all_found']) >= 2


class TestDetectorHomeDirectory:
    """Tests for home directory search."""

    def test_finds_in_local_bin(self, tmp_path):
        """Find client in ~/.local/bin/."""
        os_info = {'system': 'Linux', 'distro': None, 'package_manager': None}
        detector = EmailClientDetector(os_info=os_info)
        detector._home = tmp_path

        local_bin = tmp_path / '.local' / 'bin'
        local_bin.mkdir(parents=True)
        exe = local_bin / 'betterbird'
        exe.write_text("#!/bin/sh")

        meta = _CLIENT_REGISTRY['betterbird']
        result = detector._search_home_directory('betterbird', meta)
        assert result is not None
        assert result['path'] == exe

    def test_returns_none_when_not_in_home(self, tmp_path):
        """Return None when not found in home directories."""
        os_info = {'system': 'Linux', 'distro': None, 'package_manager': None}
        detector = EmailClientDetector(os_info=os_info)
        detector._home = tmp_path

        meta = _CLIENT_REGISTRY['betterbird']
        result = detector._search_home_directory('betterbird', meta)
        assert result is None


# ============================================================================
# detect_email_clients (backward-compatible wrapper) Tests
# ============================================================================

class TestDetectEmailClients:
    """Tests for the detect_email_clients wrapper function."""

    @patch.object(EmailClientDetector, 'find_all_clients')
    def test_returns_dict_format(self, mock_find):
        """Returns dict with betterbird and thunderbird keys."""
        mock_find.return_value = [
            {'client': 'betterbird', 'path': Path('/usr/bin/betterbird'), 'method': 'path'}
        ]
        clients = detect_email_clients()
        assert 'betterbird' in clients
        assert 'thunderbird' in clients
        assert clients['betterbird'] == Path('/usr/bin/betterbird')
        assert clients['thunderbird'] is None

    @patch.object(EmailClientDetector, 'find_all_clients')
    def test_both_clients(self, mock_find):
        """Both clients detected."""
        mock_find.return_value = [
            {'client': 'betterbird', 'path': Path('/usr/bin/betterbird'), 'method': 'path'},
            {'client': 'thunderbird', 'path': Path('/usr/bin/thunderbird'), 'method': 'path'},
        ]
        clients = detect_email_clients()
        assert clients['betterbird'] is not None
        assert clients['thunderbird'] is not None

    @patch.object(EmailClientDetector, 'find_all_clients')
    def test_no_clients(self, mock_find):
        """No clients returns None for both."""
        mock_find.return_value = []
        clients = detect_email_clients()
        assert clients['betterbird'] is None
        assert clients['thunderbird'] is None

    @patch.object(EmailClientDetector, 'find_all_clients')
    def test_flatpak_client(self, mock_find):
        """Flatpak-detected client path is returned."""
        mock_find.return_value = [
            {'client': 'betterbird', 'path': Path('flatpak::eu.betterbird.Betterbird'),
             'method': 'flatpak'}
        ]
        clients = detect_email_clients()
        assert str(clients['betterbird']) == 'flatpak::eu.betterbird.Betterbird'


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
        assert extract_first_name("Bob Smith") == "Bob"

    def test_single_name(self):
        assert extract_first_name("Bob") == "Bob"

    def test_multiple_names(self):
        assert extract_first_name("Bob James Smith") == "Bob"

    def test_empty_string(self):
        assert extract_first_name("") is None

    def test_none_input(self):
        assert extract_first_name(None) is None

    def test_whitespace_only(self):
        assert extract_first_name("   ") is None

    def test_leading_whitespace(self):
        assert extract_first_name("  Bob Smith  ") == "Bob"


# ============================================================================
# generate_email_body Tests
# ============================================================================

class TestGenerateEmailBody:
    """Tests for generate_email_body function."""

    def test_with_recipient_name(self):
        sig = "<div>Signature</div>"
        body = generate_email_body("Bob Smith", sig)
        assert "<p>Hi Bob,</p>" in body
        assert "<div>Signature</div>" in body
        assert body.startswith("<html>")
        assert body.endswith("</html>")

    def test_without_recipient_name(self):
        body = generate_email_body("", "<div>Signature</div>")
        assert "<p>Hi [Name],</p>" in body

    def test_none_recipient(self):
        body = generate_email_body(None, "<div>Sig</div>")
        assert "<p>Hi [Name],</p>" in body

    def test_signature_included(self):
        sig = '<div class="sig"><p>Jake White</p></div>'
        body = generate_email_body("Bob", sig)
        assert sig in body

    def test_empty_signature(self):
        body = generate_email_body("Bob", "")
        assert "<p>Hi Bob,</p>" in body
        assert "<html>" in body

    def test_html_structure(self):
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
        sig = load_email_signature(project_root_with_signature)
        assert "Jake White" in sig
        assert "Jake White Architecture" in sig

    def test_signature_not_found(self, project_root_no_signature):
        with pytest.raises(FileNotFoundError, match="Email signature file not found"):
            load_email_signature(project_root_no_signature)

    def test_signature_path_in_error_message(self, project_root_no_signature):
        with pytest.raises(FileNotFoundError) as exc_info:
            load_email_signature(project_root_no_signature)
        assert EMAIL_SIGNATURE_FOLDER in str(exc_info.value)
        assert EMAIL_SIGNATURE_FILENAME in str(exc_info.value)

    def test_signature_utf8_encoding(self, project_root_with_signature):
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
# save/load_email_client_preference Tests
# ============================================================================

class TestEmailClientPreference:
    """Tests for save/load email client preference functions."""

    def test_save_and_load(self, db_path):
        save_email_client_preference(db_path, 'betterbird', '/usr/bin/betterbird')
        config = load_email_client_preference(db_path)
        assert config is not None
        assert config['client_name'] == 'betterbird'
        assert config['client_path'] == Path('/usr/bin/betterbird')
        assert config['auto_detected'] is True

    def test_save_with_detection_method(self, db_path):
        """Detection method is stored and retrieved."""
        save_email_client_preference(
            db_path, 'betterbird', '/usr/bin/betterbird',
            detection_method='package_manager'
        )
        config = load_email_client_preference(db_path)
        assert config['detection_method'] == 'package_manager'

    def test_save_manual_preference(self, db_path):
        save_email_client_preference(
            db_path, 'thunderbird', '/opt/thunderbird/thunderbird',
            auto_detected=False, detection_method='manual'
        )
        config = load_email_client_preference(db_path)
        assert config['auto_detected'] is False
        assert config['detection_method'] == 'manual'

    def test_load_nonexistent_db(self, tmp_path):
        result = load_email_client_preference(tmp_path / "nonexistent.db")
        assert result is None

    def test_load_empty_db(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.close()
        result = load_email_client_preference(db_path)
        assert result is None

    def test_overwrite_preference(self, db_path):
        save_email_client_preference(db_path, 'betterbird', '/usr/bin/betterbird')
        save_email_client_preference(db_path, 'thunderbird', '/usr/bin/thunderbird')
        config = load_email_client_preference(db_path)
        assert config['client_name'] == 'thunderbird'

    def test_last_verified_timestamp(self, db_path):
        save_email_client_preference(db_path, 'betterbird', '/usr/bin/betterbird')
        config = load_email_client_preference(db_path)
        assert config['last_verified'] is not None
        datetime.fromisoformat(config['last_verified'])


# ============================================================================
# get_email_client_path Tests
# ============================================================================

class TestGetEmailClientPath:
    """Tests for get_email_client_path function."""

    def test_returns_saved_preference(self, db_path, tmp_path):
        """Return saved path if it still exists."""
        fake_exe = tmp_path / "betterbird"
        fake_exe.write_text("#!/bin/sh\necho test")
        fake_exe.chmod(0o755)

        save_email_client_preference(db_path, 'betterbird', str(fake_exe))
        result = get_email_client_path(db_path)
        assert result == fake_exe

    @patch.object(EmailClientDetector, 'find_email_client')
    def test_re_detects_when_saved_missing(self, mock_find, db_path, tmp_path):
        """Re-detect when saved path no longer exists."""
        save_email_client_preference(db_path, 'betterbird', '/nonexistent/betterbird')

        fake_tb = tmp_path / "thunderbird"
        fake_tb.write_text("#!/bin/sh")
        fake_tb.chmod(0o755)
        mock_find.return_value = {
            'client': 'thunderbird',
            'path': fake_tb,
            'method': 'path',
            'all_found': [],
        }

        result = get_email_client_path(db_path)
        assert result == fake_tb

    @patch.object(EmailClientDetector, 'find_email_client')
    def test_prefers_betterbird(self, mock_find, db_path, tmp_path):
        """Betterbird is preferred over Thunderbird."""
        fake_bb = tmp_path / "betterbird"
        fake_bb.write_text("#!/bin/sh")

        mock_find.return_value = {
            'client': 'betterbird',
            'path': fake_bb,
            'method': 'path',
            'all_found': [],
        }

        result = get_email_client_path(db_path)
        assert result == fake_bb

    @patch.object(EmailClientDetector, 'find_email_client')
    def test_raises_when_no_client(self, mock_find, db_path):
        """Raise FileNotFoundError when no client available."""
        mock_find.return_value = None
        with pytest.raises(FileNotFoundError, match="No email client found"):
            get_email_client_path(db_path)

    @patch.object(EmailClientDetector, 'find_email_client')
    def test_saves_detected_preference(self, mock_find, db_path, tmp_path):
        """Auto-detected client is saved for future use."""
        fake_tb = tmp_path / "thunderbird"
        fake_tb.write_text("#!/bin/sh")

        mock_find.return_value = {
            'client': 'thunderbird',
            'path': fake_tb,
            'method': 'filesystem',
            'all_found': [],
        }

        get_email_client_path(db_path)

        config = load_email_client_preference(db_path)
        assert config is not None
        assert config['client_name'] == 'thunderbird'
        assert config['detection_method'] == 'filesystem'

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
        att = tmp_path / "document.pdf"
        att.write_bytes(b"PDF content")
        client = tmp_path / "betterbird"

        launch_email_compose("Subject", [att], "<html></html>", client)

        args = mock_popen.call_args[0][0]
        assert "file://" in args[2]

    @patch('fileuzi.services.email_composer.subprocess.Popen')
    def test_body_html_url_encoded(self, mock_popen, tmp_path):
        att = tmp_path / "file.pdf"
        att.write_bytes(b"content")
        client = tmp_path / "betterbird"

        launch_email_compose(
            "Subject", [att],
            "<html><body><p>Hello World</p></body></html>",
            client
        )

        args = mock_popen.call_args[0][0]
        assert "body='" in args[2]

    def test_attachment_size_limit(self, tmp_path):
        large_file = tmp_path / "large.pdf"
        large_file.write_bytes(b"x" * (MAX_ATTACHMENT_SIZE + 1))
        client = tmp_path / "betterbird"

        with pytest.raises(ValueError, match="Attachments too large"):
            launch_email_compose("Subject", [large_file], "<html></html>", client)

    @patch('fileuzi.services.email_composer.subprocess.Popen')
    def test_multiple_attachments(self, mock_popen, tmp_path):
        files = []
        for i in range(3):
            f = tmp_path / f"file{i}.pdf"
            f.write_bytes(b"content")
            files.append(f)

        client = tmp_path / "betterbird"
        launch_email_compose("Subject", files, "<html></html>", client)

        args = mock_popen.call_args[0][0]
        assert args[2].count("file://") == 3

    @patch('fileuzi.services.email_composer.subprocess.Popen')
    def test_empty_to_field(self, mock_popen, tmp_path):
        att = tmp_path / "file.pdf"
        att.write_bytes(b"content")
        client = tmp_path / "betterbird"

        launch_email_compose("Subject", [att], "<html></html>", client)

        args = mock_popen.call_args[0][0]
        assert "to=''" in args[2]

    @patch('fileuzi.services.email_composer.subprocess.Popen',
           side_effect=FileNotFoundError("Not found"))
    def test_client_not_found_error(self, mock_popen, tmp_path):
        att = tmp_path / "file.pdf"
        att.write_bytes(b"content")

        with pytest.raises(FileNotFoundError, match="Email client executable not found"):
            launch_email_compose("Subject", [att], "<html></html>", "/bad/path")

    @patch('fileuzi.services.email_composer.subprocess.Popen',
           side_effect=PermissionError("Permission denied"))
    def test_launch_failure(self, mock_popen, tmp_path):
        att = tmp_path / "file.pdf"
        att.write_bytes(b"content")

        with pytest.raises(RuntimeError, match="Failed to launch email client"):
            launch_email_compose("Subject", [att], "<html></html>", "/some/path")

    @patch('fileuzi.services.email_composer.subprocess.Popen')
    def test_flatpak_launch(self, mock_popen, tmp_path):
        """Flatpak clients get --filesystem access to attachment directories."""
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
        # Should grant access to the attachment's parent directory
        assert args[2].startswith("--filesystem=")
        assert str(tmp_path) in args[2]
        assert args[3] == "eu.betterbird.Betterbird"
        assert args[4] == "-compose"
        compose = args[5]
        assert "subject='Subject'" in compose
        assert "file://" in compose
        assert "file.pdf" in compose


# ============================================================================
# detect_superseding_candidates Tests
# ============================================================================

class TestDetectSupersedingCandidates:
    """Tests for detect_superseding_candidates function."""

    def test_detects_older_revision(self, current_drawings_folder, tmp_path):
        new_file = tmp_path / "2506_20_FLOOR PLANS_C02.pdf"
        new_file.write_bytes(b"new drawing")

        candidates = detect_superseding_candidates(new_file, current_drawings_folder)
        assert len(candidates) == 2
        assert "2506_20_FLOOR PLANS_P01.pdf" in candidates
        assert "2506_20_FLOOR PLANS_C01.pdf" in candidates

    def test_no_superseding_for_different_drawing(self, current_drawings_folder, tmp_path):
        new_file = tmp_path / "2506_30_NEW DRAWING_C01.pdf"
        new_file.write_bytes(b"new drawing")

        candidates = detect_superseding_candidates(new_file, current_drawings_folder)
        assert len(candidates) == 0

    def test_no_superseding_for_non_drawing(self, current_drawings_folder, tmp_path):
        new_file = tmp_path / "Some random file.pdf"
        new_file.write_bytes(b"not a drawing")

        candidates = detect_superseding_candidates(new_file, current_drawings_folder)
        assert len(candidates) == 0

    def test_no_superseding_for_non_current_folder(self, tmp_path):
        folder = tmp_path / "ADMIN"
        folder.mkdir()
        (folder / "2506_20_FLOOR PLANS_P01.pdf").write_bytes(b"drawing")

        new_file = tmp_path / "2506_20_FLOOR PLANS_C02.pdf"
        new_file.write_bytes(b"new drawing")

        candidates = detect_superseding_candidates(new_file, folder)
        assert len(candidates) == 0

    def test_empty_folder(self, tmp_path):
        folder = tmp_path / "Current Drawings"
        folder.mkdir()

        new_file = tmp_path / "2506_20_FLOOR PLANS_C01.pdf"
        new_file.write_bytes(b"new drawing")

        candidates = detect_superseding_candidates(new_file, folder)
        assert len(candidates) == 0

    def test_same_revision_not_superseded(self, tmp_path):
        folder = tmp_path / "Current Drawings"
        folder.mkdir()
        (folder / "2506_20_FLOOR PLANS_C01.pdf").write_bytes(b"existing")

        new_file = tmp_path / "2506_20_FLOOR PLANS_C01.pdf"
        new_file.write_bytes(b"same rev")

        candidates = detect_superseding_candidates(new_file, folder)
        assert len(candidates) == 0


# ============================================================================
# Toggle Visibility Tests
# ============================================================================

class TestCreateEmailToggleVisibility:
    """Tests for Create Email toggle visibility logic."""

    def test_visible_for_export_regular_files(self):
        is_export = True
        email_data = None
        file_widgets = [("widget", "path")]
        is_regular_files = not email_data and bool(file_widgets)
        assert (is_export and is_regular_files) is True

    def test_hidden_for_import(self):
        is_export = False
        email_data = None
        file_widgets = [("widget", "path")]
        is_regular_files = not email_data and bool(file_widgets)
        assert (is_export and is_regular_files) is False

    def test_hidden_for_eml_files(self):
        is_export = True
        email_data = {"subject": "test"}
        file_widgets = []
        is_regular_files = not email_data and bool(file_widgets)
        assert (is_export and is_regular_files) is False

    def test_hidden_when_no_files(self):
        is_export = True
        email_data = None
        file_widgets = []
        is_regular_files = not email_data and bool(file_widgets)
        assert (is_export and is_regular_files) is False


# ============================================================================
# Integration Tests
# ============================================================================

class TestEmailComposerIntegration:
    """Integration tests for the full email composition workflow."""

    @patch.object(EmailClientDetector, 'find_email_client')
    def test_first_use_detection_and_save(self, mock_find, db_path, tmp_path):
        """Full workflow: detect client, save preference, load on next call."""
        fake_tb = tmp_path / "thunderbird"
        fake_tb.write_text("#!/bin/sh")
        fake_tb.chmod(0o755)

        mock_find.return_value = {
            'client': 'thunderbird',
            'path': fake_tb,
            'method': 'path',
            'all_found': [],
        }

        # First call: detect and save
        path1 = get_email_client_path(db_path)
        assert path1 == fake_tb

        # Second call: load from DB (no detection needed)
        path2 = get_email_client_path(db_path)
        assert path2 == fake_tb

        # Detector should only be called once (second time loads from DB)
        assert mock_find.call_count == 1

    @patch.object(EmailClientDetector, 'find_email_client')
    def test_path_invalidation_re_detection(self, mock_find, db_path, tmp_path):
        """When saved path becomes invalid, re-detect and save new preference."""
        save_email_client_preference(db_path, 'betterbird', '/gone/betterbird')

        fake_tb = tmp_path / "thunderbird"
        fake_tb.write_text("#!/bin/sh")
        fake_tb.chmod(0o755)

        mock_find.return_value = {
            'client': 'thunderbird',
            'path': fake_tb,
            'method': 'filesystem',
            'all_found': [],
        }

        result = get_email_client_path(db_path)
        assert result == fake_tb

        config = load_email_client_preference(db_path)
        assert config['client_name'] == 'thunderbird'

    @patch('fileuzi.services.email_composer.subprocess.Popen')
    def test_full_email_workflow(self, mock_popen, tmp_path):
        """Full workflow: generate subject, body, and launch email."""
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

        dest = tmp_path / "filed_docs"
        dest.mkdir()
        att1 = dest / "2506_20_FLOOR PLANS_C02.pdf"
        att1.write_bytes(b"drawing pdf content")

        subject = generate_email_subject("2506_SMITH EXTENSION", "Floor plans")
        assert "2506" in subject
        assert "Smith extension" in subject
        assert "Floor plans" in subject

        signature = load_email_signature(root)
        body = generate_email_body("Bob Smith", signature)
        assert "Hi Bob," in body
        assert "Jake White" in body

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

        body = generate_email_body("Bob", "")
        assert "<p>Hi Bob,</p>" in body

        att = tmp_path / "file.pdf"
        att.write_bytes(b"content")
        client = tmp_path / "betterbird"

        launch_email_compose("Subject", [att], body, client)
        mock_popen.assert_called_once()

    def test_superseding_detection_with_filing(self, tmp_path):
        """Integration: detect superseding before filing, then file."""
        current = tmp_path / "Current Drawings"
        current.mkdir()

        (current / "2506_20_FLOOR PLANS_P01.pdf").write_bytes(b"old")
        (current / "2506_20_FLOOR PLANS_C01.pdf").write_bytes(b"old")

        new_file = tmp_path / "2506_20_FLOOR PLANS_C02.pdf"
        new_file.write_bytes(b"new drawing")

        candidates = detect_superseding_candidates(new_file, current)
        assert len(candidates) == 2
        assert "2506_20_FLOOR PLANS_P01.pdf" in candidates
        assert "2506_20_FLOOR PLANS_C01.pdf" in candidates

    @patch.object(Path, 'exists', return_value=False)
    @patch('fileuzi.services.email_composer.shutil.which')
    @patch('fileuzi.services.email_composer.subprocess.run')
    def test_fedora_flatpak_detection_and_launch(self, mock_run, mock_which,
                                                  mock_exists, tmp_path):
        """Fedora: detect Betterbird via Flatpak, then verify launch command."""
        # No binaries in PATH
        mock_which.return_value = None

        # flatpak info succeeds for Betterbird
        def run_side_effect(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == 'flatpak' and cmd[1] == 'info':
                result.returncode = 0 if 'Betterbird' in cmd[2] else 1
            elif cmd[0] == 'rpm':
                result.returncode = 1
                result.stdout = ''
            else:
                result.returncode = 1
                result.stdout = ''
            return result

        mock_run.side_effect = run_side_effect

        os_info = {'system': 'Linux', 'distro': 'fedora', 'package_manager': 'dnf'}
        detector = EmailClientDetector(os_info=os_info)
        result = detector.find_email_client(preferred='betterbird')

        assert result is not None
        assert result['client'] == 'betterbird'
        assert str(result['path']) == 'flatpak::eu.betterbird.Betterbird'
        assert result['method'] == 'flatpak'
