import os
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_, case
from sqlalchemy.exc import IntegrityError

from .database import Base, engine, get_db
from . import models, schemas, auth

Base.metadata.create_all(bind=engine)
app = FastAPI(title="园区消防通道安全巡检接口", version="1.0.1")


def safe_commit(db: Session, conflict_msg: str = "数据冲突，可能存在重复编号"):
    """提交事务并将唯一约束/完整性错误统一转为 400，避免 500。"""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail=conflict_msg)


# ---------- 启动种子数据 ----------
def _seed():
    db = next(get_db())
    try:
        if db.query(models.User).count() == 0:
            users = [
                models.User(username="admin", password_hash=auth.hash_password("admin123"), role="admin", real_name="系统管理员", department="安保部"),
                models.User(username="inspector1", password_hash=auth.hash_password("inspect123"), role="inspector", real_name="张巡检", department="巡检一组"),
                models.User(username="reviewer1", password_hash=auth.hash_password("review123"), role="reviewer", real_name="李复核", department="安全委员会"),
            ]
            db.add_all(users)
            db.commit()
    finally:
        db.close()
_seed()


# ---------- 工具：序列化 ----------
def _review_out(r: models.ReviewRecord) -> dict:
    if not r:
        return None
    return {
        "id": r.id,
        "inspection_id": r.inspection_id,
        "reviewer_id": r.reviewer_id,
        "reviewer_name": r.reviewer.real_name if r.reviewer else None,
        "review_time": r.review_time,
        "recovered_width": r.recovered_width,
        "is_recovered": r.is_recovered,
        "conclusion": r.conclusion,
        "risk_level": r.risk_level,
        "close_opinion": r.close_opinion,
        "passed": r.passed,
    }


def detect_anomalies(rec: models.InspectionRecord, now: datetime = None) -> List[str]:
    """返回单条巡检记录识别出的异常标签列表"""
    now = now or datetime.utcnow()
    flags = []
    # 整改超时
    if rec.status in ("blocked", "recovering") and rec.required_deadline and rec.required_deadline < now:
        flags.append("整改超时")
    # 责任部门处理延迟：blocked 超过 24 小时未进入 recovering
    if rec.status == "blocked" and rec.submitted_at:
        sla = timedelta(hours=int(os.environ.get("FIRELANE_BLOCK_SLA_HOURS", "24")))
        if now - rec.submitted_at > sla:
            flags.append("责任部门处理延迟")
    # 指示牌异常
    if rec.sign_status and rec.sign_status not in ("normal", "正常", None):
        if rec.sign_status in ("damaged", "missing", "obscured", "损坏", "缺失", "遮挡"):
            flags.append("指示牌异常")
    # 复核结论缺失
    if rec.status == "to_review":
        latest = rec.reviews[-1] if rec.reviews else None
        if not latest or not (latest.conclusion and latest.conclusion.strip()):
            flags.append("复核结论缺失")
    # 恢复宽度不达标
    latest = rec.reviews[-1] if rec.reviews else None
    if latest and latest.recovered_width is not None and rec.lane and rec.lane.min_width is not None:
        if latest.recovered_width < rec.lane.min_width:
            flags.append("恢复宽度不达标")
        if latest.is_recovered is False:
            flags.append("恢复宽度不达标")
    return flags


def _inspection_out(rec: models.InspectionRecord, include_anomalies: bool = True) -> dict:
    latest = rec.reviews[-1] if rec.reviews else None
    data = {
        "id": rec.id,
        "lane_id": rec.lane_id,
        "lane_code": rec.lane.lane_code if rec.lane else None,
        "building_id": rec.lane.building_id if rec.lane else None,
        "building_name": rec.lane.building.name if rec.lane and rec.lane.building else None,
        "dept": rec.lane.dept if rec.lane else None,
        "min_width": rec.lane.min_width if rec.lane else None,
        "cycle_start": rec.cycle_start,
        "cycle_end": rec.cycle_end,
        "inspector_id": rec.inspector_id,
        "inspector_name": rec.inspector.real_name if rec.inspector else None,
        "status": rec.status,
        "measured_width": rec.measured_width,
        "is_occupied": rec.is_occupied,
        "obstacle_type": rec.obstacle_type,
        "sign_status": rec.sign_status,
        "site_remark": rec.site_remark,
        "risk_desc": rec.risk_desc,
        "recovery_suggestion": rec.recovery_suggestion,
        "required_deadline": rec.required_deadline,
        "started_at": rec.started_at,
        "submitted_at": rec.submitted_at,
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
        "latest_review": _review_out(latest),
        "anomalies": detect_anomalies(rec) if include_anomalies else None,
    }
    return data


# ============ 认证 ============
@app.post("/api/auth/login", response_model=schemas.TokenOut)
def login(body: schemas.LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == body.username).first()
    if not user or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = auth.create_access_token(user.id, user.role)
    return schemas.TokenOut(access_token=token, role=user.role, real_name=user.real_name)


@app.get("/api/auth/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(auth.get_current_user)):
    return user


# ============ 用户管理（管理员） ============
@app.post("/api/users", response_model=schemas.UserOut)
def create_user(body: schemas.UserCreate, user=Depends(auth.require_roles("admin")), db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == body.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    u = models.User(
        username=body.username,
        password_hash=auth.hash_password(body.password),
        role=body.role,
        real_name=body.real_name,
        department=body.department,
    )
    db.add(u); safe_commit(db, "用户名已存在"); db.refresh(u)
    return u


@app.get("/api/users", response_model=List[schemas.UserOut])
def list_users(role: Optional[str] = None, user=Depends(auth.require_roles("admin")), db: Session = Depends(get_db)):
    q = db.query(models.User)
    if role:
        q = q.filter(models.User.role == role)
    return q.order_by(models.User.id).all()


# ============ 楼宇管理（管理员） ============
@app.post("/api/buildings", response_model=schemas.BuildingOut)
def create_building(body: schemas.BuildingIn, user=Depends(auth.require_roles("admin")), db: Session = Depends(get_db)):
    if db.query(models.Building).filter(models.Building.code == body.code).first():
        raise HTTPException(status_code=400, detail="楼宇编号已存在")
    b = models.Building(**body.model_dump())
    db.add(b); safe_commit(db, "楼宇编号已存在"); db.refresh(b)
    return b


@app.get("/api/buildings", response_model=List[schemas.BuildingOut])
def list_buildings(user=Depends(auth.get_current_user), db: Session = Depends(get_db)):
    return db.query(models.Building).order_by(models.Building.id).all()


@app.put("/api/buildings/{bid}", response_model=schemas.BuildingOut)
def update_building(bid: int, body: schemas.BuildingIn, user=Depends(auth.require_roles("admin")), db: Session = Depends(get_db)):
    b = db.query(models.Building).filter(models.Building.id == bid).first()
    if not b:
        raise HTTPException(404, "楼宇不存在")
    if db.query(models.Building).filter(
        models.Building.code == body.code, models.Building.id != bid
    ).first():
        raise HTTPException(400, "楼宇编号已存在")
    for k, v in body.model_dump().items():
        setattr(b, k, v)
    safe_commit(db, "楼宇编号已存在"); db.refresh(b)
    return b


@app.delete("/api/buildings/{bid}")
def delete_building(bid: int, user=Depends(auth.require_roles("admin")), db: Session = Depends(get_db)):
    b = db.query(models.Building).filter(models.Building.id == bid).first()
    if not b:
        raise HTTPException(404, "楼宇不存在")
    db.delete(b); safe_commit(db, "删除失败，可能存在关联数据")
    return {"ok": True}


# ============ 消防通道配置（管理员） ============
@app.post("/api/lanes", response_model=schemas.FireLaneOut)
def create_lane(body: schemas.FireLaneIn, user=Depends(auth.require_roles("admin")), db: Session = Depends(get_db)):
    if not db.query(models.Building).filter(models.Building.id == body.building_id).first():
        raise HTTPException(400, "楼宇不存在")
    if db.query(models.FireLane).filter(
        models.FireLane.building_id == body.building_id,
        models.FireLane.lane_code == body.lane_code
    ).first():
        raise HTTPException(400, "该楼宇下通道编号已存在")
    lane = models.FireLane(**body.model_dump())
    db.add(lane); safe_commit(db, "该楼宇下通道编号已存在"); db.refresh(lane)
    return _lane_out(lane)


@app.get("/api/lanes", response_model=List[schemas.FireLaneOut])
def list_lanes(building_id: Optional[int] = None, dept: Optional[str] = None,
               user=Depends(auth.get_current_user), db: Session = Depends(get_db)):
    q = db.query(models.FireLane)
    if building_id:
        q = q.filter(models.FireLane.building_id == building_id)
    if dept:
        q = q.filter(models.FireLane.dept == dept)
    lanes = q.order_by(models.FireLane.building_id, models.FireLane.lane_code).all()
    return [_lane_out(l) for l in lanes]


def _lane_out(lane: models.FireLane) -> dict:
    return {
        "id": lane.id,
        "building_id": lane.building_id,
        "lane_code": lane.lane_code,
        "location_desc": lane.location_desc,
        "inspection_cycle_days": lane.inspection_cycle_days,
        "min_width": lane.min_width,
        "sign_rule": lane.sign_rule,
        "dept": lane.dept,
        "review_standard": lane.review_standard,
        "building_name": lane.building.name if lane.building else None,
    }


@app.put("/api/lanes/{lid}", response_model=schemas.FireLaneOut)
def update_lane(lid: int, body: schemas.FireLaneIn, user=Depends(auth.require_roles("admin")), db: Session = Depends(get_db)):
    lane = db.query(models.FireLane).filter(models.FireLane.id == lid).first()
    if not lane:
        raise HTTPException(404, "通道不存在")
    if not db.query(models.Building).filter(models.Building.id == body.building_id).first():
        raise HTTPException(400, "楼宇不存在")
    if db.query(models.FireLane).filter(
        models.FireLane.building_id == body.building_id,
        models.FireLane.lane_code == body.lane_code,
        models.FireLane.id != lid,
    ).first():
        raise HTTPException(400, "该楼宇下通道编号已存在")
    for k, v in body.model_dump().items():
        setattr(lane, k, v)
    safe_commit(db, "该楼宇下通道编号已存在"); db.refresh(lane)
    return _lane_out(lane)


@app.delete("/api/lanes/{lid}")
def delete_lane(lid: int, user=Depends(auth.require_roles("admin")), db: Session = Depends(get_db)):
    lane = db.query(models.FireLane).filter(models.FireLane.id == lid).first()
    if not lane:
        raise HTTPException(404, "通道不存在")
    db.delete(lane); safe_commit(db, "删除失败，可能存在关联数据")
    return {"ok": True}


# ============ 巡检记录 ============
@app.post("/api/inspections/start", response_model=schemas.InspectionOut)
def start_inspection(body: schemas.InspectionStart,
                     user=Depends(auth.require_roles("inspector", "admin")),
                     db: Session = Depends(get_db)):
    lane = db.query(models.FireLane).filter(models.FireLane.id == body.lane_id).first()
    if not lane:
        raise HTTPException(404, "通道不存在")
    if body.cycle_end <= body.cycle_start:
        raise HTTPException(400, "巡检周期结束时间必须晚于开始时间")
    # 同一通道同一周期不可重复：按周期区间重叠判定，避免相同逻辑周期用不同时间戳绕过
    overlap = db.query(models.InspectionRecord).filter(
        models.InspectionRecord.lane_id == body.lane_id,
        models.InspectionRecord.cycle_start < body.cycle_end,
        models.InspectionRecord.cycle_end > body.cycle_start,
    ).first()
    if overlap:
        raise HTTPException(400, "同一消防通道同一巡检周期已存在记录")
    rec = models.InspectionRecord(
        lane_id=body.lane_id,
        cycle_start=body.cycle_start,
        cycle_end=body.cycle_end,
        inspector_id=user.id,
        status="inspecting",
        started_at=datetime.utcnow(),
    )
    db.add(rec); safe_commit(db, "同一消防通道同一巡检周期已存在记录"); db.refresh(rec)
    return _inspection_out(rec)


@app.post("/api/inspections/{rid}/submit", response_model=schemas.InspectionOut)
def submit_inspection(rid: int, body: schemas.InspectionSubmit,
                      user=Depends(auth.require_roles("inspector", "admin")),
                      db: Session = Depends(get_db)):
    rec = db.query(models.InspectionRecord).filter(models.InspectionRecord.id == rid).first()
    if not rec:
        raise HTTPException(404, "记录不存在")
    if rec.status not in ("inspecting", "pending", "recovering"):
        raise HTTPException(400, f"当前状态 {rec.status} 不可提交巡检结果")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(rec, k, v)
    rec.inspector_id = rec.inspector_id or user.id
    rec.submitted_at = datetime.utcnow()
    # 状态判定：占用或实测宽度不足均视为通行受阻
    if body.is_occupied or (rec.lane and body.measured_width < rec.lane.min_width):
        rec.status = "blocked"
    else:
        rec.status = "to_review"
    safe_commit(db, "提交巡检结果失败"); db.refresh(rec)
    return _inspection_out(rec)


@app.post("/api/inspections/{rid}/status", response_model=schemas.InspectionOut)
def update_status(rid: int, body: schemas.StatusUpdate,
                  user=Depends(auth.require_roles("inspector", "reviewer", "admin")),
                  db: Session = Depends(get_db)):
    rec = db.query(models.InspectionRecord).filter(models.InspectionRecord.id == rid).first()
    if not rec:
        raise HTTPException(404, "记录不存在")
    # 关闭只能通过复核接口完成，避免出现"已关闭但无复核记录"
    allowed = {
        "pending": ["inspecting"],
        "inspecting": ["blocked"],
        "blocked": ["recovering"],
        "recovering": ["to_review", "blocked"],
        "to_review": ["recovering"],
        "closed": [],
    }
    if body.status not in allowed.get(rec.status, []):
        raise HTTPException(400, f"不允许从 {rec.status} 转为 {body.status}；关闭必须通过复核接口")
    # to_review 退回 recovering 仅复核员/管理员可操作
    if rec.status == "to_review" and body.status == "recovering" and user.role not in ("reviewer", "admin"):
        raise HTTPException(403, "仅复核员或管理员可将待复核单退回整改")
    rec.status = body.status
    safe_commit(db, "状态更新失败"); db.refresh(rec)
    return _inspection_out(rec)


@app.post("/api/inspections/{rid}/request-review", response_model=schemas.InspectionOut)
def request_review(rid: int, user=Depends(auth.require_roles("inspector", "admin")), db: Session = Depends(get_db)):
    rec = db.query(models.InspectionRecord).filter(models.InspectionRecord.id == rid).first()
    if not rec:
        raise HTTPException(404, "记录不存在")
    if rec.status not in ("recovering", "blocked"):
        raise HTTPException(400, "当前状态不可提交复核")
    rec.status = "to_review"
    safe_commit(db, "提交复核失败"); db.refresh(rec)
    return _inspection_out(rec)


@app.get("/api/inspections", response_model=List[schemas.InspectionOut])
def list_inspections(
    building_id: Optional[int] = None,
    lane_id: Optional[int] = None,
    dept: Optional[str] = None,
    status: Optional[str] = None,
    risk_level: Optional[str] = None,
    is_occupied: Optional[bool] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    cycle_start_from: Optional[datetime] = None,
    cycle_start_to: Optional[datetime] = None,
    only_anomaly: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user=Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(models.InspectionRecord).join(models.FireLane, models.InspectionRecord.lane_id == models.FireLane.id)
    if building_id:
        q = q.filter(models.FireLane.building_id == building_id)
    if lane_id:
        q = q.filter(models.InspectionRecord.lane_id == lane_id)
    if dept:
        q = q.filter(models.FireLane.dept == dept)
    if status:
        q = q.filter(models.InspectionRecord.status == status)
    if is_occupied is not None:
        q = q.filter(models.InspectionRecord.is_occupied == is_occupied)
    if date_from:
        q = q.filter(models.InspectionRecord.created_at >= date_from)
    if date_to:
        q = q.filter(models.InspectionRecord.created_at <= date_to)
    if cycle_start_from:
        q = q.filter(models.InspectionRecord.cycle_start >= cycle_start_from)
    if cycle_start_to:
        q = q.filter(models.InspectionRecord.cycle_start <= cycle_start_to)
    if risk_level:
        q = q.join(models.ReviewRecord, models.ReviewRecord.inspection_id == models.InspectionRecord.id)\
             .filter(models.ReviewRecord.risk_level == risk_level)

    recs = q.order_by(models.InspectionRecord.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    out = [_inspection_out(r) for r in recs]
    if only_anomaly:
        out = [x for x in out if x["anomalies"]]
    return out


@app.get("/api/inspections/{rid}", response_model=schemas.InspectionOut)
def get_inspection(rid: int, user=Depends(auth.get_current_user), db: Session = Depends(get_db)):
    rec = db.query(models.InspectionRecord).filter(models.InspectionRecord.id == rid).first()
    if not rec:
        raise HTTPException(404, "记录不存在")
    return _inspection_out(rec)


@app.get("/api/inspections/{rid}/reviews", response_model=List[schemas.ReviewOut])
def list_reviews(rid: int, user=Depends(auth.get_current_user), db: Session = Depends(get_db)):
    rec = db.query(models.InspectionRecord).filter(models.InspectionRecord.id == rid).first()
    if not rec:
        raise HTTPException(404, "记录不存在")
    return [_review_out(r) for r in rec.reviews]


# ============ 复核（复核员） ============
@app.post("/api/inspections/{rid}/review", response_model=schemas.ReviewOut)
def review_inspection(rid: int, body: schemas.ReviewIn,
                      user=Depends(auth.require_roles("reviewer", "admin")),
                      db: Session = Depends(get_db)):
    rec = db.query(models.InspectionRecord).filter(models.InspectionRecord.id == rid).first()
    if not rec:
        raise HTTPException(404, "记录不存在")
    if rec.status not in ("to_review",):
        raise HTTPException(400, f"当前状态 {rec.status} 不可复核")

    # 恢复宽度不达标自动判定：若 is_recovered 为 False 或宽度小于最小宽度，则不通过
    passed = body.passed
    if rec.lane and body.recovered_width < rec.lane.min_width:
        passed = False
    if body.is_recovered is False:
        passed = False
    # 通过时复核结论必填，避免"复核结论缺失"
    if passed and not (body.conclusion and body.conclusion.strip()):
        raise HTTPException(400, "复核通过时必须填写复核结论")

    rev = models.ReviewRecord(
        inspection_id=rid,
        reviewer_id=user.id,
        review_time=datetime.utcnow(),
        recovered_width=body.recovered_width,
        is_recovered=body.is_recovered,
        conclusion=body.conclusion,
        risk_level=body.risk_level,
        close_opinion=body.close_opinion,
        passed=passed,
    )
    db.add(rev)
    rec.status = "closed" if passed else "recovering"
    safe_commit(db, "提交复核失败"); db.refresh(rev)
    return _review_out(rev)


# ============ 异常告警 ============
@app.get("/api/alerts")
def list_alerts(building_id: Optional[int] = None, dept: Optional[str] = None,
                user=Depends(auth.get_current_user), db: Session = Depends(get_db)):
    """返回所有异常巡检记录，按异常类型聚合"""
    q = db.query(models.InspectionRecord).join(models.FireLane, models.InspectionRecord.lane_id == models.FireLane.id)
    if building_id:
        q = q.filter(models.FireLane.building_id == building_id)
    if dept:
        q = q.filter(models.FireLane.dept == dept)
    recs = q.all()
    buckets = {
        "整改超时": [],
        "同楼宇异常集中": [],
        "指示牌异常": [],
        "复核结论缺失": [],
        "恢复宽度不达标": [],
        "责任部门处理延迟": [],
    }
    now = datetime.utcnow()
    # 同楼宇异常集中：blocked/recovering 数量 >=3
    building_counts = {}
    for r in recs:
        if r.status in ("blocked", "recovering") and r.lane:
            bid = r.lane.building_id
            building_counts.setdefault(bid, []).append(r)

    concentrated_bids = {bid for bid, lst in building_counts.items() if len(lst) >= 3}

    for r in recs:
        flags = detect_anomalies(r, now=now)
        if r.lane and r.lane.building_id in concentrated_bids and r.status in ("blocked", "recovering"):
            flags.append("同楼宇异常集中")
        for f in flags:
            if f in buckets:
                buckets[f].append(_inspection_out(r, include_anomalies=False))

    summary = {k: len(v) for k, v in buckets.items()}
    return {"summary": summary, "buckets": buckets}


# ============ 统计 ============
@app.get("/api/stats/high-risk", response_model=List[schemas.HighRiskItem])
def high_risk(limit: int = 10, user=Depends(auth.get_current_user), db: Session = Depends(get_db)):
    """高风险通道排行。

    risk_score  ：该通道历次复核风险等级加权累计（critical=3/high=2/medium=1）。
    risk_count  ：该通道累计复核次数。
    latest_risk_level：按 review_time 取最新一条复核的风险等级（不再使用字符串 max）。
    """
    risk_score = func.sum(
        case(
            (models.ReviewRecord.risk_level == "critical", 3),
            (models.ReviewRecord.risk_level == "high", 2),
            (models.ReviewRecord.risk_level == "medium", 1),
            else_=0,
        )
    )
    rows = db.query(
        models.FireLane.id.label("lane_id"),
        models.FireLane.lane_code,
        models.Building.name.label("building_name"),
        models.FireLane.location_desc,
        models.FireLane.dept,
        func.count(models.ReviewRecord.id).label("risk_count"),
        risk_score.label("risk_score"),
    ).join(models.Building, models.FireLane.building_id == models.Building.id)\
     .outerjoin(models.InspectionRecord, models.InspectionRecord.lane_id == models.FireLane.id)\
     .outerjoin(models.ReviewRecord, models.ReviewRecord.inspection_id == models.InspectionRecord.id)\
     .group_by(models.FireLane.id)\
     .order_by(risk_score.desc(), func.count(models.ReviewRecord.id).desc())\
     .limit(limit).all()

    lane_ids = [r.lane_id for r in rows]
    latest_risk_map: dict = {}
    if lane_ids:
        # 用窗口函数按通道分区、按复核时间倒序取 rn=1 即最新一条复核
        rn = func.row_number().over(
            partition_by=models.InspectionRecord.lane_id,
            order_by=(models.ReviewRecord.review_time.desc(), models.ReviewRecord.id.desc()),
        ).label("rn")
        subq = db.query(
            models.InspectionRecord.lane_id.label("lane_id"),
            models.ReviewRecord.risk_level.label("risk_level"),
            rn,
        ).join(
            models.ReviewRecord, models.ReviewRecord.inspection_id == models.InspectionRecord.id
        ).filter(models.InspectionRecord.lane_id.in_(lane_ids)).subquery()
        for r in db.query(subq).filter(subq.c.rn == 1).all():
            latest_risk_map[r.lane_id] = r.risk_level

    result = []
    for row in rows:
        latest_rec = db.query(models.InspectionRecord)\
            .filter(models.InspectionRecord.lane_id == row.lane_id)\
            .order_by(models.InspectionRecord.id.desc()).first()
        result.append({
            "lane_id": row.lane_id,
            "lane_code": row.lane_code,
            "building_name": row.building_name,
            "location_desc": row.location_desc,
            "dept": row.dept,
            "risk_count": row.risk_count or 0,
            "latest_risk_level": latest_risk_map.get(row.lane_id),
            "latest_status": latest_rec.status if latest_rec else None,
        })
    return result


@app.get("/api/stats/to-review", response_model=List[schemas.InspectionOut])
def to_review_list(building_id: Optional[int] = None, user=Depends(auth.get_current_user), db: Session = Depends(get_db)):
    """待复核清单"""
    q = db.query(models.InspectionRecord).filter(models.InspectionRecord.status == "to_review")
    if building_id:
        q = q.join(models.FireLane).filter(models.FireLane.building_id == building_id)
    recs = q.order_by(models.InspectionRecord.updated_at.asc()).all()
    return [_inspection_out(r) for r in recs]


@app.get("/api/stats/recovery-rate", response_model=schemas.RecoveryRate)
def recovery_rate(building_id: Optional[int] = None, dept: Optional[str] = None,
                  date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
                  user=Depends(auth.get_current_user), db: Session = Depends(get_db)):
    """通行恢复完成率。

    分母：所有存在通行受阻问题的巡检记录（占用 OR 实测宽度 < 最小宽度）。
    分子：其中已关闭且存在“通过”复核（恢复宽度达标、通行已恢复）的记录。
    """
    base = db.query(models.InspectionRecord).join(
        models.FireLane, models.InspectionRecord.lane_id == models.FireLane.id
    ).filter(or_(
        models.InspectionRecord.is_occupied == True,
        and_(
            models.InspectionRecord.measured_width.isnot(None),
            models.InspectionRecord.measured_width < models.FireLane.min_width,
        ),
    ))
    if building_id:
        base = base.filter(models.FireLane.building_id == building_id)
    if dept:
        base = base.filter(models.FireLane.dept == dept)
    if date_from:
        base = base.filter(models.InspectionRecord.created_at >= date_from)
    if date_to:
        base = base.filter(models.InspectionRecord.created_at <= date_to)
    total = base.count()

    # 已通过复核的巡检单（is_recovered=True 且 passed=True）
    passed_insp_ids = db.query(models.ReviewRecord.inspection_id).filter(
        models.ReviewRecord.passed == True,
        models.ReviewRecord.is_recovered == True,
    ).subquery()
    recovered = base.filter(
        models.InspectionRecord.status == "closed",
        models.InspectionRecord.id.in_(passed_insp_ids),
    ).count()
    rate = round(recovered / total, 4) if total else 0.0
    return schemas.RecoveryRate(total_blocked=total, recovered=recovered, recovery_rate=rate)


@app.get("/api/stats/building-anomalies", response_model=List[schemas.BuildingAnomaly])
def building_anomalies(user=Depends(auth.get_current_user), db: Session = Depends(get_db)):
    """楼宇异常集中分布"""
    buildings = db.query(models.Building).all()
    out = []
    for b in buildings:
        lane_map = {}
        for lane in b.lanes:
            for rec in lane.inspections:
                if rec.status in ("blocked", "recovering", "to_review"):
                    lane_map.setdefault(lane.lane_code, rec.status)
        blocked = sum(1 for s in lane_map.values() if s == "blocked")
        recovering = sum(1 for s in lane_map.values() if s == "recovering")
        to_review = sum(1 for s in lane_map.values() if s == "to_review")
        total = blocked + recovering + to_review
        if total == 0:
            continue
        out.append({
            "building_id": b.id,
            "building_name": b.name,
            "blocked_count": blocked,
            "recovering_count": recovering,
            "to_review_count": to_review,
            "total_anomaly": total,
            "lanes": list(lane_map.keys()),
        })
    out.sort(key=lambda x: x["total_anomaly"], reverse=True)
    return out


@app.get("/api/healthz")
def healthz():
    return {"ok": True, "ts": datetime.utcnow()}
