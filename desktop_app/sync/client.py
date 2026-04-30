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

if __name__ == "__main__":
    sync_data()
