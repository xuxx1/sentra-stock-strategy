"""SENTRA 本地 API 服务。仅使用 Python 标准库。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_env_file() -> None:
    """读取 backend/.env（若存在），仅填充尚未设置的环境变量，不覆盖已有值。"""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()

from backend.app.workflow import PipelineService, WorkflowError  # noqa: E402
from backend.app.workflow.scheduler import CollectionScheduler  # noqa: E402


SERVICE = PipelineService()
SCHEDULER = CollectionScheduler(SERVICE)
SERVICE.attach_scheduler(SCHEDULER)


class SentraHandler(BaseHTTPRequestHandler):
    server_version = "SentraAPI/0.1"

    def _cors_origin(self) -> str:
        allowed = os.getenv("CORS_ORIGIN", "http://127.0.0.1:3000")
        origin = self.headers.get("Origin", "")
        return origin if origin and origin in {item.strip() for item in allowed.split(",")} else allowed.split(",")[0].strip()

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._json(HTTPStatus.NO_CONTENT, {})

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/api/health":
            snapshot = SERVICE.snapshot()
            self._json(
                HTTPStatus.OK,
                {
                    "success": True,
                    "service": "sentra-api",
                    "stage": snapshot.get("stage", "idle"),
                    "model_configured": bool(os.getenv("OPENAI_API_KEY")),
        "analysis_engine": snapshot.get("analysis_engine", "auto"),
        "effective_mode": SERVICE._effective_mode(snapshot.get("analysis_engine") or "auto"),
                    "model": os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
                    "analysis_mode": "openai" if os.getenv("OPENAI_API_KEY") else "rule_based",
                    "rule_fallback_available": True,
                },
            )
            return
        if path == "/api/workflow/latest":
            self._json(HTTPStatus.OK, {"success": True, "data": SERVICE.public_result()})
            return
        if path == "/api/admin/overview":
            self._json(HTTPStatus.OK, {"success": True, "data": SERVICE.admin_result()})
            return
        self._json(HTTPStatus.NOT_FOUND, {"success": False, "error": "接口不存在"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/workflow/engine":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length > 0 else b""
                body = json.loads(raw.decode("utf-8")) if raw else {}
                result = SERVICE.set_analysis_engine(str(body.get("engine", "")).strip())
                self._json(HTTPStatus.OK, {"success": True, "data": result})
            except WorkflowError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"success": False, "error": str(exc)})
            except Exception as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"success": False, "error": f"服务异常：{exc}"})
            return

        if path == "/api/workflow/market-mode":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length > 0 else b""
                body = json.loads(raw.decode("utf-8")) if raw else {}
                mode = str(body.get("mode", "")).strip()
                if mode not in ("simulated", "real"):
                    raise WorkflowError(f"不支持的行情模式：{mode or '空值'}")
                SERVICE._update(market_data_mode=mode, last_error="")
                self._json(HTTPStatus.OK, {"success": True, "data": {"market_data_mode": mode}})
            except WorkflowError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"success": False, "error": str(exc)})
            except Exception as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"success": False, "error": f"服务异常：{exc}"})
            return

        actions = {
            "/api/collect": SERVICE.collect,
            "/api/workflow/analyze": SERVICE.analyze,
            "/api/workflow/run": SERVICE.run_full,
            "/api/workflow/apply-real-data": SERVICE.apply_real_data,
            "/api/workflow/reset-simulated": SERVICE.reset_to_simulated,
            "/api/history/refresh": SERVICE.refresh_history,
            "/api/scheduler/enable": SCHEDULER.enable,
            "/api/scheduler/disable": SCHEDULER.disable,
        }
        action = actions.get(path)
        if action is None and path.startswith("/api/workflow/node/"):
            node_id = path.rsplit("/", 1)[-1]
            action = lambda: SERVICE.run_node(node_id)
        if action is None and path == "/api/market-data/fetch":
            scope = query.get("scope", ["candidates"])[0]
            data_types = [item for value in query.get("types", ["quotes,capital"]) for item in value.split(",") if item]
            action = lambda: SERVICE.fetch_market_data(scope, data_types)
        if action is None:
            self._json(HTTPStatus.NOT_FOUND, {"success": False, "error": "接口不存在"})
            return
        # 解析请求体，把研判焦点参数透传到对应 SERVICE 方法
        request_body: dict[str, Any] = {}
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            if raw:
                request_body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            request_body = {}
        kwargs = {
            "target_type": request_body.get("target_type"),
            "target_name": request_body.get("target_name"),
            "period": str(request_body.get("period") or "") if request_body.get("period") not in (None, "") else None,
            "analysis_engine": request_body.get("analysis_engine"),
            "market_data_mode": request_body.get("market_data_mode"),
        }
        kwargs = {k: v for k, v in kwargs.items() if v not in (None, "")}
        if not SERVICE.run_lock.acquire(blocking=False):
            self._json(HTTPStatus.CONFLICT, {"success": False, "error": "已有任务正在运行，请稍候"})
            return
        try:
            data = asyncio.run(action(**kwargs))
            self._json(HTTPStatus.OK, {"success": True, "data": data})
        except WorkflowError as exc:
            self._json(HTTPStatus.BAD_GATEWAY, {"success": False, "error": str(exc), "data": SERVICE.public_result()})
        except Exception as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"success": False, "error": f"服务异常：{exc}"})
        finally:
            SERVICE.run_lock.release()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description="启动 SENTRA 本地 API 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), SentraHandler)
    SCHEDULER.start()
    print(f"SENTRA API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        SCHEDULER.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
