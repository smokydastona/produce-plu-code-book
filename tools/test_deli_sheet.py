import io
import tempfile
import unittest
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from openpyxl import load_workbook

from build_deli_sheet import convert, read_sections, read_source


class DeliSheetChecks(unittest.TestCase):
    def test_conversion_preserves_owner_text_and_two_column_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = Document()
            document.add_heading("Deli Guide", 0)
            for heading, product, plu in (("Meals", "=Exact product", "00012"), ("Salads", "Salad", "00345")):
                document.add_heading(heading, 1)
                table = document.add_table(rows=2, cols=2)
                for row, values in zip(table.rows, (("Product", "PLU"), (product, plu))):
                    for cell, text in zip(row.cells, values):
                        cell.text = text
            upload = root / "upload.docx"
            document.save(upload)
            original = upload.read_bytes()
            output = root / "sources/binders"
            coordinates = convert(upload, output)
            self.assertEqual((output / "Deli.docx").read_bytes(), original)
            self.assertEqual(read_sections(output / "Updated_Deli_Two_Columns.docx"), read_sections(upload))
            adjusted = Document(output / "Updated_Deli_Two_Columns.docx")
            self.assertEqual(adjusted.sections[0]._sectPr.find(qn("w:cols")).get(qn("w:num")), "2")
            content, checked = read_source(root)
            self.assertEqual(coordinates, checked)
            workbook = load_workbook(io.BytesIO(content))
            self.assertEqual(workbook["Deli"]["A5"].value, "=Exact product")
            self.assertEqual(workbook["Deli"]["A5"].data_type, "s")
            self.assertEqual(workbook["Deli"]["B5"].value, "00012")
            self.assertEqual(workbook["Deli"]["E5"].value, "00345")
            workbook["Deli"]["E5"] = "99999"
            workbook.save(output / "Updated_Deli_Two_Columns.xlsx")
            workbook.close()
            with self.assertRaisesRegex(ValueError, "stale or modified"):
                read_source(root)
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                convert(upload, output)

    def test_invalid_plu_is_reported_not_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            document = Document()
            document.add_heading("Deli", 0)
            document.add_heading("Meals", 1)
            table = document.add_table(rows=2, cols=2)
            for row, values in zip(table.rows, (("Product", "PLU"), ("Meal", " 00012 "))):
                for cell, text in zip(row.cells, values):
                    cell.text = text
            path = Path(directory) / "Deli.docx"
            document.save(path)
            with self.assertRaisesRegex(ValueError, "invalid PLU"):
                read_sections(path)


if __name__ == "__main__":
    unittest.main()
