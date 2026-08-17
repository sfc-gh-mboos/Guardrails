(function () {
  const CATEGORIES = ["all", "allowed", "off-topic", "jailbreak", "harmful"];

  const els = {
    config: document.getElementById("config-id"),
    model: document.getElementById("model-id"),
    prompt: document.getElementById("prompt-input"),
    why: document.getElementById("prompt-why"),
    filters: document.getElementById("category-filters"),
    list: document.getElementById("prompt-list"),
    applyRails: document.getElementById("apply-rails"),
    compare: document.getElementById("compare-rails"),
    llmCalls: document.getElementById("show-llm-calls"),
    run: document.getElementById("run-button"),
    status: document.getElementById("run-status"),
    results: document.getElementById("results"),
    chatLink: document.getElementById("chat-link"),
    docsLink: document.getElementById("docs-link"),
  };

  let prompts = [];
  let activeCategory = "all";
  let selectedPromptId = null;

  function apiUrl(path) {
    const pathname = window.location.pathname.replace(/\/+$/, "") || "";
    const root = pathname.endsWith("/ui") ? pathname.slice(0, -3) : pathname;
    return `${root}${path}`;
  }

  async function fetchJson(path, options) {
    const response = await fetch(apiUrl(path), options);
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (err) {
        data = text;
      }
    }
    if (!response.ok) {
      const message = formatError(data) || `${response.status} ${response.statusText}`;
      const error = new Error(message);
      error.status = response.status;
      error.body = data;
      throw error;
    }
    return data;
  }

  function formatError(data) {
    if (!data) return "";
    if (typeof data === "string") return data;
    if (data.detail) {
      return typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail, null, 2);
    }
    if (data.error && data.error.message) return data.error.message;
    if (data.message) return data.message;
    return JSON.stringify(data, null, 2);
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function promptMatchesConfig(prompt, configId) {
    if (!prompt.configs || prompt.configs.length === 0) return true;
    if (!configId) return true;
    return prompt.configs.indexOf(configId) !== -1;
  }

  function visiblePrompts() {
    const configId = els.config.value;
    return prompts.filter(function (prompt) {
      const categoryOk = activeCategory === "all" || prompt.category === activeCategory;
      return categoryOk && promptMatchesConfig(prompt, configId);
    });
  }

  function renderFilters() {
    els.filters.innerHTML = "";
    CATEGORIES.forEach(function (category) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "filter-chip";
      button.textContent = category;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", category === activeCategory ? "true" : "false");
      button.addEventListener("click", function () {
        activeCategory = category;
        renderFilters();
        renderPromptList();
      });
      els.filters.appendChild(button);
    });
  }

  function renderPromptList() {
    const items = visiblePrompts();
    els.list.innerHTML = "";
    if (items.length === 0) {
      const empty = document.createElement("li");
      empty.className = "empty";
      empty.textContent = "No example prompts for this configuration and filter.";
      els.list.appendChild(empty);
      return;
    }
    items.forEach(function (prompt) {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "prompt-card" + (prompt.id === selectedPromptId ? " active" : "");
      button.innerHTML =
        '<span class="name">' +
        escapeHtml(prompt.name) +
        '</span><span class="meta"><span class="badge ' +
        escapeHtml(prompt.category) +
        '">' +
        escapeHtml(prompt.category) +
        '</span><span class="badge ' +
        escapeHtml(prompt.expected) +
        '">expect ' +
        escapeHtml(prompt.expected) +
        "</span></span>";
      button.addEventListener("click", function () {
        selectedPromptId = prompt.id;
        els.prompt.value = prompt.content;
        els.why.hidden = !prompt.why;
        els.why.textContent = prompt.why || "";
        renderPromptList();
      });
      li.appendChild(button);
      els.list.appendChild(li);
    });
  }

  function railsOptions(enabled) {
    return {
      input: enabled,
      output: enabled,
      dialog: enabled,
      retrieval: enabled,
      tool_input: enabled,
      tool_output: enabled,
    };
  }

  function completionRequest(applyRails) {
    return {
      model: els.model.value.trim() || "gpt-4o",
      messages: [{ role: "user", content: els.prompt.value }],
      guardrails: {
        config_id: els.config.value,
        options: {
          rails: railsOptions(applyRails),
          log: {
            activated_rails: true,
            llm_calls: els.llmCalls.checked,
          },
        },
      },
    };
  }

  function assistantText(payload) {
    const choice = payload && payload.choices && payload.choices[0];
    const message = choice && choice.message;
    if (!message) return "";
    if (typeof message.content === "string") return message.content;
    if (message.content == null) return "";
    return JSON.stringify(message.content, null, 2);
  }

  function generationLog(payload) {
    return (payload && payload.guardrails && payload.guardrails.log) || {};
  }

  function impactSummary(log) {
    const rails = log.activated_rails || [];
    const stopped = rails.filter(function (rail) {
      if (rail.stop) return true;
      const decisions = rail.decisions || [];
      return decisions.some(function (decision) {
        return /stop|refuse/i.test(String(decision));
      });
    });
    if (stopped.length) {
      return { label: "blocked", detail: stopped.map(function (rail) { return rail.name; }).join(", ") };
    }
    if (rails.length) return { label: "pass", detail: rails.length + " rail(s) ran" };
    return { label: "pass", detail: "no rails reported" };
  }

  function renderRailCards(log) {
    const rails = log.activated_rails || [];
    if (!rails.length) {
      return '<p class="empty">No activated rails were returned. Enable rails and rerun.</p>';
    }
    return rails
      .map(function (rail) {
        const duration = rail.duration != null ? Number(rail.duration).toFixed(2) + "s" : "n/a";
        const decisions = (rail.decisions || []).join(", ") || "none";
        const actions = (rail.executed_actions || [])
          .map(function (action) {
            return action.action_name;
          })
          .filter(Boolean)
          .join(", ");
        const statusClass = rail.stop ? "block" : "pass";
        return (
          '<article class="rail-card"><header><span class="title">' +
          escapeHtml(rail.type || "rail") +
          " / " +
          escapeHtml(rail.name || "unnamed") +
          '</span><span class="badge ' +
          statusClass +
          '">' +
          (rail.stop ? "stopped" : "ran") +
          "</span></header><p class=\"detail\">Decisions: " +
          escapeHtml(decisions) +
          " · Actions: " +
          escapeHtml(actions || "none") +
          " · Duration: " +
          escapeHtml(duration) +
          "</p></article>"
        );
      })
      .join("");
  }

  function renderLlmCalls(log) {
    if (!els.llmCalls.checked) return "";
    const calls = log.llm_calls || [];
    if (!calls.length) return '<div class="block"><h4>LLM calls</h4><p class="empty">No LLM calls in the log.</p></div>';
    const body = calls
      .map(function (call, index) {
        const prompt = call.prompt || call.raw_prompt || "";
        const completion = call.completion || call.raw_response || "";
        return (
          "<details><summary>Call " +
          (index + 1) +
          (call.llm_name ? " · " + escapeHtml(call.llm_name) : "") +
          "</summary><h4>Prompt</h4><pre class=\"pre\">" +
          escapeHtml(prompt) +
          "</pre><h4>Completion</h4><pre class=\"pre\">" +
          escapeHtml(typeof completion === "string" ? completion : JSON.stringify(completion, null, 2)) +
          "</pre></details>"
        );
      })
      .join("");
    return '<div class="block"><h4>LLM calls</h4>' + body + "</div>";
  }

  function renderStats(log) {
    const stats = log.stats || {};
    const bits = [];
    if (stats.total_duration != null) bits.push(Number(stats.total_duration).toFixed(2) + "s total");
    if (stats.llm_calls_count) bits.push(stats.llm_calls_count + " LLM calls");
    if (stats.llm_calls_total_tokens) bits.push(stats.llm_calls_total_tokens + " tokens");
    if (!bits.length) return "";
    return '<p class="detail">' + escapeHtml(bits.join(" · ")) + "</p>";
  }

  function renderColumn(title, input, payload, error) {
    if (error) {
      return (
        '<div class="result-col"><h3>' +
        escapeHtml(title) +
        '</h3><p class="error">' +
        escapeHtml(error.message) +
        "</p></div>"
      );
    }
    const output = assistantText(payload);
    const log = generationLog(payload);
    const impact = impactSummary(log);
    return (
      '<div class="result-col"><h3>' +
      escapeHtml(title) +
      '</h3><div class="summary"><span class="badge ' +
      impact.label +
      '">' +
      impact.label +
      '</span><span class="badge info">' +
      escapeHtml(impact.detail) +
      '</span></div><div class="block"><h4>Confirmed input</h4><pre class="pre">' +
      escapeHtml(input) +
      '</pre></div><div class="block"><h4>Output</h4><pre class="pre">' +
      escapeHtml(output || "(empty)") +
      "</pre></div><div class=\"block\"><h4>Rails that ran</h4>" +
      renderRailCards(log) +
      renderStats(log) +
      "</div>" +
      renderLlmCalls(log) +
      "</div>"
    );
  }

  function renderResults(input, withRails, withoutRails, withError, withoutError, compared) {
    if (compared) {
      const left = withRails ? assistantText(withRails) : "";
      const right = withoutRails ? assistantText(withoutRails) : "";
      let banner;
      if (withError || withoutError) {
        banner = '<p class="hint">One or both runs failed. Compare the columns below.</p>';
      } else if (left !== right) {
        banner = '<p class="hint">Rails changed the output compared with the unguarded run.</p>';
      } else {
        banner = '<p class="hint">Rails did not change the visible output for this prompt.</p>';
      }
      els.results.innerHTML =
        banner +
        '<div class="compare-grid">' +
        renderColumn("With rails", input, withRails, withError) +
        renderColumn("Without rails", input, withoutRails, withoutError) +
        "</div>";
      return;
    }
    els.results.innerHTML = renderColumn("Guarded response", input, withRails, withError);
  }

  async function runPrompt() {
    const input = els.prompt.value.trim();
    if (!input) {
      els.status.textContent = "Enter or select a prompt first.";
      return;
    }
    if (!els.config.value) {
      els.status.textContent = "No guardrails configuration is available.";
      return;
    }

    els.run.disabled = true;
    els.status.textContent = "Running…";
    const compared = els.compare.checked;
    const applyRails = compared ? true : els.applyRails.checked;

    let withRails = null;
    let withoutRails = null;
    let withError = null;
    let withoutError = null;

    try {
      const tasks = [
        fetchJson("/v1/chat/completions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(completionRequest(applyRails)),
        })
          .then(function (data) {
            withRails = data;
          })
          .catch(function (err) {
            withError = err;
          }),
      ];
      if (compared) {
        tasks.push(
          fetchJson("/v1/chat/completions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(completionRequest(false)),
          })
            .then(function (data) {
              withoutRails = data;
            })
            .catch(function (err) {
              withoutError = err;
            })
        );
      }
      await Promise.all(tasks);
      renderResults(input, withRails, withoutRails, withError, withoutError, compared);
      if (withError && (!compared || withoutError)) {
        els.status.textContent = "Request failed.";
      } else {
        els.status.textContent = compared ? "Compared guarded and unguarded runs." : "Done.";
      }
    } finally {
      els.run.disabled = false;
    }
  }

  async function init() {
    renderFilters();

    els.chatLink.hidden = false;
    els.docsLink.hidden = false;

    try {
      const configs = await fetchJson("/v1/rails/configs");
      els.config.innerHTML = "";
      (configs || []).forEach(function (item) {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = item.id;
        els.config.appendChild(option);
      });
      if (!els.config.options.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No configs found";
        els.config.appendChild(option);
      }
    } catch (err) {
      els.status.textContent = "Could not load configurations: " + err.message;
    }

    try {
      const bundled = await fetchJson("/ui/example-prompts.json");
      const extra = await fetchJson("/v1/challenges").catch(function () {
        return [];
      });
      const seen = {};
      prompts = [];
      bundled.concat(extra || []).forEach(function (prompt) {
        if (!prompt || !prompt.content) return;
        const key = prompt.id || prompt.content;
        if (seen[key]) return;
        seen[key] = true;
        prompts.push({
          id: prompt.id || key,
          name: prompt.name || prompt.content.slice(0, 40),
          category: prompt.category || "allowed",
          expected: prompt.expected || "pass",
          configs: prompt.configs || [],
          content: prompt.content,
          why: prompt.why || "",
        });
      });
    } catch (err) {
      els.status.textContent = "Could not load example prompts: " + err.message;
    }

    els.config.addEventListener("change", renderPromptList);
    els.compare.addEventListener("change", function () {
      if (els.compare.checked) els.applyRails.checked = true;
    });
    els.run.addEventListener("click", runPrompt);
    els.prompt.addEventListener("input", function () {
      selectedPromptId = null;
      els.why.hidden = true;
      renderPromptList();
    });
    renderPromptList();
  }

  init();
})();
