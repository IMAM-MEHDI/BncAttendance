from fastapi import FastAPI
from api import sync
from database.session import init_db

app = FastAPI(title="BNC Attendance Central API")

@app.on_event("startup")
def on_startup():
    print("Initializing database...")
    init_db()

app.include_router(sync.router, prefix="/api/v1/sync", tags=["sync"])

@app.get("/")
def read_root():
    return {"message": "Welcome to BNC Attendance API"}

@app.get("/api/v1/version")
def get_version():
    return {
        "version": "1.1.0",
        "mandatory": False,
        "message": "A new version of BNC Attendance is available!",
        "download_url": "https://example.com/download"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
