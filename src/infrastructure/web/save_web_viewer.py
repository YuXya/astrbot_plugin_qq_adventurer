from __future__ import annotations

import html
import secrets
from typing import Any

from aiohttp import web

from ...utils.logger import logger


class SaveWebViewer:
    def __init__(self, repository, host: str = "0.0.0.0", port: int = 8501):
        self.repository = repository
        self.host = host
        self.port = int(port)
        self.token = ""
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    @property
    def is_running(self) -> bool:
        return self._runner is not None

    async def start(self) -> str:
        if self.is_running:
            return self.token

        self.token = secrets.token_urlsafe(24)
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/player", self._player_detail)
        app.router.add_get("/health", self._health)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info(f"异世界存档网页已启动: {self.host}:{self.port}")
        return self.token

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
        self._runner = None
        self._site = None
        self.token = ""
        logger.info("异世界存档网页已关闭")

    async def _health(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return self._forbidden()
        return web.json_response({"ok": True})

    async def _index(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return self._forbidden()

        saves = self.repository.list_saves()
        rows = []
        for item in saves:
            group_id = self._e(item.get("group_id", ""))
            user_id = self._e(item.get("user_id", ""))
            nickname = self._e(item.get("nickname") or item.get("target_name") or "未命名")
            race = self._e(item.get("race", ""))
            class_name = self._e(item.get("class_name", ""))
            location = self._e(item.get("location", ""))
            updated_at = self._format_time(item.get("updated_at"))
            href = f"/player?group_id={group_id}&user_id={user_id}&token={self._e(self.token)}"
            rows.append(
                "<tr>"
                f"<td>{group_id}</td>"
                f"<td>{user_id}</td>"
                f"<td><a href=\"{href}\">{nickname}</a></td>"
                f"<td>{race}</td>"
                f"<td>{class_name}</td>"
                f"<td>{location}</td>"
                f"<td>{updated_at}</td>"
                "</tr>"
            )

        body = "\n".join(rows) or "<tr><td colspan=\"7\">还没有任何玩家存档。</td></tr>"
        return self._html_response(
            "异世界存档",
            f"""
            <h1>异世界存档</h1>
            <p class="muted">只读查看页。关闭网页命令会立即使当前令牌失效。</p>
            <table>
              <thead>
                <tr>
                  <th>群</th><th>用户</th><th>角色</th>
                  <th>种族</th><th>职阶</th><th>地点</th><th>更新时间</th>
                </tr>
              </thead>
              <tbody>{body}</tbody>
            </table>
            """,
        )

    async def _player_detail(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return self._forbidden()

        group_id = request.query.get("group_id", "")
        user_id = request.query.get("user_id", "")
        detail = self.repository.read_save_detail(group_id, user_id)
        if detail is None:
            raise web.HTTPNotFound(text="save not found")

        return self._html_response(
            "玩家存档",
            f"""
            <h1>玩家存档</h1>
            <p><a href="/?token={self._e(self.token)}">返回列表</a></p>
            <section>
              <h2>Profile</h2>
              <pre>{self._e_json(detail.get("profile", {}))}</pre>
            </section>
            <section>
              <h2>State</h2>
              <pre>{self._e_json(detail.get("state", {}))}</pre>
            </section>
            <section>
              <h2>Adventure Log</h2>
              <pre>{self._e_json(detail.get("logs", []))}</pre>
            </section>
            """,
        )

    def _is_authorized(self, request: web.Request) -> bool:
        query_token = request.query.get("token", "")
        auth = request.headers.get("Authorization", "")
        bearer = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
        return bool(self.token and (query_token == self.token or bearer == self.token))

    @staticmethod
    def _forbidden() -> web.Response:
        return web.Response(
            status=403,
            text="Forbidden: missing or invalid token.",
            content_type="text/plain",
        )

    def _html_response(self, title: str, content: str) -> web.Response:
        return web.Response(
            text=f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{self._e(title)}</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f6f7f9; color: #20242a; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 28px 18px 48px; }}
    h1 {{ margin: 0 0 12px; font-size: 28px; }}
    h2 {{ margin: 24px 0 10px; font-size: 18px; }}
    .muted {{ color: #68707d; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #dde2ea; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e6eaf0; text-align: left; font-size: 14px; }}
    th {{ background: #eef2f6; color: #3a4350; }}
    a {{ color: #1f6feb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    pre {{ overflow: auto; padding: 14px; background: #111827; color: #d1e7dd; border-radius: 6px; line-height: 1.45; }}
  </style>
</head>
<body><main>{content}</main></body>
</html>""",
            content_type="text/html",
        )

    @staticmethod
    def _e(value: object) -> str:
        return html.escape(str(value or ""), quote=True)

    def _e_json(self, value: Any) -> str:
        import json

        return self._e(json.dumps(value, ensure_ascii=False, indent=2))

    @staticmethod
    def _format_time(value: object) -> str:
        try:
            import datetime as dt

            timestamp = int(value or 0) / 1000
            if timestamp <= 0:
                return ""
            return dt.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ""
