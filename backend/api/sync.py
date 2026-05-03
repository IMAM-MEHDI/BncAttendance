from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Annotated
from database.session import SessionLocal
from schemas.sync import (
    SyncRequest, MasterDataRequest, DeleteUserRequest, 
    UserUpsertRequest, RoutineUpsertRequest, DeleteRoutineRequest
)
from database import models
import bcrypt

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/")
def sync_records(request: SyncRequest, db: Annotated[Session, Depends(get_db)]):
    """Receive attendance records from local devices and save to central DB."""
    try:
        new_records = []
        
        # Pre-fetch valid user_ids and routine_ids to avoid repeated DB lookups if batch is large
        # but for small batches, simple check is fine.
        for rec in request.records:
            # 1. Verify User exists
            exists = db.query(models.User).filter(models.User.user_id == rec.user_id).first()
            if not exists:
                print(f"Skipping record for non-existent user: {rec.user_id}")
                continue

            # 2. Verify Routine exists (if provided)
            if rec.routine_id:
                r_exists = db.query(models.Routine).filter(models.Routine.id == rec.routine_id).first()
                if not r_exists:
                    print(f"Skipping record for non-existent routine: {rec.routine_id}")
                    continue

            # Create new record object
            record = models.AttendanceRecord(
                user_id=rec.user_id,
                routine_id=rec.routine_id,
                timestamp=rec.timestamp,
                device_id=rec.device_id,
                confidence=rec.confidence,
                sync_status=True # It's now in the cloud
            )
            new_records.append(record)
            
        if new_records:
            db.add_all(new_records)
            db.commit()
            
        print(f"Successfully saved {len(new_records)} records to cloud. (Skipped {len(request.records) - len(new_records)})")
        return {"status": "success", "synced_count": len(new_records)}
    except Exception as e:
        db.rollback()
        print(f"Error during record sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/master-data")
def get_master_data(request: MasterDataRequest, db: Session = Depends(get_db)):
    # 1. Authenticate (Admin or HOD allowed)
    user = db.query(models.User).filter(models.User.enrollment == request.enrollment).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials or user not found.")
        
    if not bcrypt.checkpw(request.password.encode('utf-8'), user.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    if user.role not in ['admin', 'hod']:
        raise HTTPException(status_code=403, detail="Permission denied. Only Admins or HODs can pull master data.")

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

@router.post("/upsert-user")
def upsert_user(request: UserUpsertRequest, db: Session = Depends(get_db)):
    # Auth
    admin = db.query(models.User).filter(models.User.enrollment == request.admin_enrollment, models.User.role.in_(['admin', 'hod'])).first()
    if not admin or not bcrypt.checkpw(request.admin_password.encode('utf-8'), admin.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = request.user_data
    if 'embedding' in data and data['embedding']:
        data['embedding'] = bytes.fromhex(data['embedding'])

    # Use merge() — INSERT if PK absent, UPDATE if PK present. Eliminates UniqueViolation.
    user_obj = models.User(**data)
    db.merge(user_obj)
    db.commit()
    return {"status": "success"}

@router.post("/delete-user")
def delete_user(request: DeleteUserRequest, db: Session = Depends(get_db)):
    admin = db.query(models.User).filter(models.User.enrollment == request.admin_enrollment, models.User.role == 'admin').first()
    if not admin or not bcrypt.checkpw(request.admin_password.encode('utf-8'), admin.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = db.query(models.User).filter(models.User.enrollment == request.target_enrollment).first()
    if user:
        db.delete(user)
        db.commit()
    return {"status": "success"}

@router.post("/upsert-routine")
def upsert_routine(request: RoutineUpsertRequest, db: Session = Depends(get_db)):
    admin = db.query(models.User).filter(models.User.enrollment == request.admin_enrollment, models.User.role.in_(['admin', 'hod'])).first()
    if not admin or not bcrypt.checkpw(request.admin_password.encode('utf-8'), admin.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = request.routine_data
    from datetime import datetime as _dt
    if data.get('start_time') and isinstance(data['start_time'], str):
        data['start_time'] = _dt.strptime(data['start_time'], "%H:%M:%S").time()
    if data.get('end_time') and isinstance(data['end_time'], str):
        data['end_time'] = _dt.strptime(data['end_time'], "%H:%M:%S").time()

    # Use merge() — INSERT if PK absent, UPDATE if PK present.
    routine_obj = models.Routine(**data)
    db.merge(routine_obj)
    db.commit()
    return {"status": "success"}

@router.post("/delete-routine")
def delete_routine(request: DeleteRoutineRequest, db: Session = Depends(get_db)):
    admin = db.query(models.User).filter(models.User.enrollment == request.admin_enrollment, models.User.role.in_(['admin', 'hod'])).first()
    if not admin or not bcrypt.checkpw(request.admin_password.encode('utf-8'), admin.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Unauthorized")

    routine = db.query(models.Routine).filter(models.Routine.id == request.routine_id).first()
    if routine:
        db.delete(routine)
        db.commit()
    return {"status": "success"}

@router.post("/bulk-master-push")
def bulk_master_push(request: dict, db: Session = Depends(get_db)):
    """Bulk push Departments, Subjects, Users, and Routines from local to cloud."""
    # 1. Auth
    admin_enroll = request.get("admin_enrollment")
    admin_pass = request.get("admin_password")
    admin = db.query(models.User).filter(models.User.enrollment == admin_enroll, models.User.role.in_(['admin', 'hod'])).first()
    if not admin or not bcrypt.checkpw(admin_pass.encode('utf-8'), admin.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = request.get("data", {})
    
    # 2. Sync Departments
    for dept in data.get("departments", []):
        existing = db.query(models.Department).filter(models.Department.id == dept['id']).first()
        if existing: existing.name = dept['name']
        else: db.add(models.Department(**dept))
    db.flush()

    # 3. Sync Subjects
    for sub in data.get("subjects", []):
        existing = db.query(models.Subject).filter(models.Subject.id == sub['id']).first()
        if existing: 
            existing.code = sub['code']
            existing.name = sub['name']
        else: db.add(models.Subject(**sub))
    db.flush()

    # 4. Sync Users
    for u in data.get("users", []):
        if u.get('embedding'):
            u['embedding'] = bytes.fromhex(u['embedding'])
        
        existing = db.query(models.User).filter(models.User.enrollment == u['enrollment']).first()
        if existing:
            for k, v in u.items(): setattr(existing, k, v)
        else:
            db.add(models.User(**u))
    db.flush()

    # 5. Sync Routines
    from datetime import datetime
    for r in data.get("routines", []):
        if r.get("start_time") and isinstance(r["start_time"], str):
            r["start_time"] = datetime.strptime(r["start_time"], "%H:%M:%S").time()
        if r.get("end_time") and isinstance(r["end_time"], str):
            r["end_time"] = datetime.strptime(r["end_time"], "%H:%M:%S").time()
            
        existing = db.query(models.Routine).filter(models.Routine.id == r['id']).first()
        if existing:
            for k, v in r.items(): setattr(existing, k, v)
        else:
            db.add(models.Routine(**r))
    
    db.commit()
    return {"status": "success", "message": "Cloud database synchronized successfully!"}
