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

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class InspectRequest(BaseModel):
    """Request body for the rail inspector endpoint."""

    messages: List[dict] = Field(
        ...,
        min_length=1,
        description="Chat messages to inspect. Typically a single user message.",
    )
    config_id: Optional[str] = Field(
        default=None,
        description="Guardrails configuration ID. Uses the server default when omitted.",
    )


class InspectResponse(BaseModel):
    """Inspector payload: original prompt, final reply, and rail impact."""

    input: str = Field(description="Original user message sent to the inspector.")
    output: str = Field(description="Final assistant message after rails.")
    user_message_after_rails: Optional[str] = Field(
        default=None,
        description="User message after input rails (masked or unchanged).",
    )
    triggered_input_rail: Optional[str] = Field(
        default=None,
        description="Name of the input rail that blocked, if any.",
    )
    triggered_output_rail: Optional[str] = Field(
        default=None,
        description="Name of the output rail that blocked, if any.",
    )
    allowed: Optional[bool] = Field(
        default=None,
        description="Whether input rails allowed the request through.",
    )
    activated_rails: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Rails that ran, including decisions and stop flags.",
    )
    stats: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Timing stats for the generation.",
    )
    llm_calls: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="LLM calls made during generation, if any.",
    )
    output_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Context variables returned from generation.",
    )
    config_id: Optional[str] = Field(
        default=None,
        description="Configuration ID used for this inspect call.",
    )
