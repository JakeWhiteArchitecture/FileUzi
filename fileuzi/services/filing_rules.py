"""
Filing rules loading and matching for FileUzi.
"""

import re
import csv
from pathlib import Path
from difflib import SequenceMatcher

from fileuzi.config import FILING_RULES_FILENAME, PROJECT_MAPPING_FILENAME
from fileuzi.utils import get_tools_folder_path

# Import PDF extraction functions at module level for mockability
try:
    from .pdf_generator import (
        extract_pdf_metadata_title,
        extract_pdf_first_content,
        is_valid_pdf_title,
    )
except ImportError:
    # Graceful fallback if pdf_generator not available
    def extract_pdf_metadata_title(pdf_data):
        return None
    def extract_pdf_first_content(pdf_data, char_limit=40):
        return None
    def is_valid_pdf_title(title, filename):
        return False


def get_filing_rules_path(projects_root):
    """Get the path to the filing rules CSV in the tools folder."""
    return get_tools_folder_path(projects_root) / FILING_RULES_FILENAME


def get_project_mapping_path(projects_root):
    """Get the path to the custom project number mapping CSV in the tools folder."""
    return get_tools_folder_path(projects_root) / PROJECT_MAPPING_FILENAME


def load_project_mapping(projects_root):
    """
    Load custom project number mapping from CSV file.

    Maps external project numbers (e.g., client's drawing numbers) to local job numbers.
    If the file doesn't exist, returns empty dict (tool continues working normally).

    Returns:
        dict: Mapping of custom_project_no -> local_job_no (e.g., {'B-012': '2505'})
    """
    csv_path = get_project_mapping_path(projects_root)

    if not csv_path.exists():
        return {}

    mapping = {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Support both header formats
                custom_no = (row.get('Custom Project No:', '') or
                             row.get('client_reference', '')).strip()
                local_no = (row.get('Local Project No:', '') or
                            row.get('jwa_job_number', '')).strip()
                if custom_no and local_no:
                    # Store both original and uppercase for case-insensitive matching
                    mapping[custom_no] = local_no
                    mapping[custom_no.upper()] = local_no
    except Exception as e:
        print(f"Warning: Failed to load project mapping: {e}")
        return {}

    return mapping


def apply_project_mapping(text, mapping):
    """
    Check if text contains a custom project number and return the local job number.

    Args:
        text: The text to check (filename or subject line)
        mapping: Dict of custom_project_no -> local_job_no

    Returns:
        str or None: The local job number if mapping found, None otherwise
    """
    if not mapping:
        return None

    # Check if text contains any custom project number (case-insensitive)
    text_upper = text.upper()
    for custom_no, local_no in mapping.items():
        if custom_no.upper() in text_upper:
            return local_no

    return None


def load_filing_rules(projects_root):
    """
    Load filing rules from CSV file in FILING-WIDGET-TOOLS folder.

    Returns:
        list: List of rule dicts with keys: keywords, descriptors, folder_location,
              folder_type, subfolder_structure, colour
        Returns None if CSV is missing (caller should handle error)
    """
    csv_path = get_filing_rules_path(projects_root)

    if not csv_path.exists():
        return None

    rules = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip paused rules
                pause_val = row.get('Pause', '') or row.get('pause', '')
                if pause_val.strip().lower() == 'yes':
                    continue

                # Parse keywords (support both | and , separators, case-insensitive headers)
                keywords_raw = row.get('Keywords', '') or row.get('keywords', '')
                # Split by both | and , to handle different formats
                keywords_split = re.split(r'[|,]', keywords_raw)
                keywords = [k.strip().lower() for k in keywords_split if k.strip()]

                # Parse descriptors (support both | and , separators, case-insensitive headers)
                descriptors_raw = row.get('Interchangeable_Descriptors', '') or row.get('descriptors', '')
                descriptors_split = re.split(r'[|,]', descriptors_raw)
                descriptors = [d.strip().lower() for d in descriptors_split if d.strip()]

                rules.append({
                    'keywords': keywords,
                    'descriptors': descriptors,
                    'folder_location': (row.get('Folder_Location', '') or row.get('folder_location', '')).strip(),
                    'folder_type': (row.get('Folder_Type', '') or row.get('folder_type', '')).strip(),
                    'subfolder_structure': (row.get('Subfolder_Structure', '') or row.get('subfolder_structure', '')).strip(),
                    'colour': (row.get('Colour', '') or row.get('colour', '') or '#64748b').strip(),
                })
    except Exception as e:
        print(f"Error loading filing rules: {e}")
        return None

    return rules


def match_filing_rules(filename, rules, fuzzy_threshold=0.85):
    """
    Match a filename against filing rules.

    IMPORTANT: Only matches against the filename string, NOT file contents.

    Rules:
        - Keywords alone can trigger a match
        - Keyword + Descriptor together increases confidence
        - Descriptors alone do NOT trigger a match
        - Fuzzy matching only for words >= 5 chars and similarity >= 85%

    Returns:
        list: List of matching rules with confidence scores, sorted by confidence desc
              Each item is dict with: rule, confidence
    """
    if not rules:
        return []

    filename_lower = filename.lower()
    # Remove extension for matching
    name_without_ext = filename_lower.rsplit('.', 1)[0] if '.' in filename_lower else filename_lower
    # Split into words for matching (only words 3+ chars)
    filename_words = set(w for w in re.findall(r'\b[\w\-]+\b', name_without_ext) if len(w) >= 3)

    matches = []

    for rule in rules:
        best_confidence = 0
        matched_keyword = None

        # Check each keyword
        for keyword in rule['keywords']:
            keyword_lower = keyword.lower().strip()

            # Skip empty or too-short keywords (must be at least 2 chars)
            if len(keyword_lower) < 2:
                continue

            keyword_words = keyword_lower.split()

            # Multi-word phrase: check if phrase appears with word boundaries
            if len(keyword_words) > 1:
                # Use regex to match phrase with word boundaries
                pattern = r'\b' + re.escape(keyword_lower) + r'\b'
                if re.search(pattern, name_without_ext):
                    confidence = 1.0
                    if confidence > best_confidence:
                        best_confidence = confidence
                        matched_keyword = keyword
                    continue

                # Also try word-by-word match (words can be separated)
                all_words_found = all(w in filename_words for w in keyword_words if len(w) >= 2)
                if all_words_found and len([w for w in keyword_words if len(w) >= 2]) > 0:
                    confidence = 0.95
                    if confidence > best_confidence:
                        best_confidence = confidence
                        matched_keyword = keyword
                    continue

            # Single word: must match as whole word, not substring
            # Use regex word boundary to prevent "OS" matching inside "propOSed"
            else:
                pattern = r'\b' + re.escape(keyword_lower) + r'\b'
                if re.search(pattern, name_without_ext):
                    confidence = 1.0 if len(keyword_lower) >= 4 else 0.9
                    if confidence > best_confidence:
                        best_confidence = confidence
                        matched_keyword = keyword
                    continue

            # Acronym match (for words like "BS5837" matching "bs 5837")
            keyword_no_seps = keyword_lower.replace(' ', '').replace('-', '').replace('_', '')
            if len(keyword_no_seps) >= 3 and keyword_no_seps in filename_words:
                confidence = 0.95
                if confidence > best_confidence:
                    best_confidence = confidence
                    matched_keyword = keyword
                continue

            # Also check if filename word without common separators matches keyword
            for word in filename_words:
                word_cleaned = word.replace('-', '').replace('_', '')
                if word_cleaned == keyword_no_seps and len(word_cleaned) >= 3:
                    confidence = 0.95
                    if confidence > best_confidence:
                        best_confidence = confidence
                        matched_keyword = keyword
                    break

            # Fuzzy match - only for keywords >= 5 chars
            if len(keyword_lower) >= 5:
                for word in filename_words:
                    if len(word) >= 5 and abs(len(word) - len(keyword_lower)) <= 3:
                        ratio = SequenceMatcher(None, keyword_lower, word).ratio()
                        if ratio >= fuzzy_threshold:
                            if ratio > best_confidence:
                                best_confidence = ratio
                                matched_keyword = keyword

        # If we found a keyword match, check for descriptor bonus
        if best_confidence > 0 and matched_keyword:
            for descriptor in rule['descriptors']:
                descriptor_lower = descriptor.lower()
                if descriptor_lower in name_without_ext or descriptor_lower in filename_words:
                    best_confidence = min(1.0, best_confidence + 0.05)
                    break

            matches.append({
                'rule': rule,
                'confidence': best_confidence,
                'matched_keyword': matched_keyword
            })

    # Sort by confidence descending
    matches.sort(key=lambda x: x['confidence'], reverse=True)
    return matches


def match_filing_rules_cascade(filename, rules, attachment_data=None, job_number=None, project_mapping=None):
    """
    Multi-step cascade matching for filing rules.

    Step 1: Filename matching only
    Step 2: PDF metadata title matching (if available)
    Step 3: PDF first content line matching (if available)

    Does NOT fall back to email subject - that's handled separately at the caller level.

    Returns:
        list: List of matching rules with confidence scores
    """
    # Step 1: Match against filename
    filename_matches = match_filing_rules(filename, rules)
    if filename_matches:
        return filename_matches

    # Step 2: Try PDF metadata title (if this is a PDF with data)
    if attachment_data and filename.lower().endswith('.pdf'):
        try:
            title = extract_pdf_metadata_title(attachment_data)
            if title and is_valid_pdf_title(title, filename):
                title_matches = match_filing_rules(title, rules)
                if title_matches:
                    return title_matches
        except Exception:
            pass

    # Step 3: Try PDF first content line (if this is a PDF with data)
    if attachment_data and filename.lower().endswith('.pdf'):
        try:
            first_content = extract_pdf_first_content(attachment_data)
            if first_content:
                content_matches = match_filing_rules(first_content, rules)
                if content_matches:
                    return content_matches
        except Exception:
            pass

    # Step 4: No matches found - return empty
    return []
