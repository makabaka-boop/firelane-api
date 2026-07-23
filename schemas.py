from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    real_name: Optional[str] = None
    user_id: int


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = Field(..., pattern="^(admin|inspector|reviewer)$")
    real_name: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    real_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class BuildingCreate(BaseModel):
    name: str
    address: Optional[str] = None


class BuildingUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None


class BuildingResponse(BaseModel):
    id: int
    name: str
    address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class FireLaneCreate(BaseModel):
    building_id: int
    lane_number: str
    location_description: Optional[str] = None
    inspection_cycle_days: int = 7
    min_passable_width: float = 4.0
    sign_check_rules: Optional[str] = None
    responsible_dept: str
    review_standard: Optional[str] = None


class FireLaneUpdate(BaseModel):
    lane_number: Optional[str] = None
    location_description: Optional[str] = None
    inspection_cycle_days: Optional[int] = None
    min_passable_width: Optional[float] = None
    sign_check_rules: Optional[str] = None
    responsible_dept: Optional[str] = None
    review_standard: Optional[str] = None


class FireLaneResponse(BaseModel):
    id: int
    building_id: int
    lane_number: str
    location_description: Optional[str] = None
    inspection_cycle_days: int
    min_passable_width: float
    sign_check_rules: Optional[str] = None
    responsible_dept: str
    review_standard: Optional[str] = None
    created_at: datetime
    building_name: Optional[str] = None

    class Config:
        from_attributes = True


class InspectionSubmit(BaseModel):
    lane_id: int
    cycle_start_date: date
    cycle_end_date: date
    measured_width: float
    is_occupied: bool
    obstruction_type: Optional[str] = None
    sign_status: str = Field(..., pattern="^(正常|损坏|缺失|遮挡)$")
    floor_marking_status: str = Field(..., pattern="^(正常|磨损|缺失)$")
    site_notes: Optional[str] = None
    risk_description: Optional[str] = None
    restoration_suggestion: Optional[str] = None
    required_completion_time: Optional[datetime] = None


class InspectionStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(待巡检|巡检中|通行受阻|恢复处理中|待复核|已关闭)$")


class InspectionResponse(BaseModel):
    id: int
    lane_id: int
    inspector_id: int
    inspector_name: Optional[str] = None
    cycle_start_date: date
    cycle_end_date: date
    status: str
    measured_width: Optional[float] = None
    is_occupied: Optional[bool] = None
    obstruction_type: Optional[str] = None
    sign_status: Optional[str] = None
    floor_marking_status: Optional[str] = None
    site_notes: Optional[str] = None
    risk_description: Optional[str] = None
    restoration_suggestion: Optional[str] = None
    required_completion_time: Optional[datetime] = None
    is_overdue: bool
    has_sign_anomaly: bool
    width_insufficient: bool
    dept_delay: bool
    building_anomaly_concentrated: bool
    lane_number: Optional[str] = None
    building_name: Optional[str] = None
    responsible_dept: Optional[str] = None
    review_conclusion: Optional[str] = None
    risk_level: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ReviewSubmit(BaseModel):
    inspection_id: int
    restored_width: Optional[float] = None
    passage_restored: bool
    review_conclusion: Optional[str] = None
    risk_level: str = Field(..., pattern="^(低|中|高|极高)$")
    closing_opinion: Optional[str] = None


class ReviewResponse(BaseModel):
    id: int
    inspection_id: int
    reviewer_id: int
    reviewer_name: Optional[str] = None
    review_time: datetime
    restored_width: Optional[float] = None
    passage_restored: bool
    review_conclusion: Optional[str] = None
    risk_level: str
    closing_opinion: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PaginatedResponse(BaseModel):
    total: int
    items: List[dict]
    page: int
    page_size: int
