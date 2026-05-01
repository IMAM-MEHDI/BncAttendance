from fastapi import APIRouter
from schemas.sync import SyncRequest

router = APIRouter()

@router.post("/")
def sync_records(request: SyncRequest):
    # Logic to insert into central database would go here
    # For now, just print and return success
    print(f"Received {len(request.records)} records to sync.")
    return {"status": "success", "synced_count": len(request.records)}

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from database.session import SessionLocal
from schemas.sync import MasterDataRequest
from database import models
import bcrypt

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/master-data")
def get_master_data(request: MasterDataRequest, db: Session = Depends(get_db)):
    # 1. Authenticate Admin
    admin_user = db.query(models.User).filter(models.User.enrollment == request.enrollment, models.User.role == 'admin').first()
    if not admin_user or not admin_user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid admin credentials or user not found.")
        
    if not bcrypt.checkpw(request.password.encode('utf-8'), admin_user.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Invalid admin credentials.")

    # 2. Fetch all required data
    departments = db.query(models.Department).all()
    subjects = db.query(models.Subject).all()
    users = db.query(models.User).all()
    routines = db.query(models.Routine).all()

    # 3. Format Response
    def dict_from_obj(obj, cols):
        d = {}
        for c in cols:
            val = getattr(obj, c)
            if isinstance(val, bytes):
                d[c] = val.hex() # Send large binary as hex
            elif hasattr(val, 'isoformat'):
                d[c] = val.isoformat()
            else:
                d[c] = val
        return d

    data = {
        "departments": [dict_from_obj(d, ['id', 'name']) for d in departments],
        "subjects": [dict_from_obj(s, ['id', 'code', 'name']) for s in subjects],
        "users": [dict_from_obj(u, ['id', 'user_id', 'name', 'enrollment', 'role', 'semester', 'course_name', 'major_minor', 'password_hash', 'department_id', 'embedding']) for u in users],
        "routines": [dict_from_obj(r, ['id', 'day_of_week', 'start_time', 'end_time', 'semester', 'subject_id', 'teacher_id', 'department_id']) for r in routines]
    }
    
    return data

