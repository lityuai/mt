from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from outbound_agent.engine import AgentEngine, load_tasks
from outbound_agent.evaluation import EvaluationRunner
from outbound_agent.storage import MemorySessionStore


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"

TASKS = load_tasks(ROOT / "data" / "tasks.json")
STORE = MemorySessionStore()
ENGINE = AgentEngine(TASKS)
EVALUATOR = EvaluationRunner(ENGINE, TASKS)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "OutboundAgent/1.0"

    def do_GET(self) -> None:
        path = self._path()
        if path == "/api/health":
            self._json({"status": "ok"})
            return
        if path == "/api/llm/config":
            self._json(ENGINE.llm.config_status())
            return
        if path == "/api/tasks":
            self._json([task.summary() for task in TASKS.values()])
            return
        if path.startswith("/api/tasks/"):
            task_id = unquote(path.removeprefix("/api/tasks/"))
            task = TASKS.get(task_id)
            if not task:
                self._json({"error": "task not found"}, 404)
                return
            self._json(task.to_dict())
            return
        if path.startswith("/api/sessions/"):
            session_id = unquote(path.removeprefix("/api/sessions/"))
            session = STORE.get(session_id)
            if not session:
                self._json({"error": "session not found"}, 404)
                return
            self._json(session.to_dict())
            return
        self._static(path)

    def do_POST(self) -> None:
        path = self._path()
        if path == "/api/llm/test":
            try:
                result = ENGINE.llm.test_connection()
            except RuntimeError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            self._json(result)
            return
        if path == "/api/evaluations/run":
            payload = self._read_json()
            task_id = payload.get("task_id") or None
            if task_id and task_id not in TASKS:
                self._json({"error": "unknown task_id"}, 400)
                return
            mode = str(payload.get("mode") or "rule")
            variables = payload.get("variables") or {}
            settings = payload.get("settings") or {}
            report = EVALUATOR.run(
                task_id=task_id,
                mode=mode,
                variables={key: str(value) for key, value in variables.items()},
                settings=settings,
            )
            self._json(report)
            return
        if path == "/api/evaluations/compare":
            payload = self._read_json()
            task_id = payload.get("task_id") or None
            if task_id and task_id not in TASKS:
                self._json({"error": "unknown task_id"}, 400)
                return
            modes = payload.get("modes") or ["rule", "llm"]
            variables = payload.get("variables") or {}
            settings = payload.get("settings") or {}
            report = EVALUATOR.compare(
                task_id=task_id,
                modes=[str(item) for item in modes],
                variables={key: str(value) for key, value in variables.items()},
                settings=settings,
            )
            self._json(report)
            return
        if path == "/api/sessions":
            payload = self._read_json()
            task_id = payload.get("task_id")
            task = TASKS.get(task_id)
            if not task:
                self._json({"error": "unknown task_id"}, 400)
                return
            variables = payload.get("variables") or {}
            mode = payload.get("mode") or "llm"
            session = STORE.create(
                task_id=task_id,
                variables=variables,
                mode=mode,
            )
            ENGINE.start(session)
            self._json(session.to_dict(), 201)
            return
        if path.startswith("/api/sessions/") and path.endswith("/messages"):
            session_id = unquote(path.split("/")[3])
            session = STORE.get(session_id)
            if not session:
                self._json({"error": "session not found"}, 404)
                return
            payload = self._read_json()
            content = str(payload.get("content") or "").strip()
            if not content:
                self._json({"error": "content is required"}, 400)
                return
            reply = ENGINE.message(session, content)
            self._json({"reply": reply.to_dict(), "session": session.to_dict()})
            return
        self._json({"error": "not found"}, 404)

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))

    def _path(self) -> str:
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        return "/" if path == "/" else path.rstrip("/")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _json(self, data: object, status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _static(self, path: str) -> None:
        requested = "index.html" if path == "/" else unquote(path.lstrip("/"))
        file_path = (STATIC_DIR / requested).resolve()
        try:
            file_path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._json({"error": "invalid path"}, 403)
            return
        if not file_path.exists() or not file_path.is_file():
            self._json({"error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        raw = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Outbound dialogue agent workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Serving on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
