"""Provider dispatch for the LLM layer — guard behavior without network."""

from __future__ import annotations

import pytest

from src.errors import ConfigError
from src.llm import complete_json, vision
from tests.conftest import make_settings


def test_resolved_vision_provider_inherits_llm_provider():
    assert make_settings(llm_provider="openai", vision_provider="").resolved_vision_provider == "openai"
    assert (
        make_settings(llm_provider="anthropic", vision_provider="openai").resolved_vision_provider
        == "openai"
    )


def test_vision_returns_empty_without_key():
    s_openai = make_settings(vision_provider="openai", openai_api_key="")
    assert vision("prompt", b"\x89PNG\r\n", s_openai) == ""
    s_anthropic = make_settings(vision_provider="anthropic", anthropic_api_key="")
    assert vision("prompt", b"\x89PNG\r\n", s_anthropic) == ""


def test_complete_json_missing_key_raises():
    with pytest.raises(ConfigError):
        complete_json("sys", "user", settings=make_settings(llm_provider="openai", openai_api_key=""))
    with pytest.raises(ConfigError):
        complete_json(
            "sys", "user", settings=make_settings(llm_provider="anthropic", anthropic_api_key="")
        )
