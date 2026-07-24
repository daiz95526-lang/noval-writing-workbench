# NOVAL Phase 5 测试报告

状态：自动化验证完成，等待人工验收

## 1. 覆盖范围

### 后端

- Project 创建、更新、归档、迁移、路径安全和多项目隔离
- 原创语料扫描、分析、总体构想、完整章节规划、生成、局部修改、质检、带 warning 正式保存和导出
- 重启后项目、正式章节和任务历史重新加载
- running 任务重启转 interrupted、任务超时、取消、重试和部分结果恢复
- 原子写失败保留旧文件、备份恢复损坏 JSON、软删除
- 上传类型、大小、文件名和空字节限制
- 统一错误响应、请求 ID、输入隐藏和日志脱敏
- 集中模型调用的超时、重试、Prompt 和 token 上限

### 前端

- ESLint
- TypeScript `--noEmit`
- Vitest + Testing Library 组件测试
- 生产构建
- 任务中断状态、保留进度和重试按钮

### 依赖与 CI

- Python `pip-audit`
- npm audit
- GitHub Actions：后端测试/Ruff/依赖审计、前端 lint/TypeScript/test/build/audit、gitleaks

## 2. 最低 E2E

`test_phase4_original_creation_flow_uses_only_temporary_data_and_mock_models` 使用临时目录和原创测试文本完成：

创建项目 → 导入语料 → 扫描 → 分析 → 自动构想 → 接受构想 → 完整章节规划 → 生成 8,000+ 字章节 → 局部修改 → AI 质检 → 带 warning 保存正式章节 → 进入下一章 → 导出 → 清理运行时 → 重新加载正式章节和历史任务。

所有模型调用均为 mock；没有调用真实模型 API，没有读取或写入真实 API Key。

## 3. 验证命令

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pip_audit -r requirements.txt --cache-dir ..\.cache\pip-audit

cd ..\frontend
npm.cmd run lint
npx.cmd tsc --noEmit
npm.cmd run test
npm.cmd run build
npm.cmd audit --audit-level=high

cd ..
git diff --check
```

## 4. 本轮结果

- 后端：64 tests passed，1 条第三方 TestClient 弃用警告。
- Ruff：通过。
- 前端组件测试：1 test passed。
- ESLint：通过。
- TypeScript：通过。
- production build：通过。
- npm audit：0 vulnerabilities。
- pip-audit：No known vulnerabilities found。
- `git diff --check`：通过。

最终交付报告以本轮结束前最后一次全量执行为准。

## 5. 已知测试缺口

- 没有调用付费模型服务；Provider 的真实限流、网络抖动和 ThinkingBlock 差异需用户按自己的服务人工验证。
- 没有自动强杀后端进程；重启恢复通过重新构造任务管理器和清理运行时模拟。
- GitHub Actions 文件已创建，但本轮未 push，因此远端 runner 尚未实际运行。
- 前端没有完整浏览器 E2E 框架；核心闭环目前由 FastAPI 集成测试和组件测试覆盖。
- TestClient 依赖发出 `httpx2` 迁移警告，不影响当前测试结果，但应在依赖兼容后升级。

## 6. 发布阻塞

自动化范围内没有失败项。进入发布准备前仍需完成 Windows 人工验收：真实启动、任务中途关闭后重开、正式章节软删除恢复、超大历史列表和真实 Provider 失败提示。
