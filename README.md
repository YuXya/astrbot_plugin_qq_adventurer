# QQ Adventurer

QQ Adventurer 是一个 AstrBot 插件示例，用于把一次命令触发的互动冒险生成流程跑通：

```text
群聊命令 -> LLM 生成标准 JSON -> 解析为领域对象 -> HTML 模板渲染 -> HTML 转图片 -> 发送图片卡片
```

当前版本优先复刻 `astrbot_plugin_qq_group_daily_analysis` 的分层代码组织方式，但只实现冒险卡片所需的最小功能。

## 功能

- `/冒险 [主题或行动]`：生成一张互动冒险图片卡片。
- `/adventure [theme]`：英文别名。
- 支持 `use_mock_data` 静态假数据模式，用于先测试 HTML 转图片和发图链路。
- 支持 LLM Provider 回退：插件配置 Provider -> 当前会话 Provider -> 第一个可用 Provider。
- 支持两轮 T2I 渲染参数：第一轮质量优先，第二轮回退。

## 目录结构

```text
astrbot_plugin_qq_adventurer/
├── main.py
├── metadata.yaml
├── _conf_schema.json
├── requirements.txt
└── src/
    ├── application/
    │   └── services/adventure_application_service.py
    ├── domain/
    │   ├── models/data_models.py
    │   ├── repositories/
    │   └── services/adventure_domain_service.py
    ├── infrastructure/
    │   ├── analysis/
    │   ├── config/
    │   ├── messaging/
    │   └── reporting/
    ├── shared/
    └── utils/
```

职责分工：

- `main.py`：AstrBot 插件入口、命令注册、事件信息读取、调用应用服务。
- `application`：编排一次冒险卡片生成流程。
- `domain`：定义卡片数据模型、接口和纯业务规则。
- `infrastructure/analysis`：构建 prompt、调用 LLM、解析 JSON。
- `infrastructure/reporting`：渲染 HTML，并调用 AstrBot `html_render` 转图片。
- `infrastructure/messaging`：发送图片，失败时文本兜底。

## 运行流程

用户在群聊中发送：

```text
/冒险 森林入口
```

插件流程：

1. `main.py` 的 `adventure()` 被触发。
2. 调用 `event.should_call_llm(True)`，阻止 AstrBot 默认 LLM 闲聊回复。
3. `AdventureApplicationService.execute_adventure()` 接管流程。
4. `AdventureAnalyzer.build_prompt()` 生成给 LLM 的提示词。
5. LLM 返回 JSON 文本。
6. `json_utils.parse_json_object_response()` 提取并解析 JSON。
7. `AdventureDomainService.normalize_card()` 补默认值并裁剪字段长度。
8. `ReportGenerator.generate_image_card()` 渲染 `card.html`。
9. 调用 `self.html_render(html_content, {}, False, image_options)` 转图片。
10. `MessageSender.send_image_or_text()` 发送图片；失败则发送文本版卡片。

## LLM 输出格式

当前 prompt 要求 LLM 只返回一个 JSON 对象：

```json
{
  "title": "卡片标题",
  "subtitle": "一句副标题",
  "scene": "当前场景描述，120 到 220 字",
  "choices": [
    {
      "label": "A",
      "text": "行动选项",
      "risk": "低"
    },
    {
      "label": "B",
      "text": "行动选项",
      "risk": "中"
    }
  ],
  "status": {
    "体力": "10/10",
    "线索": "无"
  },
  "footer": "一句结尾提示"
}
```

当前版本使用以下方式提高稳定性：

- prompt 明确要求“只输出合法 JSON，不要 Markdown，不要解释”。
- 解析前会移除 ```json 代码块标记。
- 会从回复中提取第一个 `{ ... }` JSON 对象。
- 使用 `json.loads()` 校验格式。
- 字段缺失时由领域服务补默认值。

注意：当前版本还没有接入原项目那种 `response_format/json_schema` 强约束，因此 LLM 仍有可能输出坏 JSON。若出现解析失败，插件会返回文本错误，不会让命令静默失败。

## 配置项

配置文件：`_conf_schema.json`

### LLM

- `llm.llm_provider_id`：指定 LLM Provider ID，留空时使用回退策略。
- `llm.llm_retries`：LLM 调用重试次数。
- `llm.llm_backoff`：LLM 重试退避秒数。

### 冒险卡片

- `adventure.default_theme`：未传主题时使用的默认主题。
- `adventure.max_choices`：生成选项数量上限，范围 2 到 4。
- `adventure.debug_mode`：开启后保存 prompt 和 LLM 原始响应。
- `adventure.use_mock_data`：开启后不调用 LLM，使用静态假数据。

### HTML 转图片

- `t2i_rendering.t2i_r1_*`：第一轮渲染参数，默认 PNG、高质量。
- `t2i_rendering.t2i_r2_*`：第二轮回退参数，默认 JPEG、较低压力。
- `performance.max_concurrent_t2i`：限制同时进行的 T2I 渲染数量。

## 测试

推荐按下面顺序测试。

### 1. 静态卡片链路

在插件配置中开启：

```text
adventure.use_mock_data = true
```

然后在 QQ 群发送：

```text
/冒险 测试
```

预期：

- 机器人先回复“正在展开冒险卡片...”
- 随后发送一张冒险图片卡片
- 此阶段不依赖 LLM，只验证命令、HTML 渲染、T2I、发图链路

### 2. LLM JSON 链路

关闭：

```text
adventure.use_mock_data = false
```

发送：

```text
/冒险 森林入口
```

预期：

- LLM 返回符合格式的 JSON
- 插件解析为 `AdventureCard`
- 成功生成图片卡片

### 3. 调试 LLM 输出

开启：

```text
adventure.debug_mode = true
```

再次发送 `/冒险 测试`。

预期：

- 插件数据目录下生成 `debug_data/adventure_prompt.txt`
- 插件数据目录下生成 `debug_data/adventure_response.txt`
- 可用这两个文件检查 LLM 实际收到了什么、返回了什么

### 4. 本地语法检查

在插件目录运行：

```powershell
python -m compileall .
python -c "import json; json.load(open('_conf_schema.json', encoding='utf-8')); print('json ok')"
```

预期：

- Python 文件能正常编译
- `_conf_schema.json` 能正常解析

## 下一步

为了更接近原项目的可靠性，后续建议补上：

- 把冒险 prompt 从代码移动到 `_conf_schema.json`，支持面板编辑。
- 增加 `structured_output_schema.py`。
- 调用 LLM 时传 `response_format=json_schema`。
- 解析失败后增加一次“只修复 JSON”的重试。

