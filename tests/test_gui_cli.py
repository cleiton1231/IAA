import httpx

from bancada.cli import main
from bancada.client import Client
from tests.gui_helpers import make_db, make_run


def _client() -> Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "synthetic-model"}]})

    return Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))


def test_gui_command_is_loopback_only(tmp_path, monkeypatch):
    from bancada.gui import app as gui_app

    db = make_db(tmp_path, [make_run()])
    calls = []
    monkeypatch.setattr(gui_app, "serve", lambda path, port: calls.append((path, port)))

    result = main(["gui", "--db", str(db)])

    assert result == 0
    assert calls == [(db.resolve(), 8765)]


def test_serve_binds_only_to_ipv4_loopback(tmp_path, monkeypatch):
    from bancada.gui import app as gui_app

    db = make_db(tmp_path, [make_run()])
    calls = []

    def record_run(_app, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(gui_app.Flask, "run", record_run)
    gui_app.serve(db)

    assert calls == [
        {"host": "127.0.0.1", "port": 8765, "debug": False, "use_reloader": False}
    ]


def test_gui_command_rejects_invalid_port(tmp_path, monkeypatch, capsys):
    from bancada.gui import app as gui_app

    db = make_db(tmp_path, [make_run()])
    calls = []
    monkeypatch.setattr(gui_app, "serve", lambda *args: calls.append(args))

    result = main(["gui", "--db", str(db), "--port", "70000"])

    assert result == 1
    assert calls == []
    assert "porta" in capsys.readouterr().err.lower()


def test_serve_rejects_invalid_port(tmp_path):
    from bancada.gui.app import serve

    db = make_db(tmp_path, [make_run()])

    try:
        serve(db, port=0)
    except ValueError as exc:
        assert "port" in str(exc).lower()
    else:
        raise AssertionError("serve accepted a port outside 1–65535")


def test_cli_base_without_flask_keeps_base_commands_working(tmp_path, monkeypatch, capsys):
    import builtins

    original_import = builtins.__import__

    def without_gui_app(name, *args, **kwargs):
        if name == "bancada.gui.app":
            raise ModuleNotFoundError("No module named 'flask'", name="flask")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_gui_app)
    assert main(["health"], client=_client()) == 0
    assert "synthetic-model" in capsys.readouterr().out

    db = tmp_path / "runs.sqlite"
    result = main(["gui", "--db", str(db)])

    assert result == 1
    assert "pip install -e '.[gui]'" in capsys.readouterr().err
