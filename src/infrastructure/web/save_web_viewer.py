from __future__ import annotations

import html
import hmac
import json
import re
import secrets
from typing import Any
from urllib.parse import quote

from aiohttp import web

from ...utils.logger import logger
from ..storage.state_progress import (
    build_progress_sections,
    build_state_display_items,
    level_display,
    level_exp_percent,
)


ADMIN_LOGIN_CODE = "优夏酱世界第一可爱"
SESSION_COOKIE_NAME = "qq_adventurer_session"
SESSION_ADMIN_ROLE = "admin"
SESSION_USER_ROLE = "user"


class SaveWebViewer:
    def __init__(
        self,
        repository,
        editable_manager,
        host: str = "0.0.0.0",
        port: int = 8501,
        public_path_prefix: str = "",
    ):
        self.repository = repository
        self.editable_manager = editable_manager
        self.host = host
        self.port = int(port)
        self.public_path_prefix = self._normalize_path_prefix(public_path_prefix)
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
        self._add_route(app, "GET", "/login", self._login_page)
        self._add_route(app, "POST", "/login", self._login)
        self._add_route(app, "POST", "/logout", self._logout)
        self._add_route(app, "GET", "/", self._index)
        self._add_route(app, "GET", "/player", self._player_detail)
        self._add_route(app, "POST", "/player/delete", self._player_delete)
        self._add_route(app, "POST", "/player/log/delete", self._player_log_delete)
        self._add_route(app, "GET", "/editable", self._editable_index)
        self._add_route(app, "GET", "/editable/file", self._editable_file)
        self._add_route(app, "POST", "/editable/save", self._editable_save)
        self._add_route(app, "POST", "/editable/reset", self._editable_reset)
        self._add_route(app, "GET", "/health", self._health)

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

    def _add_route(self, app: web.Application, method: str, path: str, handler) -> None:
        app.router.add_route(method, path, handler)
        prefixed_path = self._url(path)
        if prefixed_path != path:
            app.router.add_route(method, prefixed_path, handler)

    async def _login_page(self, request: web.Request) -> web.Response:
        if self._is_authorized(request):
            raise self._redirect("/")
        return self._login_response()

    async def _login(self, request: web.Request) -> web.Response:
        data = await request.post()
        qq_id = str(data.get("qq_id", "")).strip()
        if qq_id == ADMIN_LOGIN_CODE:
            cookie_value = self._build_session_cookie(SESSION_ADMIN_ROLE)
        else:
            saves = self.repository.list_saves_by_user(qq_id)
            if not saves:
                return self._login_response("没有找到这个 QQ 号的异世界存档。", status=401)
            cookie_value = self._build_session_cookie(SESSION_USER_ROLE, self._safe_session_id(qq_id))

        response = self._redirect("/")
        response.set_cookie(
            SESSION_COOKIE_NAME,
            cookie_value,
            httponly=True,
            samesite="Lax",
            path=self._cookie_path(),
        )
        raise response

    async def _logout(self, request: web.Request) -> web.Response:
        response = self._redirect("/login")
        response.del_cookie(SESSION_COOKIE_NAME, path=self._cookie_path())
        raise response

    def _login_response(self, error: str = "", status: int = 200) -> web.Response:
        error_html = f"<p class=\"error\">{self._e(error)}</p>" if error else ""
        return self._html_response(
            "异世界登录",
            f"""
            <section class="login-panel">
              <h1>异世界网页登录</h1>
              <p class="muted">请输入 QQ 号登录。</p>
              {error_html}
              <form method="post" action="{self._url('/login')}">
                <label for="qq-id">QQ号</label>
                <input id="qq-id" name="qq_id" type="text" autocomplete="username" autofocus>
                <div class="actions">
                  <button type="submit">登录</button>
                </div>
              </form>
            </section>
            """,
            status=status,
            show_logout=False,
        )

    async def _health(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return self._forbidden()
        return web.json_response({"ok": True})

    async def _index(self, request: web.Request) -> web.Response:
        session = self._session(request)
        if not session:
            return self._forbidden()
        if session["role"] == SESSION_USER_ROLE:
            return self._user_index(session["user_id"])

        saves = self.repository.list_saves()
        rows = []
        for item in saves:
            row = self._save_table_row(item)
            delete_form = (
                f"<form class=\"inline-form\" method=\"post\" action=\"{self._url('/player/delete')}\" "
                "onsubmit=\"return confirm('确定删除这个玩家存档？此操作不可恢复。');\">"
                f"<input type=\"hidden\" name=\"group_id\" value=\"{row['group_id']}\">"
                f"<input type=\"hidden\" name=\"user_id\" value=\"{row['user_id']}\">"
                "<button class=\"danger compact-button\" type=\"submit\">删除</button>"
                "</form>"
            )
            rows.append(
                "<tr>"
                f"<td>{row['group_id']}</td>"
                f"<td>{row['user_id']}</td>"
                f"<td><a href=\"{row['href']}\">{row['nickname']}</a></td>"
                f"<td>{row['race']}</td>"
                f"<td>{row['class_name']}</td>"
                f"<td>{row['level']}</td>"
                f"<td>{row['region']}</td>"
                f"<td>{row['location']}</td>"
                f"<td>{row['updated_at']}</td>"
                f"<td>{delete_form}</td>"
                "</tr>"
            )

        body = "\n".join(rows) or "<tr><td colspan=\"10\">还没有任何玩家存档。</td></tr>"
        return self._html_response(
            "异世界存档",
            f"""
            <h1>异世界存档</h1>
            <p class="muted">管理员页面。关闭网页命令会立即使当前网页登录态失效。</p>
            <p class="nav-actions">
              <a class="button-link" href="{self._url('/editable?category=world_background')}">编辑世界背景</a>
              <a class="button-link" href="{self._url('/editable?category=text_completion')}">编辑文本补全</a>
            </p>
            <table>
              <thead>
                <tr>
                  <th>群</th><th>用户</th><th>角色</th>
                  <th>种族</th><th>职阶</th><th>等级</th><th>区域</th><th>地点</th><th>更新时间</th><th>操作</th>
                </tr>
              </thead>
              <tbody>{body}</tbody>
            </table>
            """,
        )

    def _user_index(self, user_id: str) -> web.Response:
        saves = self.repository.list_saves_by_user(user_id)
        rows = []
        for item in saves:
            row = self._save_table_row(item)
            rows.append(
                "<tr>"
                f"<td>{row['group_id']}</td>"
                f"<td><a href=\"{row['href']}\">{row['nickname']}</a></td>"
                f"<td>{row['race']}</td>"
                f"<td>{row['class_name']}</td>"
                f"<td>{row['level']}</td>"
                f"<td>{row['region']}</td>"
                f"<td>{row['location']}</td>"
                f"<td>{row['updated_at']}</td>"
                "</tr>"
            )

        body = "\n".join(rows) or "<tr><td colspan=\"8\">还没有找到你的异世界存档。</td></tr>"
        return self._html_response(
            "我的异世界存档",
            f"""
            <h1>我的异世界存档</h1>
            <p class="muted">当前登录 QQ：{self._e(user_id)}</p>
            <table>
              <thead>
                <tr>
                  <th>群</th><th>角色</th><th>种族</th><th>职阶</th><th>等级</th><th>区域</th><th>地点</th><th>更新时间</th>
                </tr>
              </thead>
              <tbody>{body}</tbody>
            </table>
            """,
        )

    def _save_table_row(self, item: dict[str, Any]) -> dict[str, str]:
        group_id = self._e(item.get("group_id", ""))
        user_id = self._e(item.get("user_id", ""))
        href = self._url(f"/player?group_id={group_id}&user_id={user_id}")
        return {
            "group_id": group_id,
            "user_id": user_id,
            "nickname": self._e(item.get("nickname") or item.get("target_name") or "未命名"),
            "race": self._e(item.get("race", "")),
            "class_name": self._e(item.get("class_name", "")),
            "level": self._e(f"{item.get('level', 1)}级"),
            "region": self._e(item.get("region", "")),
            "location": self._e(item.get("location", "")),
            "updated_at": self._format_time(item.get("updated_at")),
            "href": href,
        }

    async def _editable_index(self, request: web.Request) -> web.Response:
        if not self._is_admin(request):
            return self._forbidden()

        selected_category = request.query.get("category", "world_background")
        category_titles = {
            "world_background": "世界背景",
            "text_completion": "文本补全",
        }
        category_descriptions = {
            "world_background": "影响异世界公共设定、地点、魔物、种族和职业等背景内容。",
            "text_completion": "管理发给 AI 的 Prompt、System Prompt 和世界书注入话术。",
        }
        if selected_category not in category_titles:
            raise web.HTTPBadRequest(text="invalid editable category")

        items = self.editable_manager.list_editable_files()
        rows = self._editable_rows(items, selected_category)
        title = category_titles[selected_category]
        description = category_descriptions[selected_category]

        return self._html_response(
            title,
            f"""
            <h1>{self._e(title)}</h1>
            <p><a href="{self._url('/')}">返回存档列表</a></p>
            <p class="muted">保存时会自动备份旧文件。世界书、技能书和状态书 default.json 会先做 JSON 校验。</p>
            {self._editable_table(description, rows)}
            """,
        )

    async def _editable_file(self, request: web.Request) -> web.Response:
        if not self._is_admin(request):
            return self._forbidden()

        file_id = request.query.get("id", "")
        if not self._is_editable_file(file_id):
            raise web.HTTPBadRequest(text="invalid editable file")
        back_category = self._editable_back_category(request.query.get("category"), file_id)
        content = self.editable_manager.read_text(file_id)
        note = self.editable_manager.read_note(file_id)
        meta = self._editable_file_meta(file_id)
        label = meta.get("label", file_id) if meta else file_id
        title = f"编辑 {label}"
        if self._is_structured_book_file(file_id):
            return self._world_book_file_response(
                title,
                file_id,
                back_category,
                note,
                content,
            )

        return self._plain_editable_file_response(
            title,
            file_id,
            back_category,
            note,
            content,
        )

    def _plain_editable_file_response(
        self,
        title: str,
        file_id: str,
        back_category: str,
        note: str,
        content: str,
        warning: str = "",
    ) -> web.Response:
        warning_html = (
            f"<p class=\"error\">{self._e(warning)}</p>"
            if warning
            else ""
        )
        return self._html_response(
            title,
            f"""
            <h1>{self._e(title)}</h1>
            <p><a href="{self._url(f'/editable?category={self._e(back_category)}')}">返回{self._e(self._editable_category_title(back_category))}</a></p>
            <p class="muted">{self._e(file_id)}</p>
            {warning_html}
            <form method="post" action="{self._url('/editable/save')}">
              <input type="hidden" name="id" value="{self._e(file_id)}">
              <input type="hidden" name="category" value="{self._e(back_category)}">
              <label for="note">资源说明 / 注释</label>
              <textarea id="note" class="note-editor" name="note" spellcheck="false">{self._e(note)}</textarea>
              <label for="content">资源正文</label>
              <textarea id="content" class="content-editor" name="content" spellcheck="false">{self._e(content)}</textarea>
              <div class="actions">
                <button type="submit">保存</button>
              </div>
            </form>
            <form method="post" action="{self._url('/editable/reset')}" onsubmit="return confirm('确定恢复为当前代码内置默认内容？旧文件会先自动备份。');">
              <input type="hidden" name="id" value="{self._e(file_id)}">
              <input type="hidden" name="category" value="{self._e(back_category)}">
              <button class="secondary" type="submit">恢复当前默认内容</button>
            </form>
            """,
        )

    def _world_book_file_response(
        self,
        title: str,
        file_id: str,
        back_category: str,
        note: str,
        content: str,
    ) -> web.Response:
        try:
            book = self._normalize_world_book(json.loads(content))
        except Exception as exc:
            return self._plain_editable_file_response(
                title,
                file_id,
                back_category,
                note,
                content,
                warning=f"世界书 JSON 解析失败，请先修复原始 JSON：{exc}",
            )

        book_json = self._json_script_data(book)
        is_patch_book = file_id in {"skill_book/default.json", "status_book/default.json"}
        base_path_block = (
            f"""
              <div class="book-config-grid">
                <div>
                  <label for="book-display-name">展示名称</label>
                  <input id="book-display-name" type="text" value="{self._e(book.get('display_name') or self._default_book_display_name(file_id))}" spellcheck="false">
                </div>
                <div>
                  <label for="book-base-path">默认 patch 基础路径</label>
                  <input id="book-base-path" type="text" value="{self._e(book.get('base_path') or '')}" spellcheck="false">
                </div>
              </div>
              <p class="muted">这个路径会发给 AI 作为 update.patches 的路径提示，不代表 JSON 文件实际存放路径。</p>
            """
            if is_patch_book
            else ""
        )
        book_title = (
            "技能书条目"
            if file_id == "skill_book/default.json"
            else "状态书条目"
            if file_id == "status_book/default.json"
            else "世界书条目"
        )
        book_hint = (
            "每个条目会在命中后作为技能说明注入 Prompt。"
            if file_id == "skill_book/default.json"
            else "条目标题代表可觉醒状态；已拥有状态命中后注入说明，未拥有状态标题进入待觉醒列表。"
            if file_id == "status_book/default.json"
            else "每个条目会在命中后作为世界背景补充注入 Prompt。"
        )
        storage_key = "qq_adventurer:book:open_entries:" + file_id.replace("/", ":")
        return self._html_response(
            title,
            f"""
            <h1>{self._e(title)}</h1>
            <p><a href="{self._url(f'/editable?category={self._e(back_category)}')}">返回{self._e(self._editable_category_title(back_category))}</a></p>
            <p class="muted">{self._e(file_id)}</p>
            <form id="world-book-form" method="post" action="{self._url('/editable/save')}">
              <input type="hidden" name="id" value="{self._e(file_id)}">
              <input type="hidden" name="category" value="{self._e(back_category)}">
              <input id="world-book-content" type="hidden" name="content" value="">
              <label for="note">资源说明 / 注释</label>
              <textarea id="note" class="note-editor" name="note" spellcheck="false">{self._e(note)}</textarea>
              {base_path_block}

              <div class="world-book-toolbar">
                <div>
                  <h2>{self._e(book_title)}</h2>
                  <p class="muted">{self._e(book_hint)}</p>
                </div>
                <button id="add-entry" type="button">+ 添加条目</button>
              </div>
              <div id="world-book-entries"></div>
              <div class="actions">
                <button type="submit">保存</button>
              </div>
            </form>
            <form method="post" action="{self._url('/editable/reset')}" onsubmit="return confirm('确定恢复为当前代码内置默认内容？旧文件会先自动备份。');">
              <input type="hidden" name="id" value="{self._e(file_id)}">
              <input type="hidden" name="category" value="{self._e(back_category)}">
              <button class="secondary" type="submit">恢复当前默认内容</button>
            </form>
            <script>
              const initialWorldBook = {book_json};
              const entriesEl = document.getElementById("world-book-entries");
              const addEntryButton = document.getElementById("add-entry");
              const form = document.getElementById("world-book-form");
              const contentInput = document.getElementById("world-book-content");
              const displayNameInput = document.getElementById("book-display-name");
              const basePathInput = document.getElementById("book-base-path");
              const openStateStorageKey = "{self._e(storage_key)}";
              let draggingIndex = null;
              let openEntryKeys = new Set();
              let hasCapturedOpenState = false;

              const state = {{
                ...initialWorldBook,
                entries: Array.isArray(initialWorldBook.entries) ? initialWorldBook.entries : [],
              }};
              if (displayNameInput) {{
                state.display_name = String(initialWorldBook.display_name || displayNameInput.value || "");
              }}
              if (basePathInput) {{
                state.base_path = String(initialWorldBook.base_path || basePathInput.value || "");
              }}

              function entryDefaults(index) {{
                return {{
                  id: `entry_${{index + 1}}`,
                  title: "",
                  enabled: true,
                  recursive: true,
                  strategy: "keyword",
                  keys: [],
                  order: 100,
                  content: "",
                }};
              }}

              function normalizeEntry(entry, index) {{
                const keys = Array.isArray(entry.keys)
                  ? entry.keys
                  : (typeof entry.keys === "string" ? [entry.keys] : []);
                const order = Number.parseInt(entry.order, 10);
                return {{
                  id: String(entry.id || `entry_${{index + 1}}`).trim(),
                  title: String(entry.title || ""),
                  enabled: entry.enabled !== false,
                  recursive: entry.recursive !== false,
                  strategy: entry.strategy === "always" ? "always" : "keyword",
                  keys: keys.map((key) => String(key).trim()).filter(Boolean),
                  order: Number.isFinite(order) ? order : 100,
                  content: String(entry.content || ""),
                }};
              }}

              function splitKeys(value) {{
                return String(value || "")
                  .split(/[\\n,，]/)
                  .map((key) => key.trim())
                  .filter(Boolean);
              }}

              function syncFromDom() {{
                if (displayNameInput) {{
                  state.display_name = displayNameInput.value;
                }}
                if (basePathInput) {{
                  state.base_path = basePathInput.value;
                }}
                state.entries = Array.from(entriesEl.querySelectorAll(".world-entry")).map((card, index) => normalizeEntry({{
                  id: card.querySelector("[data-field='id']").value,
                  title: card.querySelector("[data-field='title']").value,
                  enabled: card.querySelector("[data-field='enabled']").checked,
                  recursive: card.querySelector("[data-field='recursive']").checked,
                  strategy: card.querySelector("[data-field='strategy']").value,
                  keys: splitKeys(card.querySelector("[data-field='keys']").value),
                  order: card.querySelector("[data-field='order']").value,
                  content: card.querySelector("[data-field='content']").value,
                }}, index));
              }}

              function entryDomKey(entry, index) {{
                return String(entry.id || entry.title || `entry_${{index + 1}}`).trim();
              }}

              function captureOpenState() {{
                hasCapturedOpenState = true;
                openEntryKeys = new Set(
                  Array.from(entriesEl.querySelectorAll(".world-entry")).flatMap((card) => {{
                    const key = card.dataset.entryKey;
                    const details = card.querySelector("details");
                    return key && details && details.open ? [key] : [];
                  }})
                );
                persistOpenState();
              }}

              function loadOpenState() {{
                try {{
                  const raw = localStorage.getItem(openStateStorageKey);
                  if (!raw) {{
                    return;
                  }}
                  const data = JSON.parse(raw);
                  if (!data || !Array.isArray(data.openKeys)) {{
                    return;
                  }}
                  openEntryKeys = new Set(data.openKeys.map((key) => String(key)));
                  hasCapturedOpenState = true;
                }} catch (error) {{
                  console.warn("failed to load world book open state", error);
                }}
              }}

              function persistOpenState() {{
                try {{
                  localStorage.setItem(
                    openStateStorageKey,
                    JSON.stringify({{ openKeys: Array.from(openEntryKeys) }})
                  );
                }} catch (error) {{
                  console.warn("failed to save world book open state", error);
                }}
              }}

              function renderEntries() {{
                entriesEl.innerHTML = "";
                state.entries.forEach((entry, index) => {{
                  const normalized = normalizeEntry(entry, index);
                  const summaryTitle = normalized.title || normalized.id || `条目 ${{index + 1}}`;
                  const entryKey = entryDomKey(normalized, index);
                  const isOpen = hasCapturedOpenState && openEntryKeys.has(entryKey);
                  const card = document.createElement("section");
                  card.className = "world-entry";
                  card.dataset.entryKey = entryKey;
                  card.innerHTML = `
                    <details${{isOpen ? " open" : ""}}>
                      <summary class="world-entry-head">
                        <button class="drag-handle" type="button" data-action="drag" draggable="true" title="拖动排序" aria-label="拖动排序">☰</button>
                        <span class="entry-title">${{escapeHtml(summaryTitle)}}</span>
                        <label class="summary-check"><input data-field="enabled" type="checkbox"${{normalized.enabled ? " checked" : ""}}> 启用</label>
                        <label class="summary-check"><input data-field="recursive" type="checkbox"${{normalized.recursive ? " checked" : ""}}> 允许递归</label>
                        <button class="danger" type="button" data-action="delete">删除</button>
                      </summary>
                      <div class="world-entry-body">
                        <div class="world-entry-grid">
                          <label class="compact-field"><span>ID</span><input data-field="id" type="text" value="${{escapeAttr(normalized.id)}}"></label>
                          <label class="compact-field"><span>标题</span><input data-field="title" type="text" value="${{escapeAttr(normalized.title)}}"></label>
                          <label class="compact-field"><span>顺序</span><input data-field="order" type="number" step="1" value="${{normalized.order}}"></label>
                          <label class="compact-field"><span>触发方式</span>
                            <select data-field="strategy">
                              <option value="keyword"${{normalized.strategy === "keyword" ? " selected" : ""}}>关键词命中</option>
                              <option value="always"${{normalized.strategy === "always" ? " selected" : ""}}>总是注入</option>
                            </select>
                          </label>
                        </div>
                        <label class="block-field">关键词（支持中文逗号、英文逗号或换行分隔；触发方式为“总是注入”时可留空）
                          <textarea data-field="keys" class="keys-editor" spellcheck="false">${{escapeHtml(normalized.keys.join("\\n"))}}</textarea>
                        </label>
                        <label class="block-field">设定内容
                          <textarea data-field="content" class="entry-content-editor" spellcheck="false">${{escapeHtml(normalized.content)}}</textarea>
                        </label>
                      </div>
                    </details>
                  `;
                  const detailsEl = card.querySelector("details");
                  detailsEl.addEventListener("toggle", () => {{
                    if (detailsEl.open) {{
                      openEntryKeys.add(entryKey);
                    }} else {{
                      openEntryKeys.delete(entryKey);
                    }}
                    hasCapturedOpenState = true;
                    persistOpenState();
                  }});
                  card.querySelector(".summary-check").addEventListener("click", (event) => {{
                    event.stopPropagation();
                  }});
                  const dragHandle = card.querySelector("[data-action='drag']");
                  dragHandle.addEventListener("click", (event) => {{
                    event.preventDefault();
                    event.stopPropagation();
                  }});
                  dragHandle.addEventListener("dragstart", (event) => {{
                    syncFromDom();
                    draggingIndex = index;
                    card.classList.add("dragging");
                    event.dataTransfer.effectAllowed = "move";
                    event.dataTransfer.setData("text/plain", String(index));
                  }});
                  dragHandle.addEventListener("dragend", () => {{
                    draggingIndex = null;
                    card.classList.remove("dragging");
                    entriesEl.querySelectorAll(".drag-over").forEach((item) => item.classList.remove("drag-over"));
                  }});
                  card.addEventListener("dragover", (event) => {{
                    if (draggingIndex === null || draggingIndex === index) {{
                      return;
                    }}
                    event.preventDefault();
                    event.dataTransfer.dropEffect = "move";
                    card.classList.add("drag-over");
                  }});
                  card.addEventListener("dragleave", () => {{
                    card.classList.remove("drag-over");
                  }});
                  card.addEventListener("drop", (event) => {{
                    event.preventDefault();
                    card.classList.remove("drag-over");
                    if (draggingIndex === null || draggingIndex === index) {{
                      return;
                    }}
                    reorderEntries(draggingIndex, index);
                    draggingIndex = null;
                  }});
                  card.querySelector("[data-action='delete']").addEventListener("click", (event) => {{
                    event.preventDefault();
                    event.stopPropagation();
                    if (!confirm("确定删除这个世界书条目？")) {{
                      return;
                    }}
                    captureOpenState();
                    syncFromDom();
                    state.entries.splice(index, 1);
                    openEntryKeys.delete(entryKey);
                    persistOpenState();
                    renderEntries();
                  }});
                  const titleInput = card.querySelector("[data-field='title']");
                  const idInput = card.querySelector("[data-field='id']");
                  const titleEl = card.querySelector(".entry-title");
                  const refreshSummaryTitle = () => {{
                    titleEl.textContent = titleInput.value.trim() || idInput.value.trim() || `条目 ${{index + 1}}`;
                  }};
                  titleInput.addEventListener("input", refreshSummaryTitle);
                  idInput.addEventListener("input", refreshSummaryTitle);
                  entriesEl.appendChild(card);
                }});
              }}

              function reorderEntries(fromIndex, toIndex) {{
                captureOpenState();
                syncFromDom();
                const nextEntries = [...state.entries];
                const [moved] = nextEntries.splice(fromIndex, 1);
                nextEntries.splice(toIndex, 0, moved);
                state.entries = nextEntries.map((entry, index) => ({{
                  ...entry,
                  order: (index + 1) * 100,
                }}));
                renderEntries();
              }}

              function escapeHtml(value) {{
                return String(value)
                  .replace(/&/g, "&amp;")
                  .replace(/</g, "&lt;")
                  .replace(/>/g, "&gt;");
              }}

              function escapeAttr(value) {{
                return escapeHtml(value)
                  .replace(/"/g, "&quot;")
                  .replace(/'/g, "&#39;");
              }}

              addEntryButton.addEventListener("click", () => {{
                captureOpenState();
                syncFromDom();
                const newEntry = entryDefaults(state.entries.length);
                state.entries.push(newEntry);
                openEntryKeys.add(entryDomKey(newEntry, state.entries.length - 1));
                persistOpenState();
                renderEntries();
              }});

              form.addEventListener("submit", () => {{
                syncFromDom();
                contentInput.value = JSON.stringify(state, null, 2);
              }});

              state.entries = state.entries.map(normalizeEntry);
              loadOpenState();
              renderEntries();
            </script>
            """,
        )

    async def _editable_save(self, request: web.Request) -> web.Response:
        if not self._is_admin(request):
            return self._forbidden()

        data = await request.post()
        file_id = str(data.get("id", ""))
        category = self._editable_back_category(str(data.get("category", "")), file_id)
        note = str(data.get("note", ""))
        content = str(data.get("content", ""))
        if not self._is_editable_file(file_id):
            raise web.HTTPBadRequest(text="invalid editable file")

        try:
            if file_id == "world_book/default.json":
                json.loads(content)
                self.editable_manager.write_world_book(content)
            elif file_id in {"skill_book/default.json", "status_book/default.json"}:
                self.editable_manager.write_json_book(file_id, content)
            else:
                self.editable_manager.write_text(file_id, content)
            self.editable_manager.write_note(file_id, note)
        except Exception as exc:
            return self._html_response(
                "保存失败",
                f"""
                <h1>保存失败</h1>
                <p class="error">{self._e(exc)}</p>
                <p><a href="{self._url(f'/editable/file?id={quote(file_id, safe="")}&category={self._e(category)}')}">返回编辑</a></p>
                """,
                status=400,
            )

        raise web.HTTPFound(
            self._url(f"/editable/file?id={quote(file_id, safe='')}&category={self._e(category)}")
        )

    @staticmethod
    def _normalize_world_book(raw: object) -> dict:
        book = dict(raw) if isinstance(raw, dict) else {}
        entries = book.get("entries", [])
        if isinstance(entries, dict):
            iterable = entries.items()
        elif isinstance(entries, list):
            iterable = enumerate(entries)
        else:
            iterable = []

        normalized_entries = []
        for fallback_id, entry in iterable:
            if not isinstance(entry, dict):
                continue
            keys = entry.get("keys", [])
            if isinstance(keys, str):
                keys = [keys]
            if not isinstance(keys, list):
                keys = []
            try:
                order = int(entry.get("order", 100))
            except (TypeError, ValueError):
                order = 100
            normalized_entries.append(
                {
                    "id": str(entry.get("id") or fallback_id).strip(),
                    "title": str(entry.get("title") or ""),
                    "enabled": entry.get("enabled", True) is not False,
                    "recursive": entry.get("recursive", True) is not False,
                    "strategy": (
                        "always"
                        if str(entry.get("strategy") or "keyword").strip().lower()
                        == "always"
                        else "keyword"
                    ),
                    "keys": [str(key).strip() for key in keys if str(key).strip()],
                    "order": order,
                    "content": str(entry.get("content") or ""),
                }
            )

        book["version"] = book.get("version", 1)
        if "display_name" in book:
            book["display_name"] = str(book.get("display_name") or "")
        if "base_path" in book:
            book["base_path"] = str(book.get("base_path") or "")
        book["entries"] = normalized_entries
        return book

    @staticmethod
    def _default_book_display_name(file_id: str) -> str:
        if file_id == "skill_book/default.json":
            return "技能&熟练度"
        if file_id == "status_book/default.json":
            return "特殊状态"
        return ""

    @staticmethod
    def _json_script_data(value: object) -> str:
        return (
            json.dumps(value, ensure_ascii=False)
            .replace("</", "<\\/")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )

    async def _editable_reset(self, request: web.Request) -> web.Response:
        if not self._is_admin(request):
            return self._forbidden()

        data = await request.post()
        file_id = str(data.get("id", ""))
        category = self._editable_back_category(str(data.get("category", "")), file_id)
        if not self._is_editable_file(file_id):
            raise web.HTTPBadRequest(text="invalid editable file")

        try:
            self.editable_manager.reset_to_default(file_id)
            self.editable_manager.reset_note_to_default(file_id)
        except Exception as exc:
            return self._html_response(
                "恢复默认失败",
                f"""
                <h1>恢复默认失败</h1>
                <p class="error">{self._e(exc)}</p>
                <p><a href="{self._url(f'/editable/file?id={quote(file_id, safe="")}&category={self._e(category)}')}">返回编辑</a></p>
                """,
                status=400,
            )

        raise web.HTTPFound(
            self._url(f"/editable/file?id={quote(file_id, safe='')}&category={self._e(category)}")
        )

    async def _player_detail(self, request: web.Request) -> web.Response:
        session = self._session(request)
        if not session:
            return self._forbidden()

        group_id = request.query.get("group_id", "")
        user_id = request.query.get("user_id", "")
        is_admin = session["role"] == SESSION_ADMIN_ROLE
        detail = self.repository.read_save_detail(group_id, user_id)
        if detail is None:
            raise web.HTTPNotFound(text="save not found")

        profile = detail.get("profile", {})
        state = detail.get("state", {})
        logs = detail.get("logs", [])
        cameo_memories = detail.get("cameo_memories", [])
        card = profile.get("card", {}) if isinstance(profile, dict) else {}
        title_name = card.get("target_name") or profile.get("nickname") or user_id
        summary = self._player_summary_html(group_id, user_id, profile, state, card)
        log_cards = self._player_log_cards(group_id, user_id, logs, allow_delete=is_admin)
        cameo_cards = self._player_cameo_memory_cards(cameo_memories)
        progress_overview = self._progress_overview_html(state)
        state_overview = self._state_overview_html(state)
        log_note = (
            "删除单条记录只会移除 adventure_log.jsonl 中对应一行，不会回滚当前 state。"
            if is_admin
            else "这里展示该存档最近的冒险记录。"
        )
        danger_zone = (
            f"""
            <form class="danger-zone" method="post" action="{self._url('/player/delete')}" onsubmit="return confirm('确定删除这个玩家存档？此操作不可恢复。');">
              <input type="hidden" name="group_id" value="{self._e(group_id)}">
              <input type="hidden" name="user_id" value="{self._e(user_id)}">
              <strong>危险操作</strong>
              <span>删除该玩家的 profile、state 和 adventure_log。</span>
              <button class="danger" type="submit">删除玩家存档</button>
            </form>
            """
            if is_admin
            else ""
        )

        return self._html_response(
            f"玩家存档 - {title_name}",
            f"""
            <h1>{self._e(title_name)}</h1>
            <p class="nav-actions">
              <a class="button-link secondary-link" href="{self._url('/')}">返回列表</a>
            </p>
            {summary}
            {progress_overview}
            <section class="detail-panel">
              <div class="section-head">
                <div>
                  <h2>冒险记录</h2>
                  <p class="muted">{self._e(log_note)}</p>
                </div>
              </div>
              <div class="log-list">{log_cards}</div>
            </section>
            <section class="detail-panel">
              <div class="section-head">
                <div>
                  <h2>其他人与主角的交互</h2>
                  <p class="muted">这里展示其他玩家日记里明确提到该角色的遭遇和结算。</p>
                </div>
              </div>
              <div class="log-list">{cameo_cards}</div>
            </section>
            <section class="detail-grid raw-grid">
              <details class="raw-panel">
                <summary>查看 profile.json</summary>
                <pre>{self._e_json(profile)}</pre>
              </details>
              <details class="raw-panel">
                <summary>查看 state.json</summary>
                <pre>{self._e_json(state)}</pre>
              </details>
            </section>
            {state_overview}
            {danger_zone}
            """,
        )

    def _player_summary_html(
        self,
        group_id: str,
        user_id: str,
        profile: dict[str, Any],
        state: dict[str, Any],
        card: dict[str, Any],
    ) -> str:
        avatar_url = card.get("avatar_url") or ""
        avatar_html = (
            f"<img src=\"{self._e(avatar_url)}\" alt=\"avatar\">"
            if avatar_url
            else "<span>転</span>"
        )
        stats = card.get("stats") if isinstance(card.get("stats"), dict) else {}
        stat_items = "".join(
            f"<div class=\"stat-pill\"><span>{self._e(key)}</span><strong>{self._e(value)}</strong></div>"
            for key, value in stats.items()
        ) or "<div class=\"stat-pill\"><span>四维</span><strong>未记录</strong></div>"
        likes = card.get("likes") if isinstance(card.get("likes"), list) else []
        like_items = "".join(
            f"<span class=\"tag\">{self._e(item)}</span>"
            for item in likes[:8]
        )
        created_at = self._format_time(profile.get("created_at"))
        updated_at = self._format_time(state.get("updated_at") or profile.get("updated_at"))
        return f"""
            <section class="hero-card">
              <div class="avatar-large">{avatar_html}</div>
              <div class="hero-main">
                <div class="kicker">群 {self._e(group_id)} / 用户 {self._e(user_id)}</div>
                <h2>{self._e(card.get("title") or "异世界转生人物卡")}</h2>
                <p class="subtitle">{self._e(card.get("subtitle") or "")}</p>
                <div class="identity-line">
                  <span>{self._e(level_display(state))}</span>
                  <span>等级经验 {self._e(level_exp_percent(state))}%</span>
                  <span>{self._e(card.get("race") or "未知种族")}</span>
                  <span>{self._e(card.get("class_name") or "未知职阶")}</span>
                  <span>{self._e(state.get("region") or "未知区域")}</span>
                  <span>{self._e(state.get("location") or "未知地点")}</span>
                </div>
              </div>
            </section>
            <section class="detail-grid">
              <article class="detail-panel">
                <h2>角色档案</h2>
                {self._profile_field("外貌", card.get("appearance"))}
                {self._profile_field("性格", card.get("personality"))}
                {self._profile_field("天赋", card.get("talent"))}
                {self._profile_field("初醒之地", card.get("birth_description"))}
                {self._profile_field("台词", card.get("quote"))}
              </article>
              <article class="detail-panel">
                <h2>当前状态</h2>
                <div class="stats-grid">{stat_items}</div>
                <div class="tag-row">{like_items}</div>
                <div class="meta-list">
                  <div><span>HP</span><strong>{self._e(state.get("hp", 100))}</strong></div>
                  <div><span>MP</span><strong>{self._e(state.get("mp", 100))}</strong></div>
                  <div><span>金币</span><strong>{self._e(state.get("gold", 0))}</strong></div>
                  <div><span>等级经验</span><strong>{self._e(level_exp_percent(state))}%</strong></div>
                  <div><span>创建</span><strong>{self._e(created_at)}</strong></div>
                  <div><span>更新</span><strong>{self._e(updated_at)}</strong></div>
                </div>
              </article>
            </section>
        """

    def _profile_field(self, label: str, value: object) -> str:
        return f"""
            <div class="profile-field">
              <span>{self._e(label)}</span>
              <p>{self._e(value or "未记录")}</p>
            </div>
        """

    def _player_log_cards(
        self,
        group_id: str,
        user_id: str,
        logs: list[dict[str, Any]],
        allow_delete: bool = False,
    ) -> str:
        if not logs:
            return "<p class=\"muted empty-state\">还没有冒险记录。</p>"

        cards: list[str] = []
        for display_index, log in enumerate(reversed(logs), start=1):
            log_index = int(log.get("_log_index", -1))
            raw_log_type = str(log.get("type", "log"))
            log_type = self._e(raw_log_type)
            title = self._e(log.get("title") or log.get("message") or "冒险记录")
            action = self._e(log.get("action") or "")
            region = self._e(log.get("region") or "")
            location = self._e(log.get("location") or "")
            level_change = self._e(log.get("level_change") or "")
            diary = self._e(log.get("diary") or "")
            encounter = self._e(log.get("encounter") or "")
            result = self._e(log.get("result") or log.get("message") or "")
            changes = log.get("changes")
            if not isinstance(changes, list):
                changes = log.get("rewards") if isinstance(log.get("rewards"), list) else []
            change_html = "".join(f"<span class=\"tag\">{self._e(item)}</span>" for item in changes)
            created_at = self._format_time(log.get("created_at"))
            region_html = f"<span>{region}</span>" if region else ""
            location_html = f"<span>{location}</span>" if location else ""
            level_html = f"<span>{level_change}</span>" if level_change else ""
            action_html = f"<p class=\"log-action\">{action}</p>" if action else ""
            diary_html = f"<p class=\"log-result\">{diary}</p>" if diary else ""
            encounter_html = (
                f"<p class=\"log-action\">遭遇：{encounter}</p>"
                if encounter
                else ""
            )
            changes_block = (
                f"<div class=\"tag-row\">{change_html}</div>"
                if change_html
                else ""
            )
            delete_button = ""
            if allow_delete and log_index >= 0 and raw_log_type == "adventure_diary":
                delete_button = f"""
                  <form class="inline-form" method="post" action="{self._url('/player/log/delete')}" onsubmit="return confirm('确定删除这条冒险记录？当前 state 不会自动回滚。');">
                    <input type="hidden" name="group_id" value="{self._e(group_id)}">
                    <input type="hidden" name="user_id" value="{self._e(user_id)}">
                    <input type="hidden" name="log_index" value="{log_index}">
                    <button class="danger compact-button" type="submit">删除记录</button>
                  </form>
                """
            cards.append(
                f"""
                <article class="log-card">
                  <div class="log-card-head">
                    <div>
                      <span class="log-index">#{display_index}</span>
                      <h3>{title}</h3>
                    </div>
                    {delete_button}
                  </div>
                  <div class="log-meta">
                    <span>{self._e(created_at)}</span>
                    <span>{log_type}</span>
                    {region_html}
                    {location_html}
                    {level_html}
                  </div>
                  {action_html}
                  {diary_html}
                  {encounter_html}
                  <p class="log-result">{result}</p>
                  {changes_block}
                </article>
                """
            )
        return "\n".join(cards)

    def _player_cameo_memory_cards(self, memories: list[dict[str, Any]]) -> str:
        if not memories:
            return "<p class=\"muted empty-state\">还没有其他人与主角的交互。</p>"

        cards: list[str] = []
        for display_index, memory in enumerate(reversed(memories), start=1):
            title = self._e(memory.get("title") or "其他人与主角的交互")
            source_name = self._e(memory.get("source_target_name") or "未知角色")
            region = self._e(memory.get("region") or "")
            location = self._e(memory.get("location") or "")
            encounter = self._e(memory.get("encounter") or "")
            result = self._e(memory.get("result") or "")
            created_at = self._format_time(memory.get("created_at"))
            region_html = f"<span>{region}</span>" if region else ""
            location_html = f"<span>{location}</span>" if location else ""
            encounter_html = (
                f"<p class=\"log-action\">遭遇：{encounter}</p>"
                if encounter
                else ""
            )
            cards.append(
                f"""
                <article class="log-card cameo-card">
                  <div class="log-card-head">
                    <div>
                      <span class="log-index">#{display_index}</span>
                      <h3>{title}</h3>
                    </div>
                  </div>
                  <div class="log-meta">
                    <span>{self._e(created_at)}</span>
                    <span>来源：{source_name}</span>
                    {region_html}
                    {location_html}
                  </div>
                  {encounter_html}
                  <p class="log-result">{result}</p>
                </article>
                """
            )
        return "\n".join(cards)

    def _progress_overview_html(self, state: dict[str, Any]) -> str:
        sections = build_progress_sections(
            state,
            self.editable_manager.read_book_base_path(
                "skill_book/default.json",
                "/主角/技能/",
            ),
            self.editable_manager.read_book_base_path(
                "status_book/default.json",
                "/主角/快感状态/性癖/",
            ),
            limit=16,
        )
        skill_title = self.editable_manager.read_book_display_name(
            "skill_book/default.json",
            "技能&熟练度",
        )
        status_title = self.editable_manager.read_book_display_name(
            "status_book/default.json",
            "特殊状态",
        )
        return (
            self._progress_panel_html(skill_title, sections.skill_items)
            + self._progress_panel_html(status_title, sections.status_items)
        )

    def _progress_panel_html(self, title: str, items: list[Any]) -> str:
        if not items:
            return f"""
            <section class="detail-panel progress-overview-panel">
              <h2>{self._e(title)}</h2>
              <p class="muted empty-state">暂无可展示的经验进度。</p>
            </section>
            """
        rows = "".join(
            f"""
            <div class="progress-row">
              <div class="progress-head">
                <div class="progress-name">
                  <span>{self._e(item.label)}</span>
                  <span class="progress-level">Lv.{self._e(item.level)}</span>
                </div>
                <div class="progress-xp">{self._e(item.value)} <small>/ 100</small></div>
              </div>
              <div class="progress-track">
                <div class="progress-fill" style="width: {self._e(item.percent)}%;"></div>
              </div>
            </div>
            """
            for item in items
        )
        return f"""
            <section class="detail-panel progress-overview-panel">
              <h2>{self._e(title)}</h2>
              <div class="progress-list">{rows}</div>
            </section>
        """

    def _state_overview_html(self, state: dict[str, Any]) -> str:
        items = build_state_display_items(state, limit=40)
        if not items:
            return ""
        item_html = "".join(
            f"""
            <div class="state-item">
              <span>{self._e(label)}</span>
              <strong>{self._e(value)}</strong>
            </div>
            """
            for label, value in items
        )
        return f"""
            <section class="detail-panel state-overview-panel">
              <h2>完整状态</h2>
              <p class="muted">包含当前 state 中除经验进度外的状态项；原始 JSON 可在上方展开查看。</p>
              <div class="state-overview-grid">{item_html}</div>
            </section>
        """

    async def _player_log_delete(self, request: web.Request) -> web.Response:
        if not self._is_admin(request):
            return self._forbidden()

        data = await request.post()
        group_id = str(data.get("group_id", ""))
        user_id = str(data.get("user_id", ""))
        try:
            log_index = int(data.get("log_index", -1))
        except (TypeError, ValueError):
            log_index = -1
        if not group_id or not user_id or log_index < 0:
            raise web.HTTPBadRequest(text="missing group_id, user_id or log_index")

        self.repository.delete_adventure_log(group_id, user_id, log_index)
        raise web.HTTPFound(
            self._url(f"/player?group_id={self._e(group_id)}&user_id={self._e(user_id)}")
        )

    async def _player_delete(self, request: web.Request) -> web.Response:
        if not self._is_admin(request):
            return self._forbidden()

        data = await request.post()
        group_id = str(data.get("group_id", ""))
        user_id = str(data.get("user_id", ""))
        if not group_id or not user_id:
            raise web.HTTPBadRequest(text="missing group_id or user_id")

        self.repository.delete_player_save(group_id, user_id)
        raise self._redirect("/")

    def _is_authorized(self, request: web.Request) -> bool:
        return self._session(request) is not None

    def _is_admin(self, request: web.Request) -> bool:
        session = self._session(request)
        return bool(session and session["role"] == SESSION_ADMIN_ROLE)

    def _session(self, request: web.Request) -> dict[str, str] | None:
        raw = request.cookies.get(SESSION_COOKIE_NAME, "")
        if not raw or not self.token:
            return None
        parts = raw.split(":")
        if len(parts) == 2 and parts[0] == SESSION_ADMIN_ROLE:
            role, signature = parts
            payload = role
            if hmac.compare_digest(signature, self._session_signature(payload)):
                return {"role": role, "user_id": ""}
            return None
        if len(parts) == 3 and parts[0] == SESSION_USER_ROLE:
            role, user_id, signature = parts
            payload = f"{role}:{user_id}"
            if hmac.compare_digest(signature, self._session_signature(payload)):
                return {"role": role, "user_id": user_id}
        return None

    def _build_session_cookie(self, role: str, user_id: str = "") -> str:
        payload = role if role == SESSION_ADMIN_ROLE else f"{role}:{user_id}"
        return f"{payload}:{self._session_signature(payload)}"

    def _session_signature(self, payload: str) -> str:
        return hmac.new(
            self.token.encode("utf-8"),
            payload.encode("utf-8"),
            "sha256",
        ).hexdigest()

    @staticmethod
    def _safe_session_id(value: object) -> str:
        text = str(value or "unknown").strip()
        text = re.sub(r"[^0-9A-Za-z_.-]+", "_", text)
        return text[:80] or "unknown"

    def _forbidden(self) -> web.Response:
        raise self._redirect("/login")

    def _redirect(self, path: str) -> web.HTTPFound:
        return web.HTTPFound(self._url(path))

    def _url(self, path: str) -> str:
        if not path:
            path = "/"
        if not path.startswith("/"):
            path = "/" + path
        if not self.public_path_prefix:
            return path
        if path == "/":
            return self.public_path_prefix + "/"
        return self.public_path_prefix + path

    def _cookie_path(self) -> str:
        return self.public_path_prefix or "/"

    @staticmethod
    def _normalize_path_prefix(prefix: str) -> str:
        text = str(prefix or "").strip()
        if not text or text == "/":
            return ""
        return "/" + text.strip("/")

    def _html_response(
        self,
        title: str,
        content: str,
        status: int = 200,
        show_logout: bool = True,
    ) -> web.Response:
        logout_html = (
            f"""
            <form class="logout-form" method="post" action="{self._url('/logout')}">
              <button class="secondary compact-button" type="submit">退出</button>
            </form>
            """
            if show_logout
            else ""
        )
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
    body {{ margin: 0; background: linear-gradient(180deg, #f3f6fb 0%, #eef3f8 42%, #f8fafc 100%); color: #20242a; -webkit-font-smoothing: antialiased; }}
    main {{ max-width: 1160px; margin: 0 auto; padding: 30px 20px 52px; }}
    .topbar {{ display: flex; justify-content: flex-end; min-height: 36px; margin-bottom: 8px; }}
    .logout-form {{ margin: 0; }}
    h1 {{ margin: 0 0 12px; font-size: 30px; letter-spacing: 0; }}
    h2 {{ margin: 24px 0 10px; font-size: 18px; }}
    .muted {{ color: #68707d; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #dde2ea; border-radius: 8px; overflow: hidden; box-shadow: 0 10px 24px rgba(31, 41, 55, 0.06); }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e6eaf0; text-align: left; font-size: 14px; }}
    th {{ background: #eef2f6; color: #3a4350; }}
    a {{ color: #1f6feb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .nav-actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 14px 0 18px; }}
    .button-link {{ display: inline-flex; align-items: center; justify-content: center; padding: 9px 16px; border-radius: 6px; background: #1f6feb; color: #fff; font-weight: 700; }}
    .button-link:hover {{ text-decoration: none; background: #1a5fc9; }}
    .secondary-link {{ background: #59636e; }}
    .secondary-link:hover {{ background: #46515d; }}
    .inline-form {{ display: inline; margin: 0; }}
    .compact-button {{ margin: 0; padding: 6px 10px; font-size: 13px; }}
    label {{ display: block; margin: 18px 0 8px; font-weight: 700; color: #303846; }}
    input[type="text"] {{ width: 100%; box-sizing: border-box; padding: 10px 12px; border: 1px solid #c8d0dc; border-radius: 7px; font: inherit; background: #fbfdff; }}
    textarea {{ width: 100%; resize: vertical; padding: 12px; border: 1px solid #c8d0dc; border-radius: 7px; font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size: 13px; line-height: 1.5; box-sizing: border-box; background: #fbfdff; transition: border-color .15s ease, box-shadow .15s ease; }}
    textarea:focus, input:focus, select:focus {{ outline: none; border-color: #1f6feb !important; box-shadow: 0 0 0 3px rgba(31, 111, 235, 0.13); }}
    textarea.note-editor {{ min-height: 132px; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    textarea.content-editor {{ min-height: 58vh; }}
    button {{ margin-top: 12px; padding: 9px 16px; border: 0; border-radius: 6px; background: #1f6feb; color: #fff; font-weight: 700; cursor: pointer; }}
    button.secondary {{ background: #59636e; }}
    button.danger {{ margin-top: 0; background: #b42318; }}
    button.danger:hover {{ background: #931f15; }}
    .actions {{ display: flex; gap: 10px; align-items: center; }}
    .error {{ color: #b42318; font-weight: 700; }}
    .login-panel {{ max-width: 420px; margin: 12vh auto 0; padding: 24px; border: 1px solid #dde2ea; border-radius: 8px; background: #fff; box-shadow: 0 10px 24px rgba(31, 41, 55, 0.06); }}
    .danger-zone {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 16px 0 22px; padding: 14px 16px; border: 1px solid #f0b8b0; border-radius: 8px; background: #fff5f3; color: #6f1d15; }}
    .danger-zone span {{ color: #7a3b34; }}
    .world-book-toolbar {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin: 16px 0 8px; padding: 10px 12px; border: 1px solid #d9e1eb; border-radius: 8px; background: rgba(255,255,255,0.86); box-shadow: 0 6px 14px rgba(31, 41, 55, 0.05); }}
    .world-book-toolbar h2 {{ margin: 0 0 3px; }}
    .world-book-toolbar p {{ margin: 0; }}
    .book-config-grid {{ display: grid; grid-template-columns: minmax(180px, .72fr) minmax(260px, 1.28fr); gap: 12px; align-items: start; }}
    #world-book-entries {{ display: grid; gap: 6px; }}
    .world-entry {{ margin: 0; background: #fff; border: 1px solid #dde2ea; border-radius: 8px; box-shadow: 0 3px 10px rgba(31, 41, 55, 0.04); transition: transform .14s ease, box-shadow .14s ease, border-color .14s ease, opacity .14s ease; }}
    .world-entry.dragging {{ opacity: .45; transform: scale(.995); }}
    .world-entry.drag-over {{ border-color: #1f6feb; box-shadow: 0 0 0 3px rgba(31, 111, 235, 0.14), 0 12px 28px rgba(31, 41, 55, 0.1); }}
    .world-entry details {{ padding: 0; }}
    .world-entry-head {{ display: flex; gap: 8px; align-items: center; padding: 7px 10px; cursor: pointer; background: linear-gradient(180deg, #f8fafc, #eef4fa); border-radius: 8px; }}
    .world-entry details[open] .world-entry-head {{ border-bottom: 1px solid #dde2ea; border-radius: 8px 8px 0 0; }}
    .world-entry-head .entry-title {{ font-weight: 800; margin-right: auto; color: #172033; }}
    .drag-handle {{ flex: 0 0 auto; width: 26px; height: 26px; margin: 0; padding: 0; border-radius: 6px; border: 1px solid #c8d0dc; background: #fff; color: #536172; cursor: grab; font-size: 15px; line-height: 1; }}
    .drag-handle:active {{ cursor: grabbing; }}
    .summary-check {{ display: inline-flex; align-items: center; gap: 5px; margin: 0; font-size: 13px; font-weight: 700; cursor: default; }}
    .summary-check input {{ width: 15px; height: 15px; }}
    .world-entry-body {{ padding: 10px; background: #fff; border-radius: 0 0 8px 8px; }}
    .world-entry-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }}
    .compact-field {{ display: flex; align-items: center; gap: 6px; margin: 0; }}
    .compact-field span {{ flex: 0 0 auto; color: #3a4350; }}
    .world-entry input[type="text"], .world-entry input[type="number"], .world-entry select {{ width: 100%; min-width: 0; box-sizing: border-box; padding: 6px 8px; border: 1px solid #c8d0dc; border-radius: 7px; font: inherit; background: #fbfdff; }}
    .block-field {{ margin-top: 12px; }}
    textarea.keys-editor {{ min-height: 48px; font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
    textarea.entry-content-editor {{ min-height: 78px; }}
    .hero-card {{ display: flex; gap: 20px; align-items: center; margin: 18px 0 18px; padding: 20px; border: 1px solid #d9e1eb; border-radius: 8px; background: #fff; box-shadow: 0 10px 24px rgba(31, 41, 55, 0.06); }}
    .avatar-large {{ width: 92px; height: 92px; flex: 0 0 auto; display: grid; place-items: center; overflow: hidden; border-radius: 8px; border: 1px solid #d8e0eb; background: #f0f4f8; color: #59636e; font-size: 34px; font-weight: 900; }}
    .avatar-large img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
    .hero-main h2 {{ margin: 4px 0 6px; font-size: 22px; }}
    .kicker {{ color: #68707d; font-size: 13px; }}
    .subtitle {{ margin: 0 0 12px; color: #3a4350; }}
    .identity-line {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .identity-line span, .tag {{ display: inline-flex; align-items: center; min-height: 26px; padding: 3px 9px; border-radius: 6px; background: #eef4fa; border: 1px solid #d8e0eb; color: #263241; font-size: 13px; font-weight: 700; }}
    .detail-grid {{ display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(320px, .85fr); gap: 16px; margin: 16px 0; }}
    .detail-panel, .raw-panel, .log-card {{ border: 1px solid #dde2ea; border-radius: 8px; background: #fff; box-shadow: 0 8px 22px rgba(31, 41, 55, 0.05); }}
    .detail-panel {{ padding: 18px; }}
    .detail-panel h2 {{ margin-top: 0; }}
    .profile-field {{ padding: 12px 0; border-top: 1px solid #edf1f5; }}
    .profile-field:first-of-type {{ border-top: 0; }}
    .profile-field span {{ display: block; margin-bottom: 5px; color: #68707d; font-size: 13px; font-weight: 800; }}
    .profile-field p {{ margin: 0; line-height: 1.7; }}
    .stats-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .stat-pill {{ padding: 12px; border-radius: 8px; background: #f7fafc; border: 1px solid #dde2ea; }}
    .stat-pill span, .meta-list span {{ display: block; color: #68707d; font-size: 12px; font-weight: 800; }}
    .stat-pill strong {{ display: block; margin-top: 3px; font-size: 22px; color: #172033; }}
    .tag-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }}
    .meta-list {{ display: grid; gap: 8px; margin-top: 16px; }}
    .meta-list div {{ display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-top: 1px solid #edf1f5; }}
    .state-overview-panel {{ margin-top: 16px; }}
    .state-overview-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }}
    .state-item {{ min-height: 64px; padding: 11px 12px; border: 1px solid #dde2ea; border-radius: 8px; background: #f8fafc; }}
    .state-item span {{ display: block; color: #68707d; font-size: 12px; font-weight: 800; overflow-wrap: anywhere; }}
    .state-item strong {{ display: block; margin-top: 4px; color: #172033; font-size: 17px; overflow-wrap: anywhere; }}
    .progress-overview-panel {{ margin: 16px 0; }}
    .progress-overview-panel h2 {{ color: #172033; }}
    .progress-list {{ display: grid; gap: 15px; }}
    .progress-row {{ min-width: 0; }}
    .progress-head {{ display: grid; grid-template-columns: 1fr auto; gap: 14px; align-items: baseline; margin-bottom: 7px; }}
    .progress-name {{ display: flex; align-items: baseline; gap: 9px; min-width: 0; color: #172033; font-size: 18px; font-weight: 900; overflow-wrap: anywhere; }}
    .progress-name::before {{ content: ""; width: 16px; height: 16px; flex: 0 0 auto; border: 3px solid #c8d0dc; border-top-color: #1f6feb; border-radius: 50%; }}
    .progress-level {{ color: #68707d; font-size: 12px; font-weight: 800; white-space: nowrap; }}
    .progress-xp {{ color: #1f6feb; font-size: 15px; font-weight: 900; white-space: nowrap; }}
    .progress-xp small {{ color: #68707d; font-size: 12px; }}
    .progress-track {{ width: 100%; height: 7px; overflow: hidden; background: #e7edf5; border-radius: 999px; }}
    .progress-fill {{ height: 100%; border-radius: inherit; background: #1f6feb; box-shadow: 0 0 8px rgba(31, 111, 235, 0.22); }}
    .section-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }}
    .section-head h2 {{ margin-bottom: 4px; }}
    .log-list {{ display: grid; gap: 12px; }}
    .log-card {{ padding: 15px; }}
    .log-card-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }}
    .log-card h3 {{ margin: 2px 0 0; font-size: 17px; }}
    .log-index {{ color: #68707d; font-size: 12px; font-weight: 800; }}
    .log-meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; color: #59636e; font-size: 13px; }}
    .log-meta span {{ padding: 3px 8px; border-radius: 6px; background: #f3f6fb; border: 1px solid #e1e7ef; }}
    .log-action {{ margin: 10px 0 6px; color: #303846; font-weight: 700; }}
    .log-result {{ margin: 0; line-height: 1.7; color: #263241; }}
    .raw-grid {{ grid-template-columns: 1fr 1fr; }}
    .raw-panel {{ padding: 0; overflow: hidden; }}
    .raw-panel summary {{ padding: 13px 15px; cursor: pointer; font-weight: 800; background: #f8fafc; }}
    .raw-panel pre {{ margin: 0; border-radius: 0; }}
    .empty-state {{ padding: 18px; background: #fff; border: 1px dashed #c8d0dc; border-radius: 8px; }}
    @media (max-width: 900px) {{ .world-entry-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media (max-width: 900px) {{ .state-overview-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media (max-width: 900px) {{ .detail-grid, .raw-grid {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 560px) {{ .state-overview-grid {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 720px) {{ .world-entry-grid, .book-config-grid {{ grid-template-columns: 1fr; }} .world-book-toolbar {{ flex-direction: column; }} .world-entry-head {{ flex-wrap: wrap; }} .hero-card {{ align-items: flex-start; }} .log-card-head {{ flex-direction: column; }} }}
    pre {{ overflow: auto; padding: 14px; background: #111827; color: #d1e7dd; border-radius: 6px; line-height: 1.45; }}
  </style>
</head>
<body><main><div class="topbar">{logout_html}</div>{content}</main></body>
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

    @staticmethod
    def _is_structured_book_file(file_id: str) -> bool:
        return file_id in {
            "world_book/default.json",
            "skill_book/default.json",
            "status_book/default.json",
        }

    def _editable_rows(self, items: list[dict[str, str]], category: str) -> list[str]:
        rows = []
        for item in items:
            item_category = item.get("category") or "other"
            if item_category not in {"world_background", "text_completion"}:
                item_category = "other"
            if item_category != category:
                continue

            raw_file_id = item["id"]
            file_id = self._e(raw_file_id)
            label = self._e(item["label"])
            file_type = self._e(item["type"])
            note_preview = self._e(item.get("note_preview", ""))
            href = self._url(f"/editable/file?id={quote(raw_file_id, safe='')}")
            rows.append(
                "<tr>"
                f"<td><a href=\"{href}\">{label}</a></td>"
                f"<td>{file_id}</td>"
                f"<td>{file_type}</td>"
                f"<td>{note_preview}</td>"
                "</tr>"
            )
        return rows

    def _editable_table(
        self,
        description: str,
        rows: list[str],
    ) -> str:
        body = "".join(rows) or "<tr><td colspan=\"4\">没有可编辑资源。</td></tr>"
        return f"""
              <p class="muted">{self._e(description)}</p>
              <table>
                <thead><tr><th>名称</th><th>文件</th><th>类型</th><th>说明</th></tr></thead>
                <tbody>{body}</tbody>
              </table>
        """

    def _editable_file_meta(self, file_id: str) -> dict[str, str] | None:
        for item in self.editable_manager.list_editable_files():
            if item["id"] == file_id:
                return item
        return None

    def _editable_back_category(self, category: str | None, file_id: str) -> str:
        if category in {"world_background", "text_completion"}:
            return str(category)
        meta = self._editable_file_meta(file_id)
        if meta and meta.get("category") in {"world_background", "text_completion"}:
            return str(meta["category"])
        return "world_background"

    @staticmethod
    def _editable_category_title(category: str) -> str:
        if category == "text_completion":
            return "文本补全"
        return "世界背景"
