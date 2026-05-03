import os
import uuid
from utils.config import settings
from database.session import SessionLocal, init_db
from database import crud

def initialize():
    init_db()
    db = SessionLocal()
    
    # Check if admin exists
    admin = crud.get_user_by_enrollment(db, "admin")
    if not admin:
        print("Creating default admin user...")
        # Use settings (which handles .env path for PyInstaller)
        admin_pw = settings.DEFAULT_ADMIN_PASSWORD
        if not admin_pw:
            print("WARNING: DEFAULT_ADMIN_PASSWORD not set in .env! Cannot create admin user.")
            return
        
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
        # If admin exists, ensure the password is up to date with .env
        # This helps if the user changed the .env but the DB was already initialized
        admin_pw = settings.DEFAULT_ADMIN_PASSWORD
        if admin_pw and not crud.verify_password(admin_pw, admin.password_hash):
            print("Updating admin password to match .env...")
            admin.password_hash = crud.hash_password(admin_pw)
            db.commit()
            print("Admin password updated.")
        else:
            print("Admin already exists and password is correct.")
    
    db.close()

if __name__ == "__main__":
    initialize()
