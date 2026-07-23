from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from datetime import datetime, date, timedelta
from typing import Optional, List
import math

from database import engine, get_db, init_db
from models import User, Building, FireLane, InspectionRecord, ReviewRecord
from schemas import (
    LoginRequest, TokenResponse, UserCreate, UserResponse,
    BuildingCreate, BuildingUpdate, BuildingResponse,
    FireLaneCreate, FireLaneUpdate, FireLaneResponse,
    InspectionSubmit, InspectionStatusUpdate, InspectionResponse,
    ReviewSubmit, ReviewResponse, PaginatedResponse
)
from auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, require_roles
)

app = FastAPI(title="园区消防通道安全巡检与通行风险闭环管理系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VALID_STATUSES = ["待巡检", "巡检中", "通行受阻", "恢复处理中", "待复核", "已关闭"]
RISK_LEVELS = ["低", "中", "高", "极高"]
SIGN_STATUSES = ["正常", "损坏", "缺失", "遮挡"]
FLOOR_MARKING_STATUSES = ["正常", "磨损", "缺失"]
OCCUPATION_TYPES = ["车辆违停", "杂物堆放", "违章搭建", "经营占道", "施工占用", "其他"]


def init_seed_data(db: Session):
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        admin_user = User(
            username="admin",
            password_hash=hash_password("admin123"),
            role="admin",
            real_name="系管理员"
        )
        inspector = User(
            username="inspector",
            password_hash=hash_password("inspect123"),
            role="inspector",
            real_name="巡检员"
        )
        reviewer = User(
            username="reviewer",
            password_hash=hash_password("review123"),
            role="reviewer",
            real_name="复核员"
        )
        db.add_all([admin_user, inspector, reviewer])
        db.commit()


@app.on_event("startup")
def startup():
    init_db()
    db = next(get_db())
    init_seed_data(db)
    db.close()


# ==================== 认证接口 ====================

@app.post("/api/auth/login", response_model=TokenResponse, tags=["认证"])
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token(data={"sub": user.username, "user_id": user.id, "role": user.role})
    return TokenResponse(access_token=token, role=user.role, real_name=user.real_name, user_id=user.id)


@app.get("/api/auth/me", tags=["认证"])
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "real_name": current_user.real_name
    }


# ==================== 管理员：用户管理 ====================

@app.post("/api/admin/users", response_model=UserResponse, tags=["管理员-用户管理"])
def create_user(req: UserCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    exists = db.query(User).filter(User.username == req.username).first()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        role=req.role,
        real_name=req.real_name
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get("/api/admin/users", response_model=List[UserResponse], tags=["管理员-用户管理"])
def list_users(db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    return db.query(User).all()


# ==================== 管理员：楼宇管理 ====================

@app.post("/api/admin/buildings", response_model=BuildingResponse, tags=["管理员-楼宇管理"])
def create_building(req: BuildingCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    b = Building(name=req.name, address=req.address)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


@app.get("/api/admin/buildings", response_model=List[BuildingResponse], tags=["管理员-楼宇管理"])
def list_buildings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Building).all()


@app.put("/api/admin/buildings/{building_id}", response_model=BuildingResponse, tags=["管理员-楼宇管理"])
def update_building(building_id: int, req: BuildingUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    b = db.query(Building).filter(Building.id == building_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="楼宇不存在")
    if req.name is not None:
        b.name = req.name
    if req.address is not None:
        b.address = req.address
    db.commit()
    db.refresh(b)
    return b


@app.delete("/api/admin/buildings/{building_id}", tags=["管理员-楼宇管理"])
def delete_building(building_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    b = db.query(Building).filter(Building.id == building_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="楼宇不存在")
    db.delete(b)
    db.commit()
    return {"message": "删除成功"}


# ==================== 管理员：消防通道管理 ====================

@app.post("/api/admin/lanes", response_model=FireLaneResponse, tags=["管理员-通道管理"])
def create_lane(req: FireLaneCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    building = db.query(Building).filter(Building.id == req.building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="楼宇不存在")
    exists = db.query(FireLane).filter(
        FireLane.building_id == req.building_id,
        FireLane.lane_number == req.lane_number
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="该楼宇下通道编号已存在")
    lane = FireLane(**req.model_dump())
    db.add(lane)
    db.commit()
    db.refresh(lane)
    result = FireLaneResponse.model_validate(lane)
    result.building_name = lane.building.name
    return result


@app.get("/api/admin/lanes", tags=["管理员-通道管理"])
def list_lanes(
    building_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(FireLane)
    if building_id:
        q = q.filter(FireLane.building_id == building_id)
    lanes = q.all()
    result = []
    for lane in lanes:
        item = {
            "id": lane.id,
            "building_id": lane.building_id,
            "building_name": lane.building.name,
            "lane_number": lane.lane_number,
            "location_description": lane.location_description,
            "inspection_cycle_days": lane.inspection_cycle_days,
            "min_passable_width": lane.min_passable_width,
            "sign_check_rules": lane.sign_check_rules,
            "responsible_dept": lane.responsible_dept,
            "review_standard": lane.review_standard,
            "created_at": lane.created_at.isoformat() if lane.created_at else None
        }
        result.append(item)
    return result


@app.put("/api/admin/lanes/{lane_id}", tags=["管理员-通道管理"])
def update_lane(lane_id: int, req: FireLaneUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    lane = db.query(FireLane).filter(FireLane.id == lane_id).first()
    if not lane:
        raise HTTPException(status_code=404, detail="消防通道不存在")
    data = req.model_dump(exclude_unset=True)
    new_lane_number = data.get("lane_number", lane.lane_number)
    new_building_id = data.get("building_id", lane.building_id)
    if new_lane_number != lane.lane_number or new_building_id != lane.building_id:
        dup = db.query(FireLane).filter(
            FireLane.building_id == new_building_id,
            FireLane.lane_number == new_lane_number,
            FireLane.id != lane_id
        ).first()
        if dup:
            raise HTTPException(status_code=400, detail="该楼宇下通道编号已存在，请使用其他编号")
    for k, v in data.items():
        setattr(lane, k, v)
    db.commit()
    db.refresh(lane)
    result = FireLaneResponse.model_validate(lane)
    result.building_name = lane.building.name
    return result


@app.delete("/api/admin/lanes/{lane_id}", tags=["管理员-通道管理"])
def delete_lane(lane_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    lane = db.query(FireLane).filter(FireLane.id == lane_id).first()
    if not lane:
        raise HTTPException(status_code=404, detail="消防通道不存在")
    db.delete(lane)
    db.commit()
    return {"message": "删除成功"}


# ==================== 巡检员：巡检接口 ====================

def run_auto_detection(db: Session, record: InspectionRecord):
    now = datetime.utcnow()

    if record.required_completion_time and now > record.required_completion_time and record.status != "已关闭":
        record.is_overdue = True
        record.dept_delay = True
    else:
        record.is_overdue = False

    if record.sign_status in ("损坏", "缺失", "遮挡") or record.floor_marking_status in ("磨损", "缺失"):
        record.has_sign_anomaly = True
    else:
        record.has_sign_anomaly = False

    lane = db.query(FireLane).filter(FireLane.id == record.lane_id).first()
    if lane and record.measured_width is not None and record.measured_width < lane.min_passable_width:
        record.width_insufficient = True
    else:
        record.width_insufficient = False

    if lane:
        recent_count = db.query(func.count(InspectionRecord.id)).filter(
            InspectionRecord.lane_id.in_(
                db.query(FireLane.id).filter(FireLane.building_id == lane.building_id)
            ),
            InspectionRecord.is_occupied == True,
            InspectionRecord.created_at >= now - timedelta(days=30)
        ).scalar()
        record.building_anomaly_concentrated = recent_count >= 3
    else:
        record.building_anomaly_concentrated = False

    db.commit()


@app.post("/api/inspections", tags=["巡检员-巡检"])
def submit_inspection(
    req: InspectionSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("inspector", "admin"))
):
    lane = db.query(FireLane).filter(FireLane.id == req.lane_id).first()
    if not lane:
        raise HTTPException(status_code=404, detail="消防通道不存在")

    duplicate = db.query(InspectionRecord).filter(
        InspectionRecord.lane_id == req.lane_id,
        InspectionRecord.cycle_start_date == req.cycle_start_date,
        InspectionRecord.cycle_end_date == req.cycle_end_date
    ).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="该通道在当前巡检周期已有记录，不可重复创建")

    initial_status = "通行受阻" if req.is_occupied else "巡检中"

    record = InspectionRecord(
        lane_id=req.lane_id,
        inspector_id=current_user.id,
        cycle_start_date=req.cycle_start_date,
        cycle_end_date=req.cycle_end_date,
        status=initial_status,
        measured_width=req.measured_width,
        is_occupied=req.is_occupied,
        obstruction_type=req.obstruction_type,
        sign_status=req.sign_status,
        floor_marking_status=req.floor_marking_status,
        site_notes=req.site_notes,
        risk_description=req.risk_description,
        restoration_suggestion=req.restoration_suggestion,
        required_completion_time=req.required_completion_time
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    run_auto_detection(db, record)

    return format_inspection(record, db)


@app.put("/api/inspections/{record_id}/status", tags=["巡检员-巡检"])
def update_inspection_status(
    record_id: int,
    req: InspectionStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("inspector", "reviewer", "admin"))
):
    record = db.query(InspectionRecord).filter(InspectionRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="巡检记录不存在")

    valid_transitions = {
        "待巡检": ["巡检中"],
        "巡检中": ["通行受阻", "待复核", "已关闭"],
        "通行受阻": ["恢复处理中"],
        "恢复处理中": ["待复核"],
        "待复核": ["已关闭", "恢复处理中"],
        "已关闭": []
    }
    if req.status not in valid_transitions.get(record.status, []):
        raise HTTPException(status_code=400, detail=f"不允许从 {record.status} 流转到 {req.status}")

    record.status = req.status
    db.commit()
    db.refresh(record)
    return format_inspection(record, db)


@app.put("/api/inspections/{record_id}", tags=["巡检员-巡检"])
def update_inspection(
    record_id: int,
    req: InspectionSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("inspector", "admin"))
):
    record = db.query(InspectionRecord).filter(InspectionRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="巡检记录不存在")

    for k, v in req.model_dump(exclude={"lane_id", "cycle_start_date", "cycle_end_date"}).items():
        setattr(record, k, v)

    if req.is_occupied:
        if record.status in ("待巡检", "巡检中"):
            record.status = "通行受阻"
    else:
        if record.status == "通行受阻":
            record.status = "恢复处理中"

    db.commit()
    db.refresh(record)
    run_auto_detection(db, record)
    return format_inspection(record, db)


# ==================== 复核员：复核接口 ====================

@app.post("/api/reviews", tags=["复核员-复核"])
def submit_review(
    req: ReviewSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("reviewer", "admin"))
):
    inspection = db.query(InspectionRecord).filter(InspectionRecord.id == req.inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="巡检记录不存在")

    if inspection.status != "待复核":
        raise HTTPException(status_code=400, detail=f"当前状态为 {inspection.status}，不可提交复核")

    if not req.review_conclusion or req.review_conclusion.strip() == "":
        raise HTTPException(status_code=400, detail="复核结论不可为空")

    lane = db.query(FireLane).filter(FireLane.id == inspection.lane_id).first()

    if req.passage_restored:
        if req.restored_width is None:
            raise HTTPException(status_code=400, detail="复核通过关闭记录时必须填写恢复后的实际通行宽度")
        if lane and req.restored_width < lane.min_passable_width:
            inspection.width_insufficient = True
            inspection.status = "恢复处理中"
            review = ReviewRecord(
                inspection_id=req.inspection_id,
                reviewer_id=current_user.id,
                review_time=datetime.utcnow(),
                restored_width=req.restored_width,
                passage_restored=False,
                review_conclusion=req.review_conclusion,
                risk_level=req.risk_level,
                closing_opinion=req.closing_opinion or f"恢复宽度不达标（最小要求{lane.min_passable_width}m），退回整改"
            )
            db.add(review)
            db.commit()
            db.refresh(review)
            raise HTTPException(status_code=400, detail=f"恢复宽度不达标（最小要求 {lane.min_passable_width}m），已退回恢复处理中")
    else:
        if req.restored_width is not None and lane and req.restored_width < lane.min_passable_width:
            inspection.width_insufficient = True
        inspection.status = "恢复处理中"

        review = ReviewRecord(
            inspection_id=req.inspection_id,
            reviewer_id=current_user.id,
            review_time=datetime.utcnow(),
            restored_width=req.restored_width,
            passage_restored=False,
            review_conclusion=req.review_conclusion,
            risk_level=req.risk_level,
            closing_opinion=req.closing_opinion or "复核未通过，退回重新整改"
        )
        db.add(review)
        db.commit()
        db.refresh(review)
        result = ReviewResponse.model_validate(review)
        result.reviewer_name = review.reviewer.real_name or review.reviewer.username
        return result

    review = ReviewRecord(
        inspection_id=req.inspection_id,
        reviewer_id=current_user.id,
        review_time=datetime.utcnow(),
        restored_width=req.restored_width,
        passage_restored=req.passage_restored,
        review_conclusion=req.review_conclusion,
        risk_level=req.risk_level,
        closing_opinion=req.closing_opinion
    )
    db.add(review)

    if req.passage_restored:
        inspection.status = "已关闭"

    db.commit()
    db.refresh(review)

    result = ReviewResponse.model_validate(review)
    result.reviewer_name = review.reviewer.real_name or review.reviewer.username
    return result


@app.get("/api/reviews", tags=["复核员-复核"])
def list_reviews(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    reviews = db.query(ReviewRecord).all()
    result = []
    for r in reviews:
        result.append({
            "id": r.id,
            "inspection_id": r.inspection_id,
            "reviewer_id": r.reviewer_id,
            "reviewer_name": r.reviewer.real_name or r.reviewer.username,
            "review_time": r.review_time.isoformat() if r.review_time else None,
            "restored_width": r.restored_width,
            "passage_restored": r.passage_restored,
            "review_conclusion": r.review_conclusion,
            "risk_level": r.risk_level,
            "closing_opinion": r.closing_opinion,
            "created_at": r.created_at.isoformat() if r.created_at else None
        })
    return result


# ==================== 公共：查询与筛选 ====================

def format_inspection(record: InspectionRecord, db: Session) -> dict:
    lane = db.query(FireLane).filter(FireLane.id == record.lane_id).first()
    inspector = db.query(User).filter(User.id == record.inspector_id).first()
    all_reviews = db.query(ReviewRecord).filter(
        ReviewRecord.inspection_id == record.id
    ).order_by(ReviewRecord.created_at.desc()).all()
    review = all_reviews[0] if all_reviews else None

    review_history = []
    for rv in all_reviews:
        review_history.append({
            "review_id": rv.id,
            "reviewer_name": rv.reviewer.real_name or rv.reviewer.username if rv.reviewer else None,
            "review_time": rv.review_time.isoformat() if rv.review_time else None,
            "restored_width": rv.restored_width,
            "passage_restored": rv.passage_restored,
            "review_conclusion": rv.review_conclusion,
            "risk_level": rv.risk_level,
            "closing_opinion": rv.closing_opinion
        })

    return {
        "id": record.id,
        "lane_id": record.lane_id,
        "inspector_id": record.inspector_id,
        "inspector_name": inspector.real_name or inspector.username if inspector else None,
        "cycle_start_date": record.cycle_start_date.isoformat() if record.cycle_start_date else None,
        "cycle_end_date": record.cycle_end_date.isoformat() if record.cycle_end_date else None,
        "status": record.status,
        "measured_width": record.measured_width,
        "is_occupied": record.is_occupied,
        "obstruction_type": record.obstruction_type,
        "sign_status": record.sign_status,
        "floor_marking_status": record.floor_marking_status,
        "site_notes": record.site_notes,
        "risk_description": record.risk_description,
        "restoration_suggestion": record.restoration_suggestion,
        "required_completion_time": record.required_completion_time.isoformat() if record.required_completion_time else None,
        "is_overdue": record.is_overdue,
        "has_sign_anomaly": record.has_sign_anomaly,
        "width_insufficient": record.width_insufficient,
        "dept_delay": record.dept_delay,
        "building_anomaly_concentrated": record.building_anomaly_concentrated,
        "lane_number": lane.lane_number if lane else None,
        "building_name": lane.building.name if lane and lane.building else None,
        "building_id": lane.building_id if lane else None,
        "responsible_dept": lane.responsible_dept if lane else None,
        "min_passable_width": lane.min_passable_width if lane else None,
        "review_conclusion": review.review_conclusion if review else None,
        "risk_level": review.risk_level if review else None,
        "passage_restored": review.passage_restored if review else None,
        "review_count": len(all_reviews),
        "review_history": review_history,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None
    }


@app.get("/api/inspections", tags=["查询-巡检记录"])
def list_inspections(
    building_id: Optional[int] = None,
    lane_id: Optional[int] = None,
    responsible_dept: Optional[str] = None,
    status: Optional[str] = None,
    risk_level: Optional[str] = None,
    is_occupied: Optional[bool] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    is_overdue: Optional[bool] = None,
    has_sign_anomaly: Optional[bool] = None,
    width_insufficient: Optional[bool] = None,
    dept_delay: Optional[bool] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(InspectionRecord)

    if lane_id:
        q = q.filter(InspectionRecord.lane_id == lane_id)
    if building_id:
        lane_ids = [l.id for l in db.query(FireLane).filter(FireLane.building_id == building_id).all()]
        q = q.filter(InspectionRecord.lane_id.in_(lane_ids) if lane_ids else False)
    if responsible_dept:
        lane_ids_dept = [l.id for l in db.query(FireLane).filter(FireLane.responsible_dept == responsible_dept).all()]
        q = q.filter(InspectionRecord.lane_id.in_(lane_ids_dept) if lane_ids_dept else False)
    if status:
        q = q.filter(InspectionRecord.status == status)
    if is_occupied is not None:
        q = q.filter(InspectionRecord.is_occupied == is_occupied)
    if is_overdue is not None:
        q = q.filter(InspectionRecord.is_overdue == is_overdue)
    if has_sign_anomaly is not None:
        q = q.filter(InspectionRecord.has_sign_anomaly == has_sign_anomaly)
    if width_insufficient is not None:
        q = q.filter(InspectionRecord.width_insufficient == width_insufficient)
    if dept_delay is not None:
        q = q.filter(InspectionRecord.dept_delay == dept_delay)
    if start_date:
        q = q.filter(InspectionRecord.cycle_start_date >= start_date)
    if end_date:
        q = q.filter(InspectionRecord.cycle_end_date <= end_date)
    if risk_level:
        from sqlalchemy import func as sa_func
        latest_review_subq = db.query(
            ReviewRecord.inspection_id,
            sa_func.max(ReviewRecord.created_at).label("max_created")
        ).group_by(ReviewRecord.inspection_id).subquery()
        latest_with_level = db.query(ReviewRecord.inspection_id).join(
            latest_review_subq,
            and_(
                ReviewRecord.inspection_id == latest_review_subq.c.inspection_id,
                ReviewRecord.created_at == latest_review_subq.c.max_created
            )
        ).filter(ReviewRecord.risk_level == risk_level).all()
        review_ids = [r[0] for r in latest_with_level]
        q = q.filter(InspectionRecord.id.in_(review_ids) if review_ids else False)

    total = q.count()
    records = q.order_by(InspectionRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = [format_inspection(r, db) for r in records]

    return {"total": total, "items": items, "page": page, "page_size": page_size}


@app.get("/api/inspections/{record_id}", tags=["查询-巡检记录"])
def get_inspection(record_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    record = db.query(InspectionRecord).filter(InspectionRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="巡检记录不存在")
    return format_inspection(record, db)


# ==================== 统计接口 ====================

@app.get("/api/stats/high-risk-lanes", tags=["统计"])
def high_risk_lanes(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    risk_score = {"低": 1, "中": 2, "高": 3, "极高": 4}
    records = db.query(InspectionRecord).filter(InspectionRecord.status != "已关闭").all()

    lane_scores = {}
    for rec in records:
        score = 0
        if rec.is_occupied:
            score += 10
        if rec.width_insufficient:
            score += 15
        if rec.is_overdue:
            score += 20
        if rec.has_sign_anomaly:
            score += 5
        if rec.dept_delay:
            score += 10
        review = db.query(ReviewRecord).filter(
            ReviewRecord.inspection_id == rec.id
        ).order_by(ReviewRecord.created_at.desc()).first()
        if review:
            score += risk_score.get(review.risk_level, 0) * 5
        lane_scores[rec.lane_id] = lane_scores.get(rec.lane_id, 0) + score

    sorted_lanes = sorted(lane_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

    result = []
    for lid, score in sorted_lanes:
        lane = db.query(FireLane).filter(FireLane.id == lid).first()
        if lane:
            result.append({
                "lane_id": lid,
                "lane_number": lane.lane_number,
                "building_name": lane.building.name,
                "responsible_dept": lane.responsible_dept,
                "risk_score": score
            })
    return result


@app.get("/api/stats/pending-reviews", tags=["统计"])
def pending_reviews(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    records = db.query(InspectionRecord).filter(InspectionRecord.status == "待复核").all()
    result = []
    for rec in records:
        result.append(format_inspection(rec, db))
    return {"total": len(result), "items": result}


@app.get("/api/stats/restoration-rate", tags=["统计"])
def restoration_rate(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(InspectionRecord).filter(InspectionRecord.is_occupied == True)
    if start_date:
        q = q.filter(InspectionRecord.cycle_start_date >= start_date)
    if end_date:
        q = q.filter(InspectionRecord.cycle_end_date <= end_date)

    occupied_records = q.all()
    total = len(occupied_records)
    restored = 0
    overdue = 0
    in_progress = 0

    for rec in occupied_records:
        review = db.query(ReviewRecord).filter(
            ReviewRecord.inspection_id == rec.id
        ).order_by(ReviewRecord.created_at.desc()).first()
        if review and review.passage_restored:
            restored += 1
        elif rec.is_overdue:
            overdue += 1
        else:
            in_progress += 1

    rate = round(restored / total * 100, 2) if total > 0 else 0

    return {
        "total_occupied": total,
        "restored": restored,
        "overdue": overdue,
        "in_progress": in_progress,
        "restoration_rate_percent": rate
    }


@app.get("/api/stats/building-anomalies", tags=["统计"])
def building_anomaly_distribution(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    buildings = db.query(Building).all()
    result = []
    for b in buildings:
        lane_ids = [l.id for l in b.lanes]
        if not lane_ids:
            result.append({
                "building_id": b.id,
                "building_name": b.name,
                "total_inspections": 0,
                "occupied_count": 0,
                "overdue_count": 0,
                "sign_anomaly_count": 0,
                "width_insufficient_count": 0,
                "concentrated": False
            })
            continue

        total = db.query(func.count(InspectionRecord.id)).filter(InspectionRecord.lane_id.in_(lane_ids)).scalar()
        occupied = db.query(func.count(InspectionRecord.id)).filter(
            InspectionRecord.lane_id.in_(lane_ids), InspectionRecord.is_occupied == True
        ).scalar()
        overdue = db.query(func.count(InspectionRecord.id)).filter(
            InspectionRecord.lane_id.in_(lane_ids), InspectionRecord.is_overdue == True
        ).scalar()
        sign_anom = db.query(func.count(InspectionRecord.id)).filter(
            InspectionRecord.lane_id.in_(lane_ids), InspectionRecord.has_sign_anomaly == True
        ).scalar()
        width_insuf = db.query(func.count(InspectionRecord.id)).filter(
            InspectionRecord.lane_id.in_(lane_ids), InspectionRecord.width_insufficient == True
        ).scalar()

        concentrated = occupied >= 3
        result.append({
            "building_id": b.id,
            "building_name": b.name,
            "total_inspections": total,
            "occupied_count": occupied,
            "overdue_count": overdue,
            "sign_anomaly_count": sign_anom,
            "width_insufficient_count": width_insuf,
            "concentrated": concentrated
        })
    return result


@app.get("/api/stats/overview", tags=["统计"])
def overview(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    total_inspections = db.query(func.count(InspectionRecord.id)).scalar()
    occupied = db.query(func.count(InspectionRecord.id)).filter(InspectionRecord.is_occupied == True).scalar()
    pending_review_cnt = db.query(func.count(InspectionRecord.id)).filter(InspectionRecord.status == "待复核").scalar()
    closed = db.query(func.count(InspectionRecord.id)).filter(InspectionRecord.status == "已关闭").scalar()
    overdue = db.query(func.count(InspectionRecord.id)).filter(InspectionRecord.is_overdue == True).scalar()
    total_lanes = db.query(func.count(FireLane.id)).scalar()
    total_buildings = db.query(func.count(Building.id)).scalar()

    status_counts = {}
    for s in VALID_STATUSES:
        cnt = db.query(func.count(InspectionRecord.id)).filter(InspectionRecord.status == s).scalar()
        status_counts[s] = cnt

    return {
        "total_buildings": total_buildings,
        "total_lanes": total_lanes,
        "total_inspections": total_inspections,
        "occupied_count": occupied,
        "pending_review_count": pending_review_cnt,
        "closed_count": closed,
        "overdue_count": overdue,
        "status_distribution": status_counts
    }


@app.get("/api/stats/department-delay", tags=["统计"])
def department_delay(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    lanes = db.query(FireLane).all()
    dept_stats = {}
    for lane in lanes:
        dept = lane.responsible_dept
        if dept not in dept_stats:
            dept_stats[dept] = {"total": 0, "delayed": 0, "overdue": 0}
        recs = db.query(InspectionRecord).filter(InspectionRecord.lane_id == lane.id).all()
        for rec in recs:
            dept_stats[dept]["total"] += 1
            if rec.dept_delay:
                dept_stats[dept]["delayed"] += 1
            if rec.is_overdue:
                dept_stats[dept]["overdue"] += 1

    result = []
    for dept, stats in dept_stats.items():
        result.append({
            "responsible_dept": dept,
            "total_records": stats["total"],
            "delayed_count": stats["delayed"],
            "overdue_count": stats["overdue"],
            "delay_rate_percent": round(stats["delayed"] / stats["total"] * 100, 2) if stats["total"] > 0 else 0
        })
    return sorted(result, key=lambda x: x["delay_rate_percent"], reverse=True)


# ==================== 自动检测触发接口 ====================

@app.post("/api/detections/run", tags=["自动检测"])
def run_all_detections(db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    records = db.query(InspectionRecord).filter(InspectionRecord.status != "已关闭").all()
    count = 0
    for rec in records:
        run_auto_detection(db, rec)
        count += 1
    return {"message": f"已对 {count} 条记录执行自动检测", "checked": count}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8150)
