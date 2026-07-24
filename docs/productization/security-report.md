# NOVAL Phase 5 安全报告

状态：实现完成，等待人工验收

## 1. 已修复项

### 路径与文件

- `project_id`、规划 ID、草稿 ID、任务项目目录使用受限格式。
- `safe_child` 拒绝 `..`、绝对路径注入和项目根目录外访问。
- 外部语料路径必须位于显式配置的 `EXTERNAL_CORPUS_ROOTS` 下，并以只读方式引用。
- 上传仅接受安全文件名的 `.txt`，限制 MIME 类型、空字节和大小，默认上限 10 MiB。
- 语料删除只移动派生的 processed 文件；不修改 `source_txt`。
- 临时记录、生成记录和正式章节删除进入项目回收目录。

### 密钥与日志

- 项目创建/更新接口拒绝把 `api_key`、`authorization`、`password`、`secret` 或 `token` 值写入项目配置。
- API 配置状态只返回是否已配置，不返回密钥或 Base URL 详情。
- 日志脱敏 Bearer、Authorization、Token、API Key；默认隐藏本机绝对路径。
- 日志不记录请求体、Prompt、语料正文或完整小说正文。
- 日志使用 JSON Lines 和轮转文件，默认单文件 5 MiB、保留 5 份。

### 网络与前端

- 后端默认监听 `127.0.0.1`。
- CORS 默认仅允许本机前端来源，通配符 `*` 会回退到安全默认值。
- React 默认转义正文和模型文本；代码中没有 `dangerouslySetInnerHTML`、`innerHTML`、`eval` 或动态函数执行。
- 用户可见错误不包含 Python/Pydantic 原始堆栈和请求输入值。

## 2. 依赖审计

- `npm audit --audit-level=high`：0 个已知漏洞。
- Vite 已从存在 Windows 路径漏洞的版本升级到本轮锁定的安全版本。
- `python -m pip_audit -r requirements.txt`：未发现已知漏洞。
- CI 对后端依赖、前端依赖和 Git 历史执行检查；模型测试不使用真实密钥。

## 3. Prompt 注入与内容边界

导入语料和模型输出都视为不可信内容。NOVAL 不执行语料中的指令，不把模型返回内容当作系统配置，不从正文提取 API Key。Prompt 注入无法仅靠本地过滤完全消除，因此用户仍需审核生成、修改和质检结果，尤其是外部来源语料。

## 4. 未解决风险

- 本地应用没有账户与鉴权；安全边界是仅监听 loopback。用户若主动配置 `HOST=0.0.0.0`，必须自行提供防火墙或反向代理认证。
- 本地数据和任务重试参数不加密，拥有本机文件权限的其他账户可能读取。
- Markdown 当前以 React 文本节点展示；未来若引入富文本渲染器，必须增加 HTML 白名单净化。
- GitHub Actions 使用主版本 action 标签，供应链风险低但非零；正式发布可进一步固定 action commit SHA。
- gitleaks 在 CI 中配置，本轮本机没有安装并执行其完整扫描。

## 5. 发布阻塞

未发现 Critical 或 High 依赖漏洞。对外网暴露后端、引入 HTML 渲染、多人账户或云同步都属于新的威胁模型，必须单独安全设计，不能沿用当前本地信任边界。
