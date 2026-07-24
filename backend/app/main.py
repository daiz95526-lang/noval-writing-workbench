import logging
import re
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.errors import (
    AppError,
    app_error_handler,
    error_response,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.logging_config import configure_logging, log_context
from app.routers import analysis, corpus, drafts, generation, planning, projects, tasks, writing
from app.services.project_context import use_project
from app.services.project_store import project_store

configure_logging()
logger = logging.getLogger("noval.requests")
app = FastAPI(
    title="NOVAL - 本地优先的 AI 长篇写作工作台",
    description="本地小说语料分析、规划、续写、章节管理与导出工作台",
    version="0.1.0",
)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.frontend_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def project_context_middleware(request, call_next):
    supplied_request_id = request.headers.get("X-Request-ID", "").strip()
    request_id = (
        supplied_request_id
        if re.fullmatch(r"[A-Za-z0-9._-]{8,64}", supplied_request_id)
        else uuid.uuid4().hex
    )
    requested_project_id = (
        request.headers.get("X-Project-ID", "").strip()
        or request.query_params.get("project_id", "").strip()
    )
    project_id = requested_project_id or settings.project_id
    operation = f"{request.method} {request.url.path}"
    started = time.perf_counter()
    with log_context(
        request_id=request_id,
        project_id=project_id,
        operation=operation,
    ):
        if requested_project_id:
            try:
                project_store.get(project_id)
            except KeyError:
                response = error_response(404, "PROJECT_NOT_FOUND", "项目不存在")
            except ValueError as exc:
                response = error_response(400, "INVALID_PROJECT_ID", str(exc))
            except RuntimeError as exc:
                response = error_response(409, "PROJECT_UNAVAILABLE", str(exc))
            else:
                with use_project(project_id):
                    try:
                        response = await call_next(request)
                    except Exception as exc:
                        response = await unhandled_exception_handler(request, exc)
        else:
            with use_project(project_id):
                try:
                    response = await call_next(request)
                except Exception as exc:
                    response = await unhandled_exception_handler(request, exc)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "request_completed",
            extra={
                "duration_ms": duration_ms,
                "status_code": response.status_code,
            },
        )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-NOVAL-Project-ID"] = project_id
    return response


app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(corpus.router, prefix="/api/corpus", tags=["corpus"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(generation.router, prefix="/api/generation", tags=["generation"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(drafts.router, prefix="/api/drafts", tags=["drafts"])
app.include_router(planning.router, prefix="/api", tags=["planning"])
app.include_router(writing.router, prefix="/api", tags=["writing"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/system/config-status")
async def config_status():
    """返回系统配置状态（不含密钥内容）"""
    from app.config import ENV_LOADED, settings

    key = settings.anthropic_api_key
    base = settings.anthropic_base_url

    # 推断 provider
    provider = "unknown"
    if base:
        if "deepseek" in base:
            provider = "deepseek"
        elif "anthropic" in base:
            provider = "anthropic"
        elif "openai" in base:
            provider = "openai"

    return {
        "has_api_key": bool(key and len(key) > 10),
        "base_url_configured": bool(base),
        "provider": provider,
        "model": settings.anthropic_model,
        "env_loaded": bool(ENV_LOADED),
    }
