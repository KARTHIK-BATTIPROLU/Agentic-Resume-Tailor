"use strict";

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const userId = () => ($("userId").value.trim() || "demo");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function wsUrl(path) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${path}`;
}

async function postJSON(url, body, method = "POST") {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

function bubble(container, text, cls) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

// ----------------------------------------------------------------------------
// Tabs
// ----------------------------------------------------------------------------
document.querySelectorAll(".tab").forEach((t) => {
  t.onclick = () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".tabpanel").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $("tab-" + t.dataset.tab).classList.add("active");
  };
});

// ============================================================================
// PROFILE BUILDER
// ============================================================================
let profileWS = null;

function setProfileInput(enabled) {
  $("profileReply").disabled = !enabled;
  $("sendProfile").disabled = !enabled;
  if (enabled) $("profileReply").focus();
}

$("startProfile").onclick = () => {
  if (profileWS) { try { profileWS.close(); } catch (e) {} }
  $("profileChat").innerHTML = "";
  $("profileEmpty").classList.add("hidden");
  const ws = new WebSocket(wsUrl(`/ws/profile/${encodeURIComponent(userId())}`));
  profileWS = ws;
  $("profileConn").textContent = "connecting…";

  ws.onopen = () => {
    $("profileConn").textContent = "connected";
    const resume_text = $("bootstrapText").value.trim();
    ws.send(JSON.stringify(resume_text ? { type: "start", resume_text } : { type: "start" }));
  };
  ws.onclose = () => { $("profileConn").textContent = "disconnected"; setProfileInput(false); };
  ws.onerror = () => { $("profileConn").textContent = "error"; };
  ws.onmessage = (ev) => handleProfileEvent(JSON.parse(ev.data));
};

$("sendProfile").onclick = sendProfileReply;
$("profileReply").addEventListener("keydown", (e) => { if (e.key === "Enter") sendProfileReply(); });

function sendProfileReply() {
  const v = $("profileReply").value.trim();
  if (!v || !profileWS) return;
  bubble($("profileChat"), v, "me");
  profileWS.send(JSON.stringify({ type: "reply", message: v }));
  $("profileReply").value = "";
  setProfileInput(false);
}

function handleProfileEvent(msg) {
  const chat = $("profileChat");
  switch (msg.type) {
    case "status": bubble(chat, msg.message, "sys"); break;
    case "question":
      bubble(chat, msg.question, "bot");
      setProfileInput(true);
      break;
    case "section_update": renderProfile(msg.profile); break;
    case "confirm": renderPending(msg.pending); break;
    case "done":
      bubble(chat, "✓ Profile complete. You can keep editing the cards or move to the Resume Tailor tab.", "sys");
      if (msg.profile) renderProfile(msg.profile);
      setProfileInput(false);
      break;
    case "error": bubble(chat, "Error: " + msg.detail, "sys"); break;
  }
}

// --- Pending confirmations -------------------------------------------------
function renderPending(pending) {
  const card = $("pendingCard"), list = $("pendingList");
  if (!pending || !pending.length) return;
  card.classList.remove("hidden");
  for (const p of pending) {
    if (list.querySelector(`[data-cid="${p.confirmation_id}"]`)) continue;
    const row = document.createElement("div");
    row.className = "confirm-item";
    row.dataset.cid = p.confirmation_id;
    row.innerHTML = `<span>New ${esc(p.kind)} — <b>${esc(p.summary)}</b> <span class="muted">(${esc(p.confidence)})</span></span>`;
    const btns = document.createElement("div");
    const mk = (label, cls, approved) => {
      const b = document.createElement("button");
      b.textContent = label; b.className = "tiny " + cls;
      b.onclick = async () => {
        try {
          await postJSON("/confirm", { user_id: userId(), confirmation_id: p.confirmation_id, approved });
          row.remove();
          if (!list.children.length) card.classList.add("hidden");
          refreshProfile();
        } catch (e) { alert(e.message); }
      };
      return b;
    };
    btns.append(mk("Approve", "", true), mk("Reject", "secondary", false));
    row.appendChild(btns);
    list.appendChild(row);
  }
}

async function refreshProfile() {
  try { renderProfile(await postJSON(`/profile/${encodeURIComponent(userId())}`, undefined, "GET")); }
  catch (e) {}
}

// --- Section cards (editable) ----------------------------------------------
const SECTIONS = ["skills", "experiences", "projects", "education", "certifications", "achievements"];
const FIELDS = {
  skills: [["name", "Name"], ["category", "Category"], ["proficiency", "Proficiency"]],
  experiences: [["company", "Company"], ["title", "Title"], ["location", "Location"],
                ["start", "Start"], ["end", "End"], ["bullets", "Bullets (one per line)", "bullets"]],
  projects: [["name", "Name"], ["description", "Description", "area"], ["role", "Role"],
             ["tech_stack", "Tech (comma-separated)", "csv"], ["outcomes", "Outcomes (one per line)", "outcomes"]],
  education: [["degree", "Degree"], ["institution", "Institution"], ["location", "Location"],
              ["start", "Start"], ["end", "End"], ["details", "Details", "area"]],
  certifications: [["name", "Name"], ["issuer", "Issuer"], ["year", "Year"]],
  achievements: [["text", "Achievement", "area"]],
};

function itemTitle(section, it) {
  if (section === "skills") return esc(it.name);
  if (section === "experiences") return `${esc(it.title || "")} ${it.company ? "@ " + esc(it.company) : ""}`;
  if (section === "projects") return esc(it.name);
  if (section === "education") return esc(it.degree || it.institution || "");
  if (section === "certifications") return esc(it.name);
  if (section === "achievements") return esc(it.text);
  return "";
}
function itemSub(section, it) {
  if (section === "skills") return esc(it.category || "");
  if (section === "experiences") return esc([it.start, it.end].filter(Boolean).join(" – ") + (it.location ? " · " + it.location : ""));
  if (section === "projects") return esc((it.tech_stack || []).join(", "));
  if (section === "education") return esc([it.start, it.end].filter(Boolean).join(" – "));
  if (section === "certifications") return esc([it.issuer, it.year].filter(Boolean).join(" · "));
  return "";
}
function itemList(section, it) {
  if (section === "experiences") return (it.bullets || []).map((b) => b.text || b);
  if (section === "projects") return (it.outcomes || []).map((o) => o.text || o);
  return [];
}

function renderProfile(profile) {
  if (!profile) return;
  $("profileEmpty").classList.add("hidden");
  const col = $("profileCards");
  col.innerHTML = "";

  // Personal (read-only)
  const c = profile.contact || {};
  const personal = document.createElement("div");
  personal.className = "section-card";
  const contactBits = [c.name, c.email, c.phone, c.location, c.linkedin, c.github, c.portfolio]
    .filter(Boolean).map(esc).join(" · ");
  personal.innerHTML = `<h3>personal</h3><div class="item"><div class="title">${esc(c.name || "—")}</div>
    <div class="sub">${contactBits || "No contact details yet"}</div>
    ${profile.headline ? `<div class="sub">${esc(profile.headline)}</div>` : ""}</div>`;
  col.appendChild(personal);

  for (const section of SECTIONS) {
    const items = profile[section] || [];
    const card = document.createElement("div");
    card.className = "section-card";
    card.innerHTML = `<h3>${section}</h3>`;
    if (!items.length) card.innerHTML += `<div class="muted">Nothing yet.</div>`;
    items.forEach((it) => card.appendChild(renderItem(section, it)));
    col.appendChild(card);
  }
}

function renderItem(section, it) {
  const wrap = document.createElement("div");
  wrap.className = "item";
  const list = itemList(section, it);
  wrap.innerHTML = `
    <div class="item-head">
      <span class="title">${itemTitle(section, it)}</span>
      <span></span>
    </div>
    ${itemSub(section, it) ? `<div class="sub">${itemSub(section, it)}</div>` : ""}
    ${list.length ? `<ul>${list.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}`;

  const actions = wrap.querySelector(".item-head span:last-child");
  const editBtn = document.createElement("button");
  editBtn.className = "tiny secondary"; editBtn.textContent = "Edit";
  const delBtn = document.createElement("button");
  delBtn.className = "tiny secondary"; delBtn.textContent = "✕";
  actions.append(editBtn, delBtn);

  editBtn.onclick = () => wrap.appendChild(buildEditForm(section, it, wrap));
  delBtn.onclick = async () => {
    if (!it.item_id || !confirm("Delete this item?")) return;
    try {
      await postJSON(`/profile/${encodeURIComponent(userId())}/${section}/${it.item_id}`, undefined, "DELETE");
      refreshProfile();
    } catch (e) { alert(e.message); }
  };
  return wrap;
}

function buildEditForm(section, it, wrap) {
  if (wrap.querySelector(".edit-grid")) return document.createComment("");
  const form = document.createElement("div");
  form.className = "edit-grid";
  const inputs = {};
  for (const [key, label, type] of FIELDS[section]) {
    const l = document.createElement("label"); l.textContent = label;
    let input;
    if (type === "area" || type === "bullets" || type === "outcomes") {
      input = document.createElement("textarea");
      if (type === "bullets") input.value = (it.bullets || []).map((b) => b.text || b).join("\n");
      else if (type === "outcomes") input.value = (it.outcomes || []).map((o) => o.text || o).join("\n");
      else input.value = it[key] ?? "";
    } else {
      input = document.createElement("input");
      input.value = type === "csv" ? (it[key] || []).join(", ") : (it[key] ?? "");
    }
    inputs[key] = { input, type };
    form.append(l, input);
  }
  const save = document.createElement("button");
  save.className = "tiny"; save.textContent = "Save";
  save.onclick = async () => {
    const patch = {};
    for (const [key, { input, type }] of Object.entries(inputs)) {
      const v = input.value;
      if (type === "csv") patch[key] = v.split(",").map((s) => s.trim()).filter(Boolean);
      else if (type === "bullets" || type === "outcomes")
        patch[key] = v.split("\n").map((s) => s.trim()).filter(Boolean).map((text) => ({ text }));
      else patch[key] = v;
    }
    try {
      await postJSON(`/profile/${encodeURIComponent(userId())}/${section}/${it.item_id}`, patch, "PATCH");
      refreshProfile();
    } catch (e) { alert(e.message); }
  };
  const cancel = document.createElement("button");
  cancel.className = "tiny secondary"; cancel.textContent = "Cancel";
  cancel.onclick = () => form.remove();
  const bar = document.createElement("div"); bar.className = "row"; bar.append(save, cancel);
  form.appendChild(bar);
  return form;
}

// ============================================================================
// RESUME TAILOR
// ============================================================================
let tailorWS = null;
let currentJD = "";

$("startTailor").onclick = () => {
  const jd = $("jdText").value.trim();
  if (!jd) { alert("Paste a job description first."); return; }
  currentJD = jd;
  if (tailorWS) { try { tailorWS.close(); } catch (e) {} }
  $("tailorChat").innerHTML = "";
  $("variantsEmpty").classList.add("hidden");
  $("variantsCol").querySelectorAll(".variant").forEach((v) => v.remove());

  const ws = new WebSocket(wsUrl(`/ws/tailor/${encodeURIComponent(userId())}`));
  tailorWS = ws;
  $("tailorConn").textContent = "connecting…";
  ws.onopen = () => { $("tailorConn").textContent = "connected"; ws.send(JSON.stringify({ type: "start", job_description: jd })); };
  ws.onclose = () => { $("tailorConn").textContent = "disconnected"; };
  ws.onerror = () => { $("tailorConn").textContent = "error"; };
  ws.onmessage = (ev) => handleTailorEvent(JSON.parse(ev.data));
};

$("sendTailor").onclick = sendTailorReply;
$("tailorReply").addEventListener("keydown", (e) => { if (e.key === "Enter") sendTailorReply(); });

function sendTailorReply() {
  const v = $("tailorReply").value.trim();
  if (!v || !tailorWS) return;
  bubble($("tailorChat"), v, "me");
  tailorWS.send(JSON.stringify({ type: "reply", message: v }));
  $("tailorReply").value = "";
  $("tailorReplyCard").classList.add("hidden");
}

function handleTailorEvent(msg) {
  const chat = $("tailorChat");
  switch (msg.type) {
    case "status": bubble(chat, msg.message, "sys"); break;
    case "question":
      bubble(chat, msg.question, "bot");
      $("tailorReplyCard").classList.remove("hidden");
      $("tailorReply").focus();
      break;
    case "variants": renderVariants(msg.variants); break;
    case "done": bubble(chat, "✓ Done.", "sys"); break;
    case "error": bubble(chat, "Error: " + msg.detail, "sys"); break;
  }
}

function renderVariants(variants) {
  const col = $("variantsCol");
  col.querySelectorAll(".variant").forEach((v) => v.remove());
  $("variantsEmpty").classList.add("hidden");
  (variants || []).forEach((v) => col.appendChild(renderVariant(v)));
}

function renderVariant(v) {
  const ats = v.ats || {};
  const analysis = v.analysis || {};
  const card = document.createElement("div");
  card.className = "variant";
  const matched = (ats.matched || []).slice(0, 14).map((k) => `<span class="pill good">${esc(k)}</span>`).join("");
  const missing = (ats.missing || []).slice(0, 14).map((k) => `<span class="pill bad">${esc(k)}</span>`).join("");
  card.innerHTML = `
    <div class="vhead">
      <span class="label">${esc(v.label)}</span>
      <div style="text-align:right">
        <div class="score">${ats.score ?? "–"}</div>
        <div class="matchpct">match ${Math.round((ats.match_pct || 0) * 100)}%</div>
      </div>
    </div>
    <div style="margin-top:6px"><span class="muted">Matched:</span> ${matched || '<span class="muted">—</span>'}</div>
    <div style="margin-top:4px"><span class="muted">Missing:</span> ${missing || '<span class="muted">—</span>'}</div>`;

  const actions = document.createElement("div");
  actions.className = "row";
  if (v.pdf_url) {
    const a = document.createElement("a");
    a.className = "download"; a.href = v.pdf_url; a.target = "_blank"; a.textContent = "⬇ PDF";
    actions.appendChild(a);
  } else {
    const s = document.createElement("span"); s.className = "muted";
    s.textContent = v.render_error ? "PDF unavailable" : "PDF pending";
    actions.appendChild(s);
  }
  const prevBtn = document.createElement("button");
  prevBtn.className = "tiny secondary"; prevBtn.textContent = "Preview";
  const editBtn = document.createElement("button");
  editBtn.className = "tiny secondary"; editBtn.textContent = "Edit & re-score";
  actions.append(prevBtn, editBtn);
  card.appendChild(actions);

  const preview = document.createElement("div");
  preview.className = "preview hidden";
  preview.textContent = previewText(v.resume || {});
  card.appendChild(preview);
  prevBtn.onclick = () => preview.classList.toggle("hidden");

  editBtn.onclick = () => {
    if (card.querySelector(".rescore")) return;
    const box = document.createElement("div");
    box.className = "rescore";
    const ta = document.createElement("textarea");
    ta.value = JSON.stringify(v.resume || {}, null, 2);
    ta.style.minHeight = "200px";
    const btn = document.createElement("button");
    btn.className = "tiny"; btn.textContent = "Re-score";
    const out = document.createElement("span"); out.className = "status";
    btn.onclick = async () => {
      let resume_json;
      try { resume_json = JSON.parse(ta.value); }
      catch (e) { out.textContent = "Invalid JSON"; return; }
      out.textContent = "scoring…";
      try {
        const r = await postJSON("/score", { resume_json, job_description: currentJD });
        v.resume = resume_json; v.ats = r.ats;
        card.replaceWith(renderVariant(v));
      } catch (e) { out.textContent = e.message; }
    };
    const bar = document.createElement("div"); bar.className = "row"; bar.append(btn, out);
    box.append(ta, bar);
    card.appendChild(box);
  };
  return card;
}

function previewText(resume) {
  const lines = [];
  if (resume.name) lines.push(resume.name);
  if (resume.summary) lines.push("\n" + resume.summary);
  if (resume.core_competencies?.length) lines.push("\nSkills: " + resume.core_competencies.join(", "));
  for (const job of resume.experience || []) {
    lines.push(`\n${job.title || ""} @ ${job.company || ""} (${job.start || ""}–${job.end || ""})`);
    (job.bullets || []).forEach((b) => lines.push("  • " + b));
  }
  for (const p of resume.projects || []) {
    lines.push(`\n${p.name || ""} [${(p.tech || []).join(", ")}]`);
    (p.bullets || []).forEach((b) => lines.push("  • " + b));
  }
  return lines.join("\n");
}
