import re
from bs4 import BeautifulSoup

class TextCleaner:
    def clean_html(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")

        # Remove scripts and styles
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        return text
