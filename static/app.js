const composer = document.querySelector("#composer");
const micBtn = document.querySelector("#mic");
const micLabel = document.querySelector("#mic-label");
const runBtn = document.querySelector("#run");
const resultEl = document.querySelector("#result");
const notesEl = document.querySelector("#notes");
const auditEl = document.querySelector("#audit");
const noteCount = document.querySelector("#note-count");
const auditCount = document.querySelector("#audit-count");
const pills = document.querySelector("#pills");
const pipeline = document.querySelector("#pipeline");
const voiceHint = document.querySelector("#voice-hint");

const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let source = "typed";
let listening = false;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function badge(kind, label) {
  return `<span class="badge ${esc(kind)}">${esc(label || kind)}</span>`;
}

function modeBadge(mode) {
  const kind = mode === "lyzr" ? "lyzr" : "mock";
  const label = mode === "lyzr" ? "Lyzr" : mode === "mixed" ? "Mixed" : "Local mock";
  return badge(kind, label);
}

async function api(path, options) {
  const response = await fetch(path, options);
  let data = {};
  try {
    data = await response.json();
  } catch (_err) {
    data = {};
  }
  if (!response.ok) {
    const detail = data.detail;
    const message = typeof detail === "string" ? detail : "The vault request failed.";
    throw new Error(message);
  }
  return data;
}

function selected(name) {
  const node = document.querySelector(`input[name="${name}"]:checked`);
  return node ? node.value : "";
}

function setRadio(name, value) {
  const node = document.querySelector(`input[name="${name}"][value="${value}"]`);
  if (node) node.checked = true;
}

function formatWhen(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function filterLine(tiers) {
  if (!tiers || !tiers.length) return "";
  if (tiers.length === 1) return `Qdrant filter: tier is ${tiers[0]}`;
  return `Qdrant filter: tier is ${tiers.join(" or ")}`;
}

function setPipeline(state, action) {
  pipeline.classList.toggle("running", state === "running");
  const steps = {
    voice: state !== "idle",
    router: state === "done",
    guard: state === "done",
    qdrant: state === "done",
    answer: state === "done" && action === "query",
    audit: state === "done",
  };
  pipeline.querySelectorAll("li").forEach((item) => {
    const name = item.dataset.step;
    item.classList.toggle("done", Boolean(steps[name]));
    item.classList.toggle("skip", state === "done" && name === "answer" && action !== "query");
  });
}

function renderPills(status) {
  const lyzrLive = status.lyzr === "lyzr";
  const qdrantKind = status.qdrant === "cloud" ? "live" : "local";
  pills.innerHTML = [
    `<span class="pill"><i class="dot ${lyzrLive ? "live" : "mock"}"></i> Lyzr <strong>${esc(lyzrLive ? "live" : "local mock")}</strong></span>`,
    `<span class="pill"><i class="dot ${qdrantKind}"></i> Qdrant <strong>${esc(status.qdrant)}</strong></span>`,
    `<span class="pill">Embed <strong>${esc(status.embedder)}</strong></span>`,
  ].join("");
  pills.title = `${status.lyzr_detail} ${status.qdrant_detail}`;
}

function renderNotes(notes, freshId) {
  noteCount.textContent = String(notes.length);
  if (!notes.length) {
    notesEl.innerHTML = `<p class="empty">No notes yet. Speak one, or restart the server to load the samples.</p>`;
    return;
  }
  notesEl.innerHTML = notes.map((note) => {
    const flags = (note.pii_flags || []).map((flag) => badge("pii", flag)).join("");
    const mismatch = note.suggested_tier && note.suggested_tier !== note.tier
      ? `<p class="meta">Guard suggested ${esc(note.suggested_tier)}</p>`
      : "";
    return `<article class="note${note.id === freshId ? " fresh" : ""}">
      <div class="badges">${badge(note.tier, note.tier)}${flags}${note.source === "seed" ? badge("meta", "sample") : ""}</div>
      <p>${esc(note.text)}</p>
      ${mismatch}
      <p class="meta">${esc(formatWhen(note.timestamp))}</p>
    </article>`;
  }).join("");
}

function renderAudit(entries, freshId) {
  auditCount.textContent = String(entries.length);
  if (!entries.length) {
    auditEl.innerHTML = `<p class="empty">No queries yet. Ask the vault and this log will name every chunk the answer used.</p>`;
    return;
  }
  auditEl.innerHTML = entries.map((entry) => {
    const chunks = (entry.chunks || []).map((chunk) => {
      const flags = (chunk.pii_flags || []).map((flag) => badge("pii", flag)).join("");
      const red = chunk.redacted ? badge("redacted", "redacted") : "";
      return `<div class="chunk">
        <div class="badges">${badge(chunk.tier, chunk.tier)}${red}${flags}</div>
        <p>${esc(chunk.excerpt)}</p>
        <p class="meta">${esc(chunk.id.slice(0, 8))} · score ${esc(chunk.score)}</p>
      </div>`;
    }).join("");
    const agents = (entry.agents || []).map((agent) => `${esc(agent.name)} (${esc(agent.mode)})`).join(", ");
    const filter = entry.qdrant_filter && entry.qdrant_filter.length
      ? `<p class="meta">${esc(filterLine(entry.qdrant_filter))}</p>`
      : "";
    return `<article class="entry${entry.id === freshId ? " fresh" : ""}" id="audit-${esc(entry.id)}">
      <div class="badges">${badge(entry.action, entry.action)}${entry.scope ? badge(entry.scope, entry.scope) : ""}${modeBadge(entry.reasoning_mode)}</div>
      <p>${esc(entry.input)}</p>
      ${filter}
      <p class="meta">${esc(formatWhen(entry.timestamp))} · ${agents || "no agents"}</p>
      ${chunks || `<p class="meta">No retrieval chunks on this turn.</p>`}
    </article>`;
  }).join("");
}

function renderResult(data) {
  const agents = [data.router, data.guard, data.answer_agent].filter(Boolean);
  const trace = `<div class="trace">${agents.map((agent) => `
    <div>
      <strong>${esc(agent.name)}</strong>
      <span>${esc(agent.mode === "lyzr" ? "Lyzr" : "Local mock")}</span>
      <span>${esc(agent.reason || agent.summary || "")}</span>
    </div>`).join("")}</div>`;
  const warning = data.warning ? `<p class="banner">${esc(data.warning)}</p>` : "";
  const modeLine = data.reasoning_mode === "lyzr"
    ? "Lyzr agents ran this loop."
    : data.reasoning_mode === "mixed"
      ? "Part of this loop used Lyzr. A failed call fell back to the local rules."
      : "Local mock reasoning. No Lyzr key is set, so the same three roles ran on local rules.";

  if (data.action === "store") {
    const note = data.note || {};
    const flags = (note.pii_flags || []).map((flag) => badge("pii", flag)).join("");
    resultEl.innerHTML = `
      <p class="kicker">Stored</p>
      <div class="answer-head">${modeBadge(data.reasoning_mode)}${badge(note.tier, note.tier)}${flags}</div>
      <p class="banner">${esc(modeLine)}</p>
      ${warning}
      <p class="answer-body">${esc(note.text || "")}</p>
      <p class="filter-line">Qdrant payload: tier ${esc(note.tier)}, ${esc(formatWhen(note.timestamp))}, flags ${(note.pii_flags || []).join(", ") || "none"}</p>
      <p class="hint">Guard suggestion: ${esc(data.guard.suggested_tier)}. ${esc(data.guard.reason)} Redacted form kept beside the raw note: ${esc(note.redacted_text || "")}</p>
      ${trace}`;
    return;
  }

  const chunks = (data.chunks || []).map((chunk) => {
    const flags = (chunk.pii_flags || []).map((flag) => badge("pii", flag)).join("");
    const red = chunk.redacted ? badge("redacted", "redacted before agent") : "";
    return `<article class="chunk">
      <div class="badges">${badge(chunk.tier, chunk.tier)}${red}${flags}<span class="meta">score ${esc(chunk.score)}</span></div>
      <p>${esc(chunk.excerpt)}</p>
      <p class="meta">chunk ${esc(chunk.id.slice(0, 8))}</p>
    </article>`;
  }).join("");

  resultEl.innerHTML = `
    <p class="kicker">Answer · scope ${esc(data.scope)}</p>
    <div class="answer-head">${modeBadge(data.reasoning_mode)}</div>
    <p class="banner">${esc(modeLine)}</p>
    ${warning}
    <p class="answer-body">${esc(data.answer || "No answer.")}</p>
    <p class="filter-line">${esc(filterLine(data.qdrant_filter))}</p>
    ${trace}
    <h3 class="kicker">Chunks the answer agent could see</h3>
    <div class="stack">${chunks || `<p class="empty">None. The payload filter returned nothing in this scope.</p>`}</div>`;
}

async function refreshLists(freshNote, freshAudit) {
  const [notes, audit] = await Promise.all([
    api("/api/notes"),
    api("/api/audit"),
  ]);
  renderNotes(notes.notes, freshNote);
  renderAudit(audit.entries, freshAudit);
}

async function boot() {
  try {
    const status = await api("/api/status");
    renderPills(status);
    await refreshLists();
    if (!SpeechRec) {
      voiceHint.textContent = "This browser has no Web Speech API. Type the note and run the loop.";
    }
  } catch (err) {
    pills.innerHTML = `<span class="pill">Vault offline</span>`;
    notesEl.innerHTML = `<p class="empty error">${esc(err.message)}</p>`;
    resultEl.innerHTML = `<p class="empty error">Could not reach the API. Start the server and reload.</p>`;
  }
}

function ensureRecognition() {
  if (!SpeechRec) return null;
  if (recognition) return recognition;
  recognition = new SpeechRec();
  recognition.lang = "en-US";
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.onresult = (event) => {
    let finalText = "";
    let interim = "";
    for (const item of event.results) {
      const said = item[0] ? item[0].transcript : "";
      if (item.isFinal) finalText += said;
      else interim += said;
    }
    composer.value = (finalText || interim).trim();
    source = "voice";
  };
  recognition.onerror = () => {
    listening = false;
    micBtn.classList.remove("live");
    micBtn.setAttribute("aria-pressed", "false");
    micLabel.textContent = "Mic error. You can type instead.";
  };
  recognition.onend = () => {
    listening = false;
    micBtn.classList.remove("live");
    micBtn.setAttribute("aria-pressed", "false");
    micLabel.textContent = source === "voice" ? "Voice captured" : "Mic idle";
  };
  return recognition;
}

micBtn.addEventListener("click", () => {
  const rec = ensureRecognition();
  if (!rec) {
    micLabel.textContent = "No speech API in this browser.";
    voiceHint.textContent = "This browser has no Web Speech API. Type the note and run the loop.";
    return;
  }
  if (listening) {
    rec.stop();
    return;
  }
  try {
    source = "voice";
    listening = true;
    micBtn.classList.add("live");
    micBtn.setAttribute("aria-pressed", "true");
    micLabel.textContent = "Listening...";
    rec.start();
  } catch (_err) {
    listening = false;
    micLabel.textContent = "Mic did not start. Type instead.";
  }
});

composer.addEventListener("input", () => {
  if (!listening) source = "typed";
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    composer.value = chip.dataset.text || "";
    if (chip.dataset.tier) setRadio("tier", chip.dataset.tier);
    if (chip.dataset.scope) setRadio("scope", chip.dataset.scope);
    source = "typed";
    composer.focus();
  });
});

async function runLoop() {
  const text = composer.value.trim();
  if (!text) {
    resultEl.innerHTML = `<p class="empty error">Say or type something first.</p>`;
    return;
  }
  const tierValue = selected("tier");
  runBtn.disabled = true;
  runBtn.textContent = "Working...";
  setPipeline("running");
  try {
    const data = await api("/api/turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        tier: tierValue === "auto" ? null : tierValue,
        scope: selected("scope") || "me",
        source,
      }),
    });
    renderResult(data);
    setPipeline("done", data.action);
    await refreshLists(data.note && data.note.id, data.audit_id);
    const auditNode = document.querySelector(`#audit-${data.audit_id}`);
    if (auditNode) auditNode.scrollIntoView({ block: "nearest" });
  } catch (err) {
    setPipeline("idle");
    resultEl.innerHTML = `<p class="empty error">${esc(err.message)}</p>`;
  } finally {
    runBtn.disabled = false;
    runBtn.textContent = "Run the loop";
  }
}

runBtn.addEventListener("click", runLoop);
composer.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    runLoop();
  }
});

setPipeline("idle");
boot();
