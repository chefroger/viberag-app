"""
VibeRAG FastAPI 主应用
"""
import asyncio
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db, SessionLocal
from app.routers import library, ask, settings as settings_router, session, customer
from app.models import Library
from app.services.scanner import run_scan_task
from app.middleware.inbound_interceptor import InboundInterceptorMiddleware

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"

# 创建 FastAPI 应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="智能商业文档分析与销售助手",
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 初始化数据库
init_db()

# 注册路由
app.include_router(library.router)
app.include_router(ask.router)
app.include_router(settings_router.router)
app.include_router(session.router)
app.include_router(customer.router)

# 注册入口拦截器中间件
app.add_middleware(InboundInterceptorMiddleware)


@app.on_event("startup")
async def startup_event():
    """启动时启动后台定期扫描任务"""
    asyncio.create_task(periodic_scan())


async def periodic_scan():
    """定期扫描所有文档库，检测新文件（每30分钟执行一次）"""
    from app.services.scanner import get_scan_progress

    while True:
        await asyncio.sleep(1800)  # 30分钟

        try:
            # 检查是否已有扫描在进行
            progress = get_scan_progress()
            if progress.status == 'scanning' or progress.status == 'indexing':
                print("上次扫描尚未完成，跳过本次周期")
                continue  # 跳过本次周期

            db = SessionLocal()
            try:
                libraries = db.query(Library).all()
                for lib in libraries:
                    # 检查路径是否存在
                    if not Path(lib.root_path).exists():
                        continue

                    print(f"后台增量扫描文档库: {lib.name}")
                    # 后台触发增量扫描（不传db，让任务自己创建）
                    asyncio.create_task(run_scan_task(lib.id, lib.root_path))
            finally:
                db.close()
        except Exception as e:
            print(f"定期扫描出错: {e}")


@app.get("/", response_class=HTMLResponse)
async def root():
    """主页"""
    with open(TEMPLATES_DIR / "index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    """设置页面"""
    with open(TEMPLATES_DIR / "settings.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": settings.APP_VERSION}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
