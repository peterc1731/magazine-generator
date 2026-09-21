from fastapi import FastAPI

app = FastAPI(title="Magazine Generator")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
