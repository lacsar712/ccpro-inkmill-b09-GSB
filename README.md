# InkMill-01 · 油墨研磨台账

面向印刷油墨研磨车间的**研磨机状态、粘度取样与研磨遍次**台账系统。  
**不是**库存、电商或 CMS 场景。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11、Flask、SQLAlchemy、PyMySQL、Flask-JWT-Extended、passlib/bcrypt、gunicorn |
| 前端 | Svelte 4、Vite、TypeScript |
| 数据库 | MySQL 8 |

## 端口与数据库

| 服务 | 宿主机端口 |
|------|------------|
| 统一入口 (Nginx) | **4200** |
| 后端 API | **9200** |
| MySQL | **3312** |

MySQL 连接：`inkmill` / `inkmill` / `inkmill`（库名/用户/密码）

## 演示账号

密码均为 **123456**：

- `admin` — 管理员
- `grinder` — 研磨工

## 领域实体（JSON 驼峰）

1. **Workshop**：`name`, `site`, `notes`
2. **Mill**：`workshopId`, `millCode`（同车间唯一）, `pigmentBase`, `bowlLiters`, `status`（`grinding` \| `idle` \| `wash`）
3. **ViscositySample**：`millId`, `sampledAt`, `viscosityPaS`（须 &gt; 0，否则 HTTP 400）, `tempC`, `notes`
4. **GrindPass**：`millId`, `startedAt`, `passNo`（≥ 1）, `durationMin`（&gt; 0）, `mediaType`, `operatorName`
5. **Dashboard**：`workshopTotal`, `grindingMillCount`, `samplesLast24h`, `passesLast7d`

## 快速启动（Docker）

```bash
cd InkMill-01
docker compose up --build -d
```

浏览器访问：**http://localhost:4200**  
前端 Nginx 将 `/api/` 反向代理到后端 `9200`。

后端容器启动流程：

1. 等待 MySQL 就绪（`DB_HOST=mysql`）
2. SQLAlchemy `create_all` 建表
3. `SEED_ON_START=true` 时写入演示数据
4. gunicorn 监听 `0.0.0.0:9200`

健康检查：`GET /api/health` → `{"status":"ok","service":"InkMill"}`

## 粘度取样导出与对账（服务端生成）

CSV **只由后端生成**，前端不拼接任何 CSV 行。导出前先调对账接口核对行数与合计，确认后再用**完全相同的筛选条件**下载 CSV。

两个接口共用同一套筛选、同一条 JOIN 查询与同一排序（唯一实现，不存在两套口径）；`workshopName` 一律经 `取样.millId → Mill.workshopId → Workshop` 取得，**不按 millCode 反查车间**，因此不同车间下出现相同 millCode 时车间名仍各归其主。

| 接口 | 说明 |
|------|------|
| `GET /api/viscosity-samples/export.csv` | 下载 CSV，**UTF-8 BOM**（`utf-8-sig`，Excel 直接打开不乱码） |
| `GET /api/viscosity-samples/export-check` | 同口径对账，返回行数、粘度合计与按车间拆分 |

查询参数（均可选，无参数导出全部）：

| 参数 | 含义 |
|------|------|
| `workshopId` | 按研磨机所属车间过滤 |
| `millId` | 按研磨机过滤（与车间同码机台靠 id 精确区分） |
| `from` | 起始时间（含），按**东八区**解释；裸日期取当日 `00:00` |
| `to` | 结束时间（含），同样按东八区解释 |

- 时间格式：`YYYY-MM-DD` 或 `YYYY-MM-DDTHH:MM:SS`，也接受 `Z`/带偏移量（会换算到东八区）。
- `from > to` 时两个接口都返回 **HTTP 400**，`{"message": "起始时间不能晚于结束时间"}`。
- 空结果：CSV **仅含表头**，对账 `rows = 0`。

CSV 列顺序固定为：

```
millCode,workshopName,sampledAt,viscosityPaS,tempC,notes
```

对账响应：

```json
{
  "rows": 3,
  "sumViscosity": 10.3501,
  "byWorkshop": [
    { "workshopId": 1, "workshopName": "一号油墨车间", "count": 2, "sumViscosity": 5.1001 },
    { "workshopId": 2, "workshopName": "调墨中心",     "count": 1, "sumViscosity": 5.25 }
  ]
}
```

`rows` 等于 CSV 数据行数；`sumViscosity` 与 CSV 粘度列之和的绝对误差 ≤ `0.0001`。

前端「粘度取样」页流程：选择车间 / 研磨机 / 起止时间 → 点**对账**展示行数、合计与按车间明细 → 点**确认并下载 CSV**；筛选一旦改动，下载按钮禁用并提示重新对账，确保两次请求条件一致。


## 本地开发（可选）

**后端**（需本机 MySQL 或连 Docker 的 3312 端口）：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
set DB_HOST=127.0.0.1
set DB_PORT=3312
set DB_USER=inkmill
set DB_PASSWORD=inkmill
set DB_NAME=inkmill
set JWT_SECRET=inkmill-jwt-secret-change-me
python -c "from app.database import Base, engine; from app import models; Base.metadata.create_all(bind=engine)"
python -c "from app.seed import seed; seed()"
gunicorn wsgi:app --bind 127.0.0.1:9200 --reload
```

**前端**：

```bash
cd frontend
npm install
npm run dev
```

Vite 开发服务器端口 **4200**，`/api` 代理到 `127.0.0.1:9200`。

## 目录结构

```
InkMill-01/
├── docker-compose.yml
├── nginx/nginx.conf          # 4200 统一入口，/api → backend
├── backend/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── requirements.txt
│   ├── wsgi.py
│   └── app/                  # Flask 路由、模型与种子数据
└── frontend/
    ├── Dockerfile
    ├── vite.config.ts
    └── src/routes/           # Login / Dashboard / CRUD 页面
```

## UI 主题

墨黑底 + 朱砂强调色，无紫色光晕风格。
