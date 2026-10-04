#!/usr/bin/env python3
"""Join ordered admin JS slices into the one file the page loads.

The slice files are the source. index.html keeps a single script tag.
The stitch inserts only `// @slice <id>` lines. Stripping those lines
must match the saved copy, or the script is not written.
"""

from __future__ import annotations

import argparse
import difflib
import subprocess
import sys
import tempfile
from pathlib import Path


def _die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def load_manifest(screen: Path) -> list[str]:
    path = screen / "manifest.txt"
    if not path.is_file():
        _die(f"missing {path}")
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.endswith(".js") or "/" in line or "\\" in line or line != Path(line).name:
            _die(f"manifest entry must be a bare .js filename: {line}")
        names.append(line)
    if not names:
        _die("manifest is empty")
    if len(names) != len(set(names)):
        _die("manifest has a duplicate name")
    return names


def slice_id(name: str) -> str:
    return name[:-3]


def comment_for(name: str) -> bytes:
    return f"// @slice {slice_id(name)}\n".encode("ascii")


def read_slices(screen: Path, names: list[str]) -> list[bytes]:
    comments = {comment_for(name).rstrip(b"\n") for name in names}
    parts: list[bytes] = []
    for name in names:
        path = screen / name
        if not path.is_file():
            _die(f"missing slice {path}")
        data = path.read_bytes()
        for line in data.splitlines(keepends=True):
            body = line[:-2] if line.endswith(b"\r\n") else line[:-1] if line.endswith((b"\n", b"\r")) else line
            if body in comments:
                _die(f"{name} contains a stitch comment; keep those only in the generated file")
        parts.append(data)
    return parts


def strip_comments(data: bytes, names: list[str]) -> bytes:
    comments = {comment_for(name).rstrip(b"\n") for name in names}
    kept: list[bytes] = []
    for line in data.splitlines(keepends=True):
        body = line[:-2] if line.endswith(b"\r\n") else line[:-1] if line.endswith((b"\n", b"\r")) else line
        if body in comments:
            continue
        kept.append(line)
    return b"".join(kept)


def output_path(screen: Path) -> Path:
    pointer = screen / "output.txt"
    if not pointer.is_file():
        _die(f"missing {pointer}")
    rel = pointer.read_text(encoding="utf-8").strip()
    if not rel or any(ch in rel for ch in "\n\r"):
        _die("output.txt must be one relative path")
    dest = (screen / rel).resolve()
    admin = screen.parents[1]
    try:
        dest.relative_to(admin)
    except ValueError:
        _die(f"output escapes the admin directory: {dest}")
    try:
        dest.relative_to(screen.resolve())
    except ValueError:
        return dest
    _die(f"output must sit outside the slice folder: {dest}")
    return dest


def unified(left: bytes, right: bytes, left_name: str, right_name: str) -> str:
    return "".join(
        difflib.unified_diff(
            left.decode("utf-8", errors="replace").splitlines(keepends=True),
            right.decode("utf-8", errors="replace").splitlines(keepends=True),
            fromfile=left_name,
            tofile=right_name,
        )
    )


def js_syntax_error(source: bytes) -> str | None:
    """None when `new Function` accepts the source."""
    handle = tempfile.NamedTemporaryFile(suffix=".js", delete=False)
    try:
        handle.write(source)
        handle.close()
        path = handle.name
        script = r"""
function run(argv) {
  var app = Application.currentApplication();
  app.includeStandardAdditions = true;
  var src = app.read(Path(argv[0]));
  try {
    new Function(src);
  } catch (e) {
    return "SYNTAX " + e.toString();
  }
  return "ok";
}
"""
        try:
            proc = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", script, path],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return "syntax check timed out"
    finally:
        Path(path).unlink(missing_ok=True)
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return err or out or f"osascript exited {proc.returncode}"
    if out != "ok":
        return out or err or "syntax check failed"
    return None


def plan(screen: Path) -> tuple[bytes, bytes, Path] | str:
    """Return (stitched, joined, dest) or an error/diff string."""
    names = load_manifest(screen)
    parts = read_slices(screen, names)
    joined = b"".join(parts)
    stitched = b"".join(comment_for(name) + part for name, part in zip(names, parts))
    if strip_comments(stitched, names) != joined:
        return "strip of the stitch did not reproduce the slices"
    baseline_path = screen / "baseline.js"
    if not baseline_path.is_file():
        return f"missing {baseline_path}"
    baseline = baseline_path.read_bytes()
    accepted_path = screen / "accepted.js"
    dest = output_path(screen)
    if not accepted_path.is_file():
        if joined != baseline:
            return "first stitch does not match baseline.js\n" + unified(
                baseline, joined, "baseline.js", "slices"
            )
        if dest.is_file() and dest.read_bytes() != baseline:
            return "output was edited before the first stitch\n" + unified(
                baseline, dest.read_bytes(), "baseline.js", str(dest)
            )
    else:
        if not dest.is_file():
            return f"missing {dest}"
        live = strip_comments(dest.read_bytes(), names)
        accepted = accepted_path.read_bytes()
        if live != accepted:
            return "generated file was edited by hand\n" + unified(
                accepted, live, "accepted.js", str(dest)
            )
    syntax = js_syntax_error(stitched)
    if syntax:
        return syntax
    return stitched, joined, dest


def main() -> None:
    parser = argparse.ArgumentParser(description="Stitch admin JS slices into one script.")
    parser.add_argument("screen", type=Path, help="Slice folder, e.g. js/customer-orders")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Compare and do not write")
    mode.add_argument("--write", action="store_true", help="Write only when the compare matches")
    args = parser.parse_args()
    screen = args.screen.resolve()
    if not screen.is_dir():
        _die(f"not a directory: {screen}")
    result = plan(screen)
    if isinstance(result, str):
        print(result, file=sys.stderr)
        raise SystemExit(1)
    stitched, joined, dest = result
    if args.check:
        print(f"match {dest}")
        return
    tmp = dest.with_name(dest.name + ".stitching")
    tmp.write_bytes(stitched)
    tmp.replace(dest)
    (screen / "accepted.js").write_bytes(joined)
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
