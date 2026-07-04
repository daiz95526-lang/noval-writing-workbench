# 验证报告模板

每个阶段完成后至少运行以下检查，并在阶段总结中记录结果。

## 后端

```powershell
cd backend
python -m pytest
python -m ruff check .
```

## 前端

```powershell
cd frontend
npm run lint
npm run build
```

## Git 数据边界

```powershell
git status --short
git ls-files
```

确认跟踪文件中不存在：

- `.env` 或真实 API Key
- 原始语料、分章正文、生成正文
- 日志、构建产物、依赖目录
- 用户私有写作项目

## 阶段报告格式

```text
阶段：
改动：
风险与影响：
回滚方案：
验证：
- 后端测试：
- 后端 lint：
- 前端 lint：
- 前端 build：
- Git 数据边界：
遗留风险：
下一步：
```
