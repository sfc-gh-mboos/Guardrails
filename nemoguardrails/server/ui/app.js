const CATEGORY_LABELS = {
  allowed: "Allowed",
  jailbreak: "Jailbreak",
  harmful: "Harmful",
  mask: "PII / mask",
  output: "Output rail",
  "off-topic": "Off-topic",
};

const state = {
  prompts: [],
  category: "all",
  selectedId: null,
};

const els = {
  config: document.getElementById("config-id"),
  categories: document.getElementById("categories"),
  examples: document.getElementById("examples"),
  prompt: document.getElementById("prompt"),
  promptNote: document.getElementById("prompt-note"),
  compare: document.getElementById("compare"),
  run: document.getElementById("run"),
  status: document.getElementById("status"),
  results: document.getElementById("results"),
};

function selectedPrompt() {
  return state.prompts.find((item) => item.id === state.selectedId) || null;
}

function setStatus(message, isError = false) {
  els.status.textContent = message;
  els.status.classList.toggle("error", isError);
}

function renderCategories() {
  const categories = ["all", ...new Set(state.prompts.map((item) => item.category))];
  els.categories.replaceChildren(
    ...categories.map((category) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `chip${state.category === category ? " active" : ""}`;
      button.textContent = category === "all" ? "All" : CATEGORY_LABELS[category] || category;
      button.addEventListener("click", () => {
        state.category = category;
        renderCategories();
        renderExamples();
      });
      return button;
    }),
  );
}

function renderExamples() {
  const visible = state.prompts.filter((item) => state.category === "all" || item.category === state.category);
  els.examples.replaceChildren(
    ...visible.map((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `example${item.id === state.selectedId ? " active" : ""}`;
      button.textContent = item.name;
      button.title = item.description || item.content;
      button.addEventListener("click", () => selectPrompt(item.id, { updateUrl: true }));
      return button;
    }),
  );
}

function selectPrompt(id, { updateUrl = false } = {}) {
  const item = state.prompts.find((prompt) => prompt.id === id);
  if (!item) {
    return;
  }
  state.selectedId = item.id;
  els.prompt.value = item.content;
  els.promptNote.textContent = item.description || "";
  renderExamples();
  if (updateUrl) {
    const url = new URL(window.location.href);
    url.searchParams.set("prompt", item.id);
    window.history.replaceState({}, "", url);
  }
}

function impactLabel(payload) {
  const rails = payload?.guardrails?.log?.activated_rails || [];
  const outputData = payload?.guardrails?.output_data || {};
  const stopped = rails.find((rail) => rail.stop);
  if (stopped) {
    return { kind: "block", text: `${stopped.name} blocked` };
  }
  if (outputData.triggered_input_rail) {
    return { kind: "block", text: `${outputData.triggered_input_rail} blocked` };
  }
  if (outputData.triggered_output_rail) {
    return { kind: "block", text: `${outputData.triggered_output_rail} blocked` };
  }
  const decisions = rails.flatMap((rail) => rail.decisions || []);
  if (decisions.some((decision) => /mask|redact|transform/i.test(decision))) {
    const rail = rails.find((item) => (item.decisions || []).some((decision) => /mask|redact|transform/i.test(decision)));
    return { kind: "mask", text: `${rail ? rail.name : "rail"} transformed` };
  }
  const masked = rails.find((rail) => /mask/i.test(rail.name || ""));
  if (masked) {
    return { kind: "mask", text: `${masked.name} transformed` };
  }
  return { kind: "pass", text: "Allowed" };
}

function railRows(payload) {
  const rails = payload?.guardrails?.log?.activated_rails || [];
  if (!rails.length) {
    return '<p class="hint">No activated rails were returned for this run.</p>';
  }
  return `<div class="rails">${rails
    .map((rail) => {
      const kind = rail.stop ? "block" : /mask/i.test(rail.name || "") ? "mask" : "pass";
      const detail = rail.stop ? "blocked" : kind === "mask" ? "transformed" : "ran";
      return `<div class="rail"><span>${rail.type || "rail"} · ${rail.name}</span><span class="badge ${kind}">${detail}</span></div>`;
    })
    .join("")}</div>`;
}

function messageText(payload) {
  return payload?.choices?.[0]?.message?.content || "";
}

function renderColumn(title, payload, input) {
  const impact = impactLabel(payload);
  return `
    <article class="card">
      <h3>${title} <span class="badge ${impact.kind}">${impact.text}</span></h3>
      <div class="block"><p>Confirmed input</p><pre>${escapeHtml(input)}</pre></div>
      <div class="block"><p>Output</p><pre>${escapeHtml(messageText(payload))}</pre></div>
      <div class="block"><p>Rails</p>${railRows(payload)}</div>
    </article>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload.error?.message || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

async function complete(prompt, railsEnabled) {
  const rails = railsEnabled
    ? {}
    : { input: false, output: false, dialog: false, retrieval: false, tool_input: false, tool_output: false };
  return fetchJson("/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "echo",
      messages: [{ role: "user", content: prompt }],
      guardrails: {
        config_id: els.config.value,
        preserve_config_model: true,
        options: {
          rails,
          output_vars: ["triggered_input_rail", "triggered_output_rail"],
          log: { activated_rails: true },
        },
      },
    }),
  });
}

async function run() {
  const prompt = els.prompt.value.trim();
  if (!prompt) {
    setStatus("Enter a prompt or pick an example.", true);
    return;
  }
  if (!els.config.value) {
    setStatus("No guardrails configuration is available.", true);
    return;
  }

  els.run.disabled = true;
  setStatus("Running…");
  try {
    const guarded = await complete(prompt, true);
    const columns = [renderColumn("With rails", guarded, prompt)];
    if (els.compare.checked) {
      const unguarded = await complete(prompt, false);
      columns.push(renderColumn("Rails off", unguarded, prompt));
    }
    els.results.className = els.compare.checked ? "compare" : "";
    els.results.innerHTML = columns.join("");
    setStatus("Done.");
  } catch (error) {
    els.results.className = "empty";
    els.results.textContent = error.message;
    setStatus(error.message, true);
  } finally {
    els.run.disabled = false;
  }
}

async function boot() {
  const [configs, prompts] = await Promise.all([
    fetchJson("/v1/rails/configs"),
    fetchJson("/playground/prompts.json"),
  ]);

  state.prompts = prompts;
  els.config.replaceChildren(
    ...configs.map((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.id;
      return option;
    }),
  );

  const preferred = configs.find((item) => item.id === "playground") || configs[0];
  if (preferred) {
    els.config.value = preferred.id;
  }

  const requested = new URLSearchParams(window.location.search).get("prompt");
  renderCategories();
  renderExamples();
  if (requested) {
    selectPrompt(requested);
  }

  els.run.addEventListener("click", run);
}

boot().catch((error) => setStatus(error.message, true));
