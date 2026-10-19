"""Elegir el proveedor del LLM con una línea en el ``.env``.

``LLM_PROVIDER`` mapea a un adaptador y ``AGENT_MODEL_NAME`` fija el modelo. El
registro es lo que hace que el bucle no sepa de qué proveedor se trata:
``agentic_loop.default_transport()`` sólo llama a ``build_transport()``.

Reglas que vale la pena conocer:

* **Ningún host se adivina.** Los alias que nombran un servidor concreto
  (DeepSeek, Ollama, Groq) traen su ``base_url``. ``openai-compatible`` nombra un
  PROTOCOLO, no un servidor: sin ``LLM_BASE_URL`` falla con un error que lo dice.
* **Ningún modelo se adivina, salvo donde el alias ya lo nombra.** ``deepseek``
  implica ``deepseek-chat``; el resto pide ``AGENT_MODEL_NAME`` explícito. Un
  modelo inventado para el proveedor equivocado falla lejos y confuso.
* **Una credencial ausente es un error tipado, no una llamada anónima.** Ollama
  es la excepción: un servidor local no tiene credencial que exigir.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from audiomind.config import settings
from audiomind.processing.agentic_loop import (
    ModelTransport,
    TransportUnavailableError,
)

#: Qué forma tiene la API del proveedor, no qué marca es.
TransportKind = Literal["gemini", "openai", "anthropic"]

#: Proveedor por defecto cuando nadie configura nada (S2: comportamiento actual).
DEFAULT_PROVIDER = "gemini"


@dataclass(frozen=True)
class ProviderSpec:
    """Lo mínimo para construir el adaptador sin preguntarle a nadie."""

    canonical: str
    kind: TransportKind
    base_url: str = ""
    requires_api_key: bool = True
    model_hint: str = ""


#: Alias (en minúsculas) -> cómo se construye. Varios alias comparten adaptador a
#: propósito: cada implementación extra es código que hay que mantener.
PROVIDERS: dict[str, ProviderSpec] = {
    "gemini": ProviderSpec("gemini", "gemini"),
    "google": ProviderSpec("gemini", "gemini"),
    "google-genai": ProviderSpec("gemini", "gemini"),
    "openai": ProviderSpec("openai", "openai", base_url="https://api.openai.com/v1"),
    "openai-compatible": ProviderSpec("openai-compatible", "openai"),
    "deepseek": ProviderSpec(
        "deepseek",
        "openai",
        base_url="https://api.deepseek.com/v1",
        model_hint="deepseek-chat",
    ),
    "ollama": ProviderSpec(
        "ollama",
        "openai",
        base_url="http://localhost:11434/v1",
        requires_api_key=False,
    ),
    "groq": ProviderSpec(
        "groq", "openai", base_url="https://api.groq.com/openai/v1"
    ),
    "anthropic": ProviderSpec(
        "anthropic", "anthropic", base_url="https://api.anthropic.com/v1"
    ),
    "claude": ProviderSpec(
        "anthropic", "anthropic", base_url="https://api.anthropic.com/v1"
    ),
}


def resolve_provider(name: str | None) -> ProviderSpec:
    """Alias -> especificación. Un nombre desconocido no cae a un default."""
    key = (name or settings.llm_provider or DEFAULT_PROVIDER).strip().lower()
    spec = PROVIDERS.get(key)
    if spec is None:
        known = ", ".join(sorted(PROVIDERS))
        raise TransportUnavailableError(
            f"Proveedor desconocido: {name!r}. LLM_PROVIDER acepta: {known}."
        )
    return spec


def build_transport(
    provider: str | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float | None = None,
    **extra: Any,
) -> ModelTransport:
    """Construye el transporte que pide la configuración.

    Precedencia: argumento explícito > ``.env`` > default del proveedor. El
    argumento explícito existe para los tests y para llamadores puntuales.
    """
    spec = resolve_provider(provider)

    resolved_model = (model or settings.agent_model_name or spec.model_hint).strip()
    resolved_key = (api_key or settings.llm_api_key or "").strip()
    if spec.kind == "gemini":
        resolved_key = resolved_key or settings.gemini_api_key.strip()
    resolved_base = (base_url or settings.llm_base_url or spec.base_url).strip()

    if spec.kind == "openai" and not resolved_base:
        raise TransportUnavailableError(
            f"El proveedor {spec.canonical!r} no tiene host por defecto. "
            "Definí LLM_BASE_URL en apps/audiomind/.env "
            "(por ejemplo http://localhost:1234/v1)."
        )
    if spec.kind != "gemini" and not resolved_model:
        raise TransportUnavailableError(
            f"El proveedor {spec.canonical!r} necesita un modelo explícito. "
            "Definí AGENT_MODEL_NAME en apps/audiomind/.env."
        )
    if spec.requires_api_key and not resolved_key:
        raise TransportUnavailableError(
            f"El proveedor {spec.canonical!r} necesita una credencial. "
            "Definí LLM_API_KEY en apps/audiomind/.env "
            "(para Gemini también sirve GEMINI_API_KEY)."
        )

    options: dict[str, Any] = dict(extra)
    if temperature is not None:
        options["temperature"] = temperature

    if spec.kind == "gemini":
        from audiomind.processing.gemini_transport import GeminiTransport

        # Modelo vacío = que Gemini elija: conserva su cadena de retiro.
        return GeminiTransport(
            api_key=resolved_key, model=resolved_model or None, **options
        )

    if spec.kind == "openai":
        from audiomind.processing.openai_compat_transport import (
            OpenAICompatTransport,
        )

        return OpenAICompatTransport(
            api_key=resolved_key,
            model=resolved_model,
            base_url=resolved_base,
            requires_api_key=spec.requires_api_key,
            **options,
        )

    from audiomind.processing.anthropic_transport import AnthropicTransport

    return AnthropicTransport(
        api_key=resolved_key,
        model=resolved_model,
        base_url=resolved_base,
        requires_api_key=spec.requires_api_key,
        **options,
    )
