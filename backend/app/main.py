from fastapi import FastAPI

app = FastAPI(
    title = "Enterprise Knowledge Copilot API",
    description = "Enterprise AI Knowledge Assistant Backend",
    version = "0.1.0",
)


@app.get("/health/live")
async def health_check():
    """Check whether the application process is alive."""
    return {"status": "alive"}

@app.get("/health/ready")
async def health_check_ready():
    """Basic readiness check external services are integrated."""
    return {
        "status": "ready",
        "checks": {
            "application": "ok"
        }
    }