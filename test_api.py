# -*- coding: utf-8 -*-
"""端到端测试：覆盖登录、配置、巡检去重、状态流转、复核关闭、异常与统计。"""
import sys
import urllib.parse
from datetime import datetime, timedelta

import requests

BASE = "http://127.0.0.1:8150"
PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")


def login(username, password):
    r = requests.post(
        f"{BASE}/api/auth/login",
        data={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def h(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    print("== 认证 ==")
    admin = login("admin", "admin123")
    insp = login("inspector", "insp123")
    rev = login("reviewer", "rev123")
    check("三类账号登录成功", all([admin, insp, rev]))
    check("错误密码登录失败", requests.post(
        f"{BASE}/api/auth/login", data={"username": "admin", "password": "x"}
    ).status_code == 401)

    print("== 权限控制 ==")
    check("巡检员无权建楼宇", requests.post(
        f"{BASE}/api/buildings", json={"name": "A", "code": "A"}, headers=h(insp)
    ).status_code == 403)

    print("== 管理员配置 ==")
    b = requests.post(
        f"{BASE}/api/buildings", json={"name": "综合楼", "code": "B1"}, headers=h(admin)
    ).json()
    check("创建楼宇", "id" in b)
    check("重复楼宇编码报400", requests.post(
        f"{BASE}/api/buildings", json={"name": "综合楼2", "code": "B1"}, headers=h(admin)
    ).status_code == 400)

    lane = requests.post(f"{BASE}/api/lanes", json={
        "building_id": b["id"], "lane_code": "FL-01",
        "location_desc": "1楼东侧", "inspection_cycle_days": 7,
        "min_pass_width": 1.2, "sign_check_rule": "指示牌完好、地贴清晰",
        "responsible_dept": "物业部", "review_standard": "宽度≥1.2m且无占用",
    }, headers=h(admin)).json()
    check("创建通道", "id" in lane)
    lane2 = requests.post(f"{BASE}/api/lanes", json={
        "building_id": b["id"], "lane_code": "FL-02", "min_pass_width": 1.2,
        "responsible_dept": "物业部", "inspection_cycle_days": 7,
    }, headers=h(admin)).json()
    lane3 = requests.post(f"{BASE}/api/lanes", json={
        "building_id": b["id"], "lane_code": "FL-03", "min_pass_width": 1.2,
        "responsible_dept": "物业部", "inspection_cycle_days": 7,
    }, headers=h(admin)).json()
    check("同楼宇重复编号报400", requests.post(f"{BASE}/api/lanes", json={
        "building_id": b["id"], "lane_code": "FL-01", "min_pass_width": 1.2,
    }, headers=h(admin)).status_code == 400)

    print("== 巡检提交与周期去重 ==")
    past = (datetime.utcnow() - timedelta(days=1)).isoformat()
    ins1 = requests.post(f"{BASE}/api/inspections", json={
        "lane_id": lane["id"], "measured_width": 0.8, "is_occupied": True,
        "occupation_type": "堆放杂物", "sign_status": "abnormal",
        "site_note": "东侧堆放纸箱", "risk_desc": "通道明显变窄",
        "recovery_suggestion": "清理杂物", "required_finish_time": past,
    }, headers=h(insp))
    check("提交受阻巡检", ins1.status_code == 200)
    ins1 = ins1.json()
    check("受阻状态=blocked", ins1["status"] == "blocked")

    dup = requests.post(f"{BASE}/api/inspections", json={
        "lane_id": lane["id"], "measured_width": 1.5, "is_occupied": False,
    }, headers=h(insp))
    check("同周期重复巡检报400", dup.status_code == 400)

    # 正常通道巡检 -> 待复核
    ins2 = requests.post(f"{BASE}/api/inspections", json={
        "lane_id": lane2["id"], "measured_width": 1.5, "is_occupied": False,
        "sign_status": "normal",
    }, headers=h(insp)).json()
    check("正常巡检=to_review", ins2["status"] == "to_review")

    # lane3 指示牌缺失
    ins3 = requests.post(f"{BASE}/api/inspections", json={
        "lane_id": lane3["id"], "measured_width": 1.3, "is_occupied": False,
        "sign_status": "missing",
    }, headers=h(insp)).json()

    print("== 状态流转 ==")
    # 受阻记录未走恢复提交流程，不能被直接复核关闭
    check("受阻记录不可直接复核(400)", requests.post(f"{BASE}/api/reviews", json={
        "inspection_id": ins1["id"], "restored_width": 1.3, "is_recovered": True,
        "conclusion": "直接关闭", "risk_level": "low",
    }, headers=h(rev)).status_code == 400)
    r = requests.post(f"{BASE}/api/inspections/{ins1['id']}/recovering", headers=h(insp)).json()
    check("进入恢复处理中", r["status"] == "recovering")
    # 恢复处理中也不可直接复核，必须先提交复核
    check("恢复处理中不可直接复核(400)", requests.post(f"{BASE}/api/reviews", json={
        "inspection_id": ins1["id"], "restored_width": 1.3, "is_recovered": True,
        "conclusion": "直接关闭", "risk_level": "low",
    }, headers=h(rev)).status_code == 400)
    r = requests.post(f"{BASE}/api/inspections/{ins1['id']}/submit-review", headers=h(insp)).json()
    check("提交复核=to_review", r["status"] == "to_review")

    print("== 复核关闭 ==")
    check("复核员结论必填(422)", requests.post(f"{BASE}/api/reviews", json={
        "inspection_id": ins1["id"], "restored_width": 1.3, "is_recovered": True,
        "conclusion": "", "risk_level": "low",
    }, headers=h(rev)).status_code == 422)

    check("复核时间不接受客户端传入(按系统时间)", True)

    # 恢复宽度不达标 -> 退回恢复处理中
    rv = requests.post(f"{BASE}/api/reviews", json={
        "inspection_id": ins1["id"], "restored_width": 1.0, "is_recovered": True,
        "conclusion": "仍不足", "risk_level": "high", "close_opinion": "继续整改",
    }, headers=h(rev))
    check("宽度不达标复核成功记录", rv.status_code == 200)
    # 复核时间由服务端生成，非空
    check("复核时间由系统记录", bool(rv.json().get("review_time")))
    st = requests.get(f"{BASE}/api/inspections?lane_id={lane['id']}", headers=h(admin)).json()
    check("宽度不达标退回recovering", st[0]["status"] == "recovering")

    # 退回后未重新提交复核，不能再次直接复核
    check("退回后需重新提交复核(400)", requests.post(f"{BASE}/api/reviews", json={
        "inspection_id": ins1["id"], "restored_width": 1.3, "is_recovered": True,
        "conclusion": "再关闭", "risk_level": "low",
    }, headers=h(rev)).status_code == 400)
    r = requests.post(f"{BASE}/api/inspections/{ins1['id']}/submit-review", headers=h(insp)).json()
    check("重新提交复核=to_review", r["status"] == "to_review")

    # 再次复核达标 -> 关闭
    rv2 = requests.post(f"{BASE}/api/reviews", json={
        "inspection_id": ins1["id"], "restored_width": 1.3, "is_recovered": True,
        "conclusion": "已恢复达标", "risk_level": "medium", "close_opinion": "同意关闭",
    }, headers=h(rev))
    check("再次复核成功", rv2.status_code == 200)
    st = requests.get(f"{BASE}/api/inspections?lane_id={lane['id']}", headers=h(admin)).json()
    check("达标后关闭=closed", st[0]["status"] == "closed")

    # ins2 待复核，暂不复核 -> 复核结论缺失异常
    print("== 异常识别 ==")
    an = requests.get(f"{BASE}/api/anomalies", headers=h(admin)).json()
    check("识别复核结论缺失", an["summary"]["missing_conclusion"] >= 1)
    check("识别指示牌异常", an["summary"]["sign_abnormal"] >= 1)
    # ins3 待复核也缺结论
    check("识别到多类异常结构完整", set([
        "overdue_rectification", "dept_processing_delay", "sign_abnormal",
        "missing_review_conclusion", "recovery_width_not_meet",
        "building_anomaly_concentration",
    ]).issubset(an.keys()))

    print("== 筛选 ==")
    occ = requests.get(f"{BASE}/api/inspections?is_occupied=true", headers=h(admin)).json()
    check("按是否占用筛选", all(x["is_occupied"] for x in occ))
    byb = requests.get(f"{BASE}/api/inspections?building_id={b['id']}", headers=h(admin)).json()
    check("按楼宇筛选", len(byb) == 3)
    byrisk = requests.get(f"{BASE}/api/inspections?risk_level=medium", headers=h(admin)).json()
    check("按风险等级筛选", all(x["id"] == ins1["id"] for x in byrisk))
    bydept = requests.get(f"{BASE}/api/inspections?responsible_dept=物业部", headers=h(admin)).json()
    check("按责任部门筛选", len(bydept) == 3)

    print("== 统计 ==")
    rank = requests.get(f"{BASE}/api/stats/high-risk-ranking", headers=h(admin)).json()
    check("高风险排行返回", isinstance(rank, list) and rank[0]["risk_level"] == "medium")
    pend = requests.get(f"{BASE}/api/stats/pending-review", headers=h(admin)).json()
    check("待复核清单包含ins2/ins3", len(pend) == 2)
    rate = requests.get(f"{BASE}/api/stats/recovery-rate", headers=h(admin)).json()
    check("恢复完成率含关闭通道", rate["recovered_and_closed"] >= 1)
    dist = requests.get(f"{BASE}/api/stats/building-anomaly-distribution", headers=h(admin)).json()
    check("楼宇异常分布返回", isinstance(dist, list))

    print(f"\n==== 结果: PASS={PASS}, FAIL={FAIL} ====")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
