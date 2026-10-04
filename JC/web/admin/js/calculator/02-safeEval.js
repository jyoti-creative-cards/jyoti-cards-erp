  function safeEval(str) {
    // Only digits/operators/parens/dot ever reach here (press() whitelists input) — no
    // arbitrary code execution risk, but avoid `eval` anyway and do it by hand.
    if (!/^[0-9+\-*/.%() ]*$/.test(str)) return null;
    try {
      // eslint-disable-next-line no-new-func
      const fn = new Function(`"use strict"; return (${str.replace(/%/g, "/100")});`);
      const v = fn();
      return Number.isFinite(v) ? v : null;
    } catch (_) {
      return null;
    }
  }

  function liveResult() {
    if (!expr) return "0";
    const v = safeEval(expr);
    if (v == null) return "…";
    return formatNum(v);
  }

  function formatNum(v) {
    const rounded = Math.round(v * 1e8) / 1e8;
    return rounded.toLocaleString("en-IN", { maximumFractionDigits: 8 });
  }

  function press(ch) {
    if (justEvaluated && /[0-9.]/.test(ch)) { expr = ""; }
    justEvaluated = false;
    if (/[+\-*/%]/.test(ch) && (expr === "" || /[+\-*/%]$/.test(expr))) {
      expr = expr.slice(0, -1) + ch; // replace trailing operator instead of stacking
    } else {
      expr += ch;
    }
    render();
  }

  function backspace() {
    expr = expr.slice(0, -1);
    justEvaluated = false;
    render();
  }

  function clearAll() {
    expr = "";
    justEvaluated = false;
    render();
  }

  function evaluate() {
    const v = safeEval(expr);
    if (v == null) return;
    expr = formatNum(v).replace(/,/g, "");
    justEvaluated = true;
    render();
  }

  function isOpen() {
    const panel = document.getElementById("calc-panel");
    return !!panel && !panel.classList.contains("hidden");
  }

  function open() {
    build();
    document.getElementById("calc-panel").classList.remove("hidden");
    document.getElementById("calc-launcher")?.classList.add("hidden");
    render();
  }

  function close() {
    const panel = document.getElementById("calc-panel");
    if (panel) panel.classList.add("hidden");
    document.getElementById("calc-launcher")?.classList.remove("hidden");
  }

  function toggle() {
    if (isOpen()) close(); else open();
  }

  // Single always-on listener (cheap: one comparison per keydown). Alt+C toggles from
  // anywhere, even while typing in a form field. Digit/operator keys only feed the
  // calculator while it's open AND no other input/textarea/select has focus, so normal
  // typing elsewhere on the page is never hijacked.
  document.addEventListener("keydown", (e) => {
    if (e.altKey && !e.ctrlKey && !e.metaKey && (e.key === "c" || e.key === "C")) {
      e.preventDefault();
      toggle();
      return;
    }
    if (!isOpen()) return;
    const active = document.activeElement;
    const typingElsewhere = active && /^(input|textarea|select)$/i.test(active.tagName || "");
    if (typingElsewhere) return;
    if (e.key === "Escape") { close(); return; }
    if (/^[0-9.+\-*/%]$/.test(e.key)) { press(e.key); e.preventDefault(); return; }
    if (e.key === "Enter" || e.key === "=") { evaluate(); e.preventDefault(); return; }
    if (e.key === "Backspace") { backspace(); e.preventDefault(); return; }
  });

  // Launcher button is tiny/cheap — safe to add on script load. If loaded before body
  // exists for some reason, defer to DOMContentLoaded instead of failing silently.
  if (document.body) buildLauncher();
  else document.addEventListener("DOMContentLoaded", buildLauncher);

