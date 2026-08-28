import os
from pypdf import PdfReader

def read_pdf(pdf_path):
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"The file {pdf_path} does not exist.")
    
    reader = PdfReader(pdf_path)
    pages = [page.extract_text() for page in reader.pages]
    return pages

def read_markdown(md_path):
    if not os.path.exists(md_path):
        raise FileNotFoundError(f"The file {md_path} does not exist.")

    with open(md_path, "r", encoding="utf-8") as file:
        text = file.read()

    # Treat heading-separated sections like PDF pages so chunk_pages can join them.
    sections = [section.strip() for section in text.split("\n## ") if section.strip()]
    if len(sections) > 1:
        sections = [sections[0]] + [f"## {section}" for section in sections[1:]]
    return sections if sections else [text]