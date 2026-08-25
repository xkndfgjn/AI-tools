import tempfile
import unittest
from pathlib import Path

import fitz

from tools.extract import pdf_extract_text
from tools.metadata import pdf_get_metadata
from tools.search import pdf_search_keywords
from tools.summarize import pdf_summarize


class ToolModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.pdf_path = Path(self.tmpdir.name) / "sample.pdf"

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello PDF tool test")
        doc.save(self.pdf_path)
        doc.close()

    def test_extract_text(self):
        result = __import__("asyncio").run(pdf_extract_text(str(self.pdf_path)))
        text = result[0].text
        self.assertIn("Hello PDF tool test", text)

    def test_metadata(self):
        result = __import__("asyncio").run(pdf_get_metadata(str(self.pdf_path)))
        text = result[0].text
        self.assertIn("pages", text)

    def test_summarize(self):
        result = __import__("asyncio").run(pdf_summarize(str(self.pdf_path), length=80))
        text = result[0].text
        self.assertIn("Hello PDF tool test", text)

    def test_search_hit(self):
        result = __import__("asyncio").run(pdf_search_keywords(str(self.pdf_path), "hello"))
        text = result[0].text
        self.assertIn("Hello PDF tool test", text)
        self.assertIn("匹配#1", text)

    def test_search_multi_keywords(self):
        result = __import__("asyncio").run(
            pdf_search_keywords(str(self.pdf_path), "hello,missing")
        )
        text = result[0].text
        self.assertIn("Hello PDF tool test", text)

    def test_search_no_match(self):
        result = __import__("asyncio").run(pdf_search_keywords(str(self.pdf_path), "nothing"))
        text = result[0].text
        self.assertIn("未找到关键词", text)


if __name__ == "__main__":
    unittest.main()
