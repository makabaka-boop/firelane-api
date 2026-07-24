# -*- coding: utf-8 -*-
"""FastAPI 应用主入口：认证、管理员配置、巡检、复核、筛选与统计接口。"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from . import auth, models, schemas
from .database import Base, engine, get_db
from .models import FireLane, InspectionRecord, LaneStatus, ReviewRecord, RiskLevel, Role, User

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="园区消防通道安全巡检与通行风险闭环管理接口",
    description="管理员配置 / 巡检提交 / 复核关闭 / 异常识别 / 筛选统计",
    version="1.0.0",
)


# ------------------------- 启动：预置账号 -------------------------
@app.on_event("startup")
def seed_accounts():
    db = next(get_db())
    try:
        presets = [
            ("admin", "admin123", Role.ADMIN, "安全管理部", "系统管理员"),
            ("inspector", "insp123", Role.INSPECTOR, "物业巡检部", "巡检员小王"),
            ("reviewer", "rev123", Role.REVIEWER, "安全复核部", "复核员小李"),
        ]
        for username, pwd, role, dept, name in presets:
            if not db.query(User).filter(User.username == username).first():
                db.add(
                    User(
                        username=username,
                        password_hash=auth.hash_password(pwd),
                        role=role,
                        department=dept,
                        display_name=name,
                    )
                )
        db.commit()
    finally:
        db.close()


# ------------------------- 工具函数 -------------------------
def compute_cycle_key(cycle_days: int, when: Optional[datetime] = None) -> str:
    """根据巡检周期天数把时间轴切成固定窗口，返回窗口索引作为周期标识。

    同一通道在同一周期窗口内只允许一条巡检记录。
    """
    when = when or datetime.utcnow()
    cycle_days = max(1, cycle_days or 1)
    day_index = int((when - datetime(1970, 1, 1)).days)
    return f"{cycle_days}-{day_index // cycle_days}"


# ==================================================================
#                            认证
# ==================================================================
@app.post("/api/auth/login", response_model=schemas.Token, tags=["认证"])
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not auth.verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )
    token = auth.create_access_token({"sub": user.username, "role": user.role})
    return schemas.Token(
        access_token=token, role=user.role, username=user.username
    )


@app.get("/api/auth/me", response_model=schemas.UserOut, tags=["认证"])
def me(current: User = Depends(auth.get_current_user)):
    return current


@app.get("/api/health", tags=["认证"])
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


# ==================================================================
#                     管理员：账号 / 楼宇 / 通道
# ==================================================================
@app.post("/api/users", response_model=schemas.UserOut, tags=["管理员"])
def create_user(
    payload: schemas.UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(auth.require_admin),
):
    if payload.role not in Role.ALL:
        raise HTTPException(400, f"非法角色，可选：{', '.join(Role.ALL)}")
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(400, "用户名已存在")
    user = User(
        username=payload.username,
        password_hash=auth.hash_password(payload.password),
        role=payload.role,
        department=payload.department,
        display_name=payload.display_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get("/api/users", response_model=List[schemas.UserOut], tags=["管理员"])
def list_users(db: Session = Depends(get_db), _: User = Depends(auth.require_admin)):
    return db.query(User).all()


@app.post("/api/buildings", response_model=schemas.BuildingOut, tags=["管理员"])
def create_building(
    payload: schemas.BuildingCreate,
    db: Session = Depends(get_db),
    _: User = Depends(auth.require_admin),
):
    if db.query(models.Building).filter(models.Building.code == payload.code).first():
        raise HTTPException(400, "楼宇编码已存在")
    b = models.Building(name=payload.name, code=payload.code)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


@app.get("/api/buildings", response_model=List[schemas.BuildingOut], tags=["管理员"])
def list_buildings(db: Session = Depends(get_db), _: User = Depends(auth.get_current_user)):
    return db.query(models.Building).all()


@app.post("/api/lanes", response_model=schemas.FireLaneOut, tags=["管理员"])
def create_lane(
    payload: schemas.FireLaneCreate,
    db: Session = Depends(get_db),
    _: User = Depends(auth.require_admin),
):
    if not db.query(models.Building).filter(models.Building.id == payload.building_id).first():
        raise HTTPException(404, "楼宇不存在")
    # 同楼宇下通道编号不可重复
    dup = (
        db.query(FireLane)
        .filter(
            FireLane.building_id == payload.building_id,
            FireLane.lane_code == payload.lane_code,
        )
        .first()
    )
    if dup:
        raise HTTPException(400, "同楼宇下该消防通道编号已存在")
    lane = FireLane(**payload.model_dump())
    db.add(lane)
    db.commit()
    db.refresh(lane)
    return lane


@app.get("/api/lanes", response_model=List[schemas.FireLaneOut], tags=["管理员"])
def list_lanes(
    building_id: Optional[int] = None,
    responsible_dept: Optional[str] = None,
    status_: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    _: User = Depends(auth.get_current_user),
):
    q = db.query(FireLane)
    if building_id is not None:
        q = q.filter(FireLane.building_id == building_id)
    if responsible_dept:
        q = q.filter(FireLane.responsible_dept == responsible_dept)
    if status_:
        q = q.filter(FireLane.status == status_)
    return q.all()


@app.put("/api/lanes/{lane_id}", response_model=schemas.FireLaneOut, tags=["管理员"])
def update_lane(
    lane_id: int,
    payload: schemas.FireLaneUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(auth.require_admin),
):
    lane = db.query(FireLane).filter(FireLane.id == lane_id).first()
    if not lane:
        raise HTTPException(404, "通道不存在")
    data = payload.model_dump(exclude_unset=True)
    # 编号变更时校验同楼宇唯一
    new_code = data.get("lane_code")
    if new_code and new_code != lane.lane_code:
        dup = (
            db.query(FireLane)
            .filter(
                FireLane.building_id == lane.building_id,
                FireLane.lane_code == new_code,
                FireLane.id != lane_id,
            )
            .first()
        )
        if dup:
            raise HTTPException(400, "同楼宇下该消防通道编号已存在")
    for k, v in data.items():
        setattr(lane, k, v)
    db.commit()
    db.refresh(lane)
    return lane


# ==================================================================
#                          巡检员：巡检
# ==================================================================
@app.post("/api/inspections", response_model=schemas.InspectionOut, tags=["巡检员"])
def submit_inspection(
    payload: schemas.InspectionCreate,
    db: Session = Depends(get_db),
    current: User = Depends(auth.require_inspector),
):
    lane = db.query(FireLane).filter(FireLane.id == payload.lane_id).first()
    if not lane:
        raise HTTPException(404, "通道不存在")

    cycle_key = compute_cycle_key(lane.inspection_cycle_days)
    # 同一消防通道同一巡检周期不可重复创建记录
    exists = (
        db.query(InspectionRecord)
        .filter(
            InspectionRecord.lane_id == lane.id,
            InspectionRecord.cycle_key == cycle_key,
        )
        .first()
    )
    if exists:
        raise HTTPException(400, "该通道本巡检周期已存在巡检记录，不可重复创建")

    # 依据实测宽度 / 占用情况判定状态
    is_blocked = payload.is_occupied or (
        payload.measured_width is not None
        and payload.measured_width < lane.min_pass_width
    )
    rec_status = LaneStatus.BLOCKED if is_blocked else LaneStatus.TO_REVIEW

    record = InspectionRecord(
        lane_id=lane.id,
        cycle_key=cycle_key,
        inspector_id=current.id,
        measured_width=payload.measured_width,
        is_occupied=payload.is_occupied,
        occupation_type=payload.occupation_type,
        sign_status=payload.sign_status,
        site_note=payload.site_note,
        risk_desc=payload.risk_desc,
        recovery_suggestion=payload.recovery_suggestion,
        required_finish_time=payload.required_finish_time,
        status=rec_status,
    )
    db.add(record)
    # 同步通道状态
    lane.status = rec_status
    db.commit()
    db.refresh(record)
    return record


@app.post(
    "/api/inspections/{inspection_id}/recovering",
    response_model=schemas.InspectionOut,
    tags=["巡检员"],
)
def mark_recovering(
    inspection_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(auth.require_inspector),
):
    """受阻通道进入恢复处理中。"""
    rec = db.query(InspectionRecord).filter(InspectionRecord.id == inspection_id).first()
    if not rec:
        raise HTTPException(404, "巡检记录不存在")
    if rec.status not in (LaneStatus.BLOCKED, LaneStatus.RECOVERING):
        raise HTTPException(400, "仅通行受阻的记录可进入恢复处理中")
    rec.status = LaneStatus.RECOVERING
    lane = db.query(FireLane).filter(FireLane.id == rec.lane_id).first()
    if lane:
        lane.status = LaneStatus.RECOVERING
    db.commit()
    db.refresh(rec)
    return rec


@app.post(
    "/api/inspections/{inspection_id}/submit-review",
    response_model=schemas.InspectionOut,
    tags=["巡检员"],
)
def submit_to_review(
    inspection_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(auth.require_inspector),
):
    """恢复处理完成后提交复核。"""
    rec = db.query(InspectionRecord).filter(InspectionRecord.id == inspection_id).first()
    if not rec:
        raise HTTPException(404, "巡检记录不存在")
    if rec.status not in (LaneStatus.RECOVERING, LaneStatus.BLOCKED):
        raise HTTPException(400, "仅受阻/恢复处理中的记录可提交复核")
    rec.status = LaneStatus.TO_REVIEW
    lane = db.query(FireLane).filter(FireLane.id == rec.lane_id).first()
    if lane:
        lane.status = LaneStatus.TO_REVIEW
    db.commit()
    db.refresh(rec)
    return rec


# ==================================================================
#                          复核员：复核
# ==================================================================
@app.post("/api/reviews", response_model=schemas.ReviewOut, tags=["复核员"])
def submit_review(
    payload: schemas.ReviewCreate,
    db: Session = Depends(get_db),
    current: User = Depends(auth.require_reviewer),
):
    rec = (
        db.query(InspectionRecord)
        .filter(InspectionRecord.id == payload.inspection_id)
        .first()
    )
    if not rec:
        raise HTTPException(404, "巡检记录不存在")
    # 仅“待复核”记录可复核：受阻记录必须先经恢复处理并提交复核，
    # 不允许 blocked / recovering 状态被直接复核关闭
    if rec.status != LaneStatus.TO_REVIEW:
        raise HTTPException(400, "仅待复核状态的记录可复核，请先完成恢复处理并提交复核")
    if payload.risk_level not in RiskLevel.ALL:
        raise HTTPException(400, f"非法风险等级，可选：{', '.join(RiskLevel.ALL)}")

    lane = db.query(FireLane).filter(FireLane.id == rec.lane_id).first()

    review = ReviewRecord(
        inspection_id=rec.id,
        reviewer_id=current.id,
        # 复核时间一律以提交时的系统时间为准，不接受客户端传入
        review_time=datetime.utcnow(),
        restored_width=payload.restored_width,
        is_recovered=payload.is_recovered,
        conclusion=payload.conclusion,
        risk_level=payload.risk_level,
        close_opinion=payload.close_opinion,
    )
    db.add(review)

    # 复核结论决定闭环：恢复且宽度达标 -> 关闭；否则退回恢复处理中
    width_ok = (
        lane is not None
        and payload.restored_width is not None
        and payload.restored_width >= lane.min_pass_width
    )
    if payload.is_recovered and width_ok:
        rec.status = LaneStatus.CLOSED
        if lane:
            lane.status = LaneStatus.CLOSED
    else:
        rec.status = LaneStatus.RECOVERING
        if lane:
            lane.status = LaneStatus.RECOVERING

    db.commit()
    db.refresh(review)
    return review


@app.get("/api/reviews", response_model=List[schemas.ReviewOut], tags=["复核员"])
def list_reviews(
    inspection_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(auth.get_current_user),
):
    q = db.query(ReviewRecord)
    if inspection_id is not None:
        q = q.filter(ReviewRecord.inspection_id == inspection_id)
    return q.order_by(ReviewRecord.review_time.desc()).all()


# ==================================================================
#                     巡检记录筛选查询
# ==================================================================
@app.get("/api/inspections", response_model=List[schemas.InspectionOut], tags=["查询"])
def query_inspections(
    building_id: Optional[int] = None,
    lane_id: Optional[int] = None,
    responsible_dept: Optional[str] = None,
    status_: Optional[str] = Query(None, alias="status"),
    risk_level: Optional[str] = None,
    is_occupied: Optional[bool] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: Session = Depends(get_db),
    _: User = Depends(auth.get_current_user),
):
    q = db.query(InspectionRecord).join(FireLane, InspectionRecord.lane_id == FireLane.id)
    if building_id is not None:
        q = q.filter(FireLane.building_id == building_id)
    if lane_id is not None:
        q = q.filter(InspectionRecord.lane_id == lane_id)
    if responsible_dept:
        q = q.filter(FireLane.responsible_dept == responsible_dept)
    if status_:
        q = q.filter(InspectionRecord.status == status_)
    if is_occupied is not None:
        q = q.filter(InspectionRecord.is_occupied == is_occupied)
    if date_from:
        q = q.filter(InspectionRecord.created_at >= date_from)
    if date_to:
        q = q.filter(InspectionRecord.created_at <= date_to)

    records = q.order_by(InspectionRecord.created_at.desc()).all()

    # 风险等级来自最新复核，需在 Python 层过滤
    if risk_level:
        filtered = []
        for r in records:
            latest = _latest_review(r)
            if latest and latest.risk_level == risk_level:
                filtered.append(r)
        records = filtered
    return records


def _latest_review(rec: InspectionRecord) -> Optional[ReviewRecord]:
    if not rec.reviews:
        return None
    return sorted(rec.reviews, key=lambda x: x.review_time)[-1]


# ==================================================================
#                        异常自动识别
# ==================================================================
@app.get("/api/anomalies", tags=["异常识别"])
def detect_anomalies(
    db: Session = Depends(get_db), _: User = Depends(auth.get_current_user)
):
    """自动识别六类异常并返回明细。"""
    now = datetime.utcnow()
    records = db.query(InspectionRecord).all()
    lanes = {l.id: l for l in db.query(FireLane).all()}

    overdue = []                # 整改超时
    dept_delay = []             # 责任部门处理延迟
    sign_abnormal = []          # 指示牌异常
    missing_conclusion = []     # 复核结论缺失
    width_not_meet = []         # 恢复宽度不达标
    building_counter = Counter()  # 楼宇异常计数

    open_statuses = {LaneStatus.BLOCKED, LaneStatus.RECOVERING, LaneStatus.TO_REVIEW}

    for r in records:
        lane = lanes.get(r.lane_id)
        latest = _latest_review(r)
        is_open = r.status in open_statuses

        # 1. 整改超时：未关闭且超过要求完成时间
        if is_open and r.required_finish_time and now > r.required_finish_time:
            overdue.append(_anomaly_item(r, lane, "整改超时"))
            if lane:
                building_counter[lane.building_id] += 1

        # 2. 责任部门处理延迟：受阻后长期停留在恢复处理中（>要求完成时间 或 创建超7天未关闭）
        if is_open and (
            (r.required_finish_time and now > r.required_finish_time)
            or (now - r.created_at > timedelta(days=7))
        ):
            dept_delay.append(_anomaly_item(r, lane, "责任部门处理延迟"))

        # 3. 指示牌异常
        if r.sign_status in ("abnormal", "missing"):
            sign_abnormal.append(_anomaly_item(r, lane, "指示牌异常"))
            if lane:
                building_counter[lane.building_id] += 1

        # 4. 复核结论缺失：进入待复核但无有效复核结论
        if r.status == LaneStatus.TO_REVIEW and (latest is None or not latest.conclusion):
            missing_conclusion.append(_anomaly_item(r, lane, "复核结论缺失"))

        # 5. 恢复宽度不达标：已复核但恢复宽度 < 最小通行宽度
        if latest and lane and latest.restored_width is not None:
            if latest.restored_width < lane.min_pass_width:
                width_not_meet.append(_anomaly_item(r, lane, "恢复宽度不达标"))
                building_counter[lane.building_id] += 1

    # 6. 同楼宇通道异常集中：单楼宇异常计数 >= 阈值
    threshold = 3
    building_names = {b.id: b.name for b in db.query(models.Building).all()}
    building_concentration = [
        {
            "building_id": bid,
            "building_name": building_names.get(bid),
            "anomaly_count": cnt,
        }
        for bid, cnt in building_counter.items()
        if cnt >= threshold
    ]

    return {
        "overdue_rectification": overdue,
        "dept_processing_delay": dept_delay,
        "sign_abnormal": sign_abnormal,
        "missing_review_conclusion": missing_conclusion,
        "recovery_width_not_meet": width_not_meet,
        "building_anomaly_concentration": building_concentration,
        "summary": {
            "overdue": len(overdue),
            "dept_delay": len(dept_delay),
            "sign_abnormal": len(sign_abnormal),
            "missing_conclusion": len(missing_conclusion),
            "width_not_meet": len(width_not_meet),
            "concentrated_buildings": len(building_concentration),
        },
    }


def _anomaly_item(rec: InspectionRecord, lane: Optional[FireLane], kind: str) -> dict:
    return {
        "type": kind,
        "inspection_id": rec.id,
        "lane_id": rec.lane_id,
        "lane_code": lane.lane_code if lane else None,
        "building_id": lane.building_id if lane else None,
        "responsible_dept": lane.responsible_dept if lane else None,
        "status": rec.status,
        "required_finish_time": rec.required_finish_time.isoformat()
        if rec.required_finish_time
        else None,
    }


# ==================================================================
#                            统计输出
# ==================================================================
@app.get("/api/stats/high-risk-ranking", tags=["统计"])
def high_risk_ranking(
    limit: int = 10,
    db: Session = Depends(get_db),
    _: User = Depends(auth.get_current_user),
):
    """高风险通道排行：按最新复核风险等级权重降序。"""
    records = db.query(InspectionRecord).all()
    lanes = {l.id: l for l in db.query(FireLane).all()}
    rows = []
    for r in records:
        latest = _latest_review(r)
        if not latest or not latest.risk_level:
            continue
        lane = lanes.get(r.lane_id)
        rows.append(
            {
                "inspection_id": r.id,
                "lane_id": r.lane_id,
                "lane_code": lane.lane_code if lane else None,
                "building_id": lane.building_id if lane else None,
                "risk_level": latest.risk_level,
                "weight": RiskLevel.WEIGHT.get(latest.risk_level, 0),
                "status": r.status,
            }
        )
    rows.sort(key=lambda x: x["weight"], reverse=True)
    return rows[:limit]


@app.get("/api/stats/pending-review", tags=["统计"])
def pending_review_list(
    db: Session = Depends(get_db), _: User = Depends(auth.get_current_user)
):
    """待复核清单。"""
    records = (
        db.query(InspectionRecord)
        .filter(InspectionRecord.status == LaneStatus.TO_REVIEW)
        .order_by(InspectionRecord.created_at.asc())
        .all()
    )
    lanes = {l.id: l for l in db.query(FireLane).all()}
    return [
        {
            "inspection_id": r.id,
            "lane_id": r.lane_id,
            "lane_code": lanes[r.lane_id].lane_code if r.lane_id in lanes else None,
            "building_id": lanes[r.lane_id].building_id if r.lane_id in lanes else None,
            "responsible_dept": lanes[r.lane_id].responsible_dept
            if r.lane_id in lanes
            else None,
            "measured_width": r.measured_width,
            "required_finish_time": r.required_finish_time.isoformat()
            if r.required_finish_time
            else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]


@app.get("/api/stats/recovery-rate", tags=["统计"])
def recovery_completion_rate(
    db: Session = Depends(get_db), _: User = Depends(auth.get_current_user)
):
    """通行恢复完成率：已闭环且宽度达标 / 所有出现过受阻或占用的记录。"""
    records = db.query(InspectionRecord).all()
    lanes = {l.id: l for l in db.query(FireLane).all()}

    total_needing = 0   # 需要恢复的记录（受阻/占用/曾进入恢复流程）
    recovered = 0       # 已恢复且宽度达标并关闭

    for r in records:
        lane = lanes.get(r.lane_id)
        latest = _latest_review(r)
        needed = r.is_occupied or r.status in (
            LaneStatus.BLOCKED,
            LaneStatus.RECOVERING,
            LaneStatus.TO_REVIEW,
            LaneStatus.CLOSED,
        )
        # 巡检直接通过（未占用未受阻，直接待复核后关闭）不计入需恢复口径
        if r.status == LaneStatus.CLOSED and not r.is_occupied and (
            r.measured_width is None
            or (lane and r.measured_width >= lane.min_pass_width)
        ):
            needed = r.is_occupied  # 只有占用时才算需恢复
        if not needed:
            continue
        total_needing += 1
        width_ok = (
            latest
            and lane
            and latest.restored_width is not None
            and latest.restored_width >= lane.min_pass_width
        )
        if r.status == LaneStatus.CLOSED and latest and latest.is_recovered and width_ok:
            recovered += 1

    rate = round(recovered / total_needing, 4) if total_needing else 0.0
    return {
        "total_needing_recovery": total_needing,
        "recovered_and_closed": recovered,
        "recovery_completion_rate": rate,
    }


@app.get("/api/stats/building-anomaly-distribution", tags=["统计"])
def building_anomaly_distribution(
    db: Session = Depends(get_db), _: User = Depends(auth.get_current_user)
):
    """楼宇异常集中分布。"""
    anomalies = detect_anomalies(db=db, _=_)  # 复用识别结果
    dist = defaultdict(int)
    building_names = {b.id: b.name for b in db.query(models.Building).all()}

    for key in (
        "overdue_rectification",
        "sign_abnormal",
        "recovery_width_not_meet",
    ):
        for item in anomalies[key]:
            if item["building_id"] is not None:
                dist[item["building_id"]] += 1

    return [
        {
            "building_id": bid,
            "building_name": building_names.get(bid),
            "anomaly_count": cnt,
        }
        for bid, cnt in sorted(dist.items(), key=lambda x: x[1], reverse=True)
    ]
