"""
Shared fixtures for FileUzi tests.
"""

import pytest
import sqlite3
import os
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email import encoders
from datetime import datetime
import base64


# ============================================================================
# Configuration Fixtures
# ============================================================================

@pytest.fixture
def config():
    """Configuration dict for tests."""
    return {
        'MY_EMAIL_ADDRESSES': ['jw@jakewhitearchitecture.com', 'jake.white@alternative.com'],
        'MIN_ATTACHMENT_SIZE': 3 * 1024,  # 3KB
        'MIN_EMBEDDED_IMAGE_SIZE': 20 * 1024,  # 20KB
        'CIRCUIT_BREAKER_LIMIT': 20,
    }


# ============================================================================
# Filesystem Fixtures
# ============================================================================

@pytest.fixture
def project_root(tmp_path):
    """
    Create a realistic project folder tree.

    Structure:
    - 2506_SMITH-EXTENSION/
      - ADMIN/
      - Current Drawings/
        - Superseded/
      - TECHNICAL/
      - IMPORTS-EXPORTS/
    - 2407_JONES-HOUSE/
      - ADMIN/
      - Current Drawings/
      - TECHNICAL/
    - _FILING-WIDGET-TOOLS/
      - filing_rules.csv
      - project_mapping.csv
    """
    root = tmp_path / "JWA_PROJECTS"
    root.mkdir()

    # Project 2506
    proj_2506 = root / "2506_SMITH-EXTENSION"
    proj_2506.mkdir()
    (proj_2506 / "ADMIN").mkdir()
    current_drawings = proj_2506 / "Current Drawings"
    current_drawings.mkdir()
    (current_drawings / "Superseded").mkdir()
    (proj_2506 / "TECHNICAL").mkdir()
    (proj_2506 / "IMPORTS-EXPORTS").mkdir()

    # Project 2407
    proj_2407 = root / "2407_JONES-HOUSE"
    proj_2407.mkdir()
    (proj_2407 / "ADMIN").mkdir()
    (proj_2407 / "Current Drawings").mkdir()
    (proj_2407 / "TECHNICAL").mkdir()

    # Tools folder
    tools = root / "_FILING-WIDGET-TOOLS"
    tools.mkdir()

    return root


@pytest.fixture
def tools_folder(project_root):
    """Return the tools folder path."""
    return project_root / "_FILING-WIDGET-TOOLS"


# ============================================================================
# CSV Fixtures
# ============================================================================

@pytest.fixture
def filing_rules_csv(tools_folder):
    """Create a minimal filing rules CSV."""
    csv_path = tools_folder / "filing_rules.csv"
    csv_content = """keywords,descriptors,folder_location,folder_type,colour
Survey|Topographical,survey topo,/XXXX_TECHNICAL/Surveys,Surveys,#10b981
Structural|Calcs|Calculations,structural engineer,/XXXX_TECHNICAL/Structural,Technical,#3b82f6
Ecological|Ecology,ecology bat,/XXXX_TECHNICAL/Ecology,Ecology,#22c55e
Planning|Application,planning permission,/XXXX_ADMIN/Planning,Planning,#f59e0b
Drawing|Drawings,architectural dwg,/XXXX_CURRENT-DRAWINGS,Current Drawings,#f59e0b
"""
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def project_mapping_csv(tools_folder):
    """Create a project mapping CSV."""
    csv_path = tools_folder / "project_mapping.csv"
    csv_content = """client_reference,jwa_job_number
JB/2024/0847,2506
ABC/2023/1234,2407
"""
    csv_path.write_text(csv_content)
    return csv_path


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture
def sample_db(tmp_path):
    """Create a fresh SQLite database with the correct schema."""
    db_path = tmp_path / "filing_widget.db"

    schema = """
    CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id TEXT,
        hash_fallback TEXT,
        subject TEXT,
        sender TEXT,
        recipient TEXT,
        email_date TEXT,
        direction TEXT,
        filed_at TEXT DEFAULT CURRENT_TIMESTAMP,
        filed_to TEXT,
        filed_also TEXT,
        attachments TEXT,
        job_number TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_message_id ON emails(message_id);
    CREATE INDEX IF NOT EXISTS idx_hash_fallback ON emails(hash_fallback);

    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email_address TEXT UNIQUE,
        display_name TEXT,
        company TEXT,
        last_used TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS file_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT,
        source_path TEXT,
        filed_to TEXT,
        filed_at TEXT DEFAULT CURRENT_TIMESTAMP,
        job_number TEXT,
        contact TEXT
    );
    """

    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.commit()
    conn.close()

    return db_path


# ============================================================================
# Email Fixtures
# ============================================================================

def _create_eml_content(
    from_addr,
    to_addr,
    subject,
    body,
    message_id=None,
    date=None,
    attachments=None,
    embedded_images=None,
    cc_addr=None
):
    """Helper to create .eml content programmatically."""

    if embedded_images:
        # Multipart with HTML body for embedded images
        msg = MIMEMultipart('related')

        # Create HTML body with image references
        html_body = f"<html><body><p>{body}</p>"
        for i, (cid, img_data, img_size) in enumerate(embedded_images):
            html_body += f'<img src="cid:{cid}">'
        html_body += "</body></html>"

        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)

        # Attach embedded images
        for cid, img_data, img_size in embedded_images:
            img = MIMEImage(img_data)
            img.add_header('Content-ID', f'<{cid}>')
            img.add_header('Content-Disposition', 'inline', filename=f'{cid}.png')
            msg.attach(img)
    else:
        if attachments:
            msg = MIMEMultipart()
            msg.attach(MIMEText(body, 'plain'))
        else:
            msg = MIMEText(body, 'plain')

    msg['From'] = from_addr
    msg['To'] = to_addr
    msg['Subject'] = subject

    if cc_addr:
        msg['Cc'] = cc_addr

    if message_id:
        msg['Message-ID'] = message_id

    if date:
        msg['Date'] = date
    else:
        msg['Date'] = 'Mon, 03 Feb 2026 10:30:00 +0000'

    # Add attachments
    if attachments:
        for filename, data, content_type in attachments:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(part)

    return msg.as_string()


def _create_fake_image(size_kb):
    """Create a fake PNG image of approximately the specified size in KB."""
    # PNG header + IDAT chunk with padding to reach target size
    header = b'\x89PNG\r\n\x1a\n'
    # Minimal valid PNG structure
    ihdr = b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
    idat = b'\x00\x00\x00\nIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N'
    iend = b'\x00\x00\x00\x00IEND\xaeB`\x82'

    base_png = header + ihdr + idat + iend

    # Pad to target size
    target_size = size_kb * 1024
    if len(base_png) < target_size:
        padding = b'\x00' * (target_size - len(base_png))
        # Insert padding before IEND
        return base_png[:-12] + padding + base_png[-12:]
    return base_png


def _create_fake_pdf(size_kb=50):
    """Create a fake PDF of approximately the specified size in KB."""
    # Minimal valid PDF structure
    pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
trailer
<< /Size 4 /Root 1 0 R >>
startxref
196
%%EOF
"""
    # Pad to target size
    target_size = size_kb * 1024
    if len(pdf_content) < target_size:
        padding = b' ' * (target_size - len(pdf_content))
        return pdf_content + padding
    return pdf_content


@pytest.fixture
def sample_eml_inbound(tmp_path):
    """
    Create a minimal valid inbound .eml file with:
    - Message-ID
    - From external sender
    - To Jake's email
    - Subject with job number
    - Body with "Kind regards" sign-off
    - One PDF attachment (50KB)
    """
    eml_path = tmp_path / "inbound_email.eml"

    body = """Hi Jake

Please find attached the structural calculations for the Smith Extension.

Kind regards
Bob Smith
Bob Smith Structural Engineers
Tel: 01onal 123456"""

    pdf_data = _create_fake_pdf(50)

    content = _create_eml_content(
        from_addr='bob@structural-engineers.co.uk',
        to_addr='jw@jakewhitearchitecture.com',
        subject='2506 Smith Extension - Structural Calculations',
        body=body,
        message_id='<abc123@mail.structural-engineers.co.uk>',
        attachments=[('Structural_Calcs_2506.pdf', pdf_data, 'application/pdf')]
    )

    eml_path.write_text(content)
    return eml_path


@pytest.fixture
def sample_eml_outbound(tmp_path):
    """
    Create a minimal valid outbound .eml file FROM Jake's configured email address.
    """
    eml_path = tmp_path / "outbound_email.eml"

    body = """Hi Bob

Please find attached the latest drawings for your review.

Kind regards
Jake White
Jake White Architecture"""

    pdf_data = _create_fake_pdf(50)

    content = _create_eml_content(
        from_addr='jw@jakewhitearchitecture.com',
        to_addr='bob@structural-engineers.co.uk',
        subject='2506 Smith Extension - Drawing Issue',
        body=body,
        message_id='<def456@mail.jakewhitearchitecture.com>',
        attachments=[('2506_20_FLOOR PLANS_P01.pdf', pdf_data, 'application/pdf')]
    )

    eml_path.write_text(content)
    return eml_path


@pytest.fixture
def sample_eml_embedded_images(tmp_path):
    """
    Create an outbound .eml with two inline images:
    - One 25KB image (should be extracted)
    - One 10KB image (should be filtered)
    """
    eml_path = tmp_path / "embedded_images_email.eml"

    body = "Hi Bob\n\nPlease see the screenshots below showing the beam detail query."

    img_25kb = _create_fake_image(25)
    img_10kb = _create_fake_image(10)

    content = _create_eml_content(
        from_addr='jw@jakewhitearchitecture.com',
        to_addr='bob@structural-engineers.co.uk',
        subject='2506 Smith Extension - Beam Detail Query',
        body=body,
        message_id='<ghi789@mail.jakewhitearchitecture.com>',
        embedded_images=[
            ('image001', img_25kb, 25),
            ('image002', img_10kb, 10),
        ]
    )

    eml_path.write_text(content)
    return eml_path


@pytest.fixture
def sample_eml_no_message_id(tmp_path):
    """
    Create a valid .eml with the Message-ID header stripped.
    """
    eml_path = tmp_path / "no_message_id_email.eml"

    body = """Hi Jake

Here are the documents you requested.

Thanks
Jane"""

    content = _create_eml_content(
        from_addr='jane@consultant.com',
        to_addr='jw@jakewhitearchitecture.com',
        subject='2407 Jones House - Documents',
        body=body,
        message_id=None,  # No Message-ID
    )

    eml_path.write_text(content)
    return eml_path


@pytest.fixture
def sample_eml_small_attachment(tmp_path):
    """
    Create an .eml with a small attachment (below threshold) and a regular one.
    """
    eml_path = tmp_path / "small_attachment_email.eml"

    body = "Hi Jake\n\nPlease find attached.\n\nRegards\nBob"

    small_img = _create_fake_image(2)  # 2KB signature image
    large_pdf = _create_fake_pdf(50)   # 50KB PDF

    content = _create_eml_content(
        from_addr='bob@external.com',
        to_addr='jw@jakewhitearchitecture.com',
        subject='2506 Smith Extension - Query',
        body=body,
        message_id='<small123@mail.com>',
        attachments=[
            ('signature.png', small_img, 'image/png'),
            ('Document.pdf', large_pdf, 'application/pdf'),
        ]
    )

    eml_path.write_text(content)
    return eml_path


# ============================================================================
# Drawing File Fixtures
# ============================================================================

@pytest.fixture
def drawing_files_new_format(tmp_path):
    """Create sample drawing files in new format."""
    drawings = tmp_path / "drawings"
    drawings.mkdir()

    files = [
        "2506_22_PROPOSED SECTIONS_C02.pdf",
        "2506_10_SITE PLAN_PL01.pdf",
        "2506_20_FLOOR PLANS_W01.pdf",
        "2506_20_FLOOR PLANS_P02.pdf",
        "2407_01_LOCATION PLAN_F03.pdf",
    ]

    for f in files:
        (drawings / f).write_bytes(_create_fake_pdf(10))

    return drawings


@pytest.fixture
def drawing_files_old_format(tmp_path):
    """Create sample drawing files in old format."""
    drawings = tmp_path / "drawings"
    drawings.mkdir()

    files = [
        "2506 - 04A - PROPOSED PLANS AND ELEVATIONS.pdf",
        "2506 - 04 - PROPOSED PLANS AND ELEVATIONS.pdf",
        "2506 - 04B - PROPOSED PLANS AND ELEVATIONS.pdf",
    ]

    for f in files:
        (drawings / f).write_bytes(_create_fake_pdf(10))

    return drawings
