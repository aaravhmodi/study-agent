from fastapi import FastAPI

from app.config import get_settings

app = FastAPI(title="StudyAgent", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "browser_mode": get_settings().browser_mode}
