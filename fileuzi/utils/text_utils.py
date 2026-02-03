"""
Text parsing and extraction utilities for FileUzi.
"""

from html.parser import HTMLParser


class HTMLTextExtractor(HTMLParser):
    """Simple HTML parser to extract plain text from HTML content."""

    def __init__(self):
        super().__init__()
        self.text_parts = []

    def handle_data(self, data):
        self.text_parts.append(data)

    def get_text(self):
        return ' '.join(self.text_parts)
