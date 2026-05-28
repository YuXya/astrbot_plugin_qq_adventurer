# QQ 异世界转生人物卡

这是一个 AstrBot 插件玩具版，用于跑通：

群聊命令 -> 读取触发者最近发言 -> 获取 QQ 头像 -> 可选头像视觉转述 -> LLM 生成标准 JSON -> HTML 模板渲染 -> HTML 转图片 -> QQ 群发送图片

## 命令

```text
/异世界转生
/异世界冒险 我要到森林里冒险
/开启异世界网页
/关闭异世界网页
```

插件会以发送命令的群友为目标，尽量读取该群友最近的群聊发言，推断性格和表达气质，然后生成一张异世界转生人物卡。右上角会显示发送者 QQ 头像。

如果开启头像转述并配置了支持图片输入的视觉 Provider，插件会先描述 QQ 头像中的画面特征，再让人物卡 LLM 保留这些核心外貌特征，并根据聊天风格扩写异世界服装、饰品、动作和气质。性格仍主要来自聊天记录。

`/开启异世界网页` 和 `/关闭异世界网页` 仅管理员可用。开启后会临时启动 `8501` 只读存档页面，并回复访问地址和临时令牌。

`/异世界冒险` 不会读取群历史，只会读取玩家自己的转生存档、当前状态、最近冒险日志和世界书。命令后可以带行动文本；如果不带行动，LLM 会根据当前状态自由生成一次完整的小冒险。

## 聊天记录路线

参考项目不是只读取当前命令那一条消息：

- QQ / OneBot：通过 `get_group_msg_history` 主动拉取群历史。
- Telegram：平时拦截群消息，写入 AstrBot 的 `message_history_manager`，分析时再读取。
- 分析前会把群消息清洗、过滤命令和机器人消息，再交给统计与 LLM 分析模块。

本插件第一版只实现 QQ 够用路线：优先尝试 OneBot 的 `get_group_msg_history`，读取最近若干条群消息后筛选当前触发者的发言。读取失败时不会崩溃，会按玩具样例生成。

聊天记录只在 `/异世界转生` 建档时使用。未来 `/异世界冒险` 会读取插件自己的玩家存档，不再读取群历史。

## 存档与排队

转生成功后会在 AstrBot 插件数据目录下创建：

```text
data/plugin_data/astrbot_plugin_qq_adventurer/saves/groups/{group_id}/users/{user_id}/
```

其中包含：

- `profile.json`：转生人物卡、头像、昵称。
- `state.json`：当前区域、具体地点、HP、MP、金币、背包、技能、任务等冒险状态。
- `adventure_log.jsonl`：从转生开始后的冒险记录。

同一个群同一个 QQ 号的请求会串行排队处理，避免多条消息同时写坏同一份存档；不同玩家可以并行处理。

## 冒险日记

冒险日记卡要求 LLM 只返回 JSON，并渲染为独立的日记卡模板。当前只实际处理等级、区域和地点；`update.patches` 是为后续状态系统预留的结构：

```json
{
  "title": "异世界冒险日记",
  "subtitle": "森林边境的一日远行",
  "target_name": "群友名称",
  "action": "我要到森林里冒险",
  "date_label": "第 1 次冒险",
  "region": "低语森林",
  "location": "溪边临时营地",
  "diary": "完整日记正文",
  "encounter": "遭遇内容",
  "result": "事件结算",
  "level_change": "Lv.1->Lv.5",
  "stats": {"魔力": "A", "力量": "F", "敏捷": "C", "体质": "E"},
  "changes": ["获得物品：小浆果", "采集熟练度 +10%"],
  "footer": "底部说明",
  "update": {
    "analysis": "本次在森林中行动并练习采集。",
    "patches": [
      { "op": "replace", "path": "/region", "value": "低语森林" },
      { "op": "replace", "path": "/location", "value": "溪边临时营地" },
      { "op": "delta", "path": "/skills/采集/proficiency", "value": 10 }
    ]
  }
}
```

代码会把等级限制在 `1..100`，并把冒险结果追加到 `adventure_log.jsonl`。技能熟练度 patch 暂时只要求 LLM 输出，不会自动应用。

## 头像与外貌

- QQ 头像 URL 由发送者 QQ 号生成。
- 头像转述默认关闭。
- 开启 `vision.enable_avatar_caption` 后，需要在 `vision.vision_provider_id` 选择支持图片输入的 Provider。
- 头像转述失败时，只跳过头像外貌参考，不影响卡片生成。
- `appearance` 是幻想角色设定，不声称是真实用户外貌。

## JSON 输出格式

LLM 被要求只返回：

```json
{
  "title": "异世界转生人物卡",
  "subtitle": "一句副标题",
  "target_name": "群友名称",
  "race": "转生种族",
  "class_name": "异世界职阶",
  "appearance": "保留头像核心特征，并根据聊天风格扩写出的异世界可爱外貌设定",
  "personality": "根据聊天记录推断出的性格",
  "talent": "一个和聊天风格有关的异世界天赋",
  "stats": {
    "魔力": "A",
    "力量": "F",
    "敏捷": "C",
    "体质": "E"
  },
  "likes": ["喜欢物1", "喜欢物2", "喜欢物3"],
  "quote": "一句符合该角色的可爱台词",
  "footer": "一句底部说明"
}
```

代码里仍然保留双重提示约束：

- system prompt 放人格。
- user prompt 再重复一次人格和格式优先级。

也就是：人格可以影响文风，但不能破坏 JSON 结构。

## 配置

- `llm.llm_provider_id`：人物卡生成 Provider，使用 `_special: select_provider`。
- `vision.enable_avatar_caption`：是否启用头像图像转述，默认关闭。
- `vision.vision_provider_id`：头像转述 Provider，使用 `_special: select_provider`，请选择支持图片输入的模型。
- `vision.avatar_caption_prompt`：头像转述提示词。
- `analysis_features.use_plugin_specific_persona`：强制使用插件指定人格。
- `analysis_features.plugin_specific_persona_id`：使用 `_special: select_persona` 选择人格。
- `adventure.max_history_messages`：读取群历史消息上限。
- `adventure.use_mock_data`：静态假数据模式，不调用人物卡 LLM。
- `t2i_rendering`：HTML 转图片策略，第一轮失败后会尝试第二轮。
- `web_viewer.host`：存档网页监听地址，默认 `0.0.0.0`。
- `web_viewer.port`：存档网页端口，默认 `8501`。
- `web_viewer.public_base_url`：回复给管理员的公网访问地址，例如 `http://你的服务器IP:8501`。

## 测试

1. 开启 `adventure.use_mock_data`。
2. 在 QQ 群发送：

```text
/异世界转生
```

3. 确认机器人能发送图片卡片，右上角显示发送者 QQ 头像。
4. 关闭 `use_mock_data`，确认 LLM 能返回 JSON 并正常渲染。
5. 开启 `vision.enable_avatar_caption` 并选择视觉 Provider，确认 `appearance` 参考头像转述结果。
6. 开启 `debug_mode` 后，可在插件数据目录查看最终 prompt 和 LLM 原始响应。
7. 使用 `/异世界冒险 我要到森林里冒险`，确认能生成日记卡，并在 8501 网页看到日志。
