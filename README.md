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

## 粘度取样导出（服务端 CSV + 对账）

导出由后端统一生成，前端**不拼接 CSV**，避免口径漂移。所有接口需 JWT。

| 接口 | 说明 |
|------|------|
| `GET /api/viscosity-samples/export.csv` | 下载 CSV，**UTF-8 BOM**（Excel 直开中文不乱码），列依次为 `millCode, workshopName, sampledAt, viscosityPaS, tempC, notes` |
| `GET /api/viscosity-samples/export-check` | 对账 JSON：`rows`、`sumViscosity`、`byWorkshop`（每项含 `workshopId, workshopName, count, sumViscosity`） |

两个接口共用同一套筛选与同一段取数代码：

- 查询参数：`workshopId`、`millId`、`from`、`to`，均可省略；无筛选时导出全部。
- `from`/`to` 按**东八区（UTC+8）**解释，支持 `YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM:SS`；仅传日期时，`to` 含当天全天（到 23:59:59.999999）。
- `from` 晚于 `to` 返回 **HTTP 400**，中文消息「起始时间不能晚于结束时间」。
- `workshopName` 必须经取样记录的 `millId` → `mills.workshopId` → `workshops` 关联得出（不按 `millCode` 猜车间），因此两个车间存在相同 `millCode` 时，导出行的车间名仍各自归属正确。
- 空结果集：CSV 仅含表头一行，`export-check.rows === 0`、`sumViscosity === 0`、`byWorkshop === []`。

**对账口径保证**：`rows` 等于 CSV 数据行数（不含表头）；`sumViscosity` 与 CSV 粘度列之和一致（允许绝对误差 0.0001，合计在服务端以 `Decimal` 精确累加）。

**前端两步流程**（粘度取样页「导出 CSV」面板）：

1. 选择车间 / 研磨机 / 起止时间后点击「对账」，页面展示总行数、粘度合计与按车间分组；
2. 核对无误后点击「确认下载 CSV」，浏览器携带 JWT 请求 `export.csv`。

下载请求**原样复用对账时的 query string**，两次请求筛选条件必然一致；筛选条件一旦变更，对账结果立即失效，必须重新对账后才能下载。

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
