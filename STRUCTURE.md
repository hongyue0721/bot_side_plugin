# bot_side_plugin 结构说明

本文档用于说明 bot 端插件目录结构与文件职责，便于发布到 GitHub。

## 目录结构
```
bot_side_plugin/
├── _manifest.json         # 插件清单（MaiBot 强制要求）
├── plugin.py              # 插件入口（BasePlugin）
├── publish_command.py     # QQ 指令发布博客
├── scheduler.py           # 定时发布调度器
├── content_generator.py   # 定时内容生成（聊天记录→提示词→LLM）
├── requirements.txt       # 依赖列表
├── config.example.toml    # 配置示例（中文注释）
├── STRUCTURE.md           # 结构说明
├── 需求.md                 # 原始需求备份
└── README.md              # 使用说明
```

## 文件职责
- `_manifest.json`：MaiBot 插件清单，描述插件元数据、兼容版本、分类等。
- `plugin.py`：插件入口类，注册配置与 QQ 发布指令与定时发布调度器。
- `publish_command.py`：/blog publish 指令处理与本地 posts.json 写入。
- `scheduler.py`：定时发布逻辑，读取队列并写入 posts.json。
- `content_generator.py`：按聊天记录生成博客标题与正文。
- `config.example.toml`：示例配置（建议对照生成的 `config.toml` 修改）。
- `requirements.txt`：插件依赖。
- `README.md`：安装与配置说明。
- `需求.md`：需求原文留档，便于追溯。

## 备注
- 本插件负责 QQ 发布与定时发布，不再处理评论回复。
