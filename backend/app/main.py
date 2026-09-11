"""
main.py

FastAPI application entrypoint (case study section 21/27/45).
Run with:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import os

from app.core.config import get_settings
from app.core.database import init_db
from app.core.logging import configure_logging, get_logger
from app.api.routes.documents import router as documents_router

settings = get_settings()
configure_logging()
logger = get_logger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    description="Document Intelligence Platform -- OCR + AI extraction + "
    "deterministic financial validation for invoices, balance sheets, "
    "profit & loss statements, and cash flow statements.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    logger.info("Starting %s in %s mode", settings.APP_NAME, settings.ENV)
    init_db()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak stack traces to the client (case study section 30).
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_SERVER_ERROR", "message": "An unexpected error occurred."}},
    )


app.include_router(documents_router, prefix="/api/v1")

# Serve the vanilla HTML/CSS/JS frontend directly from FastAPI for simple
# local/single-service deployment. In a split deployment (section 27) the
# frontend is instead hosted separately and talks to this API via
# API_BASE_URL -- both modes work with the same backend.
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
try:
    app.mount("/static", StaticFiles(directory=os.path.join(_frontend_dir, "static")), name="static")

    @app.get("/", include_in_schema=False)
    def serve_frontend():
        return FileResponse(os.path.join(_frontend_dir, "index.html"))

except Exception:  # pragma: no cover - static dir optional depending on cwd
    logger.warning("Could not mount frontend static assets from %s", _frontend_dir)
