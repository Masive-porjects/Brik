"""Embeddings via a local Ollama server (``POST /api/embed``).

Stdlib HTTP only — no extra dependency. Default model ``bge-m3``:
multilingual (the books are in Spanish and English, users write in
Spanish) and 8k-token context.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

BATCH_SIZE = 16


class EmbeddingUnavailableError(RuntimeError):
    """Ollama is not running or the model is not pulled."""


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, timeout_s: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    def _post(self, texts: Sequence[str]) -> list[list[float]]:
        body = json.dumps({"model": self.model, "input": list(texts)}).encode()
        request = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError) as exc:
            raise EmbeddingUnavailableError(
                f"Ollama no responde en {self.base_url} o falta el modelo "
                f"'{self.model}' (ollama pull {self.model}): {exc}"
            ) from exc
        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise EmbeddingUnavailableError(
                f"Respuesta inesperada de Ollama: {payload!r:.200}"
            )
        return embeddings

    def embed(self, texts: Sequence[str]) -> npt.NDArray[np.float32]:
        """Embed ``texts`` → L2-normalized float32 matrix (rows = texts)."""
        rows: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            rows.extend(self._post(texts[start : start + BATCH_SIZE]))
        matrix = np.asarray(rows, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return (matrix / np.maximum(norms, 1e-12)).astype(np.float32)
