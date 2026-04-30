import os
import uuid
from dotenv import load_dotenv
from database.session import SessionLocal, init_db
from database import crud

load_dotenv()

def initialize():
    init_db()
    db = SessionLocal()
    
    # Check if admin exists
    admin = crud.get_user_by_enrollment(db, "admin")
    if not admin:
        print("Creating default admin user...")
        # Get password from environment or use a safe fallback (though env is preferred)
        admin_pw = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
        
        crud.create_user(
            db, 
            user_id=str(uuid.uuid4()), 
            name="System Admin", 
            enrollment="admin", 
            role="admin", 
            password=admin_pw
        )
        print("Admin user created successfully.")
    else:
        print("Admin already exists.")
    
    db.close()

if __name__ == "__main__":
    initialize()
