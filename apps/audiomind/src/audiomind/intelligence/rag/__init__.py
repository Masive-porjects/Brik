"""RAG over the mixing/mastering books — offline ingestion + local search.

Pipeline (all local, nothing leaves the machine):

    PDF ──extract/OCR──► pages ──clean──► chunks ──embed (Ollama)──► index
                                                                      │
                                    query ──hybrid search (BM25 + vectors)┘

The books are copyrighted and the repo is PUBLIC: the PDFs, the extracted
text, the chunks and the embeddings live ONLY under the data dir
(``RAG_DATA_DIR``, gitignored). Only this code, the book catalog
(metadata) and the evaluation questions are versioned.

The assistant uses the retrieved passages to EXPLAIN and cite. It never
turns a passage into a DSP value at runtime — numeric rules go through the
curated Knowledge Core, reviewed by the DSP owner, and the mappers.
"""
