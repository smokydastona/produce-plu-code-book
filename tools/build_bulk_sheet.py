"""Lay out the original binder's Bulk records as six themed print pages."""
import io
import math
from collections import Counter

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.pagebreak import Break

TITLE = "BULK PLU QUICK GUIDE"
PAGE_CATEGORIES = (
    ("Candy",),
    ("Chocolate/Yogurt", "Snacking Nuts/Seeds"),
    ("Baking", "Nut Mixes"),
    ("Organics",),
    ("Seasonal Halloween", "Seasonal Christmas", "Seasonal Valentines", "Seasonal Easter"),
    ("Dried Fruit", "Mealtime", "Wrapped Candy/Chocolate"),
)
BASES = (1, 4, 7)


def read_bulk(sheet):
    themed = sheet["A1"].value == TITLE
    bases = BASES if themed else (2, 5, 8)
    starts = [1 if themed else 4, *(b.id + 1 for b in sheet.row_breaks.brk if b.man)]
    expected = {category for page in PAGE_CATEGORIES for category in page}
    columns = {column for base in bases for column in (base, base + 1)}
    for row in sheet:
        if any(cell.value is not None and cell.column not in columns for cell in row):
            raise ValueError("Bulk contains data outside its Product/PLU columns")
    sections = []
    for start, end in zip(starts, starts[1:] + [sheet.max_row + 1]):
        for base in bases:
            category = None
            for row in range(start, end):
                name, code = sheet.cell(row, base).value, sheet.cell(row, base + 1).value
                if name is not None and code is None:
                    if name in {TITLE, "PRODUCT"} or (themed and row == start + 1 and base == 1):
                        continue
                    if name not in expected:
                        raise ValueError("Bulk categories have changed; review the six-page grouping")
                    category = name
                    continue
                if not themed and name is None and code is None:
                    for left in reversed([col for col in bases if col < base]):
                        heading = sheet.cell(row, left).value
                        if heading is not None and sheet.cell(row, left + 1).value is None:
                            category = heading
                            break
                if code is None:
                    continue
                if name == "PRODUCT" and code == "PLU":
                    continue
                if category is None or not isinstance(name, str) or not name.strip():
                    raise ValueError(f"Bulk: missing product/category at {sheet.cell(row, base).coordinate}")
                if sheet.cell(row, base).data_type == "f" or sheet.cell(row, base + 1).data_type == "f":
                    raise ValueError("Bulk formulas require manual review")
                sections.append(dict(category=category, product=name, plu=str(code),
                                     source_product_cell=sheet.cell(row, base).coordinate,
                                     source_code_cell=sheet.cell(row, base + 1).coordinate))
    if {entry["category"] for entry in sections} != expected:
        raise ValueError("Bulk categories have changed; review the six-page grouping")
    return sections


def bulk_sheet(entries):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Bulk"
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A4"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_LETTER
    sheet.page_setup.scale = 100
    sheet.sheet_properties.pageSetUpPr.fitToPage = False
    sheet.page_margins = PageMargins(left=.3, right=.3, top=.3, bottom=.3, header=.1, footer=.1)
    sheet.print_options.horizontalCentered = True
    sheet.oddFooter.center.text = "Bulk | Page &P of &N"
    sheet.oddFooter.center.size = 8
    sheet.oddFooter.center.font = "DejaVu Sans"
    for base in BASES:
        sheet.column_dimensions[sheet.cell(1, base).column_letter].width = 26
        sheet.column_dimensions[sheet.cell(1, base + 1).column_letter].width = 7
    for column in ("C", "F"):
        sheet.column_dimensions[column].width = 1.5
    coordinates = []
    start = 1
    for page, categories in enumerate(PAGE_CATEGORIES, 1):
        selected = [entry for category in categories for entry in entries if entry["category"] == category]
        # Partition in source/category order; repeat category headings after a column break.
        def column_lines(group):
            lines = []
            category = None
            for entry in group:
                if entry["category"] != category:
                    category = entry["category"]
                    lines.append((category, None, 16))
                height = 16 * max(1, math.ceil(len(entry["product"]) / 29))
                lines.append((None, entry, height))
            return lines

        best = None
        for first in range(1, len(selected) - 1):
            for second in range(first + 1, len(selected)):
                columns = [column_lines(group) for group in
                           (selected[:first], selected[first:second], selected[second:])]
                heights = [sum(line[2] for line in column) for column in columns]
                score = (max(heights), max(heights) - min(heights))
                if best is None or score < best[0]:
                    best = (score, columns)
        if best is None or best[0][0] > 512:
            raise ValueError(f"Bulk page {page} no longer fits at 11 pt; review its category grouping")
        columns = best[1]
        if page > 1:
            sheet.row_breaks.append(Break(id=start - 1))
        sheet.merge_cells(start_row=start, start_column=1, end_row=start, end_column=8)
        sheet.cell(start, 1, TITLE).font = Font(name="DejaVu Sans", size=14, bold=True)
        sheet.row_dimensions[start].height = 24
        sheet.merge_cells(start_row=start + 1, start_column=1, end_row=start + 1, end_column=8)
        sheet.cell(start + 1, 1, " / ".join(categories)).font = Font(name="DejaVu Sans", size=10)
        sheet.row_dimensions[start + 1].height = 20
        for base in BASES:
            for offset, text in enumerate(("PRODUCT", "PLU")):
                cell = sheet.cell(start + 2, base + offset, text)
                cell.font = Font(name="DejaVu Sans", size=10, bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="305040")
        sheet.row_dimensions[start + 2].height = 20
        for base, lines in zip(BASES, columns):
            row = start + 3
            for category, entry, height in lines:
                units = height // 16
                for number in range(row, row + units):
                    sheet.row_dimensions[number].height = 16
                if category:
                    sheet.merge_cells(start_row=row, start_column=base, end_row=row, end_column=base + 1)
                    cell = sheet.cell(row, base, category)
                    cell.font = Font(name="DejaVu Sans", size=11, bold=True)
                    cell.fill = PatternFill("solid", fgColor="DCE6DA")
                    cell.alignment = Alignment(vertical="center")
                    row += units
                    continue
                for column, value in ((base, entry["product"]), (base + 1, entry["plu"])):
                    if units > 1:
                        sheet.merge_cells(start_row=row, start_column=column,
                                          end_row=row + units - 1, end_column=column)
                    cell = sheet.cell(row, column, value)
                    cell.data_type = "s"
                    cell.number_format = "@"
                    cell.font = Font(name="DejaVu Sans", size=11, bold=column == base + 1)
                    cell.alignment = Alignment(vertical="center", wrap_text=True,
                                               horizontal="left" if column == base else "center")
                    cell.border = Border(bottom=Side(style="hair", color="D0D0D0"))
                coordinates.append(dict(entry, product_cell=sheet.cell(row, base).coordinate,
                                        code_cell=sheet.cell(row, base + 1).coordinate, page=page))
                row += units
        page_end = start + 2 + max(sum(line[2] // 16 for line in column) for column in columns)
        height = sum(sheet.row_dimensions[row].height for row in range(start, page_end + 1))
        if height > 568:
            raise ValueError(f"Bulk page {page} exceeds landscape Letter height")
        start = page_end + 1
    sheet.print_area = f"A1:H{start - 1}"
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue(), coordinates


def validate_bulk(sheet, coordinates):
    if len(sheet.row_breaks.brk) != 5 or sheet.page_setup.scale != 100:
        raise ValueError("Bulk must have six unscaled print pages")
    for entry in coordinates:
        for key, value in (("product_cell", entry["product"]), ("code_cell", entry["plu"])):
            cell = sheet[entry[key]]
            if cell.value != value or cell.data_type != "s" or cell.font.sz != 11:
                raise ValueError(f"Bulk value/font changed at {entry[key]}")
    if Counter((entry["category"], entry["product"], entry["plu"]) for entry in read_bulk(sheet)) != Counter(
            (entry["category"], entry["product"], entry["plu"]) for entry in coordinates):
        raise ValueError("Bulk records missing or duplicated")
