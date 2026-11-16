#!/usr/bin/env python3
"""
FileUzi Rename - right-click a folder in GNOME Files and rename it to
    JOB_IN_DD-MM-YYYY_SENDER_DESCRIPTION
or  JOB_OUT_DD-MM-YYYY_RECIPIENT_DESCRIPTION

- Description is pre-filled from the files inside: extensions, then keyword
  rules, then (optional) the tiny bekko embedding model for anything else.
- Date is the day the folder was created; it only asks if the files inside
  are dated differently.
- "Also file to?" uses FileUzi's filing_rules.csv, found automatically by
  walking up to the *FILING-WIDGET-TOOLS* folder.

Optional AI matching:  python3 -m pip install --user onnxruntime tokenizers
                       python3 fileuzi_rename.py --download-model   (once; the only online step:
                       bekko for text, Mirage for images)
No telemetry: every normal run blocks all network access for this process.
Test from a terminal:  python3 fileuzi_rename.py --test "2505 Spec rev B.pdf" ...

Symlink this file into ~/.local/share/nautilus/scripts as "File IN",
"File OUT", "Also File To" and (optionally) "File Emails". The script reads its
own name to know which; "Also File To" skips the rename and just offers the
extra filing. Selected .eml emails are filed by any of them (direction comes
from the email); "File Emails" files emails only and ignores folders.
"""
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

JOB_RE = re.compile(r"^([A-Za-z]?-?\d{3,5})(?=[_ \-]|$)")   # "2505_", "2505 ", "2505-", "B-013_"
SKIP_DIRS = {"IMPORTS-EXPORTS", "IMPORTS EXPORTS", "SUPERSEDED", "ARCHIVE"}
RULES_FOLDER, RULES_FILE = "*FILING-WIDGET-TOOLS*", "filing_rules.csv"

# Folder name style while you move between systems:
#   True  -> 2505_OUT_14-11-2026_SMITH_DETAIL_T      (no spaces)
#   False -> 2505_OUT_14-11-2026_SMITH_DETAIL T      (spaces inside fields)
UNDERSCORES = True

# ---------- description vocabulary ----------
# Each group: (name used for several files, filename keywords, words the model
# matches against). One file in a group -> its own title ('DETAIL T');
# several -> the group name ('DETAILS'). Order here = order in the folder name.
CATEGORIES = [
    ("PLANS",              r"\bplans?\b|floor ?plan|site plan|layout",
                           "floor plans, site plan, layout plan, proposed plans"),
    ("ELEVATIONS",         r"elevation",       "elevations, front rear and side elevations"),
    ("SECTIONS",           r"\bsections?\b",   "sections, cross sections"),
    ("DETAILS",            r"\bdetails?\b",    "construction details, detail drawings, junction details"),
    ("CGI VIEWS",          r"\b3d\b|\bcgis?\b|visuali[sz]|render|perspective",
                           "CGI views, 3D visualisations, renders, perspectives"),
    ("MATERIAL SWATCHES",  r"swatch|sample|\bmaterials?\b|\bfinish(?:es)?\b|colour|color|\bral\b",
                           "material swatches, samples, finishes, colour options"),
    ("D&A STATEMENT",      r"\bdas\b|\bd ?& ?a\b|design (and |& )?access",
                           "design and access statement"),
    ("PLANNING STATEMENT", r"planning statement", "planning statement, planning supporting statement"),
    ("HERITAGE STATEMENT", r"heritage",        "heritage statement, heritage impact assessment"),
    ("SPECIFICATION",      r"\bspec",          "specification, schedule of works, materials schedule"),
    ("STRUCTURAL CALCS",   r"structural|calcs?\b|calculation",
                           "structural calculations, engineer calcs, beam design"),
    ("SAP CALCS",          r"\bsap\b|\bepc\b|part l", "SAP calculations, energy assessment, EPC"),
    ("SURVEYS",            r"survey|topo|measured", "measured survey, topographical survey, existing plans"),
    ("ECOLOGY REPORTS",    r"ecolog|\bbats?\b|newt", "bat survey, ecology report, protected species"),
    ("FIRE STRATEGY",      r"fire",            "fire strategy, fire safety, means of escape"),
    ("DECISION NOTICE",    r"decision",        "planning decision notice, approval, refusal"),
    ("PARTY WALL NOTICES", r"party wall|\bpwa\b", "party wall notice, party wall award"),
    ("FEE PROPOSAL",       r"\bfee",           "fee proposal, quotation, terms of appointment"),
    ("INVOICES",           r"invoice",         "invoice, payment, receipt"),
    ("MINUTES",            r"minutes|meeting", "meeting minutes, notes, agenda"),
    ("MARKUPS",            r"mark ?ups?|comments|redline", "markups, comments, redlines, feedback"),
    ("ISSUE SHEET",        r"issue sheet|transmittal|register", "drawing issue sheet, transmittal"),
    ("PHOTOS",             r"\bphotos?\b|\bimg\b|\bdsc\b", "site photos, photographs"),
]
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic"}
# Drawing groups: one file -> its own title ('DETAIL T'). Documents always use
# the group name ('D&A STATEMENT').
TITLE_GROUPS = {"PLANS", "ELEVATIONS", "SECTIONS", "DETAILS", "CGI VIEWS"}
DROP_WORDS = {"PROPOSED"}        # 'PROPOSED ELEVATIONS' -> 'ELEVATIONS' (EXISTING is kept)
MAX_DESC = 120                   # characters; folder names have a length limit

EMBED_MODEL = "hotchpotch/bekko-embedding-v1-a8m"
EMBED_THRESHOLD = 0.45     # lower = model decides more often, higher = only when confident
DEST_THRESHOLD = 0.45      # how sure the model must be to suggest an 'Also file to' folder (was 0.35: too many odd ones)



MODEL_DIR = Path(__file__).resolve().parent / "models" / "bekko-embedding-v1-a8m"


class Embedder:
    """bekko embedding model via onnxruntime, loaded ONLY from MODEL_DIR on disk
    (fetch it once with --download-model). No Hugging Face library at runtime."""

    def __init__(self):
        import json
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        if hasattr(ort, "disable_telemetry_events"):
            ort.disable_telemetry_events()                 # (Windows-only feature; harmless)
        onnx = MODEL_DIR / "onnx" / "model.onnx"
        if not onnx.is_file():
            found = sorted(MODEL_DIR.glob("**/*.onnx"))
            if not found:
                raise FileNotFoundError(f"No model in {MODEL_DIR}: run --download-model once")
            onnx = found[0]
        self.np = np
        opts = ort.SessionOptions()
        opts.intra_op_num_threads, opts.inter_op_num_threads = MODEL_THREADS, 1
        self.session = ort.InferenceSession(str(onnx), sess_options=opts, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
        self.tok.enable_truncation(128)
        self.tok.enable_padding()
        self.pooling = "mean"
        pool_cfg = MODEL_DIR / "1_Pooling" / "config.json"
        if pool_cfg.is_file():
            cfg = json.loads(pool_cfg.read_text())
            if cfg.get("pooling_mode_cls_token"):
                self.pooling = "cls"
            elif cfg.get("pooling_mode_lasttoken"):
                self.pooling = "last"

    def encode(self, texts):
        np = self.np
        enc = self.tok.encode_batch(list(texts))
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        out = self.session.run(None, {k: v for k, v in feed.items() if k in self.inputs})[0]
        if out.ndim == 3:                       # token vectors -> one vector each
            if self.pooling == "cls":
                out = out[:, 0]
            elif self.pooling == "last":
                out = out[np.arange(len(out)), mask.sum(1) - 1]
            else:
                m = mask[..., None]
                out = (out * m).sum(1) / np.maximum(m.sum(1), 1)
        return out / np.linalg.norm(out, axis=1, keepdims=True)

    def best_matches(self, items, labels):
        """For each item, (best label index, score)."""
        sims = self.encode(items) @ self.encode(labels).T
        return [(int(r.argmax()), float(r.max())) for r in sims]


_embedder = "unset"
import threading as _threading
MODEL_LOCK = _threading.RLock()     # one model working at a time: they take turns on the CPU, not fight for it
MODEL_THREADS = 3                   # of the N150's 4 cores: one always stays free for the panel
PDF_LOCK = _threading.Lock()
DB_LOCK = _threading.Lock()         # one write to the examples database at a time
SANDBOX_MODEL = True       # run the model in a bubblewrap sandbox (falls back if unavailable)


def sandbox_cmd(flag="--embed-worker", ro=(), rw=(), program=None):
    """The model runs in its own process with: no network (empty network
    namespace), a read-only view of ONLY system files, your Python packages,
    this script and the model folder. No projects, no home folder, no writes."""
    script = str(Path(__file__).resolve())
    py = str(Path(sys.executable).resolve())
    worker = list(program) if program else [py, script, flag]
    bwrap = shutil.which("bwrap")
    if bwrap:
        import site
        cmd = [bwrap, "--unshare-all", "--die-with-parent", "--new-session",
               "--ro-bind", "/usr", "/usr", "--ro-bind-try", "/etc", "/etc",
               "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--chdir", "/tmp"]
        for link in ("bin", "lib", "lib64", "sbin"):          # Fedora's /bin -> usr/bin etc.
            target = Path("/" + link)
            if target.is_symlink():
                cmd += ["--symlink", os.readlink(target), "/" + link]
            elif target.is_dir():
                cmd += ["--ro-bind", str(target), "/" + link]
        extra = {str(Path(py).parent.parent), site.getusersitepackages(), str(MODEL_DIR.parent)}
        extra |= {p for p in sys.path if p and Path(p).is_dir() and not p.startswith(("/usr", "/tmp"))
                  and "site-packages" in p}
        for path in sorted(extra):
            if Path(path).exists():
                cmd += ["--ro-bind", path, path]
        for path in ro:                                   # e.g. llama.cpp and the model folder
            if Path(path).exists():
                cmd += ["--ro-bind", str(path), str(path)]
        for path in rw:                                   # e.g. the examples cache
            cmd += ["--bind", str(path), str(path)]
        cmd += ["--ro-bind", script, script, "--setenv", "HOME", str(Path.home())]
        return cmd + worker, "bubblewrap"
    if shutil.which("unshare"):
        return ["unshare", "--user", "--map-root-user", "--net", "--"] + worker, "network namespace only"
    return None, None


class SandboxedEmbedder:
    """Same interface as Embedder, but the model lives in a sandboxed child
    process. Only filenames/labels go in, only scores come out."""

    def __init__(self, cmd):
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
        if json.loads(self.proc.stdout.readline() or "{}").get("ready") is not True:
            self.proc.kill()
            raise RuntimeError("sandboxed model didn't start")

    def best_matches(self, items, labels):
        with MODEL_LOCK:                                   # one model at a time
            self.proc.stdin.write(json.dumps({"items": list(items), "labels": list(labels)}) + "\n")
            self.proc.stdin.flush()
            reply = json.loads(self.proc.stdout.readline())
        return [tuple(x) for x in reply["matches"]]


def worker_manners():
    """Model workers: lower priority than the panel, and no more than MODEL_THREADS cores."""
    try:
        os.nice(10)
    except OSError:
        pass
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "CACTUS_NUM_THREADS"):
        os.environ[k] = str(MODEL_THREADS)
    try:
        os.sched_setaffinity(0, set(sorted(os.sched_getaffinity(0))[:MODEL_THREADS]))
    except (AttributeError, OSError):
        pass


def embed_worker():
    """Child process inside the sandbox: load the model, answer line by line."""
    worker_manners()
    block_network()
    try:
        emb = Embedder()
    except Exception as e:
        print(json.dumps({"ready": False, "error": repr(e)}), flush=True)
        return
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        req = json.loads(line)
        print(json.dumps({"matches": emb.best_matches(req["items"], req["labels"])}), flush=True)


SANDBOX_STATUS = "not loaded"


def get_embedder():
    """Load once; None if onnxruntime/tokenizers/model aren't available."""
    global _embedder, SANDBOX_STATUS
    if _embedder == "unset":
        _embedder = None
        if not (MODEL_DIR / "tokenizer.json").is_file():
            SANDBOX_STATUS = "no model (run --download-model)"
            return None
        reason = "SANDBOX_MODEL is switched off in the script settings"
        if SANDBOX_MODEL:
            cmd, kind = sandbox_cmd()
            reason = "bubblewrap (bwrap) wasn't found"
            if cmd:
                try:
                    _embedder = SandboxedEmbedder(cmd)
                    SANDBOX_STATUS = f"sandboxed ({kind})"
                    if kind != "bubblewrap":
                        warn_sandbox(f"{reason}. The model is in a network-isolated process, "
                                     "but it can see your files.")
                    return _embedder
                except Exception as e:
                    reason = f"bubblewrap failed to start the model ({e})"
        try:
            _embedder = Embedder()
            SANDBOX_STATUS = "in-process (network still blocked)"
            warn_sandbox(f"{reason}. The model is running inside the tool itself "
                         "(internet still blocked, but no file isolation).")
        except Exception as e:
            print(f"Embedding model not used: {e!r}", file=sys.stderr)
    return _embedder


def warn_sandbox(detail):
    """Tell you, every run, when the model is NOT inside bubblewrap."""
    SANDBOX_WARNINGS.append(detail)
    if "--test" in sys.argv:
        print("WARNING: model is not in bubblewrap:", detail)
        return
    message("warning", "The AI model is NOT running inside bubblewrap.\n\n" + detail +
            "\n\nCheck: which bwrap   (install: sudo dnf install bubblewrap)")


SANDBOX_WARNINGS = []


# ---------- Mirage (Cactus vision model): logo or real content? ----------
MIRAGE_DIR = MODEL_DIR.parent / "mirage"
USE_MIRAGE = True                       # ask Mirage about new images (if downloaded)
VISION_MIN_CONF = 0.6                   # below this, an image is kept as content (safer)
# Branding vs content options. A specific content list matters: a real image
# then always has a good match, and both groups' scores are added up.
VISION_BRANDING_LIST = ["company logo", "social media icon", "email signature graphic", "banner or advert"]
VISION_CONTENT_LIST = ["site photo", "hand sketch", "floor plan", "elevation or section",
                       "construction detail", "marked-up drawing", "screenshot",
                       "extract from a technical document", "material swatch or sample",
                       "CGI or 3D visualisation"]
VISION_CHOICES = VISION_BRANDING_LIST + VISION_CONTENT_LIST
VISION_BRANDING = set(VISION_BRANDING_LIST)
# folder-description wording for what Mirage saw
VISION_DESC = {"site photo": "SITE PHOTOS", "hand sketch": "SKETCH", "floor plan": "PLAN",
               "elevation or section": "ELEVATION", "construction detail": "DETAIL",
               "marked-up drawing": "MARKUPS", "screenshot": "SCREENSHOT",
               "extract from a technical document": "TECHNICAL EXTRACT",
               "material swatch or sample": "MATERIAL SWATCHES", "CGI or 3D visualisation": "CGI VIEWS"}


# PDFs that the filename rules and bekko can't place ('Scan_0001.pdf',
# 'Document.pdf'): page 1 is rendered (inside the sandbox) and Mirage says what it is.
MIRAGE_PDF_PAGES = True
MAX_PDF_LOOKS = 6                       # per folder/email, to keep it quick
PDF_PAGE_DESC = {                       # Mirage's answer -> folder wording
    "floor plan": "PLANS", "site or location plan": "SITE PLAN", "elevation or section": "ELEVATIONS",
    "construction detail": "DETAILS", "CGI or 3D visualisation": "CGI VIEWS",
    "site photo": "SITE PHOTOS", "marked-up drawing": "MARKUPS", "hand sketch": "SKETCH",
    "letter": "LETTER", "report or statement": "REPORT", "certificate": "CERTIFICATE",
    "application form": "APPLICATION FORM", "structural calculations": "STRUCTURAL CALCS",
    "specification or schedule": "SPECIFICATION", "product data sheet or brochure": "PRODUCT DATA SHEET",
    "invoice or fee proposal": "FEE PROPOSAL", "meeting minutes": "MINUTES",
}
PDF_PAGE_CHOICES = list(PDF_PAGE_DESC)
WEAK_TITLE = re.compile(r"^(?:SCAN|SCANNED|DOC|DOCUMENT|FILE|IMG|IMAGE|ATTACHMENT|UNTITLED|PRINT|"
                        r"OUTPUT|NEW|COPY|PAGE|PDF|DRAFT|EMAIL)?[\s\d()-]*$")


def weak_title(filename):
    """'Scan_0001.pdf', 'Document (3).pdf', '20261114.pdf' say nothing about the contents."""
    title = file_title(filename) or ""
    title = re.sub(r"\b(?:REV(?:ISION)?|ISSUE|VER(?:SION)?|DRAFT|FINAL|COPY)\b\.?\s*[A-Z]?\d*", " ", title)
    return len(re.sub(r"[^A-Z]", "", title)) < 3 or bool(WEAK_TITLE.match(title.strip()))


def mirage_files():
    """(weights, engine library) inside MIRAGE_DIR, or (None, None)."""
    weights = next(iter(sorted(MIRAGE_DIR.glob("*.cact"))), None)
    lib = next(iter(sorted(p for p in MIRAGE_DIR.rglob("libcactus*") if p.is_file())), None)
    return weights, lib


def find_choice(obj, with_probs=False, choices=None):
    """Pull (choice, confidence[, probability table]) out of Mirage's JSON,
    whatever its exact layout."""
    choices = set(choices or VISION_CHOICES)
    best, conf, table = None, None, {}
    def walk(o, key=None):
        nonlocal best, conf, table
        if isinstance(o, dict):
            probs = {k: v for k, v in o.items() if k in choices and isinstance(v, (int, float))}
            if probs:                                  # {"company logo": 0.9, "hand sketch": 0.1}
                k = max(probs, key=probs.get)
                best, conf, table = k, float(probs[k]), {a: float(b) for a, b in probs.items()}
                return
            for k, v in o.items():
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, str) and o in choices and best is None:
            best = o
        elif isinstance(o, (int, float)) and key and re.search(r"conf|prob|score", str(key), re.I) and conf is None:
            conf = float(o)
    walk(obj)
    return (best, conf, table) if with_probs else (best, conf)


def vision_verdict(label, conf, table=None):
    """(is_branding, score). With a full table, ALL branding options are added
    up against ALL content options; otherwise the top label decides. Unsure =
    content (an extra PDF beats a lost sketch)."""
    if table:
        brand = sum(v for k, v in table.items() if k in VISION_BRANDING)
        content = sum(v for k, v in table.items() if k not in VISION_BRANDING)
        total = (brand + content) or 1
        return brand / total >= VISION_MIN_CONF, brand / total
    if label in VISION_BRANDING:
        return conf is None or conf >= VISION_MIN_CONF, conf
    return False, conf


def vision_worker():
    """Child process inside bubblewrap: image bytes in, Mirage's choice out."""
    import base64
    worker_manners()
    block_network()
    os.environ["CACTUS_TELEMETRY"] = "0"
    weights, lib = mirage_files()
    try:
        if not weights or not lib:
            raise FileNotFoundError(f"Mirage not found in {MIRAGE_DIR}: run --download-model")
        os.environ["CACTUS_LIB_PATH"] = str(lib)
        from cactus import Mirage
        model = Mirage(weights=str(weights))
    except Exception as e:
        print(json.dumps({"ready": False, "error": repr(e)}), flush=True)
        return
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            req = json.loads(line)
            choices = req.get("choices") or VISION_CHOICES
            data = base64.b64decode(req["image"])
            if req.get("pdf"):                        # untrusted PDF: rendered in here, not outside
                data = render_first_page(data)
            raw = model.extract(data, {"image_type": {"enum": choices}})
            choice, conf, table = find_choice(raw, with_probs=True, choices=choices)
            print(json.dumps({"choice": choice, "conf": conf, "table": table, "raw": raw}, default=str), flush=True)
        except Exception as e:
            print(json.dumps({"choice": None, "conf": None, "error": repr(e)}), flush=True)


def render_first_page(pdf_bytes):
    """Page 1 of a PDF as PNG bytes (poppler's pdftoppm, else pypdfium2).
    Only ever called inside the sandboxed vision worker."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "in.pdf", Path(tmp) / "page"
        src.write_bytes(pdf_bytes)
        if shutil.which("pdftoppm"):
            subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-png", "-singlefile",
                            "-scale-to", "896", str(src), str(out)],
                           capture_output=True, timeout=30, check=True)
            return (Path(tmp) / "page.png").read_bytes()
        import io
        import pypdfium2                              # pip install --user pypdfium2
        page = pypdfium2.PdfDocument(str(src))[0]
        img = page.render(scale=896 / max(page.get_size())).to_pil()
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()


class VisionClient:
    """Mirage in a sandboxed child process (bubblewrap when available)."""

    def __init__(self, cmd):
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
        reply = json.loads(self.proc.stdout.readline() or "{}")
        if reply.get("ready") is not True:
            self.proc.kill()
            raise RuntimeError(reply.get("error", "Mirage didn't start"))

    def ask(self, data, choices=None, pdf=False):
        import base64
        with MODEL_LOCK:                                   # one model at a time
            self.proc.stdin.write(json.dumps({"image": base64.b64encode(data).decode(),
                                              "choices": choices, "pdf": pdf}) + "\n")
            self.proc.stdin.flush()
            return json.loads(self.proc.stdout.readline())


_vision = "unset"


def get_vision():
    """Mirage client, or None (not downloaded / switched off / failed)."""
    global _vision
    if _vision == "unset":
        _vision = None
        weights, lib = mirage_files()
        if not (USE_MIRAGE and weights and lib):
            return None
        cmd, kind = sandbox_cmd("--vision-worker") if SANDBOX_MODEL else (None, None)
        if kind != "bubblewrap":
            warn_sandbox("Mirage (the image model) can't run inside bubblewrap here"
                         + (" (sandbox switched off)" if not SANDBOX_MODEL else "")
                         + ", so it isn't being used. Images are judged by the simple rules instead.")
            return None
        try:
            _vision = VisionClient(cmd)
        except Exception as e:
            warn_sandbox(f"Mirage didn't start in bubblewrap ({e}); using the simple rules.")
    return _vision


PDF_LOOKS = {}            # fingerprint -> (label, conf): each PDF looked at once per run
PDF_SEEN_AS = {}          # filename -> what Mirage saw on page 1 (shown in the panel)


PDF_TEXT_FOR_LLM = True                 # the model also reads page 1 of attached PDFs (as text)
PDF_TEXT_MAX = 3                        # PDFs per email
PDF_TEXT_CHARS = 300                    # of each page 1


def pdf_page_text(data, chars=PDF_TEXT_CHARS):
    """The text on page 1 of a PDF (poppler's pdftotext, inside bubblewrap with
    only that one file visible and no network). '' for scans or on any problem."""
    import tempfile
    tool = shutil.which("pdftotext")
    if not tool:
        return ""
    with tempfile.TemporaryDirectory(prefix="fileuzi-pdf-") as tmp:
        src = Path(tmp) / "in.pdf"
        src.write_bytes(data if isinstance(data, bytes) else Path(data).read_bytes())
        cmd, kind = sandbox_cmd(ro=[tmp], program=[tool, "-f", "1", "-l", "1", "-enc", "UTF-8", str(src), "-"])
        if kind != "bubblewrap":                       # someone else's file: only ever opened sandboxed
            return ""
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=15).stdout.decode("utf-8", "replace")
        except (subprocess.TimeoutExpired, OSError):
            return ""
    text = re.sub(r"\s+", " ", out).strip()
    if len(text) > chars:
        text = text[:chars].rsplit(" ", 1)[0] + " …"
    return text


def pdf_pages_for_llm(atts):
    """{file name: page 1 text} for PDFs whose names don't say what they are
    ('Scan_0001.pdf', '24-118 Rev A.pdf', 'Q4471.pdf'), at most PDF_TEXT_MAX."""
    if not PDF_TEXT_FOR_LLM:
        return {}
    pages = {}
    for a in atts:
        if len(pages) >= PDF_TEXT_MAX:
            break
        name = a["name"]
        if not name.lower().endswith(".pdf") or parse_drawing(name) or not weak_title(name):
            continue                                   # a name that says what it is: no need
        text = pdf_page_text(a["data"])
        if text:
            pages[name] = text
    return pages


PDF_TEXT_KINDS = [                      # words on page 1 -> what kind of document (first match wins)
    ("structural calculations", r"\bCALC(?:ULATION)?S?\b|\bSTRUCTURAL DESIGN\b"),
    ("invoice or fee proposal", r"\bINVOICE\b|\bFEE PROPOSAL\b|\bQUOTATION\b|\bESTIMATE\b"),
    ("meeting minutes", r"\bMINUTES\b"),
    ("certificate", r"\bCERTIFICATE\b"),
    ("application form", r"\bAPPLICATION FORM\b"),
    ("specification or schedule", r"\bSPECIFICATION\b|\bSCHEDULE\b"),
    ("product data sheet or brochure", r"\bDATA ?SHEET\b|\bTECHNICAL DATA\b|\bBROCHURE\b"),
    ("report or statement", r"\bREPORT\b|\bSTATEMENT\b|\bSURVEY\b|\bASSESSMENT\b|\bAPPRAISAL\b"),
    ("letter", r"\bDEAR\b|\bYOURS (?:SINCERELY|FAITHFULLY)\b"),
]


def pdf_text_kind(data):
    """What kind of document page 1's words say it is, or None (e.g. a scan)."""
    text = pdf_page_text(data, chars=600).upper()
    for label, pat in PDF_TEXT_KINDS:
        if re.search(pat, text):
            return label
    return None


def pdf_front_page(data):
    """What kind of document page 1 of a PDF is, or None. data = bytes or a Path.
    The words on the page decide it (quick); Mirage only looks at scans."""
    if isinstance(data, Path):
        try:
            data = data.read_bytes()
        except OSError:
            return None
    key = image_fingerprint(data)
    if key not in PDF_LOOKS:
        label = pdf_text_kind(data)
        if label:
            PDF_LOOKS[key] = (label, None)
        else:                                          # a scan (no words): Mirage looks at the picture
            v = get_vision() if (MIRAGE_PDF_PAGES and USE_MIRAGE) else None
            if not v:
                return None
            r = v.ask(data, PDF_PAGE_CHOICES, pdf=True)
            PDF_LOOKS[key] = (r.get("choice"), r.get("conf"))
    label, conf = PDF_LOOKS[key]
    if label not in PDF_PAGE_DESC or (conf is not None and conf < 0.35):
        return None
    return label


def name_text(filename):
    """'2505-PL-100-A Proposed_Plans.pdf' -> '2505 PL 100 A Proposed Plans'."""
    return re.sub(r"[_\-.]+", " ", Path(filename).stem).strip()


# ---------- zenity helpers ----------

def ask(title, text, default="", choices=None):
    """Text box (editable drop-down if choices given). None if cancelled."""
    text = text.replace("&", "&amp;").replace("<", "&lt;")
    cmd = ["zenity", "--entry", "--title", title, "--text", text,
           "--entry-text", default, "--width", "500"]
    r = subprocess.run(cmd + list(choices or []), capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def message(kind, text):
    # --no-markup: otherwise an '&' (e.g. D&A STATEMENT) stops the box appearing
    subprocess.run(["zenity", f"--{kind}", "--no-markup", "--text", text, "--width", "450"])


# 'Also file to?' dialog size (pixels). The Folder column can also be dragged.
DIALOG_WIDTH, DIALOG_HEIGHT = 1150, 780
FOLDER_COLUMN_WIDTH = 450


def checklist(title, text, options, ticked, labels):
    """Tick-box list of folders. Returns the chosen ones ([] if cancelled).
    Drawn with GTK for proper sizing; falls back to zenity if GTK won't load."""
    if not options:
        return []
    try:
        return gtk_checklist(title, text, options, ticked, labels)
    except Exception:
        pass
    text = text.replace("&", "&amp;").replace("<", "&lt;")
    cmd = ["zenity", "--list", "--checklist", "--title", title, "--text", text,
           "--column", "", "--column", "Folder", "--column", "Rule",
           "--print-column", "2", "--separator", "\n",
           "--width", str(DIALOG_WIDTH), "--height", str(DIALOG_HEIGHT)]
    for opt in options:
        cmd += ["TRUE" if opt in ticked else "FALSE", opt, labels.get(opt, "")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l] if r.returncode == 0 else []


def gtk_checklist(title, text, options, ticked, labels):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    dialog = Gtk.Dialog(title=title)
    dialog.set_default_size(DIALOG_WIDTH, DIALOG_HEIGHT)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    dialog.set_keep_above(True)
    dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
    dialog.add_button("OK", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)

    box = dialog.get_content_area()
    box.set_spacing(8)
    box.set_border_width(10)
    intro = Gtk.Label(label=text, xalign=0)
    intro.set_line_wrap(True)
    box.pack_start(intro, False, False, 0)

    store = Gtk.ListStore(bool, str, str)
    for opt in options:
        store.append([opt in ticked, opt, labels.get(opt, "")])
    view = Gtk.TreeView(model=store)

    def flip(path):
        store[path][0] = not store[path][0]

    tick = Gtk.CellRendererToggle()
    tick.connect("toggled", lambda renderer, path: flip(path))
    view.append_column(Gtk.TreeViewColumn("", tick, active=0))

    folder = Gtk.TreeViewColumn("Folder", Gtk.CellRendererText(), text=1)
    folder.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
    folder.set_fixed_width(FOLDER_COLUMN_WIDTH)
    folder.set_resizable(True)
    view.append_column(folder)

    rule = Gtk.TreeViewColumn("Rule", Gtk.CellRendererText(), text=2)
    rule.set_expand(True)
    view.append_column(rule)

    view.connect("row-activated", lambda v, path, col: flip(path))   # double-click toggles

    scroll = Gtk.ScrolledWindow()
    scroll.set_vexpand(True)
    scroll.add(view)
    box.pack_start(scroll, True, True, 0)

    dialog.show_all()
    response = dialog.run()
    chosen = [row[1] for row in store if row[0]] if response == Gtk.ResponseType.OK else []
    dialog.destroy()
    while Gtk.events_pending():          # let the window actually close
        Gtk.main_iteration()
    return chosen


# ---------- naming ----------

JOB_ANYWHERE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]?-?\d{3,5})(?![0-9])")


def find_job_number(folder: Path):
    """1. a job number at the START of this folder's name or any parent's
       ('2505_OUT_...', '2505-Smith House/...');
    2. otherwise the project folder (directly under JWA_PROJECTS) with the
       number ANYWHERE in its name ('Smith House 2505', 'JWA - 2505 Smith')."""
    for p in [folder, *folder.parents]:
        m = JOB_RE.match(p.name)
        if m:
            return m.group(1).upper()
    csv_path = find_rules_csv(folder)
    if csv_path:
        projects_root = csv_path.parent.parent
        for p in [folder, *folder.parents]:
            if p.parent == projects_root:
                m = JOB_ANYWHERE.search(p.name)
                return m.group(1).upper() if m else None
    return None


def guess_job_number(folder: Path):
    """Any number-looking thing in the path, nearest first: a pre-fill for
    when we have to ask."""
    for p in [folder, *folder.parents]:
        m = JOB_ANYWHERE.search(p.name)
        if m:
            return m.group(1).upper()
    return ""


def find_job_root(folder: Path):
    """Highest parent folder whose name starts with a job number."""
    root = None
    for p in folder.parents:
        if JOB_RE.match(p.name):
            root = p
    return root


def created_date(folder: Path):
    """Folder creation date; falls back to last-modified."""
    try:
        ts = int(subprocess.run(["stat", "-c", "%W", str(folder)],
                                capture_output=True, text=True).stdout.strip())
        if ts > 0:
            return date.fromtimestamp(ts)
    except Exception:
        pass
    return date.fromtimestamp(folder.stat().st_mtime)


def clean(text):
    """Uppercase, no characters that break folder names or our _ separator."""
    text = re.sub(r'[\\/:*?"<>|_]', " ", text)
    return re.sub(r"\s+", " ", text).strip().upper()


def parse_date(text, fallback):
    if not text:
        return fallback
    text = re.sub(r"[/.]", "-", text.strip())
    for fmt in ("%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def unique_path(path: Path):
    """The folder name, or with _1, _2 ... added if that name is already taken
    (e.g. two emails from the same person, same day, same description)."""
    n = 1
    candidate = path
    while candidate.exists():
        candidate = path.with_name(f"{path.name}_{n}" if UNDERSCORES else f"{path.name} ({n})")
        n += 1
    return candidate


CODE_RE = re.compile(r"^(?=.*\d)[A-Za-z0-9.\-]+$")      # 2505, B-012, 133, PL-100-A, P1
REV_PART_RE = re.compile(r"^(rev(ision)?\.?\s*)?[A-Za-z]?\d{0,2}$", re.I)  # A, P1, rev B


def split_parts(filename):
    return [p.strip() for p in re.split(r"\s+-\s+|_", Path(filename).stem) if p.strip()]


def file_title(filename):
    """'B-012 - 133 - Detail T.pdf' -> 'DETAIL T'
       '2505-PL-100-A Proposed Plans.pdf' -> 'PROPOSED PLANS'"""
    parts = split_parts(filename)
    dash_style = " - " in Path(filename).stem      # new system: 'B-012 - 133 - Detail T - A'
    keep = []
    for i, p in enumerate(parts):
        prev = parts[i - 1] if i else ""
        nxt = parts[i + 1] if i + 1 < len(parts) else ""
        if CODE_RE.match(p):
            continue
        # lone revision letter: always in dash style; in underscore style only
        # right after a drawing number ('200_B'), so 'Detail_T' keeps its T
        if REV_PART_RE.match(p) and (dash_style or CODE_RE.match(prev) or not prev):
            continue
        if re.fullmatch(r"[A-Z]{1,3}", p) and CODE_RE.match(nxt) and CODE_RE.match(prev):
            continue                                       # 'PL' in 2505_PL_200
        keep.append(p)
    words = " ".join(keep).split()
    while words and CODE_RE.match(words[0]):              # leading drawing numbers
        words.pop(0)
    title = " ".join(words)
    title = re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z])", " ", title)    # 'PROPOSED-PLANS' -> 'PROPOSED PLANS'
    title = re.sub(r"\s+rev(ision)?\.?\s*[A-Za-z]?\d{0,2}$", "", title, flags=re.I)
    return clean(title)


def drawing_number(filename):
    """Drawing number without its revision: '2505-PL-100-A ...' -> '2505-PL-100',
    'B-012 - 133 - Detail T - A' -> 'B-012-133'. None if there isn't one."""
    parts = split_parts(filename)
    if len(parts) == 1:                                    # '2505-PL-100-A Proposed Plans'
        first = parts[0].split()[0]
        if not CODE_RE.match(first):
            return None
        bits = first.split("-")
        if len(bits) < 2:                                  # just '2505': not a drawing number
            return None
        if len(bits) > 2 and REV_PART_RE.match(bits[-1]):
            bits = bits[:-1]
        return "-".join(bits).upper()
    codes = []
    for p in parts:                                        # leading code-ish parts
        if CODE_RE.match(p) or re.fullmatch(r"[A-Z]{1,3}", p):
            codes.append(p)
        else:
            break
    if len(codes) > 1 and REV_PART_RE.match(codes[-1]) and not codes[-1].isdigit():
        codes = codes[:-1]
    codes = [re.sub(r"^(\d{2,3})[A-Z]$", r"\1", c) for c in codes]   # old style '04A' -> '04'
    return "-".join(codes).upper() if any(c[:1].isdigit() or "-" in c for c in codes) and len(codes) > 1 else None


def doc_keys(filename):
    """What identifies 'the same document' across sends."""
    keys = set()
    t, n = file_title(filename), drawing_number(filename)
    if t:
        keys.add("t:" + t)
    if n:
        keys.add("n:" + n)
    return keys


def previously_sent(folder: Path, direction: str, before=None):
    """doc_keys of everything in EARLIER IN/OUT folders beside this one. With
    'before' (a date), folders dated after it don't count, so filing an old
    email after a newer one doesn't wrongly call it 'UPDATED'."""
    keys = set()
    try:
        for sib in folder.parent.iterdir():
            if sib == folder or not sib.is_dir() or f"_{direction}_" not in sib.name:
                continue
            if "YYYY" in sib.name:                         # unfilled template copies
                continue
            m = re.search(r"_(?:IN|OUT)_(\d{2}-\d{2}-\d{4})_", sib.name)
            if before and m and datetime.strptime(m.group(1), "%d-%m-%Y").date() > before:
                continue
            for f in sib.iterdir():
                if f.is_file():
                    keys |= doc_keys(f.name)
    except Exception:
        pass
    return keys


def keyword_category(filename):
    words = re.sub(r"[_\-.]+", " ", Path(filename).stem.lower())
    for i, (_, pattern, _) in enumerate(CATEGORIES):
        if re.search(pattern, words):
            return i
    if Path(filename).suffix.lower() in PHOTO_EXTS:
        return [c[0] for c in CATEGORIES].index("PHOTOS")
    return None


def classify_files(filenames, data=None):
    """{filename: category index, Mirage title or None}. bekko classifies EVERY
    file; keywords are the backup; a PDF still unplaced with a meaningless name
    gets its first page looked at by Mirage (data = {filename: bytes or Path})."""
    result = {f: None for f in filenames}
    emb = get_embedder()
    if emb and filenames:
        for f, (idx, score) in zip(filenames, emb.best_matches(
                [name_text(f) for f in filenames], [c[2] for c in CATEGORIES])):
            if score >= EMBED_THRESHOLD:
                result[f] = idx
    for f in filenames:
        if result[f] is None:
            result[f] = keyword_category(f)
    names = [c[0] for c in CATEGORIES]
    looks = 0
    for f in filenames:
        if (result[f] is None and data and f in data and f.lower().endswith(".pdf")
                and weak_title(f) and looks < MAX_PDF_LOOKS):
            looks += 1
            label = pdf_front_page(data[f])
            if label:
                PDF_SEEN_AS[f] = label
                desc = PDF_PAGE_DESC[label]
                result[f] = names.index(desc) if desc in names else desc
    return result


def tidy(title):
    return " ".join(w for w in title.split() if w not in DROP_WORDS) or title


def join_items(items):
    """['PLANS', 'ELEVATIONS', 'D&A STATEMENT'] -> 'PLANS ELEVATIONS AND D&A STATEMENT'"""
    if len(items) <= 1:
        return "".join(items)
    if all(len(i.split()) == 1 for i in items[:-1]):  # 'PLANS ELEVATIONS AND D&A STATEMENT'
        return " ".join(items[:-1]) + " AND " + items[-1]
    return " AND ".join(items)                         # 'CGI VIEWS AND MATERIAL SWATCHES AND ...'



def suggest_description(filenames, folder=None, direction="OUT", before=None, data=None):
    """Describe everything in the folder, e.g.
    'UPDATED PLANS ELEVATIONS AND D&A STATEMENT'."""
    if not filenames:
        return ""
    sent = previously_sent(folder, direction, before) if folder else set()
    if data is None and folder is not None and folder.is_dir():
        data = {f: folder / f for f in filenames}
    cats = classify_files(filenames[:60], data)

    # group files: same drawing as PDF + DWG counts once
    groups = {}                     # key -> {"titles": [...], "updated": bool}
    for f in filenames[:60]:
        idx, title = cats.get(f), file_title(f)
        if isinstance(idx, str):                    # Mirage read page 1: 'LETTER', 'REPORT'
            idx, title = None, idx
        key = ("c", idx) if idx is not None else ("t", title or clean(Path(f).stem))
        g = groups.setdefault(key, {"titles": [], "updated": True})
        if title and title not in g["titles"]:
            g["titles"].append(title)
        if not (doc_keys(f) & sent):
            g["updated"] = False    # any brand-new file -> group isn't 'updated'

    def label(key, g):
        if key[0] == "c":
            name = CATEGORIES[key[1]][0]
            if name in TITLE_GROUPS and len(g["titles"]) == 1:
                return tidy(g["titles"][0])
            return name
        return key[1]

    order = sorted(groups, key=lambda k: (k[0] != "c", k[1] if k[0] == "c" else 0))
    updated = [label(k, groups[k]) for k in order if groups[k]["updated"] and sent]
    new = [label(k, groups[k]) for k in order if not (groups[k]["updated"] and sent)]

    def build(upd, nw):
        text = ""
        if upd:   # 'UPDATED PLANS ELEVATIONS AND D&A STATEMENT'
            text = "UPDATED " + ((" ".join(upd) if all(len(i.split()) == 1 for i in upd) else
                                  " AND ".join(upd)) if nw else join_items(upd))
        if nw:
            text = (text + " AND " if text else "") + join_items(nw)
        return text

    full_updated, full_new = list(updated), list(new)   # untrimmed, for the email
    text = build(updated, new)
    while len(text) > MAX_DESC and (updated or new):   # too long: trim, say so
        (new if new else updated).pop()
        text = build(updated, new) + " AND MORE"
    LAST_SUGGESTION.update(text=text, updated=full_updated, new=full_new)
    return text


LAST_SUGGESTION = {"text": None, "updated": [], "new": []}   # remembered for the email wording


# ---------- filing rules CSV ----------

def find_rules_csv(folder: Path):
    """Walk up from the folder; failing that, look beside this script itself
    (it lives in *FILING-WIDGET-TOOLS*, next to filing_rules.csv)."""
    for start in (folder, folder.resolve()):
        for p in start.parents:
            c = p / RULES_FOLDER / RULES_FILE
            if c.is_file():
                return c
    beside = Path(__file__).resolve().parent / RULES_FILE     # resolve() follows the menu symlink
    return beside if beside.is_file() else None


def load_rules(csv_path: Path):
    rules = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            if row.get("pause", "").lower() == "yes":
                continue
            kws = [k.strip().lower() for k in re.split(r"[|,]", row.get("keywords", ""))
                   if len(k.strip()) >= 2]
            if row.get("folder_location"):           # keyword-less rules (Key-stage) kept too
                rules.append({"keywords": kws, "location": row["folder_location"],
                              "type": row.get("folder_type", ""),
                              "subfolder": row.get("subfolder_structure", ""),
                              "descriptors": row.get("interchangeable_descriptors", "")
                                             or row.get("descriptors", "")})
    return rules


FILLER = {"and", "of", "the", "for", "to", "a"}


def norm_words(text):
    """Lower-case, '&' -> 'and', drop filler words, singular: so the keyword
    'Design Access' matches 'Design and Access', 'data sheets' matches 'data sheet'."""
    text = re.sub(r"[_\-.,()]+", " ", text.lower().replace("&", " and "))
    words = []
    for w in text.split():
        if w in FILLER:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        words.append(w)
    return " ".join(words)


def match_strength(filename, rule):
    """Words in the longest keyword that matches (0 = no match), so a specific
    phrase like 'fire test certificate' (3) beats a bare 'fire' (1)."""
    name = " " + norm_words(Path(filename).stem) + " "
    best = 0
    for kw in rule["keywords"]:
        k = norm_words(kw)
        if k and f" {k} " in name:
            best = max(best, len(k.split()))
    return best


def rule_matches(filename, rule):
    return match_strength(filename, rule) > 0


def best_rules(filename, rules):
    """Rules this file belongs to: only the MOST specific keyword match wins
    (ties keep all). Key-stage is separate (an archive copy), never competing."""
    strengths = [(match_strength(filename, r), i) for i, r in enumerate(rules)
                 if r["keywords"] and not is_keystage(r)]
    top = max((st for st, _ in strengths), default=0)
    winners = [i for st, i in strengths if st == top and top > 0]
    winners += [i for i, r in enumerate(rules) if is_keystage(r) and rule_matches(filename, r)]
    return winners


def excluded_folder(name, job):
    """Never offered: hidden, Superseded/Archive, any IMPORT/EXPORT folder,
    and CAD folders (2505_CAD-FEASIBILITY, 2505-CAD..., CAD...)."""
    n = name.upper()
    if name.startswith(".") or any(k in n for k in SKIP_DIRS):
        return True
    if "IMPORT" in n or "EXPORT" in n:
        return True
    rest = n[len(job):] if job and n.startswith(job.upper()) else n
    return re.sub(r"^[\s_\-]+", "", rest).startswith("CAD")


def candidate_folders(job_root: Path, job=""):
    """Other real subfolders of the job, two levels deep (never walks deeper:
    a full scan of a big project on the server is very slow)."""
    def skip(name):
        return excluded_folder(name, job)

    out = []
    try:
        level1 = sorted(d for d in job_root.iterdir() if d.is_dir() and not skip(d.name))
    except Exception:
        return out
    for d in level1:
        out.append(d.name)
        try:
            out += [f"{d.name}/{c.name}" for c in sorted(d.iterdir())
                    if c.is_dir() and not skip(c.name)]
        except Exception:
            pass
    return out


def copy_files(src: Path, dest: Path, only=None):
    """Copy top-level files into dest. NEVER overwrites: each file is opened in
    exclusive-create mode, so an existing file makes that copy fail safely.
    Returns (copied names, skipped names)."""
    copied, skipped = [], []
    for f in sorted(src.iterdir()):
        if not f.is_file() or (only is not None and f.name not in only):
            continue
        target = dest / f.name
        try:
            with open(f, "rb") as r, open(target, "xb") as w:     # 'x' = fail if exists
                shutil.copyfileobj(r, w)
            shutil.copystat(f, target)
            copied.append(f.name)
        except FileExistsError:
            skipped.append(f.name)
    return copied, skipped


# ----- your own drawings (same rules as FileUzi's is_drawing_pdf) -----
CURRENT_DRAWINGS = "/XXXX_CURRENT-DRAWINGS"            # hard-coded in FileUzi too
MAPPING_FILE = "custom_project_number_mapping.csv"     # client project no -> your job no


def load_mapping(tools_folder: Path):
    """{'B-012': '2505', ...} from custom_project_number_mapping.csv (if present)."""
    path = tools_folder / MAPPING_FILE
    if not path.is_file():
        return {}
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            cols = reader.fieldnames or []
            low = {c: c.lower().replace(":", "").replace("_", " ").strip() for c in cols}
            custom = next((c for c in cols if any(k in low[c] for k in ("custom", "client", "external"))), None) \
                or next((c for c in cols if low[c] in ("reference", "ref", "project no", "project number")), None)
            local = next((c for c in cols if any(k in low[c] for k in ("local", "jwa", "internal"))), None) \
                or next((c for c in cols if low[c] in ("job no", "job number", "job")), None)
            if (not custom or not local) and len(cols) == 2:
                custom, local = cols
            if not custom or not local:
                return {}
            return {r[custom].strip().upper(): r[local].strip().upper()
                    for r in reader if r.get(custom, "").strip() and r.get(local, "").strip()}
    except Exception:
        return {}


def my_prefixes(job, mapping):
    """Your job number plus any client project numbers mapped to it."""
    job = job.upper()
    return [job] + [c for c, l in mapping.items() if l == job and c != job]


# A PDF also counts as YOUR drawing if its document properties match ALL of
# these (case-insensitive 'contains'). Your Archicad template leaves Keywords
# as the unfilled placeholder <PRJ_KEYWORDS>; Application is 'Archicad'.
# If you ever fill in the project keywords, update or remove that line.
OWN_DRAWING_PDF_INFO = {
    "keywords": "<PRJ_KEYWORDS>",
    "creator":  "Archicad",          # shown as 'Application' in file properties
}


def pdf_info(path: Path):
    """{'keywords': ..., 'creator': ...} from a PDF's document properties.
    Uses pypdf if installed; otherwise scans the file's start and end."""
    info = {}
    try:
        import logging
        from pypdf import PdfReader
        logging.getLogger("pypdf").setLevel(logging.CRITICAL)      # no noise on odd PDFs
        meta = PdfReader(str(path), strict=False).metadata or {}
        for key in OWN_DRAWING_PDF_INFO:
            val = meta.get("/" + key.capitalize())
            if val:
                info[key] = str(val)
        if info:
            return info
    except Exception:
        pass
    try:                                    # no pypdf: look for the raw text
        size = path.stat().st_size
        with open(path, "rb") as f:
            head = f.read(262144)
            if size > 262144:
                f.seek(max(0, size - 262144))
                tail = f.read()
            else:
                tail = b""
        blob = head + tail
        # decode PDF string escapes like \074 ('<') and \137 ('_')
        blob = re.sub(rb"\\([0-7]{3})", lambda m: bytes([int(m.group(1), 8) & 0xFF]), blob)
        blob = blob.lower()
        for key, want in OWN_DRAWING_PDF_INFO.items():
            w = want.lower()
            variants = [w.encode(), w.replace("<", "&lt;").replace(">", "&gt;").encode(),
                        w.encode("utf-16-be"), w.encode().hex().encode(),
                        w.encode("utf-16-be").hex().encode()]
            if any(v in blob for v in variants):
                info[key] = want
    except Exception:
        pass
    return info


def is_my_drawing(filename, prefixes, path: Path = None):
    """Yours if EITHER:
    - FileUzi's naming rule: a PDF named PREFIX_NN... or PREFIX - NNN - ...
      where PREFIX is your job number (or a mapped client number), OR
    - its PDF properties match OWN_DRAWING_PDF_INFO (your Archicad template).
    Consultants' drawings match neither."""
    if not filename.lower().endswith(".pdf"):
        return False
    for p in prefixes:
        e = re.escape(p)
        if re.match(rf"^{e}_(\d{{2,3}})[\s_]", filename, re.I) or \
           re.match(rf"^{e}\s*[-–]\s*(\d{{2,3}})[A-Z]?[\s\-–_]", filename, re.I):
            return True
    if path is not None and OWN_DRAWING_PDF_INFO:
        info = pdf_info(path)
        return all(want.lower() in info.get(key, "").lower()
                   for key, want in OWN_DRAWING_PDF_INFO.items())
    return False


# ----- drawing superseding (same rules as FileUzi's drawing_manager) -----
# Revision codes: stage letters then a two-digit number (F01, PL02, P01...).
# Oldest -> newest stage. Within a stage the number counts: P03 beats P02.
STAGE_HIERARCHY = ["F",     # feasibility
                   "PL",    # planning
                   "P",     # preliminary / pre-construction
                   "W",     # working / building regulations
                   "CN",    # contract
                   "C"]     # construction
MUDDLED_STAGES = {"PL", "P"}     # easily swapped by hand: between these two, go by DATE, not by code
STAGE_ALT = "|".join(sorted(STAGE_HIERARCHY, key=len, reverse=True))    # 'CN' tried before 'C'


def parse_drawing(filename):
    """New: 2506_22_PROPOSED SECTIONS_C02.pdf   Old: 2506 - 04A - PROPOSED PLANS.pdf
    Also client-numbered: B-012 - 133 - Detail T - P2.pdf"""
    if not filename.lower().endswith(".pdf"):
        return None
    base = filename[:-4]
    stages = STAGE_ALT
    job_re = r"^[A-Za-z]?-?\d+$"
    parts = [p.strip() for p in base.split("_")]
    if len(parts) >= 4 and re.match(job_re, parts[0]) and parts[1].isdigit():
        m = re.match(rf"^({stages})(\d{{2}})$", parts[-1], re.I)
        if m:
            return {"format": "new", "job": parts[0].upper(), "drawing": parts[1],
                    "stage": m.group(1).upper(),
                    "rank": (STAGE_HIERARCHY.index(m.group(1).upper()), int(m.group(2)))}
    parts = [p.strip() for p in re.split(r"\s+[-–]\s+", base)]
    if len(parts) >= 3 and re.match(job_re, parts[0]):
        m = re.match(r"^(\d{2,3})([A-Z])?$", parts[1], re.I)
        if m:
            tail = re.match(rf"^({stages})(\d{{1,2}})$", parts[-1], re.I) if len(parts) >= 4 else None
            if tail:                                       # '... - P2' revision at the end
                return {"format": "dashrev", "job": parts[0].upper(), "drawing": m.group(1),
                        "stage": tail.group(1).upper(),
                        "rank": (STAGE_HIERARCHY.index(tail.group(1).upper()), int(tail.group(2)))}
            letter = (m.group(2) or "").upper()
            return {"format": "old", "job": parts[0].upper(), "drawing": m.group(1),
                    "rank": (-1 if not letter else ord(letter) - ord("A"),)}
    return None


def is_newer(a, b):
    """Is drawing a newer than b? New format always beats old format."""
    order = {"old": 0, "dashrev": 1, "new": 2}             # newer naming beats older naming
    if a["format"] != b["format"]:
        return order[a["format"]] > order[b["format"]]
    return a["rank"] > b["rank"]


def muddled(a, b):
    """True when two revisions differ only by PL vs P, which get swapped by
    hand: their order comes from dates, not from the letters."""
    return {a.get("stage"), b.get("stage")} == MUDDLED_STAGES


def is_current_drawings(folder: Path):
    n = folder.name.upper()
    return "CURRENT" in n and "DRAWING" in n


def supersede_plan(src: Path, dest: Path, names, notes=None):
    """For a Current Drawings folder, so the result is the same whatever order
    things are filed in. Returns:
      to_supersede: existing older revisions -> move to Superseded/
      same:         incoming identical revision already current -> skip
      older:        incoming OLDER than the current one -> straight into Superseded/"""
    to_supersede, same, older = [], {}, {}
    try:
        existing = [f for f in dest.iterdir() if f.is_file()]
    except Exception:
        existing = []
    for name in names:
        new = parse_drawing(name)
        if not new:
            continue
        rivals = [(f, parse_drawing(f.name)) for f in existing]
        rivals = [(f, d) for f, d in rivals if d and (d["job"], d["drawing"]) == (new["job"], new["drawing"])]
        mixed = [(f, d) for f, d in rivals if muddled(d, new)]
        if mixed and notes is not None:
            notes += [f"{name}: PL/P mix with {f.name}, so the one filed now counts as newer" for f, _ in mixed]
        newer_current = [f for f, d in rivals if is_newer(d, new) and not muddled(d, new)]
        if newer_current:
            older[name] = newer_current[0].name            # file it as history, not current
        elif any(f.name == name or (not is_newer(new, d) and not muddled(d, new)) for f, d in rivals):
            same[name] = next(f.name for f, d in rivals
                              if f.name == name or (not is_newer(new, d) and not muddled(d, new)))
        else:
            to_supersede += [f for f, d in rivals]
    return to_supersede, same, older


def superseded_folders(current: Path):
    """Existing superseded folders inside Current Drawings, matched loosely
    ('2601_SUPERSEDED', 'SUPERSEDED', 'Superseded'), the job-named one first."""
    job = find_job_number(current) or ""
    try:
        subs = [d for d in current.iterdir() if d.is_dir() and squash(d.name, job) == "superseded"]
    except OSError:
        return []
    want = f"{job}_SUPERSEDED".upper()
    return sorted(subs, key=lambda d: (d.name.upper() != want, not d.name.upper().startswith(job.upper()),
                                       d.name))


def superseded_dir(current: Path, create=True):
    """The superseded folder for a Current Drawings folder: yours if it's there
    (e.g. 2601_SUPERSEDED), otherwise JOB_SUPERSEDED is made."""
    found = superseded_folders(current)
    if found:
        return found[0]
    job = find_job_number(current) or ""
    path = current / (f"{job}_SUPERSEDED" if job else "SUPERSEDED")
    if create:
        path.mkdir(exist_ok=True)
    return path


def move_to_superseded(old_file: Path):
    """Move into the superseded folder beside it; never overwrites (timestamp on clash)."""
    sup = superseded_dir(old_file.parent)
    target = sup / old_file.name
    if target.exists():
        target = sup / f"{old_file.stem}_{datetime.now():%Y%m%d_%H%M%S}{old_file.suffix}"
    shutil.move(str(old_file), str(target))


def squash(name, job):
    """Compare folder names loosely: no case, separators or job prefix.
    '2505_P_PLANNING', 'P Planning', 'p-planning' -> 'pplanning'."""
    n = name.lower()
    j = job.lower()
    if n.startswith(j):
        n = n[len(j):]
    return re.sub(r"[\s_\-]+", "", n)


def resolve_folder(job_root: Path, rel: str, job: str):
    """Find the real existing folder for a rule path, step by step, matching
    loosely so a near-identical existing folder is used, not duplicated.
    Returns (relative path, status): "ok", "new" (only the last folder is
    missing) or "broken" (a parent is missing too: check the CSV)."""
    current = job_root
    parts = [p for p in rel.split("/") if p]
    for i, part in enumerate(parts):
        exact = current / part
        if exact.is_dir():
            current = exact
            continue
        target = squash(part, job)
        match = None
        try:
            match = next((c for c in sorted(current.iterdir())
                          if c.is_dir() and squash(c.name, job) == target), None)
        except Exception:
            pass
        if match is None:                      # genuinely missing from here down
            missing = current.joinpath(*parts[i:])
            # only the last folder missing = fine to create; more = likely a CSV error
            return str(missing.relative_to(job_root)), ("new" if i == len(parts) - 1 else "broken")
        current = match
    return str(current.relative_to(job_root)), "ok"


def is_keystage(rule):
    t = rule.get("type", "").lower().replace(" ", "-")
    return t == "key-stage" or ("key" in t and "stage" in t)


def names_subfolder(rule):
    """Rules whose Subfolder_Structure contains DESCRIPTION (Surveys, Key-stage):
    you type that folder's name rather than it being guessed."""
    return "DESCRIPTION" in rule.get("subfolder", "")


def ask_subfolder_name(job_root: Path, base_rel: str, rule, job, desc=""):
    """Pre-filled with the CSV pattern (key-stage: just the prefix, as the name
    rarely matches the files); existing folders offered in the drop-down."""
    default, existing = subfolder_default(job_root, base_rel, rule, job, desc)
    name = ask(f"{rule['type']} ({job_root.name})",
               f"Name for the new {rule['type']} folder in {base_rel}:\n"
               "(pick an existing one from the list, or type a new name)", default, existing)
    return subfolder_rel(base_rel, name, existing, job) if name else None


def rule_path(rule, job, desc):
    """Folder_Location + Subfolder_Structure, with FileUzi's placeholders:
    XXXX -> job number, DESCRIPTION -> description (FileUzi style)."""
    path = rule["location"].replace("XXXX", job).strip("/")
    sub = rule.get("subfolder", "").strip()
    if sub and callable(desc) and "DESCRIPTION" in sub:
        desc = desc()
    if sub:
        desc_safe = re.sub(r"[^\w\-]", "", desc.upper().replace("_", " ").replace(" ", "-"))
        path += "/" + sub.replace("XXXX", job).replace("DESCRIPTION", desc_safe).strip("/")
    return path


def project_folder(folder: Path, csv_path, job=None):
    """Find the project folder for this job:
    1. in JWA_PROJECTS (beside *FILING-WIDGET-TOOLS*), the folder named with
       the job number, e.g. '2505-Smith House' or 'Smith House 2505'
    2. otherwise the folder directly under JWA_PROJECTS that contains this one
    3. otherwise the highest parent whose name starts with a job number."""
    if csv_path:
        projects_root = csv_path.parent.parent
        if job:
            try:
                def job_of(name):          # number at the start, else anywhere
                    m = JOB_RE.match(name) or JOB_ANYWHERE.search(name)
                    return m.group(1).upper() if m else None
                hits = [c for c in sorted(projects_root.iterdir())
                        if c.is_dir() and c != folder and not c.name.startswith("*")
                        and job_of(c.name) == job.upper()]
            except Exception:
                hits = []
            inside = [h for h in hits if h in folder.parents]
            if inside or len(hits) == 1:
                return (inside or hits)[0]
            if len(hits) > 1:
                pick = ask_choice("Which project folder?", f"More than one folder starts with {job}:",
                                  [h.name for h in hits])
                if pick:
                    return projects_root / pick
        for p in folder.parents:
            if p.parent == projects_root:
                return p
    return find_job_root(folder)


def ask_choice(title, text, options):
    text = text.replace("&", "&amp;").replace("<", "&lt;")
    r = subprocess.run(["zenity", "--list", "--title", title, "--text", text,
                        "--column", "Folder", "--width", "500", "--height", "300", *options],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def plan_also(anchor: Path, src: Path, job: str, filenames, desc=""):
    """Work out the 'Also file to?' suggestions WITHOUT copying anything.
    anchor = where the files will live (finds the CSV / project folder);
    src = where the files are now (read for PDF details and superseding).
    Returns a plan dict; plan['warning'] is set when there's nothing to offer."""
    plan = {"warning": None, "options": [], "labels": {}, "ticked": set(), "dest_files": {},
            "missing": set(), "broken": set(), "keystage": {}, "mine": set(), "supersede": {},
            "job": job, "job_root": None, "filenames": list(filenames)}
    if not filenames:
        plan["warning"] = "No files to file."
        return plan
    csv_path = find_rules_csv(anchor)
    job_root = project_folder(anchor, csv_path, job)
    if not job_root or job_root == anchor:
        where = (f"No folder in {csv_path.parent.parent} starts with {job}."
                 if csv_path else
                 f"filing_rules.csv wasn't found above:\n{anchor}\n"
                 f"or beside the script:\n{Path(__file__).resolve().parent}")
        plan["warning"] = (f"Couldn't work out the project folder for job {job}.\n{where}\n"
                           "So there are no 'Also file to' suggestions.")
        return plan
    plan["job_root"] = job_root
    options, labels, dest_files = plan["options"], plan["labels"], plan["dest_files"]
    missing, broken, keystage = plan["missing"], plan["broken"], plan["keystage"]

    def add_option(rel_rule, label):
        """Map a rule path onto the real folder; remember if it doesn't exist."""
        rel, status = resolve_folder(job_root, rel_rule, job)
        if rel not in options:
            options.append(rel)
            labels[rel] = label + {"ok": "", "new": "  (NEW FOLDER)",
                                   "broken": "  (PATH MISSING: check CSV, will skip)"}[status]
        if status != "ok":
            missing.add(rel)
        if status == "broken":
            broken.add(rel)
        return rel

    rules = []
    if csv_path:
        try:
            rules = load_rules(csv_path)
        except Exception as e:
            plan["warning"] = f"Couldn't read {csv_path}:\n{e}"
        rule_dest = []
        for r in rules:
            if names_subfolder(r):
                base = r["location"].replace("XXXX", job).strip("/")
                rel = add_option(base, r["type"])
                labels[rel] = labels[rel] + "  (you'll name the folder)"
                keystage[rel] = r
                rule_dest.append(rel)
            else:
                rule_dest.append(add_option(rule_path(r, job, desc), r["type"]))
        reason = {}                                    # folder -> why it's ticked
        # your own numbered drawings go to Current Drawings (below), never to a
        # rules folder: 'PROPOSED PLANS' isn't a planning statement or an ecology report
        mapping0 = load_mapping(csv_path.parent)
        own = {f for f in filenames if is_my_drawing(f, my_prefixes(job, mapping0), src / f)}
        for f in filenames:                            # most specific keyword match wins
            if f in own:
                continue
            for i in best_rules(f, rules):
                dest_files.setdefault(rule_dest[i], set()).add(f)
                reason[rule_dest[i]] = "keyword"

        # the model looks at EVERY file and suggests its best-matching rule
        kw_rules = [i for i, r in enumerate(rules) if r["keywords"] and not is_keystage(r)]
        emb = get_embedder() if kw_rules else None
        if emb:
            # descriptors left out: 'certificate', 'application' etc. are in
            # nearly every rule and only blur the match
            rule_text = [f"{rules[i]['type']}: {', '.join(rules[i]['keywords'])}" for i in kw_rules]
            unmatched = [f for f in filenames[:40] if f not in own and not any(
                f in files for files in dest_files.values())]
            # a meaningless name ('Scan_0001.pdf') is matched on what Mirage saw on page 1
            texts = [f"{name_text(f)} {PDF_SEEN_AS[f]}" if f in PDF_SEEN_AS else name_text(f)
                     for f in unmatched]
            for f, (idx, score) in zip(unmatched, emb.best_matches(texts, rule_text) if unmatched else []):
                if score >= DEST_THRESHOLD:
                    dest = rule_dest[kw_rules[idx]]
                    dest_files.setdefault(dest, set()).add(f)
                    if reason.get(dest) != "keyword":
                        best = max(score, reason.get(dest, 0) if isinstance(reason.get(dest), float) else 0)
                        reason[dest] = best
        for dest, why in reason.items():
            tag = "keyword" if why == "keyword" else f"model {why:.2f}"
            labels[dest] = f"{labels.get(dest, '')}  ({tag})"

    # Current Drawings: built in (as in FileUzi), YOUR drawings only
    mapping = load_mapping(csv_path.parent) if csv_path else {}
    prefixes = my_prefixes(job, mapping)
    mine = {f for f in filenames if is_my_drawing(f, prefixes, src / f)}
    plan["mine"] = mine
    cd_rel = add_option(CURRENT_DRAWINGS.replace("XXXX", job).strip("/"), "Current Drawings")
    labels[cd_rel] += "  (your drawings only)"
    if mine:
        dest_files[cd_rel] = set(mine)
        if cd_rel not in missing:
            labels[cd_rel] += f"  ({len(mine)} found)"
            sup, _, _ = supersede_plan(src, job_root / cd_rel, mine)
            if sup:                                    # preview only; re-checked when filing
                plan["supersede"][cd_rel] = [f.name for f in sup]
                labels[cd_rel] += f"  ({len(sup)} older to Superseded)"
    else:
        dest_files.pop(cd_rel, None)

    for rel in candidate_folders(job_root, job):
        if rel not in options:
            options.append(rel)

    plan["note"] = "Rules from filing_rules.csv." if csv_path else "No filing_rules.csv found."
    for d, files in dest_files.items():                # which files each suggestion gets
        names = sorted(files)
        shown = ", ".join(Path(n).stem for n in names[:3]) + (f" +{len(names) - 3} more" if len(names) > 3 else "")
        labels[d] = f"{labels.get(d, '')}  → {shown}"
    plan["ticked"] = {d for d in dest_files if d not in missing}   # never pre-tick a new folder
    # suggestions first, then suggestions that need a new folder, then the rest
    ticked = plan["ticked"]
    plan["options"] = ([o for o in options if o in ticked] +
                       [o for o in options if o in dest_files and o not in ticked] +
                       [o for o in options if o not in dest_files])
    return plan


def subfolder_default(job_root: Path, base_rel: str, rule, job, desc="", folder_name=""):
    """(suggested name, existing folder names) for a Surveys / Key-stage folder.
    Surveys take the IN/OUT folder's own name (folder_name) when it's known."""
    pattern = rule["subfolder"].strip().strip("/")
    prefix, _, suffix = pattern.replace("XXXX", job).partition("DESCRIPTION")
    if folder_name and not is_keystage(rule):
        default = folder_name
    elif is_keystage(rule) or not desc:
        default = prefix
    else:
        default = prefix + re.sub(r"[^\w\-]", "", desc.upper().replace("_", " ").replace(" ", "-")) + suffix
    try:
        existing = sorted((d.name for d in (job_root / base_rel).iterdir() if d.is_dir()), reverse=True)
    except Exception:
        existing = []
    return default, existing


def same_name_rel(job_root: Path, base_rel, name):
    """'base/NAME', or 'base/NAME_1', 'base/NAME_2'... if that folder is already
    there: a Surveys subfolder named exactly like its IN/OUT folder."""
    name = re.sub(r'[\\/:*?"<>|]', "-", name.strip())
    candidate, n = name, 0
    while (job_root / base_rel / candidate).exists():
        n += 1
        candidate = f"{name}_{n}"
    return f"{base_rel}/{candidate}"


def subfolder_rel(base_rel, name, existing, job):
    """Typed name -> 'base/name', reusing an existing folder that only differs
    in case/spacing/job prefix (never a near-duplicate folder)."""
    name = re.sub(r'[\\/:*?"<>|]', "-", (name or "").strip())
    if not name:
        return None
    match = next((e for e in existing if squash(e, job) == squash(name, job)), None)
    return f"{base_rel}/{match or name}"


def zenity_confirm_supersede(to_move):
    listing = "\n".join(f"  {f.parent.name}/{f.name}" for f in to_move[:20])
    ok = subprocess.run(["zenity", "--question", "--no-markup", "--width", "500", "--title", "Supersede drawings?",
                         "--text", f"These older revisions will be moved to Superseded/:\n\n{listing}\n\nGo ahead?"])
    return ok.returncode == 0


def run_also(plan, chosen, src: Path, keystage_names=None, desc="", confirm=zenity_confirm_supersede,
             routes=None):
    """Copy into the chosen folders. Never overwrites, only creates ticked folders.
    keystage_names: {base rel: typed folder name}; missing ones are asked for.
    routes: per-file choices instead of per-folder ones, as
            [(folder rel, typed name for Surveys/Key-stage or None, {filenames})]:
            each file goes only where it was sent.
    Returns a summary (str) or None if nothing was chosen/cancelled."""
    job, job_root = plan["job"], plan["job_root"]
    filenames = sorted(p.name for p in src.iterdir() if p.is_file())
    dest_files = {d: set(f) & set(filenames) for d, f in plan["dest_files"].items()}
    mine = plan["mine"] & set(filenames)
    broken, keystage = plan["broken"], plan["keystage"]
    if routes is not None:                             # each file to its own folders
        dest_files, chosen = {}, []
        for rel, name, files in routes:
            files = set(files) & set(filenames)
            if not files:
                continue                               # (an empty set would mean 'every file')
            final = rel
            if rel in keystage and rel not in broken:
                if not is_keystage(keystage[rel]) and (not name or name.strip() == src.name):
                    final = same_name_rel(job_root, rel, src.name)     # Surveys: same name as IN/OUT folder
                else:
                    _, existing = subfolder_default(job_root, rel, keystage[rel], job)
                    final = subfolder_rel(rel, name or "", existing, job)
                if not final:
                    continue
            dest_files.setdefault(final, set()).update(files)
            if final not in chosen:
                chosen.append(final)
        keystage = {}                                  # names are already in the paths
    named = []
    for rel in chosen:
        if rel in keystage and rel not in broken:
            if keystage_names is not None and rel in keystage_names:
                _, existing = subfolder_default(job_root, rel, keystage[rel], job)
                ks = subfolder_rel(rel, keystage_names[rel], existing, job)
            elif not is_keystage(keystage[rel]):
                ks = same_name_rel(job_root, rel, src.name)            # Surveys: same name as IN/OUT folder
            else:
                ks = ask_subfolder_name(job_root, rel, keystage[rel], job,
                                        desc() if callable(desc) else desc)
            if ks:
                named.append(ks)                       # every file goes in (no 'only' set)
        else:
            named.append(rel)
    chosen = named
    chosen_ok = [r for r in chosen if r not in broken]
    skipped_broken = [r for r in chosen if r in broken]

    # Current Drawings folders: plan superseding first, confirm once
    plans = {}
    for rel in chosen_ok:
        dest = job_root / rel
        if is_current_drawings(dest) and dest.is_dir():
            names = (dest_files.get(rel) or set(filenames)) & mine
            plans[rel] = supersede_plan(src, dest, names)
    to_move = [f for sup, _, _ in plans.values() for f in sup]
    if to_move and not confirm(to_move):
        return "Nothing copied: superseding was cancelled."

    copied_total, skipped_all, history_notes = 0, [], []
    for rel in chosen_ok:
        dest = job_root / rel
        dest.mkdir(parents=True, exist_ok=True)            # only for ticked folders
        only = dest_files.get(rel)                         # rule matches: just their files
        if is_current_drawings(dest):                      # never a consultant's drawing
            not_mine = [f for f in (only or filenames) if f not in mine]
            only = set(mine) & set(only or filenames)
            skipped_all += [f"{rel}/{n}  (not one of your drawings)" for n in not_mine]
        sup, same, older = plans.get(rel, ([], {}, {}))
        for old in sup:
            move_to_superseded(old)
        if same or older:
            only = (only or set(filenames)) - set(same) - set(older)
            skipped_all += [f"{rel}/{n}  (same revision already current: {o})" for n, o in same.items()]
        if older:                                          # older revision: straight to history
            sup_dir = superseded_dir(dest)
            hist, dup = copy_files(src, sup_dir, set(older))
            copied_total += len(hist)
            history_notes.extend(f"{rel}/{sup_dir.name}/{n}  (newer {older[n]} is current)" for n in hist)
            skipped_all += [f"{rel}/{sup_dir.name}/{n}  (already there)" for n in dup]
        copied, skipped = copy_files(src, dest, only)
        copied_total += len(copied)
        skipped_all += [f"{rel}/{n}  (already there)" for n in skipped]
    if not chosen:
        return None
    text = f"Copied {copied_total} file(s) into {len(chosen_ok)} folder(s)."
    if to_move:
        text += f"\nMoved {len(to_move)} older revision(s) to Superseded/."
    if history_notes:
        text += "\n\nOlder than what's current, so filed straight into Superseded/:\n" + \
                "\n".join(history_notes[:10])
    if skipped_all:
        text += ("\n\nNOT copied, nothing overwritten:\n" +
                 "\n".join(skipped_all[:15]) + ("\n..." if len(skipped_all) > 15 else ""))
    if skipped_broken:
        text += "\n\nSkipped (path missing, check filing_rules.csv):\n" + "\n".join(skipped_broken)
    return text


def also_file_to(folder: Path, job: str, filenames, desc=""):
    """The zenity/GTK version: plan, tick-list, copy."""
    if not filenames:
        return                                     # empty folder: nothing to copy
    plan = plan_also(folder, folder, job, filenames, desc)
    if not plan["job_root"]:
        message("warning", plan["warning"])
        return
    if plan["warning"]:
        message("error", plan["warning"])
    chosen = checklist(f"Also file to? ({plan['job_root'].name})",
                       "Copy these files into other job folders too. Suggestions are ticked, at the top,\n"
                       "and only get the files shown after →. Folders you tick yourself get every file.\n"
                       "NEW FOLDER = doesn't exist yet; only created if you tick it.\n"
                       f"Existing files are never overwritten. {plan['note']}",
                       plan["options"], plan["ticked"], plan["labels"])
    text = run_also(plan, chosen, folder, desc=desc)
    if text:
        message("info", text)


# ----- planning or building regs? (for 'decision notice', 'approval' etc.) -----
AMBIGUOUS_OUTCOMES = re.compile(r"\b(decision notice|decision|approval|refusal|rejection|certificate|"
                                r"notice|consent|conditions?|application|permission)\b", re.I)
ALREADY_SAYS = re.compile(r"\b(planning|building|br|bc|regs?|fire|party wall|listed|lawful|prior)\b", re.I)
REGIME_SIGNALS = {
    "PLANNING": [r"town and country planning", r"planning permission", r"planning application",
                 r"local planning authority", r"\bhouseholder\b", r"listed building consent",
                 r"prior approval", r"lawful development", r"permitted development",
                 r"conservation area", r"planning officer", r"development management",
                 r"\bDM/\d", r"\b\d{2}/\d{4,6}/[A-Z]{2,5}\b", r"\bplanning\b"],
    "BUILDING REGS": [r"building regulations", r"building act 1984", r"building control",
                      r"full plans", r"initial notice", r"completion certificate", r"final certificate",
                      r"plan check", r"building control approver", r"approved inspector", r"\blabc\b",
                      r"building notice", r"regularisation", r"\bpart [a-s]\b"],
}


def pdf_text(data, chars=4000):
    """First page or two of a PDF as text (pypdf; empty if unreadable)."""
    try:
        import io
        import logging
        from pypdf import PdfReader
        logging.getLogger("pypdf").setLevel(logging.CRITICAL)
        r = PdfReader(io.BytesIO(data), strict=False)
        return " ".join((pg.extract_text() or "") for pg in r.pages[:2])[:chars]
    except Exception:
        return ""


def regime(pdf_texts=(), other_texts=()):
    """'PLANNING', 'BUILDING REGS' or None. Attached PDFs count most (their
    legal wording is decisive); email wording and filenames break ties."""
    score = {k: 0 for k in REGIME_SIGNALS}
    for weight, texts in ((3, pdf_texts), (1, other_texts)):
        for t in texts:
            for k, pats in REGIME_SIGNALS.items():
                score[k] += weight * sum(1 for p in pats if re.search(p, t or "", re.I))
    (best, a), (_, b) = sorted(score.items(), key=lambda x: -x[1])
    return best if a > 0 and a >= 2 * b else None          # clear winner only


BR_PLAN_CHECK = re.compile(r"\b(?:conditional |full plans |plans )?(?:decision notice|decision|approval|"
                           r"plan check)\b", re.I)
BR_FINAL_CERT = re.compile(r"\b(?:completion |final )?certificate\b|\bcompletion\b", re.I)
BR_OWN_TERMS = re.compile(r"\b(plan check|final certificate)\b", re.I)


def qualify(desc, kind):
    """Say which regime an outcome belongs to, in your terms:
       planning:       'DECISION NOTICE' -> 'PLANNING DECISION NOTICE'
       building regs:  decision/approval -> 'BUILDING REGULATIONS PLAN CHECK'
                       certificate       -> 'BUILDING REGULATIONS FINAL CERTIFICATE'
    Left alone when there's no clear evidence, or it already says which."""
    if not desc:
        return desc
    if re.search(r"\bbuilding\b|\bregs?\b|\bregulations\b|\bplanning\b", desc, re.I):
        return desc                                     # already says which
    if kind is None and BR_OWN_TERMS.search(desc):
        kind = "BUILDING REGS"                          # 'plan check' / 'final certificate' imply it
    if not kind:
        return desc
    if kind == "BUILDING REGS":
        if BR_FINAL_CERT.search(desc):
            return BR_FINAL_CERT.sub("FINAL CERTIFICATE", desc, count=1).replace(
                "FINAL CERTIFICATE", "BUILDING REGULATIONS FINAL CERTIFICATE", 1)
        if BR_PLAN_CHECK.search(desc):
            return BR_PLAN_CHECK.sub("BUILDING REGULATIONS PLAN CHECK", desc, count=1)
        if AMBIGUOUS_OUTCOMES.search(desc):
            return f"BUILDING REGULATIONS {desc}"
        return desc
    if not AMBIGUOUS_OUTCOMES.search(desc) or ALREADY_SAYS.search(desc):
        return desc
    return f"{kind} {desc}"


def folder_regime(folder: Path, filenames):
    """Regime from the PDFs and filenames in a folder (for File IN / OUT)."""
    texts = []
    for f in filenames[:10]:
        p = folder / f
        if p.suffix.lower() == ".pdf" and p.is_file() and p.stat().st_size < 30 * 1048576:
            texts.append(pdf_text(p.read_bytes()))
    return regime(texts, [name_text(f) for f in filenames])


# ---------- .eml files: extract attachments into a dated IN/OUT folder ----------
MY_EMAIL_ADDRESSES = ["jw@jakewhitearchitecture.com",          # From one of these = OUT
                      "jakepwhite@protonmail.com"]
MIN_ATTACHMENT_SIZE = 3 * 1024        # images smaller than this are branding/logos: omitted
MIN_EMBEDDED_IMAGE_SIZE = 20 * 1024   # body images bigger than this = sketches/screenshots -> PDF
SIGN_OFFS = ["kind regards", "yours sincerely", "yours faithfully", "best wishes", "best regards",
             "warm regards", "with thanks", "many thanks", "cheers", "regards", "thanks"]
GENERIC_DOMAINS = {"gmail", "googlemail", "yahoo", "hotmail", "outlook", "icloud", "aol", "mail",
                   "live", "btinternet", "sky", "protonmail", "proton", "me"}
GENERIC_MAILBOXES = {"planning", "info", "admin", "enquiries", "enquiry", "office", "noreply", "no-reply",
                     "do not reply", "building control", "buildingcontrol", "accounts", "reception",
                     "mail", "team", "support", "contact", "hello", "development management",
                     "planning department", "customer services", "the team"}
REPLY_MARKERS = re.compile(r"^(on .+ wrote:|-{2,}\s*original message|from:\s|sent:\s|_{5,})", re.I)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".heic", ".tif", ".tiff"}


def html_to_text(html):
    from html.parser import HTMLParser

    class T(HTMLParser):
        def __init__(self):
            super().__init__()
            self.out, self.skip = [], 0

        def handle_starttag(self, tag, attrs):
            if tag in ("style", "script", "head"):
                self.skip += 1
            if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
                self.out.append("\n")

        def handle_endtag(self, tag):
            if tag in ("style", "script", "head"):
                self.skip = max(0, self.skip - 1)

        def handle_data(self, d):
            if not self.skip:
                self.out.append(d)
    t = T()
    t.feed(html)
    return re.sub(r"\n\s*\n+", "\n\n", "".join(t.out)).strip()


def parse_email(path: Path):
    """Headers, plain/HTML body, real attachments, and images embedded in the
    body (Content-ID) kept separate, as in FileUzi's parse_eml_file."""
    import email
    from email import policy
    from email.utils import parsedate_to_datetime
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    try:
        when = parsedate_to_datetime(msg.get("Date", ""))
    except Exception:
        when = None
    text = html = None
    attachments, embedded = [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype, disp = part.get_content_type(), part.get_content_disposition()
        cid = (part.get("Content-ID") or "").strip().strip("<>")
        name = part.get_filename()
        data = part.get_payload(decode=True) or b""
        if ctype.startswith("image/") and cid and disp != "attachment":
            embedded.append({"cid": cid, "data": data, "ctype": ctype, "size": len(data)})
        elif disp == "attachment" or (name and disp == "inline"):
            if data:
                attachments.append({"name": name or "attachment", "data": data,
                                    "size": len(data), "ctype": ctype})
        elif ctype == "text/plain" and text is None:
            text = data.decode(part.get_content_charset() or "utf-8", errors="replace")
        elif ctype == "text/html" and html is None:
            html = data.decode(part.get_content_charset() or "utf-8", errors="replace")
    body = text if text and text.strip() else (html_to_text(html) if html else "")
    html_clean = body_above_signoff(html_to_text(html)) if html else ""
    return {"html_clean": html_clean, "from": str(msg.get("From", "")), "to": str(msg.get("To", "")),
            "cc": str(msg.get("Cc", "")), "subject": str(msg.get("Subject", "")) or "(no subject)",
            "date": when, "html": html, "body": body, "body_clean": body_above_signoff(body),
            "attachments": attachments, "embedded": embedded}


def is_signoff_line(line):
    """'Kind regards', 'Thanks,', 'Many thanks, Bob' = sign-off.
    'Thanks Jake, please see attached the plans' = NOT (it's the message)."""
    low = line.strip().lower().rstrip(",.!")
    return bool(low) and len(low) <= 30 and any(
        low == s or low.startswith(s + ",") or low.startswith(s + " ") and len(low.split()) <= len(s.split()) + 2
        for s in SIGN_OFFS)


def body_above_signoff(body):
    """This email's own words: stop at the first sign-off or quoted reply."""
    lines = []
    for line in body.splitlines():
        if is_signoff_line(line) or REPLY_MARKERS.match(line.strip()):
            break
        if line.strip().startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


ATTACH_PATTERNS = [
    r"please find (?:attached|enclosed|below|above)(?: herewith)?\s*(?P<x>[^.\n;!?]*)",
    r"attached (?:please find|you(?: will|'ll) find)\s+(?P<x>[^.\n;!?]*)",
    r"(?:attached|enclosed) (?:herewith )?(?:is|are)\s+(?P<x>[^.\n;!?]*)",
    r"(?:please )?(?:see|find) (?:the )?(?:attached|enclosed|below|above)\s*(?P<x>[^.\n;!?]*)",
    r"\b(?:i|we)(?: have|'ve)? (?:attach(?:ed)?|enclose(?:d)?|include(?:d)?)\s+(?P<x>[^.\n;!?]*)",
    r"\b(?:just )?send(?:ing)? (?:you )?(?:over|across|through)\s+(?P<x>[^.\n;!?]*)",
    r"(?:please )?(?:see|find) (?:the )?(?P<x>(?:screenshot|sketch|markup|mark-up|drawing|photo|image|attachment)s?[^.\n;!?]*)",
    r"(?:^|[.!?]\s+|\n)(?:the |our |my )?(?P<x>[a-z][^.\n;!?]{2,60}?) (?:is|are) attached",
    # 'please see a revised plan attached', 'find the updated drawings enclosed'
    r"(?:please )?(?:see|find) (?:a |an |the |our |my )?(?P<x>[^.\n;!?]{2,60}?) (?:attached|enclosed)\b"
    r"(?P<y>\s+for [^.\n;!?]*)?",
    r"\bhere(?:'s| is| are)\s+(?P<x>[^.\n;!?]*)",          # weakest: only if nothing else matches
]
WEAK_ATTACH = 1                      # the last pattern(s): tried only after every sentence fails the rest
GREETING = re.compile(r"^(?:(?:hi|hello|hey|dear|morning|afternoon|evening|good (?:morning|afternoon|evening))\b[^\n]*"
                      r"|[A-Z][a-z]+(?: [A-Z][a-z]+)?\s*[,!]?)$")
PLEASANTRIES = re.compile(r"^(?:(?:i )?hope (?:you(?:'re| are)|all is|this finds)[^.,!]*[.,!]?\s*|thanks? (?:you )?for [^.,!]*[.,!]\s*|"
                    r"just a quick (?:note|email|one)[^,.]*[,.]?\s*|following (?:on from )?(?:our|my|your|the) [^,]+,\s*|"
                    r"further to [^,]+,\s*|as (?:discussed|per|requested|promised)[^,]*,\s*|"
                    r"(?:i'm|i am|we're|we are) (?:just )?(?:writing|emailing|getting in touch)[^,.]*[,.]?\s*|"
                    r"(?:ok|okay|great|perfect|lovely|brilliant|cheers)[,!.]\s*)+", re.I)


ACKNOWLEDGEMENT = re.compile(r"^(?:all |that's |that is |this is )?(?:received|noted|ok|okay|thanks|thank you|"
                             r"cheers|will do|sounds good|great|perfect|lovely|brilliant|no problem|no worries|"
                             r"yes|no|got it|understood|agreed|fine|done|confirmed|speak soon)\b[\w\s,!.']{0,25}$",
                             re.I)


def topic_sentence(body_clean):
    """No 'attached' wording? Use the first real sentence, minus greeting
    and pleasantries, trimmed to a folder-sized description."""
    lines = [l for l in body_clean.splitlines() if l.strip() and not GREETING.match(l.strip())]
    text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        sentence = PLEASANTRIES.sub("", sentence.strip()).strip(" .!?")
        if ACKNOWLEDGEMENT.match(sentence):           # 'All received', 'Noted, thanks' say nothing
            continue
        if len(sentence.split()) >= 3:
            sentence = re.sub(r"\b(?:the|a|an)\s+", "", PHRASE_CUT.split(sentence)[0], flags=re.I)
            words = sentence.split()
            if len(words) >= 2:
                return clean(" ".join(words[:8]))
    return None


PHRASE_CUT = re.compile(r"\b(?:for your|for comment|for review|for approval|for info|for reference|"
                        r"as discussed|as requested|as promised|as agreed|which|that|following|ahead of|"
                        r"in advance|so that|so you|if you|please|thanks|let me|to this email|with this email|"
                        r"herewith|for you)\b|,", re.I)


def attached_phrase(body_clean):
    """'Please find attached the revised plans and elevations for your comment'
    -> 'REVISED PLANS AND ELEVATIONS'.  None if there's nothing useful."""
    return attached_match(body_clean)[0]


def attached_match(body_clean):
    """(description, the sentence it came from). Sentences are tried in order,
    so the email's FIRST 'attached / enclosed / see below' sentence wins; the
    weak 'here is / here are' wording only counts if nothing else does."""
    if not body_clean:
        return None, None
    lines = [l for l in body_clean.splitlines() if l.strip() and not GREETING.match(l.strip())]
    text = re.sub(r"\s+", " ", " ".join(lines))
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]
    strong, weak = ATTACH_PATTERNS[:-WEAK_ATTACH], ATTACH_PATTERNS[-WEAK_ATTACH:]
    for patterns in (strong, weak):
        for sentence in sentences:
            for pat in patterns:
                m = re.search(pat, sentence, re.I)
                if m:
                    tail = m.groupdict().get("y") or ""        # '...attached for obtaining quotes'
                    x = tidy_phrase(m.group("x") + tail)
                    if x:
                        return x, sentence
    return None, None


QUOTES_WORDING = re.compile(r"\b(?:for|to get|to obtain)\s+(?:obtaining\s+|getting\s+|seeking\s+)?"
                            r"(?:builders?'?\s+|contractors?'?\s+)?(?:quotes?|quotations?|pricing|prices|tenders?)\b",
                            re.I)
SINGLE_SHEETS = r"(?<!SITE )(?<!LOCATION )(?<!BLOCK )"        # 'SITE PLAN' is one drawing: leave it
PLURALS = [(rf"{SINGLE_SHEETS}\bPLAN\b", "PLANS"), (r"\bELEVATION\b", "ELEVATIONS"), (r"\bSECTION\b", "SECTIONS"),
           (r"\bDRAWING\b", "DRAWINGS"), (r"\bDETAIL\b", "DETAILS")]
REVISION_WORDS = re.compile(r"^(?:REVISED|AMENDED|LATEST|NEW|UPDATED)\s+", re.I)


# What the documents are, never what state they're in: '... IS READY', '... HAS BEEN UPLOADED'
STATUS_TAIL = re.compile(
    r"\s+(?:IS|ARE|HAS|HAVE|WAS|WERE|NOW)\b(?:\s+(?:NOW|BEEN|ALL|BOTH|JUST|FINALLY|NOW))*\s+"
    r"(?:READY|ATTACHED|ENCLOSED|AVAILABLE|COMPLETE|COMPLETED|DONE|FINISHED|UPLOADED|SENT|"
    r"SHARED|HERE|BELOW|ABOVE|THROUGH|IN|APPROVED|ISSUED)\b.*$")


def house_style(desc, sent_before=False, trim_status=True):
    """The way you'd write it yourself: 'REVISED PLAN FOR OBTAINING QUOTES'
    (sent before) -> 'UPDATED PLANS FOR BUILDER QUOTES'."""
    if not desc:
        return desc
    d = QUOTES_WORDING.sub("FOR BUILDER QUOTES", desc)
    d = d.upper()
    if trim_status:                                    # (the rules only: the model is told in its prompt)
        d = STATUS_TAIL.sub("", d).strip() or d
    for pat, word in PLURALS:
        d = re.sub(pat, word, d)
    if sent_before:
        d = "UPDATED " + REVISION_WORDS.sub("", d)
    return clean(d)


def tidy_phrase(raw):
    """The part after 'please find attached' -> a folder-sized description, or None."""
    if True:
        x = PHRASE_CUT.split(raw)[0]
        x = re.sub(r"^(?:is |are |to |:\s*)", "", x.strip(), flags=re.I)
        x = re.sub(r"^(?:a copy of|copies of|copy of|the|our|my|an|a|some|your)\s+", "", x, flags=re.I)
        x = re.sub(r"^(?:the|our|my)\s+", "", x, flags=re.I).strip(" :-")
        x = re.sub(r"\b(and|&|of)\s+(?:the|our|my|a|an)\s+", r"\1 ", x, flags=re.I)
        x = re.sub(r"\s+(?:below|above|attached|enclosed|herewith)\b", "", x, flags=re.I).strip()
        m_for = re.search(r"\s+for (?:the|this)\s+", x, re.I)
        if m_for and len(x[:m_for.start()].split()) >= 3:   # long enough without 'for the ...'
            x = x[:m_for.start()]
        x = re.sub(r"\bfor (?:the )?purposes? of\s+", "for ", x, flags=re.I)   # 'for the purposes of quotes'
        x = re.sub(r"\bfor (?:the|this)\s+", "for ", x, flags=re.I)
        if len(x.split()) > 10:          # 'plans and elevations with the larger glazing we discussed'
            x = re.split(r"\s+(?:with|showing|including|incorporating|we|which|from|following|"
                         r"based on|to show|now)\b", x, maxsplit=1, flags=re.I)[0].strip()
        if x and 1 <= len(x.split()) <= 10 and x.lower() not in ("below", "above", "attached"):
            return clean(x)
    return None


def display_name(addr_field):
    """'Bob Smith <bob@smithengineers.co.uk>' -> 'Bob Smith'; no name -> business from domain."""
    from email.utils import getaddresses
    pairs = getaddresses([addr_field])
    if not pairs:
        return ""
    name, addr = pairs[0]
    name = name.strip().strip('"')
    if "," in name:                                    # 'Smith, Bob' -> 'Bob Smith'
        last, _, first = name.partition(",")
        name = f"{first.strip()} {last.strip()}".strip()
    if name and "@" not in name and name.lower() not in GENERIC_MAILBOXES:
        return name
    domain = addr.split("@")[-1].lower() if "@" in addr else ""
    business = re.sub(r"\.(co\.uk|org\.uk|gov\.uk|ac\.uk|com|org|net|io|co|uk)$", "", domain).split(".")[-1]
    return business if business and business not in GENERIC_DOMAINS else addr.split("@")[0]


def person(addr_field):
    """'you' for your own address, otherwise the display name."""
    from email.utils import parseaddr
    if parseaddr(addr_field)[1].lower() in [a.lower() for a in MY_EMAIL_ADDRESSES]:
        return "you"
    return display_name(addr_field)


def email_direction(parsed):
    from email.utils import parseaddr
    _, frm = parseaddr(parsed["from"])
    return "OUT" if frm.lower() in [a.lower() for a in MY_EMAIL_ADDRESSES] else "IN"


SIGNOFF_HTML = re.compile(r">\s*(?:kind regards|best regards|warm regards|regards|many thanks|thanks|cheers|"
                          r"yours sincerely|yours faithfully|best wishes|with thanks)\b[\s,.!]*<", re.I)
QUOTE_HTML = re.compile(r"(?:on [^<]{5,120} wrote:|-{2,}\s*original message|<div[^>]+(?:divRplyFwdMsg|gmail_quote|"
                        r"moz-cite-prefix|yahoo_quoted)|<blockquote|border-top:\s*solid|>\s*from:\s*<)", re.I)


def image_fingerprint(data):
    import hashlib
    return hashlib.sha1(data).hexdigest()


def branding_reason(data, size, seen, position=None, cutoff=None):
    """Why an image is branding (signature/logo/icon), or None if it looks
    like real content (a sketch or screenshot)."""
    if size < MIN_ATTACHMENT_SIZE:
        return f"small image, {size / 1024:.1f} KB"
    if image_fingerprint(data) in seen:
        return "seen in earlier emails (logo/signature)"
    if position is not None and cutoff is not None and position > cutoff:
        return "in the signature / quoted email"
    return None


def seen_images():
    return set(load_history().get("image_fingerprints", []))


def remember_images(datas):
    """Fingerprints of every image met, so a logo is recognised next time."""
    data = load_history()
    known = set(data.get("image_fingerprints", []))
    known |= {image_fingerprint(d) for d in datas}
    data["image_fingerprints"] = sorted(known)[-5000:]
    try:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps(data, indent=1))
    except Exception:
        pass


def known_verdicts():
    return load_history().get("image_verdicts", {})


def remember_verdicts(new):
    """{fingerprint: {...}} plus a name|size index, so copies are recognised
    without asking Mirage again."""
    if not new:
        return
    data = load_history()
    verdicts = data.setdefault("image_verdicts", {})
    names = data.setdefault("image_names", {})
    for fp, v in new.items():
        verdicts[fp] = {k: v[k] for k in ("v", "label", "conf")}
        if v.get("key"):
            names[v["key"]] = fp
    if len(verdicts) > 5000:                          # keep the file small
        for fp in list(verdicts)[:len(verdicts) - 5000]:
            verdicts.pop(fp, None)
    try:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps(data, indent=1))
    except Exception:
        pass


CONTENT_LABELS = {}       # fingerprint -> what Mirage saw ('hand sketch', 'site photo', ...)


def looks_like_photo(data, size):
    """A camera/phone photo: a JPEG carrying EXIF camera data and not tiny, or just big.
    Logos and signature graphics are small and don't come from a camera."""
    head = data[:65536]
    is_jpeg = head[:3] == b"\xff\xd8\xff"
    camera = b"Exif\x00\x00" in head and any(m in head for m in (
        b"Apple", b"samsung", b"SAMSUNG", b"Google", b"HUAWEI", b"OnePlus", b"Xiaomi", b"motorola",
        b"Canon", b"NIKON", b"SONY", b"FUJIFILM", b"OLYMPUS", b"Panasonic", b"DJI"))
    return (is_jpeg and camera and size >= 100_000) or size >= 800_000


def judge_image(data, name, size, known, names, seen, new, embedded):
    """Branding reason for one image, or None for content. Uses (in order):
    remembered verdict (fingerprint, then name+size) -> Mirage once -> simple rules."""
    fp = image_fingerprint(data)
    key = f"{name}|{size}"
    v = known.get(fp) or (known.get(names.get(key, "")) if key in names else None)
    if v:
        if v["v"] == "branding":
            return f"recognised {v.get('label') or 'logo'} (seen before)"
        CONTENT_LABELS[fp] = v.get("label")
        return None
    if looks_like_photo(data, size):                  # a camera photo is never a logo: no need for Mirage
        new[fp] = {"v": "content", "label": "site photo", "conf": None, "key": key}
        CONTENT_LABELS[fp] = "site photo"
        return None
    vision = get_vision()
    if vision:
        r = vision.ask(data)
        label, conf = r.get("choice"), r.get("conf")
        if label:
            is_brand, score = vision_verdict(label, conf, r.get("table"))
            new[fp] = {"v": "branding" if is_brand else "content", "label": label, "conf": score, "key": key}
            CONTENT_LABELS[fp] = None if is_brand else label
            if is_brand:
                return f"Mirage: {label}" + (f" ({score:.0%} branding)" if score is not None else "")
            return None
    if fp in seen:                                    # no Mirage: simple rules
        return "seen in earlier emails (logo/signature)"
    if embedded and size < MIN_EMBEDDED_IMAGE_SIZE:
        return f"small body image, {size / 1024:.0f} KB"
    return None


def classify_email_images(parsed):
    """Mark every embedded image and image attachment with a branding reason
    (or None = content). Signature/quoted position and tiny size are decided
    without any model; everything else goes through judge_image."""
    seen, known = seen_images(), known_verdicts()
    names = load_history().get("image_names", {})
    new = {}
    html = parsed["html"] or ""
    cutoffs = [m.start() for m in (SIGNOFF_HTML.search(html), QUOTE_HTML.search(html)) if m]
    cutoff = min(cutoffs) if cutoffs else None
    for img in parsed["embedded"]:
        m = re.search(rf"cid:{re.escape(img['cid'])}", html, re.I)
        if not m:
            img["why"] = "not shown in the email body"
        elif img["size"] < MIN_ATTACHMENT_SIZE:
            img["why"] = f"small image, {img['size'] / 1024:.1f} KB"
        elif cutoff is not None and m.start() > cutoff:
            img["why"] = "in the signature / quoted email"
            new[image_fingerprint(img["data"])] = {"v": "branding", "label": "signature image",
                                                   "conf": None, "key": f"{img['cid']}|{img['size']}"}
        else:
            img["why"] = judge_image(img["data"], img["cid"].split("@")[0], img["size"],
                                     known, names, seen, new, embedded=True)
    signature = {image_fingerprint(i["data"]) for i in parsed["embedded"] if i["why"]}
    for a in parsed["attachments"]:
        is_image = a["ctype"].startswith("image/") or Path(a["name"]).suffix.lower() in IMAGE_EXTS
        if not is_image:
            a["why"] = None
        elif a["size"] < MIN_ATTACHMENT_SIZE:
            a["why"] = f"small image, {a['size'] / 1024:.1f} KB"
        elif image_fingerprint(a["data"]) in signature:
            a["why"] = "same image as the email's signature/logo"
        else:
            a["why"] = judge_image(a["data"], a["name"], a["size"], known, names, seen, new, embedded=False)
    remember_verdicts(new)


def is_branding(att):
    return bool(att.get("why"))


def email_pdf(parsed, job):
    """PDF of the whole email with its embedded images (FileUzi's generate_email_pdf).
    Remote images/links are never fetched (no tracking pixels, no network).
    Returns (pdf bytes, filename) or (None, reason)."""
    import base64
    import html as h
    when = parsed["date"] or datetime.now()
    subject = parsed["subject"]
    cleaned = re.sub(rf"^{re.escape(job)}\s*[-:]?\s*", "", subject).strip()
    cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned).strip() or "untitled"
    filename = f"{job}_email_{when:%Y-%m-%d}_{cleaned}.pdf"
    body = parsed["html"]
    if body:
        for img in parsed["embedded"]:
            uri = f"data:{img['ctype']};base64,{base64.b64encode(img['data']).decode()}"
            body = re.sub(rf"cid:{re.escape(img['cid'])}", uri, body, flags=re.I)
        m = re.search(r"<body[^>]*>(.*?)</body>", body, re.S | re.I)
        body = m.group(1) if m else body
    else:
        body = h.escape(parsed["body"]).replace("\n", "<br>")
        for img in parsed["embedded"]:
            uri = f"data:{img['ctype']};base64,{base64.b64encode(img['data']).decode()}"
            body += f'<p><img src="{uri}"></p>'
    cc = f"<div><b>CC:</b> {h.escape(parsed['cc'])}</div>" if parsed["cc"] else ""
    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body {{ font-family: Arial, sans-serif; font-size: 11pt; line-height: 1.4; margin: 15px 20px; }}
.hdr {{ background: #f5f5f5; padding: 15px; margin-bottom: 20px; border-radius: 4px; }}
.subj {{ font-size: 14pt; font-weight: bold; margin-top: 10px; }}
img {{ max-width: 100%; height: auto; }}</style></head><body>
<div class="hdr"><div><b>From:</b> {h.escape(parsed['from'])}</div><div><b>To:</b> {h.escape(parsed['to'])}</div>
{cc}<div><b>Date:</b> {when:%Y-%m-%d %H:%M}</div><div class="subj">{h.escape(subject)}</div></div>
<div>{body}</div></body></html>"""
    if SANDBOX_MODEL:
        pdf = pdf_in_sandbox(page)                     # the worker stays loaded between emails
        if pdf:
            return pdf, filename
        cmd, kind = sandbox_cmd("--pdf-worker")
        if cmd and kind == "bubblewrap":               # one-off try, for its error message
            r = subprocess.run(cmd, input=page.encode("utf-8"), capture_output=True, timeout=120)
            if r.returncode == 0 and r.stdout.startswith(b"%PDF"):
                return r.stdout, filename
            err = r.stderr.decode(errors="replace").strip().splitlines()
            return None, (err[-1] if err else "PDF failed in the sandbox")
        warn_sandbox("The email PDF is being made outside bubblewrap "
                     "(internet still blocked, but no file isolation).")
    try:
        return render_pdf(page), filename
    except ImportError:
        return None, "no PDF renderer (install: sudo dnf install python3-weasyprint)"
    except Exception as e:
        return None, f"PDF failed: {e}"


def strip_remote(html):
    """Remove everything that would load from the internet (remote images,
    tracking pixels, stylesheets, fonts, scripts). Embedded data: images stay."""
    html = re.sub(r"<(script|link|iframe|object|embed|meta)\b[^>]*>(?:.*?</\1>)?", "", html,
                  flags=re.I | re.S)
    html = re.sub(r"(\b(?:src|href|background|poster)\s*=\s*)([\"'])(?!data:|#)[^\"']*\2",
                  r'\1""', html, flags=re.I)
    html = re.sub(r"url\(\s*([\"']?)(?!data:)[^)]*\)", "none", html, flags=re.I)
    html = re.sub(r"@import[^;]+;", "", html, flags=re.I)
    return html


def render_pdf(page):
    """HTML -> PDF with WeasyPrint, after stripping anything remote."""
    import logging
    from weasyprint import HTML
    logging.getLogger("weasyprint").setLevel(logging.CRITICAL)
    return HTML(string=strip_remote(page)).write_pdf()


def shrink_inline_images(page, longest=1600, min_bytes=300_000):
    """Inside the PDF sandbox: big pictures in the email (data: URIs) scaled down
    to print size before WeasyPrint lays them out. Small ones are left alone."""
    import base64, io
    try:
        from PIL import Image
    except ImportError:
        return page

    def shrink(m):
        ctype, b64 = m.group(1), m.group(2)
        if len(b64) * 3 // 4 < min_bytes:
            return m.group(0)
        try:
            im = Image.open(io.BytesIO(base64.b64decode(b64)))
            im.thumbnail((longest, longest))
            out = io.BytesIO()
            if im.mode in ("RGBA", "LA", "P") and ctype.endswith("png"):
                im.save(out, "PNG", optimize=False)
                ctype = "image/png"
            else:
                im.convert("RGB").save(out, "JPEG", quality=82)
                ctype = "image/jpeg"
            return f"data:{ctype};base64,{base64.b64encode(out.getvalue()).decode()}"
        except Exception:
            return m.group(0)
    return re.sub(r"data:(image/[a-zA-Z+.-]+);base64,([A-Za-z0-9+/=\s]+)", shrink, page)


def pdf_server():
    """Child process inside bubblewrap that stays running: WeasyPrint is loaded
    once (slow on a small CPU), then each email's HTML -> PDF. Frames are an
    8-byte length followed by the bytes; a zero-length reply means failure."""
    block_network()
    import struct
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    try:
        import logging
        from weasyprint import HTML                    # (the slow part, done once)
        logging.getLogger("weasyprint").setLevel(logging.CRITICAL)
        ok = b"ready"
    except ImportError:
        ok = b""
    out.write(struct.pack(">Q", len(ok)) + ok)
    out.flush()
    if not ok:
        return
    while True:
        head = inp.read(8)
        if len(head) < 8:
            return
        page = inp.read(struct.unpack(">Q", head)[0]).decode("utf-8", errors="replace")
        try:
            page = shrink_inline_images(page)          # full-size photos make WeasyPrint crawl
            pdf = HTML(string=strip_remote(page)).write_pdf()
        except Exception:
            pdf = b""
        out.write(struct.pack(">Q", len(pdf)) + pdf)
        out.flush()


_pdf_proc = None


def pdf_in_sandbox(page):
    """HTML -> PDF bytes via the long-running sandboxed PDF worker (None on failure)."""
    import struct
    global _pdf_proc
    with PDF_LOCK:
        if _pdf_proc is None or _pdf_proc.poll() is not None:
            cmd, kind = sandbox_cmd("--pdf-server")
            if not cmd or kind != "bubblewrap":
                return None
            _pdf_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL)
            n = struct.unpack(">Q", _pdf_proc.stdout.read(8) or b"\0" * 8)[0]
            if not n or _pdf_proc.stdout.read(n) != b"ready":
                _pdf_proc.kill()
                _pdf_proc = None
                return None
        data = page.encode("utf-8")
        try:
            _pdf_proc.stdin.write(struct.pack(">Q", len(data)) + data)
            _pdf_proc.stdin.flush()
            n = struct.unpack(">Q", _pdf_proc.stdout.read(8))[0]
            pdf = _pdf_proc.stdout.read(n) if n else b""
        except (OSError, struct.error):
            _pdf_proc = None
            return None
        return pdf if pdf.startswith(b"%PDF") else None


def pdf_worker():
    """Child process inside bubblewrap: HTML in on stdin, PDF out on stdout."""
    block_network()
    page = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        sys.stdout.buffer.write(render_pdf(page))
    except ImportError:
        sys.exit("no PDF renderer (install: sudo dnf install python3-weasyprint)")
    except Exception as e:
        sys.exit(f"PDF failed: {e}")


def write_new(dest: Path, name, data):
    """Write a file without ever overwriting: name_2.ext if taken. Returns path."""
    name = re.sub(r'[\\/:*?"<>|]', "-", name).strip() or "attachment"
    stem, suffix = Path(name).stem, Path(name).suffix
    target, n = dest / name, 2
    while True:
        try:
            with open(target, "xb") as f:
                f.write(data)
            return target
        except FileExistsError:
            target = dest / f"{stem}_{n}{suffix}"
            n += 1


def trash(path: Path):
    """To the bin (recoverable), never a hard delete."""
    try:
        return subprocess.run(["gio", "trash", str(path)], capture_output=True).returncode == 0
    except Exception:
        return False


def email_sent_time(eml: Path):
    """Sent time from the headers only (fast), for sorting a batch oldest first."""
    from email.parser import BytesHeaderParser
    from email.utils import parsedate_to_datetime
    try:
        with open(eml, "rb") as f:
            d = parsedate_to_datetime(BytesHeaderParser().parse(f).get("Date", ""))
        return d.timestamp()
    except Exception:
        return eml.stat().st_mtime


PDF_ROW = "PDF of the email itself"
QUOTE_CUE = re.compile(r"\b(attach\w*|enclos\w*|below|above|screenshot\w*|sketch\w*|"
                       r"mark-?ups?|here(?:'s| is| are)|send(?:ing)? (?:over|across|through))\b", re.I)


def email_quote(parsed, limit=900):
    """This email's own words (above the sign-off), and the sentence the
    description most likely came from (to highlight)."""
    text = parsed["body_clean"] or parsed["html_clean"] or ""
    lines = [l.rstrip() for l in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + " …"
    flat = re.sub(r"\s+", " ", " ".join(l for l in text.splitlines() if not GREETING.match(l.strip())))
    key = next((s for s in re.split(r"(?<=[.!?])\s+", flat) if QUOTE_CUE.search(s)), None)
    return text, key


# ---------- share links (WeTransfer, Dropbox, ...) ----------
SHARE_SERVICES = [                                  # (name, host pattern)
    ("WeTransfer", r"(?:^|\.)(?:wetransfer\.com|we\.tl)$"),
    ("Proton Drive", r"^drive\.proton\.me$"),
    ("Dropbox", r"(?:^|\.)(?:dropbox\.com|db\.tt)$"),
    ("Google Drive", r"^(?:drive|docs)\.google\.com$"),
    ("OneDrive", r"(?:^|\.)(?:onedrive\.live\.com|1drv\.ms)$"),
    ("SharePoint", r"\.sharepoint\.com$"),
    ("Box", r"(?:^|\.)box\.com$"),
    ("iCloud", r"^(?:www\.)?icloud\.com$"),
    ("Smash", r"(?:^|\.)fromsmash\.com$"),
    ("TransferNow", r"(?:^|\.)transfernow\.net$"),
    ("Filemail", r"(?:^|\.)filemail\.com$"),
    ("MEGA", r"^(?:www\.)?mega\.(?:nz|io)$"),
    ("Hightail", r"(?:^|\.)hightail\.com$"),
    ("SwissTransfer", r"(?:^|\.)swisstransfer\.com$"),
]
URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]+", re.I)


def above_signature_html(html):
    """The HTML of this email's own message: cut at the sign-off or the quoted earlier email."""
    cuts = [m.start() for m in (SIGNOFF_HTML.search(html), QUOTE_HTML.search(html)) if m]
    return html[:min(cuts)] if cuts else html


def share_links(parsed):
    """[(service, url)] for file-sharing links in THIS email's own words (not in the
    signature, not in quoted earlier emails), leaving out links whose files you've
    already filed."""
    from urllib.parse import urlparse
    import html as _html
    done = load_history().get("share_links_done", {})
    found = {}
    for text in (parsed.get("body_clean") or "", _html.unescape(above_signature_html(parsed.get("html") or ""))):
        for url in URL_RE.findall(text):
            url = url.rstrip(".,;:!?")
            host = (urlparse(url).hostname or "").lower()
            if url in done:
                continue
            for name, pat in SHARE_SERVICES:
                if re.search(pat, host) and urlparse(url).path.strip("/"):
                    found.setdefault(url, name)
    return [(name, url) for url, name in found.items()]


def remember_share_links(plan, folder_name):
    """Files from these links are now filed: don't offer the links again (e.g. in replies)."""
    data = load_history()
    done = data.setdefault("share_links_done", {})
    for _, url in plan.get("share_links") or []:
        done[url] = {"filed": f"{date.today():%Y-%m-%d}", "folder": folder_name}
    if len(done) > 500:                                # keep the newest 500
        data["share_links_done"] = dict(sorted(done.items(), key=lambda kv: kv[1]["filed"])[-500:])
    try:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps(data, indent=1))
    except Exception:
        pass


def dropped_attachments(paths):
    """Files dropped onto the card (e.g. a WeTransfer download), as attachments.
    A .zip is opened and its files used instead (folders inside are flattened)."""
    import mimetypes, zipfile
    out = []
    def add(name, data):
        out.append({"name": name, "data": data, "size": len(data), "dropped": True,
                    "ctype": mimetypes.guess_type(name)[0] or "application/octet-stream"})
    for p in paths:
        p = Path(p)
        files = sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else [p]
        for f in files:
            if f.name.startswith("."):
                continue
            if f.suffix.lower() == ".zip":
                try:
                    with zipfile.ZipFile(f) as z:
                        for info in z.infolist():
                            name = Path(info.filename).name        # never a path from inside the zip
                            if info.is_dir() or not name or name.startswith(".") or "__MACOSX" in info.filename:
                                continue
                            if info.file_size > 2_000_000_000:
                                continue
                            add(name, z.read(info))
                    continue
                except zipfile.BadZipFile:
                    pass
            add(f.name, f.read_bytes())
    return out


def plan_email(eml: Path, status=lambda msg: None, extra=None):
    """Read one .eml and work out everything (nothing is written).
    Returns a dict; plan['skip'] is set when there's nothing to file."""
    status(f"Reading {eml.name}")
    parsed = parse_email(eml)
    direction = email_direction(parsed)
    job = find_job_number(eml) or ""
    atts = parsed["attachments"]
    if extra:                                          # files you downloaded from a share link
        atts += dropped_attachments(extra)
    seen = {}
    for a in atts:                                     # two 'image001.png' -> distinct rows
        n = a["name"]
        seen[n] = seen.get(n, 0) + 1
        a["row"] = n if seen[n] == 1 else f"{Path(n).stem} ({seen[n]}){Path(n).suffix}"
    status("Checking images (logos / branding / sketches)")
    classify_email_images(parsed)
    big_embedded = [i for i in parsed["embedded"] if not i["why"]]
    small_embedded = len(parsed["embedded"]) - len(big_embedded)
    when = parsed["date"] or datetime.now()
    if getattr(when, "tzinfo", None):                  # sender's time zone -> UK local time
        when = when.astimezone()
    when_d = when.date() if hasattr(when, "date") else when
    plan = {"eml": eml, "parsed": parsed, "direction": direction, "job": job, "when": when_d,
            "atts": atts, "big_embedded": big_embedded, "small_embedded": small_embedded,
            "skip": None, "also": None, "staging": None, "share_links": share_links(parsed),
            "extra": list(extra or [])}
    if not atts and not big_embedded:
        remember_images([i["data"] for i in parsed["embedded"]])
        plan["skip"] = (f"No attachments or sketches to file ({small_embedded} branding image(s) ignored). "
                        "The email has been left where it is.")
        return plan

    keep = [a for a in atts if not is_branding(a)]
    content_seen = sorted({CONTENT_LABELS.get(image_fingerprint(i["data"])) for i in big_embedded} - {None})
    plan["content_seen"] = content_seen
    who_guess = display_name(parsed["to"] if direction == "OUT" else parsed["from"])
    recent = recent_names(eml.parent / "_", job, direction) if job else []
    plan["who_options"] = list(dict.fromkeys(
        ([who_guess] if who_guess else []) + [r for r in recent if r != clean(who_guess)]))

    status("Describing the contents")
    from_attached, source_sentence = attached_match(parsed["body_clean"])
    if not from_attached:
        from_attached, source_sentence = attached_match(parsed["html_clean"])
    from_topic = topic_sentence(parsed["body_clean"]) or topic_sentence(parsed["html_clean"])
    from_body = from_attached or from_topic
    data = {a["name"]: a["data"] for a in keep}
    from_files = suggest_description([a["name"] for a in keep], eml.parent / "_new_", direction, when_d, data)
    sent_before = bool(from_files and from_files.startswith("UPDATED "))
    if from_body:                                        # your wording: UPDATED if sent before, PLANS, BUILDER QUOTES
        from_body = house_style(from_body, sent_before)
    subj = parsed["subject"]
    for _ in range(3):                                   # 'RE: FW: 2505 - ...' -> '...'
        subj = re.sub(rf"^\s*(?:(?:re|fw|fwd)\s*:|{re.escape(job)}\s*[-:]?)\s*" if job
                      else r"^\s*(?:re|fw|fwd)\s*:\s*", "", subj, flags=re.I)
    if job:
        subj = re.sub(rf"\s*[-:]?\s*\b{re.escape(job)}\b\s*[-:]?\s*", " ", subj, flags=re.I)
    subject_desc = clean(subj)
    kind = regime([pdf_text(a["data"]) for a in keep if a["name"].lower().endswith(".pdf")],
                  [parsed["subject"], parsed["body_clean"]] + [a["name"] for a in keep])
    seen_desc = " AND ".join(dict.fromkeys(VISION_DESC[l] for l in content_seen if l in VISION_DESC)) \
        if big_embedded else None                     # 'SKETCH AND SITE PHOTOS' from what Mirage saw
    # order: 'please find attached...' wording > what Mirage saw in the body >
    # first real sentence > attachment names > subject (people don't update subjects)
    body_kind = "attached wording" if from_attached else "first sentence"
    order = ([(from_body, body_kind), (seen_desc, "what Mirage saw")] if from_attached else
             [(seen_desc, "what Mirage saw"), (from_body, body_kind)]) + \
            [(from_files, "file names"), (subject_desc, "subject")]
    plan["quote"], plan["quote_key"] = email_quote(parsed)
    status("Writing the description")                   # the language model goes first; the rules stay in the menu
    pages = pdf_pages_for_llm(keep) if get_llm(wait=False) else {}
    plan["pdf_pages"] = pages
    model_desc = llm_describe(parsed["subject"], plan["quote"], [a["name"] for a in keep], pages)
    if model_desc:
        model_desc = house_style(model_desc, False, trim_status=False)   # UPDATED: the model's call, from the wording
        order.insert(0, (model_desc, "language model"))
    sources = {}
    for x, why in order:                                  # first source of each wording wins
        q = qualify(x, kind)
        if q and q not in sources:
            sources[q] = why
    plan["desc_options"] = list(sources)
    plan["desc_sources"] = sources
    top = sources.get(plan["desc_options"][0]) if plan["desc_options"] else None
    plan["desc_source"] = top
    body = parsed["body_clean"] or parsed["html_clean"] or ""
    if top == "language model":                          # it read the whole email (as shown at the top)
        plan["desc_block"] = plan["quote"]
    elif top in ("attached wording", "first sentence"):  # the paragraph the wording came from (for Hermes)
        plan["desc_block"] = source_paragraph(body, source_sentence)
    elif top == "file names":
        plan["desc_block"] = "\n".join(a["name"] for a in keep)
    elif top == "subject":
        plan["desc_block"] = parsed["subject"]
    else:
        plan["desc_block"] = ", ".join(content_seen)
    if source_sentence:                                  # highlight where the description came from
        plan["quote_key"] = source_sentence
    plan["seen_as"] = {a["name"]: PDF_SEEN_AS[a["name"]] for a in keep if a["name"] in PDF_SEEN_AS}
    if job:
        plan_email_also(plan, status)
    return plan


def source_paragraph(body, sentence=None):
    """The paragraph of the email holding this sentence (or, without one, the
    first real paragraph after the greeting)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", body or "") if p.strip()]
    flat = lambda t: re.sub(r"\s+", " ", t).strip().lower()
    if sentence:
        key = flat(sentence)[:40]
        for p in paras:
            if key and key in flat(p):
                return re.sub(r"[ \t]+", " ", p)
    for p in paras:
        lines = [l for l in p.splitlines() if l.strip() and not GREETING.match(l.strip())]
        if lines and not ACKNOWLEDGEMENT.match(" ".join(lines)):
            return " ".join(l.strip() for l in lines)
    return None


def plan_email_also(plan, status=lambda msg: None):
    """'Also file to' suggestions for an email, before its folder exists:
    attachments are staged in a private temp folder so PDFs can be read."""
    import tempfile
    status("Working out 'Also file to' suggestions")
    if not plan.get("staging"):
        plan["staging"] = Path(tempfile.mkdtemp(prefix="fileuzi-"))
        for a in plan["atts"]:
            if not is_branding(a):
                (plan["staging"] / Path(a["name"]).name).write_bytes(a["data"])
    names = sorted(p.name for p in plan["staging"].iterdir())
    desc = plan["desc_options"][0] if plan.get("desc_options") else ""
    plan["also"] = plan_also(plan["eml"].parent, plan["staging"], plan["job"], names, desc)
    return plan["also"]


def drop_staging(plan):
    if plan.get("staging"):
        shutil.rmtree(plan["staging"], ignore_errors=True)
        plan["staging"] = None


def email_folder_name(job, direction, when_d, who, desc):
    w, d = clean(who), clean(desc)
    if UNDERSCORES:
        w, d = w.replace(" ", "_"), d.replace(" ", "_")
    return f"{job}_{direction}_{when_d:%d-%m-%Y}_{w}_{d}"


def file_email(plan, rows, make_pdf, job, direction, who, desc, when_d=None, status=lambda msg: None):
    """Create the new IN/OUT folder beside the .eml, write the chosen files
    (never overwriting), verify them, then bin the .eml.
    Returns (folder or None, [problems])."""
    parsed, eml = plan["parsed"], plan["eml"]
    when_d = when_d or plan["when"]
    keep = [a for a in plan["atts"] if a["row"] in rows]
    if not keep and not make_pdf:
        return None, ["Nothing ticked to extract, so nothing was filed."]
    with Waited("remembering the contact name (history file)"):
        remember_name(job, direction, clean(who))
    with Waited(f"making the folder in {eml.parent}"):
        folder = unique_path(eml.parent / email_folder_name(job, direction, when_d, who, desc))
        folder.mkdir()
    written, problems = [], []
    status("Filing: writing the attachments")
    with Waited(f"writing {len(keep)} attachment(s)"):
        for a in keep:
            p = write_new(folder, a["name"], a["data"])
            written.append((p, len(a["data"])))
    if make_pdf:
        status("Filing: making the PDF of the email")
        with Waited("making the PDF of the email"):
            pdf, info = email_pdf(parsed, job)
        if pdf:
            written.append((write_new(folder, info, pdf), len(pdf)))
        else:
            problems.append(f"No PDF of the email: {info}")
            for n, img in enumerate(plan["big_embedded"], 1):   # fall back to the images themselves
                ext = {"image/jpeg": ".jpg", "image/gif": ".gif"}.get(img["ctype"], ".png")
                name = f"{job}_email_screenshot_{when_d:%Y-%m-%d}_{n:03d}{ext}"
                written.append((write_new(folder, name, img["data"]), len(img["data"])))

    # verify every file before the .eml goes
    status("Filing: checking the files and binning the .eml")
    bad = [p.name for p, size in written if not p.is_file() or p.stat().st_size != size]
    if bad or not written:
        return folder, ["Something didn't save properly, so the email was NOT removed:\n"
                        + "\n".join(bad or ["(nothing written)"])]
    with Waited("remembering image fingerprints (history file)"):
        remember_images([i["data"] for i in parsed["embedded"]] +
                        [a["data"] for a in plan["atts"] if a["ctype"].startswith("image/")])
    with Waited("moving the .eml to the bin"):
        binned = trash(eml)
    if not binned:
        problems.append("Couldn't move the .eml to the bin; please delete it yourself.")
    return folder, problems


def process_email(eml: Path, index=1, total=1):
    """zenity version: preview -> name -> new IN/OUT folder -> verify -> bin -> Also file to."""
    tag = f"Email {index} of {total}" if total > 1 else "Email"
    try:
        plan = plan_email(eml)
    except Exception as e:
        message("error", f"Couldn't read {eml.name}:\n{e}")
        return
    try:
        _process_email(plan, tag)
    finally:
        drop_staging(plan)


def _process_email(plan, tag):
    parsed, eml, direction, when_d = plan["parsed"], plan["eml"], plan["direction"], plan["when"]
    if plan["skip"]:
        message("info", f"{tag}: {parsed['subject']}\n\n{plan['skip']}")
        return
    job = plan["job"] or clean(ask(f"{tag}: {eml.name}", "Couldn't find a job number. Job number:",
                                   guess_job_number(eml)) or "")
    if not job:
        return
    atts, big_embedded = plan["atts"], plan["big_embedded"]
    labels = {}
    for a in atts:
        kb = a["size"] / 1024
        size = f"{kb / 1024:.1f} MB" if kb > 1024 else f"{kb:.0f} KB"
        seen = f"  (page 1 looks like: {plan['seen_as'][a['name']]})" if a["name"] in plan["seen_as"] else ""
        labels[a["row"]] = f"OMITTED: {a['why']}" if is_branding(a) else size + seen
    options = [a["row"] for a in atts]
    ticked = {a["row"] for a in atts if not is_branding(a)}
    if big_embedded:
        options.insert(0, PDF_ROW)
        ticked.add(PDF_ROW)
        labels[PDF_ROW] = f"{len(big_embedded)} sketch/screenshot image(s) in the body"
    omitted = [a["row"] for a in atts if is_branding(a)]
    content_seen = plan["content_seen"]
    intro = (f"{tag}  ·  {direction}  ·  {when_d:%d-%m-%Y}\n{parsed['subject']}\n"
             f"From {person(parsed['from'])} to {person(parsed['to'])}\n\n"
             f"Ticked items go into the new folder. {len(omitted)} image attachment(s) omitted as branding.\n"
             + (f"Images in the body: {len(big_embedded)} content"
                + (f" ({', '.join(content_seen)})" if content_seen else "")
                + f", {plan['small_embedded']} ignored ("
                + ", ".join(sorted({i['why'].split(',')[0] for i in parsed['embedded'] if i['why']})) + ").\n"
                if parsed["embedded"] else "")
             + "Cancel skips this email (it stays where it is).")
    chosen = checklist(f"{tag}: what to extract", intro, options, ticked, labels)
    if not chosen:
        return
    who_opts = plan["who_options"] or recent_names(eml.parent / "_", job, direction)
    who = ask(f"{tag}: {parsed['subject']}", "Sender:" if direction == "IN" else "Recipient:",
              who_opts[0] if who_opts else "", who_opts)
    if not who:
        return
    desc_opts = plan["desc_options"]
    desc = ask(f"{tag}: {parsed['subject']}", "Description (from the email's own wording; others in the list):",
               desc_opts[0] if desc_opts else "", desc_opts)
    if not desc:
        return
    folder, problems = file_email(plan, set(chosen), PDF_ROW in chosen, job, direction, who, desc)
    if folder is None or (problems and "NOT removed" in problems[0]):
        message("error", "\n".join(problems))
        return
    if problems:
        message("warning", "\n".join(problems))
    d = clean(desc).replace(" ", "_") if UNDERSCORES else clean(desc)
    also_file_to(folder, job, sorted(p.name for p in folder.iterdir() if p.is_file()), d)


# ---------- recipient / sender memory ----------

HISTORY = Path.home() / ".local" / "share" / "fileuzi-rename" / "names.json"
DATE_IN_NAME = re.compile(r"_(?:IN|OUT)_(\d{2}-\d{2}-\d{4})_")


def load_history():
    try:
        return json.loads(HISTORY.read_text())
    except Exception:
        return {}


def remember_name(job, direction, who):
    """Most recent first, up to 10 names per project and direction."""
    data = load_history()
    key = f"{job}|{direction}"
    names = [n for n in data.get(key, []) if n != who]
    data[key] = [who] + names[:9]
    try:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps(data, indent=1))
    except Exception:
        pass


def names_from_folders(folder: Path, job, direction):
    """Fallback: read names out of older space-style folder names, newest first.
    ('2505_OUT_21-11-2025_SMITH_PDFS AND DWGS' -> 'SMITH')."""
    found = []
    pattern = re.compile(rf"^{re.escape(job)}_{direction}_(\d{{2}}-\d{{2}}-\d{{4}})_([^_]+)_[^_]+$")
    try:
        for sib in folder.parent.iterdir():
            m = pattern.match(sib.name)
            if sib.is_dir() and m and sib != folder:
                found.append((datetime.strptime(m.group(1), "%d-%m-%Y"), m.group(2)))
    except Exception:
        pass
    out = []
    for _, name in sorted(found, reverse=True):
        if name not in out:
            out.append(name)
    return out


def recent_names(folder: Path, job, direction):
    names = load_history().get(f"{job}|{direction}", [])
    for n in names_from_folders(folder, job, direction):
        if n not in names:
            names.append(n)
    return names[:10]


# ---------- email for fresh OUT folders ----------
# How "Create email" works:
#   "betterbird" -> Betterbird/Thunderbird compose with the files ATTACHED and
#                   your HTML signature (via Proton Mail Bridge)
#   "webmail"    -> a mailto link (subject + greeting) in Proton web, with the
#                   folder opened in Files to drag the attachments in
MAIL_CLIENT = "betterbird"
# Proton's web mailto handler (from Proton's help pages). Set to None to use
# whatever your computer's default mail app is instead.
MAIL_COMPOSE_URL = "https://mail.proton.me/inbox/#mailto={}"
MAX_ATTACHMENTS_MB = 25


SMALL_WORDS = {"and", "of", "the", "on", "in", "at", "upon", "under", "by", "to"}


def title_case(text):
    """'12 HIGH STREET CUCKFIELD WEST SUSSEX' -> '12 High Street Cuckfield West Sussex'
    (small words like 'upon' stay lower-case; '12A' / 'B-012' stay as they are)."""
    out = []
    for i, w in enumerate(text.split()):
        lw = w.lower()
        if re.search(r"\d", w):
            out.append(w.upper())
        elif i and lw in SMALL_WORDS:
            out.append(lw)
        else:
            out.append("-".join(part[:1].upper() + part[1:] for part in lw.split("-")))
    return " ".join(out)


def project_name(job_root: Path, job):
    """'2505_12 HIGH STREET CUCKFIELD' / 'Smith House 2505' -> '12 High Street Cuckfield'"""
    if not job_root:
        return ""
    name = re.sub(rf"(^|[\s_\-]){re.escape(job)}([\s_\-]|$)", " ", job_root.name, flags=re.I)
    name = re.sub(r"[\s_]+", " ", name).strip(" -")
    return title_case(name)


KEEP_CAPS = {"DAS", "BR", "CDM", "SAP", "GA", "PDFS", "PDF", "DWGS", "DWG", "PD", "LDC",
             "NMA", "BNG", "EPC", "PV", "RIBA", "JCT", "IFC", "PWA", "OS"}


def sentence_case(text):
    """'UPDATED PLANS AND D&A STATEMENT' -> 'Updated plans and D&A statement'"""
    words = []
    for i, w in enumerate(text.split()):
        if w.upper() in KEEP_CAPS or re.search(r"[&\d]", w) or len(w) == 1:
            words.append(w.upper())
        else:
            words.append(w.capitalize() if i == 0 else w.lower())
    return " ".join(words)


def phrase_case(text):
    """Like sentence_case but for mid-sentence: 'DETAIL T' -> 'detail T'."""
    out = sentence_case(text).split()
    if out and not (out[0].upper() in KEEP_CAPS or re.search(r"[&\d]", out[0]) or len(out[0]) == 1):
        out[0] = out[0].lower()
    return " ".join(out)


def nice_list(items):
    """['plans', 'elevations', 'D&A statement'] -> 'plans, elevations and D&A statement'"""
    items = [i for i in items if i]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def email_wording(desc):
    """Full-sentence version of the description, e.g.
    'the updated plans and elevations, and the D&A statement'."""
    plain = desc.replace("_", " ").strip()
    if LAST_SUGGESTION["text"] and clean(plain) == clean(LAST_SUGGESTION["text"]):
        upd = [phrase_case(i) for i in LAST_SUGGESTION["updated"]]
        new = [phrase_case(i) for i in LAST_SUGGESTION["new"]]
    else:                                        # you edited it: best effort
        parts = [p.strip() for p in re.split(r"\s+AND\s+", plain, flags=re.I) if p.strip()]
        upd, new = [], [phrase_case(p) for p in parts]
        if new and new[0].lower().startswith("updated "):
            upd, new = [new[0][8:]], new[1:]
    if upd and new:
        return f"the updated {nice_list(upd)}, and the {nice_list(new)}"
    if upd:
        return f"the updated {nice_list(upd)}"
    return f"the {nice_list(new)}" if new else ""


SIGNATURE_FOLDER, SIGNATURE_FILE = "*EMAIL_SIGNATURE*", "email_signature.html"   # FileUzi's template


def load_signature(tools: Path):
    """FileUzi's email_signature.html, with its images embedded so they
    survive being pasted into Proton."""
    import base64
    import mimetypes
    path = tools / SIGNATURE_FOLDER / SIGNATURE_FILE
    if not path.is_file():
        return ""
    html = path.read_text(encoding="utf-8", errors="replace")

    def embed(m):
        src = m.group(2)
        if re.match(r"^(https?:|data:|cid:)", src, re.I):
            return m.group(0)
        img = (path.parent / src).resolve()
        if not img.is_file():
            return m.group(0)
        mime = mimetypes.guess_type(str(img))[0] or "image/png"
        data = base64.b64encode(img.read_bytes()).decode()
        return f'{m.group(1)}"data:{mime};base64,{data}"'
    return re.sub(r'(src\s*=\s*)["\']([^"\']+)["\']', embed, html, flags=re.I)


def find_betterbird():
    """Betterbird (preferred) or Thunderbird: installed normally or as a Flatpak.
    Returns the command prefix to run, or None."""
    for exe in ("betterbird", "thunderbird"):
        path = shutil.which(exe)
        if path:
            return [path]
    for app_id in ("eu.betterbird.Betterbird", "org.mozilla.Thunderbird"):
        for root in (Path("/var/lib/flatpak/exports/bin"),
                     Path.home() / ".local/share/flatpak/exports/bin"):
            if (root / app_id).exists():
                return ["flatpak", "run", f"--filesystem={{folder}}", app_id]
    return None


def compose_betterbird(cmd_prefix, folder: Path, subject, body_html):
    """FileUzi's -compose launch: subject, HTML body and every file attached."""
    files = sorted(p for p in folder.iterdir() if p.is_file())
    # literal spaces are fine (as in FileUzi); ' and , would break the
    # -compose syntax, so those two are %-encoded in the file:// address
    attach = ",".join("file://" + str(p.absolute()).replace("'", "%27").replace(",", "%2C")
                      for p in files)
    q = lambda v: v.replace("'", "\\'")                 # quotes inside a value
    params = ["to=''", f"subject='{q(subject)}'"]
    if attach:
        params.append(f"attachment='{attach}'")
    params += [f"body='{q(body_html)}'", "format=html"]
    cmd = [part.replace("{folder}", str(folder)) for part in cmd_prefix]
    subprocess.Popen(cmd + ["-compose", ",".join(params)], start_new_session=True)


def offer_email(folder: Path, job, who, desc):
    """Create email for a fresh OUT folder (see MAIL_CLIENT)."""
    from urllib.parse import quote
    import html as htmllib
    who_plain = who.replace("_", " ").strip()
    first = who_plain.split()[0].title() if who_plain else "[Name]"
    wording = email_wording(desc)                              # 'the updated plans, ...'

    files = [p for p in folder.iterdir() if p.is_file()]
    size_mb = sum(p.stat().st_size for p in files) / 1048576
    client = find_betterbird() if MAIL_CLIENT == "betterbird" else None
    too_big = size_mb > MAX_ATTACHMENTS_MB
    attach_now = bool(client) and not too_big

    if attach_now:
        detail = f"Opens Betterbird with the {len(files)} file(s) attached ({size_mb:.1f} MB)."
    else:
        why = ("Betterbird wasn't found, so this opens Proton web instead. "
               if MAIL_CLIENT == "betterbird" and not client else "")
        if too_big:
            why = f"The files are {size_mb:.0f} MB (over {MAX_ATTACHMENTS_MB} MB), so they aren't attached. "
        detail = why + "Drag the files in from the folder that opens."
    ok = subprocess.run(["zenity", "--question", "--no-markup", "--title", f"Email: {folder.name}",
                         "--text", f"Create an email to {who_plain.title()} for these files?\n\n{detail}",
                         "--ok-label", "Create email", "--cancel-label", "Close", "--width", "450"])
    if ok.returncode != 0:
        return

    csv_path = find_rules_csv(folder)
    root = project_folder(folder, csv_path, job)
    subject_desc = re.sub(r"^the ", "", wording)
    subject_desc = subject_desc[:1].upper() + subject_desc[1:] if subject_desc else sentence_case(desc.replace("_", " "))
    subject = " - ".join(p for p in [job, project_name(root, job), subject_desc] if p)
    body_text = f"Hi {first},\n\n" + (f"Please find attached {wording}.\n\n" if wording else "")

    if client:                                       # Betterbird: HTML + signature
        tools = csv_path.parent if csv_path else Path(__file__).resolve().parent
        body_html = (f"<p>Hi {htmllib.escape(first)},</p>"
                     + (f"<p>Please find attached {htmllib.escape(wording)}.</p>" if wording else "")
                     + "<p><br></p>" + load_signature(tools))
        if too_big:
            subprocess.Popen(["xdg-open", str(folder)])
            _compose_no_files(client, folder, subject, body_html)
        else:
            compose_betterbird(client, folder, subject, body_html)
        return

    mailto = f"mailto:?subject={quote(subject)}&body={quote(body_text)}"    # webmail
    url = MAIL_COMPOSE_URL.format(quote(mailto, safe="")) if MAIL_COMPOSE_URL else mailto
    subprocess.Popen(["xdg-open", str(folder)])                # drag the files from here
    subprocess.Popen(["xdg-open", url])


def _compose_no_files(cmd_prefix, folder, subject, body_html):
    """Betterbird compose without attachments (files too big to email)."""
    q = lambda v: v.replace("'", "\\'")
    params = ["to=''", f"subject='{q(subject)}'", f"body='{q(body_html)}'", "format=html"]
    cmd = [part.replace("{folder}", str(folder)) for part in cmd_prefix]
    subprocess.Popen(cmd + ["-compose", ",".join(params)], start_new_session=True)


# ---------- main ----------

def rename_one(folder: Path, direction: str):
    title = f"File {direction}: {folder.name}"
    filenames = sorted(p.name for p in folder.iterdir() if p.is_file())

    job = find_job_number(folder) or clean(ask(
        title, "Couldn't find a job number in this folder or its project folder.\nJob number:",
        guess_job_number(folder)) or "")
    if not job:
        return
    recent = recent_names(folder, job, direction)
    who = ask(title, "Sender:" if direction == "IN" else "Recipient:",
              recent[0] if recent else "", recent)
    if not who:
        return
    remember_name(job, direction, clean(who))
    desc = ask(title, "Description:", qualify(suggest_description(filenames, folder, direction,
                                                                  created_date(folder),
                                                                  {f: folder / f for f in filenames}),
                                              folder_regime(folder, filenames)))
    if not desc:
        return

    made = created_date(folder)
    file_dates = sorted({date.fromtimestamp((folder / f).stat().st_mtime) for f in filenames})
    when = made
    if file_dates and file_dates != [made]:
        # files are dated differently from the folder: check with the user
        span = (f"{file_dates[0]:%d-%m-%Y}" if len(file_dates) == 1
                else f"{file_dates[0]:%d-%m-%Y} to {file_dates[-1]:%d-%m-%Y}")
        while True:
            raw = ask(title, f"Folder made {made:%d-%m-%Y}, but files are dated {span}.\n"
                             "Date for the folder name:", made.strftime("%d-%m-%Y"))
            if raw is None:
                return
            when = parse_date(raw, made)
            if when:
                break
            message("error", f"Couldn't read the date '{raw}'. Try DD-MM-YYYY.")

    who, desc = clean(who), clean(desc)
    if UNDERSCORES:
        who, desc = who.replace(" ", "_"), desc.replace(" ", "_")
    name = f"{job}_{direction}_{when:%d-%m-%Y}_{who}_{desc}"
    new_path = unique_path(folder.with_name(name))
    try:
        folder.rename(new_path)
    except OSError as e:
        message("error", f"Rename failed:\n{e}")
        return
    also_file_to(new_path, job, filenames, desc)
    if direction == "OUT" and (date.today() - when).days in (0, 1):     # today or yesterday
        offer_email(new_path, job, who, desc)


def test(args):
    """python3 fileuzi_rename.py --test "file1.pdf" ...           (just filenames)
       python3 fileuzi_rename.py --test /path/to/folder [OUT|IN]  (real folder)"""
    folder, direction = None, "OUT"
    if args and Path(args[0]).is_dir():
        folder = Path(args[0]).resolve()
        direction = args[1].upper() if len(args) > 1 else "OUT"
        filenames = sorted(p.name for p in folder.iterdir() if p.is_file())
    else:
        filenames = args
    emb = get_embedder()
    get_llm()
    print("Language model:", LLM_STATUS)
    print("Embedding model:", f"loaded from {MODEL_DIR}, {SANDBOX_STATUS}" if emb
          else f"NOT available (keywords only): {SANDBOX_STATUS}")
    try:
        import socket
        socket.create_connection(("1.1.1.1", 443), timeout=2)
        print("Network: OPEN (should not happen)")
    except OSError as e:
        print("Network:", e)
    sent = previously_sent(folder, direction) if folder else set()
    cats = classify_files(filenames)
    for f in filenames:
        idx = cats[f]
        line = (f"{f}\n   title: {file_title(f) or '-'}   number: {drawing_number(f) or '-'}"
                f"\n   group: {CATEGORIES[idx][0] if idx is not None else '-'}"
                f"   sent before: {'yes' if doc_keys(f) & sent else 'no'}")
        if emb:
            (i, score), = emb.best_matches([name_text(f)], [c[2] for c in CATEGORIES])
            flag = "" if score >= EMBED_THRESHOLD else " (below threshold, used keywords)"
            line += f"\n   model: {CATEGORIES[i][0]} {score:.2f}{flag}"
        print(line)
    print("\nDescription:", suggest_description(filenames, folder, direction))

    csv_path = find_rules_csv(folder) if folder else find_rules_csv(Path.cwd() / "x")
    rules = [r for r in load_rules(csv_path) if r["keywords"]] if csv_path else []
    if rules:
        print(f"\n'Also file to' rules from {csv_path}:")
        texts = [f"{r['type']}: {', '.join(r['keywords'])}" for r in rules]
        scores = emb.best_matches([name_text(f) for f in filenames], texts) if emb else [None] * len(filenames)
        for f, sc in zip(filenames, scores):
            kw = [f"{rules[i]['type']}" for i in best_rules(f, rules)]
            line = f"{f}\n   keyword: {', '.join(kw) or '-'}"
            if sc:
                idx, score = sc
                flag = "  -> pre-ticked" if score >= DEST_THRESHOLD else "  (too low, not ticked)"
                line += f"\n   model:   {rules[idx]['type']}  {score:.2f}{flag}"
            print(line)


FILED_NAME = re.compile(r"^(.+?)_(IN|OUT)_(\d{2}-\d{2}-\d{4})_(.+)$")


def desc_from_folder(folder: Path, job, direction, filenames):
    """Description part of an already-filed folder name. The sender/recipient
    is stripped using remembered names; falls back to describing the files."""
    m = FILED_NAME.match(folder.name)
    if not m:
        return suggest_description(filenames, folder, direction)
    rest = re.sub(r"(_\d+| \(\d+\))$", "", m.group(4))          # drop _2 / (2)
    for name in recent_names(folder, job, direction):
        for form in (name.replace(" ", "_"), name):
            if rest.upper().startswith(form.upper() + "_"):
                return rest[len(form) + 1:].replace("_", " ")
    if "_" in rest and " " in rest:                                  # space style: WHO_DESC WORDS
        return rest.split("_", 1)[1]
    return suggest_description(filenames, folder, direction)


def file_also_only(folder: Path):
    """Third menu item: just the 'Also file to?' step for an existing folder."""
    filenames = sorted(p.name for p in folder.iterdir() if p.is_file())
    if not filenames:
        message("info", f"{folder.name}\nhas no files to file.")
        return
    m = FILED_NAME.match(folder.name)
    direction = m.group(2) if m else "OUT"
    job = find_job_number(folder) or clean(ask(f"Also file: {folder.name}",
                                               "Couldn't find a job number. Job number:",
                                               guess_job_number(folder)) or "")
    if not job:
        return
    cache = {}

    def lazy_desc():                      # only needed for DESCRIPTION subfolders
        if "d" not in cache:
            cache["d"] = desc_from_folder(folder, job, direction, filenames)
        return cache["d"]
    also_file_to(folder, job, filenames, lazy_desc)


# ---------- folders in the panel: rename (File IN / OUT) or Also File To ----------

def plan_folder(folder: Path, mode, status=lambda msg: None):
    """mode 'in' / 'out' (rename) or 'also' (copies only). Nothing is changed here."""
    status(f"Looking at {folder.name}")
    filenames = sorted(p.name for p in folder.iterdir() if p.is_file())
    job = find_job_number(folder) or ""
    filed = FILED_NAME.match(folder.name)
    direction = mode.upper() if mode in ("in", "out") else (filed.group(2) if filed else "OUT")
    made = created_date(folder)
    when = (parse_date(filed.group(3), made) if (mode == "also" and filed) else made) or made
    file_dates = sorted({date.fromtimestamp((folder / f).stat().st_mtime) for f in filenames})
    atts = [{"name": f, "row": f, "size": (folder / f).stat().st_size, "why": None, "ctype": "", "data": None}
            for f in filenames]
    plan = {"mode": mode, "folder": folder, "eml": folder, "direction": direction, "job": job, "when": when,
            "made": made, "file_dates": file_dates, "atts": atts, "big_embedded": [], "small_embedded": 0,
            "parsed": {"subject": folder.name, "from": "", "to": "", "embedded": []}, "skip": None,
            "also": None, "staging": None, "content_seen": [], "quote": "", "quote_key": None}
    if not filenames:
        plan["skip"] = "This folder has no files in it, so there's nothing to file."
        return plan
    status("Describing the contents")
    data = {f: folder / f for f in filenames}
    if mode == "also":
        desc = desc_from_folder(folder, job, direction, filenames) if job else \
            suggest_description(filenames, folder, direction, None, data)
    else:
        desc = qualify(suggest_description(filenames, folder, direction, made, data),
                       folder_regime(folder, filenames))
    plan["desc_options"] = [d for d in [desc] if d]
    plan["desc_source"] = "folder name" if mode == "also" else "file names"
    plan["desc_block"] = folder.name if mode == "also" else "\n".join(filenames)
    plan["who_options"] = recent_names(folder, job, direction) if job else []
    plan["seen_as"] = {f: PDF_SEEN_AS[f] for f in filenames if f in PDF_SEEN_AS}
    if job:
        plan_folder_also(plan, status)
    return plan


def plan_folder_also(plan, status=lambda msg: None):
    status("Working out 'Also file to' suggestions")
    folder = plan["folder"]
    names = sorted(p.name for p in folder.iterdir() if p.is_file())
    desc = plan["desc_options"][0] if plan.get("desc_options") else ""
    plan["also"] = plan_also(folder, folder, plan["job"], names, desc)
    return plan["also"]


def file_folder(plan, c):
    """Rename the folder (File IN / OUT). Returns its path afterwards."""
    folder = plan["folder"]
    if plan["mode"] not in ("in", "out"):
        return folder
    name = email_folder_name(c["job"], c["direction"], c["when"], c["who"], c["desc"])
    remember_name(c["job"], c["direction"], clean(c["who"]))
    if folder.name == name:
        return folder
    new_path = unique_path(folder.with_name(name))
    folder.rename(new_path)
    return new_path


# ---------- Check Drawings: Current Drawings against what was actually issued ----------
# The dates on your OUT folders are the gospel: the drawing in the most recently
# dated OUT folder is the one that should be current. Revision codes that
# disagree with that order are warned about, not fixed automatically.

def same_drawing_content(a: Path, b: Path):
    """Same file, or the same drawing re-exported (identical text)."""
    import hashlib
    try:
        if a.stat().st_size == b.stat().st_size and \
                hashlib.sha1(a.read_bytes()).digest() == hashlib.sha1(b.read_bytes()).digest():
            return True
        ta, tb = pdf_text(a.read_bytes()), pdf_text(b.read_bytes())
        return bool(ta.strip()) and " ".join(ta.split()) == " ".join(tb.split())
    except Exception:
        return False


def issue_folder(path: Path):
    """('OUT', date) for a file inside a dated IN/OUT folder, else (None, None)."""
    for p in path.parents:
        m = FILED_NAME.match(p.name)
        if m:
            return m.group(2), parse_date(m.group(3), None)
    return None, None


def rev_code(name):
    """The revision part of a drawing name, for messages: 'P02', '04A', 'P2'."""
    stem = Path(name).stem
    m = re.search(rf"(?:^|[_\s-])((?:{STAGE_ALT})\d{{1,2}}|\d{{2,3}}[A-Z]?)\s*$", stem, re.I)
    if m:
        return m.group(1).upper()
    m = re.match(r"^\S+\s*[-–]\s*(\d{2,3}[A-Z]?)\b", stem)
    return m.group(1).upper() if m else stem


def plan_check(folder: Path, status=lambda msg: None):
    """Compare Current Drawings with every copy of your drawings in the job."""
    job = find_job_number(folder) or ""
    plan = {"mode": "check", "folder": folder, "eml": folder, "job": job, "issues": [], "skip": None,
            "parsed": {"subject": folder.name}}
    if not job:
        plan["skip"] = "Couldn't find a job number for this folder."
        return plan
    root = folder if JOB_RE.match(folder.name) else None
    for p in [folder, *folder.parents]:                    # the project folder: highest one named with the job
        if JOB_RE.match(p.name) and JOB_RE.match(p.name).group(1).upper() == job:
            root = p
    root = root or folder
    rel, state = resolve_folder(root, CURRENT_DRAWINGS.replace("XXXX", job).strip("/"), job)
    cd = root / rel                                     # e.g. 2505_CURRENT-DRAWINGS, matched loosely
    plan.update(root=root, current=cd, create_current=not cd.is_dir())
    csv_path = find_rules_csv(root)
    prefixes = my_prefixes(job, load_mapping(csv_path.parent) if csv_path else {})

    status("Looking through the job for your drawings")
    found = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and "CAD" not in d.upper()[len(job):][:6]]
        for f in files:
            d = parse_drawing(f)
            if not d:
                continue
            path = Path(dirpath) / f
            if not is_my_drawing(f, prefixes, path):
                continue
            direction, when = issue_folder(path)
            where = ("current" if path.parent == cd else
                     "superseded" if cd in path.parents else
                     "out" if direction == "OUT" and when else "other")
            found.setdefault((d["job"], d["drawing"]), []).append(
                {"path": path, "d": d, "where": where, "date": when})

    status("Checking revisions against issue dates")
    same_rev = lambda a, b: not is_newer(a["d"], b["d"]) and not is_newer(b["d"], a["d"])
    for key, items in sorted(found.items(), key=lambda kv: kv[0][1]):
        current = [e for e in items if e["where"] == "current"]
        issued = sorted([e for e in items if e["where"] == "out"], key=lambda e: e["date"])
        title = file_title((issued or current or items)[-1]["path"].name) or key[1]
        label = f"{key[1]} {title}".strip()
        warns, notes = [], []
        # revision codes against the issue order (PL/P mix-ups go by date, with a note)
        best = None
        for e in issued:
            if best and muddled(best["d"], e["d"]):
                notes.append(f"PL/P mix: {rev_code(best['path'].name)} ({best['date']:%d-%m-%Y}) then "
                             f"{rev_code(e['path'].name)} ({e['date']:%d-%m-%Y}), so going by date")
                best = e
                continue
            if best and is_newer(best["d"], e["d"]):
                warns.append(f"{rev_code(e['path'].name)} went out {e['date']:%d-%m-%Y}, after "
                             f"{rev_code(best['path'].name)} on {best['date']:%d-%m-%Y}")
            if best is None or is_newer(e["d"], best["d"]):
                best = e
        # the same revision issued with different contents
        by_rev = {}
        for e in issued:
            by_rev.setdefault(rev_code(e["path"].name), []).append(e)
        for code, copies in by_rev.items():
            changed = [c for c in copies[1:] if not same_drawing_content(copies[0]["path"], c["path"])]
            if changed:
                dates = ", ".join(f"{c['date']:%d-%m-%Y}" for c in copies)
                warns.append(f"{code} was issued {len(copies)} times ({dates}) with different contents: "
                             "the revision wasn't bumped")
        issue = None
        if issued:
            latest = issued[-1]                             # the gospel: last one out of the door

            def saved(e):                                   # an unissued file: when it was last saved
                try:
                    return date.fromtimestamp(e["path"].stat().st_mtime)
                except OSError:
                    return date.min

            def mixed_newer(c):                             # PL/P mix: newer only if saved after the issue
                return saved(c) > latest["date"]
            have = [c for c in current if same_rev(c, latest)]
            wip = [c for c in current if (mixed_newer(c) if muddled(c["d"], latest["d"])
                                          else is_newer(c["d"], latest["d"]))]
            stale = [c for c in current if c not in wip and c not in have and
                     (muddled(c["d"], latest["d"]) or is_newer(latest["d"], c["d"]))]
            for c in current:
                if muddled(c["d"], latest["d"]) and c not in wip:
                    notes.append(f"PL/P mix: Current {rev_code(c['path'].name)} against "
                                 f"{rev_code(latest['path'].name)} issued {latest['date']:%d-%m-%Y}, "
                                 "so going by date")
            changed_same = [c for c in have if not same_drawing_content(c["path"], latest["path"])]
            src = f"on {latest['date']:%d-%m-%Y}"
            if not current:
                issue = {"kind": "missing", "lines": [f"Not in Current Drawings",
                                                      f"Last issued: {rev_code(latest['path'].name)} {src}"],
                         "actions": [("copy", latest["path"])]}
            elif wip and not warns:
                continue                                    # a newer, unissued revision: work in progress
            elif not have:
                issue = {"kind": "behind",
                         "lines": [f"Current has {', '.join(rev_code(c['path'].name) for c in current)}",
                                   f"Last issued: {rev_code(latest['path'].name)} {src}"],
                         "actions": [("copy", latest["path"])] + [("supersede", c["path"]) for c in stale]}
            elif changed_same:
                issue = {"kind": "changed",
                         "lines": [f"Current {rev_code(latest['path'].name)} isn't the copy issued "
                                   f"{latest['date']:%d-%m-%Y}"],
                         "actions": [("supersede", c["path"]) for c in changed_same] + [("copy", latest["path"])]}
            elif stale:
                issue = {"kind": "duplicate",
                         "lines": [f"Older revision{'s' if len(stale) > 1 else ''} still in Current: "
                                   + ", ".join(rev_code(c["path"].name) for c in stale)],
                         "actions": [("supersede", c["path"]) for c in stale]}
            elif warns or notes:
                issue = {"kind": "warning" if warns else "note", "lines": [], "actions": []}
        elif len(current) > 1:                              # never issued: go by revision code
            newest = current[0]
            for c in current[1:]:
                if is_newer(c["d"], newest["d"]):
                    newest = c
            stale = [c for c in current if is_newer(newest["d"], c["d"])]
            if stale:
                issue = {"kind": "duplicate",
                         "lines": [f"Older revision{'s' if len(stale) > 1 else ''} still in Current: "
                                   + ", ".join(rev_code(c["path"].name) for c in stale)],
                         "actions": [("supersede", c["path"]) for c in stale]}
        if issue:
            issue.update(label=label, warns=warns, notes=list(dict.fromkeys(notes)),
                         ticked=not warns and issue["kind"] not in ("warning", "note"),
                         files=[e["path"].name for e in items])
            plan["issues"].append(issue)
    sups = superseded_folders(cd) if cd.is_dir() else []
    for stray in sups[1:]:                                 # e.g. 'Superseded' beside '2601_SUPERSEDED'
        n = sum(1 for f in stray.rglob("*") if f.is_file())
        plan["issues"].insert(0, {"kind": "stray", "label": f"{stray.name} → {sups[0].name}",
                                  "lines": [f"Two superseded folders in {cd.name}",
                                            f"{n} file{'s' if n != 1 else ''} in {stray.name}"],
                                  "actions": [("merge", stray)], "warns": [], "notes": [], "ticked": True,
                                  "files": [f.name for f in stray.rglob("*") if f.is_file()]})
    plan["drawings"] = len(found)
    plan["in_current"] = sum(1 for items in found.values() if any(e["where"] == "current" for e in items))
    return plan


def apply_check(plan, chosen):
    """Carry out the ticked fixes. Copies never overwrite; anything replaced
    goes to Superseded/ (timestamped if a file of that name is already there)."""
    cd, done, notes, moved = plan["current"], 0, [], 0
    if chosen and not cd.is_dir():
        cd.mkdir()                                      # no Current Drawings folder yet: make it
    for i in chosen:
        issue = plan["issues"][i]
        copied_names = set()
        for action, path in issue["actions"]:
            if action == "merge" and path.is_dir():       # stray superseded folder into the real one
                main = superseded_dir(cd)
                for f in sorted(path.iterdir()):
                    target = main / f.name
                    if target.exists():
                        target = main / f"{f.stem}_{datetime.now():%Y%m%d_%H%M%S}{f.suffix}"
                    shutil.move(str(f), str(target))
                try:
                    path.rmdir()
                except OSError:
                    notes.append(f"{path.name} wasn't empty afterwards, so it was left in place")
                continue
            if action == "supersede" and path.exists() and path.parent == cd and path.name not in copied_names:
                move_to_superseded(path)
                moved += 1
            elif action == "copy":
                if (cd / path.name).exists():
                    notes.append(f"{path.name} is already in Current Drawings (left as it is)")
                    continue
                copied, _ = copy_files(path.parent, cd, {path.name})
                copied_names |= set(copied)
        done += 1
    text = f"Fixed {done} drawing{'s' if done != 1 else ''}."
    if moved:
        text += f"\nMoved {moved} older revision{'s' if moved != 1 else ''} to Superseded/."
    if notes:
        text += "\n\n" + "\n".join(notes)
    return text


# ---------- filing examples: every accepted / corrected description, for Hermes ----------
# One row per filing from the panel. 'suggested' is what the tool proposed,
# 'final' what was filed; 'edited' = 1 when you changed it. Copies are recorded
# the same way (suggested groups against what you actually sent where).
EXAMPLES_DB = None      # None = filing_examples.db beside this script (in *FILING-WIDGET-TOOLS*), or set a path

EXAMPLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS filings (
    id               INTEGER PRIMARY KEY,
    filed_at         TEXT NOT NULL,      -- when you pressed File (local time, ISO)
    kind             TEXT NOT NULL,      -- email / in / out / also
    job              TEXT,
    direction        TEXT,               -- IN / OUT
    item_date        TEXT,               -- date in the folder name (YYYY-MM-DD)
    who              TEXT,               -- sender / recipient as filed
    suggested        TEXT,               -- description the tool proposed first
    alternatives     TEXT,               -- JSON list: the other suggestions offered
    final            TEXT,               -- description actually filed
    edited           INTEGER NOT NULL,   -- 1 = you changed the suggestion
    folder_name      TEXT,               -- the IN/OUT folder as named
    subject          TEXT,               -- email subject (emails only)
    sender           TEXT,
    recipients       TEXT,
    email_text       TEXT,               -- the email's own words, above the sign-off
    key_sentence     TEXT,               -- the 'please find attached...' sentence, if found
    source_kind      TEXT,               -- where the suggestion came from: attached wording / first
                                         --   sentence / what Mirage saw / file names / subject
    source_block     TEXT,               -- the paragraph (or file list / subject) it was taken from
    files            TEXT,               -- JSON list of file names filed
    seen_as          TEXT,               -- JSON {file: what page 1 looked like} (Mirage)
    suggested_copies TEXT,               -- JSON [{folder, files}] as first suggested
    final_copies     TEXT,               -- JSON [{folder, files}] as actually copied
    copies_edited    INTEGER NOT NULL,   -- 1 = you changed where things were copied
    source           TEXT                -- the .eml or folder it came from
);
CREATE INDEX IF NOT EXISTS filings_job ON filings(job);
CREATE INDEX IF NOT EXISTS filings_edited ON filings(edited);
"""


def examples_path():
    return Path(EXAMPLES_DB).expanduser() if EXAMPLES_DB else Path(__file__).resolve().parent / "filing_examples.db"


def examples_db():
    import sqlite3
    path = examples_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    old = HISTORY.parent / "filing_examples.db"            # where earlier versions kept it
    if not path.exists() and old.exists() and old != path:
        shutil.copy2(old, path)                            # carry the examples across (old copy left as a backup)
    con = None
    with Waited(f"opening the examples database ({path})"):
        try:
            con = sqlite3.connect(path, timeout=3)
            con.execute("PRAGMA journal_mode = DELETE")    # plain journal: safest on a network share
        except sqlite3.OperationalError as e:
            # A folder that can't do file locks (some network/FUSE mounts) makes every
            # write wait out the timeout, then fail. Only FileUzi writes this file, one
            # write at a time (DB_LOCK), so locking can safely be switched off.
            if con:
                con.close()
            with open(DEBUG_LOG, "a") as log:
                log.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  examples database: {e}; using no-lock mode\n")
            con = sqlite3.connect(f"file:{path}?nolock=1", uri=True, timeout=3)
            con.execute("PRAGMA journal_mode = DELETE")
    con.executescript(EXAMPLES_SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(filings)")}
    for col in ("source_kind", "source_block"):           # older databases: add the new columns
        if col not in have:
            con.execute(f"ALTER TABLE filings ADD COLUMN {col} TEXT")
    con.execute("PRAGMA user_version = 2")
    con.commit()
    return con


def record_example(plan, c, folder_name=""):
    """Called after a successful filing. Never lets a database problem stop filing."""
    try:
        def copies(items):
            merged = {}
            for rel, typed, files in items:                # two groups to one folder = one entry
                merged.setdefault(rel + (f"/{typed}" if typed else ""), set()).update(files)
            return [{"folder": k, "files": sorted(v)} for k, v in sorted(merged.items())]
        parsed = plan.get("parsed") or {}
        options = plan.get("desc_options") or []
        suggested = options[0] if options else ""
        final = c.get("desc") or suggested
        attached = {a["name"] for a in plan.get("atts", [])}
        files = sorted(c.get("rows") or attached) if plan.get("mode", "email") == "email" else sorted(attached)
        if c.get("pdf"):
            files.append("PDF of the email")
        sug = copies(plan.get("suggested_routes") or [])
        fin = copies(c.get("routes") or [])
        when = c.get("when") or plan.get("when")
        row = (datetime.now().isoformat(timespec="seconds"), plan.get("mode", "email"), c.get("job"),
               c.get("direction") or plan.get("direction"), when.isoformat() if when else None,
               c.get("who"), suggested, json.dumps(options[1:]), final,
               int(clean(final) != clean(suggested)), folder_name, parsed.get("subject"),
               parsed.get("from"), parsed.get("to"), plan.get("quote") or None, plan.get("quote_key"),
               json.dumps(files), json.dumps(plan.get("seen_as") or {}), json.dumps(sug), json.dumps(fin),
               int(sug != fin), str(plan.get("eml") or plan.get("folder") or ""),
               plan.get("desc_source"), plan.get("desc_block"))
        with DB_LOCK, Waited("writing the filing to the examples database"):
            con = examples_db()
            with con:
                con.execute("INSERT INTO filings (filed_at, kind, job, direction, item_date, who, suggested, "
                            "alternatives, final, edited, folder_name, subject, sender, recipients, email_text, "
                            "key_sentence, files, seen_as, suggested_copies, final_copies, copies_edited, source, "
                            "source_kind, source_block) VALUES (" + ",".join("?" * 24) + ")", row)
            con.close()
    except Exception as e:
        print(f"Couldn't record the filing example: {e}", file=sys.stderr)


def show_examples(args):
    """python3 fileuzi_rename.py --examples [N]          recent filings, suggested -> final
       python3 fileuzi_rename.py --export-examples F.jsonl  everything, one JSON per line (for Hermes)"""
    path = examples_path()
    if not path.exists():
        print(f"No examples yet ({path} is made on the first filing).")
        return
    con = examples_db()
    con.row_factory = __import__("sqlite3").Row
    total, edited, moved = con.execute(
        "SELECT COUNT(*), SUM(edited), SUM(copies_edited) FROM filings").fetchone()
    print(f"{path}\n{total} filings: description changed {edited or 0} times "
          f"({100 * (edited or 0) // max(total, 1)}%), copies changed {moved or 0} times.\n")
    n = int(args[0]) if args and args[0].isdigit() else 15
    for r in con.execute("SELECT * FROM filings ORDER BY id DESC LIMIT ?", (n,)):
        mark = "edited" if r["edited"] else "kept"
        print(f"{r['filed_at'][:16]}  {r['job']} {r['direction'] or ''}  [{mark}]")
        print(f"   suggested: {r['suggested']}")
        if r["edited"]:
            print(f"   filed as:  {r['final']}")
        if r["source_kind"]:
            block = " ".join((r["source_block"] or "").split())
            print(f"   from {r['source_kind']}: {block[:110]}{'…' if len(block) > 110 else ''}")
    con.close()


def export_examples(args):
    target = Path(args[0] if args else "filing_examples.jsonl")
    con = examples_db()
    con.row_factory = __import__("sqlite3").Row
    with target.open("w") as out:
        for r in con.execute("SELECT * FROM filings ORDER BY id"):
            d = dict(r)
            for k in ("alternatives", "files", "seen_as", "suggested_copies", "final_copies"):
                d[k] = json.loads(d[k]) if d[k] else None
            out.write(json.dumps(d) + "\n")
    con.close()
    print(f"Wrote {target}")


def make_mapping():
    """python3 fileuzi_rename.py --make-mapping
    Scans every project's Current Drawings folder for drawings numbered with a
    client project number (e.g. 'B-012 - 133 - ...' in job 2505) and writes
    custom_project_number_mapping_suggested.csv beside the script. Never
    touches your real mapping file."""
    from collections import Counter
    tools = Path(__file__).resolve().parent
    root = tools.parent
    existing = load_mapping(tools)
    prefix_re = re.compile(r"^([A-Za-z]{1,3}-?\d{2,4}|\d{3,5})\s*[-–_]\s*\d{2,3}[A-Z]?[\s\-–_]")
    found = {}                                   # (client no, job) -> count
    for proj in sorted(p for p in root.iterdir() if p.is_dir() and JOB_RE.match(p.name)):
        job = JOB_RE.match(proj.name).group(1).upper()
        try:
            cd_dirs = [d for d in proj.iterdir() if d.is_dir() and is_current_drawings(d)]
        except Exception:
            continue
        counts = Counter()
        for d in cd_dirs:
            for f in d.iterdir():
                m = prefix_re.match(f.name) if f.suffix.lower() == ".pdf" else None
                if m and m.group(1).upper() != job:
                    counts[m.group(1).upper()] += 1
        for prefix, n in counts.items():
            found[(prefix, job)] = n
    rows = dict(existing)
    print(f"Scanned {root}\n")
    for (prefix, job), n in sorted(found.items(), key=lambda x: x[0][1]):
        flag = ""
        if prefix in rows and rows[prefix] != job:
            flag = f"   !! also mapped to {rows[prefix]}: check"
        elif prefix not in rows:
            rows[prefix] = job
        print(f"  {prefix:10} -> {job}   ({n} drawing{'s' if n > 1 else ''}){flag}")
    if not found:
        print("  No client-numbered drawings found in any Current Drawings folder.")
    out = tools / "custom_project_number_mapping_suggested.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Client Project No", "JWA Job No"])
        for c, l in sorted(rows.items(), key=lambda x: x[1]):
            w.writerow([c, l])
    print(f"\nWrote {out.name} ({len(rows)} rows). Check it, then rename it to {MAPPING_FILE}.")


def test_image(paths):
    """python3 fileuzi_rename.py --test-image logo.png sketch.jpg ...
    Shows Mirage's verdict (and raw answer) for each image, sandboxed, offline."""
    v = get_vision()
    print("Mirage:", "running in bubblewrap" if v else "NOT available (see warnings / run --download-model)")
    for p in paths:
        data = Path(p).read_bytes()
        if not v:
            print(f"{p}: (no Mirage)")
            continue
        if str(p).lower().endswith(".pdf"):           # page 1 of a PDF
            r = v.ask(data, PDF_PAGE_CHOICES, pdf=True)
            print(f"{p}\n   page 1 looks like: {r.get('choice')} "
                  f"{'' if r.get('conf') is None else format(r['conf'], '.0%')}"
                  f" -> folder wording: {PDF_PAGE_DESC.get(r.get('choice'), '(not used)')}")
            print("   raw:", json.dumps(r.get("raw") or r.get("error"), default=str)[:300])
            continue
        r = v.ask(data)
        label, conf = r.get("choice"), r.get("conf")
        is_brand, score = vision_verdict(label, conf, r.get("table"))
        verdict = "BRANDING (skipped)" if is_brand else "CONTENT (kept / makes PDF)"
        print(f"{p}\n   top: {label} {'' if conf is None else f'{conf:.0%}'}"
              + (f" | branding total {score:.0%}" if r.get("table") and score is not None else "")
              + f" -> {verdict}")
        print("   raw:", json.dumps(r.get("raw") or r.get("error"), default=str)[:300])


def download_model():
    """python3 fileuzi_rename.py --download-model
    The ONLY time this script goes online: fetches bekko's ONNX model,
    tokenizer and pooling settings into MODEL_DIR. Every other run is offline."""
    for k, v in {"HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
                 "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1"}.items():
        os.environ[k] = v
    from huggingface_hub import hf_hub_download, list_repo_files
    files = list_repo_files(EMBED_MODEL)
    onnx = "onnx/model.onnx" if "onnx/model.onnx" in files else next(f for f in files if f.endswith(".onnx"))
    wanted = [onnx, onnx + "_data", "tokenizer.json", "1_Pooling/config.json", "config.json"]
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name in [w for w in wanted if w in files]:
        hf_hub_download(EMBED_MODEL, name, local_dir=str(MODEL_DIR))
        print(f"  got {name}")
    size = sum(f.stat().st_size for f in MODEL_DIR.rglob("*") if f.is_file()) / 1048576
    print(f"\nbekko saved to {MODEL_DIR} ({size:.0f} MB).")
    try:                                              # Mirage: weights + engine, for images
        os.environ["CACTUS_TELEMETRY"] = "0"
        from cactus.agent import fetch
        MIRAGE_DIR.mkdir(parents=True, exist_ok=True)
        w = fetch.fetch_weights(fetch.MIRAGE, dest_dir=str(MIRAGE_DIR))
        lib = fetch.fetch_library(dest_dir=str(MIRAGE_DIR), generation=fetch.MIRAGE)
        print(f"Mirage saved to {MIRAGE_DIR}:\n  {Path(w).name}\n  {Path(lib).name}")
    except ImportError:
        print("Mirage skipped: install it with  python3 -m pip install --user cactus-compute")
    except Exception as e:
        print(f"Mirage download failed: {e}")
    print("\nThe tool now runs fully offline.")


# ---------- The description writer (LFM2.5 in llama.cpp, inside bubblewrap) ----------
USE_LLM = True                                     # write the description with the language model
LLM_MODEL = "~/models/LFM2.5-1.2B-Instruct-Q4_K_M.gguf"
LLM_SERVER_BIN = "~/llama.cpp/build/bin/llama-server"
LLM_THREADS = 3                                    # of the N150's 4 cores: one stays free for the panel (see MODEL_THREADS)
LLM_EXAMPLES = 8                                   # your recent filings shown to it as worked examples
LLM_CACHE = Path.home() / ".cache" / "fileuzi-llm" # the examples, read once and saved (no email text)

LLM_SYSTEM = (
    "You name folders for an architecture practice. Read the email, the attached file names and "
    "any 'Page 1' text from the attached PDFs, then write ONE short description of what was sent. "
    "Page 1 text often holds company names, addresses and references: leave those out.\n"
    "Rules:\n"
    "- Capital letters only. 10 words or fewer. No punctuation.\n"
    "- Use the sender's own words for the documents, in the order they wrote them. "
    "Do not reorder, swap or invent words.\n"
    "- No padding. Leave out filler such as FOR THE SITE, FOR RECORDS, FOR FILING, "
    "FOR YOUR INFORMATION, FOR REFERENCE, AS DISCUSSED, AS REQUESTED.\n"
    "- Only start with UPDATED when the email itself says the documents are updated, revised or "
    "amended. A revision letter or number in a file name (P02, Rev B) is not a reason to add it.\n"
    "- Describe the documents only, never their status: no IS READY, ATTACHED, UPLOADED, "
    "AVAILABLE, HAS BEEN SENT.\n"
    "- Only add a purpose when the email gives a real one, such as FOR BUILDER QUOTES, "
    "FOR SUBMISSION, FOR PLANNING, FOR COMMENT or FOR APPROVAL.\n"
    "- No dates, job numbers, or names of people or companies.\n"
    "Reply with the description only."
)

# Worked examples used until your own filings take over (subject, email, files, answer).
LLM_STYLE_EXAMPLES = [
    ("", "Please find attached the existing drawings for your information.",
     ["2601_01_EXISTING PLANS_F01.pdf", "2601_02_EXISTING ELEVATIONS_F01.pdf"], "EXISTING DRAWINGS"),
    ("", "Dear Agent, attached is the validation letter for the above application.",
     ["Validation letter.pdf"], "PLANNING VALIDATION LETTER"),
    ("", "Please find attached the updated plans for builder quotes.",
     ["2601_22_PROPOSED PLANS_P02.pdf"], "UPDATED PLANS FOR BUILDER QUOTES"),
    ("", "Please find attached the proposed elevations for your comment.",
     ["2601_23_PROPOSED ELEVATIONS_P03.pdf"], "PROPOSED ELEVATIONS FOR COMMENT"),
    ("", "See attached SAP calculations and EPC as requested.",
     ["SAP calcs.pdf", "EPC.pdf"], "SAP CALCULATIONS AND EPC"),
    ("", "Quote attached for the steel, let me know if you want to go ahead.",
     ["Q4471.pdf"], "STEEL QUOTE"),
    ("", "Please find the location plan and site plan attached, ready for submission.",
     ["2601_00_LOCATION PLAN_PL01.pdf", "2601_05_SITE PLAN_PL01.pdf"],
     "LOCATION PLAN AND SITE PLAN FOR SUBMISSION"),
]

LLM_FILLER = re.compile(r"(?:^|\s+)(?:FOR|AS)\s+(?:THE\s+SITE|(?:YOUR\s+)?RECORDS?|FILING|(?:YOUR\s+)?INFO(?:RMATION)?|"
                        r"(?:YOUR\s+)?REFERENCE|DISCUSSED|REQUESTED)$")


def llm_user_text(subject, text, files, limit=700, pages=None):
    """What the model is shown for one email (the same shape for examples and the real thing).
    pages = {PDF name: the text on its first page}."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + " …"
    out = f"Subject: {subject or '-'}\nEmail: {text}\nFiles: {', '.join(files) or '-'}"
    for name, page in (pages or {}).items():
        out += f"\nPage 1 of {name}: {page}"
    return out


LLM_FROZEN = LLM_CACHE / "examples.json"   # the worked examples in use; kept until you refresh them


def llm_examples():
    """The worked examples shown to the model. Chosen once and kept (examples.json),
    so the model never has to reread them after a session's filings; refresh them
    with:  python3 fileuzi_rename.py --refresh-examples"""
    try:
        frozen = json.loads(LLM_FROZEN.read_text())
        if frozen:
            return [tuple(e) for e in frozen]
    except (OSError, ValueError):
        pass
    ex = llm_examples_fresh()
    try:
        LLM_CACHE.mkdir(parents=True, exist_ok=True)
        LLM_FROZEN.write_text(json.dumps(ex, indent=1))
    except OSError:
        pass
    return ex


def refresh_examples():
    """--refresh-examples: pick the worked examples again from your latest filings."""
    old = len(llm_examples())
    ex = llm_examples_fresh()
    LLM_CACHE.mkdir(parents=True, exist_ok=True)
    LLM_FROZEN.write_text(json.dumps(ex, indent=1))
    style = {e[3] for e in LLM_STYLE_EXAMPLES}
    mine = sum(1 for e in ex if e[3] not in style)
    print(f"Worked examples refreshed: {len(ex)} ({mine} from your own filings, was {old} in total).")
    print("The next session reads them once (10-25 s on the N150), then they're saved again.")
    for subject, text, files, answer in ex:
        print(f"  {answer}")


def llm_examples_fresh():
    """Your most recent email filings (what you actually filed), topped up with the style examples."""
    rows = []
    try:
        if examples_path().exists():
            import sqlite3
            with Waited("reading worked examples from the examples database"):
                try:
                    con = sqlite3.connect(f"file:{examples_path()}?mode=ro", uri=True, timeout=3)
                    con.execute("SELECT 1 FROM filings LIMIT 1").fetchall()
                except sqlite3.OperationalError:
                    con = sqlite3.connect(f"file:{examples_path()}?mode=ro&nolock=1", uri=True, timeout=3)
            rows = con.execute(
                "SELECT subject, COALESCE(email_text, source_block), files, final FROM filings "
                "WHERE kind='email' AND COALESCE(final,'') != '' "
                "AND COALESCE(email_text, source_block, '') != '' ORDER BY id DESC LIMIT ?",
                (LLM_EXAMPLES,)).fetchall()
            con.close()
    except Exception:
        rows = []
    ex = []
    for subject, text, files, final in reversed(rows):   # oldest first, newest nearest the email
        try:
            files = json.loads(files or "[]")
        except Exception:
            files = []
        ex.append((subject, text, files, final.upper()))
    for e in LLM_STYLE_EXAMPLES:
        if len(ex) >= LLM_EXAMPLES:
            break
        ex.insert(0, e)
    return ex


def llm_messages(examples, user=None):
    msgs = [{"role": "system", "content": LLM_SYSTEM}]
    for subject, text, files, answer in examples:
        msgs += [{"role": "user", "content": llm_user_text(subject, text, files, limit=350)},
                 {"role": "assistant", "content": answer}]
    if user is not None:
        msgs.append({"role": "user", "content": user})
    return msgs


def llm_tidy(out):
    """Model reply -> a folder description, or '' if it isn't one."""
    out = re.sub(r"<think>.*?</think>", "", out or "", flags=re.S).strip()
    out = out.splitlines()[0] if out else ""
    out = re.sub(r"^(?:description|answer)\s*:\s*", "", out, flags=re.I)
    out = clean(re.sub(r"[^A-Za-z0-9 &'-]", " ", out)).replace("'", "")
    while LLM_FILLER.search(out):
        out = LLM_FILLER.sub("", out).strip()
    return out if 0 < len(out.split()) <= 12 else ""


def llm_worker():
    """Child process inside bubblewrap: starts llama-server on the sandbox's own
    loopback (unreachable from outside, and it can't reach out), then answers
    one JSON line per request on stdin/stdout."""
    import http.client, socket, time, hashlib
    try:                                               # refuse to run with a real network
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        if s.connect_ex(("1.1.1.1", 443)) == 0:
            print(json.dumps({"ready": False, "error": "network reachable: not sandboxed"}), flush=True)
            return
        s.close()
    except OSError:
        pass
    for k in ("HF_HUB_OFFLINE", "DO_NOT_TRACK"):
        os.environ[k] = "1"
    cfg = json.loads(sys.stdin.readline())
    port = 8089
    proc = subprocess.Popen([cfg["server"], "-m", cfg["model"], "--host", "127.0.0.1", "--port", str(port),
                             "-t", str(cfg["threads"]), "-c", "4096", "-np", "1",
                             "--slot-save-path", cfg["cache"], "--no-webui"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            preexec_fn=worker_manners)         # the panel comes first

    def call(method, path, body=None, timeout=300):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Content-Type": "application/json"})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, (json.loads(data) if data else {})

    for _ in range(240):                               # loading the model
        if proc.poll() is not None:
            break
        try:
            if call("GET", "/health", timeout=2)[0] == 200:
                break
        except OSError:
            pass
        time.sleep(0.5)
    else:
        proc.kill()
    if proc.poll() is not None:
        print(json.dumps({"ready": False, "error": "llama-server didn't start"}), flush=True)
        return

    bos = (call("POST", "/tokenize", {"content": "", "add_special": True})[1].get("tokens") or [None])[0]

    def tokens(messages):
        text = call("POST", "/apply-template", {"messages": messages})[1]["prompt"]
        t = call("POST", "/tokenize", {"content": text, "add_special": False, "parse_special": True})[1]["tokens"]
        return ([bos] if bos is not None and (not t or t[0] != bos) else []) + t

    examples = cfg["examples"]
    # The shared part = the tokens two different emails have in common, minus a few at the
    # join (so a real email can never tokenise differently there). Exact match matters:
    # this model can't step back through what it has read, so a mismatch means rereading it all.
    ta, tb = (tokens(llm_messages(examples, u)) for u in ("\x01 one", "\x02 two"))
    n = 0
    while n < min(len(ta), len(tb)) and ta[n] == tb[n]:
        n += 1
    prefix = ta[:max(n - 4, 1)]
    ident = f"{cfg['model']}|{os.path.getsize(cfg['model'])}|{prefix}"
    fname = "prefix-" + hashlib.sha1(ident.encode()).hexdigest()[:16] + ".bin"
    saved = False
    try:
        st, r = call("POST", "/slots/0?action=restore", {"filename": fname})
        saved = st == 200 and r.get("n_restored") == len(prefix)
    except Exception:
        saved = False
    t0 = time.time()
    if not saved:                                      # first time with these examples: read them once
        call("POST", "/completion", {"prompt": prefix, "n_predict": 0, "id_slot": 0, "cache_prompt": True})
        try:
            saved = call("POST", "/slots/0?action=save", {"filename": fname})[0] == 200
        except Exception:
            saved = False
        for old in Path(cfg["cache"]).glob("prefix-*.bin"):
            if old.name != fname:
                try:
                    old.unlink()
                except OSError:
                    pass
    print(json.dumps({"ready": True, "examples": len(examples), "prefix_tokens": len(prefix),
                      "warmup_s": round(time.time() - t0, 1)}), flush=True)

    for line in sys.stdin:
        try:
            req = json.loads(line)
            t0 = time.time()
            toks = tokens(llm_messages(examples, req["user"]))
            matched = toks[:len(prefix)] == prefix
            restored = False
            if saved and matched:                      # back to 'examples read, nothing else'
                st, rr = call("POST", "/slots/0?action=restore", {"filename": fname})
                restored = st == 200 and rr.get("n_restored") == len(prefix)
            st, r = call("POST", "/completion", {
                "prompt": toks, "n_predict": 24, "temperature": 0, "id_slot": 0, "cache_prompt": True,
                "stop": ["\n"]})
            tm = r.get("timings") or {}
            print(json.dumps({"text": r.get("content", ""), "secs": round(time.time() - t0, 2),
                              "read": tm.get("prompt_n"), "read_ms": round(tm.get("prompt_ms") or 0),
                              "write_ms": round(tm.get("predicted_ms") or 0), "tokens": len(toks),
                              "matched": matched, "restored": restored}), flush=True)
        except Exception as e:
            print(json.dumps({"text": "", "error": repr(e)}), flush=True)
    proc.terminate()


class LLMClient:
    """The description writer in a bubblewrap sandbox: email text in, one line out."""

    def __init__(self, model=None, examples=None):
        model = Path(model or LLM_MODEL).expanduser()
        server = Path(LLM_SERVER_BIN).expanduser()
        LLM_CACHE.mkdir(parents=True, exist_ok=True)
        cmd, kind = sandbox_cmd("--llm-worker", ro=[server.parent.parent, model.parent], rw=[LLM_CACHE])
        if kind != "bubblewrap":
            raise RuntimeError("bubblewrap isn't available, so the language model isn't used")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.examples = examples if examples is not None else llm_examples()
        self.proc.stdin.write(json.dumps({"server": str(server), "model": str(model), "threads": LLM_THREADS,
                                          "cache": str(LLM_CACHE), "examples": self.examples}) + "\n")
        self.proc.stdin.flush()
        self.info = json.loads(self.proc.stdout.readline() or "{}")
        if self.info.get("ready") is not True:
            self.proc.kill()
            raise RuntimeError(self.info.get("error", "the language model didn't start"))

    def ask(self, subject, text, files, pages=None):
        with MODEL_LOCK:                                   # one model at a time
            self.proc.stdin.write(json.dumps({"user": llm_user_text(subject, text, files, pages=pages)}) + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("the language model stopped")
        reply = json.loads(line)
        reply["desc"] = llm_tidy(reply.get("text"))
        try:                                           # numbers only, no email text
            with open(LLM_CACHE / "timing.log", "a") as log:
                log.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {reply.get('secs')}s  read {reply.get('read')}"
                          f"/{reply.get('tokens')} tokens  matched={reply.get('matched')} "
                          f"restored={reply.get('restored')}\n")
        except OSError:
            pass
        return reply

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(5)
        except Exception:
            self.proc.kill()


DEBUG_LOG = LLM_CACHE / "debug.log"     # slow steps (over 2 s) and errors, step names only


class Waited:
    """with Waited("writing to the examples database"): ...
    Logs to debug.log when the step takes over 2 seconds or fails, so a hidden
    wait (a lock, a timeout, a slow network folder) shows up by name."""

    def __init__(self, label, limit=2.0):
        import time
        self.label, self.limit, self.time = label, limit, time.time

    def __enter__(self):
        self.t0 = self.time()
        return self

    def __exit__(self, kind, err, tb):
        took = self.time() - self.t0
        if took >= self.limit or kind:
            note = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {took:5.1f}s  {self.label}"
            if kind:
                note += f"  FAILED: {kind.__name__}: {err}"
            try:
                LLM_CACHE.mkdir(parents=True, exist_ok=True)
                with open(DEBUG_LOG, "a") as log:
                    log.write(note + "\n")
            except OSError:
                pass
        return False


class StageTimer:
    """Wraps a status callback and times each step ('Checking images', 'Writing
    the description' ...). Written to timing.log as numbers and step names only."""

    def __init__(self, status=lambda msg: None, label=""):
        import time
        self.time, self.status, self.label = time.time, status, label
        self.steps, self.name, self.t = [], None, self.time()

    def __call__(self, msg):
        now = self.time()
        if self.name:
            self.steps.append((self.name, now - self.t))
        self.name, self.t = msg, now
        self.status(msg)

    def done(self):
        self("")
        total = sum(t for _, t in self.steps)
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {total:5.1f}s total  " + "  ".join(
            f"{n.split(' (')[0][:40]}: {t:.1f}s" for n, t in self.steps if t >= 0.05)
        try:
            LLM_CACHE.mkdir(parents=True, exist_ok=True)
            with open(LLM_CACHE / "timing.log", "a") as log:
                log.write(line + "\n")
        except OSError:
            pass
        return total


def time_email(args):
    """python3 fileuzi_rename.py --time-email FILE.eml   how long each step of reading it takes"""
    get_llm()                                          # (start-up isn't counted)
    for a in args:
        st = StageTimer()
        plan = plan_email(Path(a), st)
        total = st.done()
        print(f"\n{Path(a).name}: {total:.1f}s")
        for n, t in st.steps:
            print(f"  {t:5.1f}s  {n}")
        drop_staging(plan)


def llm_check():
    """python3 fileuzi_rename.py --llm-check   time the description writer on four sample emails"""
    import time
    t0 = time.time()
    llm = get_llm()
    print(f"Language model: {LLM_STATUS}  (started in {time.time() - t0:.1f}s)")
    if not llm:
        return
    print(f"Shared part: {llm.info['prefix_tokens']} tokens, read in {llm.info['warmup_s']}s"
          + ("  (loaded from the saved copy)" if llm.info["warmup_s"] < 1 else ""))
    samples = [
        ("Re: plans", "Hi all, please find attached the updated plans for builder quotes.", ["2601_22_PROPOSED PLANS_P02.pdf"]),
        ("Survey", "Hi Jake, attached is the topographical survey for the site, as discussed.", ["Survey.pdf"]),
        ("Calcs", "Please see attached the engineer's calculations for the rear extension.", ["Calcs Rev A.pdf"]),
        ("Award", "Attached the party wall award, now signed by both surveyors.", ["PW Award.pdf"]),
    ]
    for subject, text, files in samples:
        r = llm.ask(subject, text, files)
        print(f"  {r['secs']:5.1f}s  read {r.get('read')}/{r.get('tokens')} tokens "
              f"({r.get('read_ms')} ms) + writing {r.get('write_ms')} ms  "
              f"matched={r.get('matched')} restored={r.get('restored')}  {r['desc']}")
    print("Healthy: matched=True restored=True, and 'read' is a couple of hundred tokens, not thousands.")


_llm = "unset"
LLM_STATUS = "not loaded"


_llm_ready = None


def _start_llm():
    import threading
    global _llm, LLM_STATUS
    try:
        client = LLMClient()
        LLM_STATUS = (f"running in bubblewrap ({client.info['examples']} examples, "
                      f"warm-up {client.info['warmup_s']}s)")
        _llm = client
    except Exception as e:
        _llm = None
        LLM_STATUS = f"not used: {e}"
        warn_sandbox(f"The language model didn't start in bubblewrap ({e}); "
                     "descriptions come from the simple rules.")
    finally:
        _llm_ready.set()
    if _llm:
        # bubblewrap's --die-with-parent follows the THREAD that started it, so this
        # thread stays alive (asleep) for as long as FileUzi runs.
        threading.Event().wait()


def get_llm(wait=True):
    """The description writer, or None (switched off / not installed / no bubblewrap /
    still starting when wait=False). It starts in the background on first use, so the
    first emails aren't held up while it loads; they get the rules until it's ready."""
    global _llm, _llm_ready, LLM_STATUS
    if _llm == "unset":
        model, server = Path(LLM_MODEL).expanduser(), Path(LLM_SERVER_BIN).expanduser()
        if not USE_LLM:
            _llm, LLM_STATUS = None, "switched off (USE_LLM)"
        elif not model.is_file() or not server.is_file():
            _llm, LLM_STATUS = None, f"not installed ({model.name if not model.is_file() else server} missing)"
        elif not SANDBOX_MODEL:
            _llm, LLM_STATUS = None, "not used: SANDBOX_MODEL is off"
            warn_sandbox("The language model only runs inside bubblewrap, and the sandbox is switched off, "
                         "so descriptions come from the simple rules.")
        else:
            import threading
            _llm, LLM_STATUS = "starting", "starting"
            _llm_ready = threading.Event()
            threading.Thread(target=_start_llm, daemon=True).start()
    if _llm == "starting":
        if not wait:
            return None
        _llm_ready.wait()
    return _llm


def llm_describe(subject, text, files, pages=None):
    """One description from the model, or None. Never stops filing."""
    llm = get_llm(wait=False)
    if not llm or not (text or files):
        return None
    try:
        return llm.ask(subject, text, files, pages)["desc"] or None
    except Exception as e:
        print(f"Language model skipped: {e!r}", file=sys.stderr)
        return None


def block_network():
    """No internet for this process: nothing it loads can call home.
    Local Unix sockets (desktop plumbing) still work."""
    import socket
    real = socket.socket

    def refuse(*args, **kwargs):
        raise OSError("FileUzi rename: network disabled (no telemetry)")

    class NoInternet(real):
        def connect(self, address):
            if self.family == getattr(socket, "AF_UNIX", None):
                return super().connect(address)
            refuse()

        def connect_ex(self, address):
            if self.family == getattr(socket, "AF_UNIX", None):
                return super().connect_ex(address)
            refuse()

    socket.socket = NoInternet
    socket.create_connection = refuse
    socket.getaddrinfo = refuse
    for k, v in {"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"}.items():
        os.environ[k] = v


def main():
    if sys.argv[1:2] == ["--download-model"]:
        return download_model()
    if sys.argv[1:2] == ["--embed-worker"]:
        return embed_worker()
    if sys.argv[1:2] == ["--pdf-server"]:
        return pdf_server()
    if sys.argv[1:2] == ["--pdf-worker"]:
        return pdf_worker()
    if sys.argv[1:2] == ["--vision-worker"]:
        return vision_worker()
    if sys.argv[1:2] == ["--llm-worker"]:
        return llm_worker()
    if sys.argv[1:2] == ["--llm-check"]:
        return llm_check()
    if sys.argv[1:2] == ["--refresh-examples"]:
        return refresh_examples()
    if sys.argv[1:2] == ["--time-email"]:
        return time_email(sys.argv[2:])
    block_network()                                   # everything below is offline
    if sys.argv[1:2] == ["--test"]:
        return test(sys.argv[2:])
    if sys.argv[1:2] == ["--test-image"]:
        return test_image(sys.argv[2:])
    if sys.argv[1:2] == ["--make-mapping"]:
        return make_mapping()
    if sys.argv[1:2] == ["--examples"]:
        return show_examples(sys.argv[2:])
    if sys.argv[1:2] == ["--export-examples"]:
        return export_examples(sys.argv[2:])
    menu = Path(sys.argv[0]).name.upper()
    # Files passes just the selected NAMES and starts the script inside the
    # current folder, so make them full paths or parent folders can't be seen
    paths = [Path(p).absolute() for p in sys.argv[1:]] or [
        Path(p).absolute() for p in os.environ.get("NAUTILUS_SCRIPT_SELECTED_FILE_PATHS", "").splitlines() if p]
    emails = sorted((p for p in paths if p.is_file() and p.suffix.lower() == ".eml"),
                    key=email_sent_time)              # oldest first, as it happened
    folders = [p for p in paths if p.is_dir()]
    if "CHECK" in menu:                               # "Check Drawings" on a project folder
        targets = folders or [Path.cwd()]
        if USE_PANEL and email_panel(targets[:1], ["check"]):
            return
        message("error", "Check Drawings needs the new window: sudo dnf install python3-pyqt6")
        return
    if USE_PANEL and (emails or folders):
        mode = "also" if "ALSO" in menu else "out" if "OUT" in menu else "in"
        items = emails + ([] if "EMAIL" in menu else folders)
        if email_panel(items, ["email"] * len(emails) + [mode] * (len(items) - len(emails))):
            return                                    # the floating window did them
    for i, eml in enumerate(emails, 1):            # emails: one at a time, any menu item
        try:
            process_email(eml, i, len(emails))
        except Exception:
            show_crash(eml)
    if "EMAIL" in menu:                           # "File Emails": emails only
        if not emails:
            message("error", "Select one or more .eml emails first.")
        return
    if not folders and not emails:
        message("error", "Select one or more folders or .eml emails first.")
    for folder in folders:
        try:
            if "ALSO" in menu:                    # "Also File To"
                file_also_only(folder)
            else:                                 # "File IN" / "File OUT"
                rename_one(folder, "OUT" if "OUT" in menu else "IN")
        except Exception:
            show_crash(folder)


USE_PANEL = True        # emails in the floating PyQt6 window (falls back to zenity dialogs)


def email_panel(emails, modes=None):
    """The floating window (fileuzi_panel.py beside this script): emails,
    folders ('in' / 'out' / 'also') or a drawings check ('check'). False if
    PyQt6 isn't installed, so the zenity dialogs are used instead."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import fileuzi_panel
    except ImportError as e:
        print(f"Panel not used ({e}); install with: sudo dnf install python3-pyqt6", file=sys.stderr)
        return False
    try:
        fileuzi_panel.run(sys.modules[__name__], emails, modes)
    except Exception:
        show_crash(emails[0].parent)
    return True


def show_crash(folder):
    """Files hides Python errors, so put any crash on screen (and in a log)."""
    import traceback
    tb = traceback.format_exc()
    log = Path.home() / ".cache" / "fileuzi-rename.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a") as f:
            f.write(f"\n{datetime.now():%Y-%m-%d %H:%M:%S}  {folder}\n{tb}")
    except Exception:
        pass
    subprocess.run(["zenity", "--text-info", "--title", "FileUzi: something went wrong",
                    "--width", "800", "--height", "450", "--font", "monospace 9"],
                   input=f"Folder: {folder}\n\n{tb}\n(Also saved to {log})", text=True)


if __name__ == "__main__":
    main()
