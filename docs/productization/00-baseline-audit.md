# NOVAL Phase 0 稳定版本与项目基线审计

审计日期：2026-07-11  
实际工作区：`C:\Users\zdx\Desktop\Project\noval`  
稳定提交：`e01e5e9c2becac27808ab32c6fe3145de1912879`  
稳定标签：`v0.1-stable`（本地 annotated tag，未推送）  
产品化分支：`productization-v1`（本地分支，未推送）

## 1. 审计结论

当前版本具备继续进行分阶段产品化改造的基础：后端测试、静态检查、前端 lint、TypeScript 检查和生产构建均通过；后端健康接口返回正常，前端开发服务器可访问；现有核心能力在代码、API 和验收测试中仍然存在。

Phase 0 没有修改业务逻辑、生成逻辑、提示词、数据模型或 UI。新增内容为本报告、四张经过空数据环境隔离的基线截图，以及一处后端验收测试隔离修复。未执行模型调用，未读取或输出真实 API Key。

首次运行现有验收测试时发现一个重要基线问题：测试调用真实 `/api/corpus/scan-local`，重写了 `backend/data` 中 337 个派生文件（处理后章节、元数据、导入报告和章节审计报告）。原始语料和 `writing_projects` 未被写入；测试前后 `backend/data` 的文件总数和总字节数完全一致，但派生文件时间戳发生变化，且测试前未保存逐文件哈希，因此不能将“用户数据未修改”标记为完全通过。随后已将这些测试输出隔离到临时目录；修复后重新运行全部测试，真实数据目录没有继续变化。

当前版本仍属于单项目原型：产品文案、路径、项目 ID、部分接口模型和写作工作台仍与 `longzu` / `longzu6` 强绑定；任务状态不能跨后端重启恢复；前端缺少真正的路由、全局工作流状态和多项目入口。这些问题应在后续 Phase 中逐步处理，不应在单次重构中一次性替换。

## 2. Git 与版本保护

### 2.1 Phase 0 开始前状态

- 分支：`main`
- 上游：`origin/main`
- 本地与远端提交一致：`e01e5e9`
- 已跟踪文件：83 个
- 已修改文件：0 个
- 未跟踪文件：0 个
- 已有标签：0 个
- 工作区干净

### 2.2 已建立的本地保护引用

- `v0.1-stable` 指向 `e01e5e9`，用于标记产品化前稳定版本。
- `productization-v1` 从 `e01e5e9` 创建，后续产品化工作应在该分支小步推进。
- 未执行 `git push`、`git add` 或 `git commit`。

如需回滚本阶段，可删除新增报告和截图；如确定不保留本地引用，可手工删除 `productization-v1` 和 `v0.1-stable`。不得使用会覆盖工作区或用户数据的强制重置命令。

## 3. Git 文件边界

### 3.1 已跟踪文件

以下为 Phase 0 开始时的完整跟踪清单：

```text
.gitignore
README.md
backend/.env.example
backend/app/__init__.py
backend/app/config.py
backend/app/main.py
backend/app/models/__init__.py
backend/app/models/schemas.py
backend/app/prompts/__init__.py
backend/app/prompts/generation.py
backend/app/prompts/knowledge.py
backend/app/prompts/style_analysis.py
backend/app/routers/__init__.py
backend/app/routers/analysis.py
backend/app/routers/corpus.py
backend/app/routers/drafts.py
backend/app/routers/generation.py
backend/app/routers/planning.py
backend/app/routers/tasks.py
backend/app/routers/writing.py
backend/app/services/__init__.py
backend/app/services/book_planner.py
backend/app/services/chapter_audit.py
backend/app/services/chapter_planner.py
backend/app/services/chapter_quality.py
backend/app/services/chapter_reviewer.py
backend/app/services/draft_store.py
backend/app/services/file_loader.py
backend/app/services/generator.py
backend/app/services/knowledge_base.py
backend/app/services/local_importer.py
backend/app/services/model_response_parser.py
backend/app/services/planning_store.py
backend/app/services/preprocessor.py
backend/app/services/style_analyzer.py
backend/app/services/task_manager.py
backend/app/services/writing_project_store.py
backend/data/analysis/.gitkeep
backend/data/books/longzu/archive/.gitkeep
backend/data/books/longzu/source_txt/.gitkeep
backend/data/processed/.gitkeep
backend/data/projects/.gitkeep
backend/data/raw/.gitkeep
backend/data/style_cache/.gitkeep
backend/pyproject.toml
backend/requirements-dev.txt
backend/requirements.txt
backend/tests/test_acceptance.py
backend/tests/test_config.py
docs/CONFIG.md
docs/DATA_AND_PRIVACY.md
docs/DEVELOPMENT.md
docs/INSTALLATION.md
docs/USER_GUIDE.md
docs/VERIFICATION.md
examples/sample_book_plan.json
examples/sample_chapter.txt
frontend/.env.example
frontend/.gitignore
frontend/README.md
frontend/eslint.config.js
frontend/index.html
frontend/package-lock.json
frontend/package.json
frontend/public/favicon.svg
frontend/public/icons.svg
frontend/src/App.tsx
frontend/src/api/index.ts
frontend/src/assets/hero.png
frontend/src/assets/vite.svg
frontend/src/components/Layout.tsx
frontend/src/components/TaskStatusPanel.tsx
frontend/src/index.css
frontend/src/main.tsx
frontend/src/pages/CorpusManage.tsx
frontend/src/pages/Dashboard.tsx
frontend/src/pages/Generator.tsx
frontend/src/pages/StyleAnalysis.tsx
frontend/tsconfig.app.json
frontend/tsconfig.json
frontend/tsconfig.node.json
frontend/vite.config.ts
writing_projects/.gitkeep
```

数据目录中被跟踪的文件全部是 `.gitkeep`。未发现语料正文、用户草稿、正式章节、生成记录、真实 `.env` 或密钥文件被跟踪。

### 3.2 未跟踪文件

Phase 0 开始前没有未跟踪文件。Phase 0 完成后预期新增且未暂存：

```text
docs/productization/00-baseline-audit.md
docs/productization/baseline-screenshots/dashboard.png
docs/productization/baseline-screenshots/corpus-management.png
docs/productization/baseline-screenshots/style-analysis.png
docs/productization/baseline-screenshots/writing-workbench.png
```

另有一个已跟踪测试文件处于修改状态：

```text
backend/tests/test_acceptance.py
```

该修改只隔离测试输出，不改变产品功能或运行时数据格式。

### 3.3 被忽略内容

已确认以下类别由根目录或前端 `.gitignore` 排除：

- `.env`、`backend/.env`、`frontend/.env` 和其他非示例环境文件
- `backend/.venv/`、Python 缓存、pytest 缓存、Ruff 缓存
- `frontend/node_modules/`、`frontend/dist/`、Vite 缓存
- 运行日志和临时文件
- `backend/data/` 下除 `.gitkeep` 外的语料、清洗结果、分析缓存、项目数据和导出
- `writing_projects/` 下除根目录 `.gitkeep` 外的全部用户写作项目
- 本地修复报告 `REPAIR_REPORT.md`

为避免把版权语料或私人项目的文件名写入产品化报告，本报告只记录受保护目录、文件数量和 Git 规则，不展开被忽略私有文件的逐文件名称。审计开始与结束时 `backend/data` 均为 483 个文件、124,361,113 字节，`writing_projects` 均为 44 个文件、714,481 字节；它们均未进入 Git 跟踪清单。首次测试造成的派生文件时间戳变化已单独记录。

## 4. 当前稳定功能

代码、API、页面和验收测试共同表明当前版本包含以下能力：

- 本地文本上传与主语料目录扫描
- 章节解析、去重、统计、列表、详情和删除
- 单章风格分析、风格档案读取与本地缓存
- 角色、世界设定、情节、主题和全局风格知识库构建
- 自动构想下一部作品、修订和接受总体构想
- 将总体构想转换为完整章节规划
- 创建、编辑和删除章节计划
- 单次生成、流式生成、完整章节分段生成和续写
- 局部修改与整章重写
- 章节完整性规则检查、AI 深度质检和 AI 修复
- 长任务进度、阶段、日志、部分成功、失败、超时分类和取消请求
- 草稿创建、追加、版本快照、连续性检查和导出
- 临时生成记录读取、保存、加载和删除
- 正式章节读取、保存、更新、加载、删除和导出
- 写作项目清单及本地文件持久化

### 当前核心用户流程

1. 在“语料管理”上传文本或扫描默认本地目录。
2. 在“系统总览”查看章节统计和章节列表。
3. 在“风格分析”选择章节并启动分析任务。
4. 在“续写工作台”生成并审核总体构想。
5. 接受总体构想并生成完整章节规划。
6. 选择章节计划并生成完整章节。
7. 对生成内容进行规则检查、AI 质检、修复或定向修改。
8. 将内容保存为临时记录或正式章节。
9. 查看正式章节、历史记录并导出 Markdown 或文本。

## 5. 前端基线

### 5.1 页面清单

| 页面 | 源文件 | 当前职责 |
| --- | --- | --- |
| 系统总览 | `frontend/src/pages/Dashboard.tsx` | 语料统计、章节分页列表 |
| 语料管理 | `frontend/src/pages/CorpusManage.tsx` | 本地扫描、文件上传、导入报告、章节详情和删除 |
| 风格分析 | `frontend/src/pages/StyleAnalysis.tsx` | 章节选择、任务恢复、风格档案和维度报告 |
| 续写工作台 | `frontend/src/pages/Generator.tsx` | 总体构想、章节生成、修改、质检、临时记录、正式章节和导出 |

续写工作台内部还有四个标签：`总体构想`、`章节生成`、`临时生成记录`、`正式章节库`。

### 5.2 路由、组件和状态管理

- `App.tsx` 使用 `useState` 在四个页面间切换，没有 React Router 或 URL 路由。
- 页面切换会卸载当前页面；不能使用浏览器前进/后退、深链接或刷新恢复页面位置。
- `Layout.tsx` 提供固定侧栏和主内容容器。
- `TaskStatusPanel.tsx` 展示长任务进度、阶段、日志、耗时、错误和取消入口。
- 没有全局状态容器；页面主要使用本地 `useState` / `useEffect`。
- 风格分析和续写工作台使用 `localStorage` 保存部分任务 ID、选中项和工作台标签。
- Generator 中仍集中维护大量互相关联状态，文件超过 1700 行，是后续 UI 改造的高风险区域。

### 5.3 基线截图

截图使用 1440×1000 桌面视口，并通过进程级环境变量指向临时空数据目录，未显示真实章节、语料或私人生成内容。

- [系统总览](baseline-screenshots/dashboard.png)
- [语料管理](baseline-screenshots/corpus-management.png)
- [风格分析](baseline-screenshots/style-analysis.png)
- [续写工作台](baseline-screenshots/writing-workbench.png)

### 5.4 当前 UI/UX 问题

- 产品副标题、工作台说明、按钮和文件路径直接使用具体作品名称。
- 没有“创建项目”“切换项目”“配置模型”的产品级入口。
- 新用户进入后只能从侧栏和零散提示推断使用顺序，缺少贯穿全流程的下一步指引。
- 知识库、总体构想、规划、生成、质检和正式保存被集中在一个大型页面中，入口层级不清晰。
- 没有 URL 路由，页面状态、浏览器历史和可分享位置不稳定。
- 空状态多数只说明“暂无数据”，没有稳定的一键下一步动作和环境诊断入口。
- 深色单一色调、内联样式和页面局部样式并存，组件一致性与可维护性不足。
- 固定 200px 侧栏和桌面双栏布局缺少明确的移动端/窄屏策略。
- 按钮反馈依赖页面各自维护的 banner 和 busy 字符串，交互规范不统一。
- 文件系统路径和内部项目目录直接暴露给普通用户。
- 部分页面仍出现固定“8 个 txt 文件”等仅适用于当前本地数据的提示。
- 续写工作台首屏信息密度高，但总体流程、当前阶段和前置条件不够明确。

## 6. 后端基线

### 6.1 应用结构

- 框架：FastAPI + Pydantic
- 路由模块：7 个
- HTTP API：73 个
- 服务模块：16 个
- 模型与请求/响应结构集中在 `backend/app/models/schemas.py`
- 配置入口集中在 `backend/app/config.py`
- 本地数据使用 JSON、Markdown、文本文件和目录清单持久化

主要服务职责：

| 服务 | 职责 |
| --- | --- |
| `local_importer.py` / `file_loader.py` / `preprocessor.py` | 本地语料扫描、解析、清洗与章节读取 |
| `style_analyzer.py` | 风格分析、缓存和全局风格汇总 |
| `knowledge_base.py` | 角色、设定、情节、主题与风格知识构建 |
| `generator.py` | 章节生成、续写和迭代修改 |
| `book_planner.py` / `chapter_planner.py` | 总体构想和章节规划 |
| `chapter_quality.py` / `chapter_audit.py` | 规则完整性与审计报告 |
| `chapter_reviewer.py` | AI 深度质检和修复建议 |
| `draft_store.py` | 草稿、版本、连续性检查和导出 |
| `planning_store.py` | 总体构想与章节计划持久化 |
| `writing_project_store.py` | 临时记录、正式章节、修订和导出 |
| `task_manager.py` | 长任务状态、进度、日志、失败分类和取消标记 |
| `model_response_parser.py` | 模型返回结构解析和容错 |

### 6.2 API 清单

系统与诊断：

```text
GET    /api/health
GET    /api/system/config-status
```

语料 `/api/corpus`：

```text
GET    /stats
GET    /chapters
GET    /chapters/{chapter_id}
POST   /chapters/upload
DELETE /chapters/{chapter_id}
POST   /scan-local
GET    /import-report
```

风格分析 `/api/analysis`：

```text
GET    /profiles
GET    /profiles/{profile_id}
POST   /analyze/{chapter_id}
GET    /tasks/{task_id}
```

生成与知识库 `/api/generation`：

```text
GET    /knowledge-base
POST   /knowledge-base/build
POST   /generate
POST   /generate/stream
POST   /iterate
GET    /results/{result_id}
GET    /results
DELETE /results/{result_id}
```

草稿 `/api/drafts`：

```text
GET    /
POST   /
GET    /{draft_id}
PUT    /{draft_id}
POST   /{draft_id}/append
POST   /{draft_id}/version
GET    /{draft_id}/versions
POST   /{draft_id}/export
POST   /{draft_id}/continuity-check
```

统一长任务 `/api/tasks`：

```text
GET    /
GET    /{task_id}
POST   /{task_id}/cancel
POST   /style-analysis/start
POST   /knowledge-build/start
POST   /generation/start
POST   /revision/start
```

规划 `/api`：

```text
GET    /outline
PUT    /outline
GET    /book-plan
POST   /book-plan/generate
POST   /book-plan/regenerate
PUT    /book-plan
POST   /book-plan/accept
POST   /book-plan/complete-chapter-plans
POST   /book-plan/revise
POST   /book-plan/reparse-raw/{temp_id}
POST   /book-plan/apply-to-chapter-plans
GET    /chapter-plans
POST   /chapter-plans
GET    /chapter-plans/{plan_id}
PUT    /chapter-plans/{plan_id}
DELETE /chapter-plans/{plan_id}
```

写作项目 `/api`：

```text
GET    /writing-project
POST   /chapter-generation/start
POST   /chapter-generation/full-chapter/start
POST   /chapter-generation/check-completeness
POST   /chapter-generation/ai-review/start
POST   /chapter-generation/ai-repair/start
GET    /chapter-generation/{task_id}
POST   /chapter-generation/revise
POST   /chapter-generation/save-temp
POST   /chapter-generation/save-official
GET    /temp-generations
GET    /temp-generations/{temp_id}
DELETE /temp-generations/{temp_id}
POST   /temp-generations/{temp_id}/load-to-editor
GET    /official-chapters
GET    /official-chapters/{chapter_id}
PUT    /official-chapters/{chapter_id}
DELETE /official-chapters/{chapter_id}
POST   /official-chapters/{chapter_id}/export
POST   /official-chapters/{chapter_id}/load-to-editor
```

### 6.3 任务系统

当前任务系统支持：`pending`、`running`、`success`、`partial_success`、`failed`、`cancelled`；记录进度、阶段、消息、最近 50 条日志、部分正文、字数、起止时间和结构化错误分类。

主要限制：

- 任务字典保存在进程内存，后端重启后全部丢失。
- 取消主要依赖任务代码主动检查状态，不是强制终止底层模型请求。
- 任务日志没有统一持久化、轮转和诊断追踪 ID。
- 旧分析任务接口、统一任务接口和写作任务接口存在重叠。
- 前端依靠轮询和本地任务 ID 恢复；后端重启后会出现任务不存在。

## 7. 数据目录与保护边界

### 7.1 不得破坏的数据目录

后续 Phase 在没有独立迁移方案、备份和用户确认前，不得删除、重命名、批量改写或移动：

```text
backend/.env
backend/data/
backend/data/books/longzu/source_txt/
backend/data/books/longzu/archive/
backend/data/processed/
backend/data/analysis/
backend/data/style_cache/
backend/data/projects/
writing_projects/
writing_projects/longzu6/
```

原始语料目录必须保持只读语义。后续迁移只能复制或建立兼容读取层，不能以“清理旧结构”为理由删除旧数据。

### 7.2 不得无保护重构的核心文件

```text
backend/app/config.py
backend/app/models/schemas.py
backend/app/routers/generation.py
backend/app/routers/planning.py
backend/app/routers/tasks.py
backend/app/routers/writing.py
backend/app/services/generator.py
backend/app/services/style_analyzer.py
backend/app/services/knowledge_base.py
backend/app/services/task_manager.py
backend/app/services/draft_store.py
backend/app/services/planning_store.py
backend/app/services/writing_project_store.py
frontend/src/api/index.ts
frontend/src/pages/Generator.tsx
```

这些文件承载跨模块契约、持久化格式或核心工作流；修改时必须有兼容层、针对性测试和明确回滚路径。

## 8. 当前技术债

### 高优先级

- `longzu`、`longzu6`、特定作品标题、固定文件名和固定相对路径仍散落在后端模型、服务和前端页面。
- `CORPUS_SOURCE_DIR` 已进入配置，但导入器和页面提示尚未完全统一使用该配置。
- `HOST`、`PORT`、`FRONTEND_ORIGINS` 已进入配置，但 FastAPI CORS 和实际启动命令仍有硬编码。
- 默认数据仍位于源码树中的 `backend/data`，代码与用户数据没有完成物理分离。
- 不存在通用的项目创建、项目列表、项目切换和项目元数据版本机制。
- 长任务无法跨重启恢复，未达到“可恢复”产品要求。
- 本地 JSON/Markdown 存储没有 schema version、迁移记录和跨进程并发控制。

### 中优先级

- 73 个接口中存在同步生成、流式生成、旧分析任务和统一长任务等重叠入口。
- `schemas.py`、`frontend/src/api/index.ts` 和 `Generator.tsx` 体积过大，职责混合。
- 前后端类型手工同步，没有 OpenAPI 类型生成或契约漂移检查。
- Ruff 当前只启用少量致命规则，不能代表完整 Python 代码质量检查。
- 后端测试集中在验收和配置层，服务边界、并发、恢复、失败注入和迁移测试不足。
- 前端没有组件测试、交互测试或端到端测试。
- 没有 CI、许可证、贡献指南、安全策略、版本发布流程和已知限制清单。

### 低优先级

- 前端包名和版本仍为 Vite 默认风格 `frontend@0.0.0`。
- 运行日志位置和命名不统一。
- 健康检查只返回状态和版本，没有数据目录可写性、依赖、端口、模型配置和恢复状态诊断。

## 9. 当前数据风险

- Git 忽略规则有效，但用户数据仍与源码目录相邻，复制、打包或错误配置发布工具时可能被带出。
- 当前验收测试曾直接重写真实派生数据；Phase 0 已隔离写入，但测试仍依赖本地私有语料才能满足“8 卷、至少 332 章”的断言，不适合直接作为公开仓库的独立 CI 测试。
- 现有路径覆盖以单个当前项目为中心，尚无多项目根目录和项目隔离规则。
- 数据格式缺少显式 schema version，未来字段调整可能让旧 JSON 无法读取。
- 多个存储服务采用临时文件替换，单次写入具备一定原子性，但没有完整事务或跨进程锁。
- 删除接口覆盖章节、结果、临时记录、正式章节和计划；产品层仍需要回收站、确认和版本保护策略。
- 任务状态不持久化，生成完成但任务响应丢失时可能出现“文件存在但界面不知道”的不一致。
- 错误消息做了 API Key 基础脱敏，但日志、第三方异常和未来诊断接口仍需统一敏感信息过滤。
- 当前没有自动备份、恢复验证或迁移演练。

## 10. 测试与启动验证

### 后端

```text
命令：backend/.venv/Scripts/python.exe -m pytest
首次结果：44 passed, 1 warning（20.11s，同时暴露真实派生数据写入问题）
隔离修复后结果：44 passed, 1 warning（16.91s，真实数据目录无新增写入）
Python：3.12.13
```

唯一警告来自 FastAPI TestClient 间接依赖：Starlette 提示当前 `httpx` 集成未来弃用并建议迁移到 `httpx2`。该警告不影响当前测试通过，但应纳入依赖升级计划。

```text
命令：backend/.venv/Scripts/python.exe -m ruff check .
结果：All checks passed!
```

### 前端

```text
命令：npm.cmd run lint
结果：通过

命令：npm.cmd exec tsc -- --noEmit -p tsconfig.app.json
结果：通过

命令：npm.cmd run build
结果：通过
Vite：8.0.14
产物：CSS 8.28 kB；JS 268.42 kB（gzip 80.30 kB）
```

### 启动验证

```text
GET http://127.0.0.1:8010/api/health -> 200, {status: ok, version: 0.1.0}
GET http://127.0.0.1:5173            -> 200
```

默认配置启动和前端访问已验证。为了保护私人内容，截图阶段重启后端并用临时空目录覆盖所有数据路径；空目录环境下健康接口正常，语料章节数为 0。

测试隔离修复覆盖：`settings.processed_dir`、语料元数据索引、导入报告和章节审计报告。原始语料仍只读，测试继续从现有本地语料加载章节；将验收测试进一步改造成完全基于原创 fixture 的公开 CI 测试，应作为后续工程阶段任务。

未执行真实模型调用，因此 Phase 0 不对第三方模型服务、余额、网络质量或当前 API Key 有效性作验证结论。

## 11. 后续改造高风险区域

1. **项目模型与路径迁移**：必须同时兼容默认 `longzu6`、自定义目录和未来多项目结构。
2. **写作项目存储**：正式章节、临时记录、修订和导出格式不能因重命名或目录调整失联。
3. **总体构想与章节规划契约**：后端 Pydantic 模型、JSON 文件和前端 TypeScript 类型需要同步演进。
4. **长任务持久化**：从内存任务切换到持久化时要处理运行中、部分成功、取消和孤儿任务。
5. **生成与风格核心逻辑**：提示词、上下文裁剪、响应解析和分段生成已有复杂行为，不能与 UI 重构混改。
6. **Generator 页面拆分**：状态依赖密集，直接拆组件容易造成任务恢复、编辑内容或选中项丢失。
7. **API 收敛**：旧接口不能直接删除，需要弃用周期、兼容适配和契约测试。
8. **数据目录外置**：不得默认移动现有用户数据；需要显式选择、复制迁移、校验和回滚。
9. **删除与覆盖操作**：正式章节和计划需要版本保护、确认、回收或可恢复策略。
10. **公开发布**：许可证、隐私说明、示例数据和打包清单必须在发布前独立复核。

## 12. Phase 0 验收结果

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| 当前版本可以启动 | 通过 | 后端健康接口 200；前端页面 200 |
| 核心功能仍然存在 | 通过 | 页面/API 清单完整；44 个后端测试通过 |
| 测试结果有记录 | 通过 | 本报告第 10 节 |
| 用户数据未修改 | 有偏差 | 原始语料和 `writing_projects` 未写入；首次测试重写 337 个派生文件并更新时间戳，文件数和总字节数不变；隔离修复后复测未再写入真实目录 |
| 基线报告完整 | 通过 | Git、架构、API、页面、数据、风险、测试和截图均已记录 |
| 未开始产品功能改造 | 通过 | 业务代码和 UI 无修改；仅修复测试输出隔离 |

Phase 0 的产品代码、启动和测试基线通过；“用户数据未修改”验收项因首次测试刷新派生数据而只能标记为有偏差。该偏差已止损并加入永久记录，不能追溯性地改写为完全通过。

## 13. Phase 1 建议输入

Phase 1 应只处理“产品定义与核心用户流程”，先确定产品规则，再允许后续信息架构和工程实现。建议输入包括：

- 产品正式定位：本地优先的 AI 长篇小说分析、规划、续写和章节管理工作台。
- 目标用户优先级：个人长篇作者、同人/续写研究者、需要私有语料的创作者，还是可扩展开发者工具。
- “项目”的最小定义：项目 ID、标题、语料目录、写作目录、模型配置、状态和创建时间。
- 首次使用必须完成的步骤：创建项目、配置模型、导入语料、扫描、分析、规划、生成、审核、保存。
- 哪些能力属于一级导航，哪些属于项目内步骤，哪些属于高级工具。
- 知识库与风格分析是强制前置条件还是可跳过步骤。
- 总体构想、章节计划、临时生成和正式章节之间的状态转换规则。
- 失败、取消、部分成功、恢复和重试的用户语言与操作边界。
- 原始语料只读、正式章节版本保护和删除恢复原则。
- 产品通用术语，清除所有把具体版权作品当作通用功能名的文案。
- Phase 1 交付物：`docs/productization/01-product-definition.md`，不修改功能代码。

Phase 1 开始前应再次检查 `git status`，阅读本报告，并由用户确认接受 Phase 0 中记录的测试副作用，然后明确发送“进入 Phase 1”。
