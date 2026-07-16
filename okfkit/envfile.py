"""Minimal .env loader. KEY=value lines only; stdlib, silent, no interpolation."""

from __future__ import annotations

import getpass
import os
import sys

# Provenance, consumed by `okf doctor`:
applied: dict[str, str] = {}  # key -> file it was actually loaded into os.environ from
found: dict[str, str] = {}    # key -> first file it appeared in (even if env already had it)

_MARKERS = (".git", "okf.config.yaml")


def parse(path: str) -> dict[str, str]:
    """Parse one .env file. Unreadable/missing file -> {}."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def candidates(start_dir: str, max_up: int = 8) -> list[str]:
    """Candidate .env paths walking from start_dir upward, nearest first.

    Stops after a directory holding a project-root marker (.git / okf.config.yaml),
    at the home directory, at the filesystem root, or after max_up levels.
    Paths are returned whether or not the files exist.
    """
    paths: list[str] = []
    d = os.path.abspath(start_dir)
    home = os.path.abspath(os.path.expanduser("~"))
    for _ in range(max_up):
        paths.append(os.path.join(d, ".env"))
        if any(os.path.exists(os.path.join(d, m)) for m in _MARKERS):
            break
        parent = os.path.dirname(d)
        if d == home or parent == d:
            break
        d = parent
    return paths


def load(paths: list[str]) -> None:
    """Load each existing .env in order; the real environment always wins. Silent."""
    for path in paths:
        if not os.path.isfile(path):
            continue
        for k, v in parse(path).items():
            found.setdefault(k, path)
            if k not in os.environ:
                os.environ[k] = v
                applied[k] = path


def load_default(config_path: str | None = None) -> None:
    """One-call entry: real environment > nearest cwd .env > config-dir .env."""
    load(candidates(os.getcwd()))
    if config_path:
        load(candidates(os.path.dirname(os.path.abspath(config_path))))


def default_env_path() -> str:
    """Where a key-save offer should append: the first .env seen, else cwd/.env."""
    for path in found.values():
        return path
    return os.path.join(os.getcwd(), ".env")


def prompt_for_key(var: str, hint: str = "") -> str | None:
    """TTY-gated rescue for a missing key. Never touches stdout; never echoes the value."""
    if os.environ.get("OKF_NONINTERACTIVE") or not (sys.stdin.isatty() and sys.stderr.isatty()):
        return None
    value = getpass.getpass(f"{var}{(' (' + hint + ')') if hint else ''}: ").strip()
    if not value:
        return None
    os.environ[var] = value
    path = default_env_path()
    sys.stderr.write(f"Save to {path}? [y/N] ")
    sys.stderr.flush()
    if sys.stdin.readline().strip().lower() in ("y", "yes"):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{var}={value}\n")
    return value
