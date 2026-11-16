#!/usr/bin/env python3
"""
Model ability test for FileUzi descriptions.

Runs each .gguf model over the same set of emails and scores the one-line
description it writes against the answer you would file. Writes an HTML
report and opens it.

It uses the real writer from fileuzi_rename.py: the same instructions, the
same worked examples (your newest filings), the same bubblewrap sandbox.

Test emails come from two places:
  1. Your older filings in filing_examples.db (the newest are the examples,
     so they aren't tested).
  2. Twelve built-in practice emails with known answers.

Usage (from the tools folder, beside fileuzi_rename.py):
  python3 model_ability_test.py
  python3 model_ability_test.py --models ~/models/*.gguf --n 30
"""
import argparse, html, json, re, sqlite3, sys, webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fileuzi_rename as fz           # the real writer: same prompt, same sandbox, same cache

# Practice emails with known answers (scored).
BUILT_IN_TESTS = [
    ("Builder quotes", "Hi all, please find attached the updated plans for builder quotes. Any questions let me know.",
     ["2601_22_PROPOSED PLANS_P02.pdf"], "UPDATED PLANS FOR BUILDER QUOTES"),
    ("Survey", "Hi Jake, attached is the topographical survey for the site, as discussed on the phone.",
     ["Survey.dwg", "Survey.pdf"], "TOPOGRAPHICAL SURVEY"),
    ("Calcs", "Please see attached the structural engineer's calculations for the rear extension.",
     ["24-118 Calcs Rev A.pdf"], "STRUCTURAL CALCULATIONS FOR REAR EXTENSION"),
    ("Decision", "Dear Sir/Madam, please find attached the decision notice for the above application.",
     ["DM_24_1234 Decision.pdf"], "DECISION NOTICE"),
    ("Photos", "Here are the photos from this morning's site visit, the lintel is in.",
     ["IMG_4410.jpg", "IMG_4411.jpg", "IMG_4412.jpg"], "SITE VISIT PHOTOS"),
    ("Fee", "Following our meeting, I attach our fee proposal for the loft conversion.",
     ["Fee proposal.pdf"], "FEE PROPOSAL FOR LOFT CONVERSION"),
    ("BC approval", "Please find enclosed the building control approval and conditions.",
     ["Approval notice.pdf"], "BUILDING CONTROL APPROVAL AND CONDITIONS"),
    ("Messy client", "Hi Jake, hope you're well. Sorry for the delay, the kids have been ill. We've had a "
     "think and I've marked up the plans with our comments, see attached. The kitchen supplier's layout "
     "is in there too. Speak soon.",
     ["Plans marked up.pdf", "Kitchen layout v3.pdf"], "MARKED UP PLANS AND KITCHEN LAYOUT"),
    ("Party wall", "Attached the party wall award, now signed by both surveyors.",
     ["PW Award signed.pdf"], "SIGNED PARTY WALL AWARD"),
    ("Windows", "Please find attached the revised window schedule.",
     ["2601_40_WINDOW SCHEDULE_W03.pdf"], "REVISED WINDOW SCHEDULE"),
    ("Asbestos", "Asbestos report attached for your records.",
     ["R-2231 Asbestos survey.pdf"], "ASBESTOS REPORT"),
    ("Tender", "Here's the tender return from the builder, plus their programme.",
     ["Tender return.pdf", "Programme.xlsx"], "TENDER RETURN AND PROGRAMME"),
]


def words(s):
    return [w for w in re.findall(r"[A-Z0-9]+", (s or "").upper()) if w not in {"THE", "A", "AN", "OF"}]


def score(got, want):
    """Word overlap (F1): 1.0 = same words, 0 = nothing in common."""
    g, w = words(got), words(want)
    if not g or not w:
        return 0.0
    common = sum(min(g.count(x), w.count(x)) for x in set(g))
    if not common:
        return 0.0
    p, r = common / len(g), common / len(w)
    return 2 * p * r / (p + r)


def load_db(n):
    """Your older filings: the newest ones are the model's examples, so they aren't tested."""
    path = fz.examples_path()
    if not path.exists():
        return []
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM filings WHERE kind='email' AND COALESCE(final,'') != '' "
        "AND COALESCE(email_text, source_block, '') != '' ORDER BY id DESC LIMIT ? OFFSET ?",
        (n, fz.LLM_EXAMPLES)).fetchall()
    con.close()
    out = []
    for r in rows:
        try:
            files = json.loads(r["files"] or "[]")
        except Exception:
            files = []
        out.append({"label": (r["subject"] or "")[:40] or f"Filing {r['id']}", "subject": r["subject"],
                    "text": r["email_text"] or r["source_block"] or "", "files": files,
                    "want": r["final"].upper(), "rules": (r["suggested"] or "").upper(), "from": "yours"})
    return out


def build_tests(db_rows):
    tests = list(db_rows)
    for label, text, files, want in BUILT_IN_TESTS:
        tests.append({"label": label, "subject": "", "text": text, "files": files, "want": want,
                      "rules": (fz.attached_phrase(text) or "").upper(), "from": "built-in"})
    return tests


def run_model(model, tests):
    name = Path(model).name
    print(f"\n=== {name}")
    try:
        client = fz.LLMClient(model=model)
    except Exception as e:
        print(f"  didn't start: {e}")
        return name, None, None
    info = client.info
    print(f"  {info['examples']} examples, {info['prefix_tokens']} tokens, read in {info['warmup_s']}s"
          + (" (saved from last time)" if info["warmup_s"] < 1 else ""))
    results = []
    try:
        for i, t in enumerate(tests, 1):
            try:
                r = client.ask(t["subject"], t["text"], t["files"])
                got, secs = r["desc"] or "(rejected: " + (r.get("text") or "").strip()[:40] + ")", r["secs"]
            except Exception as e:
                got, secs = f"(error: {e})", 0.0
            s = score(got, t["want"])
            results.append({"got": got, "secs": secs, "score": s})
            print(f"  {i:>2}/{len(tests)}  {secs:5.1f}s  {s:4.2f}  {got}")
    finally:
        client.close()
    return name, results, info


def colour(s):
    if s >= 0.99: return "#d9f2dd"
    if s >= 0.6:  return "#eef6d5"
    if s >= 0.3:  return "#fbefd2"
    return "#f8dcdc"


def report(tests, runs, path):
    runs = [(n, r) for n, r, _ in runs]
    e = html.escape
    rules_scores = [score(t["rules"], t["want"]) for t in tests]
    head = "".join(f"<th>{e(n)}</th>" for n, _ in runs)
    summary = ["<tr><td>Rules (today)</td>"
               f"<td>{sum(rules_scores)/len(tests):.2f}</td>"
               f"<td>{sum(s >= 0.99 for s in rules_scores)}/{len(tests)}</td><td>instant</td></tr>"]
    for n, res in runs:
        if not res:
            summary.append(f"<tr><td>{e(n)}</td><td colspan=3>did not run</td></tr>")
            continue
        sc = [r["score"] for r in res]
        secs = [r["secs"] for r in res]
        summary.append(f"<tr><td>{e(n)}</td><td>{sum(sc)/len(sc):.2f}</td>"
                       f"<td>{sum(s >= 0.99 for s in sc)}/{len(sc)}</td>"
                       f"<td>{sum(secs)/len(secs):.1f}s each</td></tr>")
    rows = []
    for i, t in enumerate(tests):
        snippet = re.sub(r"\s+", " ", t["text"])[:300]
        cells = [f"<td class=src><b>{e(t['label'])}</b> <i>{e(t['from'])}</i>"
                 f"<div>{e(snippet)}</div>"
                 f"<small>{e(', '.join(t['files'])[:160])}</small></td>",
                 f"<td><b>{e(t['want'])}</b></td>",
                 f"<td style='background:{colour(rules_scores[i])}'>{e(t['rules'] or '-')}</td>"]
        for n, res in runs:
            if res:
                r = res[i]
                cells.append(f"<td style='background:{colour(r['score'])}'>{e(r['got'] or '-')}"
                             f"<small>{r['score']:.2f} · {r['secs']:.1f}s</small></td>")
            else:
                cells.append("<td>-</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    page = f"""<!doctype html><meta charset=utf-8><title>FileUzi model ability test</title>
<style>
body{{font:14px/1.4 'Adwaita Sans','Inter',sans-serif;color:#1C1B33;margin:28px;background:#f6f5fb}}
h1{{font-size:22px;margin:0 0 4px}} p{{color:#6E7090;margin:0 0 18px}}
table{{border-collapse:collapse;background:#fff;margin-bottom:26px}}
th,td{{border:1px solid #e3e1ef;padding:7px 9px;vertical-align:top;text-align:left}}
th{{background:#efedf9;font-weight:600}} td small{{display:block;color:#6E7090;margin-top:3px}}
td.src{{max-width:380px}} td.src div{{margin:3px 0;color:#3b3a55}} i{{color:#6A5AE0;font-style:normal;font-size:12px}}
</style>
<h1>FileUzi model ability test</h1>
<p>Score is word overlap with the answer filed: 1.00 means the same words. Green is a match, red is a miss.
Speed is per email, through the real sandboxed writer.</p>
<table><tr><th>Writer</th><th>Average score</th><th>Exact</th><th>Speed</th></tr>{''.join(summary)}</table>
<table><tr><th>Email</th><th>Answer filed</th><th>Rules (today)</th>{head}</tr>{''.join(rows)}</table>"""
    path.write_text(page, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=[str(Path(fz.LLM_MODEL).expanduser())])
    ap.add_argument("--server", default=fz.LLM_SERVER_BIN)
    ap.add_argument("--db", help="filing_examples.db (default: beside fileuzi_rename.py)")
    ap.add_argument("--n", type=int, default=20, help="how many of your older filings to test")
    a = ap.parse_args()
    fz.LLM_SERVER_BIN = a.server
    if a.db:
        fz.EXAMPLES_DB = a.db
    if not Path(a.server).expanduser().exists():
        sys.exit(f"llama-server not found at {a.server} (use --server)")

    db_rows = load_db(a.n)
    tests = build_tests(db_rows)
    print(f"Examples from {fz.examples_path()}\n{len(db_rows)} of your filings + "
          f"{len(BUILT_IN_TESTS)} built-in emails, {len(a.models)} model(s)")
    runs = [run_model(m, tests) for m in a.models]
    out = HERE / "model_test_report.html"
    report(tests, runs, out)
    print(f"\nReport: {out}")
    try:
        webbrowser.open(out.as_uri())
    except Exception:
        pass


if __name__ == "__main__":
    main()
