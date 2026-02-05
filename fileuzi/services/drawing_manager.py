"""
Drawing management and superseding functions for FileUzi.
"""

import re
import shutil
from pathlib import Path

from fileuzi.config import STAGE_HIERARCHY
from fileuzi.utils import (
    get_file_ops_logger,
    get_circuit_breaker,
    validate_path_jail,
    PathJailViolation,
    CircuitBreakerTripped,
)


def is_drawing_pdf(filename, job_number, project_mapping=None):
    """
    Check if a PDF file is a drawing based on naming convention.

    Patterns:
        - XXXX_NN_... (new convention) e.g., 2506_20_PROPOSED FLOOR PLANS_C01.pdf
        - XXXX_NN ... (space after number) e.g., B-013_11 PLANS & SECTION.pdf
        - XXXX - NNN - ... (old convention) e.g., 2502 - 104 - BUILDING REGULATIONS NOTES_P01.pdf

    Returns:
        bool: True if filename matches drawing pattern for the given job
    """
    if not filename.lower().endswith('.pdf'):
        return False

    # Build list of prefixes to check
    prefixes_to_check = []

    if job_number:
        prefixes_to_check.append(job_number)

    if project_mapping:
        for custom_no, local_no in project_mapping.items():
            if custom_no not in prefixes_to_check:
                prefixes_to_check.append(custom_no)
            if local_no not in prefixes_to_check:
                prefixes_to_check.append(local_no)

    for prefix in prefixes_to_check:
        escaped_prefix = re.escape(prefix)

        # Pattern 1: PREFIX_NN followed by separator
        pattern1 = rf'^{escaped_prefix}_(\d{{2,3}})[\s_]'
        if re.match(pattern1, filename, re.IGNORECASE):
            return True

        # Pattern 2: PREFIX - NNN followed by separator
        pattern2 = rf'^{escaped_prefix}\s*[-–]\s*(\d{{2,3}})[\s\-–_]'
        if re.match(pattern2, filename, re.IGNORECASE):
            return True

    return False


def parse_drawing_filename_new(filename):
    """
    Parse a drawing filename in the new underscore format.

    Format: [job]_[drawing number]_[drawing name]_[stage prefix][revision number].pdf
    Example: 2506_22_PROPOSED SECTIONS_C02.pdf

    Returns:
        dict with keys: job, drawing, name, stage, revision, format
        None if parsing fails
    """
    if filename is None:
        return None

    if not filename.lower().endswith('.pdf'):
        return None

    base = filename[:-4]
    parts = [p.strip() for p in base.split('_')]
    if len(parts) < 4:
        return None

    job = parts[0]
    drawing_num = parts[1]

    if not job.isdigit() or not drawing_num.isdigit():
        return None

    last_part = parts[-1]
    stage_match = re.match(r'^(F|PL|P|W|C)(\d{2})$', last_part, re.IGNORECASE)
    if not stage_match:
        return None

    stage = stage_match.group(1).upper()
    revision = int(stage_match.group(2))
    name = '_'.join(parts[2:-1])

    return {
        'job': job,
        'drawing': drawing_num,
        'name': name,
        'stage': stage,
        'revision': revision,
        'format': 'new'
    }


def parse_drawing_filename_old(filename):
    """
    Parse a drawing filename in the old space-dash-space format.

    Format: [job] - [drawing number][revision letter or nothing] - [drawing name].pdf
    Example: 2506 - 04A - PROPOSED PLANS AND ELEVATIONS.pdf

    Returns:
        dict with keys: job, drawing, name, revision_letter, format
        None if parsing fails
    """
    if filename is None:
        return None

    if not filename.lower().endswith('.pdf'):
        return None

    base = filename[:-4]
    parts = re.split(r'\s+[-–]\s+', base)
    if len(parts) < 3:
        return None

    job = parts[0].strip()
    drawing_part = parts[1].strip()
    name = ' - '.join(parts[2:]).strip()

    if not job.isdigit():
        return None

    drawing_match = re.match(r'^(\d{2,3})([A-Z])?$', drawing_part, re.IGNORECASE)
    if not drawing_match:
        return None

    drawing_num = drawing_match.group(1)
    revision_letter = drawing_match.group(2).upper() if drawing_match.group(2) else ''

    return {
        'job': job,
        'drawing': drawing_num,
        'name': name,
        'revision_letter': revision_letter,
        'format': 'old'
    }


def parse_drawing_filename(filename):
    """
    Parse a drawing filename, auto-detecting the format.

    Returns:
        dict with parsed info, or None if not a recognized drawing format
    """
    result = parse_drawing_filename_new(filename)
    if result:
        return result

    result = parse_drawing_filename_old(filename)
    if result:
        return result

    return None


def compare_drawing_revisions(parsed_a, parsed_b):
    """
    Compare two parsed drawing revisions.

    Returns:
        positive if b > a (b is newer)
         0 if a == b (same revision)
        negative if a > b (a is newer)
    """
    if parsed_a['format'] != parsed_b['format']:
        # New format is always considered newer than old format
        if parsed_a['format'] == 'old':
            return 1   # B (new format) is newer
        else:
            return -1  # A (new format) is newer

    if parsed_a['format'] == 'new':
        stage_a = STAGE_HIERARCHY.index(parsed_a['stage'])
        stage_b = STAGE_HIERARCHY.index(parsed_b['stage'])

        if stage_a != stage_b:
            return 1 if stage_a < stage_b else -1

        rev_a = parsed_a['revision']
        rev_b = parsed_b['revision']

        if rev_a < rev_b:
            return 1   # B has higher revision, B is newer
        elif rev_a > rev_b:
            return -1  # A has higher revision, A is newer
        else:
            return 0

    else:  # old format
        letter_a = parsed_a['revision_letter']
        letter_b = parsed_b['revision_letter']

        val_a = -1 if letter_a == '' else ord(letter_a) - ord('A')
        val_b = -1 if letter_b == '' else ord(letter_b) - ord('A')

        if val_a < val_b:
            return 1   # B has higher letter, B is newer
        elif val_a > val_b:
            return -1  # A has higher letter, A is newer
        else:
            return 0


def find_matching_drawings(current_drawings_folder, job_number, drawing_number):
    """
    Scan a folder for drawings with the same job and drawing number.

    Returns:
        list of tuples: [(filepath, parsed_info), ...]
    """
    matches = []
    folder = Path(current_drawings_folder)

    if not folder.exists():
        return matches

    for item in folder.iterdir():
        if not item.is_file():
            continue

        parsed = parse_drawing_filename(item.name)
        if parsed is None:
            continue

        if parsed['job'] == str(job_number) and parsed['drawing'] == str(drawing_number):
            matches.append((item, parsed))

    return matches


def supersede_drawings(current_drawings_folder, new_file_path, projects_root, circuit_breaker=None):
    """
    Handle drawing revision superseding when a new drawing arrives.

    If older revisions of the same drawing exist, move them to Superseded subfolder
    using the safe replace_with_supersede workflow.

    Returns:
        tuple: (success, message, superseded_count)
    """
    from fileuzi.services.filing_operations import replace_with_supersede

    logger = get_file_ops_logger(projects_root)
    new_file = Path(new_file_path)

    new_parsed = parse_drawing_filename(new_file.name)
    if new_parsed is None:
        logger.warning(f"SUPERSEDE SKIP | Could not parse revision info from: {new_file.name}")
        return (True, f"⚠ Could not parse revision info from: \"{new_file.name}\"\nFiled without superseding check. Manual review recommended.", 0)

    matches = find_matching_drawings(
        current_drawings_folder,
        new_parsed['job'],
        new_parsed['drawing']
    )

    matches = [(path, parsed) for path, parsed in matches if path != new_file]

    if not matches:
        return (True, None, 0)

    to_supersede = []
    for match_path, match_parsed in matches:
        comparison = compare_drawing_revisions(match_parsed, new_parsed)
        if comparison > 0:
            # Positive means new_parsed is newer, so match is older → supersede it
            to_supersede.append((match_path, match_parsed))
        elif comparison < 0:
            # Negative means match_parsed is newer → new file is older (anomaly)
            logger.warning(
                f"SUPERSEDE ANOMALY | New file {new_file.name} appears OLDER than existing {match_path.name}"
            )

    if not to_supersede:
        return (True, None, 0)

    cb = circuit_breaker or get_circuit_breaker()
    superseded_count = 0

    for old_path, old_parsed in to_supersede:
        try:
            # Use safe superseding workflow: back up old file, then delete it
            # We pass the old file's own content as the "new" content = None
            # since we just want to move the old file to Superseded (not replace it)
            # Instead, we use replace_with_supersede to back up, then unlink old
            superseded_path = _supersede_single_drawing(
                old_path, projects_root, cb, logger
            )
            if superseded_path:
                superseded_count += 1

        except PathJailViolation as e:
            logger.error(f"SUPERSEDE BLOCKED | Path jail violation: {e}")
            raise
        except CircuitBreakerTripped:
            raise
        except Exception as e:
            logger.error(f"SUPERSEDE FAILED | {old_path.name}: {e}")
            # Abort remaining supersedes for this drawing
            break

    if superseded_count > 0:
        msg = f"Superseded {superseded_count} older revision(s) → Superseded/"
        return (True, msg, superseded_count)

    return (True, None, 0)


def _supersede_single_drawing(old_path, projects_root, circuit_breaker, logger):
    """
    Move a single old drawing to the Superseded folder using the safe workflow.

    Returns:
        Path where old file was backed up, or None if failed.
    """
    old_path = Path(old_path)
    superseded_dir = old_path.parent / 'Superseded'
    superseded_path = superseded_dir / old_path.name

    # Validate paths
    validate_path_jail(superseded_dir, projects_root)
    validate_path_jail(superseded_path, projects_root)

    # Create Superseded folder if needed
    if superseded_dir.exists() and not superseded_dir.is_dir():
        logger.error(
            f"SUPERSEDE FAILED | Cannot create Superseded folder - "
            f"a file with that name already exists: {superseded_dir}"
        )
        return None

    if not superseded_dir.exists():
        superseded_dir.mkdir(exist_ok=True)
        circuit_breaker.record("MKDIR", str(old_path.parent), str(superseded_dir))
        logger.info(f"MKDIR | Created Superseded folder: {superseded_dir}")

    # Handle naming collision in Superseded
    if superseded_path.exists():
        from datetime import datetime
        stem = old_path.stem
        suffix = old_path.suffix
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        superseded_path = superseded_dir / f"{stem}_{timestamp}{suffix}"
        validate_path_jail(superseded_path, projects_root)

    # Copy old file to Superseded
    old_size = old_path.stat().st_size
    circuit_breaker.record("COPY", str(old_path), str(superseded_path))
    shutil.copy2(str(old_path), str(superseded_path))

    # Verify copy
    if superseded_path.stat().st_size != old_size:
        superseded_path.unlink()
        logger.error(
            f"SUPERSEDE VERIFY FAILED | {old_path.name} - "
            f"copy verification failed, source retained"
        )
        return None

    # Delete old file (it's been safely backed up)
    old_path.unlink()
    logger.info(f"SUPERSEDE | {old_path.name} -> Superseded/")
    return superseded_path


def is_current_drawings_folder(folder_path):
    """
    Check if a folder is a Current Drawings folder (where superseding applies).

    Returns True if folder name contains both "CURRENT" and "DRAWING" (case insensitive).
    """
    folder_name = Path(folder_path).name.upper()
    return 'CURRENT' in folder_name and 'DRAWING' in folder_name
