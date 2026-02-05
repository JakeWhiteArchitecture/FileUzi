"""
Email composition service for FileUzi.

Generates email subjects, bodies, signatures and launches email clients
(Betterbird/Thunderbird) with pre-populated composition windows.
"""

import logging
import os
import platform
import shutil
import sqlite3
import subprocess
import urllib.parse
from datetime import datetime
from pathlib import Path

from fileuzi.config import FILING_WIDGET_TOOLS_FOLDER

logger = logging.getLogger(__name__)

# Maximum attachment size for email (25MB)
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024

# Maximum command line length (safe limit below 32KB kernel limit)
MAX_COMMAND_LENGTH = 30000

# Email signature folder and filename
EMAIL_SIGNATURE_FOLDER = '*EMAIL_SIGNATURE*'
EMAIL_SIGNATURE_FILENAME = 'email_signature.html'


# ============================================================================
# Email Subject Generation
# ============================================================================

def generate_email_subject(project_folder_name, description):
    """
    Generate email subject line from project folder name and description.

    Args:
        project_folder_name: e.g., "2506_SMITH EXTENSION"
        description: User-entered description from UI field

    Returns:
        Formatted subject: "2506 - Smith extension - Structural calculations"
    """
    if not project_folder_name:
        return ""

    # Split folder name by first underscore
    parts = project_folder_name.split('_', 1)

    job_number = parts[0]

    if len(parts) == 2 and parts[1]:
        project_name = parts[1]
        # Format: lowercase with first letter capitalized
        project_name_formatted = project_name[0].upper() + project_name[1:].lower()
    else:
        project_name_formatted = ""

    # Format description: lowercase with first letter capitalized
    if description and description.strip():
        desc = description.strip()
        desc_formatted = desc[0].upper() + desc[1:].lower()
    else:
        desc_formatted = ""

    # Build subject line
    if project_name_formatted and desc_formatted:
        return f"{job_number} - {project_name_formatted} - {desc_formatted}"
    elif project_name_formatted:
        return f"{job_number} - {project_name_formatted}"
    elif desc_formatted:
        return f"{job_number} - {desc_formatted}"
    else:
        return job_number


# ============================================================================
# Recipient Name Extraction
# ============================================================================

def extract_first_name(recipient_name):
    """
    Extract first name from recipient name field.

    Args:
        recipient_name: Full name entered by user (e.g., "Bob Smith")

    Returns:
        First name only (e.g., "Bob"), or None if field empty
    """
    if not recipient_name or not recipient_name.strip():
        return None

    parts = recipient_name.strip().split()
    return parts[0] if parts else None


# ============================================================================
# Email Body Generation
# ============================================================================

def generate_email_body(recipient_name, signature_html):
    """
    Generate email body with greeting and signature.

    Args:
        recipient_name: Full recipient name from UI field
        signature_html: HTML signature loaded from file

    Returns:
        Complete HTML email body
    """
    first_name = extract_first_name(recipient_name)

    if first_name:
        greeting = f"<p>Hi {first_name},</p>"
    else:
        greeting = "<p>Hi [Name],</p>"

    return (
        f"<html>\n<body>\n{greeting}\n<p><br></p>\n"
        f"{signature_html}\n</body>\n</html>"
    )


# ============================================================================
# Email Signature Loading
# ============================================================================

def load_email_signature(project_root):
    """
    Load email signature HTML from *EMAIL_SIGNATURE* folder.

    Args:
        project_root: Root of the projects folder (e.g., /JWA_PROJECTS)

    Returns:
        HTML signature content with relative image paths intact

    Raises:
        FileNotFoundError: If signature file doesn't exist
    """
    project_root = Path(project_root)
    signature_path = (
        project_root /
        FILING_WIDGET_TOOLS_FOLDER /
        EMAIL_SIGNATURE_FOLDER /
        EMAIL_SIGNATURE_FILENAME
    )

    if not signature_path.exists():
        raise FileNotFoundError(
            f"Email signature file not found.\n"
            f"Expected location: {signature_path}\n\n"
            f"Please create email_signature.html in the "
            f"{EMAIL_SIGNATURE_FOLDER} folder."
        )

    return signature_path.read_text(encoding='utf-8')


# ============================================================================
# OS & Distribution Detection
# ============================================================================

def detect_os_info():
    """
    Detect operating system, Linux distribution, and package manager.

    Returns:
        {
            'system': 'Linux' | 'Windows' | 'Darwin',
            'distro': 'fedora' | 'ubuntu' | 'debian' | 'arch' | None,
            'package_manager': 'dnf' | 'apt' | 'pacman' | 'brew' | None
        }
    """
    system = platform.system()
    distro = None
    package_manager = None

    if system == 'Linux':
        # Read /etc/os-release for distro info
        try:
            os_release = Path('/etc/os-release').read_text()
            os_release_lower = os_release.lower()
            if 'fedora' in os_release_lower:
                distro = 'fedora'
            elif 'ubuntu' in os_release_lower:
                distro = 'ubuntu'
            elif 'debian' in os_release_lower:
                distro = 'debian'
            elif 'arch' in os_release_lower:
                distro = 'arch'
            elif 'opensuse' in os_release_lower or 'suse' in os_release_lower:
                distro = 'suse'
            elif 'manjaro' in os_release_lower:
                distro = 'manjaro'
            elif 'mint' in os_release_lower:
                distro = 'mint'
        except (FileNotFoundError, PermissionError):
            pass

        # Detect package manager by checking which are available
        if shutil.which('dnf'):
            package_manager = 'dnf'
        elif shutil.which('apt'):
            package_manager = 'apt'
        elif shutil.which('pacman'):
            package_manager = 'pacman'
        elif shutil.which('zypper'):
            package_manager = 'zypper'

    elif system == 'Darwin':
        if shutil.which('brew'):
            package_manager = 'brew'

    return {
        'system': system,
        'distro': distro,
        'package_manager': package_manager,
    }


# ============================================================================
# Email Client Detection
# ============================================================================

# Client metadata: names, executable names, Flatpak IDs, Snap names
_CLIENT_REGISTRY = {
    'betterbird': {
        'exe_names': ['betterbird'],
        'flatpak_id': 'eu.betterbird.Betterbird',
        'snap_name': None,
        'supports_compose': True,
    },
    'thunderbird': {
        'exe_names': ['thunderbird'],
        'flatpak_id': 'org.mozilla.Thunderbird',
        'snap_name': 'thunderbird',
        'supports_compose': True,
    },
}

# Platform-specific search paths
_LINUX_PATHS = {
    'betterbird': [
        '/usr/bin/betterbird',
        '/usr/local/bin/betterbird',
        '/opt/betterbird/betterbird',
    ],
    'thunderbird': [
        '/usr/bin/thunderbird',
        '/usr/local/bin/thunderbird',
        '/opt/thunderbird/thunderbird',
    ],
}

_WINDOWS_PATHS = {
    'betterbird': [
        r'C:\Program Files\Betterbird\betterbird.exe',
        r'C:\Program Files (x86)\Betterbird\betterbird.exe',
    ],
    'thunderbird': [
        r'C:\Program Files\Mozilla Thunderbird\thunderbird.exe',
        r'C:\Program Files (x86)\Mozilla Thunderbird\thunderbird.exe',
    ],
}

_MACOS_PATHS = {
    'betterbird': [
        '/Applications/Betterbird.app/Contents/MacOS/betterbird',
    ],
    'thunderbird': [
        '/Applications/Thunderbird.app/Contents/MacOS/thunderbird',
    ],
}


class EmailClientDetector:
    """
    Intelligent OS-aware email client detector.

    Searches for email clients using a prioritised strategy:
    1. PATH lookup (shutil.which)
    2. Package manager verification (dnf, apt, pacman, brew)
    3. Standard OS-specific install locations
    4. Flatpak installations (Linux)
    5. Snap installations (Linux)
    6. User home directory locations
    """

    def __init__(self, os_info=None):
        self.os_info = os_info or detect_os_info()
        self._home = Path.home()

    def find_all_clients(self):
        """
        Find all installed email clients that support -compose.

        Returns:
            List of dicts, each with:
            {
                'client': 'betterbird',
                'path': Path or str,
                'method': 'path' | 'package_manager' | 'filesystem' | 'flatpak' | 'snap',
            }
        """
        found = []
        for client_name, meta in _CLIENT_REGISTRY.items():
            if not meta['supports_compose']:
                continue
            result = self._search_client(client_name, meta)
            if result:
                found.append(result)
        return found

    def find_email_client(self, preferred=None):
        """
        Find the best available email client.

        Args:
            preferred: Optional client name to search first ('betterbird')

        Returns:
            {
                'client': 'betterbird',
                'path': Path('/usr/bin/betterbird'),
                'method': 'path',
                'all_found': [list of all detected clients]
            }
            or None if nothing found
        """
        all_found = self.find_all_clients()
        if not all_found:
            return None

        # Pick primary: preferred first, then by registry order
        primary = None
        if preferred:
            for item in all_found:
                if item['client'] == preferred:
                    primary = item
                    break

        if not primary:
            primary = all_found[0]

        return {
            'client': primary['client'],
            'path': primary['path'],
            'method': primary['method'],
            'all_found': all_found,
        }

    def _search_client(self, client_name, meta):
        """Run the full search strategy for a single client."""
        logger.debug("Searching for %s (OS: %s, distro: %s, pm: %s)",
                      client_name, self.os_info['system'],
                      self.os_info.get('distro'), self.os_info.get('package_manager'))

        # 1. PATH lookup
        for exe_name in meta['exe_names']:
            found = shutil.which(exe_name)
            logger.debug("  PATH lookup '%s': %s", exe_name, found or "not found")
            if found:
                return {
                    'client': client_name,
                    'path': Path(found),
                    'method': 'path',
                }

        # 2. Package manager verification
        result = self._search_via_package_manager(client_name)
        if result:
            return result

        # 3. OS-specific filesystem paths
        result = self._search_filesystem(client_name)
        if result:
            return result

        # 4. Flatpak (Linux only)
        if self.os_info['system'] == 'Linux' and meta.get('flatpak_id'):
            result = self._search_flatpak(
                client_name, meta['flatpak_id']
            )
            if result:
                return result

        # 5. Snap (Linux only)
        if self.os_info['system'] == 'Linux' and meta.get('snap_name'):
            result = self._search_snap(
                client_name, meta['snap_name']
            )
            if result:
                return result

        # 6. User home directory
        result = self._search_home_directory(client_name, meta)
        if result:
            return result

        return None

    def _search_via_package_manager(self, client_name):
        """Query package manager for installed client."""
        pm = self.os_info.get('package_manager')
        if not pm:
            return None

        try:
            if pm == 'dnf':
                result = subprocess.run(
                    ['rpm', '-ql', client_name],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        if '/bin/' in line and line.strip().endswith(client_name):
                            path = Path(line.strip())
                            if path.exists():
                                return {
                                    'client': client_name,
                                    'path': path,
                                    'method': 'package_manager',
                                }

            elif pm == 'apt':
                result = subprocess.run(
                    ['dpkg', '-L', client_name],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        if '/bin/' in line and line.strip().endswith(client_name):
                            path = Path(line.strip())
                            if path.exists():
                                return {
                                    'client': client_name,
                                    'path': path,
                                    'method': 'package_manager',
                                }

            elif pm == 'pacman':
                result = subprocess.run(
                    ['pacman', '-Ql', client_name],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        parts = line.strip().split(None, 1)
                        if len(parts) == 2 and '/bin/' in parts[1]:
                            if parts[1].endswith(client_name):
                                path = Path(parts[1])
                                if path.exists():
                                    return {
                                        'client': client_name,
                                        'path': path,
                                        'method': 'package_manager',
                                    }

            elif pm == 'brew':
                result = subprocess.run(
                    ['brew', '--prefix', client_name],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    prefix = Path(result.stdout.strip())
                    bin_path = prefix / 'bin' / client_name
                    if bin_path.exists():
                        return {
                            'client': client_name,
                            'path': bin_path,
                            'method': 'package_manager',
                        }

        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

        return None

    def _search_filesystem(self, client_name):
        """Search OS-specific standard install locations."""
        system = self.os_info['system']

        if system == 'Linux':
            paths = _LINUX_PATHS.get(client_name, [])
        elif system == 'Windows':
            paths = _WINDOWS_PATHS.get(client_name, [])
            # Also check %LOCALAPPDATA%
            local_app = os.environ.get('LOCALAPPDATA', '')
            if local_app:
                paths.append(
                    str(Path(local_app) / 'Programs' / client_name.title()
                        / f'{client_name}.exe')
                )
        elif system == 'Darwin':
            paths = _MACOS_PATHS.get(client_name, [])
        else:
            paths = []

        for path_str in paths:
            path = Path(path_str)
            if path.exists():
                return {
                    'client': client_name,
                    'path': path,
                    'method': 'filesystem',
                }

        return None

    def _search_flatpak(self, client_name, flatpak_id):
        """Check Flatpak installations."""
        # Check export wrappers first (these launch like normal executables)
        flatpak_export_paths = [
            Path(f"/var/lib/flatpak/exports/bin/{flatpak_id}"),
            self._home / f".local/share/flatpak/exports/bin/{flatpak_id}",
        ]
        for fp in flatpak_export_paths:
            exists = fp.exists()
            logger.debug("  Flatpak wrapper %s: %s", fp, "FOUND" if exists else "not found")
            if exists:
                return {
                    'client': client_name,
                    'path': f"flatpak::{flatpak_id}",
                    'method': 'flatpak',
                }

        # Query flatpak registry
        try:
            result = subprocess.run(
                ['flatpak', 'info', flatpak_id],
                capture_output=True, timeout=5
            )
            logger.debug("  flatpak info %s: returncode=%d", flatpak_id, result.returncode)
            if result.returncode == 0:
                return {
                    'client': client_name,
                    'path': f"flatpak::{flatpak_id}",
                    'method': 'flatpak',
                }
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.debug("  flatpak info failed: %s", e)

        return None

    def _search_snap(self, client_name, snap_name):
        """Check Snap installations."""
        # Check snap binary path
        snap_bin = Path(f"/snap/bin/{snap_name}")
        if snap_bin.exists():
            return {
                'client': client_name,
                'path': snap_bin,
                'method': 'snap',
            }

        # Query snap list
        try:
            result = subprocess.run(
                ['snap', 'list', snap_name],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return {
                    'client': client_name,
                    'path': snap_bin,
                    'method': 'snap',
                }
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return None

    def _search_home_directory(self, client_name, meta):
        """Search user home directory for portable/local installs."""
        exe_name = meta['exe_names'][0]
        home_paths = [
            self._home / '.local' / 'bin' / exe_name,
            self._home / 'Applications' / exe_name,
            self._home / '.local' / 'share' / 'applications' / exe_name,
        ]

        if self.os_info['system'] == 'Darwin':
            home_paths.append(
                self._home / 'Applications'
                / f'{client_name.title()}.app' / 'Contents' / 'MacOS'
                / exe_name
            )

        for path in home_paths:
            if path.exists():
                return {
                    'client': client_name,
                    'path': path,
                    'method': 'filesystem',
                }

        return None


def detect_email_clients():
    """
    Detect installed email clients (Betterbird and Thunderbird).

    Uses OS-aware detection: PATH, package manager, filesystem,
    Flatpak, and Snap.

    Returns:
        Dictionary with client names and paths:
        {
            'betterbird': Path('/usr/bin/betterbird') or None,
            'thunderbird': Path('/usr/bin/thunderbird') or None
        }
    """
    detector = EmailClientDetector()
    all_found = detector.find_all_clients()

    clients = {'betterbird': None, 'thunderbird': None}
    for item in all_found:
        name = item['client']
        if name in clients and clients[name] is None:
            clients[name] = item['path']

    return clients


# ============================================================================
# Email Client Preference Storage
# ============================================================================

_EMAIL_CLIENT_CONFIG_SCHEMA = """
    CREATE TABLE IF NOT EXISTS email_client_config (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        client_name TEXT NOT NULL,
        client_path TEXT NOT NULL,
        detection_method TEXT DEFAULT 'auto',
        auto_detected BOOLEAN DEFAULT TRUE,
        last_verified TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""


def save_email_client_preference(db_path, client_name, client_path,
                                  auto_detected=True, detection_method='auto'):
    """
    Save email client preference to database.

    Args:
        db_path: Path to filing_widget.db
        client_name: 'betterbird' or 'thunderbird'
        client_path: Full path to executable
        auto_detected: Whether path was auto-detected or user-configured
        detection_method: How client was found ('path', 'package_manager',
                          'filesystem', 'flatpak', 'snap', 'manual')
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(_EMAIL_CLIENT_CONFIG_SCHEMA)
    cursor.execute(
        "INSERT OR REPLACE INTO email_client_config "
        "(id, client_name, client_path, detection_method, auto_detected, last_verified) "
        "VALUES (1, ?, ?, ?, ?, ?)",
        (client_name, str(client_path), detection_method,
         auto_detected, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def load_email_client_preference(db_path):
    """
    Load email client preference from database.

    Returns:
        Dictionary with client info, or None if not configured:
        {
            'client_name': 'betterbird',
            'client_path': Path('/usr/bin/betterbird'),
            'auto_detected': True,
            'last_verified': '2026-02-05T...'
        }
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return None

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check if table exists
    cursor.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='email_client_config'"
    )
    if not cursor.fetchone():
        conn.close()
        return None

    cursor.execute(
        "SELECT client_name, client_path, auto_detected, last_verified "
        "FROM email_client_config WHERE id = 1"
    )
    row = cursor.fetchone()

    # Try to get detection_method (column may not exist in old DBs)
    detection_method = 'auto'
    try:
        cursor.execute(
            "SELECT detection_method FROM email_client_config WHERE id = 1"
        )
        method_row = cursor.fetchone()
        if method_row and method_row[0]:
            detection_method = method_row[0]
    except sqlite3.OperationalError:
        pass

    conn.close()

    if not row:
        return None

    return {
        'client_name': row[0],
        'client_path': Path(row[1]),
        'auto_detected': bool(row[2]),
        'last_verified': row[3],
        'detection_method': detection_method,
    }


def get_email_client_path(db_path):
    """
    Get email client path, with verification and re-detection if needed.

    Args:
        db_path: Path to filing_widget.db

    Returns:
        Path to email client executable (or 'flatpak::app.id' string)

    Raises:
        FileNotFoundError: If no email client available
    """
    logger.info("get_email_client_path: checking db at %s", db_path)

    # Try saved preference
    config = load_email_client_preference(db_path)
    if config:
        saved_path = config['client_path']
        logger.info("  Saved preference: %s (method=%s)",
                     saved_path, config.get('detection_method'))
        # Flatpak sentinel paths aren't real files - check differently
        if str(saved_path).startswith("flatpak::"):
            logger.info("  Using saved Flatpak path: %s", saved_path)
            return str(saved_path)
        # Stale old-format flatpak export wrapper path — re-detect
        if '/flatpak/exports/bin/' in str(saved_path):
            logger.info("  Stale flatpak export wrapper path, re-detecting")
        elif saved_path.exists():
            logger.info("  Saved path verified on disk")
            return saved_path
        else:
            logger.warning("  Saved path no longer exists, re-detecting")
    else:
        logger.info("  No saved preference, detecting fresh")

    # Re-detect using full OS-aware detection
    detector = EmailClientDetector()
    result = detector.find_email_client(preferred='betterbird')

    if not result:
        logger.error("  No email client found anywhere")
        raise FileNotFoundError(
            "No email client found. "
            "Please install Betterbird or Thunderbird."
        )

    logger.info("  Detected: %s at %s (method=%s)",
                 result['client'], result['path'], result['method'])

    save_email_client_preference(
        db_path,
        result['client'],
        result['path'],
        auto_detected=True,
        detection_method=result['method'],
    )
    return result['path']


# ============================================================================
# Email Compose Launch
# ============================================================================

def launch_email_compose(subject, attachment_paths, body_html, client_path):
    """
    Launch email client with pre-populated composition window.

    Uses the Thunderbird/Betterbird ``-compose`` parameter for both native
    and Flatpak installs.  For Flatpak, ``--filesystem=home`` is added so
    the sandboxed app can read attachment files under ``$HOME``.

    Args:
        subject: Formatted email subject line
        attachment_paths: List of Path objects to filed documents
        body_html: Complete HTML email body
        client_path: Path to email client executable (or 'flatpak::app.id')

    Raises:
        FileNotFoundError: If email client not found at specified path
        ValueError: If attachments too large or command too long
        RuntimeError: If email client fails to launch
    """
    logger.info("launch_email_compose called: client_path=%s", client_path)

    # Validate attachments size
    total_size = 0
    for path in attachment_paths:
        p = Path(path)
        if p.exists():
            total_size += p.stat().st_size
            logger.debug("  attachment: %s (%d bytes)", p, p.stat().st_size)
        else:
            logger.warning("  attachment NOT FOUND: %s", p)

    if total_size > MAX_ATTACHMENT_SIZE:
        total_mb = total_size / (1024 * 1024)
        raise ValueError(
            f"Attachments too large for email ({total_mb:.1f} MB).\n"
            f"Gmail and most email providers limit attachments to 25MB.\n\n"
            f"Please file in smaller batches or use file sharing service."
        )

    # Build attachment string with raw file:// URIs (no %20 encoding —
    # Betterbird/Thunderbird expects literal spaces in paths)
    attachments = []
    for path in attachment_paths:
        p = Path(path).resolve()
        abs_path = str(p)
        # Guard against double leading slashes (would create file:////)
        if abs_path.startswith('//'):
            abs_path = abs_path[1:]
        # Verify file exists before adding
        if not p.is_file():
            logger.warning("  SKIPPING missing attachment: %s", abs_path)
            continue
        logger.debug("  attachment URI: file://%s (exists=True)", abs_path)
        attachments.append(f"file://{abs_path}")
    attachment_string = ','.join(attachments) if attachments else ''

    # URL encode the body HTML
    body_encoded = urllib.parse.quote(body_html)

    # Build -compose parameter string
    compose_params = [
        "to=''",
        f"subject='{subject}'",
    ]
    if attachment_string:
        compose_params.append(f"attachment='{attachment_string}'")
    compose_params.append(f"body='{body_encoded}'")
    compose_params.append("format=html")
    compose_string = ','.join(compose_params)
    logger.debug("  compose_string length: %d", len(compose_string))
    logger.debug("  compose_string preview: %s", compose_string[:300])

    # Check command line length
    if len(compose_string) > MAX_COMMAND_LENGTH:
        raise ValueError(
            f"Too many files to attach ({len(attachment_paths)} files). "
            f"Please file in smaller batches or attach manually."
        )

    # Launch email client
    try:
        client_str = str(client_path)
        if client_str.startswith("flatpak::"):
            # Flatpak app — grant $HOME access so sandbox can read attachments
            app_id = client_str.split("::", 1)[1]
            cmd = [
                "flatpak", "run", "--filesystem=home",
                app_id, "-compose", compose_string,
            ]
            logger.info("  Launching via flatpak run --filesystem=home: %s",
                         app_id)
        else:
            cmd = [client_str, "-compose", compose_string]
            logger.info("  Launching directly: %s -compose ...", client_str)

        logger.debug("  Full command argv[0..3]: %s", cmd[:4])
        subprocess.Popen(cmd)
        logger.info("  Process launched successfully")

    except FileNotFoundError:
        logger.error("  FileNotFoundError: %s", client_path)
        raise FileNotFoundError(
            f"Email client executable not found at: {client_path}\n\n"
            f"Please install Betterbird/Thunderbird or configure "
            f"the correct path."
        )
    except Exception as e:
        logger.error("  Unexpected error: %s", e, exc_info=True)
        raise RuntimeError(f"Failed to launch email client: {e}")


# ============================================================================
# Superseding Detection (pre-filing check)
# ============================================================================

def detect_superseding_candidates(new_file_path, destination_folder):
    """
    Detect which files will be superseded when filing this drawing.

    Called BEFORE filing to show confirmation dialog.

    Args:
        new_file_path: Path to the file being filed
        destination_folder: Where it will be filed

    Returns:
        List of filenames that will be moved to Superseded/
        Empty list if no superseding will occur
    """
    from fileuzi.services.drawing_manager import (
        parse_drawing_filename,
        is_current_drawings_folder,
        find_matching_drawings,
        compare_drawing_revisions,
    )

    new_file_path = Path(new_file_path)
    destination_folder = Path(destination_folder)

    # Check if this is a recognized drawing
    new_parsed = parse_drawing_filename(new_file_path.name)
    if not new_parsed:
        return []

    # Check if destination is a Current Drawings folder
    if not is_current_drawings_folder(destination_folder):
        return []

    # Find matching drawings already in destination
    matches = find_matching_drawings(
        destination_folder,
        new_parsed['job'],
        new_parsed['drawing'],
    )

    # Filter to only older revisions
    old_revisions = []
    for match_path, match_parsed in matches:
        comparison = compare_drawing_revisions(match_parsed, new_parsed)
        if comparison > 0:
            # Positive = new is newer, match is older → will be superseded
            old_revisions.append(match_path.name)

    return old_revisions
