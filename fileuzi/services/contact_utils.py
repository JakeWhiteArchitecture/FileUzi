"""
Contact name utilities for FileUzi.
"""

from pathlib import Path
from difflib import SequenceMatcher

from fileuzi.config import CONTACT_MANAGEMENT, FOLDER_KEYWORDS


def parse_import_export_folder(folder_name):
    """
    Parse an import/export folder name to extract the contact name.

    Format: {job}_{IN/OUT}_{date}_{contact}_{description}
    Example: 2508_IN_2024-01-15_SMITH-ARCHITECTS_DRAWINGS

    Returns:
        str: contact name or None
    """
    parts = folder_name.split('_')
    if len(parts) >= CONTACT_MANAGEMENT['folder_name_contact_index'] + 1:
        # Contact is the 4th part (index 3)
        return parts[CONTACT_MANAGEMENT['folder_name_contact_index']]
    return None


def find_previous_contacts(project_folder, job_number):
    """
    Search IMPORTS-EXPORTS folder for previously used contact names.

    Returns:
        list: List of unique contact names found
    """
    contacts = set()
    project_path = Path(project_folder)

    if not project_path.exists():
        return []

    # Find IMPORTS-EXPORTS folder
    imports_exports_folder = None
    for item in project_path.iterdir():
        if item.is_dir():
            name_upper = item.name.upper()
            if all(kw in name_upper for kw in FOLDER_KEYWORDS['imports_exports']):
                imports_exports_folder = item
                break
            if job_number in item.name and any(kw in name_upper for kw in FOLDER_KEYWORDS['imports_exports']):
                imports_exports_folder = item
                break

    if not imports_exports_folder:
        return []

    # Scan folders for contact names
    for item in imports_exports_folder.iterdir():
        if item.is_dir():
            contact = parse_import_export_folder(item.name)
            if contact and len(contact) > CONTACT_MANAGEMENT['min_contact_name_length']:
                # Convert from folder format back to readable
                readable = contact.replace('-', ' ').title()
                contacts.add(readable)

    return sorted(list(contacts))


def fuzzy_match_contact(input_text, contacts, threshold=None):
    """
    Find contacts that fuzzy match the input text.

    Returns:
        list: Matching contacts sorted by similarity
    """
    if threshold is None:
        threshold = CONTACT_MANAGEMENT['fuzzy_match_threshold']
    if not input_text or not contacts:
        return contacts

    input_lower = input_text.lower()
    matches = []

    for contact in contacts:
        contact_lower = contact.lower()

        # Check if input is substring
        if input_lower in contact_lower:
            matches.append((contact, 1.0))
            continue

        # Calculate similarity
        ratio = SequenceMatcher(None, input_lower, contact_lower).ratio()
        if ratio >= threshold:
            matches.append((contact, ratio))

    # Sort by similarity descending
    matches.sort(key=lambda x: x[1], reverse=True)
    return [m[0] for m in matches]
