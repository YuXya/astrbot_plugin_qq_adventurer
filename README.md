# QQ 异世界转生人物卡

这是一个 AstrBot 插件玩具版，用于跑通：

群聊命令 -> 尝试读取触发者最近发言 -> LLM 生成标准 JSON -> 解析为人物卡对象 -> HTML 模板渲染 -> HTML 转图片 -> QQ 群发送图片

## 命令

```text
/异世界转生
```

插件会以发送命令的群友为目标，尽量读取该群友最近的群聊发言，推断性格和表达气质，然后生成一张异世界转生人物卡。

当前外貌设定固定要求为“可可爱爱的异世界小萝莉风格”，但性格会根据聊天记录变化。

## 原项目的聊天记录路线

参考项目不是只读取当前命令那一条消息：

- QQ / OneBot：通过 `get_group_msg_history` 主动拉取群历史。
- Telegram：平时拦截群消息，写入 AstrBot 的 `message_history_manager`，分析时再读取。
- 分析前会把群消息清洗、过滤命令和机器人消息，再交给统计与 LLM 分析模块。

本插件第一版只实现够用路线：优先尝试 OneBot 的 `get_group_msg_history`，读取最近若干条群消息后筛选当前触发者的发言。读取失败时不会崩溃，会按玩具样例生成。

## JSON 输出格式

LLM 被要求只返回：

```json
{
  "title": "异世界转生人物卡",
  "subtitle": "一句副标题",
  "target_name": "群友名称",
  "race": "转生种族",
  "class_name": "异世界职阶",
  "appearance": "可爱小萝莉外貌描述",
  "personality": "根据聊天记录推断出的性格",
  "talent": "一个和聊天风格有关的异世界天赋",
  "stats": {
    "魔力": "A",
    "吐槽": "S",
    "幸运": "B",
    "可爱": "SS"
  },
  "likes": ["喜欢物1", "喜欢物2", "喜欢物3"],
  "quote": "一句符合该角色的可爱台词",
  "footer": "一句底部说明"
}
```

代码里仍然保留了双重提示约束：

- system prompt 放人格。
- user prompt 再重复一次人格和格式优先级。

也就是：人格可以影响文风，但不能破坏 JSON 结构。

## 配置

- `llm.llm_provider_id`：使用原项目同款 `_special: select_provider`，在面板里选择 Provider。
- `analysis_features.use_plugin_specific_persona`：强制使用插件指定人格。
- `analysis_features.plugin_specific_persona_id`：使用原项目同款 `_special: select_persona`，在面板里选择人格。
- `adventure.max_history_messages`：读取群历史消息上限。
- `adventure.use_mock_data`：静态假数据模式，不调用 LLM，也不读取真实聊天记录。
- `t2i_rendering`：HTML 转图片策略，第一轮失败后会尝试第二轮。

## 测试

1. 开启 `adventure.use_mock_data`。
2. 在 QQ 群发送：

```text
/异世界转生
```

3. 确认机器人能发送图片卡片。
4. 关闭 `use_mock_data`，确认 LLM 能返回 JSON 并正常渲染。
5. 开启 `debug_mode` 后，可在插件数据目录查看最终 prompt 和 LLM 原始响应。
