"""Adaptador para la API Messages de Anthropic (Claude).

No se reusa el adaptador OpenAI-compatible porque la forma es otra: el system
prompt va en un campo de arriba, las herramientas llevan ``input_schema``, una
llamada es un bloque ``tool_use`` y su resultado vuelve dentro de un turno
``user`` como bloque ``tool_result``. Traducir eso "a la fuerza" escondería las
diferencias en vez de soportarlas.

Sin SDK a propósito: ``httpx`` ya viaja como dependencia transitiva y esta API es
HTTP chato.

Decisiones que vale la pena conocer:

* **``max_tokens`` es obligatorio** para el servicio. Se manda siempre; sin él la
  petición se rechaza y el síntoma se ve como "el agente no responde".
* **``anthropic-version`` se fija explícitamente.** El servicio exige el header y
  su default puede cambiar sin aviso.
* **El transcript neutro se asume alternado.** Una llamada a herramienta y su
  resultado producen un turno ``assistant`` y un ``user``, así que el historial
  que arma el bucle alterna solo. Un transcript construido a mano con dos turnos
  ``user`` seguidos lo rechazaría el servicio, y ese error se levanta como
  ``TransportUnavailableError``.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

import httpx

from audiomind.processing.agentic_loop import (
    ModelTurn,
    ToolCall,
    TransportUnavailableError,
    assign_call_ids,
)

log = logging.getLogger(__name__)

#: Baja: este agente mueve perillas, no hace brainstorming.
DEFAULT_TEMPERATURE = 0.3

#: Tope de salida. La API lo exige; el bucle usa turnos cortos.
DEFAULT_MAX_TOKENS = 4096

#: El servicio exige el header de versión en cada petición.
ANTHROPIC_VERSION = "2023-06-01"

DEFAULT_TIMEOUT_SECONDS = 120.0


class AnthropicTransport:
    """``ModelTransport`` sobre ``POST {base_url}/messages``."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        requires_api_key: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.base_url = (base_url or "").strip().rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        if requires_api_key and not self.api_key:
            raise TransportUnavailableError(
                "Falta LLM_API_KEY para Anthropic. Completala en "
                "apps/audiomind/.env."
            )
        if not self.model:
            raise TransportUnavailableError(
                "Falta el modelo de Claude. Definí AGENT_MODEL_NAME en "
                "apps/audiomind/.env."
            )
        if not self.base_url:
            raise TransportUnavailableError(
                "Falta la URL de Anthropic. Definí LLM_BASE_URL en "
                "apps/audiomind/.env."
            )

        self._client = client or httpx.Client(timeout=timeout)

    # -- ModelTransport -----------------------------------------------------

    def turn(
        self,
        *,
        phase: str,
        system: str,
        transcript: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> ModelTurn:
        """Un turno del modelo: texto, o las herramientas que pidió ejecutar."""
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": self._messages(transcript),
            "temperature": self.temperature,
        }
        if tools:
            body["tools"] = [self._tool(tool) for tool in tools]

        payload = self._post(phase, body)
        return self._parse(phase, payload)

    # -- Traducción --------------------------------------------------------

    @staticmethod
    def _tool(tool: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["parameters"],
        }

    def _messages(
        self, transcript: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []

        for entry in assign_call_ids(transcript):
            if "function_call" in entry:
                call = entry["function_call"]
                messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": call["id"],
                                "name": call["name"],
                                "input": call.get("args") or {},
                            }
                        ],
                    }
                )
            elif "response" in entry:
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": entry["id"],
                                "content": json.dumps(entry["response"]),
                            }
                        ],
                    }
                )
            else:
                role = "assistant" if entry.get("role") == "model" else "user"
                messages.append(
                    {
                        "role": role,
                        "content": [{"type": "text", "text": entry.get("text", "")}],
                    }
                )

        return messages

    def _parse(self, phase: str, payload: dict[str, Any]) -> ModelTurn:
        blocks = payload.get("content") or []
        if not blocks:
            raise TransportUnavailableError(
                f"Anthropic no devolvió contenido en {phase}: {payload!r}"
            )

        texts = [
            str(block.get("text") or "")
            for block in blocks
            if block.get("type") == "text"
        ]
        calls = [
            ToolCall(name=str(block["name"]), args=dict(block.get("input") or {}))
            for block in blocks
            if block.get("type") == "tool_use" and block.get("name")
        ]
        text = " ".join(part.strip() for part in texts if part.strip())

        if calls or text:
            return ModelTurn(text=text, tool_calls=calls)
        raise TransportUnavailableError(
            f"Anthropic devolvió un turno vacío en {phase}: {payload!r}"
        )

    # -- Red ---------------------------------------------------------------

    def _post(self, phase: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        try:
            response = self._client.post(
                f"{self.base_url}/messages", json=body, headers=headers
            )
            response.raise_for_status()
            return dict(response.json())
        except httpx.HTTPError as exc:
            raise TransportUnavailableError(
                f"Falló la llamada a Anthropic en {phase}: {exc}"
            ) from exc
