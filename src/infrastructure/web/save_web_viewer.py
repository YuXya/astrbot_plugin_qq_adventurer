from __future__ import annotations

import html
import json
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
            <p class="nav-actions">
              <a class="button-link" href="/editable?category=world_background&token={self._e(self.token)}">编辑世界背景</a>
              <a class="button-link" href="/editable?category=text_completion&token={self._e(self.token)}">编辑文本补全</a>
            </p>
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
            <p><a href="/?token={self._e(self.token)}">返回存档列表</a></p>
            <p class="muted">保存时会自动备份旧文件。世界书 default.json 会先做 JSON 校验。</p>
            {self._editable_table(description, rows)}
            """,
        )

    async def _editable_file(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
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
        if file_id == "world_book/default.json":
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
            <p><a href="/editable?category={self._e(back_category)}&token={self._e(self.token)}">返回{self._e(self._editable_category_title(back_category))}</a></p>
            <p class="muted">{self._e(file_id)}</p>
            {warning_html}
            <form method="post" action="/editable/save?token={self._e(self.token)}">
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
            <form method="post" action="/editable/reset?token={self._e(self.token)}" onsubmit="return confirm('确定恢复为当前代码内置默认内容？旧文件会先自动备份。');">
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
        return self._html_response(
            title,
            f"""
            <h1>{self._e(title)}</h1>
            <p><a href="/editable?category={self._e(back_category)}&token={self._e(self.token)}">返回{self._e(self._editable_category_title(back_category))}</a></p>
            <p class="muted">{self._e(file_id)}</p>
            <form id="world-book-form" method="post" action="/editable/save?token={self._e(self.token)}">
              <input type="hidden" name="id" value="{self._e(file_id)}">
              <input type="hidden" name="category" value="{self._e(back_category)}">
              <input id="world-book-content" type="hidden" name="content" value="">
              <label for="note">资源说明 / 注释</label>
              <textarea id="note" class="note-editor" name="note" spellcheck="false">{self._e(note)}</textarea>

              <div class="world-book-toolbar">
                <div>
                  <h2>世界书条目</h2>
                  <p class="muted">每个条目会在命中后作为世界背景补充注入 Prompt。</p>
                </div>
                <button id="add-entry" type="button">+ 添加条目</button>
              </div>
              <div id="world-book-entries"></div>
              <div class="actions">
                <button type="submit">保存</button>
              </div>
            </form>
            <form method="post" action="/editable/reset?token={self._e(self.token)}" onsubmit="return confirm('确定恢复为当前代码内置默认内容？旧文件会先自动备份。');">
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
              let draggingIndex = null;
              let openEntryKeys = new Set();
              let hasCapturedOpenState = false;

              const state = {{
                ...initialWorldBook,
                entries: Array.isArray(initialWorldBook.entries) ? initialWorldBook.entries : [],
              }};

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
              }}

              function renderEntries() {{
                entriesEl.innerHTML = "";
                state.entries.forEach((entry, index) => {{
                  const normalized = normalizeEntry(entry, index);
                  const summaryTitle = normalized.title || normalized.id || `条目 ${{index + 1}}`;
                  const entryKey = entryDomKey(normalized, index);
                  const isOpen = !hasCapturedOpenState || openEntryKeys.has(entryKey);
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
                renderEntries();
              }});

              form.addEventListener("submit", () => {{
                syncFromDom();
                contentInput.value = JSON.stringify(state, null, 2);
              }});

              state.entries = state.entries.map(normalizeEntry);
              renderEntries();
            </script>
            """,
        )

    async def _editable_save(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
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
            else:
                self.editable_manager.write_text(file_id, content)
            self.editable_manager.write_note(file_id, note)
        except Exception as exc:
            return self._html_response(
                "保存失败",
                f"""
                <h1>保存失败</h1>
                <p class="error">{self._e(exc)}</p>
                <p><a href="/editable/file?id={quote(file_id, safe='')}&category={self._e(category)}&token={self._e(self.token)}">返回编辑</a></p>
                """,
                status=400,
            )

        raise web.HTTPFound(
            f"/editable/file?id={quote(file_id, safe='')}&category={self._e(category)}&token={self._e(self.token)}"
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
        book["entries"] = normalized_entries
        return book

    @staticmethod
    def _json_script_data(value: object) -> str:
        return (
            json.dumps(value, ensure_ascii=False)
            .replace("</", "<\\/")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )

    async def _editable_reset(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
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
                <p><a href="/editable/file?id={quote(file_id, safe='')}&category={self._e(category)}&token={self._e(self.token)}">返回编辑</a></p>
                """,
                status=400,
            )

        raise web.HTTPFound(
            f"/editable/file?id={quote(file_id, safe='')}&category={self._e(category)}&token={self._e(self.token)}"
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
    body {{ margin: 0; background: linear-gradient(180deg, #f3f6fb 0%, #eef3f8 42%, #f8fafc 100%); color: #20242a; -webkit-font-smoothing: antialiased; }}
    main {{ max-width: 1160px; margin: 0 auto; padding: 30px 20px 52px; }}
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
    label {{ display: block; margin: 18px 0 8px; font-weight: 700; color: #303846; }}
    textarea {{ width: 100%; resize: vertical; padding: 12px; border: 1px solid #c8d0dc; border-radius: 7px; font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size: 13px; line-height: 1.5; box-sizing: border-box; background: #fbfdff; transition: border-color .15s ease, box-shadow .15s ease; }}
    textarea:focus, input:focus, select:focus {{ outline: none; border-color: #1f6feb !important; box-shadow: 0 0 0 3px rgba(31, 111, 235, 0.13); }}
    textarea.note-editor {{ min-height: 132px; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    textarea.content-editor {{ min-height: 58vh; }}
    button {{ margin-top: 12px; padding: 9px 16px; border: 0; border-radius: 6px; background: #1f6feb; color: #fff; font-weight: 700; cursor: pointer; }}
    button.secondary {{ background: #59636e; }}
    button.danger {{ margin-top: 0; background: #b42318; }}
    .actions {{ display: flex; gap: 10px; align-items: center; }}
    .error {{ color: #b42318; font-weight: 700; }}
    .world-book-toolbar {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin: 22px 0 12px; padding: 16px 18px; border: 1px solid #d9e1eb; border-radius: 8px; background: rgba(255,255,255,0.86); box-shadow: 0 10px 24px rgba(31, 41, 55, 0.06); }}
    .world-book-toolbar h2 {{ margin-top: 0; }}
    #world-book-entries {{ display: grid; gap: 12px; }}
    .world-entry {{ margin: 0; background: #fff; border: 1px solid #dde2ea; border-radius: 8px; box-shadow: 0 8px 22px rgba(31, 41, 55, 0.06); transition: transform .14s ease, box-shadow .14s ease, border-color .14s ease, opacity .14s ease; }}
    .world-entry.dragging {{ opacity: .45; transform: scale(.995); }}
    .world-entry.drag-over {{ border-color: #1f6feb; box-shadow: 0 0 0 3px rgba(31, 111, 235, 0.14), 0 12px 28px rgba(31, 41, 55, 0.1); }}
    .world-entry details {{ padding: 0; }}
    .world-entry-head {{ display: flex; gap: 12px; align-items: center; padding: 13px 14px; cursor: pointer; background: linear-gradient(180deg, #f8fafc, #eef4fa); border-radius: 8px; }}
    .world-entry details[open] .world-entry-head {{ border-bottom: 1px solid #dde2ea; border-radius: 8px 8px 0 0; }}
    .world-entry-head .entry-title {{ font-weight: 800; margin-right: auto; color: #172033; }}
    .drag-handle {{ flex: 0 0 auto; width: 32px; height: 32px; margin: 0; padding: 0; border-radius: 7px; border: 1px solid #c8d0dc; background: #fff; color: #536172; cursor: grab; font-size: 17px; line-height: 1; }}
    .drag-handle:active {{ cursor: grabbing; }}
    .summary-check {{ display: inline-flex; align-items: center; gap: 6px; margin: 0; font-weight: 700; cursor: default; }}
    .summary-check input {{ width: 18px; height: 18px; }}
    .world-entry-body {{ padding: 16px; background: #fff; border-radius: 0 0 8px 8px; }}
    .world-entry-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }}
    .compact-field {{ display: flex; align-items: center; gap: 8px; margin: 0; }}
    .compact-field span {{ flex: 0 0 auto; color: #3a4350; }}
    .world-entry input[type="text"], .world-entry input[type="number"], .world-entry select {{ width: 100%; min-width: 0; box-sizing: border-box; padding: 8px 9px; border: 1px solid #c8d0dc; border-radius: 7px; font: inherit; background: #fbfdff; }}
    .block-field {{ margin-top: 12px; }}
    textarea.keys-editor {{ min-height: 72px; font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
    textarea.entry-content-editor {{ min-height: 112px; }}
    @media (max-width: 900px) {{ .world-entry-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media (max-width: 720px) {{ .world-entry-grid {{ grid-template-columns: 1fr; }} .world-book-toolbar {{ flex-direction: column; }} .world-entry-head {{ flex-wrap: wrap; }} }}
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
            href = (
                f"/editable/file?id={quote(raw_file_id, safe='')}"
                f"&token={self._e(self.token)}"
            )
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
