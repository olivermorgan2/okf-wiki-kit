import os

from okfkit import config


def _write(tmp_path, text, name="okf.config.yaml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_relative_py_adapter_resolves_against_config_dir(tmp_path, monkeypatch):
    (tmp_path / "adapter.py").write_text("# dummy adapter file\n", encoding="utf-8")
    cfgp = _write(tmp_path, "adapter: adapter.py:MyAdapter\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)   # a different CWD must not change the result
    cfg = config.load(cfgp)
    target, _, cls = cfg.adapter.rpartition(":")
    assert cls == "MyAdapter"
    assert os.path.isabs(target)
    assert target == str(tmp_path / "adapter.py")
    assert os.path.exists(target)


def test_relative_py_adapter_without_class_suffix(tmp_path, monkeypatch):
    cfgp = _write(tmp_path, "adapter: ./sub/adapter.py\n")
    monkeypatch.chdir(tmp_path.parent)
    cfg = config.load(cfgp)
    assert cfg.adapter == str(tmp_path / "sub" / "adapter.py")


def test_module_adapter_specs_pass_through(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = config.load(_write(tmp_path, "adapter: markdown_folder\n"))
    assert cfg.adapter == "markdown_folder"
    cfg = config.load(_write(tmp_path, "adapter: my.pkg.adapters:Cls\n", name="b.yaml"))
    assert cfg.adapter == "my.pkg.adapters:Cls"


def test_clean_defaults_true_and_parses_false(tmp_path):
    cfg = config.load(_write(tmp_path, "output: ./vault\n"))
    assert cfg.clean is True
    cfg = config.load(_write(tmp_path, "clean: false\n", name="b.yaml"))
    assert cfg.clean is False
