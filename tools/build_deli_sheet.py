"""Convert the owner's deli document into two-column Word and Excel sources."""
import argparse
import io
import zipfile
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.page import PageMargins

ROOT = Path(__file__).resolve().parents[1]
DELI_SOURCE = Path("sources/binders/Updated_Deli_Two_Columns.xlsx")


def read_sections(path):
    document = Document(path)
    sections = []
    heading = None
    title = None
    tables = iter(document.tables)
    for element in document.element.body:
        if element.tag == qn("w:p"):
            text = "".join(node.text or "" for node in element.iter(qn("w:t")))
            if text:
                if title is None:
                    title = text
                elif heading is not None:
                    raise ValueError(f"deli heading has no table: {heading}")
                else:
                    heading = text
        elif element.tag == qn("w:tbl"):
            table = next(tables)
            if heading is None or len(table.columns) != 2:
                raise ValueError("each deli category must have one two-column Product/PLU table")
            values = [[cell.text for cell in row.cells] for row in table.rows]
            if values[0] != ["Product", "PLU"] or len(values) < 2:
                raise ValueError(f"invalid deli table header or empty category: {heading}")
            if any(not product or not plu.isascii() or not plu.isdecimal()
                   for product, plu in values[1:]):
                raise ValueError(f"blank product or invalid PLU in deli category: {heading}")
            sections.append((heading, values[1:]))
            heading = None
        elif element.tag != qn("w:sectPr"):
            raise ValueError("unsupported deli document structure")
    if not title or not sections or heading is not None:
        raise ValueError("incomplete deli document")
    return title, sections


def workbook_bytes(title, sections):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Deli"
    sheet.sheet_view.showGridLines = False
    sheet.merge_cells("A1:E1")
    sheet["A1"] = title
    sheet["A1"].data_type = "s"
    sheet["A1"].font = Font(name="Calibri", size=14, bold=True)
    sheet["A1"].alignment = Alignment(horizontal="center")
    sheet.row_dimensions[1].height = 26
    for column, width in (("A", 33), ("B", 10), ("C", 3), ("D", 33), ("E", 10)):
        sheet.column_dimensions[column].width = width
    weights = [len(values) + 3 for _, values in sections]
    split = min(range(1, len(sections)), key=lambda i: abs(sum(weights[:i]) - sum(weights[i:]))) \
        if len(sections) > 1 else 1
    coordinates = []
    border = Border(bottom=Side(style="hair", color="CCCCCC"))
    for start, group in ((1, sections[:split]), (4, sections[split:])):
        row = 3
        for category, values in group:
            sheet.merge_cells(start_row=row, start_column=start, end_row=row, end_column=start + 1)
            cell = sheet.cell(row, start, category)
            cell.data_type = "s"
            cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="375623")
            sheet.row_dimensions[row].height = 20
            row += 1
            for column, text in ((start, "Product"), (start + 1, "PLU")):
                sheet.cell(row, column, text).font = Font(name="Calibri", size=10, bold=True)
            sheet.row_dimensions[row].height = 16
            row += 1
            for product, plu in values:
                for column, value in ((start, product), (start + 1, plu)):
                    cell = sheet.cell(row, column, value)
                    cell.data_type = "s"
                    cell.font = Font(name="Calibri", size=11)
                    cell.alignment = Alignment(wrap_text=True, vertical="center",
                                               horizontal="left" if column == start else "center")
                    cell.border = border
                sheet.cell(row, start + 1).number_format = "@"
                sheet.row_dimensions[row].height = max(
                    sheet.row_dimensions[row].height or 0, 16 * ((len(product) + 29) // 30))
                coordinates.append(dict(category=category, product=product, plu=plu,
                                        product_cell=sheet.cell(row, start).coordinate,
                                        code_cell=sheet.cell(row, start + 1).coordinate))
                row += 1
            row += 1
    sheet.print_area = f"A1:E{sheet.max_row}"
    sheet.print_options.horizontalCentered = True
    sheet.page_setup.orientation = "portrait"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_LETTER
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 1
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_margins = PageMargins(left=.25, right=.25, top=.3, bottom=.3, header=.1, footer=.1)
    sheet.freeze_panes = "A3"
    content = io.BytesIO()
    workbook.save(content)
    return content.getvalue(), coordinates


def validate_sheet(sheet, coordinates):
    for entry in coordinates:
        product, code = sheet[entry["product_cell"]], sheet[entry["code_cell"]]
        if product.value != entry["product"] or product.data_type != "s":
            raise ValueError(f"deli product changed at {entry['product_cell']}")
        if code.value != entry["plu"] or code.data_type != "s" or code.number_format != "@":
            raise ValueError(f"deli PLU changed at {entry['code_cell']}")


def read_source(root):
    path = Path(root) / DELI_SOURCE
    title, sections = read_sections(Path(root) / "sources/binders/Deli.docx")
    expected, coordinates = workbook_bytes(title, sections)
    content = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(content)) as saved, zipfile.ZipFile(io.BytesIO(expected)) as generated:
        for name in ("xl/worksheets/sheet1.xml", "xl/styles.xml", "xl/workbook.xml"):
            if saved.read(name) != generated.read(name):
                raise ValueError("updated deli source is stale or modified; regenerate it from Deli.docx")
    source, rebuilt = load_workbook(io.BytesIO(content)), load_workbook(io.BytesIO(expected))
    try:
        if source.sheetnames != ["Deli"]:
            raise ValueError("updated deli source must contain only the Deli worksheet")
        validate_sheet(source["Deli"], coordinates)
        if list(source["Deli"].values) != list(rebuilt["Deli"].values):
            raise ValueError("updated deli source differs from owner document; regenerate it")
    finally:
        source.close()
        rebuilt.close()
    return content, coordinates


def convert(source, output):
    title, sections = read_sections(source)
    output.mkdir(parents=True, exist_ok=True)
    paths = [output / name for name in ("Deli.docx", "Updated_Deli_Two_Columns.docx",
                                       DELI_SOURCE.name)]
    if any(path.exists() for path in paths):
        raise ValueError("deli source output already exists; refusing to overwrite")
    document = Document(source)
    for paragraph in document.paragraphs:
        paragraph.paragraph_format.space_after = Pt(3 if paragraph.text else 0)
        paragraph.paragraph_format.space_before = Pt(5 if paragraph.text else 0)
        if paragraph.text:
            paragraph.paragraph_format.keep_with_next = True
        for run in paragraph.runs:
            run.font.size = Pt(12 if paragraph.text == title else 11)
    for section in document.sections:
        section.page_width, section.page_height = Inches(8.5), Inches(11)
        section.left_margin = section.right_margin = Inches(.4)
        columns = section._sectPr.find(qn("w:cols"))
        if columns is None:
            raise ValueError("deli document lacks column settings")
        columns.set(qn("w:num"), "2")
        columns.set(qn("w:space"), "360")
    for table in document.tables:
        table.autofit = False
        for number, row in enumerate(table.rows):
            row.cells[0].width, row.cells[1].width = Inches(2.8), Inches(.8)
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.space_before = Pt(0)
                    paragraph.paragraph_format.space_after = Pt(0)
                    paragraph.paragraph_format.keep_with_next = number < len(table.rows) - 1
                    paragraph.paragraph_format.keep_together = True
                    for run in paragraph.runs:
                        run.font.size = Pt(10)
        table.columns[0].width, table.columns[1].width = Inches(2.8), Inches(.8)
    content, coordinates = workbook_bytes(title, sections)
    paths[0].write_bytes(Path(source).read_bytes())
    document.save(paths[1])
    paths[2].write_bytes(content)
    return coordinates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "sources/binders")
    args = parser.parse_args()
    try:
        entries = convert(args.source, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(f"Saved two-column deli sources with {len(entries)} exact product/PLU entries")


if __name__ == "__main__":
    main()
