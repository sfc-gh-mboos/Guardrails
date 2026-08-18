(() => {
  const promptList = document.getElementById("prompt-list");
  const healthEl = document.getElementById("health");
  const form = document.getElementById("inspect-form");
  const userInput = document.getElementById("user-input");
  const assistantInput = document.getElementById("assistant-input");
  const useDemoReply = document.getElementById("use-demo-reply");
  const runBtn = document.getElementById("run-btn");
  const expectedEl = document.getElementById("expected");
  const results = document.getElementById("results");
  const outcomeBanner = document.getElementById("outcome-banner");
  const inputView = document.getElementById("input-view");
  const candidateView = document.getElementById("candidate-view");
  const finalView = document.getElementById("final-view");
  const railsList = document.getElementById("rails-list");
  const railsMeta = document.getElementById("rails-meta");
  const rawView = document.getElementById("raw-view");

  let prompts = [];
  let activeFilter = "all";
  let selectedId = null;

  const outcomeCopy = {
    passed: "Passed — input and output cleared the configured rails.",
    input_blocked: "Input blocked — an input rail stopped the request before output checks.",
    output_blocked: "Output blocked — the candidate reply was rejected by an output rail.",
    modified: "Modified — rails changed the response content.",
  };

  function categoryLabel(category) {
    if (category === "input-blocked") return "Input blocked";
    if (category === "output-blocked") return "Output blocked";
    return "Pass";
  }

  function renderPromptList() {
    const filtered =
      activeFilter === "all" ? prompts : prompts.filter((p) => p.category === activeFilter);

    promptList.innerHTML = "";
    for (const prompt of filtered) {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "prompt-card" + (prompt.id === selectedId ? " is-selected" : "");
      button.innerHTML = `
        <span class="tag tag-${prompt.category}">${categoryLabel(prompt.category)}</span>
        <strong>${escapeHtml(prompt.label)}</strong>
        <span>${escapeHtml(prompt.user)}</span>
      `;
      button.addEventListener("click", () => selectPrompt(prompt));
      li.appendChild(button);
      promptList.appendChild(li);
    }
  }

  function selectPrompt(prompt) {
    selectedId = prompt.id;
    userInput.value = prompt.user || "";
    assistantInput.value = prompt.assistant || "";
    expectedEl.hidden = false;
    expectedEl.textContent = `Expected: ${prompt.expected}`;
    renderPromptList();
    userInput.focus();
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function renderResults(payload) {
    const impact = payload.impact || {};
    const outcome = impact.outcome || "passed";
    results.hidden = false;
    outcomeBanner.dataset.outcome = outcome;
    outcomeBanner.textContent = outcomeCopy[outcome] || outcome;

    inputView.textContent = impact.user || "";
    candidateView.textContent = impact.candidate_assistant || "(none — input-only check)";
    finalView.textContent = impact.final_assistant || payload.response || "";

    const activated = payload.activated_rails || [];
    railsMeta.textContent = `${activated.length} rail(s) activated · flows: ${(payload.rails_run || []).join(", ")}`;
    railsList.innerHTML = "";

    if (!activated.length) {
      const empty = document.createElement("p");
      empty.className = "empty-rails";
      empty.textContent = "No rails reported activation for this run.";
      railsList.appendChild(empty);
    } else {
      for (const rail of activated) {
        const row = document.createElement("article");
        row.className = "rail-row";
        row.dataset.stop = String(Boolean(rail.stop));
        const decisions = (rail.decisions || []).join(", ") || "continue";
        const duration =
          typeof rail.duration === "number" ? `${rail.duration.toFixed(3)}s` : "n/a";
        row.innerHTML = `
          <span class="rail-type">${escapeHtml(rail.type || "?")}</span>
          <div class="rail-body">
            <strong>${escapeHtml(rail.name || "unnamed rail")}</strong>
            <p>Decisions: ${escapeHtml(decisions)} · Duration: ${escapeHtml(duration)}</p>
          </div>
          <span class="rail-stop">${rail.stop ? "STOPPED" : ""}</span>
        `;
        railsList.appendChild(row);
      }
    }

    rawView.textContent = JSON.stringify(payload, null, 2);
  }

  async function loadHealth() {
    try {
      const res = await fetch("/api/health");
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "health failed");
      healthEl.dataset.state = "ok";
      healthEl.textContent = `Ready · ${data.engine} · input: ${(data.input_flows || []).join(", ") || "none"} · output: ${(data.output_flows || []).join(", ") || "none"}`;
    } catch (err) {
      healthEl.dataset.state = "error";
      healthEl.textContent = `Engine unavailable: ${err.message}`;
    }
  }

  async function loadPrompts() {
    const res = await fetch("/api/prompts");
    const data = await res.json();
    prompts = data.prompts || [];
    renderPromptList();
  }

  document.querySelectorAll(".filter").forEach((button) => {
    button.addEventListener("click", () => {
      activeFilter = button.dataset.filter;
      document.querySelectorAll(".filter").forEach((el) => el.classList.toggle("is-active", el === button));
      renderPromptList();
    });
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    runBtn.disabled = true;
    runBtn.textContent = "Inspecting…";
    try {
      const res = await fetch("/api/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user: userInput.value,
          assistant: assistantInput.value,
          use_demo_reply: useDemoReply.checked,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Inspect request failed");
      }
      renderResults(data);
    } catch (err) {
      results.hidden = false;
      outcomeBanner.dataset.outcome = "input_blocked";
      outcomeBanner.textContent = `Error: ${err.message}`;
      inputView.textContent = userInput.value;
      candidateView.textContent = assistantInput.value || "(none)";
      finalView.textContent = "";
      railsList.innerHTML = "";
      rawView.textContent = String(err);
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = "Inspect rails";
    }
  });

  loadHealth();
  loadPrompts();
})();
