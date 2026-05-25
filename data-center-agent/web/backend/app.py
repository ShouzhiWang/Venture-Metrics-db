from __future__ import annotations

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("FastAPI is required for the demo website. Install with: pip install -e '.[web]'") from exc

from web.backend.routes.auth import router as auth_router
from web.backend.routes.chat import router as chat_router
from web.backend.routes.history import router as history_router
from web.backend.routes.map import router as map_router
from web.backend.routes.projects import router as projects_router


app = FastAPI(title="Startup Data Intelligence Demo API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(history_router)
app.include_router(projects_router)
app.include_router(map_router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
