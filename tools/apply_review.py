"""Apply data/review_notes.txt verdicts to the booklets and regenerate image reports.

Run after tools/extract_entries.py. Rewrites each entry's Verification Status line
in current/booklets/*_PRODUCTION.docx (the PDFs must then be re-exported) and writes
data/image_review.csv plus current/reports/{MASTER_IMAGE_LIBRARY,IMAGE_MATCH_REPORT}.csv.
Status rules:
  rejected              -> REJECTED, replacement needed
  AI-generated source   -> AI GENERATED REFERENCE IMAGE (never "verified photo")
  photo, match          -> VERIFIED PHOTO (visually reviewed against the PickList name)
  photo, approximate    -> APPROXIMATE PHOTO MATCH
"""
import copy, csv, hashlib, re
from collections import Counter
from pathlib import Path
import docx
from docx.oxml.ns import qn
from check_image_uniqueness import require_unique_entries

ROOT = Path(__file__).resolve().parents[1]
DATA, REP = ROOT / "data", ROOT / "current/reports"
STATUS = {"verified": "✅ VERIFIED PHOTO", "approx": "⚠ APPROXIMATE PHOTO MATCH",
          "ai": "🤖 AI GENERATED REFERENCE IMAGE", "rejected": "❌ IMAGE REJECTED – REPLACEMENT NEEDED"}
LICENSE = {"AI Generated": "AI generated (internal use)"}
DEFAULT_LICENSE = "Supplied-document image; license not independently verified"
BOOKS = {"Fruit": "FRUIT_VISUAL_PLU_BOOKLET_PRODUCTION.docx", "Vegetable": "VEGETABLE_VISUAL_PLU_BOOKLET_PRODUCTION.docx"}

def load_notes():
    notes = {}
    for line in (DATA / "review_notes.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip(): continue
        i, v, n = line.split("|", 2); notes[int(i)] = (v, n)
    return notes

def status_for(source, verdict):
    if verdict == "r": return STATUS["rejected"]
    if source == "AI Generated": return STATUS["ai"]
    return STATUS["verified"] if verdict == "m" else STATUS["approx"]

def main():
    notes = load_notes()
    rows = list(csv.DictReader(open(DATA / "entries.csv", encoding="utf-8")))
    require_unique_entries(rows, DATA)
    hashes = {r["idx"]: hashlib.md5((DATA / r["image"]).read_bytes()).hexdigest() for r in rows}
    reuse = Counter(hashes.values())
    for r in rows:
        v, n = notes[int(r["idx"])]
        r.update(verdict={"m": "Approved", "a": "Approximate", "r": "Rejected"}[v], note=n,
                 status=status_for(r["source"], v), below_500=int(min(int(r["width"]), int(r["height"])) < 500),
                 shared_image_entries=reuse[hashes[r["idx"]]])
    with open(DATA / "image_review.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    by_plu = {}
    for r in rows: by_plu.setdefault((r["book"], r["plu"], r["name"]), r)
    for book, fn in BOOKS.items():
        d = docx.Document(ROOT / "current/booklets" / fn)
        for tc in d.element.body.iter(qn("w:tc")):
            paras = list(tc.iter(qn("w:p")))
            texts = ["".join(t.text or "" for t in p.iter(qn("w:t"))) for p in paras]
            plu = next((t[5:].strip() for t in texts if t.startswith("PLU:")), None)
            if not plu: continue
            name = texts[texts.index("PLU: " + plu) + 1]
            r = by_plu[(book, plu, name)]
            si = next(i for i, t in enumerate(texts) if t.startswith("Verification Status:"))
            ci = next(i for i, t in enumerate(texts) if t.startswith("Category:"))
            for p in paras[si + 1:]:
                if "Review note:" in "".join(t.text or "" for t in p.iter(qn("w:t"))): p.getparent().remove(p)
            def clone(text, color=None, bold=False):
                new = copy.deepcopy(paras[ci])  # Category paragraph carries the cell's centered small-text styling
                ts = list(new.iter(qn("w:t"))); ts[0].text = text
                for t in ts[1:]: t.text = ""
                rpr = next(new.iter(qn("w:rPr")))
                for el in list(rpr):
                    if el.tag in (qn("w:color"), qn("w:b")): rpr.remove(el)
                if bold: rpr.append(rpr.makeelement(qn("w:b"), {}))
                if color: rpr.append(rpr.makeelement(qn("w:color"), {qn("w:val"): color}))
                return new
            colors = {"Approved": "2E7D32", "Approximate": "B45F06", "Rejected": "C00000"}
            if r["source"] == "AI Generated" and r["verdict"] != "Rejected": colors["Approved"] = colors["Approximate"] = "5B5B5B"
            st = clone("Verification Status: " + r["status"], colors[r["verdict"]], True)
            paras[si].addnext(st); paras[si].getparent().remove(paras[si])
            if r["verdict"] != "Approved": st.addnext(clone("Review note: " + r["note"]))
        d.save(ROOT / "current/booklets" / fn)

    def w(path, header, out):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            cw = csv.writer(f); cw.writerow(header); cw.writerows(out)
    w(REP / "MASTER_IMAGE_LIBRARY.csv", ["PLU", "Product", "Image File", "Image Source", "License", "Verification Status", "Width", "Height"],
      [[r["plu"], r["name"], f'data/{r["image"]}', r["source"], LICENSE.get(r["source"], DEFAULT_LICENSE),
        r["status"], r["width"], r["height"]] for r in rows])
    def conf(r): return {"Approved": "Medium", "Approximate": "Low", "Rejected": "None"}[r["verdict"]]
    w(REP / "IMAGE_MATCH_REPORT.csv", ["PLU", "Product", "Assigned Image", "Source", "Confidence", "Review Result", "Notes"],
      [[r["plu"], r["name"], f'data/{r["image"]}', r["source"], conf(r), r["verdict"],
        "; ".join(x for x in [r["note"], "below 500 px minimum" if r["below_500"] else "",
                              f'image shared by {r["shared_image_entries"]} entries' if r["shared_image_entries"] > 1 else ""] if x)] for r in rows])
    c = Counter(r["verdict"] for r in rows)
    print(dict(c), "AI:", sum(r["source"] == "AI Generated" for r in rows), "below500:", sum(r["below_500"] for r in rows))

if __name__ == "__main__": main()

def update_workbook():
    import openpyxl
    p = REP / "BOOKLET_AUDIT_REPORT.xlsx"; wb = openpyxl.load_workbook(p)
    for name in ("Image Review", "Rejected Images", "Review Summary"):
        if name in wb.sheetnames: del wb[name]
    rows = list(csv.DictReader(open(DATA / "image_review.csv", encoding="utf-8-sig")))
    cols = ["idx", "book", "section", "plu", "name", "source", "width", "height", "verdict", "status", "note", "shared_image_entries"]
    for name, sel in (("Image Review", rows), ("Rejected Images", [r for r in rows if r["verdict"] == "Rejected"])):
        ws = wb.create_sheet(name); ws.append(["Entry #", "Book", "Section", "PLU", "Product", "Image Source", "Width", "Height",
                                              "Review Result", "Booklet Status", "Reviewer Note", "Entries Sharing Image"])
        for r in sel: ws.append([int(r[c]) if c in ("idx", "width", "height", "shared_image_entries") else r[c] for c in cols])
        ws.freeze_panes = "A2"
    ws = wb.create_sheet("Review Summary"); c = Counter(r["verdict"] for r in rows)
    for k, v in [("Entries reviewed", len(rows)), ("Approved (visual match)", c["Approved"]), ("Approximate", c["Approximate"]),
                 ("Rejected (replacement needed)", c["Rejected"]),
                 ("AI-generated images", sum(r["source"] == "AI Generated" for r in rows)),
                 ("Photographic coverage (non-AI)", f'{sum(r["source"] != "AI Generated" for r in rows)/len(rows):.1%}'),
                 ("Images below 500 px", sum(r["below_500"] == "1" for r in rows))]: ws.append([k, v])
    wb.save(p)

if __name__ == "__main__": update_workbook()
