# 数据与隐私边界

NOVAL 的开源仓库只应该包含程序代码、文档和原创示例。用户的真实语料、生成内容、模型缓存、日志和 API Key 都属于本地私有数据。

## 不应提交的内容

- `.env`、`.env.local`、任何包含密钥的配置文件
- 原始小说、电子书、用户上传文本
- 分章后的正文文本
- 风格分析缓存、知识库缓存和导入报告
- 临时生成记录、草稿、修订版本、正式章节和导出文件
- 运行日志、构建产物、虚拟环境、`node_modules`

## 可提交的内容

- 源代码
- 文档
- `.env.example`
- 完全原创且可公开的 `examples/` 示例
- 空目录占位 `.gitkeep`
- 不含私人正文的测试 fixtures

## 提交前检查

```powershell
git status --short
git check-ignore -v backend/.env
git check-ignore -v backend/data/books/longzu/source_txt/
git check-ignore -v backend/data/projects/
git check-ignore -v writing_projects/longzu6/
git ls-files
```

`git ls-files` 中不应出现 `.env`、语料全文、生成正文、日志、大型电子书或本地构建目录。

## 模型调用隐私

模型调用会把选定章节、规划、草稿或用户输入发送给你配置的模型服务。使用前请确认你有权处理这些文本，并理解服务提供方的数据处理政策。

## 本地备份

重要写作项目建议定期备份：

```text
writing_projects/
backend/data/projects/
```

备份文件同样不应上传到公开仓库。
