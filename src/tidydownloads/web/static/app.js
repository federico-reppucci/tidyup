/* TidyDownloads — Review UI */

let proposals = [];

const EXT_ICONS = {
  ".pdf": "📄", ".doc": "📝", ".docx": "📝", ".rtf": "📝",
  ".xls": "📊", ".xlsx": "📊", ".csv": "📊",
  ".ppt": "📊", ".pptx": "📊",
  ".jpg": "🖼️", ".jpeg": "🖼️", ".png": "🖼️", ".gif": "🖼️",
  ".svg": "🖼️", ".webp": "🖼️", ".heic": "🖼️",
  ".mp3": "🎵", ".wav": "🎵", ".flac": "🎵", ".aac": "🎵",
  ".mp4": "🎬", ".mov": "🎬", ".avi": "🎬", ".mkv": "🎬",
  ".zip": "📦", ".tar": "📦", ".gz": "📦", ".rar": "📦", ".7z": "📦",
  ".py": "💻", ".js": "💻", ".ts": "💻", ".html": "💻", ".css": "💻",
  ".txt": "📃", ".md": "📃",
  ".json": "📋", ".xml": "📋", ".yaml": "📋", ".yml": "📋",
};

function getIcon(filename) {
  const ext = "." + filename.split(".").pop().toLowerCase();
  return EXT_ICONS[ext] || "📎";
}

function getConfidenceClass(c) {
  if (c >= 0.9) return "confidence-high";
  if (c >= 0.7) return "confidence-mid";
  return "confidence-low";
}

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "className") node.className = v;
      else if (k === "textContent") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2).toLowerCase(), v);
      else node.setAttribute(k, v);
    }
  }
  if (children) {
    for (const child of Array.isArray(children) ? children : [children]) {
      if (typeof child === "string") node.appendChild(document.createTextNode(child));
      else if (child) node.appendChild(child);
    }
  }
  return node;
}

function updateCounter() {
  const counter = document.getElementById("counter");
  const btn = document.getElementById("accept-all-btn");
  const container = document.getElementById("proposals-container");
  const empty = document.getElementById("empty-state");

  if (proposals.length === 0) {
    counter.textContent = "";
    btn.style.display = "none";
    container.style.display = "none";
    empty.style.display = "block";
  } else {
    counter.textContent = proposals.length + " file" + (proposals.length !== 1 ? "s" : "") + " to review";
    btn.style.display = "";
    container.style.display = "";
    empty.style.display = "none";
  }
}

function buildCard(p) {
  const filename = p.filename;
  const notFound = p.exists === false;

  const header = el("div", { className: "card-header" }, [
    el("span", { className: "file-icon", textContent: getIcon(filename) }),
    el("span", { className: "file-name", textContent: filename }),
  ]);

  const dest = el("div", { className: "destination" }, [
    el("span", { className: "arrow", textContent: "→" }),
    el("span", { className: "path", textContent: "Documents/" + p.destination }),
  ]);

  const reason = el("div", { className: "reason", textContent: p.reason });

  const badge = el("span", {
    className: "confidence-badge " + getConfidenceClass(p.confidence),
    textContent: (p.confidence * 100).toFixed(0) + "%",
  });

  const actions = el("div", { className: "card-actions" });
  if (!notFound) {
    actions.appendChild(el("button", {
      className: "btn btn-reject",
      textContent: "Reject",
      onClick: function () { rejectFile(filename); },
    }));
    actions.appendChild(el("button", {
      className: "btn btn-accept",
      textContent: "Accept",
      onClick: function () { acceptFile(filename); },
    }));
  }

  const footer = el("div", { className: "card-footer" }, [badge, actions]);

  const card = el("div", {
    className: "card" + (notFound ? " not-found" : ""),
    id: "card-" + encodeURIComponent(filename),
  }, [header, dest, reason, footer]);

  return card;
}

function renderProposals() {
  const container = document.getElementById("proposals-container");
  while (container.firstChild) container.removeChild(container.firstChild);

  for (const p of proposals) {
    container.appendChild(buildCard(p));
  }

  updateCounter();
}

async function apiFetch(url, method) {
  method = method || "GET";
  const sep = url.includes("?") ? "&" : "?";
  const resp = await fetch(url + sep + "token=" + TOKEN, {
    method: method,
    headers: { "X-Auth-Token": TOKEN },
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text);
  }
  return resp.json();
}

async function loadProposals() {
  try {
    proposals = await apiFetch("/api/proposals");
    renderProposals();
  } catch (e) {
    const container = document.getElementById("proposals-container");
    while (container.firstChild) container.removeChild(container.firstChild);
    container.appendChild(el("div", { className: "loading", textContent: "Error loading proposals: " + e.message }));
  }
}

async function acceptFile(filename) {
  const card = document.getElementById("card-" + encodeURIComponent(filename));
  card.querySelectorAll(".btn").forEach(function (b) { b.disabled = true; });

  try {
    await apiFetch("/api/accept/" + encodeURIComponent(filename), "POST");
    card.classList.add("removing");
    setTimeout(function () {
      proposals = proposals.filter(function (p) { return p.filename !== filename; });
      renderProposals();
    }, 350);
  } catch (e) {
    alert("Error accepting file: " + e.message);
    card.querySelectorAll(".btn").forEach(function (b) { b.disabled = false; });
  }
}

async function rejectFile(filename) {
  const card = document.getElementById("card-" + encodeURIComponent(filename));
  card.querySelectorAll(".btn").forEach(function (b) { b.disabled = true; });

  try {
    await apiFetch("/api/reject/" + encodeURIComponent(filename), "POST");
    card.classList.add("removing");
    setTimeout(function () {
      proposals = proposals.filter(function (p) { return p.filename !== filename; });
      renderProposals();
    }, 350);
  } catch (e) {
    alert("Error rejecting file: " + e.message);
    card.querySelectorAll(".btn").forEach(function (b) { b.disabled = false; });
  }
}

async function acceptAll() {
  var btn = document.getElementById("accept-all-btn");
  btn.disabled = true;
  btn.textContent = "Accepting...";

  try {
    var result = await apiFetch("/api/accept-all", "POST");
    proposals = [];
    renderProposals();
    if (result.errors && result.errors.length > 0) {
      alert("Some files had errors:\n" + result.errors.join("\n"));
    }
  } catch (e) {
    alert("Error: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Accept All";
  }
}

loadProposals();
