/*
 * Concept Factory — in-page tools widget.
 *
 * Injected by the backend into every served concept's index.html. Renders:
 *   • Draggable credits HUD — console.x.ai prepaid $ remaining
 *   • Bottom-right launcher that opens a panel with three tabs:
 *       – Chat     — live tutor Q&A about this topic (does not edit the app)
 *       – Improve  — ask Grok to change this app and rebuild in place
 *       – Versions — git history with one-click "serve this version"
 *
 * Everything lives in shadow roots so the concept's own CSS can't touch it.
 * It talks to the backend via slug-scoped endpoints; the slug is derived from
 * the URL (…/concepts/<slug>/…) or window.__CONCEPT_SLUG__ if injected.
 */
(function () {
  if (window.__conceptWidgetMounted) return;
  window.__conceptWidgetMounted = true;

  var slug =
    window.__CONCEPT_SLUG__ ||
    (location.pathname.match(/\/concepts\/([^/]+)/) || [])[1] ||
    "";
  if (!slug) return;

  var api = {
    history: function () {
      return fetch("/api/concepts/" + slug + "/history").then(function (r) {
        return r.json();
      });
    },
    status: function () {
      return fetch("/api/concepts/" + slug + "/status").then(function (r) {
        return r.json();
      });
    },
    log: function () {
      return fetch("/api/concepts/" + slug + "/log").then(function (r) {
        return r.json();
      });
    },
    improve: function (prompt) {
      return fetch("/api/concepts/" + slug + "/improve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt }),
      }).then(function (r) {
        return r.json();
      });
    },
    revert: function (hash) {
      return fetch("/api/concepts/" + slug + "/revert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hash: hash }),
      }).then(function (r) {
        return r.json();
      });
    },
    chatHistory: function () {
      return fetch("/api/concepts/" + slug + "/chat").then(function (r) {
        return r.json();
      });
    },
    chatClear: function () {
      return fetch("/api/concepts/" + slug + "/chat", { method: "DELETE" }).then(
        function (r) {
          return r.json();
        }
      );
    },
    credits: function (force) {
      return fetch("/api/credits" + (force ? "?force=1" : "")).then(function (r) {
        return r.json();
      });
    },
  };

  function relTime(iso) {
    var s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
    if (isNaN(s)) return "";
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Balance HUD (draggable; console.x.ai prepaid remaining) ────────────
  var BAL_POS_KEY = "cf-credits-hud-pos";
  var BAL_CSS =
    ":host { all: initial; }" +
    "*, *::before, *::after { box-sizing: border-box; }" +
    ".bal {" +
    "  position: fixed; top: 14px; left: 14px; z-index: 2147483646;" +
    "  font-family: ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif;" +
    "  display: flex; align-items: center; gap: 10px;" +
    "  padding: 8px 12px 8px 10px; border-radius: 14px;" +
    "  background: rgba(14,16,23,.88); color: #e2e8f0;" +
    "  border: 1px solid rgba(255,255,255,.1);" +
    "  box-shadow: 0 10px 28px rgba(0,0,0,.4), inset 0 1px 0 rgba(255,255,255,.05);" +
    "  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);" +
    "  cursor: grab; user-select: none; touch-action: none;" +
    "  max-width: min(320px, calc(100vw - 28px));" +
    "}" +
    ".bal.dragging { cursor: grabbing; border-color: rgba(167,139,250,.45); }" +
    ".bal:hover { border-color: rgba(167,139,250,.35); }" +
    ".bal .dot {" +
    "  width: 9px; height: 9px; border-radius: 999px; flex: none;" +
    "  background: #64748b; box-shadow: 0 0 0 3px rgba(100,116,139,.2);" +
    "}" +
    ".bal.ok .dot { background: #34d399; box-shadow: 0 0 0 3px rgba(52,211,153,.22); }" +
    ".bal.warn .dot { background: #fbbf24; box-shadow: 0 0 0 3px rgba(251,191,36,.22); }" +
    ".bal.low .dot { background: #f87171; box-shadow: 0 0 0 3px rgba(248,113,113,.22); animation: pulse 1.2s ease infinite; }" +
    "@keyframes pulse { 50% { opacity: .55; } }" +
    ".bal .col { min-width: 0; flex: 1; }" +
    ".bal .kicker {" +
    "  font-size: 9.5px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase;" +
    "  color: #64748b; line-height: 1;" +
    "}" +
    ".bal .label {" +
    "  margin-top: 3px; font-size: 12.5px; font-weight: 600; color: #f1f5f9;" +
    "  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" +
    "}" +
    ".bal .bar {" +
    "  margin-top: 5px; height: 4px; border-radius: 999px; background: rgba(255,255,255,.08);" +
    "  overflow: hidden;" +
    "}" +
    ".bal .bar > i {" +
    "  display: block; height: 100%; border-radius: 999px;" +
    "  background: linear-gradient(90deg, #34d399, #a78bfa);" +
    "  transition: width .4s ease;" +
    "}" +
    ".bal.low .bar > i { background: linear-gradient(90deg, #f87171, #fbbf24); }" +
    ".bal .meta {" +
    "  margin-top: 3px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;" +
    "  font-size: 10px; color: #64748b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" +
    "}" +
    ".bal .refresh {" +
    "  flex: none; border: none; background: rgba(255,255,255,.06); color: #94a3b8;" +
    "  width: 26px; height: 26px; border-radius: 8px; cursor: pointer; font-size: 13px;" +
    "}" +
    ".bal .refresh:hover { color: #e2e8f0; background: rgba(255,255,255,.1); }";

  var balHost = document.createElement("div");
  document.body.appendChild(balHost);
  var balSr = balHost.attachShadow({ mode: "open" });
  balSr.innerHTML = "<style>" + BAL_CSS + "</style><div class='bal' id='bal'></div>";
  var balEl = balSr.getElementById("bal");
  var balData = null;
  var balPos = null;
  var balDrag = null;

  try {
    var savedPos = localStorage.getItem(BAL_POS_KEY);
    if (savedPos) {
      var p = JSON.parse(savedPos);
      if (typeof p.x === "number" && typeof p.y === "number") balPos = p;
    }
  } catch (e) {}

  function clampBalPos(x, y) {
    var w = balEl.offsetWidth || 180;
    var h = balEl.offsetHeight || 48;
    var maxX = Math.max(8, window.innerWidth - w - 8);
    var maxY = Math.max(8, window.innerHeight - h - 8);
    return {
      x: Math.min(maxX, Math.max(8, x)),
      y: Math.min(maxY, Math.max(8, y)),
    };
  }

  function applyBalPos() {
    if (!balPos) {
      balEl.style.left = "14px";
      balEl.style.top = "14px";
      return;
    }
    var c = clampBalPos(balPos.x, balPos.y);
    balPos = c;
    balEl.style.left = c.x + "px";
    balEl.style.top = c.y + "px";
  }

  function balTone(d) {
    if (d.ok === false) return "low";
    var pct = d.pct;
    if (pct != null) {
      if (pct <= 12) return "low";
      if (pct <= 30) return "warn";
      return "ok";
    }
    if (d.remainingUsd != null && d.remainingUsd < 0) return "low";
    return "ok";
  }

  function renderBalance() {
    var d = balData || {};
    var pct = d.pct != null ? d.pct : null;
    var tone = balTone(d);
    var dragging = balEl.classList.contains("dragging");
    balEl.className = "bal " + tone + (dragging ? " dragging" : "");
    balEl.title =
      (d.detail || d.error || "Credits from console.x.ai") + " · drag to move";
    balEl.innerHTML =
      '<span class="dot" aria-hidden="true"></span>' +
      '<div class="col">' +
      '<div class="kicker">Credits</div>' +
      '<div class="label">' +
      escapeHtml(d.label || "Loading…") +
      "</div>" +
      (pct != null
        ? '<div class="bar" title="' +
          pct +
          '% of prepaid left"><i style="width:' +
          Math.max(0, Math.min(100, pct)) +
          '%"></i></div>'
        : "") +
      '<div class="meta">' +
      escapeHtml(d.detail || d.error || "Fetching balance…") +
      "</div>" +
      "</div>" +
      '<button class="refresh" title="Refresh from console.x.ai" type="button">↻</button>';
    balEl.querySelector(".refresh").onclick = function (e) {
      e.stopPropagation();
      refreshBalance(true);
    };
    balEl.querySelector(".refresh").onpointerdown = function (e) {
      e.stopPropagation();
    };
    applyBalPos();
  }

  balEl.addEventListener("pointerdown", function (e) {
    if (e.button != null && e.button !== 0) return;
    if (e.target && e.target.closest && e.target.closest(".refresh")) return;
    var r = balEl.getBoundingClientRect();
    balPos = balPos || { x: r.left, y: r.top };
    balDrag = {
      startX: e.clientX,
      startY: e.clientY,
      origX: balPos.x,
      origY: balPos.y,
      moved: false,
    };
    balEl.classList.add("dragging");
    try {
      balEl.setPointerCapture(e.pointerId);
    } catch (err) {}
    e.preventDefault();
  });

  balEl.addEventListener("pointermove", function (e) {
    if (!balDrag) return;
    var dx = e.clientX - balDrag.startX;
    var dy = e.clientY - balDrag.startY;
    if (Math.abs(dx) + Math.abs(dy) > 3) balDrag.moved = true;
    balPos = clampBalPos(balDrag.origX + dx, balDrag.origY + dy);
    applyBalPos();
  });

  function endBalDrag(e) {
    if (!balDrag) return;
    if (balDrag.moved && balPos) {
      try {
        localStorage.setItem(BAL_POS_KEY, JSON.stringify(balPos));
      } catch (err) {}
    }
    balDrag = null;
    balEl.classList.remove("dragging");
    if (e && e.pointerId != null) {
      try {
        balEl.releasePointerCapture(e.pointerId);
      } catch (err) {}
    }
  }

  balEl.addEventListener("pointerup", endBalDrag);
  balEl.addEventListener("pointercancel", endBalDrag);
  balEl.addEventListener("dblclick", function () {
    balPos = null;
    try {
      localStorage.removeItem(BAL_POS_KEY);
    } catch (err) {}
    applyBalPos();
  });
  window.addEventListener("resize", function () {
    if (balPos) applyBalPos();
  });

  function refreshBalance(force) {
    api
      .credits(!!force)
      .then(function (d) {
        balData = d;
        renderBalance();
      })
      .catch(function () {
        balData = {
          ok: false,
          label: "Balance offline",
          detail: "Couldn't reach backend",
        };
        renderBalance();
      });
  }

  renderBalance();
  refreshBalance(false);
  setInterval(function () {
    refreshBalance(false);
  }, 25000);

  // ── Tools panel (bottom-right) ──────────────────────────────────────────
  var CSS =
    ":host { all: initial; }" +
    "*, *::before, *::after { box-sizing: border-box; }" +
    ".root {" +
    "  position: fixed; right: 20px; bottom: 20px; z-index: 2147483647;" +
    "  font-family: ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif;" +
    "  color: #e2e8f0;" +
    "}" +
    ".fab {" +
    "  width: 52px; height: 52px; border-radius: 999px; border: none; cursor: pointer;" +
    "  display: grid; place-items: center; color: #fff;" +
    "  background: linear-gradient(135deg, #7c3aed, #6366f1);" +
    "  box-shadow: 0 8px 24px rgba(99,102,241,.45), 0 2px 6px rgba(0,0,0,.3);" +
    "  transition: transform .15s ease, box-shadow .15s ease;" +
    "}" +
    ".fab:hover { transform: translateY(-2px) scale(1.04); box-shadow: 0 12px 30px rgba(99,102,241,.55); }" +
    ".fab:active { transform: scale(.96); }" +
    ".fab svg { width: 24px; height: 24px; }" +
    ".panel {" +
    "  position: absolute; right: 0; bottom: 64px; width: 392px; max-width: calc(100vw - 40px);" +
    "  height: 560px; max-height: calc(100vh - 96px);" +
    "  display: flex; flex-direction: column; overflow: hidden;" +
    "  background: #0e1017; border: 1px solid rgba(255,255,255,.09);" +
    "  border-radius: 18px; box-shadow: 0 24px 60px rgba(0,0,0,.55);" +
    "  transform-origin: bottom right; animation: pop .16s ease;" +
    "}" +
    "@keyframes pop { from { opacity: 0; transform: translateY(8px) scale(.97); } }" +
    ".hdr { display: flex; align-items: center; gap: 10px; padding: 14px 16px 0; }" +
    ".hdr .title { font-size: 13px; font-weight: 600; letter-spacing: .01em; flex: 1; }" +
    ".hdr .slug { font-family: ui-monospace, monospace; font-size: 11px; color: #64748b; }" +
    ".close { background: none; border: none; color: #64748b; cursor: pointer; font-size: 18px; line-height: 1; padding: 2px 6px; border-radius: 8px; }" +
    ".close:hover { color: #e2e8f0; background: rgba(255,255,255,.06); }" +
    ".tabs { display: flex; gap: 3px; padding: 12px 12px 0; }" +
    ".tab {" +
    "  flex: 1; padding: 8px 2px; border: none; cursor: pointer; border-radius: 10px;" +
    "  background: transparent; color: #94a3b8; font-size: 11.5px; font-weight: 600;" +
    "  display: flex; align-items: center; justify-content: center; gap: 5px;" +
    "}" +
    ".tab:hover { color: #e2e8f0; background: rgba(255,255,255,.04); }" +
    ".tab.active { background: rgba(124,58,237,.18); color: #c4b5fd; }" +
    ".tab svg { width: 14px; height: 14px; flex: none; }" +
    ".body { flex: 1; overflow-y: auto; padding: 14px 16px 16px; min-height: 0; }" +
    ".body.chat-body { display: flex; flex-direction: column; padding: 0; overflow: hidden; }" +
    ".intro { font-size: 12.5px; line-height: 1.55; color: #94a3b8; margin: 0 0 12px; }" +
    "textarea, .chat-input {" +
    "  width: 100%; min-height: 96px; resize: vertical; border-radius: 12px; padding: 11px 12px;" +
    "  background: #14171f; border: 1px solid rgba(255,255,255,.09); color: #e2e8f0;" +
    "  font: inherit; font-size: 13px; line-height: 1.5; outline: none;" +
    "}" +
    "textarea:focus, .chat-input:focus { border-color: rgba(124,58,237,.6); }" +
    "textarea::placeholder, .chat-input::placeholder { color: #475569; }" +
    ".chat-input { min-height: 44px; max-height: 120px; resize: none; }" +
    ".send {" +
    "  margin-top: 10px; width: 100%; padding: 10px; border: none; border-radius: 12px; cursor: pointer;" +
    "  background: linear-gradient(135deg, #7c3aed, #6366f1); color: #fff; font-size: 13px; font-weight: 600;" +
    "  transition: filter .15s ease, opacity .15s ease;" +
    "}" +
    ".send:hover { filter: brightness(1.1); }" +
    ".send:disabled { opacity: .45; cursor: not-allowed; }" +
    ".send.sm { margin-top: 0; width: auto; padding: 10px 14px; flex: none; }" +
    ".commit { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid rgba(255,255,255,.06); }" +
    ".commit:first-child { border-top: none; }" +
    ".commit .info { min-width: 0; flex: 1; }" +
    ".commit .msg { font-size: 12.5px; color: #cbd5e1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }" +
    ".commit .meta { font-family: ui-monospace, monospace; font-size: 11px; color: #64748b; margin-top: 2px; }" +
    ".pill { font-size: 10.5px; font-weight: 600; padding: 3px 8px; border-radius: 999px; background: rgba(52,211,153,.18); color: #6ee7b7; white-space: nowrap; }" +
    ".revert {" +
    "  font-size: 11.5px; font-weight: 600; padding: 5px 10px; border-radius: 9px; cursor: pointer; white-space: nowrap;" +
    "  background: transparent; border: 1px solid rgba(255,255,255,.14); color: #cbd5e1;" +
    "}" +
    ".revert:hover { background: rgba(255,255,255,.06); border-color: rgba(255,255,255,.25); }" +
    ".empty { font-size: 12.5px; color: #64748b; padding: 8px 0; }" +
    ".busy { position: absolute; inset: 0; background: #0e1017; display: flex; flex-direction: column; padding: 14px 16px 16px; }" +
    ".busy .hd { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }" +
    ".spinner { width: 16px; height: 16px; flex: none; border-radius: 999px; border: 2px solid rgba(124,58,237,.28); border-top-color: #a78bfa; animation: spin .8s linear infinite; }" +
    "@keyframes spin { to { transform: rotate(360deg); } }" +
    ".busy .t1 { font-size: 13px; font-weight: 600; }" +
    ".stream {" +
    "  flex: 1; min-height: 0; overflow-y: auto; border-radius: 12px; padding: 11px 12px;" +
    "  background: #06070b; border: 1px solid rgba(255,255,255,.07);" +
    "  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; line-height: 1.55; color: #cbd5e1;" +
    "  white-space: pre-wrap; word-break: break-word;" +
    "}" +
    ".stream .waiting { color: #64748b; }" +
    ".caret { display: inline-block; width: 7px; height: 13px; margin-top: 2px; background: rgba(52,211,153,.7); animation: blink 1s steps(2) infinite; }" +
    "@keyframes blink { 50% { opacity: 0; } }" +
    ".err { margin: 0; font-size: 12.5px; color: #fca5a5; background: rgba(244,63,94,.1); border: 1px solid rgba(244,63,94,.25); border-radius: 10px; padding: 10px 12px; }" +
    /* Chat */
    ".chat-msgs {" +
    "  flex: 1; min-height: 0; overflow-y: auto; padding: 14px 16px;" +
    "  display: flex; flex-direction: column; gap: 10px;" +
    "}" +
    ".bubble {" +
    "  max-width: 92%; padding: 9px 12px; border-radius: 14px;" +
    "  font-size: 13px; line-height: 1.5; white-space: pre-wrap; word-break: break-word;" +
    "}" +
    ".bubble.user {" +
    "  align-self: flex-end; background: rgba(124,58,237,.28); color: #ede9fe;" +
    "  border-bottom-right-radius: 5px;" +
    "}" +
    ".bubble.assistant {" +
    "  align-self: flex-start; background: #14171f; color: #e2e8f0;" +
    "  border: 1px solid rgba(255,255,255,.07); border-bottom-left-radius: 5px;" +
    "}" +
    ".bubble.assistant.streaming { border-color: rgba(124,58,237,.35); }" +
    ".bubble .who {" +
    "  display: block; font-size: 10px; font-weight: 700; letter-spacing: .06em;" +
    "  text-transform: uppercase; color: #64748b; margin-bottom: 4px;" +
    "}" +
    ".chat-empty {" +
    "  margin: auto; text-align: center; padding: 16px; color: #64748b; font-size: 12.5px; line-height: 1.55;" +
    "}" +
    ".chat-empty strong { display: block; color: #cbd5e1; font-size: 13.5px; margin-bottom: 6px; }" +
    ".chat-suggestions { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; margin-top: 12px; }" +
    ".chip {" +
    "  border: 1px solid rgba(255,255,255,.1); background: rgba(255,255,255,.04);" +
    "  color: #cbd5e1; font-size: 11.5px; padding: 6px 10px; border-radius: 999px; cursor: pointer;" +
    "}" +
    ".chip:hover { background: rgba(124,58,237,.15); border-color: rgba(124,58,237,.35); color: #e9d5ff; }" +
    ".chat-composer {" +
    "  display: flex; gap: 8px; padding: 10px 12px 12px; border-top: 1px solid rgba(255,255,255,.07);" +
    "  background: #0b0d12; align-items: flex-end;" +
    "}" +
    ".chat-toolbar {" +
    "  display: flex; justify-content: space-between; align-items: center;" +
    "  padding: 8px 14px 0; font-size: 11px; color: #64748b;" +
    "}" +
    ".chat-toolbar button {" +
    "  background: none; border: none; color: #64748b; cursor: pointer; font-size: 11px; font-weight: 600;" +
    "}" +
    ".chat-toolbar button:hover { color: #c4b5fd; }";

  var host = document.createElement("div");
  document.body.appendChild(host);
  var sr = host.attachShadow({ mode: "open" });
  sr.innerHTML = "<style>" + CSS + "</style><div class='root'></div>";
  var root = sr.querySelector(".root");

  var ICON_CHAT =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7a8.5 8.5 0 0 1 3.5-11.3 8.38 8.38 0 0 1 12.6 7.5z"/></svg>';
  var ICON_SPARK =
    '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.6 5.8L19 9l-5.4 1.2L12 16l-1.6-5.8L5 9l5.4-1.2z"/></svg>';
  var ICON_CLOCK =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>';
  var ICON_BUBBLE =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';

  var open = false;
  var tab = "chat"; // chat | improve | versions
  var busy = false;
  var busyMsg = "";
  var busyGrok = false;
  var errMsg = "";
  var commits = [];
  var served = "";
  var draft = ""; // improve draft
  var logLines = [];
  var pollTimer = null;

  // Chat state
  var chatMessages = []; // {role, content}
  var chatDraft = "";
  var chatStreaming = false;
  var chatStreamBuf = "";
  var chatError = "";
  var chatTitle = "";

  var SUGGESTIONS = [
    "Explain the core idea in one minute",
    "Where do people usually get stuck?",
    "Give me a hint for level 1",
    "Quiz me on this topic",
  ];

  function poll() {
    api
      .log()
      .then(function (r) {
        logLines = r.lines || [];
        if (r.status === "built") {
          clearInterval(pollTimer);
          location.reload();
        } else if (r.status === "error") {
          clearInterval(pollTimer);
          busy = false;
          errMsg = r.error || "Something went wrong.";
          render();
        } else {
          renderStream();
        }
      })
      .catch(function () {});
  }

  function startPolling(message, isGrok) {
    busy = true;
    busyMsg = message;
    busyGrok = !!isGrok;
    errMsg = "";
    logLines = [];
    render();
    if (pollTimer) clearInterval(pollTimer);
    poll();
    pollTimer = setInterval(poll, 1200);
  }

  function loadHistory() {
    api
      .history()
      .then(function (r) {
        commits = r.commits || [];
        served = r.served || "";
        if (r.status === "building") startPolling("Working…", false);
        render();
      })
      .catch(function () {
        errMsg = "Couldn't load version history (backend error).";
        render();
      });
  }

  function loadChat() {
    api
      .chatHistory()
      .then(function (r) {
        chatMessages = r.messages || [];
        chatTitle = r.title || "";
        render();
        scrollChat();
      })
      .catch(function () {});
  }

  function sendImprove() {
    var text = draft.trim();
    if (!text) return;
    draft = "";
    api.improve(text).then(function () {
      startPolling("Grok is improving this app…", true);
    });
  }

  function doRevert(hash) {
    api.revert(hash).then(function () {
      startPolling("Switching to this version…", false);
    });
  }

  function scrollChat() {
    var el = root.querySelector("#chat-msgs");
    if (el) el.scrollTop = el.scrollHeight;
  }

  function sendChat(text) {
    text = (text == null ? chatDraft : text).trim();
    if (!text || chatStreaming) return;
    chatDraft = "";
    chatError = "";
    chatMessages.push({ role: "user", content: text });
    chatStreaming = true;
    chatStreamBuf = "";
    render();
    scrollChat();

    fetch("/api/concepts/" + slug + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    })
      .then(function (res) {
        if (!res.ok) {
          return res.text().then(function (t) {
            throw new Error(t || "Chat failed (" + res.status + ")");
          });
        }
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var buf = "";

        function pump() {
          return reader.read().then(function (result) {
            if (result.done) {
              finishStream();
              return;
            }
            buf += decoder.decode(result.value, { stream: true });
            var parts = buf.split("\n");
            buf = parts.pop() || "";
            for (var i = 0; i < parts.length; i++) {
              var line = parts[i].trim();
              if (line.indexOf("data:") !== 0) continue;
              var raw = line.slice(5).trim();
              if (!raw) continue;
              var evt;
              try {
                evt = JSON.parse(raw);
              } catch (e) {
                continue;
              }
              if (evt.type === "text" && evt.data) {
                chatStreamBuf += evt.data;
                renderChatLive();
              } else if (evt.type === "error") {
                chatError = evt.message || "Chat error";
              } else if (evt.type === "end") {
                if (evt.text) chatStreamBuf = evt.text;
              }
            }
            return pump();
          });
        }
        return pump();
      })
      .catch(function (e) {
        chatError = (e && e.message) || "Network error";
        finishStream();
      });
  }

  function finishStream() {
    if (chatStreamBuf) {
      chatMessages.push({ role: "assistant", content: chatStreamBuf });
    }
    chatStreamBuf = "";
    chatStreaming = false;
    render();
    scrollChat();
    // Chat burned tokens — refresh the balance pill.
    refreshBalance(true);
  }

  function renderChatLive() {
    // Update only the streaming bubble + scroll, avoid full re-render thrash.
    var el = root.querySelector("#chat-msgs");
    if (!el) {
      render();
      return;
    }
    var streamEl = el.querySelector(".bubble.streaming .txt");
    if (streamEl) {
      streamEl.textContent = chatStreamBuf || "…";
      el.scrollTop = el.scrollHeight;
    } else {
      render();
      scrollChat();
    }
  }

  function clearChat() {
    if (!confirm("Clear this chat?")) return;
    api.chatClear().then(function () {
      chatMessages = [];
      chatStreamBuf = "";
      chatError = "";
      render();
    });
  }

  function renderChatBody() {
    var msgsHtml = "";
    if (chatMessages.length === 0 && !chatStreaming) {
      msgsHtml =
        '<div class="chat-empty">' +
        "<strong>Ask about this concept</strong>" +
        "Clarifications, mental models, level hints — Grok tutors from the plan for this page." +
        '<div class="chat-suggestions">' +
        SUGGESTIONS.map(function (s) {
          return (
            '<button type="button" class="chip" data-q="' +
            escapeHtml(s) +
            '">' +
            escapeHtml(s) +
            "</button>"
          );
        }).join("") +
        "</div></div>";
    } else {
      msgsHtml = chatMessages
        .map(function (m) {
          return (
            '<div class="bubble ' +
            (m.role === "user" ? "user" : "assistant") +
            '">' +
            '<span class="who">' +
            (m.role === "user" ? "You" : "Tutor") +
            "</span>" +
            '<span class="txt">' +
            escapeHtml(m.content) +
            "</span></div>"
          );
        })
        .join("");
      if (chatStreaming) {
        msgsHtml +=
          '<div class="bubble assistant streaming">' +
          '<span class="who">Tutor</span>' +
          '<span class="txt">' +
          escapeHtml(chatStreamBuf || "…") +
          '</span><span class="caret"></span></div>';
      }
    }

    return (
      '<div class="chat-toolbar">' +
      "<span>" +
      (chatTitle ? escapeHtml(chatTitle) : "Topic chat") +
      " · Q&amp;A only</span>" +
      (chatMessages.length
        ? '<button type="button" id="chat-clear">Clear</button>'
        : "<span></span>") +
      "</div>" +
      '<div class="chat-msgs" id="chat-msgs">' +
      msgsHtml +
      "</div>" +
      (chatError
        ? '<p class="err" style="margin:0 12px 8px">' +
          escapeHtml(chatError) +
          "</p>"
        : "") +
      '<div class="chat-composer">' +
      '<textarea class="chat-input" id="chat-ta" rows="1" placeholder="Ask a question… (Enter to send, Shift+Enter for newline)"' +
      (chatStreaming ? " disabled" : "") +
      "></textarea>" +
      '<button class="send sm" id="chat-send"' +
      (chatStreaming || !chatDraft.trim() ? " disabled" : "") +
      ">Send</button>" +
      "</div>"
    );
  }

  function render() {
    if (!open) {
      root.innerHTML =
        '<button class="fab" title="Concept tools">' + ICON_CHAT + "</button>";
      root.querySelector(".fab").onclick = function () {
        open = true;
        render();
        loadHistory();
        loadChat();
      };
      return;
    }

    var bodyHtml;
    var bodyClass = "body";
    if (tab === "chat") {
      bodyClass = "body chat-body";
      bodyHtml = renderChatBody();
    } else if (tab === "improve") {
      bodyHtml =
        '<p class="intro">Describe a change and Grok will rebuild this concept in place. The page reloads when it\'s done.</p>' +
        '<textarea id="ta" placeholder="e.g. add a dark-mode toggle, make it mobile-friendly, add two harder levels…"></textarea>' +
        '<button class="send" id="send">Send to Grok</button>' +
        (errMsg
          ? '<p class="err" style="margin-top:12px">' +
            escapeHtml(errMsg) +
            "</p>"
          : "");
    } else {
      if (commits.length === 0) {
        bodyHtml = '<p class="empty">No version history yet.</p>';
      } else {
        var liveHash = served;
        var hasLive = commits.some(function (c) {
          return c.hash === liveHash;
        });
        if (!hasLive) liveHash = commits[0].hash;
        bodyHtml = commits
          .map(function (c) {
            return (
              '<div class="commit">' +
              '<div class="info">' +
              '<div class="msg">' +
              escapeHtml(c.message) +
              "</div>" +
              '<div class="meta">' +
              c.hash.slice(0, 7) +
              " · " +
              relTime(c.date) +
              "</div>" +
              "</div>" +
              (c.hash === liveHash
                ? '<span class="pill">serving now</span>'
                : '<button class="revert" data-hash="' +
                  c.hash +
                  '">Serve this</button>') +
              "</div>"
            );
          })
          .join("");
      }
    }

    root.innerHTML =
      '<div class="panel">' +
      '<div class="hdr"><span class="title">Concept tools</span>' +
      '<span class="slug">' +
      escapeHtml(slug) +
      "</span>" +
      '<button class="close" title="Close">×</button></div>' +
      '<div class="tabs">' +
      '<button class="tab ' +
      (tab === "chat" ? "active" : "") +
      '" data-tab="chat">' +
      ICON_BUBBLE +
      "Chat</button>" +
      '<button class="tab ' +
      (tab === "improve" ? "active" : "") +
      '" data-tab="improve">' +
      ICON_SPARK +
      "Improve</button>" +
      '<button class="tab ' +
      (tab === "versions" ? "active" : "") +
      '" data-tab="versions">' +
      ICON_CLOCK +
      "Versions</button>" +
      "</div>" +
      '<div class="' +
      bodyClass +
      '">' +
      bodyHtml +
      "</div>" +
      (busy
        ? '<div class="busy"><div class="hd"><span class="spinner"></span><span class="t1">' +
          escapeHtml(busyMsg) +
          '</span></div><div class="stream" id="stream"></div></div>'
        : "") +
      "</div>";

    root.querySelector(".close").onclick = function () {
      open = false;
      render();
    };
    var tabs = root.querySelectorAll(".tab");
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].onclick = function () {
        tab = this.getAttribute("data-tab");
        render();
        if (tab === "chat") scrollChat();
      };
    }

    if (tab === "chat" && !busy) {
      var cta = root.querySelector("#chat-ta");
      if (cta) {
        cta.value = chatDraft;
        cta.oninput = function () {
          chatDraft = cta.value;
          var btn = root.querySelector("#chat-send");
          if (btn) btn.disabled = chatStreaming || !chatDraft.trim();
          // auto-grow
          cta.style.height = "auto";
          cta.style.height = Math.min(120, cta.scrollHeight) + "px";
        };
        cta.onkeydown = function (e) {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendChat();
          }
        };
        if (!chatStreaming) cta.focus();
      }
      var sendBtn = root.querySelector("#chat-send");
      if (sendBtn) sendBtn.onclick = function () {
        sendChat();
      };
      var clearBtn = root.querySelector("#chat-clear");
      if (clearBtn) clearBtn.onclick = clearChat;
      var chips = root.querySelectorAll(".chip");
      for (var k = 0; k < chips.length; k++) {
        chips[k].onclick = function () {
          sendChat(this.getAttribute("data-q"));
        };
      }
      scrollChat();
    }

    if (tab === "improve" && !busy) {
      var ta = root.querySelector("#ta");
      ta.value = draft;
      ta.oninput = function () {
        draft = ta.value;
        updateSend();
      };
      ta.onkeydown = function (e) {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
          e.preventDefault();
          sendImprove();
        }
      };
      root.querySelector("#send").onclick = sendImprove;
      updateSend();
      ta.focus();
    }

    var reverts = root.querySelectorAll(".revert");
    for (var j = 0; j < reverts.length; j++) {
      reverts[j].onclick = function () {
        if (
          confirm(
            "Serve this earlier version? A new commit records the rollback."
          )
        ) {
          doRevert(this.getAttribute("data-hash"));
        }
      };
    }
    if (busy) renderStream();
  }

  function renderStream() {
    var el = root.querySelector("#stream");
    if (!el) return;
    if (logLines.length === 0) {
      el.innerHTML =
        '<span class="waiting">' +
        (busyGrok ? "Waiting for Grok…" : "Running…") +
        "</span>";
    } else {
      el.innerHTML =
        logLines.map(escapeHtml).join("\n") + '<span class="caret"></span>';
    }
    el.scrollTop = el.scrollHeight;
  }

  function updateSend() {
    var btn = root.querySelector("#send");
    if (btn) btn.disabled = !draft.trim();
  }

  render();
})();
