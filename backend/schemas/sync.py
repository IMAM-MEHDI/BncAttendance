from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class AttendanceRecordBase(BaseModel):
    user_id: str
    device_id: str
    timestamp: datetime
    confidence: float
    routine_id: Optional[int] = None

class SyncRequest(BaseModel):
    records: List[AttendanceRecordBase]

class MasterDataRequest(BaseModel):
    enrollment: str
    password: str

class DeleteUserRequest(BaseModel):
    admin_enrollment: str
    admin_password: str
    target_enrollment: str

class UserUpsertRequest(BaseModel):
    admin_enrollment: str
    admin_password: str
    user_data: dict # Full user object data

class RoutineUpsertRequest(BaseModel):
    admin_enrollment: str
    admin_password: str
    routine_data: dict # Routine object data

class DeleteRoutineRequest(BaseModel):
    admin_enrollment: str
    admin_password: str
    routine_id: int
