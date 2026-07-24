# 配置说明

NOVAL 的后端配置集中在 `backend/app/config.py`，本地覆盖值写入 `backend/.env`。不要提交真实 `.env` 或 API Key。

## 默认兼容原则

Phase 2.1 不迁移、不删除、不重命名任何现有数据。默认配置继续兼容当前开发目录：

- 数据根目录：`backend/data`
- 语料源目录：`backend/data/books/longzu/source_txt`
- 草稿与章节规划目录：`backend/data/projects/longzu_continuation`
- 正式写作项目目录：`writing_projects/longzu6`
- 项目 ID：`longzu6`
- 项目标题：`龙族 VI 续写工程`

如果不写任何路径配置，现有本地工作流应保持不变。

## 可覆盖配置

在 `backend/.env` 中可覆盖以下值：

```dotenv
HOST=127.0.0.1
PORT=8010
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

PROJECT_ID=longzu6
PROJECT_TITLE=龙族 VI 续写工程

DATA_DIR=./backend/data
CORPUS_SOURCE_DIR=./backend/data/books/longzu/source_txt
CONTINUATION_PROJECT_DIR=./backend/data/projects/longzu_continuation
WRITING_PROJECT_DIR=./writing_projects/longzu6

TASK_STORAGE_DIR=./backend/data/tasks
TASK_TIMEOUT_SECONDS=3600
TASK_HISTORY_LIMIT=500
UPLOAD_MAX_BYTES=10485760
MODEL_MAX_RETRIES=2
LOG_DIR=./backend/data/logs
LOG_LEVEL=INFO
LOG_MAX_BYTES=5242880
LOG_BACKUP_COUNT=5
LOG_INCLUDE_PATHS=false
```

相对路径会按仓库根目录解析。绝对路径会按原样使用。路径配置不会自动迁移旧数据，也不会删除旧目录。

## 配置项含义

- `HOST`：后端监听地址。
- `PORT`：后端监听端口，默认 `8010`。非法端口会 fallback 到默认值，并记录配置警告。
- `FRONTEND_ORIGINS`：允许访问后端的前端来源，多个来源用英文逗号分隔。
- `PROJECT_ID`：当前写作项目 ID。Phase 2.1 默认保持 `longzu6`。
- `PROJECT_TITLE`：当前写作项目显示标题。
- `DATA_DIR`：后端本地数据根目录。
- `CORPUS_SOURCE_DIR`：本地语料源目录。Phase 2.1 先集中声明配置字段，后续阶段会把导入器完全切换到该字段。
- `CONTINUATION_PROJECT_DIR`：草稿、章节规划、临时生成记录等项目工作目录。
- `WRITING_PROJECT_DIR`：正式章节库、总体构想、修订和导出目录。
- `TASK_STORAGE_DIR`：按 `project_id` 隔离的任务记录目录；不放入语料或正式章节目录。
- `TASK_TIMEOUT_SECONDS`：后台任务最大等待时间，范围 30 秒至 24 小时。
- `TASK_HISTORY_LIMIT`：每个项目保留的任务记录上限，默认 500。
- `UPLOAD_MAX_BYTES`：单个 TXT 语料文件上传上限，默认 10 MiB。
- `MODEL_MAX_RETRIES`：模型 SDK 的有限自动重试次数，默认 2，不允许无限重试。
- `LOG_DIR`：结构化 JSON Lines 日志目录。
- `LOG_LEVEL`：`DEBUG`、`INFO`、`WARNING`、`ERROR` 或 `CRITICAL`。
- `LOG_MAX_BYTES` / `LOG_BACKUP_COUNT`：单日志文件大小和轮转保留数量。
- `LOG_INCLUDE_PATHS`：默认 `false`，仅在本地开发诊断时显式开启完整路径。

## 错误处理

配置解析遵循“明确 fallback，不静默失败”的原则：

- `PORT` 不是整数或超出端口范围时，使用 `8010`。
- `FRONTEND_ORIGINS` 为空或格式不合法时，使用默认前端来源。
- `FRONTEND_ORIGINS=*` 会被拒绝并回退到本地默认来源。
- 路径为空时使用默认路径。
- 路径包含非法空字符时使用默认路径。

配置警告保存在 `settings.config_warnings`，配置状态接口不会返回 API Key、Token 或完整密钥来源。
