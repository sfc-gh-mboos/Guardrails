const promptInput = document.getElementById("prompt");
const runForm = document.getElementById("run-form");
const runButton = document.getElementById("run-button");
const statusBox = document.getElementById("status");
const resultBox = document.getElementById("result");
const verdictBox = document.getElementById("verdict");
const pipelineBox = document.getElementById("pipeline");
const railsBody = document.getElementById("rails-body");
const statsBox = document.getElementById("stats");
const rawJsonBox = document.getElementById("raw-json");

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function showStatus(message, isError = false) {
    statusBox.textContent = message;
    statusBox.classList.toggle("error", isError);
    statusBox.hidden = false;
}

/**
 * Highlight the span that differs between two strings by trimming the shared
 * prefix and suffix. Good enough to make a masked identifier or a rewritten
 * sentence jump out without pulling in a diff library.
 */
function renderTextWithDiff(target, text, comparedTo) {
    target.textContent = "";
    if (comparedTo === null || comparedTo === undefined || comparedTo === text) {
        target.textContent = text;
        return;
    }

    let start = 0;
    while (start < text.length && start < comparedTo.length && text[start] === comparedTo[start]) {
        start += 1;
    }
    let end = 0;
    while (
        end < text.length - start &&
        end < comparedTo.length - start &&
        text[text.length - 1 - end] === comparedTo[comparedTo.length - 1 - end]
    ) {
        end += 1;
    }

    const changed = text.slice(start, text.length - end);
    target.append(text.slice(0, start));
    if (changed) {
        target.append(element("mark", null, changed));
    }
    target.append(text.slice(text.length - end));
}

function stageCard(step, title, chip, text, comparedTo) {
    const item = element("li", "stage");
    const head = element("div", "stage-head");
    const titleNode = element("div", "stage-title");
    titleNode.append(element("span", "step", `${step}`), document.createTextNode(title));
    head.append(titleNode);
    if (chip) {
        head.append(element("span", `chip ${chip.tone}`, chip.label));
    }
    item.append(head);

    const body = element("p", "stage-text");
    if (text === null || text === undefined) {
        body.classList.add("absent");
        body.textContent = chip && chip.absentText ? chip.absentText : "Not produced.";
    } else {
        renderTextWithDiff(body, text, comparedTo);
    }
    item.append(body);
    return item;
}

function renderPipeline(result) {
    pipelineBox.textContent = "";

    pipelineBox.append(stageCard(1, "Prompt you sent", null, result.prompt, null));

    const inputChip = result.prompt_after_input_rails === null
        ? { tone: "blocked", label: "stopped by input rail", absentText: "Input rails stopped the request before the model was called." }
        : result.input_modified
          ? { tone: "modified", label: "rewritten by input rails" }
          : { tone: "passed", label: "unchanged" };
    pipelineBox.append(
        stageCard(2, "Prompt the model received", inputChip, result.prompt_after_input_rails, result.prompt),
    );

    const modelChip = result.model_called
        ? { tone: "passed", label: "model answered" }
        : { tone: "blocked", label: "model not called", absentText: "The model was never called." };
    pipelineBox.append(stageCard(3, "Raw model output", modelChip, result.model_output, null));

    const outputChip =
        result.verdict === "blocked" && result.blocked_stage === "output"
            ? { tone: "blocked", label: "replaced by output rail" }
            : result.output_modified
              ? { tone: "modified", label: "rewritten by output rails" }
              : { tone: "passed", label: "unchanged" };
    pipelineBox.append(stageCard(4, "Response returned to the user", outputChip, result.response, result.model_output));
}

function renderVerdict(result) {
    verdictBox.className = `verdict ${result.verdict}`;
    verdictBox.textContent = "";
    verdictBox.append(element("strong", null, result.verdict));

    let detail;
    if (result.verdict === "blocked") {
        detail = `Stopped by the ${result.blocked_stage} rail "${result.blocked_by}". The user got the configured refusal message.`;
    } else if (result.verdict === "modified") {
        const sides = [];
        if (result.input_modified) sides.push("the prompt");
        if (result.output_modified) sides.push("the response");
        detail = `Rails rewrote ${sides.join(" and ")}.`;
    } else {
        detail = "Every rail ran and let the prompt and the response through unchanged.";
    }
    verdictBox.append(element("span", null, detail));
}

function renderRails(result) {
    railsBody.textContent = "";
    result.rails.forEach((rail) => {
        const row = element("tr", rail.effect === "blocked" ? "blocked" : null);
        row.append(element("td", null, rail.stage));
        row.append(element("td", "rail-name", rail.name));

        const effectCell = element("td");
        effectCell.append(element("span", `chip ${rail.effect}`, rail.effect));
        row.append(effectCell);

        const matched = rail.detections.length ? `matched: ${rail.detections.join(", ")}` : null;
        row.append(element("td", null, rail.reason || matched || "-"));
        row.append(element("td", "numeric", rail.duration_ms === null ? "-" : `${rail.duration_ms} ms`));
        railsBody.append(row);
    });

    const stats = result.stats;
    statsBox.textContent =
        `Total ${stats.total_ms ?? 0} ms - input rails ${stats.input_rails_ms ?? 0} ms - ` +
        `generation ${stats.generation_ms ?? 0} ms - output rails ${stats.output_rails_ms ?? 0} ms - ` +
        `${stats.llm_calls_count ?? 0} LLM call(s)`;
}

async function runPrompt(prompt) {
    runButton.disabled = true;
    showStatus("Running the prompt through the rails...");
    try {
        const response = await fetch("/api/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt }),
        });
        if (!response.ok) {
            const problem = await response.json().catch(() => ({}));
            throw new Error(problem.detail || `Request failed with status ${response.status}`);
        }
        const result = await response.json();
        renderVerdict(result);
        renderPipeline(result);
        renderRails(result);
        rawJsonBox.textContent = JSON.stringify(result, null, 2);
        resultBox.hidden = false;
        statusBox.hidden = true;
    } catch (error) {
        showStatus(error.message, true);
    } finally {
        runButton.disabled = false;
    }
}

function renderPromptBank(bank) {
    const container = document.getElementById("prompt-bank");
    container.textContent = "";
    bank.groups.forEach((group) => {
        const section = element("div", "prompt-group");
        section.append(element("h3", null, group.name));
        if (group.description) {
            section.append(element("p", null, group.description));
        }
        group.prompts.forEach((entry) => {
            const button = element("button", "prompt-button");
            button.type = "button";
            button.append(document.createTextNode(entry.text));
            if (entry.expected) {
                button.append(element("span", "expected", entry.expected));
            }
            button.addEventListener("click", () => {
                promptInput.value = entry.text;
                promptInput.focus();
                runPrompt(entry.text);
            });
            section.append(button);
        });
        container.append(section);
    });
}

function renderConfig(config) {
    const summary = document.getElementById("config-summary");
    summary.textContent = "";
    const entries = [
        ["Config", config.config_id],
        ["Main model", config.main_model || "none configured"],
        ["Rails", `${config.input_rails.length} input / ${config.output_rails.length} output`],
    ];
    entries.forEach(([label, value]) => {
        const group = element("div");
        group.append(element("dt", null, label), element("dd", null, value));
        summary.append(group);
    });
    if (config.scripted_demo_model) {
        summary.append(element("span", "demo-badge", "scripted demo model"));
    }

    const railsSummary = document.getElementById("rails-summary");
    railsSummary.textContent = "";
    [
        ["Input", config.input_rails],
        ["Output", config.output_rails],
        ["Retrieval", config.retrieval_rails],
    ].forEach(([label, rails]) => {
        if (!rails.length) return;
        railsSummary.append(element("strong", null, label));
        const list = element("ul");
        rails.forEach((rail) => list.append(element("li", null, rail)));
        railsSummary.append(list);
    });
}

runForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const prompt = promptInput.value.trim();
    if (prompt) runPrompt(prompt);
});

promptInput.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        runForm.requestSubmit();
    }
});

Promise.all([
    fetch("/api/config").then((response) => response.json()),
    fetch("/api/prompts").then((response) => response.json()),
])
    .then(([config, bank]) => {
        renderConfig(config);
        renderPromptBank(bank);
    })
    .catch(() => showStatus("Could not load the configuration or the prompt bank.", true));
