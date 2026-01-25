# bot_side_plugin（MaiBot 博客评论自动回复插件）

> 用于对接博客端 API 的 MaiBot 插件，定时拉取评论并自动生成回复写回。

## ✨ 功能简介
- 定时拉取待处理评论
- 结合主程序人设与回复风格生成回复
- 自动写回博客
- 去重与缓存机制
- 可配置黑白名单/禁评词/人工审核

## ✅ 兼容性
- MaiBot 插件系统（需 `_manifest.json`）
- Python 3.10+

## 📦 目录结构
```
bot_side_plugin/
├── _manifest.json         # 插件清单（MaiBot 强制要求）
├── plugin.py              # 插件入口（BasePlugin）
├── monitor.py             # 定时监控逻辑
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

- **plugin.enable**：是否启用插件
- **blog_api.blog_api_url**：博客 API 地址（必填）
- **blog_api.blog_api_key**：API Token（必填）
- **monitor.check_interval**：拉取间隔（秒）
- **reply.reply_prompt_template**：回复提示词模板
- **dedup.cache_ttl**：去重缓存过期时间（秒）
- **security.forbidden_words**：禁评词列表

## 🤖 人设复用说明
插件不会在自身配置中定义人设，所有人设均从主程序读取：
- `personality.personality`
- `personality.reply_style`
- `personality.plan_style`
- `personality.states`
- `personality.state_probability`

## 🧪 API 对接约定
插件调用博客端的两个接口：
- `GET /api/v1/comments/pending?since=timestamp`
- `POST /api/v1/comments`

请参考博客端样板工程 `blog_side_api/`。

## 📄 License
建议发布到 GitHub 时补充 LICENSE（如 MIT）。
