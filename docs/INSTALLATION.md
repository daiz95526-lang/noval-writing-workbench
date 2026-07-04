# 安装与运行

本文档面向第一次拿到 NOVAL 的用户，目标是在一台新机器上从零启动本地写作工作台。

## 前置要求

- Windows、macOS 或 Linux
- Python 3.11 或更高版本
- Node.js 18 或更高版本
- npm
- 一个 Anthropic 兼容的模型 API

不要把真实 API Key 写入仓库、截图、日志、README 或问题反馈。

## 获取代码

```powershell
git clone <your-repository-url> noval
cd noval
```

如果你是从压缩包获取项目，解压后进入项目根目录即可。

## 配置后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `backend/.env`，填入自己的模型服务配置：

```dotenv
ANTHROPIC_AUTH_TOKEN=your_api_key_here
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_MODEL=deepseek-v4-pro[1m]
ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
```

启动后端：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

后端健康检查地址：

```text
http://127.0.0.1:8010/api/health
```

API 文档地址：

```text
http://127.0.0.1:8010/docs
```

## 配置前端

另开一个终端：

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev -- --host 127.0.0.1
```

默认前端通过 Vite 代理访问后端，通常不需要改 `frontend/.env.local`。如需连接不同地址，可修改：

```dotenv
VITE_API_BASE_URL=/api
```

访问：

```text
http://127.0.0.1:5173
```

## 准备本地语料

NOVAL 不自带任何版权语料。你需要自行准备具有合法来源和处理权限的文本。

推荐把原始文本放在：

```text
backend/data/books/longzu/source_txt/
```

这些文件只保存在本机，不应提交到 Git。导入后生成的分章、分析缓存、草稿、正式章节和导出文件也都属于本地私有数据。

## 常见问题

如果页面提示无法连接后端，先确认后端运行在 `127.0.0.1:8010`，前端运行在 `127.0.0.1:5173`。

如果提示未配置 API Key，检查 `backend/.env` 是否存在，以及 `ANTHROPIC_AUTH_TOKEN` 或兼容变量是否已填写。

如果导入后没有章节，确认文本是 UTF-8 编码，并且你选择的导入目录中确实存在文本文件。
