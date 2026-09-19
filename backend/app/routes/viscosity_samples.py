import csv
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, Response, jsonify, request
from flask_jwt_extended import jwt_required

from app.database import SessionLocal
from app.models.mill import Mill
from app.models.viscosity_sample import ViscositySample
from app.models.workshop import Workshop
from app.serializers import viscosity_sample_json
from app.utils import error, normalize_datetime

bp = Blueprint("viscosity_samples", __name__, url_prefix="/api/viscosity-samples")

CST = timezone(timedelta(hours=8))

CSV_HEADER = ["millCode", "workshopName", "sampledAt", "viscosityPaS", "tempC", "notes"]


def _validate(body: dict) -> str | None:
    mill_id = int(body.get("millId") or 0)
    if mill_id <= 0:
        return "请选择研磨机"

    db = SessionLocal()
    try:
        if not db.get(Mill, mill_id):
            return "研磨机不存在"
    finally:
        db.close()

    sampled_at = str(body.get("sampledAt", "")).strip()
    if not sampled_at:
        return "取样时间不能为空"

    viscosity = float(body.get("viscosityPaS") or 0)
    if viscosity <= 0:
        return "粘度(Pa·s)必须大于 0"

    return None


def _parse_int_arg(name: str) -> tuple[int | None, str | None]:
    raw = request.args.get(name)
    if raw is None or str(raw).strip() == "":
        return None, None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None, "参数无效，必须为正整数"
    if value <= 0:
        return None, "参数无效，必须为正整数"
    return value, None


def _parse_bound(raw: str, end_of_day: bool) -> datetime:
    """把查询参数按东八区解释成 naive datetime（与库内本地时间口径一致）。"""
    text = raw.strip().replace("T", " ")
    date_only = len(text) == 10
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            break
        except ValueError:
            dt = None
    if dt is None:
        # 兼容带时区的 ISO 字符串：先解析再换算到东八区墙钟时间。
        try:
            parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("时间格式无效") from exc
        if parsed.tzinfo is None:
            raise ValueError("时间格式无效")
        dt = parsed.astimezone(CST).replace(tzinfo=None)
    elif date_only and end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


def _export_filters() -> tuple[dict | None, tuple | None]:
    """解析导出/对账共用的筛选条件。返回 (filters, None) 或 (None, 错误响应)。"""
    workshop_id, err = _parse_int_arg("workshopId")
    if err:
        return None, error(f"车间{err}", 400)
    mill_id, err = _parse_int_arg("millId")
    if err:
        return None, error(f"研磨机{err}", 400)

    from_raw = request.args.get("from")
    to_raw = request.args.get("to")
    try:
        from_dt = _parse_bound(from_raw, end_of_day=False) if from_raw and from_raw.strip() else None
        to_dt = _parse_bound(to_raw, end_of_day=True) if to_raw and to_raw.strip() else None
    except ValueError:
        return None, error("时间格式无效，支持 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS（东八区）", 400)

    if from_dt and to_dt and from_dt > to_dt:
        return None, error("起始时间不能晚于结束时间", 400)

    return (
        {"workshop_id": workshop_id, "mill_id": mill_id, "from_dt": from_dt, "to_dt": to_dt},
        None,
    )


def _export_rows(db, filters: dict):
    """取样 → millId → Mill.workshopId → Workshop，唯一取数口径，导出与对账共用。"""
    query = (
        db.query(ViscositySample, Mill, Workshop)
        .join(Mill, ViscositySample.mill_id == Mill.id)
        .join(Workshop, Mill.workshop_id == Workshop.id)
    )
    if filters["mill_id"] is not None:
        query = query.filter(ViscositySample.mill_id == filters["mill_id"])
    if filters["workshop_id"] is not None:
        query = query.filter(Mill.workshop_id == filters["workshop_id"])
    if filters["from_dt"] is not None:
        query = query.filter(ViscositySample.sampled_at >= filters["from_dt"])
    if filters["to_dt"] is not None:
        query = query.filter(ViscositySample.sampled_at <= filters["to_dt"])
    return query.order_by(ViscositySample.sampled_at.asc(), ViscositySample.id.asc()).all()


def _csv_text(sample: ViscositySample, mill: Mill, workshop: Workshop) -> list[str]:
    return [
        mill.mill_code,
        workshop.name,
        sample.sampled_at.strftime("%Y-%m-%d %H:%M:%S"),
        f"{sample.viscosity_pa_s:.4f}",
        "" if sample.temp_c is None else f"{sample.temp_c:.2f}",
        sample.notes or "",
    ]


@bp.get("")
@jwt_required()
def list_samples():
    db = SessionLocal()
    try:
        rows = (
            db.query(ViscositySample)
            .order_by(ViscositySample.sampled_at.desc(), ViscositySample.id.desc())
            .all()
        )
        return jsonify([viscosity_sample_json(r) for r in rows])
    finally:
        db.close()


@bp.get("/export.csv")
@jwt_required()
def export_csv():
    filters, err_response = _export_filters()
    if err_response is not None:
        return err_response

    db = SessionLocal()
    try:
        rows = _export_rows(db, filters)
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\r\n")
        writer.writerow(CSV_HEADER)
        for sample, mill, workshop in rows:
            writer.writerow(_csv_text(sample, mill, workshop))
        # UTF-8 BOM，保证 Excel 直接打开中文不乱码。
        resp = Response(
            "\ufeff" + buf.getvalue(),
            mimetype="text/csv; charset=utf-8",
        )
        resp.headers["Content-Disposition"] = "attachment; filename=viscosity-samples.csv"
        return resp
    finally:
        db.close()


@bp.get("/export-check")
@jwt_required()
def export_check():
    filters, err_response = _export_filters()
    if err_response is not None:
        return err_response

    db = SessionLocal()
    try:
        rows = _export_rows(db, filters)
        total = Decimal("0")
        grouped: dict[int, dict] = {}
        for sample, _mill, workshop in rows:
            total += sample.viscosity_pa_s
            bucket = grouped.setdefault(
                workshop.id,
                {"workshopId": workshop.id, "workshopName": workshop.name, "count": 0, "sum": Decimal("0")},
            )
            bucket["count"] += 1
            bucket["sum"] += sample.viscosity_pa_s

        by_workshop = [
            {
                "workshopId": item["workshopId"],
                "workshopName": item["workshopName"],
                "count": item["count"],
                "sumViscosity": float(item["sum"]),
            }
            for item in grouped.values()
        ]
        return jsonify(
            {
                "rows": len(rows),
                "sumViscosity": float(total),
                "byWorkshop": by_workshop,
            }
        )
    finally:
        db.close()


@bp.post("")
@jwt_required()
def create_sample():
    body = request.get_json(silent=True) or {}
    err = _validate(body)
    if err:
        return error(err, 400)

    temp_raw = body.get("tempC")
    temp_c = None
    if temp_raw is not None and temp_raw != "":
        temp_c = Decimal(str(temp_raw))

    db = SessionLocal()
    try:
        row = ViscositySample(
            mill_id=int(body["millId"]),
            sampled_at=normalize_datetime(str(body["sampledAt"])),
            viscosity_pa_s=Decimal(str(body["viscosityPaS"])),
            temp_c=temp_c,
            notes=str(body.get("notes", "")).strip() or None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return jsonify(viscosity_sample_json(row)), 201
    finally:
        db.close()


@bp.put("/<int:item_id>")
@jwt_required()
def update_sample(item_id: int):
    body = request.get_json(silent=True) or {}
    err = _validate(body)
    if err:
        return error(err, 400)

    temp_raw = body.get("tempC")
    temp_c = None
    if temp_raw is not None and temp_raw != "":
        temp_c = Decimal(str(temp_raw))

    db = SessionLocal()
    try:
        row = db.get(ViscositySample, item_id)
        if not row:
            return error("粘度取样记录不存在", 404)

        row.mill_id = int(body["millId"])
        row.sampled_at = normalize_datetime(str(body["sampledAt"]))
        row.viscosity_pa_s = Decimal(str(body["viscosityPaS"]))
        row.temp_c = temp_c
        row.notes = str(body.get("notes", "")).strip() or None
        db.commit()
        db.refresh(row)
        return jsonify(viscosity_sample_json(row))
    finally:
        db.close()


@bp.delete("/<int:item_id>")
@jwt_required()
def delete_sample(item_id: int):
    db = SessionLocal()
    try:
        row = db.get(ViscositySample, item_id)
        if not row:
            return error("粘度取样记录不存在", 404)
        db.delete(row)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()
