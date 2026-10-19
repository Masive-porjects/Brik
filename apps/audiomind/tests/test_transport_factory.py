"""S1/S3: ``LLM_PROVIDER`` picks the adapter; one line in ``.env`` is the switch.

The registry is the whole point of the feature: no provider name may need a code
edit to be swapped. These tests pin the resolution table, the per-provider
defaults, and the honest failures.
"""
from __future__ import annotations

import pytest

from audiomind.processing import transport_factory as tf
from audiomind.processing.agentic_loop import TransportUnavailableError
from audiomind.processing.anthropic_transport import AnthropicTransport
from audiomind.processing.gemini_transport import GeminiTransport
from audiomind.processing.openai_compat_transport import OpenAICompatTransport

AMBIENT_KEYS = (
    "LLM_PROVIDER",
    "AGENT_MODEL_NAME",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "GEMINI_API_KEY",
)


@pytest.fixture(autouse=True)
def _no_ambient_llm_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the resolved config to its defaults, whatever the developer exported.

    Same reasoning as the suite's supabase and storage seals: a real key sitting
    in the developer's ``.env`` must not decide what these tests observe.
    """
    for key in AMBIENT_KEYS:
        monkeypatch.delenv(key, raising=False)
    fields = (
        "llm_provider",
        "agent_model_name",
        "llm_api_key",
        "llm_base_url",
        "gemini_api_key",
    )
    for field in fields:
        default = tf.settings.__class__.model_fields[field].default
        monkeypatch.setattr(tf.settings, field, default)


class TestProviderResolution:
    def test_no_provider_falls_back_to_gemini(self) -> None:
        """S2: an unset provider keeps the historic default."""
        assert isinstance(tf.build_transport(api_key="fake"), GeminiTransport)

    @pytest.mark.parametrize("alias", ["gemini", "google", "google-genai"])
    def test_gemini_aliases(self, alias: str) -> None:
        got = tf.build_transport(provider=alias, api_key="fake")
        assert isinstance(got, GeminiTransport)

    @pytest.mark.parametrize(
        "alias", ["openai", "deepseek", "ollama", "openai-compatible", "groq"]
    )
    def test_openai_compatible_aliases(self, alias: str) -> None:
        # ``openai-compatible`` names a protocol, not a server, so it needs an
        # explicit host while the rest carry theirs. The dedicated test below
        # pins that difference.
        got = tf.build_transport(
            provider=alias, api_key="k", model="m", base_url="http://box:1234/v1"
        )
        assert isinstance(got, OpenAICompatTransport)

    @pytest.mark.parametrize("alias", ["anthropic", "claude"])
    def test_anthropic_aliases(self, alias: str) -> None:
        got = tf.build_transport(provider=alias, api_key="k", model="m")
        assert isinstance(got, AnthropicTransport)

    def test_resolution_ignores_case_and_padding(self) -> None:
        got = tf.build_transport(provider="  Anthropic ", api_key="k", model="m")
        assert isinstance(got, AnthropicTransport)

    def test_an_unknown_provider_is_a_typed_failure(self) -> None:
        with pytest.raises(TransportUnavailableError):
            tf.build_transport(provider="skynet", api_key="k", model="m")

    def test_the_error_lists_the_known_providers(self) -> None:
        with pytest.raises(TransportUnavailableError) as caught:
            tf.build_transport(provider="skynet", api_key="k", model="m")
        assert "gemini" in str(caught.value)


class TestProviderDefaults:
    def test_deepseek_gets_its_own_host(self) -> None:
        got = tf.build_transport(provider="deepseek", api_key="k")
        assert got.base_url == "https://api.deepseek.com/v1"

    def test_deepseek_carries_its_model_hint(self) -> None:
        got = tf.build_transport(provider="deepseek", api_key="k")
        assert got.model == "deepseek-chat"

    def test_ollama_points_at_the_local_server(self) -> None:
        got = tf.build_transport(provider="ollama", model="llama3.2")
        assert got.base_url == "http://localhost:11434/v1"

    def test_an_explicit_base_url_wins_over_the_default(self) -> None:
        got = tf.build_transport(
            provider="ollama", model="llama3.2", base_url="http://box:1234/v1"
        )
        assert got.base_url == "http://box:1234/v1"

    def test_a_provider_whose_host_cannot_be_guessed_asks_for_one(self) -> None:
        """``openai-compatible`` names a protocol, not a server."""
        with pytest.raises(TransportUnavailableError) as caught:
            tf.build_transport(provider="openai-compatible", api_key="k", model="m")
        assert "LLM_BASE_URL" in str(caught.value)


class TestKeys:
    def test_ollama_starts_without_a_key(self) -> None:
        """A local server has no credential to demand."""
        assert tf.build_transport(provider="ollama", model="llama3.2").api_key == ""

    @pytest.mark.parametrize("alias", ["deepseek", "anthropic", "openai"])
    def test_a_hosted_provider_refuses_to_start_without_a_key(self, alias: str) -> None:
        with pytest.raises(TransportUnavailableError) as caught:
            tf.build_transport(provider=alias, model="m")
        assert "LLM_API_KEY" in str(caught.value)

    def test_the_generic_key_is_read_from_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tf.settings, "llm_api_key", "from-env")
        got = tf.build_transport(provider="deepseek", model="m")
        assert got.api_key == "from-env"

    def test_the_gemini_key_field_is_used_for_gemini(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tf.settings, "gemini_api_key", "gem-from-env")
        got = tf.build_transport(provider="gemini")
        assert got.api_key == "gem-from-env"

    def test_an_explicit_key_wins_over_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tf.settings, "llm_api_key", "from-env")
        got = tf.build_transport(provider="deepseek", api_key="explicit")
        assert got.api_key == "explicit"


class TestModelNameComesFromConfig:
    def test_the_model_hint_is_an_env_key_not_an_argument(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tf.settings, "agent_model_name", "claude-3-5-sonnet")
        got = tf.build_transport(provider="anthropic", api_key="k")
        assert got.model == "claude-3-5-sonnet"

    def test_an_explicit_model_argument_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tf.settings, "agent_model_name", "from-env")
        got = tf.build_transport(provider="anthropic", api_key="k", model="explicit")
        assert got.model == "explicit"

    def test_a_provider_with_no_model_hint_asks_for_the_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tf.settings, "agent_model_name", "")
        with pytest.raises(TransportUnavailableError) as caught:
            tf.build_transport(provider="openai", api_key="k")
        assert "AGENT_MODEL_NAME" in str(caught.value)

    def test_gemini_keeps_its_own_default_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """S2: with no model configured, Gemini uses its retirement ladder."""
        monkeypatch.setattr(tf.settings, "agent_model_name", "")
        got = tf.build_transport(provider="gemini", api_key="fake")
        assert isinstance(got, GeminiTransport)
        assert len(got.models) >= 2

    def test_the_provider_comes_from_settings_when_not_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One line in ``.env``, no argument: this is the S3 switch."""
        monkeypatch.setattr(tf.settings, "llm_provider", "anthropic")
        monkeypatch.setattr(tf.settings, "agent_model_name", "claude-3-5-sonnet")
        monkeypatch.setattr(tf.settings, "llm_api_key", "k")
        assert isinstance(tf.build_transport(), AnthropicTransport)
