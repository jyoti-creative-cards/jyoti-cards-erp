# Services layout and print-report cards

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put every loose service module in a package, keep one scripts home, and show print-report parties as compact cards with a red bus / transport / self-pickup mark.

**Architecture:** A top-level `app/services/foo.py` becomes the package `app/services/foo/` with the same code in `core.py` and a facade `__init__.py`, so `from app.services.foo import name` does not change. `JC/backend/scripts` is an empty unused directory. `JC/scripts` stays; it is the one-off import toolbox and the app does not import it. The print report All filter keeps every mode, and each card shows that mode in red.

**Tech Stack:** FastAPI, SQLAlchemy, vanilla admin JS stitched from slices, pytest.

## Global Constraints

- JC ERP only: edit `JC/backend` and `JC/web/admin`. Do not edit repo-root `backend/`.
- Do not commit `JC/web/admin/vercel.json`, `fly.toml`, `.env`, xlsx, pdf, or photos.
- Do not change money sign convention, IST date helpers, or soft-delete filters.
- Existing import paths `from app.services.<module> import <name>` must keep working.
- Do not delete `JC/scripts/*.py`. Those are the debtor and stock import tools.
- Print-report mode text is exactly `BUS`, `TRANSPORT`, or `SELF PICKUP`, color `#b91c1c`, font-weight 800.
- A print with blank `carry` is self pickup.
- Admin cache bump: `reports.js?v=ui114` in `JC/web/admin/index.html`.
- Stitch reports with `JC/web/admin/tools/stitch_screen.py` before commit. Do not hand-edit `reports.js` except by stitching the slices.
- Work only in `/Users/sourabh/Desktop/personal/anshul-wt/jc-services-reports` on branch `feat/services-reports`.

---

### Task 1: Print report cards and red mode mark

**Files:**
- Modify: `JC/backend/app/services/sticker_labels.py` (`list_print_report`)
- Modify: `JC/web/admin/js/reports/01-init.js` (`setPrintCarry`, `renderPrintReport`)
- Modify: `JC/web/admin/styles.css` (add print-party card rules)
- Modify: `JC/web/admin/index.html` (`reports.js?v=ui114`)
- Test: `JC/backend/tests/test_sticker_hindi.py`

**Interfaces:**
- Consumes: `StickerPrint.carry` is `bus`, `transport`, or null.
- Produces: `list_print_report(..., carry="self_pickup")` returns rows whose `carry` is null or `""`. `carry="bus"` and `carry="transport"` stay exact matches. UI `Reports.setPrintCarry("self_pickup")` sends that query value.

- [ ] **Step 1: Write the failing test**

Add this test to `JC/backend/tests/test_sticker_hindi.py`. Use the existing `db` fixture, `Customer`, `City`, and `StickerPrint`.

```python
def test_print_report_filters_self_pickup(db):
    from datetime import datetime, timezone
    from app.models.sticker_print import StickerPrint
    from app.services.sticker_labels import list_print_report

    city = City(name="Indore")
    db.add(city)
    db.flush()
    bus = Customer(business_name="Bus Party", phone="9800000001", password_hash="x", city_id=city.id, party_number=1)
    walk = Customer(business_name="Walk Party", phone="9800000002", password_hash="x", city_id=city.id, party_number=2)
    db.add_all([bus, walk])
    db.flush()
    now = datetime(2026, 10, 28, 6, 0, tzinfo=timezone.utc)
    db.add(StickerPrint(
        customer_id=bus.id, party_number=1, business_name="Bus Party",
        name_hi="बस", city_name="Indore", city_hi="इंदौर", phone="9800000001",
        printed_by="Pandit", printed_at=now, carry="bus",
    ))
    db.add(StickerPrint(
        customer_id=walk.id, party_number=2, business_name="Walk Party",
        name_hi="वॉक", city_name="Indore", city_hi="इंदौर", phone="9800000002",
        printed_by="Pandit", printed_at=now, carry=None,
    ))
    db.commit()
    pickup = list_print_report(db, carry="self_pickup")
    assert [row.business_name for row in pickup] == ["Walk Party"]
    buses = list_print_report(db, carry="bus")
    assert [row.business_name for row in buses] == ["Bus Party"]
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd JC/backend && python3 -m pytest tests/test_sticker_hindi.py::test_print_report_filters_self_pickup -q`
Expected: FAIL because `self_pickup` is ignored and both rows return, or the assertion on names fails.

- [ ] **Step 3: Filter self pickup in `list_print_report`**

In `list_print_report`, replace the carry filter with:

```python
    mode = (carry or "").strip().lower()
    if mode == "self_pickup":
        query = query.filter(or_(StickerPrint.carry.is_(None), StickerPrint.carry == ""))
    elif mode in ("bus", "transport"):
        query = query.filter(StickerPrint.carry == mode)
```

`or_` is already imported in that file.

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd JC/backend && python3 -m pytest tests/test_sticker_hindi.py -q`
Expected: all tests in that file PASS.

- [ ] **Step 5: Replace the full-width print row with cards**

In `JC/web/admin/js/reports/01-init.js`, replace `setPrintCarry` with:

```javascript
  function setPrintCarry(mode) {
    printCarry = mode === "bus" || mode === "transport" || mode === "self_pickup" ? mode : "";
    loadChip();
  }
```

Replace the body of `renderPrintReport` after the `groups` map is filled. Keep the fetch. Render a grid of cards, not a `btn` stretched across the screen. Mode text is red.

```javascript
    const modeLabel = (row) => {
      const carry = String(row.carry || "").toLowerCase();
      if (carry === "bus") return "BUS";
      if (carry === "transport") return "TRANSPORT";
      return "SELF PICKUP";
    };
    const chipBtn = (id, label) => `<button type="button" class="btn btn-sm ${printCarry === id ? "btn-primary" : "btn-secondary"}" onclick="Reports.setPrintCarry('${id}')">${label}</button>`;
    const cards = [...groups.values()].map((g) => {
      const key = String(g.rows[0].customer_id || g.name);
      const open = !!printOpen[key];
      const modes = [...new Set(g.rows.map(modeLabel))];
      const lines = g.rows.map((r) => `<div class="print-party-line">
          <strong>${ctx.esc(r.printed_label || "—")}</strong>
          <span class="print-mode-flag">${ctx.esc(modeLabel(r))}</span>
          <span class="print-party-by">${ctx.esc(r.printed_by || "")}</span>
        </div>`).join("");
      return `<article class="print-party-card">
        <button type="button" class="print-party-hit" onclick="Reports.togglePrintGroup('${ctx.esc(key)}')">
          <strong class="print-party-name">${ctx.esc(g.name)}</strong>
          <span class="print-mode-flag">${modes.map(m => ctx.esc(m)).join(" · ")}</span>
          <span class="print-party-meta">${g.city ? ctx.esc(g.city) : ""}${g.number != null ? ` #${ctx.esc(g.number)}` : ""}</span>
          <span class="print-party-count">${g.rows.length} print${g.rows.length === 1 ? "" : "s"}</span>
        </button>
        ${open ? `<div class="print-party-lines">${lines}</div>` : ""}
      </article>`;
    }).join("");
    body.innerHTML = `
      <p class="fin-panel-sub" style="margin:0 0 12px;">Stickers Pandit Ji printed. A party with 3 bundles shows 3 prints. Open the party to see each time.</p>
      <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
        ${chipBtn("", "All")}
        ${chipBtn("bus", "Bus")}
        ${chipBtn("transport", "Transport")}
        ${chipBtn("self_pickup", "Self pickup")}
      </div>
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">Prints</span><strong>${items.length}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Parties</span><strong>${groups.size}</strong></div>
      </div>
      <div class="print-party-grid">${cards}</div>
      ${cards ? "" : empty("No prints", "No sticker was printed in these dates.")}`;
```

Add this CSS at the end of `JC/web/admin/styles.css`:

```css
.print-party-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  width: 100%;
}
.print-party-card {
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface);
  box-shadow: var(--shadow);
  overflow: hidden;
  min-width: 0;
}
.print-party-hit {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  width: 100%;
  margin: 0;
  padding: 14px;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.print-party-name { font-size: 16px; line-height: 1.3; }
.print-mode-flag { color: #b91c1c; font-weight: 800; font-size: 13px; letter-spacing: .04em; }
.print-party-meta, .print-party-count, .print-party-by { color: var(--muted); font-size: 13px; }
.print-party-lines { border-top: 1px solid var(--border); padding: 0 14px 10px; }
.print-party-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
  padding: 8px 0;
  border-top: 1px solid var(--line, var(--border));
}
```

Bump `JC/web/admin/index.html` from `reports.js?v=ui113` to `reports.js?v=ui114`.

Stitch from `JC/web/admin`:

```bash
export PATH="/Users/sourabh/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH"
python3 - << 'PY'
import subprocess, sys
from pathlib import Path
sys.path.insert(0, "tools")
import stitch_screen
def js_syntax_error(source: bytes):
    proc = subprocess.run(["node", "--check", "-"], input=source, capture_output=True)
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or b"syntax").decode()
    return None
stitch_screen.js_syntax_error = js_syntax_error
result = stitch_screen.plan(Path("js/reports").resolve())
if isinstance(result, str):
    raise SystemExit(result)
stitched, joined, dest = result
dest.write_bytes(stitched)
(Path("js/reports") / "accepted.js").write_bytes(joined)
print("wrote", dest)
PY
```

- [ ] **Step 6: Commit**

```bash
git add JC/backend/app/services/sticker_labels.py JC/backend/tests/test_sticker_hindi.py \
  JC/web/admin/js/reports/01-init.js JC/web/admin/js/reports.js JC/web/admin/js/reports/accepted.js \
  JC/web/admin/styles.css JC/web/admin/index.html
git commit -m "$(cat <<'EOF'
Show bus, transport, and self pickup in red on print-report cards.

The All filter still lists every party, and each card is a compact tile instead of one full-width row.
EOF
)"
```

---

### Task 2: One scripts home

**Files:**
- Delete: `JC/backend/scripts` if that empty directory exists.
- Do not delete: `JC/scripts/*.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `JC/scripts` remains the only scripts directory. The running app does not import it.

- [ ] **Step 1: Confirm the app never imports JC/scripts**

Run from the repo root:

```bash
rg -n "JC/scripts|backend/scripts" JC/backend/app JC/web/admin --glob '!**/data/**' || true
```

Expected: no imports of those folders from application code. `JC/backend/scripts` is an empty directory created 4 Oct and is not referenced.

- [ ] **Step 2: Remove only the empty directory**

```bash
rmdir JC/backend/scripts
```

If `rmdir` says the directory is not empty, stop and report BLOCKED. Do not delete files inside `JC/scripts`.

- [ ] **Step 3: Commit only if git tracked the empty directory**

`git status --short -- JC/backend/scripts`. If there is no change, do not make an empty commit. Report DONE with note "empty directory was untracked; JC/scripts kept".

---

### Task 3: Package every loose service module

**Files:**
- Modify: every `JC/backend/app/services/*.py` except `JC/backend/app/services/__init__.py` if present.
- Create: `JC/backend/app/services/<module>/core.py` and `JC/backend/app/services/<module>/__init__.py` for each of those modules.
- Do not move code that already lives in a package directory (`customer_bills`, `customer_selling`, `ap_ledger_parts`, `ar_ledger_parts`, `bill_pdf_parts`, `ledger_parts`, `pdf_parts`, `report_parts`, `reports_extra`, `void_parts`).

**Interfaces:**
- Consumes: public names currently defined on each loose module.
- Produces: the same names importable from `app.services.<module>`. `import app.main` must succeed.

- [ ] **Step 1: Add a facade import test**

Create `JC/backend/tests/test_service_packages.py`:

```python
from pathlib import Path

import app.main  # noqa: F401


def test_loose_service_modules_are_packages():
    root = Path(__file__).resolve().parents[1] / "app" / "services"
    loose = [p.name for p in root.glob("*.py") if p.name != "__init__.py"]
    assert loose == []


def test_service_facades_import():
    import importlib
    root = Path(__file__).resolve().parents[1] / "app" / "services"
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("__")):
        importlib.import_module(f"app.services.{folder.name}")
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd JC/backend && python3 -m pytest tests/test_service_packages.py::test_loose_service_modules_are_packages -q`
Expected: FAIL listing loose `.py` files.

- [ ] **Step 3: Convert each loose module into a package**

Run this from `JC/backend`. It moves each loose module to `<name>/core.py` and writes a facade that re-exports public names. Do not edit `core.py` bodies.

```python
import ast
from pathlib import Path

root = Path("app/services")
for path in sorted(root.glob("*.py")):
    if path.name == "__init__.py":
        continue
    name = path.stem
    dest = root / name
    if dest.exists():
        raise SystemExit(f"refuse to overwrite {dest}")
    tree = ast.parse(path.read_text())
    public = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                public.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    public.append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if not node.target.id.startswith("_"):
                public.append(node.target.id)
    dest.mkdir()
    core = dest / "core.py"
    path.rename(core)
    lines = [f'"""{name} package. Import from app.services.{name}."""', ""]
    if public:
        joined = ",\n    ".join(public)
        lines.append(f"from app.services.{name}.core import (")
        lines.append(f"    {joined},")
        lines.append(")")
        lines.append("")
        lines.append("__all__ = [")
        for item in public:
            lines.append(f'    "{item}",')
        lines.append("]")
    else:
        lines.append(f"from app.services.{name} import core as _core")
        lines.append("__all__ = []")
    lines.append("")
    (dest / "__init__.py").write_text("\n".join(lines))
print("converted")
```

If `python3 -c "import app.main"` raises ImportError because a package `__init__` is half-loaded, do not invent a new layout. Move that one module's code back to a single file and report DONE_WITH_CONCERNS naming the module. Do not leave the app unable to import.

- [ ] **Step 4: Verify**

```bash
cd JC/backend && python3 -c "import app.main" && python3 -m pytest tests/test_service_packages.py tests/test_sticker_hindi.py tests/test_shop_product_search.py -q
```

Expected: `import app.main` prints nothing and exits 0. Pytest passes.

- [ ] **Step 5: Commit**

```bash
git add JC/backend/app/services JC/backend/tests/test_service_packages.py
git commit -m "$(cat <<'EOF'
Move loose service modules into packages without changing their import paths.

Each former module is now a folder with the same public names.
EOF
)"
```
