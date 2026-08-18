# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Rails Inspector — small local UI for inspecting input/output rail impact.

Run from the repository root:

    uv run --locked python examples/rails_inspector/app.py

Then open http://127.0.0.1:7860
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nemoguardrails import LLMRails, RailsConfig
from nemoguardrails.rails.llm.options import GenerationResponse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo_replies import draft_assistant_reply  # noqa: E402

log = logging.getLogger(__name__)

CONFIG_DIR = ROOT / "config"
STATIC_DIR = ROOT / "static"
PROMPTS_PATH = ROOT / "prompts.json"

app = FastAPI(title="NeMo Guardrails Rails Inspector", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_rails: Optional[LLMRails] = None
_prompts: list[dict[str, Any]] = []


class InspectRequest(BaseModel):
    user: str = Field(..., min_length=1, description="User prompt to inspect.")
    assistant: Optional[str] = Field(
        default=None,
        description="Optional candidate assistant reply. When omitted, a deterministic demo reply is drafted.",
    )
    use_demo_reply: bool = Field(
        default=True,
        description="When True and assistant is empty, draft a demo reply before running output rails.",
    )


def _load_prompts() -> list[dict[str, Any]]:
    with PROMPTS_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def get_rails() -> LLMRails:
    global _rails
    if _rails is None:
        config = RailsConfig.from_path(str(CONFIG_DIR))
        _rails = LLMRails(config, verbose=False)
    return _rails


def _message_content(response: Any) -> str:
    if isinstance(response, GenerationResponse):
        response = response.response
    if isinstance(response, list) and response:
        first = response[0]
        if isinstance(first, dict):
            return str(first.get("content") or "")
        return str(first)
    if isinstance(response, dict):
        return str(response.get("content") or "")
    return str(response or "")


def _serialize_activated_rails(log_obj: Any) -> list[dict[str, Any]]:
    if log_obj is None or not getattr(log_obj, "activated_rails", None):
        return []
    rows: list[dict[str, Any]] = []
    for rail in log_obj.activated_rails:
        actions = []
        for action in rail.executed_actions or []:
            actions.append(
                {
                    "action_name": action.action_name,
                    "return_value": action.return_value,
                    "duration": action.duration,
                }
            )
        rows.append(
            {
                "type": rail.type,
                "name": rail.name,
                "decisions": list(rail.decisions or []),
                "stop": bool(rail.stop),
                "duration": rail.duration,
                "executed_actions": actions,
            }
        )
    return rows


def _impact_summary(
    *,
    user_text: str,
    candidate_assistant: Optional[str],
    final_text: str,
    activated: list[dict[str, Any]],
) -> dict[str, Any]:
    input_rails = [r for r in activated if r.get("type") == "input"]
    output_rails = [r for r in activated if r.get("type") == "output"]
    stopped = [r for r in activated if r.get("stop")]

    if any(r.get("stop") for r in input_rails):
        outcome = "input_blocked"
    elif any(r.get("stop") for r in output_rails):
        outcome = "output_blocked"
    elif candidate_assistant and final_text.strip() != candidate_assistant.strip():
        outcome = "modified"
    else:
        outcome = "passed"

    return {
        "outcome": outcome,
        "input_unchanged": True,
        "output_changed": bool(candidate_assistant)
        and final_text.strip() != (candidate_assistant or "").strip(),
        "blocking_rails": [r.get("name") for r in stopped],
        "input_rail_count": len(input_rails),
        "output_rail_count": len(output_rails),
        "user": user_text,
        "candidate_assistant": candidate_assistant,
        "final_assistant": final_text,
    }


@app.on_event("startup")
def startup() -> None:
    global _prompts
    _prompts = _load_prompts()
    get_rails()
    log.info("Rails Inspector ready with %s example prompts", len(_prompts))


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    rails = get_rails()
    return {
        "status": "ok",
        "engine": "LLMRails",
        "config_path": str(CONFIG_DIR),
        "prompt_count": len(_prompts),
        "input_flows": list(rails.config.rails.input.flows),
        "output_flows": list(rails.config.rails.output.flows),
    }


@app.get("/api/prompts")
async def prompts() -> dict[str, Any]:
    return {"prompts": _prompts}


@app.get("/api/config")
async def config_summary() -> dict[str, Any]:
    rails = get_rails()
    regex = getattr(rails.config.rails.config, "regex_detection", None)
    return {
        "input_flows": list(rails.config.rails.input.flows),
        "output_flows": list(rails.config.rails.output.flows),
        "regex_detection": regex.model_dump() if regex is not None else None,
    }


@app.post("/api/inspect")
async def inspect(body: InspectRequest) -> dict[str, Any]:
    user_text = body.user.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="user prompt is required")

    if body.assistant is not None and body.assistant.strip():
        candidate: Optional[str] = body.assistant.strip()
    elif body.use_demo_reply:
        candidate = draft_assistant_reply(user_text)
    else:
        candidate = None

    messages: list[dict[str, str]] = [{"role": "user", "content": user_text}]
    if candidate is not None:
        messages.append({"role": "assistant", "content": candidate})

    # Input/output rails only — no dialog or main-model generation.
    rails_to_run = ["input", "output"] if candidate is not None else ["input"]

    rails = get_rails()
    result = await rails.generate_async(
        messages=messages,
        options={
            "rails": rails_to_run,
            "log": {
                "activated_rails": True,
                "llm_calls": True,
            },
            "output_vars": [
                "triggered_input_rail",
                "triggered_output_rail",
                "allowed",
            ],
        },
    )

    final_text = _message_content(result)
    log_obj = result.log if isinstance(result, GenerationResponse) else None
    activated = _serialize_activated_rails(log_obj)
    output_data = result.output_data if isinstance(result, GenerationResponse) else None

    return {
        "messages_sent": messages,
        "rails_run": rails_to_run,
        "response": final_text,
        "output_data": output_data,
        "activated_rails": activated,
        "impact": _impact_summary(
            user_text=user_text,
            candidate_assistant=candidate,
            final_text=final_text,
            activated=activated,
        ),
        "stats": log_obj.stats.model_dump() if log_obj and log_obj.stats else None,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="127.0.0.1", port=7860, reload=False)


if __name__ == "__main__":
    main()
