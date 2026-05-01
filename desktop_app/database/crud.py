import datetime
import numpy as np
import bcrypt
from sqlalchemy.orm import Session
from database import models

# --- Auth Helpers ---
def hash_password(password: str):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str):
    if not hashed: return False
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

# --- Department CRUD ---
def create_department(db: Session, name: str):
    db_dept = models.Department(name=name)
    db.add(db_dept)
    db.commit()
    db.refresh(db_dept)
    return db_dept

def get_all_departments(db: Session):
    return db.query(models.Department).all()

def delete_department(db: Session, dept_id: int):
    db.query(models.Department).filter(models.Department.id == dept_id).delete()
    db.commit()

# --- Subject CRUD ---
def get_or_create_subject(db: Session, code: str, name: str):
    subject = db.query(models.Subject).filter(models.Subject.code == code).first()
    if not subject:
        subject = models.Subject(code=code, name=name)
        db.add(subject)
        db.commit()
        db.refresh(subject)
    return subject

def get_all_subjects(db: Session):
    return db.query(models.Subject).all()

# --- User CRUD ---
def get_user_by_enrollment(db: Session, enrollment: str):
    return db.query(models.User).filter(models.User.enrollment == enrollment).first()

def get_user_by_id(db: Session, user_id: str):
    return db.query(models.User).filter(models.User.user_id == user_id).first()

def create_user(db: Session, user_id: str, name: str, enrollment: str, 
                role: str = 'student', department_id: int = None, 
                semester: int = None, course_name: str = None, 
                major_minor: str = None, password: str = None,
                embedding: np.ndarray = None):
    
    embedding_bytes = embedding.tobytes() if embedding is not None else None
    pw_hash = hash_password(password) if password else None
    
    db_user = models.User(
        user_id=user_id, 
        name=name, 
        enrollment=enrollment, 
        role=role,
        department_id=department_id,
        semester=semester,
        course_name=course_name,
        major_minor=major_minor,
        password_hash=pw_hash,
        embedding=embedding_bytes
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def update_student(db: Session, enrollment: str, **kwargs):
    db.query(models.User).filter(models.User.enrollment == enrollment).update(kwargs)
    db.commit()

def delete_user(db: Session, enrollment: str):
    user = db.query(models.User).filter(models.User.enrollment == enrollment).first()
    if user:
        # Delete associated attendance records first
        db.query(models.AttendanceRecord).filter(models.AttendanceRecord.user_id == user.user_id).delete()
        db.delete(user)
        db.commit()
        return True
    return False

def get_all_users(db: Session, role: str = None):
    query = db.query(models.User)
    if role:
        query = query.filter(models.User.role == role)
    return query.all()

def get_students_by_dept_sem(db: Session, dept_id: int, sem: int):
    return db.query(models.User).filter(
        models.User.department_id == dept_id,
        models.User.semester == sem,
        models.User.role == 'student'
    ).all()

from datetime import datetime

# --- Routine CRUD ---
def create_routine(db: Session, day: str, start: str, end: str, subject_id: int,
                   semester: int, teacher_id: int, dept_id: int):
    
    # SQLite Time type requires Python datetime.time objects
    try:
        start_time = datetime.strptime(start, "%I:%M %p").time()
    except ValueError:
        start_time = datetime.strptime(start, "%H:%M").time() if ":" in start else None
        
    try:
        end_time = datetime.strptime(end, "%I:%M %p").time()
    except ValueError:
        end_time = datetime.strptime(end, "%H:%M").time() if ":" in end else None

    db_routine = models.Routine(
        day_of_week=day, start_time=start_time, end_time=end_time,
        subject_id=subject_id,
        semester=semester, teacher_id=teacher_id, department_id=dept_id
    )
    db.add(db_routine)
    db.commit()
    db.refresh(db_routine)
    return db_routine

def get_routines_by_dept(db: Session, dept_id: int):
    return db.query(models.Routine).filter(models.Routine.department_id == dept_id).all()

def delete_routine(db: Session, routine_id: int):
    db.query(models.Routine).filter(models.Routine.id == routine_id).delete()
    db.commit()

# --- Attendance Logic ---
def mark_attendance(db: Session, user_id: int, device_id: str, confidence: float, routine_id: int = None):
    # Get user to find department
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user: return {"status": "error", "message": "User not found"}

    routine = None
    if routine_id:
        routine = db.query(models.Routine).filter(models.Routine.id == routine_id).first()
    
    if not routine:
        # Find active routine (class happening now)
        from datetime import datetime
        now = datetime.now()
        day = now.strftime("%A")
        current_time = now.time()
        
        routine = db.query(models.Routine).filter(
            models.Routine.department_id == user.department_id,
            models.Routine.day_of_week == day,
            models.Routine.start_time <= current_time,
            models.Routine.end_time >= current_time
        ).first()

    if not routine:
        return {"status": "error", "message": "No active routine found for this time"}

    # Check if already marked for THIS specific routine today
    import datetime as dt
    # Use aware datetime for consistency
    today_start = datetime.combine(now.date(), dt.time.min).replace(tzinfo=dt.timezone.utc)
    
    existing = db.query(models.AttendanceRecord).filter(
        models.AttendanceRecord.user_id == user.user_id,
        models.AttendanceRecord.routine_id == routine.id,
        models.AttendanceRecord.timestamp >= today_start
    ).first()
    
    if existing:
        subject_name = routine.subject.name if routine.subject else "Class"
        print(f"Attendance skipped: {user.name} already marked today for {subject_name}")
        return {"status": "duplicate", "message": f"Already marked for {subject_name}"}

    record = models.AttendanceRecord(
        user_id=user.user_id, 
        device_id=device_id, 
        confidence=confidence,
        routine_id=routine.id,
        sync_status=False
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"status": "success", "message": "Attendance marked", "routine": routine.subject.name}

def get_unsynced_records(db: Session):
    return db.query(models.AttendanceRecord).filter(models.AttendanceRecord.sync_status == False).all()

def mark_records_synced(db: Session, record_ids: list):
    db.query(models.AttendanceRecord).filter(models.AttendanceRecord.id.in_(record_ids)).update({"sync_status": True}, synchronize_session=False)
    db.commit()

def get_filtered_attendance(db: Session, dept_id: int, semester: int = None, days: int = 30):
    from sqlalchemy.orm import joinedload
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    query = db.query(models.AttendanceRecord).options(
        joinedload(models.AttendanceRecord.user),
        joinedload(models.AttendanceRecord.routine).joinedload(models.Routine.subject)
    ).join(models.User)
    
    query = query.filter(models.User.department_id == dept_id)
    query = query.filter(models.AttendanceRecord.timestamp >= cutoff)
    
    if semester:
        query = query.filter(models.User.semester == semester)
        
    return query.order_by(models.AttendanceRecord.timestamp.desc()).all()

def promote_students(db: Session, dept_id: int, current_semester: int):
    # 1. Fetch all students in this dept and semester
    students = db.query(models.User).filter(
        models.User.department_id == dept_id,
        models.User.semester == current_semester,
        models.User.role == 'student'
    ).all()
    
    if not students:
        return 0
    
    student_user_ids = [s.user_id for s in students]
    
    # 2. Archive attendance records for these students
    # We only archive records that haven't been archived yet (though they should be gone if promoted)
    records = db.query(models.AttendanceRecord).filter(
        models.AttendanceRecord.user_id.in_(student_user_ids)
    ).all()
    
    history_entries = []
    for r in records:
        history_entries.append(models.AttendanceHistory(
            user_id=r.user_id,
            routine_id=r.routine_id,
            timestamp=r.timestamp,
            device_id=r.device_id,
            confidence=r.confidence,
            semester=current_semester
        ))
    
    if history_entries:
        db.bulk_save_objects(history_entries)
        
    # 3. Delete from current AttendanceRecord
    db.query(models.AttendanceRecord).filter(
        models.AttendanceRecord.user_id.in_(student_user_ids)
    ).delete(synchronize_session=False)
    
    # 4. Increment semester for students
    for s in students:
        s.semester += 1
        
    db.commit()
    return len(students)
