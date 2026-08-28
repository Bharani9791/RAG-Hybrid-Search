from pdfreader import read_markdown, read_pdf
from chunker import chunk_pages, chunk_by_structure
from vector_store import store_in_pinecone

pdf_path = "./resources/document.pdf"
# markdown_path = "./resources/document.md"


def run():
    pages = read_pdf(pdf_path)
    # pages = read_markdown(markdown_path)

    # Baseline: character chunks for semantic search in __default__
    character_chunks = chunk_pages(pages, chunk_size=200, chunk_overlap=0)
    store_in_pinecone(character_chunks, namespace="__default__")
    print(f"Stored {len(character_chunks)} character chunks in __default__")

    # Improved RAG: structure chunks for hybrid search in __hybrid__
    structure_chunks = chunk_by_structure(pages)
    store_in_pinecone(structure_chunks, namespace="__hybrid__")
    print(f"Stored {len(structure_chunks)} structure chunks in __hybrid__")


if __name__ == "__main__":
    run()
