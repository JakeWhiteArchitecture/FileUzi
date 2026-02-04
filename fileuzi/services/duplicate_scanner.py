"""
Duplicate file scanning for FileUzi.
"""

from pathlib import Path


def scan_for_file_duplicates(project_path, filename):
    """
    Scan ALL subfolders of a project for files with the same name.

    Args:
        project_path: Path to the project folder
        filename: Name of the file to check for duplicates

    Returns:
        list: List of Path objects where duplicates exist
    """
    duplicates = []
    project_path = Path(project_path)

    if not project_path.exists():
        return duplicates

    # Walk through all subdirectories
    for item in project_path.rglob(filename):
        if item.is_file():
            duplicates.append(item)

    return duplicates
