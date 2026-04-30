from fastapi import APIRouter
from schemas.sync import SyncRequest

router = APIRouter()

@router.post("/")
def sync_records(request: SyncRequest):
    # Logic to insert into central database would go here
    # For now, just print and return success
    print(f"Received {len(request.records)} records to sync.")
    return {"status": "success", "synced_count": len(request.records)}
