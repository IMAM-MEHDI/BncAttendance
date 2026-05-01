from pydantic import BaseModel
from typing import List
from datetime import datetime

class AttendanceRecordBase(BaseModel):
    user_id: str
    device_id: str
    timestamp: datetime
    confidence: float

class SyncRequest(BaseModel):
    records: List[AttendanceRecordBase]

class MasterDataRequest(BaseModel):
    enrollment: str
    password: str
