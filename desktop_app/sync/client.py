import requests
import os
from database.session import SessionLocal
from database import crud
from utils.config import settings

BACKEND_URL = settings.BACKEND_SYNC_URL

def sync_data():
    db = SessionLocal()
    try:
        if not BACKEND_URL:
            return 0
            
        unsynced = crud.get_unsynced_records(db)
        if not unsynced:
            print("No records to sync.")
            return 0

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
        # Ensure trailing slash for the base sync endpoint
        request_url = BACKEND_URL if BACKEND_URL.endswith("/") else f"{BACKEND_URL}/"
        response = requests.post(request_url, json=payload)
        
        if response.status_code == 200:
            crud.mark_records_synced(db, record_ids)
            print(f"Successfully synced {len(record_ids)} records.")
            return len(record_ids)
        else:
            print(f"Sync failed: {response.text}")
            raise Exception(f"Server returned {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Error during sync: {e}")
        raise e
    finally:
        db.close()

def delete_user_cloud(admin_enroll, admin_pass, target_enroll):
    """Notify backend to delete a user from cloud."""
    try:
        base_url = BACKEND_URL.rstrip("/")
        url = f"{base_url}/delete-user"
        payload = {"admin_enrollment": admin_enroll, "admin_password": admin_pass, "target_enrollment": target_enroll}
        response = requests.post(url, json=payload)
        return response.status_code == 200
    except Exception: return False

def upsert_user_cloud(admin_enroll, admin_pass, user_data):
    try:
        base_url = BACKEND_URL.rstrip("/")
        url = f"{base_url}/upsert-user"
        payload = {"admin_enrollment": admin_enroll, "admin_password": admin_pass, "user_data": user_data}
        response = requests.post(url, json=payload)
        return response.status_code == 200
    except Exception: return False

def upsert_routine_cloud(admin_enroll, admin_pass, routine_data):
    try:
        base_url = BACKEND_URL.rstrip("/")
        url = f"{base_url}/upsert-routine"
        payload = {"admin_enrollment": admin_enroll, "admin_password": admin_pass, "routine_data": routine_data}
        response = requests.post(url, json=payload)
        return response.status_code == 200
    except Exception: return False

def delete_routine_cloud(admin_enroll, admin_pass, routine_id):
    try:
        base_url = BACKEND_URL.rstrip("/")
        url = f"{base_url}/delete-routine"
        payload = {"admin_enrollment": admin_enroll, "admin_password": admin_pass, "routine_id": routine_id}
        response = requests.post(url, json=payload)
        return response.status_code == 200
    except Exception: return False

def pull_master_data_from_backend(enrollment: str, password: str):
    db = SessionLocal()
    from database import models
    from datetime import datetime
    
    try:
        if not BACKEND_URL:
            return {"status": "error", "message": "Backend URL is not configured. Please check your .env file."}
            
        payload = {
            "enrollment": enrollment,
            "password": password
        }
        # Ensure we don't have double slashes if BACKEND_URL ends with one
        request_url = f"{BACKEND_URL.rstrip('/')}/master-data"
        resp = requests.post(request_url, json=payload)
        resp.raise_for_status()
        
        try:
            data = resp.json()
        except ValueError:
            # If it's not JSON, it might be an HTML error page or HuggingFace "sleeping" page
            if "text/html" in resp.headers.get("Content-Type", ""):
                return {"status": "error", "message": "Backend returned an HTML page instead of data. The server might be sleeping or down. Please try visiting the backend URL in your browser to wake it up."}
            return {"status": "error", "message": f"Invalid response from server: {resp.text[:100]}"}

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
