"""
Email composition service for FileUzi.

Generates email subjects, bodies, signatures and launches email clients
(Betterbird/Thunderbird) with pre-populated composition windows.
"""

import os
import shutil
import sqlite3
import subprocess
import urllib.parse
from datetime import datetime
from pathlib import Path

from fileuzi.config import FILING_WIDGET_TOOLS_FOLDER

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
# Email Client Detection
# ============================================================================

def _find_executable(name, known_paths, flatpak_id=None):
    """
    Find an executable by name, checking PATH, known paths, and Flatpak.

    Args:
        name: Executable name (e.g., 'betterbird')
        known_paths: List of filesystem paths to check
        flatpak_id: Optional Flatpak app ID (e.g., 'eu.betterbird.Betterbird')

    Returns:
        Path to executable, or None if not found
    """
    # 1. Check PATH
    in_path = shutil.which(name)
    if in_path:
        return Path(in_path)

    # 2. Check known filesystem paths
    for path_str in known_paths:
        path = Path(path_str)
        if path.exists():
            return path

    # 3. Check Flatpak exports (these are wrappers that work like normal executables)
    if flatpak_id:
        home = Path.home()
        flatpak_paths = [
            Path(f"/var/lib/flatpak/exports/bin/{flatpak_id}"),
            home / f".local/share/flatpak/exports/bin/{flatpak_id}",
        ]
        for fp in flatpak_paths:
            if fp.exists():
                return fp

        # 4. Check if flatpak app is installed (flatpak run would work)
        try:
            result = subprocess.run(
                ["flatpak", "info", flatpak_id],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                # App is installed; use 'flatpak run' wrapper
                # Return a sentinel path that launch_email_compose handles
                return Path(f"flatpak::{flatpak_id}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return None


def detect_email_clients():
    """
    Detect installed email clients (Betterbird and Thunderbird).

    Checks PATH, common installation paths, and Flatpak installations.

    Returns:
        Dictionary with client names and paths:
        {
            'betterbird': Path('/usr/bin/betterbird') or None,
            'thunderbird': Path('/usr/bin/thunderbird') or None
        }
    """
    home = Path.home()

    betterbird_paths = [
        # Linux
        "/usr/bin/betterbird",
        "/usr/local/bin/betterbird",
        "/opt/betterbird/betterbird",
        str(home / ".local/bin/betterbird"),
        str(home / "Applications/betterbird"),
        # Windows
        "C:\\Program Files\\Betterbird\\betterbird.exe",
        # macOS
        "/Applications/Betterbird.app/Contents/MacOS/betterbird",
    ]

    thunderbird_paths = [
        # Linux
        "/usr/bin/thunderbird",
        "/usr/local/bin/thunderbird",
        "/opt/thunderbird/thunderbird",
        str(home / ".local/bin/thunderbird"),
        # Windows
        "C:\\Program Files\\Mozilla Thunderbird\\thunderbird.exe",
        # macOS
        "/Applications/Thunderbird.app/Contents/MacOS/thunderbird",
    ]

    clients = {
        'betterbird': _find_executable(
            "betterbird", betterbird_paths,
            flatpak_id="eu.betterbird.Betterbird"
        ),
        'thunderbird': _find_executable(
            "thunderbird", thunderbird_paths,
            flatpak_id="org.mozilla.Thunderbird"
        ),
    }

    return clients


# ============================================================================
# Email Client Preference Storage
# ============================================================================

_EMAIL_CLIENT_CONFIG_SCHEMA = """
    CREATE TABLE IF NOT EXISTS email_client_config (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        client_name TEXT NOT NULL,
        client_path TEXT NOT NULL,
        auto_detected BOOLEAN DEFAULT TRUE,
        last_verified TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""


def save_email_client_preference(db_path, client_name, client_path,
                                  auto_detected=True):
    """
    Save email client preference to database.

    Args:
        db_path: Path to filing_widget.db
        client_name: 'betterbird' or 'thunderbird'
        client_path: Full path to executable
        auto_detected: Whether path was auto-detected or user-configured
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(_EMAIL_CLIENT_CONFIG_SCHEMA)
    cursor.execute(
        "INSERT OR REPLACE INTO email_client_config "
        "(id, client_name, client_path, auto_detected, last_verified) "
        "VALUES (1, ?, ?, ?, ?)",
        (client_name, str(client_path), auto_detected, datetime.now().isoformat())
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
    conn.close()

    if not row:
        return None

    return {
        'client_name': row[0],
        'client_path': Path(row[1]),
        'auto_detected': bool(row[2]),
        'last_verified': row[3],
    }


def get_email_client_path(db_path):
    """
    Get email client path, with verification and re-detection if needed.

    Args:
        db_path: Path to filing_widget.db

    Returns:
        Path to email client executable

    Raises:
        FileNotFoundError: If no email client available
    """
    # Try saved preference
    config = load_email_client_preference(db_path)
    if config:
        saved_path = config['client_path']
        # Flatpak sentinel paths aren't real files - check differently
        if str(saved_path).startswith("flatpak::"):
            return saved_path
        if saved_path.exists():
            return saved_path

    # Re-detect
    clients = detect_email_clients()

    # Prefer Betterbird
    if clients['betterbird']:
        client_name = 'betterbird'
        client_path = clients['betterbird']
    elif clients['thunderbird']:
        client_name = 'thunderbird'
        client_path = clients['thunderbird']
    else:
        raise FileNotFoundError(
            "No email client found. "
            "Please install Betterbird or Thunderbird."
        )

    save_email_client_preference(
        db_path, client_name, client_path, auto_detected=True
    )
    return client_path


# ============================================================================
# Email Compose Launch
# ============================================================================

def launch_email_compose(subject, attachment_paths, body_html, client_path):
    """
    Launch email client with pre-populated composition window.

    Args:
        subject: Formatted email subject line
        attachment_paths: List of Path objects to filed documents
        body_html: Complete HTML email body
        client_path: Path to email client executable

    Raises:
        FileNotFoundError: If email client not found at specified path
        ValueError: If attachments too large or command too long
        RuntimeError: If email client fails to launch
    """
    client_path = Path(client_path)

    # Validate attachments size
    total_size = 0
    for path in attachment_paths:
        p = Path(path)
        if p.exists():
            total_size += p.stat().st_size

    if total_size > MAX_ATTACHMENT_SIZE:
        total_mb = total_size / (1024 * 1024)
        raise ValueError(
            f"Attachments too large for email ({total_mb:.1f} MB).\n"
            f"Gmail and most email providers limit attachments to 25MB.\n\n"
            f"Please file in smaller batches or use file sharing service."
        )

    # Build attachment string with file:// URIs
    attachments = []
    for path in attachment_paths:
        abs_path = Path(path).resolve()
        file_uri = abs_path.as_uri()
        attachments.append(file_uri)

    attachment_string = ','.join(attachments)

    # URL encode the body HTML
    body_encoded = urllib.parse.quote(body_html)

    # Build compose parameters
    compose_params = [
        "to=''",
        f"subject='{subject}'",
        f"attachment='{attachment_string}'",
        f"body='{body_encoded}'",
        "format=html",
    ]
    compose_string = ','.join(compose_params)

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
            # Flatpak app - launch via 'flatpak run'
            app_id = client_str.split("::", 1)[1]
            subprocess.Popen(["flatpak", "run", app_id, '-compose', compose_string])
        else:
            subprocess.Popen([client_str, '-compose', compose_string])
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Email client executable not found at: {client_path}\n\n"
            f"Please install Betterbird/Thunderbird or configure "
            f"the correct path."
        )
    except Exception as e:
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
