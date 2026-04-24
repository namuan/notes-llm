import unittest

from html_converter import html_to_plaintext, md_to_apple_notes_html


class HtmlConverterTests(unittest.TestCase):
    def test_markdown_to_html_keeps_basic_structure(self) -> None:
        html = md_to_apple_notes_html("# Title\n\n- one\n- two\n")
        self.assertIn("Title", html)
        self.assertIn("<li>", html)

    def test_html_to_plaintext_preserves_headings_and_lists(self) -> None:
        text = html_to_plaintext("<h1>Title</h1><ul><li>One</li><li>Two</li></ul>")
        self.assertIn("# Title", text)
        self.assertIn("- One", text)
        self.assertIn("- Two", text)


if __name__ == "__main__":
    unittest.main()
