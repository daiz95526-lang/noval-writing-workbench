# NOVAL

NOVAL 是一个本地优先的小说语料分析与长篇写作辅助系统。它使用 FastAPI 和 React 构建，可导入用户自行准备的合法文本，提取章节、风格和设定信息，并辅助完成构想、规划、生成、审稿、修订和版本管理。

仓库只包含程序代码和原创示例，不应包含小说原文、用户私有写作内容、API 密钥或本地分析缓存。

## 功能特性

- 本地语料导入、清洗与章节识别
- 章节列表、统计与内容管理
- 分章节风格分析及本地缓存
- 角色、设定、情节和风格知识库构建
- 自动构想下一部作品及总体故事规划
- 完整章节规划与章节状态管理
- 一键生成完整章节和分段生成
- 局部修改与整章重写模式
- 规则完整性检查与 AI 深度质检
- 临时生成记录、草稿和版本保存
- 正式章节库、修订快照与导出
- 长任务进度、超时、失败和部分成功处理

## 技术栈

- 后端：Python、FastAPI、Pydantic、Anthropic SDK
- 前端：React、TypeScript、Vite
- 数据：本地文件系统
- 模型接口：Anthropic 兼容 API

## 目录结构

```text
noval/
├── backend/
│   ├── app/                 # FastAPI 应用、路由、服务与数据模型
│   ├── data/                # 本地语料、缓存和项目数据，不提交具体内容
│   ├── tests/               # 后端验收测试
│   ├── .env.example         # 环境变量模板
│   └── requirements.txt
├── frontend/
│   ├── src/                 # React 页面、组件和 API 客户端
│   └── package.json
├── examples/                # 完全原创、可公开的最小示例
├── writing_projects/        # 用户私有写作项目，仅保留 .gitkeep
├── .gitignore
└── README.md
```

## 环境要求

- Python 3.11 或更高版本
- Node.js 18 或更高版本
- npm
- 可用的 Anthropic 兼容模型 API

## 环境变量

进入 `backend` 后复制模板：

```powershell
Copy-Item .env.example .env
```

编辑新建的 `.env`：

```dotenv
ANTHROPIC_AUTH_TOKEN=your_api_key_here
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_MODEL=deepseek-v4-pro[1m]
ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
```

后端也兼容 `ANTHROPIC_API_KEY` 和 `DEEPSEEK_API_KEY`。不要把真实密钥写入代码、README、日志或 `.env.example`，也不要提交 `.env`。

## 本地启动

### 后端

在项目根目录执行：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

API 文档：<http://127.0.0.1:8010/docs>

### 前端

另开一个终端，在项目根目录执行：

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

访问：<http://127.0.0.1:5173>

## 准备语料

用户需要自行准备具有合法来源和使用权限的 UTF-8 文本。可将待导入文本放入：

```text
backend/data/books/longzu/source_txt/
```

也可以通过页面提供的本地导入功能处理语料。目录名仅是当前默认配置，可以在代码配置中调整。

仓库中的 `examples/sample_chapter.txt` 是完全原创的短示例，不属于任何现有小说。

## 本地数据边界

以下内容只应保存在本机，已由 `.gitignore` 排除：

- `backend/.env` 和其他环境变量文件
- `backend/data/` 下的原始语料、分章文本、分析结果和缓存
- `backend/data/projects/` 下的草稿、生成记录、版本与导出
- `writing_projects/` 下的总体构想、临时记录、正式章节和修订
- 运行日志、构建产物、虚拟环境和 `node_modules`

如需保留目录结构，只提交目录内的 `.gitkeep`。

## 测试与构建

后端：

```powershell
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check .
```

前端：

```powershell
cd frontend
npm run lint
npm run build
```

## 文档

- [安装与运行](docs/INSTALLATION.md)
- [配置说明](docs/CONFIG.md)
- [用户使用指南](docs/USER_GUIDE.md)
- [开发指南](docs/DEVELOPMENT.md)
- [数据与隐私边界](docs/DATA_AND_PRIVACY.md)
- [验证报告模板](docs/VERIFICATION.md)

## GitHub 上传前检查

首次提交前建议执行：

```powershell
git status --short
git check-ignore -v backend/.env
git check-ignore -v backend/data/books/longzu/source_txt/
git check-ignore -v backend/data/projects/
git check-ignore -v writing_projects/longzu6/
git ls-files
```

检查 `git ls-files` 的结果，确认不存在 `.env`、密钥、语料全文、生成正文、日志或大文件。若某个敏感文件曾被加入索引，使用 `git rm --cached <path>` 仅从索引移除，切勿误删本地文件。

## 安全声明

- 所有模型凭据必须由环境变量或本地 `.env` 提供。
- SDK 自动重试、请求超时和任务失败状态由后端控制，但用户仍应自行评估第三方 API 的数据处理政策。
- 向远程模型发送文本前，请确认拥有相应内容的处理权限。
- 公开仓库前应再次运行密钥扫描和大文件检查。

## 版权声明

- 本项目不包含、也不授权分发任何受版权保护的小说原文。
- 用户需要自行准备合法来源且有权处理的本地语料。
- 不建议公开上传原始语料、分析缓存或可能侵权的派生生成内容。
- 本项目仅用于本地文本分析、写作辅助和工程学习；使用者应自行遵守所在地法律、内容许可和模型服务条款。

## 项目状态

核心本地工作流已可用，包括语料管理、风格分析、知识库、总体构想、章节规划、完整章节生成、迭代修改、AI 质检、正式章节保存和导出。当前重点是稳定性、数据边界和开源前安全整理。

## 后续计划

- 增加更多自动化测试和跨平台启动脚本
- 提供可配置的数据目录与项目模板
- 改进模型供应商适配和结构化输出兼容
- 增加更清晰的备份、迁移和隐私提示

## License

提交或分发代码前，请由项目所有者选择并添加合适的开源许可证文件。
