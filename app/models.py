from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False)  # admin / inspector / reviewer
    real_name = Column(String(64))
    department = Column(String(128))
    created_at = Column(DateTime, default=datetime.utcnow)


class Building(Base):
    __tablename__ = "buildings"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(32), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    address = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

    lanes = relationship("FireLane", back_populates="building", cascade="all, delete-orphan")


class FireLane(Base):
    __tablename__ = "fire_lanes"
    id = Column(Integer, primary_key=True, index=True)
    building_id = Column(Integer, ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False, index=True)
    lane_code = Column(String(32), nullable=False, index=True)
    location_desc = Column(String(255))
    inspection_cycle_days = Column(Integer, nullable=False, default=7)
    min_width = Column(Float, nullable=False, default=4.0)  # 最小通行宽度(米)
    sign_rule = Column(Text)        # 指示牌检查规则
    dept = Column(String(128))      # 责任部门
    review_standard = Column(Text)  # 复核标准
    created_at = Column(DateTime, default=datetime.utcnow)

    building = relationship("Building", back_populates="lanes")
    inspections = relationship("InspectionRecord", back_populates="lane", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("building_id", "lane_code", name="uq_lane_building_code"),
    )


class InspectionRecord(Base):
    __tablename__ = "inspection_records"
    id = Column(Integer, primary_key=True, index=True)
    lane_id = Column(Integer, ForeignKey("fire_lanes.id", ondelete="CASCADE"), nullable=False, index=True)
    cycle_start = Column(DateTime, nullable=False)  # 巡检周期开始
    cycle_end = Column(DateTime, nullable=False)    # 巡检周期结束
    inspector_id = Column(Integer, ForeignKey("users.id"), index=True)

    status = Column(String(24), nullable=False, default="pending", index=True)
    # pending 待巡检 / inspecting 巡检中 / blocked 通行受阻 / recovering 恢复处理中 / to_review 待复核 / closed 已关闭

    measured_width = Column(Float)           # 实测宽度
    is_occupied = Column(Boolean)            # 是否占用
    obstacle_type = Column(String(128))      # 占用物类型
    sign_status = Column(String(64))         # 指示牌/地贴状态 (normal/damaged/missing/obscured/...)
    site_remark = Column(Text)               # 现场备注
    risk_desc = Column(Text)                 # 风险说明
    recovery_suggestion = Column(Text)       # 通行恢复建议
    required_deadline = Column(DateTime)     # 要求完成时间

    started_at = Column(DateTime)            # 巡检员开始时间
    submitted_at = Column(DateTime)          # 巡检员提交时间
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lane = relationship("FireLane", back_populates="inspections")
    inspector = relationship("User", foreign_keys=[inspector_id])
    reviews = relationship("ReviewRecord", back_populates="inspection", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("lane_id", "cycle_start", name="uq_lane_cycle"),
        Index("ix_inspection_lane_cycle", "lane_id", "cycle_start"),
    )


class ReviewRecord(Base):
    __tablename__ = "review_records"
    id = Column(Integer, primary_key=True, index=True)
    inspection_id = Column(Integer, ForeignKey("inspection_records.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    review_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    recovered_width = Column(Float)          # 实测恢复宽度
    is_recovered = Column(Boolean)           # 通行是否恢复
    conclusion = Column(Text)                # 复核结论
    risk_level = Column(String(16), index=True)  # low / medium / high / critical
    close_opinion = Column(Text)             # 关闭意见
    passed = Column(Boolean, default=True)   # 复核是否通过

    created_at = Column(DateTime, default=datetime.utcnow)

    inspection = relationship("InspectionRecord", back_populates="reviews")
    reviewer = relationship("User", foreign_keys=[reviewer_id])
