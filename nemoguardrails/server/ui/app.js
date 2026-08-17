const CATEGORIES = [
  { id: "all", label: "All" },
  { id: "allowed", label: "Allowed" },
  { id: "jailbreak", label: "Jailbreak" },
  { id: "harmful", label: "Harmful" },
  { id: "pii", label: "PII" },
  { id: "output", label: "Output rail" },
  { id: "off-topic", label: "Off-topic" },
];

const EXPECTED_LABELS = {
  allow: "Expected: allow",
  "block-input": "Expected: input rail blocks",
  "block-output": "Expected: output rail blocks",
  "block-dialog": "Expected: dialog rail refuses",
};

const state = {
  prompts: [],
  category: "all",
  selectedId: null,
};

const els = {
  filters: document.getElementById("filters"),
  promptList: document.getElementById("prompt-list"),
  configId: document.getElementById("config-id"),
  model: document.getElementById("model"),
  prompt: document.getElementById("prompt"),
  preserve: document.getElementById("preserve-config-model"),
  compare: document.getElementById("compare"),
  run: document.getElementById("run"),
  status: document.getElementById("status"),
  results: document.getElementById("results"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!response.ok) {
    const detail = data && typeof data === "object" ? data.detail || data.message || JSON.stringify(data) : text;
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return data;
}

function normalizePrompt(raw, source) {
  const content = raw.content || raw.message || raw.prompt || "";
  if (!content) {
    return null;
  }
  return {
    id: raw.id || `${source}-${content.slice(0, 24)}`,
    name: raw.name || raw.label || content.slice(0, 40),
    category: raw.category || "allowed",
    expected: raw.expected || "",
    content,
    description: raw.description || "",
  };
}

function mergePrompts(builtIn, challenges) {
  const byId = new Map();
  for (const item of [...builtIn, ...challenges]) {
    const prompt = normalizePrompt(item, item.id ? "prompt" : "challenge");
    if (prompt) {
      byId.set(prompt.id, prompt);
    }
  }
  return [...byId.values()];
}

function renderFilters() {
  els.filters.innerHTML = CATEGORIES.map(
    (category) =>
      `<button type="button" role="tab" data-category="${category.id}" aria-selected="${
        state.category === category.id
      }">${category.label}</button>`,
  ).join("");
}

function renderPrompts() {
  const prompts = state.prompts.filter((prompt) => state.category === "all" || prompt.category === state.category);
  els.promptList.innerHTML = prompts
    .map((prompt) => {
      const expected = EXPECTED_LABELS[prompt.expected] || "";
      return `<li>
        <button type="button" class="prompt-card${prompt.id === state.selectedId ? " active" : ""}" data-id="${escapeHtml(
          prompt.id,
        )}">
          <strong>${escapeHtml(prompt.name)}</strong>
          <span>${escapeHtml(prompt.category)}${expected ? ` · ${expected}` : ""}</span>
        </button>
      </li>`;
    })
    .join("");
}

function selectedPrompt() {
  return state.prompts.find((prompt) => prompt.id === state.selectedId);
}

function extractAssistantText(payload) {
  const choice = payload?.choices?.[0]?.message;
  if (!choice) {
    return "";
  }
  if (typeof choice.content === "string") {
    return choice.content;
  }
  return JSON.stringify(choice.content ?? "", null, 2);
}

function summarizeImpact(payload) {
  const outputData = payload?.guardrails?.output_data || {};
  const log = payload?.guardrails?.log || {};
  const rails = log.activated_rails || [];
  const triggeredInput = outputData.triggered_input_rail;
  const triggeredOutput = outputData.triggered_output_rail;
  const stopped = rails.filter((rail) => rail.stop);
  let outcome = "allowed";
  if (triggeredInput || stopped.some((rail) => rail.type === "input")) {
    outcome = "blocked-input";
  } else if (triggeredOutput || stopped.some((rail) => rail.type === "output")) {
    outcome = "blocked-output";
  } else if (stopped.length) {
    outcome = "stopped";
  }
  return { outputData, log, rails, triggeredInput, triggeredOutput, stopped, outcome };
}

function outcomeBadge(outcome) {
  if (outcome === "allowed") {
    return `<span class="badge allow">Allowed</span>`;
  }
  if (outcome === "blocked-input") {
    return `<span class="badge block">Blocked by input rail</span>`;
  }
  if (outcome === "blocked-output") {
    return `<span class="badge block">Blocked by output rail</span>`;
  }
  return `<span class="badge warn">Stopped by a rail</span>`;
}

function renderRailTable(rails) {
  if (!rails.length) {
    return `<p class="hint">No rails were activated. Enable log.activated_rails or choose a config that defines rails.</p>`;
  }
  const rows = rails
    .map((rail) => {
      const decisions = (rail.decisions || []).join(", ") || "—";
      const actions = (rail.executed_actions || []).map((action) => action.action_name).join(", ") || "—";
      const duration = rail.duration == null ? "—" : `${Number(rail.duration).toFixed(2)}s`;
      const stop = rail.stop ? "yes" : "no";
      return `<tr>
        <td>${escapeHtml(rail.type)}</td>
        <td>${escapeHtml(rail.name)}</td>
        <td>${escapeHtml(stop)}</td>
        <td>${escapeHtml(decisions)}</td>
        <td>${escapeHtml(actions)}</td>
        <td>${escapeHtml(duration)}</td>
      </tr>`;
    })
    .join("");
  return `<table class="rail-table">
    <thead>
      <tr>
        <th>Type</th>
        <th>Name</th>
        <th>Stopped</th>
        <th>Decisions</th>
        <th>Actions</th>
        <th>Duration</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function renderRun(title, input, payload) {
  const impact = summarizeImpact(payload);
  const stats = impact.log.stats || {};
  const llmCalls = impact.log.llm_calls || [];
  return `<article class="result-block">
    <h3>${escapeHtml(title)}</h3>
    <div class="badge-row">
      ${outcomeBadge(impact.outcome)}
      <span class="badge">triggered input: ${escapeHtml(impact.triggeredInput || "none")}</span>
      <span class="badge">triggered output: ${escapeHtml(impact.triggeredOutput || "none")}</span>
      ${stats.total_duration != null ? `<span class="badge">${Number(stats.total_duration).toFixed(2)}s total</span>` : ""}
      ${llmCalls.length ? `<span class="badge">${llmCalls.length} LLM call${llmCalls.length === 1 ? "" : "s"}</span>` : ""}
    </div>
    <h3>Confirmed input</h3>
    <pre class="pre">${escapeHtml(input)}</pre>
    <h3>Output</h3>
    <pre class="pre">${escapeHtml(extractAssistantText(payload) || "(empty)")}</pre>
    <h3>Activated rails</h3>
    ${renderRailTable(impact.rails)}
  </article>`;
}

function setStatus(message, isError = false) {
  els.status.textContent = message;
  els.status.classList.toggle("error", isError);
}

async function loadConfigs() {
  const configs = await fetchJson("/v1/rails/configs");
  const ids = (configs || []).map((item) => item.id);
  if (!ids.length) {
    els.configId.innerHTML = `<option value="">No configurations found</option>`;
    return;
  }
  const preferred = ids.includes("playground") ? "playground" : ids[0];
  els.configId.innerHTML = ids.map((id) => `<option value="${escapeHtml(id)}">${escapeHtml(id)}</option>`).join("");
  els.configId.value = preferred;
}

async function loadPrompts() {
  const [builtIn, challenges] = await Promise.all([
    fetchJson("/playground/prompts.json"),
    fetchJson("/v1/challenges").catch(() => []),
  ]);
  state.prompts = mergePrompts(Array.isArray(builtIn) ? builtIn : [], Array.isArray(challenges) ? challenges : []);
  renderFilters();
  renderPrompts();
}

function buildRequest(prompt, railsEnabled) {
  const options = {
    output_vars: ["triggered_input_rail", "triggered_output_rail", "allowed"],
    log: {
      activated_rails: true,
      llm_calls: true,
    },
  };
  if (!railsEnabled) {
    options.rails = {
      input: false,
      output: false,
      retrieval: false,
      tool_input: false,
      tool_output: false,
    };
  }
  return {
    model: els.model.value.trim() || "echo",
    messages: [{ role: "user", content: prompt }],
    guardrails: {
      config_id: els.configId.value,
      preserve_config_model: els.preserve.checked,
      options,
    },
  };
}

async function runPrompt() {
  const prompt = els.prompt.value.trim();
  if (!prompt) {
    setStatus("Enter a prompt or choose one from the bank.", true);
    return;
  }
  if (!els.configId.value) {
    setStatus("Select a guardrails configuration.", true);
    return;
  }

  els.run.disabled = true;
  setStatus("Running…");
  try {
    const guarded = await fetchJson("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildRequest(prompt, true)),
    });
    let html = renderRun("With rails", prompt, guarded);
    if (els.compare.checked) {
      const raw = await fetchJson("/v1/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildRequest(prompt, false)),
      });
      html += renderRun("Without rails", prompt, raw);
    }
    els.results.innerHTML = html;
    setStatus("Done.");
  } catch (error) {
    els.results.innerHTML = `<article class="result-block"><h3>Request failed</h3><pre class="pre error">${escapeHtml(
      error.message,
    )}</pre></article>`;
    setStatus(error.message, true);
  } finally {
    els.run.disabled = false;
  }
}

els.filters.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-category]");
  if (!button) {
    return;
  }
  state.category = button.dataset.category;
  renderFilters();
  renderPrompts();
});

els.promptList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-id]");
  if (!button) {
    return;
  }
  state.selectedId = button.dataset.id;
  const prompt = selectedPrompt();
  if (prompt) {
    els.prompt.value = prompt.content;
  }
  renderPrompts();
});

els.run.addEventListener("click", () => {
  runPrompt();
});

els.prompt.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    runPrompt();
  }
});

setStatus("Loading configurations…");
Promise.all([loadConfigs(), loadPrompts()])
  .then(() => setStatus("Ready."))
  .catch((error) => setStatus(error.message, true));
