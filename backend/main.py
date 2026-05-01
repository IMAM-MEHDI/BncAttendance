# Deployment: 2026-04-30
from fastapi import FastAPI
from api import sync
from database.session import init_db

app = FastAPI(title="BNC Attendance Central API")

@app.on_event("startup")
def on_startup():
    print("Initializing database...")
    init_db()
    
    # Create default admin if no users exist
    from database.session import SessionLocal
    from database import models
    import bcrypt
    import uuid
    import os
    
    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            print("No users found in database. Creating default admin...")
            admin_pw = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
            hashed_pw = bcrypt.hashpw(admin_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            new_admin = models.User(
                user_id="ADMIN-001",
                name="System Administrator",
                enrollment="admin",
                role="admin",
                password_hash=hashed_pw
            )
            db.add(new_admin)
            db.commit()
            print("Default admin created successfully.")
    except Exception as e:
        print(f"Error creating default admin: {e}")
    finally:
        db.close()

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
