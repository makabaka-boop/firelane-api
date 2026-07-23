#!/usr/bin/env python3
"""验证三个 Bug 修复的测试脚本"""
import requests
import json
from datetime import date, datetime, timedelta

BASE = "http://localhost:8150"

def login(username, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": username, "password": password})
    return r.json()["access_token"]

def setup():
    admin = login("admin", "admin123")
    inspector = login("inspector", "inspect123")
    reviewer = login("reviewer", "review123")
    return {
        "admin": {"Authorization": f"Bearer {admin}", "Content-Type": "application/json"},
        "inspect": {"Authorization": f"Bearer {inspector}", "Content-Type": "application/json"},
        "review": {"Authorization": f"Bearer {reviewer}", "Content-Type": "application/json"},
    }

def api(method, path, headers, json_data=None, expected=None):
    r = requests.request(method, f"{BASE}{path}", headers=headers, json=json_data)
    try:
        body = r.json()
    except Exception:
        body = r.text
    tag = "✅" if expected is None or r.status_code == expected else "❌"
    print(f"{tag} {method} {path} -> {r.status_code}")
    return r, body

print("=" * 60)
print("Bug 修复验证测试")
print("=" * 60)

h = setup()

# ------ 准备基础数据 ------
print("\n--- 准备：创建楼宇和通道 ---")
r, b1 = api("POST", "/api/admin/buildings", h["admin"], {"name": "A座", "address": "东区"}, 200)
api("POST", "/api/admin/buildings", h["admin"], {"name": "B座", "address": "西区"}, 200)

r, l1 = api("POST", "/api/admin/lanes", h["admin"], {
    "building_id": 1, "lane_number": "A-001",
    "inspection_cycle_days": 7, "min_passable_width": 4.0,
    "responsible_dept": "安保部", "review_standard": ">=4m",
    "location_description": "东侧主通道"
}, 200)

r, l2 = api("POST", "/api/admin/lanes", h["admin"], {
    "building_id": 1, "lane_number": "A-002",
    "inspection_cycle_days": 7, "min_passable_width": 3.5,
    "responsible_dept": "物业部"
}, 200)

# ============================================================
# Bug 3 验证：管理员修改通道编号为同楼宇已有编号 -> 应返回400，不是500
# ============================================================
print("\n=== Bug3 验证：重复通道编号应返回400 ===")
r, body = api("PUT", "/api/admin/lanes/2", h["admin"], {"lane_number": "A-001"}, expected=400)
assert r.status_code == 400, f"期望400，实际{r.status_code}"
print(f"   返回信息: {body}")

r, body = api("PUT", "/api/admin/lanes/2", h["admin"], {"lane_number": "A-003"}, expected=200)
print(f"   改为不重复编号 A-003 成功")

# ============================================================
# Bug 2 验证：复核关闭时不填恢复宽度 -> 应拒绝
# ============================================================
print("\n=== Bug2 验证：复核通过关闭必须填写恢复宽度 ===")
today = date.today()
r, insp = api("POST", "/api/inspections", h["inspect"], {
    "lane_id": 1,
    "cycle_start_date": str(today - timedelta(days=7)),
    "cycle_end_date": str(today),
    "measured_width": 2.0, "is_occupied": True,
    "obstruction_type": "杂物堆放",
    "sign_status": "正常", "floor_marking_status": "正常",
    "site_notes": "有杂物", "risk_description": "堵了",
    "restoration_suggestion": "清理"
}, 200)
insp_id = insp["id"]
print(f"   创建巡检记录 ID={insp_id}, 初始状态={insp['status']}")

# 流转到待复核
api("PUT", f"/api/inspections/{insp_id}/status", h["inspect"], {"status": "恢复处理中"}, 200)
api("PUT", f"/api/inspections/{insp_id}/status", h["inspect"], {"status": "待复核"}, 200)

# 不填恢复宽度直接关闭
r, body = api("POST", "/api/reviews", h["review"], {
    "inspection_id": insp_id,
    "restored_width": None,
    "passage_restored": True,
    "review_conclusion": "清理完成",
    "risk_level": "低"
}, expected=400)
assert r.status_code == 400, f"期望400，实际{r.status_code}"
print(f"   不填恢复宽度被拒绝: {body['detail']}")

# ============================================================
# Bug 1 验证：复核未通过 -> 退回恢复处理中 -> 整改后再次复核通过
# ============================================================
print("\n=== Bug1 验证：复核未通过退回整改后可再次复核 ===")
# 第一次复核：不通过，未恢复
r, body = api("POST", "/api/reviews", h["review"], {
    "inspection_id": insp_id,
    "restored_width": 3.0,
    "passage_restored": False,
    "review_conclusion": "杂物未清理干净，宽度不足",
    "risk_level": "高"
}, expected=200)
assert r.status_code == 200
print(f"   第一次复核未通过，复核记录已保存")

# 查看巡检记录状态应回到恢复处理中
r, rec = api("GET", f"/api/inspections/{insp_id}", h["admin"])
print(f"   当前状态: {rec['status']}  (应为 恢复处理中)")
assert rec["status"] == "恢复处理中", f"状态应为恢复处理中，实际{rec['status']}"

# 恢复宽度不足但试图通过 -> 应被拒绝并退回
# 先流转回待复核
api("PUT", f"/api/inspections/{insp_id}/status", h["inspect"], {"status": "待复核"}, 200)

r, body = api("POST", "/api/reviews", h["review"], {
    "inspection_id": insp_id,
    "restored_width": 3.5,
    "passage_restored": True,
    "review_conclusion": "已清理",
    "risk_level": "中"
}, expected=400)
print(f"   恢复宽度不达标(3.5 < 4.0)被退回: {body['detail']}")

# 再查看状态
r, rec = api("GET", f"/api/inspections/{insp_id}", h["admin"])
print(f"   退回后状态: {rec['status']}  (应为 恢复处理中)")
assert rec["status"] == "恢复处理中"
print(f"   累计复核次数: {rec['review_count']} (应为 2)")

# 整改完成，流转到待复核，再次复核通过
api("PUT", f"/api/inspections/{insp_id}/status", h["inspect"], {"status": "待复核"}, 200)
r, body = api("POST", "/api/reviews", h["review"], {
    "inspection_id": insp_id,
    "restored_width": 4.2,
    "passage_restored": True,
    "review_conclusion": "杂物已清理，宽度达标，通道恢复畅通",
    "risk_level": "低",
    "closing_opinion": "同意关闭"
}, expected=200)
assert r.status_code == 200
print(f"   第三次复核通过并关闭")

r, rec = api("GET", f"/api/inspections/{insp_id}", h["admin"])
print(f"   最终状态: {rec['status']}  (应为 已关闭)")
print(f"   累计复核次数: {rec['review_count']} (应为 3)")
print(f"   最新风险等级: {rec['risk_level']} (应为 低)")
assert rec["status"] == "已关闭"
assert rec["review_count"] == 3

print("\n" + "=" * 60)
print("复核历史记录:")
for rv in rec["review_history"]:
    print(f"  - [{rv['review_time'][:19]}] 通过={rv['passage_restored']} 宽度={rv['restored_width']} 风险={rv['risk_level']} 结论: {rv['review_conclusion']}")
print("=" * 60)
print("✅ 全部三个 Bug 修复验证通过！")
