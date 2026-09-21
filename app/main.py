from fastapi import FastAPI

from app.opds import router as opds_router

app = FastAPI(title="Magazine Generator")
app.include_router(opds_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
