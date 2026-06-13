from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import corpus, analysis, drafts, generation, planning, tasks, writing

app = FastAPI(
    title="Noval - 龙族风格蒸馏与续写系统",
    description="对《龙族》系列进行风格蒸馏，提取文风/文笔/内核，并基于此进行风格一致的续写",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
