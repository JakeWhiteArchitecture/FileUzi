"""
Job number detection functions for FileUzi.
"""

import re
from pathlib import Path


def scan_projects_folder(projects_root):
    """
    Scan the projects root folder for project directories.

    Looks for folders matching pattern: XXXX - Project Name or XXXXX - Project Name
    (4-5 digit job number followed by " - " and project name)

    Returns:
        list: List of tuples (job_number, project_name) sorted by job number descending
    """
    projects = []
    root_path = Path(projects_root)

    if not root_path.exists():
        return projects

    for item in root_path.iterdir():
        # Only process directories, ignore files
        if not item.is_dir():
            continue

        # Use existing parse_folder_name function to extract job number and name
        job_number, project_name = parse_folder_name(item.name)
        if job_number and project_name:
            projects.append((job_number, project_name))

    # Sort by job number descending (newest jobs first)
    projects.sort(key=lambda x: x[0], reverse=True)

    return projects


def parse_folder_name(folder_name):
    """
    Parse folder name in format: {job_number} - {project_name}

    Returns:
        tuple: (job_number, project_name) or (None, None) if invalid
    """
    match = re.match(r'^(\d{4,5})\s*[-–]\s*(.+)$', folder_name)
    if match:
        job_number = match.group(1)
        project_name = match.group(2).strip()
        return (job_number, project_name)
    return (None, None)


def extract_job_number_from_filename(filename, project_mapping=None):
    """
    Extract job number from filename in format: XXXX_... or XXXXX_... or custom prefix.

    Examples:
        2506_22_PROPOSED SECTIONS_C02.pdf -> 2506
        25061_DRAWING.pdf -> 25061
        B-012_01_DRAWING.pdf -> 2505 (if B-012 maps to 2505)

    Returns:
        str: job_number or None if not found
    """
    # Check custom project mappings FIRST (allows B-012 style prefixes)
    if project_mapping:
        for custom_no, local_no in project_mapping.items():
            # Check for patterns like B-012_... or B-012 - ...
            escaped = re.escape(custom_no)
            # Match prefix followed by underscore, space, or dash
            pattern = rf'^{escaped}[\s_\-]'
            if re.match(pattern, filename, re.IGNORECASE):
                return local_no

    # Then check standard numeric pattern
    match = re.match(r'^(\d{4,5})_', filename)
    if match:
        return match.group(1)
    return None


def find_job_number_from_path(file_path, project_mapping=None):
    """
    Find job number from file path - checks filename first, then folder structure.

    Returns:
        tuple: (job_number, project_name, project_folder_path) or (None, None, None)
    """
    path = Path(file_path)

    # First, check the filename itself for XXXX_ pattern or custom prefix
    filename = path.name
    job_number = extract_job_number_from_filename(filename, project_mapping)
    if job_number:
        return (job_number, None, None)

    # Walk up the directory tree looking for folder pattern
    for parent in path.parents:
        folder_name = parent.name
        job_number, project_name = parse_folder_name(folder_name)
        if job_number:
            return (job_number, project_name, str(parent))

    return (None, None, None)


def is_embedded_image(filename):
    """
    Check if filename looks like an embedded/inline image.
    These typically have names like 'image1769415576585.png' or 'image1769415576585'
    """
    name_lower = filename.lower()
    # Remove extension if present
    base_name = name_lower.rsplit('.', 1)[0] if '.' in name_lower else name_lower

    # Pattern: 'image' followed by digits (with or without extension)
    if re.match(r'^image\d+$', base_name):
        return True
    # Pattern: just a long number (with or without extension)
    if re.match(r'^\d{10,}$', base_name):
        return True
    # Pattern: UUID-like or hash-like names
    if re.match(r'^[a-f0-9\-]{20,}$', base_name):
        return True
    return False


def detect_project_from_subject(subject, known_projects, project_mapping=None):
    """
    Detect project number from email subject line.

    Detection logic:
    1. Strip RE:/FW:/Fwd: prefixes
    2. Check mapping CSV for client references (e.g., B-013 -> 2507)
    3. Look for 4-digit job number
    4. Check if it matches a known project

    Args:
        subject: Email subject line
        known_projects: List of (project_number, project_name) tuples
        project_mapping: Dict mapping client references to local job numbers

    Returns:
        str or None: Detected job number, or None if not found
    """
    if not subject:
        return None

    # Strip RE:/FW:/Fwd: prefixes
    cleaned = re.sub(r'^(RE|FW|Fwd):\s*', '', subject, flags=re.IGNORECASE).strip()

    # Step 1: Check project mapping for client references anywhere in subject
    if project_mapping:
        for custom_no, local_no in project_mapping.items():
            # Case-insensitive check if custom number appears in subject
            if custom_no.upper() in cleaned.upper():
                return local_no

    # Step 2: Look for 4-5 digit job number at the start
    match = re.match(r'^(\d{4,5})\s*[-–]?\s*', cleaned)
    if match:
        job_number = match.group(1)
        # Verify it's a known project
        known_job_numbers = [p[0] for p in known_projects]
        if job_number in known_job_numbers:
            return job_number

    # Step 3: Look for 4-5 digit number anywhere in subject
    all_numbers = re.findall(r'\b(\d{4,5})\b', cleaned)
    known_job_numbers = [p[0] for p in known_projects]
    for num in all_numbers:
        if num in known_job_numbers:
            return num

    return None
