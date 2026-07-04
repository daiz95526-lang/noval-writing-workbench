# 开发指南

本文档面向希望维护或扩展 NOVAL 的开发者。

## 设计原则

- 保持本地优先：默认不需要数据库或外部后端服务。
- 代码目录和数据目录分离：业务代码可提交，用户数据不可提交。
- API 稳定优先：前端依赖的响应字段需要通过测试保护。
- 长任务可观察：耗时模型调用必须能查看状态、日志、失败原因和部分结果。
- 错误信息可恢复：向用户解释下一步，而不是只暴露堆栈。

## 后端

后端位于 `backend/app`：

- `routers/`：FastAPI 路由，保持请求/响应边界清晰。
- `services/`：语料处理、模型调用、规划、草稿、正式章节和任务管理。
- `models/schemas.py`：Pydantic 数据契约。
- `prompts/`：模型提示词模板。
- `tests/`：核心验收测试。

本地开发：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check .
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

## 前端

前端位于 `frontend/src`：

- `api/`：后端 API 客户端和类型。
- `components/`：复用组件。
- `pages/`：主要工作台页面。

本地开发：

```powershell
cd frontend
npm install
npm run lint
npm run build
npm run dev -- --host 127.0.0.1
```

## 修改准则

- 不要把真实语料、生成正文、分析缓存或密钥加入测试快照。
- 变更 API 字段时，先更新后端 schema、前端类型和验收测试。
- 新增长任务时，必须支持状态查询、失败记录和可理解的用户提示。
- 涉及文件写入时，明确写入目录，避免跨出用户配置的数据根目录。
- 修改模型调用时，保留超时、错误分类和密钥脱敏逻辑。

## 测试策略

后端验收测试覆盖核心本地工作流：导入、章节 API、风格分析、知识库、规划、生成、修订、保存、导出和长任务状态。

前端当前以 TypeScript 构建和 ESLint 作为基础保护。后续增加组件测试或端到端测试时，应优先覆盖导入、规划、生成、保存和导出路径。
