import requests
import os
from database.session import SessionLocal
from database import crud
from utils.config import settings

BACKEND_URL = settings.BACKEND_SYNC_URL

def sync_data():
    db = SessionLocal()
    try:
        unsynced = crud.get_unsynced_records(db)
        if not unsynced:
            print("No records to sync.")
            return

        records_data = []
        record_ids = []
        for r in unsynced:
            records_data.append({
                "user_id": r.user_id,
                "device_id": r.device_id,
                "timestamp": r.timestamp.isoformat(),
                "confidence": r.confidence,
                "routine_id": r.routine_id
            })
            record_ids.append(r.id)

        payload = {"records": records_data}
        response = requests.post(BACKEND_URL, json=payload)
        
        if response.status_code == 200:
            crud.mark_records_synced(db, record_ids)
            print(f"Successfully synced {len(record_ids)} records.")
        else:
            print(f"Sync failed: {response.text}")
    except Exception as e:
        print(f"Error during sync: {e}")
    finally:
        db.close()

def pull_master_data_from_backend(enrollment: str, password: str):
    db = SessionLocal()
    from database import models
    from datetime import datetime
    
    try:
        payload = {
            "enrollment": enrollment,
            "password": password
        }
        resp = requests.post(f"{BACKEND_URL}/master-data", json=payload)
        resp.raise_for_status()
        data = resp.json()

        # 1. Departments
        for row in data.get("departments", []):
            db.merge(models.Department(**row))
        db.commit()
        
        # 2. Subjects
        for row in data.get("subjects", []):
            db.merge(models.Subject(**row))
        db.commit()
        
        # 3. Users
        for row in data.get("users", []):
            if row.get("embedding") and isinstance(row["embedding"], str):
                row["embedding"] = bytes.fromhex(row["embedding"])
            db.merge(models.User(**row))
        db.commit()
        
        # 4. Routines
        for row in data.get("routines", []):
            if row.get("start_time") and isinstance(row["start_time"], str):
                row["start_time"] = datetime.strptime(row["start_time"], "%H:%M:%S").time()
            if row.get("end_time") and isinstance(row["end_time"], str):
                row["end_time"] = datetime.strptime(row["end_time"], "%H:%M:%S").time()
            db.merge(models.Routine(**row))
        db.commit()
        
        return {"status": "success", "message": "Master database synchronized from Backend successfully!"}
        
    except requests.exceptions.HTTPError as he:
        db.rollback()
        error_detail = he.response.json().get("detail", he.response.text) if he.response.content else he.response.text
        return {"status": "error", "message": f"HTTP Error {he.response.status_code}: {error_detail}"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        db.close()

if __name__ == "__main__":
    sync_data()
