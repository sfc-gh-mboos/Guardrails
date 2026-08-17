import os

import pytest

pytest.importorskip("openai", reason="openai is required for server tests")
from fastapi.testclient import TestClient

from nemoguardrails.server import api
from nemoguardrails.server.api import (
    GuardrailsApp,
    load_builtin_example_prompts,
    register_server_ui,
)

client = TestClient(api.app)

REQUIRED_PROMPT_KEYS = {"id", "name", "category", "expected", "content", "why"}
ALLOWED_CATEGORIES = {"allowed", "off-topic", "jailbreak", "harmful"}
ALLOWED_EXPECTED = {"pass", "block"}


def test_playground_is_served_at_root():
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Guardrails Playground" in response.text
    assert "Example prompts" in response.text
    assert "ui/app.js" in response.text
    assert "ui/styles.css" in response.text


def test_playground_static_assets_are_served():
    js = client.get("/ui/app.js")
    css = client.get("/ui/styles.css")

    assert js.status_code == 200
    assert "chat/completions" in js.text
    assert "activated_rails" in js.text
    assert css.status_code == 200
    assert "--accent" in css.text


def test_example_prompt_bank_is_valid():
    response = client.get("/ui/example-prompts.json")

    assert response.status_code == 200
    prompts = response.json()
    assert isinstance(prompts, list)
    assert len(prompts) >= 8

    ids = [prompt["id"] for prompt in prompts]
    assert len(ids) == len(set(ids))

    for prompt in prompts:
        assert REQUIRED_PROMPT_KEYS <= set(prompt)
        assert prompt["category"] in ALLOWED_CATEGORIES
        assert prompt["expected"] in ALLOWED_EXPECTED
        assert prompt["content"].strip()
        if "configs" in prompt:
            assert isinstance(prompt["configs"], list)


def test_builtin_example_prompts_match_static_file():
    bundled = load_builtin_example_prompts()
    static = client.get("/ui/example-prompts.json").json()

    assert bundled == static


def test_challenges_fall_back_to_example_prompt_bank(monkeypatch):
    monkeypatch.setattr(api, "challenges", [])

    response = client.get("/v1/challenges")

    assert response.status_code == 200
    assert response.json() == load_builtin_example_prompts()


def test_challenges_prefer_registered_entries(monkeypatch):
    custom = [{"name": "custom", "content": "hello from a registered challenge"}]
    monkeypatch.setattr(api, "challenges", custom)

    response = client.get("/v1/challenges")

    assert response.status_code == 200
    assert response.json() == custom


def test_disabled_ui_returns_status_payload():
    application = GuardrailsApp()
    application.disable_chat_ui = True
    register_server_ui(application)

    response = TestClient(application).get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_example_prompts_file_is_packaged():
    ui_dir = os.path.join(os.path.dirname(api.__file__), "ui")
    assert os.path.isfile(os.path.join(ui_dir, "example-prompts.json"))
    with open(os.path.join(ui_dir, "index.html"), encoding="utf-8") as handle:
        html = handle.read()
    assert "prompt-input" in html
    assert "results" in html
