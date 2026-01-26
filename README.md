# bot_side_plugin（MaiBot QQ 发布博客插件）

> 用于在 QQ 中通过指令发布博客内容（含定时发布）。

## ✨ 功能简介
- QQ 指令发布博客
- 管理员权限校验
- 写入本地 posts.json
- 定时发布队列

## ✅ 兼容性
- MaiBot 插件系统（需 `_manifest.json`）
- Python 3.10+

## 📦 目录结构
```
bot_side_plugin/
├── _manifest.json         # 插件清单（MaiBot 强制要求）
├── plugin.py              # 插件入口（BasePlugin）
├── publish_command.py     # QQ 指令发布博客
├── scheduler.py           # 定时发布调度器
├── requirements.txt       # 依赖
├── config.example.toml    # 配置示例（含中文注释）
├── STRUCTURE.md           # 结构说明
├── 需求.md                 # 原始需求备份
└── README.md              # 使用说明
```

## 🚀 安装方式
1. 将 `bot_side_plugin/` 目录放到 `MaiBot/plugins/` 下
2. 安装依赖：
   ```bash
   pip install -r plugins/bot_side_plugin/requirements.txt
   ```
3. 启动 MaiBot，插件会自动生成 `config.toml`
4. 按照 `config.example.toml` 配置实际参数（建议对照修改生成的 `config.toml`）

## ⚙️ 配置说明（核心）
> 实际配置位于 `config.toml`，字段由 `config_schema` 自动生成。

- **plugin.enabled**：是否启用插件
- **admin.admin_qqs**：允许发布博客的管理员 QQ 号
- **admin.silent_when_no_permission_in_group**：群聊无权限静默处理
- **publish.posts_json_path**：本地 posts.json 路径
- **schedule.enabled**：是否启用定时发布
- **schedule.schedule_time**：每日执行时间（HH:MM）
- **schedule.timezone**：时区设置
- **schedule.queue_json_path**：定时发布队列 JSON 路径
- **schedule.max_posts_per_run**：每次执行最多发布条数

## 📝 QQ 指令发布博客
- 指令格式：`/blog publish 标题 | 正文`
- 示例：`/blog publish 今天的标题 | 这里是正文内容`
- 仅管理员可执行（`admin.admin_qqs`）
- 写入本地 `posts.json`（默认 `blog_side_api/data/posts.json`）

## ⏰ 定时发布
- 通过 `schedule.queue_json_path` 指定定时队列文件
- 每日按 `schedule.schedule_time` 执行一次，处理队列中到期条目
- 队列条目格式示例：
```json
[
  {
    "title": "定时发布标题",
    "content": "这是正文内容",
    "author": "MaiBot",
    "publish_at": "2026-01-26T20:00:00+08:00"
  }
]
```
- `publish_at` 可选；缺省或解析失败时视为可立即发布

## 🤖 人设复用说明
插件不会在自身配置中定义人设，所有人设均从主程序读取：
- `personality.personality`
- `personality.reply_style`
- `personality.plan_style`
- `personality.states`
- `personality.state_probability`

## 🧪 说明
本插件不再调用博客端回复接口，仅通过 QQ 指令写入本地 `posts.json`。
定时发布模式仅处理队列文件，不会发送 QQ 消息。

## 📄 License
建议发布到 GitHub 时补充 LICENSE（如 MIT）。
