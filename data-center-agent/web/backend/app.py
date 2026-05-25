from __future__ import annotations

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("FastAPI is required for the demo website. Install with: pip install -e '.[web]'") from exc

from web.backend.routes.auth import router as auth_router
from web.backend.routes.chat import router as chat_router


app = FastAPI(title="Startup Data Intelligence Demo API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
