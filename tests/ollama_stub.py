"""A stand-in for Ollama on a loopback port, for the clients that talk to a local model."""

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class Stub:
    """Records requests and answers with whatever `reply` says."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.reply: Callable[[BaseHTTPRequestHandler], None] = lambda h: None
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                stub.requests.append({"path": self.path, "body": json.loads(body)})
                stub.reply(self)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def answer(self, content: object) -> None:
        self.send(200, json.dumps({"message": {"role": "assistant", "content": content}}))

    def send(self, status: int, body: str, headers: dict[str, str] | None = None) -> None:
        def reply(handler: BaseHTTPRequestHandler) -> None:
            handler.send_response(status)
            for name, value in (headers or {}).items():
                handler.send_header(name, value)
            handler.send_header("Content-Length", str(len(body.encode())))
            handler.end_headers()
            handler.wfile.write(body.encode())

        self.reply = reply

    def redirect_once(self, answer: str) -> None:
        """A 307 to another path, which would repeat the POST there, and a valid answer there."""
        payload = answer.encode()

        def reply(handler: BaseHTTPRequestHandler) -> None:
            moved = handler.path == "/api/chat"
            handler.send_response(307 if moved else 200)
            if moved:
                handler.send_header("Location", f"{self.url}/elsewhere")
            handler.send_header("Content-Length", "0" if moved else str(len(payload)))
            handler.end_headers()
            if not moved:
                handler.wfile.write(payload)

        self.reply = reply

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
