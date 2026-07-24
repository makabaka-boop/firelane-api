# firelane-api

园区消防通道安全巡检与通行风险闭环管理接口服务。基于 FastAPI + SQLAlchemy(SQLite)，通过 JWT 登录，支持管理员 / 巡检员 / 复核员三类账号协同，覆盖巡检、通行受阻处理、复核关闭全流程，并提供周期去重、异常自动识别、多维筛选与统计输出。

## 技术栈
- FastAPI + Uvicorn（后端端口 **8150**）
- SQLAlchemy ORM + SQLite（`firelane.db`）
- python-jose（JWT）+ passlib/bcrypt（密码哈希）

## 启动
```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8150
```
Swagger 文档：http://127.0.0.1:8150/docs  · 健康检查：`GET /api/health`

## 预置账号
| 角色 | 用户名 | 密码 | 说明 |
| --- | --- | --- | --- |
| 管理员 admin | `admin` | `admin123` | 维护楼宇/通道/账号 |
| 巡检员 inspector | `inspector` | `insp123` | 按周期提交巡检 |
| 复核员 reviewer | `reviewer` | `rev123` | 记录复核并关闭 |

## 核心模型
- **Building** 楼宇（名称、编码）
- **FireLane** 消防通道：编号、位置描述、巡检周期、最小通行宽度、指示牌检查规则、责任部门、复核标准
- **InspectionRecord** 巡检：实测宽度、是否占用、占用物类型、指示牌/地贴状态、现场备注、风险说明、恢复建议、要求完成时间
- **ReviewRecord** 复核：复核时间、实测恢复宽度、通行是否恢复、复核结论、风险等级、关闭意见

## 状态机
`待巡检 pending → 巡检中 inspecting → 通行受阻 blocked → 恢复处理中 recovering → 待复核 to_review → 已关闭 closed`
- 巡检提交：占用或宽度不足 → `blocked`，否则 → `to_review`
- 复核：恢复且宽度达标 → `closed`；否则退回 `recovering`（可再次复核，保留历史）
- 同一消防通道同一巡检周期不可重复创建记录（`(lane_id, cycle_key)` 唯一约束）

## 主要接口
- 认证：`POST /api/auth/login`、`GET /api/auth/me`
- 管理员：`POST /api/users`、`POST /api/buildings`、`POST/PUT /api/lanes`
- 巡检员：`POST /api/inspections`、`.../recovering`、`.../submit-review`
- 复核员：`POST /api/reviews`
- 查询：`GET /api/inspections`（按楼宇/通道/责任部门/状态/风险等级/是否占用/日期范围筛选）
- 异常识别：`GET /api/anomalies`（整改超时、责任部门处理延迟、指示牌异常、复核结论缺失、恢复宽度不达标、同楼宇通道异常集中）
- 统计：`/api/stats/high-risk-ranking`、`/api/stats/pending-review`、`/api/stats/recovery-rate`、`/api/stats/building-anomaly-distribution`

## 测试
服务启动后运行端到端测试（29 条断言）：
```bash
python test_api.py
```
