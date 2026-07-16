import os
import re

import pytest

from okfkit import cli

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Fix 1: the MCP register hint must point at this interpreter, not bare `okf`
# (MCP clients spawn servers with no shell/venv/PATH).
# ---------------------------------------------------------------------------

def test_register_hint_executable_resolves():
    hint = cli._register_hint("-c", "/abs/path/okf.config.yaml")
    tokens = hint.split()
    i = tokens.index("--")
    exe = tokens[i + 1].strip("'\"")   # shlex.quote only quotes when needed
    assert os.path.isabs(exe)
    assert os.access(exe, os.X_OK)
    assert tokens[i + 2:i + 4] == ["-m", "okfkit.cli"]
    assert tokens[i + 4] == "serve"
    assert hint.endswith("-c /abs/path/okf.config.yaml")


# ---------------------------------------------------------------------------
# Fix 2: `okf init`'s template must mention every top-level key of
# okf.config.example.yaml (commented-out is fine — visibility is the point).
# ---------------------------------------------------------------------------

def test_init_template_covers_example_top_level_keys():
    with open(os.path.join(REPO, "okf.config.example.yaml"), encoding="utf-8") as fh:
        example = fh.read()
    # top-level keys, including commented-out ones ("# key:") on column-0 lines;
    # indented prose comments ("#   Custom: ...") don't match
    keys = set(re.findall(r"^(?:# )?(\w+):", example, flags=re.M))
    assert keys >= {"adapter", "output", "serve", "clean"}   # sanity: parsing worked
    for key in keys:
        assert re.search(rf"^(?:#\s*)?{key}:", cli._CONFIG_TEMPLATE, flags=re.M), (
            f"top-level key {key!r} from okf.config.example.yaml is missing "
            f"from cli._CONFIG_TEMPLATE"
        )


# ---------------------------------------------------------------------------
# Fix 4: guard rails against a clean build wiping the config dir / source,
# and the `clean:` key reaching engine.build.
# ---------------------------------------------------------------------------

def _write_config(tmp_path, text):
    p = tmp_path / "okf.config.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_build_refuses_output_equal_to_config_dir(tmp_path):
    cfgp = _write_config(tmp_path, "adapter: markdown_folder\n"
                                   "adapter_options:\n  path: ./notes\n"
                                   "output: .\n")
    with pytest.raises(SystemExit) as ei:
        cli.main(["build", "-c", cfgp])
    assert "wipe" in str(ei.value)
    assert os.listdir(tmp_path) == ["okf.config.yaml"]   # nothing was touched


def test_build_refuses_output_equal_to_adapter_path(tmp_path):
    cfgp = _write_config(tmp_path, "adapter: markdown_folder\n"
                                   "adapter_options:\n  path: ./notes\n"
                                   "output: ./notes\n")
    with pytest.raises(SystemExit) as ei:
        cli.main(["build", "-c", cfgp])
    assert "wipe" in str(ei.value)


def test_build_refuses_output_ancestor_of_adapter_path(tmp_path):
    cfgp = _write_config(tmp_path, "adapter: markdown_folder\n"
                                   "adapter_options:\n  path: ./out/notes\n"
                                   "output: ./out\n")
    with pytest.raises(SystemExit) as ei:
        cli.main(["build", "-c", cfgp])
    assert "wipe" in str(ei.value)


def test_clean_false_reaches_engine_build(tmp_path, monkeypatch):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("Hello.\n", encoding="utf-8")
    cfgp = _write_config(tmp_path, "adapter: markdown_folder\n"
                                   "adapter_options:\n  path: ./notes\n"
                                   "output: ./vault\n"
                                   "clean: false\n")
    captured = {}

    def fake_build(nodes, output, **kwargs):
        captured.update(kwargs)

        class Result:
            ok = True

            def summary(self):
                return "(stub)"

        return Result()

    from okfkit import engine
    monkeypatch.setattr(engine, "build", fake_build)
    assert cli.main(["build", "-c", cfgp]) == 0
    assert captured["clean"] is False


# ---------------------------------------------------------------------------
# Provider-conditional chunk default: 1000 for the static local model,
# 4000 for contextual hosted models; an explicit config value always wins.
# ---------------------------------------------------------------------------

def test_chunk_max_chars_default_is_provider_conditional():
    assert cli._chunk_max_chars({}, "local") == 1000
    assert cli._chunk_max_chars({}, "voyage") == 4000
    assert cli._chunk_max_chars({}, "openai") == 4000
    assert cli._chunk_max_chars({"chunk_max_chars": 2500}, "local") == 2500
