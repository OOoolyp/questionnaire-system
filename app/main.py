"""应用入口：生命周期、错误处理、路由注册与静态资源。"""
import os
import mimetypes
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool

from app.api.routes import router
from app.library.routes import router as library_router
from app.surveys.reuse_routes import router as reuse_router
from app.surveys.version_routes import router as version_router
from app.library.bank_routes import router as bank_router
from app.library.share_routes import router as share_router
from app.library.analytics_routes import router as analytics_router
from app.core.database import prepare_database
from app.auth.security import configure_secret


@asynccontextmanager
async def lifespan(application: FastAPI):
    configure_secret(application)
    client = MongoClient(
        os.getenv("MONGODB_URI", "mongodb://localhost:27017"),
        serverSelectionTimeoutMS=3000,
        connectTimeoutMS=3000,
        socketTimeoutMS=5000,
        tz_aware=True,
    )
    try:
        await run_in_threadpool(client.admin.command, "ping")
        database = client[os.getenv("MONGODB_DATABASE", "questionnaire")]
        application.state.database = database
        await run_in_threadpool(prepare_database, database)
        yield
    finally:
        client.close()


app = FastAPI(
    title="问卷系统 API",
    description="注册登录、编辑和发布问卷、通过分享标识填写并提交。先通过 Authorize 登录。",
    version="0.8.0",
    lifespan=lifespan,
)


@app.exception_handler(PyMongoError)
async def database_error_handler(request: Request, exc: PyMongoError):
    return JSONResponse(
        status_code=503,
        content={"detail": "数据库暂时不可用，请检查 MongoDB 服务后重试"},
    )


app.include_router(router)
app.include_router(library_router)
app.include_router(reuse_router)
app.include_router(version_router)
app.include_router(bank_router)
app.include_router(share_router)
app.include_router(analytics_router)


# 前端与API同源，避免额外端口和跨域配置；保留 /docs 及原有API路径。
# Windows的注册表可能将.mjs识别为text/plain，模块必须用JavaScript媒体类型提供。
mimetypes.init()
mimetypes.add_type("application/javascript", ".mjs")
app.mount("/ui", StaticFiles(directory=Path(__file__).resolve().parent.parent / "frontend", html=True), name="frontend")
