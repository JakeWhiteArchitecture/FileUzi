# FileUzi

A PyQt6-based document filing widget designed for architectural practices. FileUzi streamlines the process of filing emails, attachments, and documents into structured project folders.

## Disclaimer

This software is provided for informational and educational purposes only. The authors, Jake White and Claude AI (Anthropic), accept no responsibility or liability for any errors, omissions, or damages arising from the use of this software. Users are solely responsible for verifying the suitability of this software for their intended purpose and for any consequences of its use. Use at your own risk.

## Features

### Email Processing
- **Email Parsing**: Extracts metadata (from, to, cc, date, subject), body text, and attachments from `.eml` files
- **Direction Detection**: Automatically detects IN (received) vs OUT (sent) emails based on configured email addresses
- **Attachment Extraction**: Lists all attachments with size filtering (ignores small signature images by default)
- **Embedded Image Detection**: Identifies images embedded in HTML emails (screenshots, inline images)

### Document Filing
- **Drag & Drop Support**: Drop emails or files directly into the widget
- **Job Number Detection**: Automatically extracts job numbers from:
  - Filenames (e.g., `2505_drawing.pdf`)
  - Email subjects (e.g., "RE: 2505 - Project Update")
  - Custom project mappings (e.g., `B-013` → `2507`)
- **Project Folder Navigation**: Auto-navigates to correct project folder based on detected job number
- **Date-organised Filing**: Files to dated import/export folders organised by month and direction

### Drawing Management
- **Drawing Detection**: Recognises architectural drawing files by naming patterns
- **Current Drawings Filing**: Option to file drawings to project's Current Drawings folder
- **Automatic Superseding**: When filing a new revision, automatically moves older versions to Superseded folder

### Print Email to PDF
- **Toggle Visibility**: Only appears when email contains embedded images >20KB
- **Full Email Rendering**: Generates PDF with email headers and HTML body
- **Embedded Image Preservation**: Converts inline image references to embedded images in the PDF
- **Structured Naming**: Generates descriptive filename from job number, date, and subject

### Duplicate Handling
- **Project-wide Scanning**: Checks entire project folder tree for existing files
- **Conflict Resolution Dialog**: Options to skip, rename with version suffix, or overwrite
- **Logging**: All duplicate decisions are logged

### Secondary Filing
- **Multiple Destinations**: File attachments to additional locations beyond the primary destination
- **Rule-based Routing**: Configure filing rules based on file type or folder structure
- **Subfolder Creation**: Supports dynamic subfolder creation with placeholders

### Safety Features
- **Circuit Breaker**: Prevents runaway file operations with per-destination limits
- **Safe Write Operations**: Atomic writes with proper error handling
- **Operation Logging**: All file operations logged for audit purposes

---

## Workflows

### Workflow 1: Filing an Incoming Email with Attachments

1. Drag the `.eml` file onto FileUzi
2. FileUzi parses the email and displays metadata, direction, and attachments
3. Job number is auto-detected from subject line or attachment names
4. Project folder auto-populates based on job number
5. Select which attachments to file
6. Optionally add secondary destinations for specific files
7. Click "File" - files are copied to the dated import folder
8. If duplicate detected, choose to skip, rename, or overwrite

### Workflow 2: Filing Outbound Email with Embedded Screenshots

1. Drag your sent `.eml` file onto FileUzi
2. FileUzi detects direction (OUT) and embedded images
3. "Print Email to PDF" toggle appears
4. Click "File" - PDF is generated with all embedded images preserved
5. PDF is filed to the dated export folder

### Workflow 3: Filing a New Drawing Revision

1. Drag the drawing PDF onto FileUzi
2. FileUzi detects it's a drawing file
3. Add "Current Drawings" as secondary destination
4. Click "File"
5. Drawing filed to primary location and Current Drawings
6. Older revision automatically moved to Superseded folder

### Workflow 4: Filing with Custom Project Mapping

1. Configure `project_mapping.csv` with client references mapped to your job numbers
2. Drag email or file with client reference in the name/subject
3. FileUzi resolves to your internal job number
4. File as normal

### Workflow 5: Batch Filing Multiple Files

1. Drag multiple files onto FileUzi
2. All files listed with checkboxes - select/deselect as needed
3. Job number detected from first matching file
4. Add secondary destinations for specific files
5. Click "File" - all selected files copied to destination

### Workflow 6: Handling Duplicate Files

1. Drag file onto FileUzi and click "File"
2. If duplicate detected, dialog shows filename and existing locations
3. Choose: Skip, Rename (adds `_v2` suffix), or Overwrite
4. Decision is logged for audit trail

---

## User Stories

1. **I want to** drag an email onto a widget **so that** I can quickly file it to the correct project folder without manual navigation.

2. **I want** job numbers auto-detected **so that** I don't have to manually look up which project an email belongs to.

3. **I want to** file drawings to Current Drawings **so that** the latest revisions are always in the right place.

4. **I want** old drawing revisions automatically superseded **so that** Current Drawings always contains only the latest versions.

5. **I want** a PDF version of emails with embedded images **so that** visual information isn't lost when archiving.

6. **I want** duplicate file warnings **so that** I don't accidentally overwrite important documents.

7. **I want** client project references mapped to our job numbers **so that** I can file documents regardless of how they're labelled.

8. **I want to** file documents to multiple locations **so that** they're accessible in both the archive and category folders.

9. **I want** all filing operations logged **so that** I can audit what was filed and when.

10. **I want** small signature images auto-ignored **so that** I don't clutter the project with unnecessary files.

---

## Configuration

### Email Addresses
Configure your email addresses for IN/OUT detection:
```python
MY_EMAIL_ADDRESSES = [
    "you@yourcompany.com",
]
```

### Project Mapping CSV
Create `project_mapping.csv` for custom project references:
```csv
custom_reference,local_job
CLIENT-001,2505
B-013,2507
```

### Minimum Attachment Size
Adjust the threshold for auto-selecting attachments (default 3KB to skip signature images).

---

## Dependencies

### Required
- Python 3.9+
- PyQt6

### Optional (for PDF generation)
- `weasyprint` (preferred)
- `xhtml2pdf` (fallback)

---

## Authors

- **Jake White** - Architecture & Design
- **Claude AI (Anthropic)** - Code Implementation
