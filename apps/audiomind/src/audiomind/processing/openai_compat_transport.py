"""Adaptador para cualquier endpoint OpenAI-compatible.

Cubre dos de los proveedores pedidos con UNA sola implementación, porque
``POST /v1/chat/completions`` es el mismo protocolo en DeepSeek y en Ollama (y en
Groq, LM Studio, vLLM, OpenRouter…). Es deliberado: cada adaptador de más es
código que hay que mantener.

Sin SDK a propósito. ``httpx`` ya viaja como dependencia transitiva de
``google-genai``; se declara explícitamente porque este módulo lo importa.

Decisiones que vale la pena conocer:

* **El esquema de herramientas viaja como JSON Schema crudo.** ``tools[].function
  .parameters`` recibe el dict que sale de ``tool_definitions()`` sin tocar. Ese
  es el requisito de agnosticismo: lo que ve el modelo sale de los modelos
  Pydantic, no de un tipo del SDK.
* **Los argumentos de una llamada son un string JSON, no un objeto.** Un payload
  ilegible se levanta en vez de caer a ``{}``: ejecutar la herramienta con
  argumentos vacíos movería faders a ciegas.
* **Una respuesta vacía es un error.** Nunca se devuelve un turno en blanco que
  el bucle interpretaría como "el agente no quiso hacer nada".
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

#: Un render del bucle puede tardar; el timeout no debe ser el cuello de botella.
DEFAULT_TIMEOUT_SECONDS = 120.0


def _arguments(raw: Any) -> dict[str, Any]:
    """Los argumentos vienen serializados; un payload roto se levanta."""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise TransportUnavailableError(
            f"El proveedor mandó argumentos que no son JSON: {raw!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise TransportUnavailableError(
            f"El proveedor mandó argumentos que no son un objeto: {raw!r}"
        )
    return parsed


class OpenAICompatTransport:
    """``ModelTransport`` sobre ``POST {base_url}/chat/completions``."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        requires_api_key: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.base_url = (base_url or "").strip().rstrip("/")
        self.temperature = temperature
        self.timeout = timeout

        if requires_api_key and not self.api_key:
            raise TransportUnavailableError(
                "Falta LLM_API_KEY para el proveedor OpenAI-compatible. "
                "Completala en apps/audiomind/.env."
            )
        if not self.model:
            raise TransportUnavailableError(
                "Falta el modelo. Definí AGENT_MODEL_NAME en apps/audiomind/.env."
            )
        if not self.base_url:
            raise TransportUnavailableError(
                "Falta la URL del proveedor. Definí LLM_BASE_URL "
                "en apps/audiomind/.env."
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
            "messages": self._messages(system, transcript),
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
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }

    def _messages(
        self, system: str, transcript: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]

        for entry in assign_call_ids(transcript):
            if "function_call" in entry:
                call = entry["function_call"]
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call["id"],
                                "type": "function",
                                "function": {
                                    "name": call["name"],
                                    "arguments": json.dumps(call.get("args") or {}),
                                },
                            }
                        ],
                    }
                )
            elif "response" in entry:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": entry["id"],
                        "content": json.dumps(entry["response"]),
                    }
                )
            else:
                role = "assistant" if entry.get("role") == "model" else "user"
                messages.append({"role": role, "content": entry.get("text", "")})

        return messages

    def _parse(self, phase: str, payload: dict[str, Any]) -> ModelTurn:
        choices = payload.get("choices") or []
        if not choices:
            raise TransportUnavailableError(
                f"El proveedor no devolvió contenido en {phase}: {payload!r}"
            )

        message = choices[0].get("message") or {}
        calls = [
            ToolCall(
                name=raw["function"]["name"],
                args=_arguments(raw["function"].get("arguments")),
            )
            for raw in (message.get("tool_calls") or [])
            if (raw.get("function") or {}).get("name")
        ]
        text = (message.get("content") or "").strip()

        if calls or text:
            return ModelTurn(text=text, tool_calls=calls)
        raise TransportUnavailableError(
            f"El proveedor devolvió un turno vacío en {phase}: {payload!r}"
        )

    # -- Red ---------------------------------------------------------------

    def _post(self, phase: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions", json=body, headers=headers
            )
            response.raise_for_status()
            return dict(response.json())
        except httpx.HTTPError as exc:
            raise TransportUnavailableError(
                f"Falló la llamada a {self.base_url} en {phase}: {exc}"
            ) from exc
