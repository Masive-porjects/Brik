"""Tests for the books RAG pipeline (pure functions — no PDFs, no Ollama).

The real books are copyrighted and never in the repo, so every test runs on
synthetic page text that reproduces the layouts seen in the OCR output:
running footers with page numbers ("Chapter Five 31"), a scan missing a leaf
(offset shift), OCR noise numbers, hyphenated line breaks.
"""

import json
from io import BytesIO
from unittest.mock import patch

import numpy as np
import pytest

from audiomind.intelligence.rag.books import BOOKS, get_book
from audiomind.intelligence.rag.chapters import canonical_chapter, chapter_from_figures
from audiomind.intelligence.rag.chunk import Chunk, chunk_book
from audiomind.intelligence.rag.clean import (
    CleanPage,
    clean_book,
    detect_printed_number,
    reconcile_page_numbers,
    to_paragraphs,
)
from audiomind.intelligence.rag.embed import EmbeddingUnavailableError, OllamaEmbedder
from audiomind.intelligence.rag.evaluate import (
    QUESTIONS_PATH,
    Expected,
    first_hit_rank,
    is_hit,
    load_questions,
)
from audiomind.intelligence.rag.index import BM25, RagIndex, rrf_fuse, tokenize


def _chunk(
    book_id: str = "b",
    pages: tuple[int | None, int | None] = (1, 1),
    pdf: tuple[int, int] = (10, 10),
    text: str = "texto",
    chapter: str = "",
) -> Chunk:
    return Chunk(
        f"{book_id}#0", book_id, chapter, pages[0], pages[1], pdf[0], pdf[1], text
    )


class TestCatalog:
    def test_book_ids_are_unique(self):
        ids = [b.book_id for b in BOOKS]
        assert len(ids) == len(set(ids))

    def test_exactly_one_reference_edition_for_code_citations(self):
        """The Mix Engine cites 'Owsinski pág. 32' from ONE edition."""
        refs = [b for b in BOOKS if b.reference_for_code]
        assert [b.book_id for b in refs] == ["owsinski-meh-1e-en"]

    def test_citation_format(self):
        book = get_book("owsinski-meh-1e-en")
        assert book.citation(32).endswith("pág. 32")
        assert book.citation(32, pdf_index=45).endswith("pág. 32")
        assert book.citation(None, pdf_index=367).endswith("pág. PDF 368")
        assert "pág." not in book.citation(None)

    def test_unknown_book_raises(self):
        with pytest.raises(KeyError):
            get_book("nope")


class TestChapters:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("Chapter Five 31", "Cap. 5"),
            ("CAPÍTULO 5", "Cap. 5"),
            ("Capitulo cinco", "Cap. 5"),
            ("Chapter Twenty One 145", "Cap. 21"),
            ("PART ll — MIXING IN SURROUND", "Parte 2"),  # OCR reads II as ll
            ("Parte III Las entrevistas", "Parte 3"),
            (
                "Chapter 12: Why Is Surround Better Than Stereo?............",
                None,
            ),  # TOC
            ("The chapter was long", None),
        ],
    )
    def test_canonical_chapter(self, line, expected):
        assert canonical_chapter(line) == expected

    def test_chapter_from_figure_numbers(self):
        assert (
            chapter_from_figures("Figura 6.5: Panorámica hacia los agujeros.")
            == "Cap. 6"
        )
        assert chapter_from_figures("sin figuras aquí") is None


class TestClean:
    def test_detects_standalone_and_footer_numbers(self):
        assert detect_printed_number(["texto", "", "32"]) == 32
        assert detect_printed_number(["Some text", "Chapter Five 31"]) == 31
        assert (
            detect_printed_number(["32 The Mixing Engineer's Handbook", "text"]) == 32
        )
        assert detect_printed_number(["no number here", "nor here"]) is None

    def test_paragraphs_join_lines_and_hyphens_and_drop_footer(self):
        text = (
            "Equalize to make every fre-\nquency fit\ntogether.\n\n"
            "Second para.\nChapter Five 31"
        )
        assert to_paragraphs(text) == (
            "Equalize to make every frequency fit together.",
            "Second para.",
        )

    def test_drops_credit_and_placeholder_lines(self):
        text = "Real content here.\n\n© 2022 Bobby Owsinski, todos los derechos.\n\n￼"
        assert to_paragraphs(text) == ("Real content here.",)

    def test_offset_shift_is_resolved_locally(self):
        """Scan missing a leaf: offset 14 early in the book, 13 later."""
        detected = {i: i - 14 for i in range(20, 60, 2)} | {
            i: i - 13 for i in range(100, 160, 2)
        }
        printed = reconcile_page_numbers(detected, [46, 47, 150, 151])
        assert printed == {46: 32, 47: 33, 150: 137, 151: 138}

    def test_isolated_noise_detection_is_ignored(self):
        detected = {i: i - 13 for i in range(90, 112, 2)} | {100: 4}  # "4" = OCR noise
        assert reconcile_page_numbers(detected, [100])[100] == 87

    def test_agreeing_noise_pair_loses_to_local_majority(self):
        detected = {i: i - 14 for i in range(24, 46, 2)} | {33: 3, 34: 4}
        assert reconcile_page_numbers(detected, [34])[34] == 20

    def test_front_matter_has_no_printed_page(self):
        detected = {i: i - 14 for i in range(20, 40, 2)}
        assert reconcile_page_numbers(detected, [3])[3] is None

    def test_clean_book_attaches_page_and_chapter(self):
        words = "kick snare bass vocal guitar piano organ synth strings brass".split()
        pages = {
            i: f"The {words[i - 40]} needs its own space.\n\nChapter Five {i - 14}"
            for i in range(40, 50)
        }
        cleaned = clean_book(pages)
        page46 = next(p for p in cleaned if p.pdf_index == 46)
        assert page46.printed_page == 32
        assert page46.chapter_hint == "Cap. 5"
        assert page46.paragraphs == ("The organ needs its own space.",)

    def test_repeated_edge_line_is_dropped_as_running_header(self):
        pages = {
            i: f"THE MIXING ENGINEER'S HANDBOOK\n\nUnique body {chr(65 + i)}.\n\n{i}"
            for i in range(10)
        }
        assert all("HANDBOOK" not in " ".join(p.paragraphs) for p in clean_book(pages))


class TestChunk:
    def _pages(self, n: int, words: int, chapter_at: dict[int, str] | None = None):
        chapter_at = chapter_at or {}
        return [
            CleanPage(
                i,
                i + 1,
                (" ".join(f"w{i}x{j}" for j in range(words)),),
                chapter_at.get(i),
            )
            for i in range(n)
        ]

    def test_chunks_respect_target_size(self):
        chunks = chunk_book(
            "b", self._pages(20, 100), target_words=300, overlap_words=0
        )
        assert all(c.word_count <= 400 for c in chunks)
        assert sum(c.word_count for c in chunks) == 2000

    def test_never_crosses_a_chapter(self):
        pages = self._pages(6, 100, {0: "Cap. 1", 3: "Cap. 2"})
        chunks = chunk_book("b", pages, target_words=1000, overlap_words=0)
        assert [c.chapter for c in chunks] == ["Cap. 1", "Cap. 2"]
        assert (chunks[0].pdf_start, chunks[0].pdf_end) == (0, 2)
        assert (chunks[1].page_start, chunks[1].page_end) == (4, 6)

    def test_overlap_repeats_the_tail_paragraph(self):
        pages = [CleanPage(0, 1, tuple(f"p{i} " + "x " * 39 for i in range(10)))]
        chunks = chunk_book("b", pages, target_words=120, overlap_words=60)
        assert chunks[1].text.split("\n\n")[0] == chunks[0].text.split("\n\n")[-1]

    def test_heading_paragraph_sets_chapter(self):
        pages = [CleanPage(0, 1, ("CAPÍTULO 3", "contenido " * 40))]
        assert chunk_book("b", pages)[0].chapter == "Cap. 3"

    def test_json_roundtrip(self):
        chunk = _chunk(text="hola mundo")
        assert Chunk.from_json(chunk.to_json()) == chunk


class TestIndex:
    def test_tokenize_folds_accents_and_drops_stopwords(self):
        assert tokenize("La canción y el BOMBO a 400 Hz") == [
            "cancion",
            "bombo",
            "400",
            "hz",
        ]

    def test_bm25_ranks_the_matching_document_first(self):
        docs = [
            tokenize(t)
            for t in ("bombo graves 80 hz", "voz aire brillo", "caja boing 900")
        ]
        scores = BM25(docs).scores(tokenize("caja 900"))
        assert scores.index(max(scores)) == 2

    def test_rrf_rewards_agreement_between_rankings(self):
        fused = rrf_fuse([[1, 2, 3], [3, 1, 2]])
        assert [doc for doc, _ in fused][0] == 1
        assert fused[0][1] > fused[-1][1]

    def test_hybrid_search_and_book_filter(self):
        chunks = [
            _chunk("a", text="kick drum bottom at 80 Hz"),
            _chunk("b", text="snare boing at 900 Hz"),
        ]
        vectors = np.eye(2, dtype=np.float32)
        index = RagIndex(chunks, vectors)
        hits = index.search(
            "snare", k=2, query_vector=np.array([0, 1], dtype=np.float32)
        )
        assert hits[0].chunk.book_id == "b"
        only_a = index.search("snare kick", k=2, mode="bm25", book_ids={"a"})
        assert [h.chunk.book_id for h in only_a] == ["a"]

    def test_hybrid_without_vectors_degrades_to_bm25(self):
        index = RagIndex([_chunk(text="snare boing 900")])
        assert index.search("snare", mode="hybrid")[0].chunk.text == "snare boing 900"
        with pytest.raises(ValueError):
            index.search("snare", mode="vector")

    def test_save_and_load_roundtrip(self, tmp_path):
        chunks = [_chunk(text="uno dos"), _chunk("c", text="tres cuatro")]
        RagIndex(chunks, np.eye(2, dtype=np.float32)).save(tmp_path, "bge-m3")
        loaded = RagIndex.load(tmp_path)
        assert loaded.chunks == chunks
        assert loaded.has_vectors
        assert (
            json.loads((tmp_path / "meta.json").read_text())["embed_model"] == "bge-m3"
        )


class TestEmbedder:
    def test_embeddings_are_normalized(self):
        payload = json.dumps({"embeddings": [[3.0, 4.0], [0.0, 2.0]]}).encode()
        with patch("urllib.request.urlopen", return_value=BytesIO(payload)):
            matrix = OllamaEmbedder("http://x", "bge-m3").embed(["a", "b"])
        assert matrix.dtype == np.float32
        np.testing.assert_allclose(
            np.linalg.norm(matrix, axis=1), [1.0, 1.0], rtol=1e-6
        )

    def test_unreachable_ollama_raises_clear_error(self):
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            with pytest.raises(EmbeddingUnavailableError, match="ollama pull bge-m3"):
                OllamaEmbedder("http://x", "bge-m3").embed(["a"])


class TestEvaluation:
    def test_printed_page_overlap(self):
        expected = (Expected("b", 32, 33),)
        assert is_hit(_chunk(pages=(31, 32)), expected)
        assert not is_hit(_chunk(pages=(34, 35)), expected)
        assert not is_hit(_chunk("other", pages=(32, 32)), expected)
        assert not is_hit(_chunk(pages=(None, None)), expected)

    def test_pdf_index_overlap_for_unnumbered_books(self):
        expected = (Expected("b", 368, 370, by_pdf_index=True),)
        assert is_hit(_chunk(pages=(None, None), pdf=(369, 371)), expected)

    def test_first_hit_rank(self):
        expected = (Expected("b", 5, 5),)
        ranked = [_chunk(pages=(1, 1)), _chunk(pages=(5, 6))]
        assert first_hit_rank(ranked, expected) == 2
        assert first_hit_rank(ranked[:1], expected) is None

    def test_versioned_questions_reference_known_books(self):
        known = {b.book_id for b in BOOKS}
        questions = load_questions(QUESTIONS_PATH)
        assert len(questions) >= 15
        for q in questions:
            assert q.expected and all(e.book_id in known for e in q.expected)
            assert all(e.page_start <= e.page_end for e in q.expected)
