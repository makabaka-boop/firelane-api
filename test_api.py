#!/usr/bin/env python3
import requests
import json

BASE = "http://localhost:8150"

def login(username, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": username, "password": password})
    data = r.json()
    return data["access_token"]

admin_token = login("admin", "admin123")
inspector_token = login("inspector", "inspect123")
reviewer_token = login("reviewer", "review123")

headers_admin = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
headers_inspect = {"Authorization": f"Bearer {inspector_token}", "Content-Type": "application/json"}
headers_review = {"Authorization": f"Bearer {reviewer_token}", "Content-Type": "application/json"}

print("=== 1. 创建楼宇 ===")
r = requests.post(f"{BASE}/api/admin/buildings", headers=headers_admin, json={"name": "A座研发楼", "address": "园区东区A座"})
print(r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 2. 创建第二个楼宇 ===")
r = requests.post(f"{BASE}/api/admin/buildings", headers=headers_admin, json={"name": "B座生产楼", "address": "园区西区B座"})
print(r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 3. 创建消防通道 ===")
r = requests.post(f"{BASE}/api/admin/lanes", headers=headers_admin, json={
    "building_id": 1,
    "lane_number": "A-FL-001",
    "location_description": "A座一层东侧主通道",
    "inspection_cycle_days": 7,
    "min_passable_width": 4.0,
    "sign_check_rules": "每月检查指示牌完好性、反光度",
    "responsible_dept": "物业安保部",
    "review_standard": "通行宽度>=4m且无占用，指示牌完好"
})
print(r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 4. 创建第二个通道 (占用风险) ===")
r = requests.post(f"{BASE}/api/admin/lanes", headers=headers_admin, json={
    "building_id": 1,
    "lane_number": "A-FL-002",
    "location_description": "A座二层西侧疏散通道",
    "inspection_cycle_days": 7,
    "min_passable_width": 3.5,
    "sign_check_rules": "检查指示牌和地贴完整性",
    "responsible_dept": "物业管理部",
    "review_standard": "通道畅通无遮挡"
})
print(r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 5. 创建B座通道 ===")
r = requests.post(f"{BASE}/api/admin/lanes", headers=headers_admin, json={
    "building_id": 2,
    "lane_number": "B-FL-001",
    "location_description": "B座一层北侧消防通道",
    "inspection_cycle_days": 14,
    "min_passable_width": 4.0,
    "sign_check_rules": "检查指示牌",
    "responsible_dept": "物业安保部",
    "review_standard": "标准宽度"
})
print(r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 6. 巡检员提交巡检记录 (通道占用) ===")
from datetime import date, datetime, timedelta
today = date.today()
r = requests.post(f"{BASE}/api/inspections", headers=headers_inspect, json={
    "lane_id": 1,
    "cycle_start_date": str(today - timedelta(days=7)),
    "cycle_end_date": str(today),
    "measured_width": 2.5,
    "is_occupied": True,
    "obstruction_type": "车辆违停",
    "sign_status": "遮挡",
    "floor_marking_status": "磨损",
    "site_notes": "通道内发现3辆违停车辆，严重影响通行",
    "risk_description": "通行宽度不足，紧急情况下无法保障疏散",
    "restoration_suggestion": "立即移走违停车辆，设置物理隔离桩",
    "required_completion_time": (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
})
print(r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 7. 巡检员提交第二个通道巡检 (正常) ===")
r = requests.post(f"{BASE}/api/inspections", headers=headers_inspect, json={
    "lane_id": 2,
    "cycle_start_date": str(today - timedelta(days=7)),
    "cycle_end_date": str(today),
    "measured_width": 3.8,
    "is_occupied": False,
    "sign_status": "正常",
    "floor_marking_status": "正常",
    "site_notes": "通道畅通，状态良好",
    "risk_description": "",
    "restoration_suggestion": "",
    "required_completion_time": None
})
print(r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 8. 测试重复创建 (同一通道同一周期) ===")
r = requests.post(f"{BASE}/api/inspections", headers=headers_inspect, json={
    "lane_id": 1,
    "cycle_start_date": str(today - timedelta(days=7)),
    "cycle_end_date": str(today),
    "measured_width": 2.5,
    "is_occupied": True,
    "sign_status": "遮挡",
    "floor_marking_status": "磨损"
})
print(r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 9. 状态流转: 通行受阻 -> 恢复处理中 ===")
r = requests.put(f"{BASE}/api/inspections/1/status", headers=headers_inspect, json={"status": "恢复处理中"})
print(r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 10. 状态流转: 恢复处理中 -> 待复核 ===")
r = requests.put(f"{BASE}/api/inspections/1/status", headers=headers_inspect, json={"status": "待复核"})
print(r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 11. 复核员提交复核 ===")
r = requests.post(f"{BASE}/api/reviews", headers=headers_review, json={
    "inspection_id": 1,
    "restored_width": 4.2,
    "passage_restored": True,
    "review_conclusion": "违停车辆已移走，通道恢复畅通，宽度达标",
    "risk_level": "低",
    "closing_opinion": "同意关闭，建议加强日常巡查"
})
print(r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 12. 查询巡检记录列表 ===")
r = requests.get(f"{BASE}/api/inspections?page=1&page_size=10", headers=headers_admin)
data = r.json()
print(f"总记录数: {data['total']}")
for item in data['items']:
    print(f"  ID:{item['id']} 通道:{item['lane_number']} 楼宇:{item['building_name']} 状态:{item['status']} 占用:{item['is_occupied']} 超时:{item['is_overdue']} 指示牌异常:{item['has_sign_anomaly']} 宽度不达标:{item['width_insufficient']} 风险等级:{item['risk_level']}")

print("\n=== 13. 高风险通道排行 ===")
r = requests.get(f"{BASE}/api/stats/high-risk-lanes?limit=10", headers=headers_admin)
print(json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 14. 待复核清单 ===")
r = requests.get(f"{BASE}/api/stats/pending-reviews", headers=headers_admin)
data = r.json()
print(f"待复核数量: {data['total']}")

print("\n=== 15. 通行恢复完成率 ===")
r = requests.get(f"{BASE}/api/stats/restoration-rate", headers=headers_admin)
print(json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 16. 楼宇异常集中分布 ===")
r = requests.get(f"{BASE}/api/stats/building-anomalies", headers=headers_admin)
print(json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 17. 总览统计 ===")
r = requests.get(f"{BASE}/api/stats/overview", headers=headers_admin)
print(json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 18. 部门处理延迟 ===")
r = requests.get(f"{BASE}/api/stats/department-delay", headers=headers_admin)
print(json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n=== 19. 按占用状态筛选 ===")
r = requests.get(f"{BASE}/api/inspections?is_occupied=true", headers=headers_admin)
print(f"占用记录数: {r.json()['total']}")

print("\n=== 20. 执行全局自动检测 ===")
r = requests.post(f"{BASE}/api/detections/run", headers=headers_admin)
print(json.dumps(r.json(), ensure_ascii=False, indent=2))

print("\n✅ 所有测试完成!")
