"""Desktop entry point.

Usage:
    python app.py                 # native window (pywebview / WebView2)
    python app.py --no-window     # local server only (tests, browser UI)
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from .api import APP_TITLE, create_app
from .settings import Settings


def free_port(preferred: int = 0) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", preferred))
        return int(sock.getsockname()[1])


def wait_for_server(port: int, timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.12)
    return False


def run_server(app, port: int, debug: bool = False) -> None:
    app.run(host="127.0.0.1", port=port, debug=debug, use_reloader=False, threaded=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FileGenFOAM Studio")
    parser.add_argument("--no-window", action="store_true", help="Run the local server without opening a desktop window")
    parser.add_argument("--port", type=int, default=0, help="HTTP port (0 chooses a free port)")
    parser.add_argument("--debug", action="store_true", help="Enable webview/flask debug mode")
    parser.add_argument("--browser", action="store_true", help="Open the UI in the default browser")
    args = parser.parse_args(argv)

    settings = Settings.load()
    app = create_app(settings)
    port = args.port or free_port()
    url = f"http://127.0.0.1:{port}/"

    if args.no_window:
        print(f"{APP_TITLE} running at {url}", flush=True)
        if args.browser:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        app.run(host="127.0.0.1", port=port, debug=args.debug, use_reloader=False, threaded=True)
        return 0

    server_thread = threading.Thread(target=run_server, args=(app, port, args.debug), daemon=True)
    server_thread.start()
    if not wait_for_server(port):
        print("No se pudo iniciar el servidor local", file=sys.stderr)
        return 1

    try:
        import webview
    except Exception as exc:  # pragma: no cover - depends on desktop environment
        print(f"No se pudo cargar pywebview ({exc}). Abriendo en el navegador.", file=sys.stderr)
        webbrowser.open(url)
        while True:
            time.sleep(3600)

    window = webview.create_window(
        f"{APP_TITLE} — CFD Workbench",
        url,
        width=1580,
        height=980,
        min_size=(1120, 700),
        background_color="#0b0e14",
        text_select=True,
        confirm_close=False,
    )

    def _on_closing():
        active = app.config["CTX"].jobs.active()
        if not active:
            return True
        confirmed = window.create_confirmation_dialog(
            "Simulación en curso",
            "Hay un solver ejecutándose. ¿Quieres detenerlo y cerrar FileGenFOAM Studio?",
        )
        if confirmed:
            active.request_cancel()
            time.sleep(1.0)
            return True
        return False

    window.events.closing += _on_closing
    try:
        webview.start(debug=args.debug, private_mode=False)
    except Exception as exc:
        print(f"No se pudo abrir la ventana nativa: {exc}", file=sys.stderr)
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
