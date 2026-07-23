from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey, Date, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(200), nullable=False)
    role = Column(String(20), nullable=False)
    real_name = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Building(Base):
    __tablename__ = "buildings"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    address = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    lanes = relationship("FireLane", back_populates="building", cascade="all, delete-orphan")


class FireLane(Base):
    __tablename__ = "fire_lanes"

    id = Column(Integer, primary_key=True, index=True)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)
    lane_number = Column(String(30), nullable=False)
    location_description = Column(Text, nullable=True)
    inspection_cycle_days = Column(Integer, nullable=False, default=7)
    min_passable_width = Column(Float, nullable=False, default=4.0)
    sign_check_rules = Column(Text, nullable=True)
    responsible_dept = Column(String(100), nullable=False)
    review_standard = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    building = relationship("Building", back_populates="lanes")
    inspections = relationship("InspectionRecord", back_populates="lane", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("building_id", "lane_number", name="uq_building_lane"),
    )


class InspectionRecord(Base):
    __tablename__ = "inspection_records"

    id = Column(Integer, primary_key=True, index=True)
    lane_id = Column(Integer, ForeignKey("fire_lanes.id"), nullable=False)
    inspector_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    cycle_start_date = Column(Date, nullable=False)
    cycle_end_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="待巡检")
    measured_width = Column(Float, nullable=True)
    is_occupied = Column(Boolean, nullable=True)
    obstruction_type = Column(String(100), nullable=True)
    sign_status = Column(String(20), nullable=True)
    floor_marking_status = Column(String(20), nullable=True)
    site_notes = Column(Text, nullable=True)
    risk_description = Column(Text, nullable=True)
    restoration_suggestion = Column(Text, nullable=True)
    required_completion_time = Column(DateTime, nullable=True)
    is_overdue = Column(Boolean, default=False)
    has_sign_anomaly = Column(Boolean, default=False)
    width_insufficient = Column(Boolean, default=False)
    dept_delay = Column(Boolean, default=False)
    building_anomaly_concentrated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lane = relationship("FireLane", back_populates="inspections")
    inspector = relationship("User", foreign_keys=[inspector_id])
    reviews = relationship("ReviewRecord", back_populates="inspection", cascade="all, delete-orphan", order_by="ReviewRecord.created_at")

    __table_args__ = (
        UniqueConstraint("lane_id", "cycle_start_date", "cycle_end_date", name="uq_lane_cycle"),
    )


class ReviewRecord(Base):
    __tablename__ = "review_records"

    id = Column(Integer, primary_key=True, index=True)
    inspection_id = Column(Integer, ForeignKey("inspection_records.id"), nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    review_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    restored_width = Column(Float, nullable=True)
    passage_restored = Column(Boolean, nullable=False, default=False)
    review_conclusion = Column(Text, nullable=True)
    risk_level = Column(String(10), nullable=False, default="中")
    closing_opinion = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    inspection = relationship("InspectionRecord", back_populates="reviews")
    reviewer = relationship("User", foreign_keys=[reviewer_id])
