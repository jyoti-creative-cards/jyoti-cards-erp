  function buildLauncher() {
    if (launcherBuilt || document.getElementById("calc-launcher")) return;
    injectStyle();
    const btn = document.createElement("button");
    btn.id = "calc-launcher";
    btn.type = "button";
    btn.title = "Calculator (Alt+C)";
    btn.textContent = "🧮";
    btn.onclick = toggle;
    document.body.appendChild(btn);
    launcherBuilt = true;
  }

  function injectStyle() {
    if (document.getElementById("calc-style")) return;
    const style = document.createElement("style");
    style.id = "calc-style";
    style.textContent = `
      #calc-panel { position: fixed; top: 50%; right: 20px; transform: translateY(-50%);
        width: 260px; z-index: 9999;
        background: var(--card-bg, #fff); border: 1px solid var(--border, #e2e2e2);
        border-radius: 12px; box-shadow: 0 8px 28px rgba(0,0,0,0.18); font-family: inherit;
        overflow: hidden; }
      #calc-panel.hidden { display: none; }
      #calc-head { display: flex; align-items: center; justify-content: space-between;
        padding: 8px 10px; background: var(--brand, #1f2937); color: #fff; cursor: move;
        font-size: 13px; font-weight: 600; }
      #calc-head button { background: none; border: none; color: #fff; font-size: 16px;
        cursor: pointer; line-height: 1; padding: 0 4px; }
      #calc-display { padding: 12px 10px 4px; text-align: right; }
      #calc-expr { font-size: 12px; color: var(--muted, #888); min-height: 14px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      #calc-result { font-size: 26px; font-weight: 600; margin-top: 2px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      #calc-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px;
        padding: 10px; }
      #calc-grid button { padding: 10px 0; font-size: 15px; border: 1px solid var(--border, #e2e2e2);
        border-radius: 8px; background: #f7f7f8; cursor: pointer; }
      #calc-grid button:hover { background: #ececee; }
      #calc-grid button.calc-op { background: #eef2ff; }
      #calc-grid button.calc-eq { background: var(--brand, #1f2937); color: #fff; grid-row: span 1; }
      #calc-grid button.calc-clear { color: #b91c1c; }
      #calc-hint { padding: 0 10px 10px; font-size: 11px; color: var(--muted, #888); text-align: center; }
      #calc-launcher { position: fixed; top: 50%; right: 20px; transform: translateY(-50%);
        z-index: 9998;
        width: 38px; height: 38px; border-radius: 50%; border: 1px solid var(--border, #e2e2e2);
        background: var(--card-bg, #fff); box-shadow: 0 2px 10px rgba(0,0,0,0.15);
        font-size: 17px; cursor: pointer; display: flex; align-items: center; justify-content: center; }
      #calc-launcher:hover { background: #f2f2f4; }
      #calc-launcher.hidden { display: none; }
    `;
    document.head.appendChild(style);
  }

  function build() {
    if (built) return;
    injectStyle();
    const panel = document.createElement("div");
    panel.id = "calc-panel";
    panel.className = "hidden";
    panel.innerHTML = `
      <div id="calc-head">
        <span>Calculator</span>
        <button type="button" onclick="Calculator.close()" aria-label="Close">×</button>
      </div>
      <div id="calc-display">
        <div id="calc-expr"></div>
        <div id="calc-result">0</div>
      </div>
      <div id="calc-grid">
        <button type="button" class="calc-clear" onclick="Calculator.clearAll()">C</button>
        <button type="button" onclick="Calculator.backspace()">⌫</button>
        <button type="button" class="calc-op" onclick="Calculator.press('%')">%</button>
        <button type="button" class="calc-op" onclick="Calculator.press('/')">÷</button>
        <button type="button" onclick="Calculator.press('7')">7</button>
        <button type="button" onclick="Calculator.press('8')">8</button>
        <button type="button" onclick="Calculator.press('9')">9</button>
        <button type="button" class="calc-op" onclick="Calculator.press('*')">×</button>
        <button type="button" onclick="Calculator.press('4')">4</button>
        <button type="button" onclick="Calculator.press('5')">5</button>
        <button type="button" onclick="Calculator.press('6')">6</button>
        <button type="button" class="calc-op" onclick="Calculator.press('-')">−</button>
        <button type="button" onclick="Calculator.press('1')">1</button>
        <button type="button" onclick="Calculator.press('2')">2</button>
        <button type="button" onclick="Calculator.press('3')">3</button>
        <button type="button" class="calc-op" onclick="Calculator.press('+')">+</button>
        <button type="button" onclick="Calculator.press('0')" style="grid-column: span 2;">0</button>
        <button type="button" onclick="Calculator.press('.')">.</button>
        <button type="button" class="calc-eq" onclick="Calculator.evaluate()">=</button>
      </div>
      <div id="calc-hint">Alt+C to toggle · Esc to close</div>
    `;
    document.body.appendChild(panel);
    makeDraggable(panel, panel.querySelector("#calc-head"));
    built = true;
  }

  function makeDraggable(panel, handle) {
    let dragging = false, offX = 0, offY = 0;
    handle.addEventListener("mousedown", (e) => {
      dragging = true;
      const rect = panel.getBoundingClientRect();
      offX = e.clientX - rect.left;
      offY = e.clientY - rect.top;
      panel.style.transform = "none"; // stop fighting the CSS translateY(-50%) centering
      panel.style.top = `${rect.top}px`;
      panel.style.left = `${rect.left}px`;
      panel.style.right = "auto";
      panel.style.bottom = "auto";
      e.preventDefault();
    });
    document.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      panel.style.left = `${e.clientX - offX}px`;
      panel.style.top = `${e.clientY - offY}px`;
    });
    document.addEventListener("mouseup", () => { dragging = false; });
  }

  function render() {
    const exprEl = document.getElementById("calc-expr");
    const resultEl = document.getElementById("calc-result");
    if (exprEl) exprEl.textContent = displayExpr();
    if (resultEl) resultEl.textContent = liveResult();
  }

  function displayExpr() {
    return expr.replace(/\*/g, "×").replace(/\//g, "÷");
  }

