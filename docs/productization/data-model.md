# NOVAL Phase 2 项目数据模型

状态：已实现，待人工验收  
模型版本：`schema_version = 1`

## 1. 设计目标

NOVAL 使用稳定 `project_id` 作为项目身份和目录名，显示名称只用于界面展示。项目改名不会重命名目录，也不会改变语料、规划、章节、任务或导出的归属。

## 2. Project

```json
{
  "schema_version": 1,
  "project_id": "stable-project-id",
  "title": "项目名称",
  "description": "",
  "project_type": "continuation | original | analysis",
  "status": "active | archived",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "corpus_config": {
    "mode": "managed | external_readonly | none",
    "source_paths": [],
    "read_only": true
  },
  "model_config_ref": {},
  "current_book_plan_id": null,
  "current_chapter_id": null,
  "metadata": {},
  "storage_mode": "managed | legacy",
  "legacy": false,
  "migration_state": "not_required | available | in_progress | complete | failed"
}
```

约束：

- `project_id` 只能包含小写字母、数字、下划线和连字符，长度 3-64。
- 未指定 ID 时生成 32 位 UUID hex；ID 创建后不可通过更新 API 修改。
- 中文项目名保存在 UTF-8 JSON 中，不参与路径计算。
- 同名活动托管项目会被拒绝；归档项目不占用显示名称。
- manifest、语料索引和写作存储使用临时文件加原子替换。

实现位置：`backend/app/models/schemas.py`、`backend/app/services/project_store.py`。

## 3. 项目目录

```text
PROJECTS_DIR/{project_id}/
├─ project.json
├─ corpus/
│  ├─ source/
│  ├─ processed/
│  ├─ index/
│  └─ reports/
├─ analysis/
│  ├─ style/
│  ├─ knowledge/
│  └─ summaries/
├─ planning/
│  ├─ book_plans/
│  └─ chapter_plans/
├─ writing/
│  ├─ temp_generations/
│  ├─ drafts/
│  ├─ official_chapters/
│  ├─ revisions/
│  ├─ versions/
│  └─ draft_store/
├─ exports/
└─ backups/
```

默认 `PROJECTS_DIR=./backend/data/projects`，保持现有开发环境兼容；可以通过 `.env` 改到独立用户数据位置。本阶段不自动移动任何旧目录。

## 4. 语料归属与路径安全

- `managed`：语料写入项目自己的 `corpus/source`。
- `external_readonly`：只引用已存在目录，不把原始语料当成项目可写内容。
- `none`：原创项目可以没有语料。
- 外部路径必须为绝对目录，并位于旧 `CORPUS_SOURCE_DIR` 或 `EXTERNAL_CORPUS_ROOTS` 明确列出的允许根目录内。
- `safe_child()` 在解析后检查目标仍位于托管根目录，拒绝 `..` 和目录逃逸。
- 草稿、规划、临时记录和正式章节 ID 另有文件名安全校验。

## 5. 项目上下文

旧接口保持不变，通过 `X-Project-ID` 请求头选择项目。后端中间件验证项目存在后建立 `ContextVar` 上下文；未携带请求头时回退旧项目，保证旧前端和本地数据继续工作。

以下状态按项目隔离：

- 语料内存索引；
- 风格档案、知识库和生成结果缓存；
- 总体构想、Book Plan 和章节规划；
- 草稿、版本、临时生成、正式章节和导出；
- 长任务列表、查询和取消。

后台任务创建时捕获 `project_id`，执行时恢复同一上下文。任务还记录 `operation_type`、`target_id` 和 `user_visible_title`。

## 6. 项目 API

```text
GET    /api/projects
POST   /api/projects
GET    /api/projects/{project_id}
PUT    /api/projects/{project_id}
POST   /api/projects/{project_id}/archive
DELETE /api/projects/{project_id}?confirm_project_id={project_id}
GET    /api/projects/{project_id}/summary
GET    /api/projects/{project_id}/migration-preview
POST   /api/projects/{project_id}/migrate
```

删除只适用于托管项目：先创建 ZIP，再把整个目录移动到 `.trash`。旧项目不能由删除 API 删除。

## 7. 旧项目运行时配置

旧作品专用提示词、卷名映射、规则角色和旧文件名只在 `storage_mode=legacy` 时启用。托管项目在模型调用前转换为通用项目名称和通用作品语境；旧规则回退不会进入普通项目。

## 8. 已知限制

- 任务仍为进程内状态，后端重启后不能恢复。
- 原子替换保证单文件完整性，但本阶段没有跨进程文件锁；不支持同时启动多个后端写同一数据根。
- 外部语料允许根通过 `.env` 配置，尚无图形化目录授权界面。
- 旧接口使用请求头而不是项目路径；兼容周期结束前不移除旧调用方式。
