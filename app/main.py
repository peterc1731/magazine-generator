from fastapi import FastAPI

from app.opds import router as opds_router
from app.web import router as web_router

app = FastAPI(title="Magazine Generator")
app.include_router(opds_router)
app.include_router(web_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
