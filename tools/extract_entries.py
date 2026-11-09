"""Extract every PLU entry and its embedded image from the current booklets.

Writes data/entries.csv and image files under data/images/<book>/.
"""
import csv, re, sys
from pathlib import Path
import docx
from docx.oxml.ns import qn
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BOOKS = {"Fruit": "FRUIT_VISUAL_PLU_BOOKLET_PRODUCTION.docx",
         "Vegetable": "VEGETABLE_VISUAL_PLU_BOOKLET_PRODUCTION.docx"}
BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"

def main():
    out = ROOT / "data"; (out / "images").mkdir(parents=True, exist_ok=True)
    rows = []
    for book, fn in BOOKS.items():
        d = docx.Document(ROOT / "current/booklets" / fn)
        # table order follows heading order: map each table to its section heading
        body = d.element.body
        section = None
        for el in body.iterchildren():
            if el.tag == qn("w:p"):
                m = re.match(r"Section \d+: (.+)", "".join(t.text or "" for t in el.iter(qn("w:t"))))
                if m: section = m.group(1)
            elif el.tag == qn("w:tbl") and section:
                for tc in el.iter(qn("w:tc")):
                    txt = ["".join(t.text or "" for t in p.iter(qn("w:t"))) for p in tc.iter(qn("w:p"))]
                    plu = next((re.sub(r"PLU:\s*", "", s).strip() for s in txt if s.startswith("PLU:")), None)
                    if not plu: continue
                    i = txt.index("PLU: " + plu)
                    name = txt[i + 1]
                    get = lambda k: next((s.split(":", 1)[1].strip() for s in txt if s.startswith(k + ":")), "")
                    blip = next(tc.iter(BLIP), None)
                    img = ""
                    if blip is not None:
                        part = d.part.related_parts[blip.get(EMBED)]
                        img = f"images/{book}/{len(rows)+1:04d}_{plu}{Path(part.partname).suffix}"
                        (out / img).parent.mkdir(parents=True, exist_ok=True)
                        (out / img).write_bytes(part.blob)
                    w = h = 0
                    if img:
                        with Image.open(out / img) as im: w, h = im.size
                    rows.append(dict(idx=len(rows)+1, book=book, section=section, plu=plu, name=name,
                        category=get("Category"), variety=get("Variety"), source=get("Image Source"),
                        image=img, width=w, height=h))
    with open(out / "entries.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(len(rows), "entries")

if __name__ == "__main__": main()
