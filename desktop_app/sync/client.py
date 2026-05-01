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

def pull_master_data_from_supabase(supabase_url: str, supabase_key: str):
    db = SessionLocal()
    from database import models
    from datetime import datetime
    
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }
    
    try:
        # 1. Departments
        resp = requests.get(f"{supabase_url}/rest/v1/departments", headers=headers)
        resp.raise_for_status()
        for row in resp.json():
            db.merge(models.Department(**row))
        db.commit()
        
        # 2. Subjects
        resp = requests.get(f"{supabase_url}/rest/v1/subjects", headers=headers)
        resp.raise_for_status()
        for row in resp.json():
            db.merge(models.Subject(**row))
        db.commit()
        
        # 3. Users
        resp = requests.get(f"{supabase_url}/rest/v1/users", headers=headers)
        resp.raise_for_status()
        for row in resp.json():
            if row.get("embedding") and isinstance(row["embedding"], str):
                emb_str = row["embedding"]
                if emb_str.startswith("\\x"):
                    emb_str = emb_str[2:]
                row["embedding"] = bytes.fromhex(emb_str)
            db.merge(models.User(**row))
        db.commit()
        
        # 4. Routines
        resp = requests.get(f"{supabase_url}/rest/v1/routines", headers=headers)
        resp.raise_for_status()
        for row in resp.json():
            if row.get("start_time") and isinstance(row["start_time"], str):
                row["start_time"] = datetime.strptime(row["start_time"], "%H:%M:%S").time()
            if row.get("end_time") and isinstance(row["end_time"], str):
                row["end_time"] = datetime.strptime(row["end_time"], "%H:%M:%S").time()
            db.merge(models.Routine(**row))
        db.commit()
        
        return {"status": "success", "message": "Master database synchronized from Cloud successfully!"}
        
    except requests.exceptions.HTTPError as he:
        db.rollback()
        return {"status": "error", "message": f"HTTP Error {he.response.status_code}: {he.response.text}"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        db.close()

if __name__ == "__main__":
    sync_data()
