from fastapi import FastAPI, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import engine
from app.api.auth import router as auth_router
from app.api.knowledge_bases import router as knowledge_bases_router
from app.api.conversations import router as conversations_router

app = FastAPI(
    title = "Enterprise Knowledge Copilot API",
    description = "Enterprise AI Knowledge Assistant Backend",
    version = "0.1.0",
)

app.include_router(auth_router)
app.include_router(knowledge_bases_router)
app.include_router(conversations_router)

@app.get("/health/live")
async def health_check():
    """Check whether the application process is alive."""
    return {"status": "alive"}

@app.get("/health/ready")
def health_ready(response: Response):
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "checks": {"postgres": "unavailable"}}

    return {"status": "ready", "checks": {"postgres": "ok"}}