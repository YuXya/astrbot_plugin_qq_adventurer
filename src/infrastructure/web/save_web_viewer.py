from __future__ import annotations

import html
import secrets
from typing import Any
from urllib.parse import quote

from aiohttp import web

from ...utils.logger import logger


class SaveWebViewer:
    def __init__(
        self,
        repository,
        editable_manager,
        host: str = "0.0.0.0",
        port: int = 8501,
    ):
        self.repository = repository
        self.editable_manager = editable_manager
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
        app.router.add_get("/editable", self._editable_index)
        app.router.add_get("/editable/file", self._editable_file)
        app.router.add_post("/editable/save", self._editable_save)
        app.router.add_post("/editable/reset", self._editable_reset)
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
            level = self._e(f"Lv.{item.get('level', 1)}")
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
                f"<td>{level}</td>"
                f"<td>{location}</td>"
                f"<td>{updated_at}</td>"
                "</tr>"
            )

        body = "\n".join(rows) or "<tr><td colspan=\"8\">还没有任何玩家存档。</td></tr>"
        return self._html_response(
            "异世界存档",
            f"""
            <h1>异世界存档</h1>
            <p class="muted">只读查看页。关闭网页命令会立即使当前令牌失效。</p>
            <p><a href="/editable?token={self._e(self.token)}">编辑世界书和 Prompt 话术</a></p>
            <table>
              <thead>
                <tr>
                  <th>群</th><th>用户</th><th>角色</th>
                  <th>种族</th><th>职阶</th><th>等级</th><th>地点</th><th>更新时间</th>
                </tr>
              </thead>
              <tbody>{body}</tbody>
            </table>
            """,
        )

    async def _editable_index(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return self._forbidden()

        rows = []
        for item in self.editable_manager.list_editable_files():
            raw_file_id = item["id"]
            file_id = self._e(raw_file_id)
            label = self._e(item["label"])
            file_type = self._e(item["type"])
            href = (
                f"/editable/file?id={quote(raw_file_id, safe='')}"
                f"&token={self._e(self.token)}"
            )
            rows.append(
                "<tr>"
                f"<td><a href=\"{href}\">{label}</a></td>"
                f"<td>{file_id}</td>"
                f"<td>{file_type}</td>"
                "</tr>"
            )

        return self._html_response(
            "可编辑资源",
            f"""
            <h1>可编辑资源</h1>
            <p><a href="/?token={self._e(self.token)}">返回存档列表</a></p>
            <p class="muted">保存时会自动备份旧文件。世界书 default.json 会先做 JSON 校验。</p>
            <table>
              <thead><tr><th>名称</th><th>文件</th><th>类型</th></tr></thead>
              <tbody>{"".join(rows)}</tbody>
            </table>
            """,
        )

    async def _editable_file(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return self._forbidden()

        file_id = request.query.get("id", "")
        if not self._is_editable_file(file_id):
            raise web.HTTPBadRequest(text="invalid editable file")
        content = self.editable_manager.read_text(file_id)
        title = f"编辑 {file_id}"
        return self._html_response(
            title,
            f"""
            <h1>{self._e(title)}</h1>
            <p><a href="/editable?token={self._e(self.token)}">返回可编辑资源</a></p>
            <form method="post" action="/editable/save?token={self._e(self.token)}">
              <input type="hidden" name="id" value="{self._e(file_id)}">
              <textarea name="content" spellcheck="false">{self._e(content)}</textarea>
              <div class="actions">
                <button type="submit">保存</button>
              </div>
            </form>
            <form method="post" action="/editable/reset?token={self._e(self.token)}" onsubmit="return confirm('确定恢复为当前代码内置默认内容？旧文件会先自动备份。');">
              <input type="hidden" name="id" value="{self._e(file_id)}">
              <button class="secondary" type="submit">恢复当前默认内容</button>
            </form>
            """,
        )

    async def _editable_save(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return self._forbidden()

        data = await request.post()
        file_id = str(data.get("id", ""))
        content = str(data.get("content", ""))
        if not self._is_editable_file(file_id):
            raise web.HTTPBadRequest(text="invalid editable file")

        try:
            if file_id == "world_book/default.json":
                self.editable_manager.write_world_book(content)
            else:
                self.editable_manager.write_text(file_id, content)
        except Exception as exc:
            return self._html_response(
                "保存失败",
                f"""
                <h1>保存失败</h1>
                <p class="error">{self._e(exc)}</p>
                <p><a href="/editable/file?id={quote(file_id, safe='')}&token={self._e(self.token)}">返回编辑</a></p>
                """,
                status=400,
            )

        raise web.HTTPFound(
            f"/editable/file?id={quote(file_id, safe='')}&token={self._e(self.token)}"
        )

    async def _editable_reset(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return self._forbidden()

        data = await request.post()
        file_id = str(data.get("id", ""))
        if not self._is_editable_file(file_id):
            raise web.HTTPBadRequest(text="invalid editable file")

        try:
            self.editable_manager.reset_to_default(file_id)
        except Exception as exc:
            return self._html_response(
                "恢复默认失败",
                f"""
                <h1>恢复默认失败</h1>
                <p class="error">{self._e(exc)}</p>
                <p><a href="/editable/file?id={quote(file_id, safe='')}&token={self._e(self.token)}">返回编辑</a></p>
                """,
                status=400,
            )

        raise web.HTTPFound(
            f"/editable/file?id={quote(file_id, safe='')}&token={self._e(self.token)}"
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

    def _html_response(
        self,
        title: str,
        content: str,
        status: int = 200,
    ) -> web.Response:
        return web.Response(
            status=status,
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
    textarea {{ width: 100%; min-height: 68vh; resize: vertical; padding: 12px; border: 1px solid #c8d0dc; border-radius: 6px; font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size: 13px; line-height: 1.5; }}
    button {{ margin-top: 12px; padding: 9px 16px; border: 0; border-radius: 6px; background: #1f6feb; color: #fff; font-weight: 700; cursor: pointer; }}
    button.secondary {{ background: #59636e; }}
    .actions {{ display: flex; gap: 10px; align-items: center; }}
    .error {{ color: #b42318; font-weight: 700; }}
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

    def _is_editable_file(self, file_id: str) -> bool:
        return file_id in {
            item["id"] for item in self.editable_manager.list_editable_files()
        }
