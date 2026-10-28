"""open_lines package. Import from app.services.open_lines."""

_core_path = __import__("pathlib").Path(__file__).with_name("core.py")
exec(compile(_core_path.read_text(encoding="utf-8"), str(_core_path), "exec"), globals())
del _core_path
if "__all__" not in globals():
    __all__ = [name for name in globals() if not name.startswith("_")]
