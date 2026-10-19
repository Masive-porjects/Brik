"""S1/H1/H2: every LLM knob must be a declared ``Settings`` field.

Why this file exists: ``Settings`` inherits ``extra="forbid"``. A key written in
``apps/audiomind/.env`` that no field declares is **not** ignored — it raises
``ValidationError`` while the settings object is built, which happens at import
time, so the whole backend refuses to boot. Measured against the real settings
class: appending ``GEMINI_API_KEY=...`` to the real ``.env`` produced
``Extra inputs are not permitted``.

So the operator-facing contract is: declare the knob, or the file breaks. These
tests pin both halves — the knobs are readable, and the loud failure stays.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from audiomind.config import Settings

# Both spellings the operator may reasonably type. The unprefixed pair is what
# the request asked for; the prefixed pair matches every other backend knob.
LLM_ENV_KEYS = (
    "LLM_PROVIDER",
    "AGENT_MODEL_NAME",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "GEMINI_API_KEY",
    "AUDIOMIND_LLM_PROVIDER",
    "AUDIOMIND_AGENT_MODEL_NAME",
    "AUDIOMIND_LLM_API_KEY",
    "AUDIOMIND_LLM_BASE_URL",
    "AUDIOMIND_GEMINI_API_KEY",
)


@pytest.fixture(autouse=True)
def _no_ambient_llm_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's exported key must never decide what the suite asserts."""
    for key in LLM_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _settings(tmp_path: Path, body: str) -> Settings:
    env_file = tmp_path / "probe.env"
    env_file.write_text(body, encoding="utf-8")
    return Settings(_env_file=str(env_file))


class TestDeclaredKnobs:
    def test_provider_defaults_to_gemini(self, tmp_path: Path) -> None:
        assert _settings(tmp_path, "").llm_provider == "gemini"

    def test_the_unprefixed_provider_name_is_read(self, tmp_path: Path) -> None:
        """The request names ``LLM_PROVIDER``, with no ``AUDIOMIND_`` prefix."""
        got = _settings(tmp_path, "LLM_PROVIDER=anthropic\n")
        assert got.llm_provider == "anthropic"

    def test_the_prefixed_provider_name_also_works(self, tmp_path: Path) -> None:
        got = _settings(tmp_path, "AUDIOMIND_LLM_PROVIDER=openai\n")
        assert got.llm_provider == "openai"

    def test_model_name_defaults_to_empty(self, tmp_path: Path) -> None:
        assert _settings(tmp_path, "").agent_model_name == ""

    def test_the_model_name_is_read(self, tmp_path: Path) -> None:
        got = _settings(tmp_path, "AGENT_MODEL_NAME=claude-3-5-sonnet\n")
        assert got.agent_model_name == "claude-3-5-sonnet"

    def test_gemini_key_is_read_from_the_env_file(self, tmp_path: Path) -> None:
        """H2: the transport reads ``os.environ``, which the env_file never fills."""
        got = _settings(tmp_path, "GEMINI_API_KEY=sk-abc\n")
        assert got.gemini_api_key == "sk-abc"

    def test_generic_key_and_base_url_are_read(self, tmp_path: Path) -> None:
        got = _settings(tmp_path, "LLM_API_KEY=k\nLLM_BASE_URL=http://box:1234/v1\n")
        assert got.llm_api_key == "k"
        assert got.llm_base_url == "http://box:1234/v1"

    def test_an_empty_file_leaves_every_knob_at_its_default(
        self, tmp_path: Path
    ) -> None:
        got = _settings(tmp_path, "")
        assert got.llm_api_key == ""
        assert got.llm_base_url == ""
        assert got.gemini_api_key == ""


class TestUnknownKeysStillFailLoudly:
    def test_a_typo_is_not_silently_ignored(self, tmp_path: Path) -> None:
        """``extra="forbid"`` is the feature. Declaring the knobs is the fix."""
        with pytest.raises(ValidationError):
            _settings(tmp_path, "LLM_PROVIDER_TYPO=oops\n")
