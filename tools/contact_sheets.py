"""Build labelled contact sheets of all entry images for manual review (output in /tmp, not committed)."""
import csv, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/sheets"); OUT.mkdir(exist_ok=True, parents=True)
COLS, ROWS, CELL, LAB = 6, 4, 250, 46
rows = list(csv.DictReader(open(ROOT / "data/entries.csv", encoding="utf-8")))
try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
except OSError: font = ImageFont.load_default()
per = COLS * ROWS
for s in range(0, len(rows), per):
    sheet = Image.new("RGB", (COLS*CELL, ROWS*(CELL+LAB)), "white"); dr = ImageDraw.Draw(sheet)
    for k, r in enumerate(rows[s:s+per]):
        x, y = (k % COLS)*CELL, (k // COLS)*(CELL+LAB)
        im = Image.open(ROOT / "data" / r["image"]).convert("RGB"); im.thumbnail((CELL-6, CELL-6))
        sheet.paste(im, (x+3, y+3))
        dr.text((x+4, y+CELL), f'#{r["idx"]} {r["plu"]}', fill="black", font=font)
        dr.text((x+4, y+CELL+20), r["name"][:30], fill=(180,0,0), font=font)
    sheet.save(OUT / f"sheet-{s//per+1:02d}.jpg", quality=85)
print(len(rows)//per + 1, "sheets")
