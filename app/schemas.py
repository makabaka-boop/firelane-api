# -*- coding: utf-8 -*-
"""Pydantic 请求 / 响应模型。"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ------------------------- 认证 -------------------------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class LoginRequest(BaseModel):
    username: str
    password: str


# ------------------------- 用户 -------------------------
class UserCreate(BaseModel):
    username: str
    password: str
    role: str = Field(..., description="admin/inspector/reviewer")
    department: Optional[str] = None
    display_name: Optional[str] = None


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    department: Optional[str] = None
    display_name: Optional[str] = None

    class Config:
        from_attributes = True


# ------------------------- 楼宇 -------------------------
class BuildingCreate(BaseModel):
    name: str
    code: str


class BuildingOut(BaseModel):
    id: int
    name: str
    code: str

    class Config:
        from_attributes = True


# ------------------------- 消防通道 -------------------------
class FireLaneCreate(BaseModel):
    building_id: int
    lane_code: str
    location_desc: Optional[str] = None
    inspection_cycle_days: int = 7
    min_pass_width: float = 1.2
    sign_check_rule: Optional[str] = None
    responsible_dept: Optional[str] = None
    review_standard: Optional[str] = None


class FireLaneUpdate(BaseModel):
    lane_code: Optional[str] = None
    location_desc: Optional[str] = None
    inspection_cycle_days: Optional[int] = None
    min_pass_width: Optional[float] = None
    sign_check_rule: Optional[str] = None
    responsible_dept: Optional[str] = None
    review_standard: Optional[str] = None


class FireLaneOut(BaseModel):
    id: int
    building_id: int
    lane_code: str
    location_desc: Optional[str] = None
    inspection_cycle_days: int
    min_pass_width: float
    sign_check_rule: Optional[str] = None
    responsible_dept: Optional[str] = None
    review_standard: Optional[str] = None
    status: str

    class Config:
        from_attributes = True


# ------------------------- 巡检记录 -------------------------
class InspectionCreate(BaseModel):
    lane_id: int
    measured_width: Optional[float] = None
    is_occupied: bool = False
    occupation_type: Optional[str] = None
    sign_status: Optional[str] = Field(
        None, description="normal/abnormal/missing"
    )
    site_note: Optional[str] = None
    risk_desc: Optional[str] = None
    recovery_suggestion: Optional[str] = None
    required_finish_time: Optional[datetime] = None


class InspectionOut(BaseModel):
    id: int
    lane_id: int
    cycle_key: str
    inspector_id: int
    measured_width: Optional[float] = None
    is_occupied: bool
    occupation_type: Optional[str] = None
    sign_status: Optional[str] = None
    site_note: Optional[str] = None
    risk_desc: Optional[str] = None
    recovery_suggestion: Optional[str] = None
    required_finish_time: Optional[datetime] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ------------------------- 复核记录 -------------------------
class ReviewCreate(BaseModel):
    inspection_id: int
    restored_width: float = Field(..., description="实测恢复宽度，必填")
    is_recovered: bool
    conclusion: str = Field(..., min_length=1, description="复核结论，必填")
    risk_level: str = Field(..., description="low/medium/high/critical")
    close_opinion: Optional[str] = None


class ReviewOut(BaseModel):
    id: int
    inspection_id: int
    reviewer_id: int
    review_time: datetime
    restored_width: Optional[float] = None
    is_recovered: bool
    conclusion: Optional[str] = None
    risk_level: Optional[str] = None
    close_opinion: Optional[str] = None

    class Config:
        from_attributes = True


# ------------------------- 统计输出 -------------------------
class MessageOut(BaseModel):
    message: str
