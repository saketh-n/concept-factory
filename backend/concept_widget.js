/*
 * Concept Factory — in-page tools widget.
 *
 * Injected by the backend into every served concept's index.html. Renders a
 * floating launcher (bottom-right) that opens a panel with two tabs:
 *   • Improve  — chat box that asks Grok to change this app
 *   • Versions — git history with one-click "serve this version"
 *
 * Everything lives in a shadow root so the concept's own CSS can't touch it.
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
      return fetch("/api/concepts/" + slug + "/history").then(r => r.json());
    },
    status: function () {
      return fetch("/api/concepts/" + slug + "/status").then(r => r.json());
    },
    log: function () {
      return fetch("/api/concepts/" + slug + "/log").then(r => r.json());
    },
    improve: function (prompt) {
      return fetch("/api/concepts/" + slug + "/improve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt }),
      }).then(r => r.json());
    },
    revert: function (hash) {
      return fetch("/api/concepts/" + slug + "/revert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hash: hash }),
      }).then(r => r.json());
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

  var CSS = `
    :host { all: initial; }
    *, *::before, *::after { box-sizing: border-box; }
    .root {
      position: fixed; right: 20px; bottom: 20px; z-index: 2147483647;
      font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
      color: #e2e8f0;
    }
    .fab {
      width: 52px; height: 52px; border-radius: 999px; border: none; cursor: pointer;
      display: grid; place-items: center; color: #fff;
      background: linear-gradient(135deg, #7c3aed, #6366f1);
      box-shadow: 0 8px 24px rgba(99,102,241,.45), 0 2px 6px rgba(0,0,0,.3);
      transition: transform .15s ease, box-shadow .15s ease;
    }
    .fab:hover { transform: translateY(-2px) scale(1.04); box-shadow: 0 12px 30px rgba(99,102,241,.55); }
    .fab:active { transform: scale(.96); }
    .fab svg { width: 24px; height: 24px; }
    .fab .badge {
      position: absolute; top: -3px; right: -3px; width: 12px; height: 12px;
      border-radius: 999px; background: #f59e0b; border: 2px solid #0e1017;
    }
    .panel {
      position: absolute; right: 0; bottom: 64px; width: 372px; max-width: calc(100vw - 40px);
      height: 520px; max-height: calc(100vh - 96px);
      display: flex; flex-direction: column; overflow: hidden;
      background: #0e1017; border: 1px solid rgba(255,255,255,.09);
      border-radius: 18px; box-shadow: 0 24px 60px rgba(0,0,0,.55);
      transform-origin: bottom right;
      animation: pop .16s ease;
    }
    @keyframes pop { from { opacity: 0; transform: translateY(8px) scale(.97); } }
    .hdr { display: flex; align-items: center; gap: 10px; padding: 14px 16px 0; }
    .hdr .title { font-size: 13px; font-weight: 600; letter-spacing: .01em; flex: 1; }
    .hdr .slug { font-family: ui-monospace, monospace; font-size: 11px; color: #64748b; }
    .close { background: none; border: none; color: #64748b; cursor: pointer; font-size: 18px; line-height: 1; padding: 2px 6px; border-radius: 8px; }
    .close:hover { color: #e2e8f0; background: rgba(255,255,255,.06); }
    .tabs { display: flex; gap: 4px; padding: 12px 16px 0; }
    .tab {
      flex: 1; padding: 8px 0; border: none; cursor: pointer; border-radius: 10px;
      background: transparent; color: #94a3b8; font-size: 12.5px; font-weight: 600;
      display: flex; align-items: center; justify-content: center; gap: 6px;
    }
    .tab:hover { color: #e2e8f0; background: rgba(255,255,255,.04); }
    .tab.active { background: rgba(124,58,237,.18); color: #c4b5fd; }
    .tab svg { width: 15px; height: 15px; }
    .body { flex: 1; overflow-y: auto; padding: 14px 16px 16px; }
    .intro { font-size: 12.5px; line-height: 1.55; color: #94a3b8; margin: 0 0 12px; }
    textarea {
      width: 100%; min-height: 96px; resize: vertical; border-radius: 12px; padding: 11px 12px;
      background: #14171f; border: 1px solid rgba(255,255,255,.09); color: #e2e8f0;
      font: inherit; font-size: 13px; line-height: 1.5; outline: none;
    }
    textarea:focus { border-color: rgba(124,58,237,.6); }
    textarea::placeholder { color: #475569; }
    .send {
      margin-top: 10px; width: 100%; padding: 10px; border: none; border-radius: 12px; cursor: pointer;
      background: linear-gradient(135deg, #7c3aed, #6366f1); color: #fff; font-size: 13px; font-weight: 600;
      transition: filter .15s ease, opacity .15s ease;
    }
    .send:hover { filter: brightness(1.1); }
    .send:disabled { opacity: .45; cursor: not-allowed; }
    .commit { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid rgba(255,255,255,.06); }
    .commit:first-child { border-top: none; }
    .commit .info { min-width: 0; flex: 1; }
    .commit .msg { font-size: 12.5px; color: #cbd5e1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .commit .meta { font-family: ui-monospace, monospace; font-size: 11px; color: #64748b; margin-top: 2px; }
    .pill { font-size: 10.5px; font-weight: 600; padding: 3px 8px; border-radius: 999px; background: rgba(52,211,153,.18); color: #6ee7b7; white-space: nowrap; }
    .revert {
      font-size: 11.5px; font-weight: 600; padding: 5px 10px; border-radius: 9px; cursor: pointer; white-space: nowrap;
      background: transparent; border: 1px solid rgba(255,255,255,.14); color: #cbd5e1;
    }
    .revert:hover { background: rgba(255,255,255,.06); border-color: rgba(255,255,255,.25); }
    .empty { font-size: 12.5px; color: #64748b; padding: 8px 0; }
    .busy { position: absolute; inset: 0; background: #0e1017; display: flex; flex-direction: column; padding: 14px 16px 16px; }
    .busy .hd { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
    .spinner { width: 16px; height: 16px; flex: none; border-radius: 999px; border: 2px solid rgba(124,58,237,.28); border-top-color: #a78bfa; animation: spin .8s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .busy .t1 { font-size: 13px; font-weight: 600; }
    .stream {
      flex: 1; min-height: 0; overflow-y: auto; border-radius: 12px; padding: 11px 12px;
      background: #06070b; border: 1px solid rgba(255,255,255,.07);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; line-height: 1.55; color: #cbd5e1;
      white-space: pre-wrap; word-break: break-word;
    }
    .stream .waiting { color: #64748b; }
    .caret { display: inline-block; width: 7px; height: 13px; margin-top: 2px; background: rgba(52,211,153,.7); animation: blink 1s steps(2) infinite; }
    @keyframes blink { 50% { opacity: 0; } }
    .err { margin: 0; font-size: 12.5px; color: #fca5a5; background: rgba(244,63,94,.1); border: 1px solid rgba(244,63,94,.25); border-radius: 10px; padding: 10px 12px; }
  `;

  var host = document.createElement("div");
  document.body.appendChild(host);
  var sr = host.attachShadow({ mode: "open" });
  sr.innerHTML =
    "<style>" + CSS + "</style>" +
    '<div class="root"></div>';
  var root = sr.querySelector(".root");

  var ICON_CHAT =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7a8.5 8.5 0 0 1 3.5-11.3 8.38 8.38 0 0 1 12.6 7.5z"/></svg>';
  var ICON_SPARK =
    '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.6 5.8L19 9l-5.4 1.2L12 16l-1.6-5.8L5 9l5.4-1.2z"/></svg>';
  var ICON_CLOCK =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>';

  var open = false;
  var tab = "improve";
  var busy = false;
  var busyMsg = "";
  var busyGrok = false; // true only when Grok is the thing running
  var errMsg = "";
  var commits = [];
  var served = "";        // hash of the version currently being served
  var draft = "";
  var logLines = [];
  var pollTimer = null;

  function poll() {
    api.log().then(function (r) {
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
    }).catch(function () {});
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
    api.history().then(function (r) {
      commits = r.commits || [];
      served = r.served || "";
      // A build already in progress on open could be an improve (Grok) or
      // a revert (plain git/npm) — stay neutral rather than claim Grok.
      if (r.status === "building") startPolling("Working…", false);
      render();
    }).catch(function () {
      errMsg = "Couldn't load version history (backend error).";
      render();
    });
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

  function render() {
    if (!open) {
      root.innerHTML =
        '<button class="fab" title="Concept tools">' + ICON_CHAT +
        (commits.length === 0 ? "" : "") + "</button>";
      root.querySelector(".fab").onclick = function () {
        open = true;
        render();
        loadHistory();
      };
      return;
    }

    var bodyHtml;
    if (tab === "improve") {
      bodyHtml =
        '<p class="intro">Describe a change and Grok will rebuild this concept in place. The page reloads when it\'s done.</p>' +
        '<textarea id="ta" placeholder="e.g. add a dark-mode toggle, make it mobile-friendly, add two harder levels…"></textarea>' +
        '<button class="send" id="send">Send to Grok</button>' +
        (errMsg ? '<p class="err" style="margin-top:12px">' + escapeHtml(errMsg) + "</p>" : "");
    } else {
      if (commits.length === 0) {
        bodyHtml = '<p class="empty">No version history yet.</p>';
      } else {
        // The served version isn't necessarily the newest commit (a revert
        // restores an older one), so mark the one the backend reports as live.
        var liveHash = served;
        var hasLive = commits.some(function (c) { return c.hash === liveHash; });
        if (!hasLive) liveHash = commits[0].hash; // fallback: assume newest
        bodyHtml = commits.map(function (c) {
          return (
            '<div class="commit">' +
              '<div class="info">' +
                '<div class="msg">' + escapeHtml(c.message) + "</div>" +
                '<div class="meta">' + c.hash.slice(0, 7) + " · " + relTime(c.date) + "</div>" +
              "</div>" +
              (c.hash === liveHash
                ? '<span class="pill">serving now</span>'
                : '<button class="revert" data-hash="' + c.hash + '">Serve this</button>') +
            "</div>"
          );
        }).join("");
      }
    }

    root.innerHTML =
      '<div class="panel">' +
        '<div class="hdr"><span class="title">Concept tools</span>' +
          '<span class="slug">' + escapeHtml(slug) + "</span>" +
          '<button class="close" title="Close">×</button></div>' +
        '<div class="tabs">' +
          '<button class="tab ' + (tab === "improve" ? "active" : "") + '" data-tab="improve">' + ICON_SPARK + "Improve</button>" +
          '<button class="tab ' + (tab === "versions" ? "active" : "") + '" data-tab="versions">' + ICON_CLOCK + "Versions</button>" +
        "</div>" +
        '<div class="body">' + bodyHtml + "</div>" +
        (busy
          ? '<div class="busy"><div class="hd"><span class="spinner"></span><span class="t1">' +
            escapeHtml(busyMsg) + '</span></div><div class="stream" id="stream"></div></div>'
          : "") +
      "</div>";

    root.querySelector(".close").onclick = function () { open = false; render(); };
    var tabs = root.querySelectorAll(".tab");
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].onclick = function () { tab = this.getAttribute("data-tab"); render(); };
    }
    if (tab === "improve" && !busy) {
      var ta = root.querySelector("#ta");
      ta.value = draft;
      ta.oninput = function () { draft = ta.value; updateSend(); };
      ta.onkeydown = function (e) {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendImprove(); }
      };
      root.querySelector("#send").onclick = sendImprove;
      updateSend();
      ta.focus();
    }
    var reverts = root.querySelectorAll(".revert");
    for (var j = 0; j < reverts.length; j++) {
      reverts[j].onclick = function () {
        if (confirm("Serve this earlier version? A new commit records the rollback.")) {
          doRevert(this.getAttribute("data-hash"));
        }
      };
    }
    if (busy) renderStream();
  }

  // Refresh only the streamed log so polling doesn't rebuild the panel (which
  // would reset the scroll position mid-stream).
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

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  render();
})();
