# NOVAL Design System

## 1. 目标与原则

NOVAL 的界面服务于长时间阅读、研究和写作，不使用营销页或游戏式表达。设计遵循以下原则：

1. 暗色优先，背景层级靠明度和边框区分，不靠大面积渐变或阴影。
2. 主要操作使用低饱和青绿色；成功、警告、危险和信息状态使用独立语义色。
3. 页面保持清晰的信息层级，高级参数、日志和内部编号默认折叠。
4. 临时生成、正式章节、任务状态和项目上下文必须有明确文字，不只依赖颜色。
5. 页面级布局响应 1366×768 和 1920×1080；窄屏允许侧栏收起，表格在自身容器滚动。

## 2. UI 审计结论

Phase 3 前端此前可用，但存在以下高优先级问题：

| 问题 | 根因 | Phase 3 处理 |
|---|---|---|
| 页面颜色不一致 | TSX 内散落多套十六进制颜色 | 建立语义 CSS Variables，并迁移主要页面 |
| 主次操作不清晰 | 所有按钮共享近似金色强调 | 建立 Primary、Secondary、Ghost、Danger、Link |
| 导航职责不完整 | 只有总览、语料、风格、创作四项 | 建立工作区、当前项目和设置三层导航 |
| 项目上下文弱 | 项目 select 与页面标题分离 | App Shell 顶栏和 ProjectSwitcher 持续显示项目 |
| 状态反馈重复 | 各页自行拼接成功和错误色块 | 统一 Alert、Toast、EmptyState、ErrorState |
| 长任务暴露技术细节 | task_id 位于任务面板主信息区 | 主区显示用户可读阶段，编号和日志移入技术详情 |
| 固定列布局溢出 | 四列统计和双栏页面写死 | 使用响应式网格、容器滚动和移动侧栏 |
| 创作页阅读负担大 | 规划、正文、AI 结果连续堆叠 | 固定流程 Tab、双区自适应布局、长文本专用编辑样式 |

## 3. Design Tokens

Token 定义在 `frontend/src/index.css` 的 `:root`，业务组件不得新增重复调色板。

### 3.1 颜色

| 类别 | Token | 用途 |
|---|---|---|
| 背景 | `--background-primary` | 页面与编辑器底色 |
| 背景 | `--background-secondary` | 导航和主要面板 |
| 背景 | `--background-elevated` | 卡片、Modal、提升层 |
| 交互 | `--surface-hover` / `--surface-active` | hover 和选中表面 |
| 边框 | `--border-subtle` / `--border-strong` | 普通分隔和强调分隔 |
| 文本 | `--text-primary` / `--text-secondary` / `--text-muted` | 标题、正文、辅助信息 |
| 品牌 | `--accent-primary` / `--accent-hover` / `--accent-soft` | 主操作、焦点、当前项 |
| 状态 | `--success` / `--warning` / `--danger` / `--info` | 语义状态及对应 soft 背景 |

### 3.2 Typography

- UI 字体：Inter、Segoe UI、PingFang SC、Microsoft YaHei 回退栈。
- 长正文：Source Han Serif SC、Songti SC、SimSun 回退栈。
- 字号：12 / 13 / 14 / 16 / 20 / 24px，通过 `--font-*` token 使用。
- UI 行高：1.35 至 1.6；长文本行高：1.9。
- 页面标题保持 24px，面板标题保持 16px，不随视口宽度缩放。

### 3.3 Spacing、圆角与动效

- 间距采用 4px 基线：`--space-1` 至 `--space-10`。
- 圆角仅使用 4 / 6 / 8px；状态 Badge 可使用胶囊形状。
- 阴影仅用于 Modal 等真正提升层。
- 交互过渡为 140ms；遵守 `prefers-reduced-motion`。

## 4. 组件规范

通用组件位于 `frontend/src/components/ui.tsx`。

| 组件 | 规范 |
|---|---|
| Button / IconButton | primary、secondary、ghost、danger、link；sm/md/lg；loading/disabled |
| Input / Textarea / Select / MultiSelect | 统一边框、hover、focus、disabled 与 placeholder |
| Checkbox / Radio | 使用浏览器原生语义和 accent token |
| Card / Panel | Card 仅用于项目等重复对象；Panel 用于页面工作区 |
| Tabs | `role=tablist/tab`，当前项同时使用文字与底边强调 |
| Modal / ConfirmDialog | Escape 和遮罩关闭，保留 aria-modal 与标题关联 |
| Alert / Toast / Badge | success、warning、danger、info，不以颜色作为唯一信息 |
| Progress / Spinner / Skeleton | 任务、加载和占位状态 |
| EmptyState / ErrorState / LoadingState | 页面与局部区域统一状态语言 |
| PageHeader / SectionHeader | 统一面包屑、标题、说明和操作位置 |
| SearchInput / LongTextEditor / ChapterList | 搜索、长正文编辑和章节选择基础能力 |

领域组件包括 `ProjectSwitcher`、`TaskStatusPanel`、App Shell Sidebar。`TaskStatusPanel` 将任务名称、阶段、耗时和恢复操作作为主信息，task_id 与技术日志仅在“技术详情”中显示。

## 5. 页面模板

### 5.1 App Shell

- 左侧栏：品牌、当前项目、工作区导航、项目导航、设置。
- 顶栏：当前页面、当前项目、全局任务状态和设置入口。
- 主内容：最大宽度 1600px，页面使用 PageHeader 和 page-stack。
- 900px 以下使用紧凑图标侧栏，680px 以下改为可关闭抽屉。

### 5.2 首页与项目

- 首页首先显示当前项目，而不是空白系统统计。
- 无语料时提供一个明确的“导入语料”下一步。
- 项目页显示项目类型、状态、兼容标记和切换操作；创建项目使用 Modal，不再使用浏览器 prompt。

### 5.3 创作与章节库

- 固定流程为总体构想、章节生成、临时记录、正式章节。
- 规划和正文使用自适应双区布局；不足宽度时自动单列。
- 正文编辑器使用适合中文长文本的字体、16px 字号和 1.9 行高。
- 章节库复用同一业务工作台并直接进入正式章节 Tab，避免复制保存和导出逻辑。

### 5.4 语料、分析与设置

- 语料上传、扫描、导入报告、章节列表和正文详情保持原流程。
- 分析页保留任务恢复、取消、已有报告和维度展开。
- 设置页只显示安全的配置状态，不读取或展示密钥、完整文件路径。

## 6. 状态与错误

1. 无项目：引导创建或选择项目。
2. 无语料：引导导入，不显示硬编码章节统计。
3. 无分析结果：解释下一步，不显示空白面板。
4. 加载：使用 LoadingState、Spinner 或 Skeleton。
5. 后台任务：显示阶段、百分比、耗时、取消和重试。
6. 成功、警告、错误：使用语义 Alert；底层技术信息折叠展示。
7. 后端不可用：API 层继续输出用户可读的连接失败消息，由 ErrorState 承载。

## 7. 可访问性与响应式

- 所有图标按钮必须提供 `aria-label` 和 tooltip。
- 全局 `:focus-visible` 使用 2px accent outline。
- Tabs、Modal、Progress 使用对应 ARIA 角色或属性。
- 表单使用可见 label；长正文编辑器提供 aria-label。
- 颜色之外同时提供文字、图标或状态标签。
- 页面禁止整体水平滚动；宽表格在 `.table-scroll` 内滚动。
- 支持键盘 Tab、Escape 关闭 Modal 和浏览器缩放。

## 8. 改造截图与验证

改造前基线：

- [首页](baseline-screenshots/dashboard.png)
- [语料管理](baseline-screenshots/corpus-management.png)
- [风格分析](baseline-screenshots/style-analysis.png)
- [创作工作台](baseline-screenshots/writing-workbench.png)

Phase 3：

- [首页 1366×768](phase3-screenshots/home-1366x768.png)
- [项目 1366×768](phase3-screenshots/projects-1366x768.png)
- [创作工作台 1366×768](phase3-screenshots/creation-1366x768.png)
- [创作工作台 1920×1080](phase3-screenshots/creation-1920x1080.png)
- [语料库 1366×768](phase3-screenshots/corpus-1366x768.png)
- [设置 1366×768](phase3-screenshots/settings-1366x768.png)

自动浏览器检查结果：两个目标分辨率均无页面级横向溢出、无控制台错误；连续 Tab 后焦点保持在可交互控件。

## 9. 已知限制与后续边界

1. 当前没有视觉回归测试框架；截图作为人工验收基线保存。
2. Toast 目前复用 Alert 语义，尚未建立全局消息队列。
3. 创作工作台保留原有大组件和业务状态机，本阶段只做布局与视觉整理；后续拆分必须单独评估业务回归风险。
4. 知识库仍位于现有创作流程内，没有在 Phase 3 改动信息架构或后端 API。
5. 本阶段未实现浅色主题，也未进入 Phase 4 的安装、部署或新业务功能。
