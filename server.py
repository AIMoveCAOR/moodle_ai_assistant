"""
FastAPI backend server for Moodle AI Assistant.

This server acts as a proxy between the JavaScript frontend and the RAG system,
providing streaming responses and document-based or pure generation modes.
"""

import os
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load .env before any LangChain import so LANGSMITH_TRACING is picked up at SDK init time
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import router
from core.chat_ticket import internal_token_middleware
from config.settings import setup_logging


# Setup logging
logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Moodle AI Assistant Backend Server...")

    # Check for Documents folder on startup
    docs_exist = os.path.exists("Documents") and os.path.isdir("Documents")
    mode = "RAG" if docs_exist else "Generation"
    logger.info(f"Server mode: {mode} (Documents folder exists: {docs_exist})")

    yield

    logger.info("Shutting down Moodle AI Assistant Backend Server...")


# Create FastAPI app
app = FastAPI(
    title="Moodle AI Assistant Backend",
    description="Backend proxy server for Moodle AI Assistant block plugin",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS — backend is internal-only (127.0.0.1), so lock down origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1", "http://localhost"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Internal-Token"],
)

_INTERNAL_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")
_PUBLIC_PATHS = {"/", "/api/health", "/api/status"}


# Every route needs the shared internal token except the public ones and
# /api/chat, which also accepts a signed ticket from local/craftpilot/chat_proxy.php
# (browsers never hold the token). See core/chat_ticket.py.
app.middleware("http")(internal_token_middleware(_INTERNAL_TOKEN, _PUBLIC_PATHS))

# Include API routes
app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint."""
    return JSONResponse(
        {
            "message": "Moodle AI Assistant Backend Server",
            "version": "1.0.0",
            "docs": "/docs",
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app", host="0.0.0.0", port=8000, reload=True, log_level="info"
    )
