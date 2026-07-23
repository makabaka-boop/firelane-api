from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ---- Auth ----
class LoginIn(BaseModel):
    username: str
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    real_name: Optional[str] = None

class UserCreate(BaseModel):
    username: str
    password: str
    role: str = Field(..., pattern="^(admin|inspector|reviewer)$")
    real_name: Optional[str] = None
    department: Optional[str] = None

class UserOut(BaseModel):
    id: int
    username: str
    role: str
    real_name: Optional[str] = None
    department: Optional[str] = None
    class Config: from_attributes = True


# ---- Building ----
class BuildingIn(BaseModel):
    code: str
    name: str
    address: Optional[str] = None

class BuildingOut(BuildingIn):
    id: int
    class Config: from_attributes = True


# ---- FireLane ----
class FireLaneIn(BaseModel):
    building_id: int
    lane_code: str
    location_desc: Optional[str] = None
    inspection_cycle_days: int = 7
    min_width: float = 4.0
    sign_rule: Optional[str] = None
    dept: Optional[str] = None
    review_standard: Optional[str] = None

class FireLaneOut(BaseModel):
    id: int
    building_id: int
    lane_code: str
    location_desc: Optional[str] = None
    inspection_cycle_days: int
    min_width: float
    sign_rule: Optional[str] = None
    dept: Optional[str] = None
    review_standard: Optional[str] = None
    building_name: Optional[str] = None
    class Config: from_attributes = True


# ---- Inspection ----
class InspectionStart(BaseModel):
    lane_id: int
    cycle_start: datetime
    cycle_end: datetime

class InspectionSubmit(BaseModel):
    measured_width: float
    is_occupied: bool
    obstacle_type: Optional[str] = None
    sign_status: Optional[str] = None
    site_remark: Optional[str] = None
    risk_desc: Optional[str] = None
    recovery_suggestion: Optional[str] = None
    required_deadline: Optional[datetime] = None

class StatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|inspecting|blocked|recovering|to_review|closed)$")
    remark: Optional[str] = None

class ReviewIn(BaseModel):
    recovered_width: float
    is_recovered: bool
    conclusion: Optional[str] = None
    risk_level: str = Field(..., pattern="^(low|medium|high|critical)$")
    close_opinion: Optional[str] = None
    passed: bool = True

class ReviewOut(BaseModel):
    id: int
    inspection_id: int
    reviewer_id: int
    reviewer_name: Optional[str] = None
    review_time: datetime
    recovered_width: Optional[float] = None
    is_recovered: Optional[bool] = None
    conclusion: Optional[str] = None
    risk_level: Optional[str] = None
    close_opinion: Optional[str] = None
    passed: bool
    class Config: from_attributes = True

class InspectionOut(BaseModel):
    id: int
    lane_id: int
    lane_code: Optional[str] = None
    building_id: Optional[int] = None
    building_name: Optional[str] = None
    dept: Optional[str] = None
    min_width: Optional[float] = None
    cycle_start: datetime
    cycle_end: datetime
    inspector_id: Optional[int] = None
    inspector_name: Optional[str] = None
    status: str
    measured_width: Optional[float] = None
    is_occupied: Optional[bool] = None
    obstacle_type: Optional[str] = None
    sign_status: Optional[str] = None
    site_remark: Optional[str] = None
    risk_desc: Optional[str] = None
    recovery_suggestion: Optional[str] = None
    required_deadline: Optional[datetime] = None
    started_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    latest_review: Optional[ReviewOut] = None
    anomalies: Optional[List[str]] = None
    class Config: from_attributes = True


# ---- Stats ----
class HighRiskItem(BaseModel):
    lane_id: int
    lane_code: Optional[str] = None
    building_name: Optional[str] = None
    location_desc: Optional[str] = None
    dept: Optional[str] = None
    risk_count: int
    latest_risk_level: Optional[str] = None
    latest_status: Optional[str] = None

class RecoveryRate(BaseModel):
    total_blocked: int
    recovered: int
    recovery_rate: float

class BuildingAnomaly(BaseModel):
    building_id: int
    building_name: str
    blocked_count: int
    recovering_count: int
    to_review_count: int
    total_anomaly: int
    lanes: List[str]
