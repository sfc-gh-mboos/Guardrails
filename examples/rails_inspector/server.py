"""Rails Inspector: a small web UI for seeing what guardrails do to a prompt.

Run it against the bundled offline demo config::

    python examples/rails_inspector/server.py

Or against your own guardrails configuration::

    python examples/rails_inspector/server.py --config path/to/config --prompts path/to/prompts.json

The UI sends one prompt at a time through ``LLMRails.generate_async`` with the
``activated_rails`` generation log enabled, then shows the prompt, the prompt the
model actually received, the raw model output, the final response, and every
rail that ran along the way.

Requires the server extra: ``pip install nemoguardrails[server]``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nemoguardrails import LLMRails, RailsConfig
from nemoguardrails.rails.llm.options import GenerationLog, GenerationOptions

APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
DEMO_CONFIG_DIR = APP_DIR / "demo_config"
DEMO_PROMPTS_PATH = APP_DIR / "prompts.json"

# Context variables the UI needs to explain what the rails did.
OUTPUT_VARS = [
    "user_message",
    "bot_message",
    "triggered_input_rail",
    "triggered_output_rail",
]

log = logging.getLogger(__name__)


class PromptBankEntry(BaseModel):
    text: str
    expected: Optional[str] = None


class PromptBankGroup(BaseModel):
    name: str
    description: Optional[str] = None
    prompts: List[PromptBankEntry] = Field(default_factory=list)


class PromptBank(BaseModel):
    groups: List[PromptBankGroup] = Field(default_factory=list)


class ConfigInfo(BaseModel):
    config_id: str
    config_path: str
    main_model: str
    scripted_demo_model: bool = Field(
        description="True when no model provider is configured and the scripted demo model answers instead."
    )
    input_rails: List[str] = Field(default_factory=list)
    output_rails: List[str] = Field(default_factory=list)
    retrieval_rails: List[str] = Field(default_factory=list)


class RailTrace(BaseModel):
    stage: str = Field(description="Rail stage: input, dialog, generation, retrieval, or output.")
    name: str
    effect: str = Field(description="What the rail did: passed, modified, or blocked.")
    reason: Optional[str] = None
    detections: List[str] = Field(default_factory=list)
    duration_ms: Optional[float] = None
    actions: List[str] = Field(default_factory=list)


class LLMCallTrace(BaseModel):
    task: Optional[str] = None
    duration_ms: Optional[float] = None
    total_tokens: Optional[int] = None


class RunRequest(BaseModel):
    prompt: str


class RunResponse(BaseModel):
    verdict: str = Field(description="Overall outcome: passed, modified, or blocked.")
    blocked_by: Optional[str] = None
    blocked_stage: Optional[str] = None
    prompt: str
    prompt_after_input_rails: Optional[str] = None
    input_modified: bool = False
    model_called: bool = False
    model_output: Optional[str] = None
    response: str
    output_modified: bool = False
    rails: List[RailTrace] = Field(default_factory=list)
    llm_calls: List[LLMCallTrace] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)


def _seconds_to_ms(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value * 1000, 1)


def _rail_evidence(rail) -> tuple[bool, Optional[str], List[str]]:
    """Pull transform status, reason, and detections out of a rail's actions.

    Rails in the catalog return a ``RailOutcome``; custom rails may return
    anything, so every field is read defensively.
    """
    transformed = False
    reason: Optional[str] = None
    detections: List[str] = []

    for executed_action in rail.executed_actions:
        outcome = executed_action.return_value
        if getattr(outcome, "is_transform", False):
            transformed = True
        if reason is None and isinstance(getattr(outcome, "reason", None), str):
            reason = outcome.reason
        metadata = getattr(outcome, "metadata", None)
        if isinstance(metadata, dict):
            for key in ("detections", "topics", "categories"):
                values = metadata.get(key)
                if isinstance(values, list):
                    detections.extend(str(value) for value in values)

    # Preserve order while dropping repeats of the same detection label.
    return transformed, reason, list(dict.fromkeys(detections))


def _trace_rails(generation_log: GenerationLog) -> List[RailTrace]:
    traces = []
    for rail in generation_log.activated_rails:
        transformed, reason, detections = _rail_evidence(rail)
        if rail.stop:
            effect = "blocked"
        elif transformed:
            effect = "modified"
        else:
            effect = "passed"

        traces.append(
            RailTrace(
                stage=rail.type,
                name=rail.name,
                effect=effect,
                reason=reason,
                detections=detections,
                duration_ms=_seconds_to_ms(rail.duration),
                actions=[action.action_name for action in rail.executed_actions],
            )
        )
    return traces


def _model_output(generation_log: GenerationLog, internal_events: Optional[List[dict]]) -> Optional[str]:
    """The bot message produced by generation, before any output rail ran."""
    events = internal_events or []
    output_rails_start = next(
        (index for index, event in enumerate(events) if event.get("type") == "StartOutputRails"),
        len(events),
    )
    bot_messages = [
        event.get("text")
        for event in events[:output_rails_start]
        if event.get("type") == "BotMessage" and event.get("text")
    ]
    if bot_messages:
        return bot_messages[-1]

    # No internal events (or no bot message in them): fall back to the last
    # generation-style LLM call, skipping LLM calls made by the rails themselves.
    generation_tasks = {"general", "generate_bot_message"}
    completions = [
        call.completion for call in (generation_log.llm_calls or []) if call.task in generation_tasks and call.completion
    ]
    return completions[-1] if completions else None


def _first_message_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, list) and response:
        return str(response[-1].get("content", ""))
    return ""


def build_run_response(prompt: str, generation_response) -> RunResponse:
    """Turn a raw generation response into the flat shape the UI renders."""
    generation_log = generation_response.log
    output_data = generation_response.output_data or {}
    final_response = _first_message_text(generation_response.response)

    rails = _trace_rails(generation_log)
    blocking_rail = next((rail for rail in rails if rail.effect == "blocked"), None)

    input_blocked = blocking_rail is not None and blocking_rail.stage == "input"
    prompt_after_input_rails = None if input_blocked else output_data.get("user_message")

    model_output = None if input_blocked else _model_output(generation_log, generation_log.internal_events)

    if blocking_rail is not None:
        verdict = "blocked"
    elif (prompt_after_input_rails is not None and prompt_after_input_rails != prompt) or (
        model_output is not None and model_output != final_response
    ):
        verdict = "modified"
    else:
        verdict = "passed"

    return RunResponse(
        verdict=verdict,
        blocked_by=blocking_rail.name if blocking_rail else None,
        blocked_stage=blocking_rail.stage if blocking_rail else None,
        prompt=prompt,
        prompt_after_input_rails=prompt_after_input_rails,
        input_modified=prompt_after_input_rails is not None and prompt_after_input_rails != prompt,
        model_called=model_output is not None,
        model_output=model_output,
        response=final_response,
        output_modified=model_output is not None and model_output != final_response,
        rails=rails,
        llm_calls=[
            LLMCallTrace(
                task=call.task,
                duration_ms=_seconds_to_ms(call.duration),
                total_tokens=call.total_tokens,
            )
            for call in (generation_log.llm_calls or [])
        ],
        stats={
            "total_ms": _seconds_to_ms(generation_log.stats.total_duration),
            "input_rails_ms": _seconds_to_ms(generation_log.stats.input_rails_duration),
            "generation_ms": _seconds_to_ms(generation_log.stats.generation_rails_duration),
            "output_rails_ms": _seconds_to_ms(generation_log.stats.output_rails_duration),
            "llm_calls_count": generation_log.stats.llm_calls_count,
            "llm_calls_total_tokens": generation_log.stats.llm_calls_total_tokens,
        },
    )


def _load_prompt_bank(prompts_path: Path) -> PromptBank:
    if not prompts_path.exists():
        return PromptBank()
    return PromptBank.model_validate(json.loads(prompts_path.read_text(encoding="utf-8")))


def _main_model_name(config: RailsConfig) -> str:
    for model in config.models:
        if model.type == "main":
            return f"{model.engine}/{model.model}" if model.model else str(model.engine)
    return ""


def _flow_names(flows) -> List[str]:
    return [flow if isinstance(flow, str) else str(flow) for flow in flows]


def _load_scripted_demo_model():
    """Import the bundled demo model by path so this script runs from anywhere."""
    spec = importlib.util.spec_from_file_location("rails_inspector_demo_model", APP_DIR / "demo_model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ScriptedDemoModel()


def create_app(config_path: Path = DEMO_CONFIG_DIR, prompts_path: Path = DEMO_PROMPTS_PATH) -> FastAPI:
    config_path = Path(config_path).resolve()
    config = RailsConfig.from_path(str(config_path))

    # With no model provider configured there is nothing to generate with, so the
    # bundled scripted model answers instead. This keeps the demo runnable offline
    # and is surfaced in the UI so results are never mistaken for a real model.
    scripted_demo_model = not config.models
    rails = LLMRails(config, llm=_load_scripted_demo_model()) if scripted_demo_model else LLMRails(config)

    prompt_bank = _load_prompt_bank(Path(prompts_path))

    app = FastAPI(title="NeMo Guardrails Rails Inspector")

    @app.get("/api/config", response_model=ConfigInfo)
    async def get_config() -> ConfigInfo:
        return ConfigInfo(
            config_id=config_path.name,
            config_path=str(config_path),
            main_model=_main_model_name(config),
            scripted_demo_model=scripted_demo_model,
            input_rails=_flow_names(config.rails.input.flows),
            output_rails=_flow_names(config.rails.output.flows),
            retrieval_rails=_flow_names(config.rails.retrieval.flows),
        )

    @app.get("/api/prompts", response_model=PromptBank)
    async def get_prompts() -> PromptBank:
        return prompt_bank

    @app.post("/api/run", response_model=RunResponse)
    async def run_prompt(request: RunRequest) -> RunResponse:
        prompt = request.prompt.strip()
        if not prompt:
            raise HTTPException(status_code=422, detail="The prompt must not be empty.")

        generation_response = await rails.generate_async(
            messages=[{"role": "user", "content": prompt}],
            options=GenerationOptions(
                log={"activated_rails": True, "llm_calls": True, "internal_events": True},
                output_vars=OUTPUT_VARS,
            ),
        )
        return build_run_response(prompt, generation_response)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the NeMo Guardrails Rails Inspector UI.")
    parser.add_argument(
        "--config",
        default=str(DEMO_CONFIG_DIR),
        help="Path to the guardrails configuration directory (default: the bundled demo config).",
    )
    parser.add_argument(
        "--prompts",
        default=str(DEMO_PROMPTS_PATH),
        help="Path to a JSON prompt bank (default: the bundled prompt bank).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(Path(args.config), Path(args.prompts)), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
