# -*- coding: utf-8 -*-
"""SQLAlchemy ORM 模型与状态、角色枚举定义。"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


# ------------------------- 枚举常量 -------------------------
class Role:
    """账号角色。"""

    ADMIN = "admin"        # 管理员
    INSPECTOR = "inspector"  # 巡检员
    REVIEWER = "reviewer"    # 复核员
    ALL = {ADMIN, INSPECTOR, REVIEWER}


class LaneStatus:
    """消防通道 / 巡检单状态机取值。"""

    PENDING = "pending"        # 待巡检
    INSPECTING = "inspecting"  # 巡检中
    BLOCKED = "blocked"        # 通行受阻
    RECOVERING = "recovering"  # 恢复处理中
    TO_REVIEW = "to_review"    # 待复核
    CLOSED = "closed"          # 已关闭
    ALL = {PENDING, INSPECTING, BLOCKED, RECOVERING, TO_REVIEW, CLOSED}


class RiskLevel:
    """风险等级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    ALL = {LOW, MEDIUM, HIGH, CRITICAL}
    # 排序权重，用于高风险排行
    WEIGHT = {LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4}


# ------------------------- 模型 -------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(16), nullable=False)          # admin/inspector/reviewer
    department = Column(String(128), nullable=True)    # 所属/责任部门
    display_name = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Building(Base):
    __tablename__ = "buildings"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)          # 楼宇名称
    code = Column(String(64), unique=True, nullable=False)  # 楼宇编码
    created_at = Column(DateTime, default=datetime.utcnow)

    lanes = relationship("FireLane", back_populates="building")


class FireLane(Base):
    """消防通道配置（管理员维护）。"""

    __tablename__ = "fire_lanes"
    __table_args__ = (
        # 同一楼宇下通道编号不可重复
        UniqueConstraint("building_id", "lane_code", name="uq_building_lane_code"),
    )

    id = Column(Integer, primary_key=True, index=True)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)
    lane_code = Column(String(64), nullable=False)             # 消防通道编号
    location_desc = Column(String(256), nullable=True)         # 通道位置描述
    inspection_cycle_days = Column(Integer, nullable=False, default=7)  # 巡检周期(天)
    min_pass_width = Column(Float, nullable=False, default=1.2)  # 最小通行宽度(米)
    sign_check_rule = Column(Text, nullable=True)              # 指示牌检查规则
    responsible_dept = Column(String(128), nullable=True)      # 责任部门
    review_standard = Column(Text, nullable=True)              # 复核标准
    status = Column(String(16), nullable=False, default=LaneStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)

    building = relationship("Building", back_populates="lanes")
    inspections = relationship("InspectionRecord", back_populates="lane")


class InspectionRecord(Base):
    """巡检记录（巡检员提交）。"""

    __tablename__ = "inspection_records"
    __table_args__ = (
        # 同一消防通道同一巡检周期不可重复创建记录
        UniqueConstraint("lane_id", "cycle_key", name="uq_lane_cycle"),
    )

    id = Column(Integer, primary_key=True, index=True)
    lane_id = Column(Integer, ForeignKey("fire_lanes.id"), nullable=False)
    cycle_key = Column(String(32), nullable=False)  # 巡检周期标识（周期窗口索引）
    inspector_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    measured_width = Column(Float, nullable=True)        # 通道实测宽度
    is_occupied = Column(Boolean, nullable=False, default=False)  # 是否占用
    occupation_type = Column(String(128), nullable=True)  # 占用物类型
    sign_status = Column(String(64), nullable=True)       # 指示牌/地贴状态 normal/abnormal/missing
    site_note = Column(Text, nullable=True)               # 现场备注
    risk_desc = Column(Text, nullable=True)               # 风险说明
    recovery_suggestion = Column(Text, nullable=True)     # 通行恢复建议
    required_finish_time = Column(DateTime, nullable=True)  # 要求完成时间

    status = Column(String(16), nullable=False, default=LaneStatus.INSPECTING)
    created_at = Column(DateTime, default=datetime.utcnow)

    lane = relationship("FireLane", back_populates="inspections")
    reviews = relationship("ReviewRecord", back_populates="inspection")


class ReviewRecord(Base):
    """复核记录（复核员记录）。一条巡检记录可有多次复核历史。"""

    __tablename__ = "review_records"

    id = Column(Integer, primary_key=True, index=True)
    inspection_id = Column(Integer, ForeignKey("inspection_records.id"), nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    review_time = Column(DateTime, nullable=False, default=datetime.utcnow)  # 复核时间
    restored_width = Column(Float, nullable=True)     # 实测恢复宽度
    is_recovered = Column(Boolean, nullable=False, default=False)  # 通行是否恢复
    conclusion = Column(Text, nullable=True)          # 复核结论
    risk_level = Column(String(16), nullable=True)    # 风险等级
    close_opinion = Column(Text, nullable=True)       # 关闭意见
    created_at = Column(DateTime, default=datetime.utcnow)

    inspection = relationship("InspectionRecord", back_populates="reviews")
