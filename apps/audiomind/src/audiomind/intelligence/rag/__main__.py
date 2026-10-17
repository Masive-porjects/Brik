"""CLI: ``python -m audiomind.intelligence.rag <command>``.

status                     what is extracted / indexed / reachable
extract [--book ID]        PDF → pages (text layer or Tesseract OCR)
build [--no-embed]         pages → clean → chunks (+ Ollama embeddings)
search "pregunta" [-k 5]   hybrid search with citations
eval [-k 5]                hit@k / MRR on eval_questions.json
"""

import argparse
import json
import sys

from audiomind.intelligence.rag.books import BOOKS, get_book
from audiomind.intelligence.rag.chunk import Chunk, chunk_book
from audiomind.intelligence.rag.clean import clean_book
from audiomind.intelligence.rag.config import RagConfig
from audiomind.intelligence.rag.embed import EmbeddingUnavailableError, OllamaEmbedder
from audiomind.intelligence.rag.evaluate import first_hit_rank, load_questions
from audiomind.intelligence.rag.extract import extract_book, load_raw_pages, pages_path
from audiomind.intelligence.rag.index import RagIndex, SearchMode


def _embedder(config: RagConfig) -> OllamaEmbedder:
    return OllamaEmbedder(config.ollama_url, config.embed_model)


def cmd_status(config: RagConfig, _: argparse.Namespace) -> None:
    print(f"datos:  {config.data_dir}")
    print(f"libros: {config.books_dir}")
    for book in sorted(BOOKS, key=lambda b: b.priority):
        pages = len(load_raw_pages(pages_path(config, book)))
        print(
            f"  [{book.priority}] {book.book_id:<36} {book.method:<4} páginas={pages}"
        )
    meta = config.index_dir / "meta.json"
    print(
        "índice:",
        meta.read_text(encoding="utf-8") if meta.exists() else "sin construir",
    )
    try:
        _embedder(config).embed(["ping"])
        print(f"ollama: OK ({config.embed_model})")
    except EmbeddingUnavailableError as exc:
        print(f"ollama: NO disponible — {exc}")


def cmd_extract(config: RagConfig, args: argparse.Namespace) -> None:
    books = (
        [get_book(args.book)] if args.book else sorted(BOOKS, key=lambda b: b.priority)
    )
    for book in books:
        added = extract_book(config, book, workers=args.workers, limit=args.limit)
        print(f"{book.book_id}: +{added} páginas", flush=True)


def cmd_build(config: RagConfig, args: argparse.Namespace) -> None:
    chunks: list[Chunk] = []
    for book in sorted(BOOKS, key=lambda b: b.priority):
        raw = load_raw_pages(pages_path(config, book))
        if not raw:
            print(f"{book.book_id}: sin páginas extraídas, se omite")
            continue
        book_chunks = chunk_book(book.book_id, clean_book(raw))
        print(f"{book.book_id}: {len(raw)} páginas → {len(book_chunks)} chunks")
        chunks.extend(book_chunks)
    embeddings = None
    if not args.no_embed:
        try:
            embeddings = _embedder(config).embed([c.text for c in chunks])
        except EmbeddingUnavailableError as exc:
            print(f"AVISO: índice solo BM25 (sin vectores). {exc}")
    RagIndex(chunks, embeddings).save(config.index_dir, config.embed_model)
    print(f"índice guardado en {config.index_dir} ({len(chunks)} chunks)")


def _load_index(config: RagConfig) -> RagIndex:
    if not (config.index_dir / "chunks.jsonl").exists():
        sys.exit("No hay índice: corre primero `build`.")
    return RagIndex.load(config.index_dir)


def _search(
    index: RagIndex, config: RagConfig, query: str, k: int, mode: SearchMode
) -> list[Chunk]:
    vector = None
    if mode != "bm25" and index.has_vectors:
        vector = _embedder(config).embed([query])[0]
    effective: SearchMode = mode if (vector is not None or mode == "bm25") else "bm25"
    return [
        hit.chunk
        for hit in index.search(query, k=k, mode=effective, query_vector=vector)
    ]


def cmd_search(config: RagConfig, args: argparse.Namespace) -> None:
    index = _load_index(config)
    for rank, chunk in enumerate(
        _search(index, config, args.query, args.k, args.mode), 1
    ):
        book = get_book(chunk.book_id)
        source = book.citation(chunk.page_start, pdf_index=chunk.pdf_start)
        print(f"\n#{rank} {source} — {chunk.chapter or 's/capítulo'}")
        print("   " + chunk.text[: args.chars].replace("\n", " ") + "…")


def cmd_eval(config: RagConfig, args: argparse.Namespace) -> None:
    index = _load_index(config)
    modes: list[SearchMode] = (
        ["bm25", "vector", "hybrid"] if index.has_vectors else ["bm25"]
    )
    questions = load_questions()
    summary = {}
    for mode in modes:
        ranks = [
            first_hit_rank(_search(index, config, q.question, args.k, mode), q.expected)
            for q in questions
        ]
        hits = sum(r is not None for r in ranks)
        mrr = sum(1 / r for r in ranks if r is not None) / len(questions)
        summary[mode] = {"hit@k": f"{hits}/{len(questions)}", "mrr": round(mrr, 3)}
        if args.verbose:
            for q, r in zip(questions, ranks, strict=True):
                print(f"[{mode}] {q.qid:<14} rank={r}  {q.question}")
    print(json.dumps({"k": args.k, **summary}, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m audiomind.intelligence.rag")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    p_extract = sub.add_parser("extract")
    p_extract.add_argument("--book")
    p_extract.add_argument("--workers", type=int, default=4)
    p_extract.add_argument("--limit", type=int)
    p_build = sub.add_parser("build")
    p_build.add_argument("--no-embed", action="store_true")
    p_search = sub.add_parser("search")
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=5)
    p_search.add_argument(
        "--mode", choices=["bm25", "vector", "hybrid"], default="hybrid"
    )
    p_search.add_argument("--chars", type=int, default=300)
    p_eval = sub.add_parser("eval")
    p_eval.add_argument("-k", type=int, default=5)
    p_eval.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    config = RagConfig.from_env()
    commands = {
        "status": cmd_status,
        "extract": cmd_extract,
        "build": cmd_build,
        "search": cmd_search,
        "eval": cmd_eval,
    }
    commands[args.command](config, args)


if __name__ == "__main__":
    main()
