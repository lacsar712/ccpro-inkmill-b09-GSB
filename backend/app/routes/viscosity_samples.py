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

# 东八区。from/to 查询参数一律按此时区的挂钟时间解释。
CST = timezone(timedelta(hours=8))
EXPORT_COLUMNS = ["millCode", "workshopName", "sampledAt", "viscosityPaS", "tempC", "notes"]


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


def _parse_int_arg(name: str) -> int | None:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_cst_boundary(raw: str) -> datetime | None:
    """把 from/to 按东八区解释为可与库存 naive 时间比较的 naive datetime。

    裸日期取当日 00:00；带时区/ Z 的时间先换算到东八区再去掉 tzinfo。
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("时间格式无效，请使用 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(CST).replace(tzinfo=None)
    return parsed


def _export_dataset(db) -> tuple[list[dict] | None, str | None]:
    """导出与对账共用的唯一取数口径：同筛选、同 JOIN、同排序。

    workshopName 一律经 sample.mill_id -> Mill.workshop_id -> Workshop 取得，
    不按 millCode 反查车间。
    """
    workshop_id = _parse_int_arg("workshopId")
    mill_id = _parse_int_arg("millId")
    try:
        start = _parse_cst_boundary(request.args.get("from", ""))
        end = _parse_cst_boundary(request.args.get("to", ""))
    except ValueError as exc:
        return None, str(exc)
    if start is not None and end is not None and start > end:
        return None, "起始时间不能晚于结束时间"

    query = (
        db.query(ViscositySample, Mill, Workshop)
        .join(Mill, ViscositySample.mill_id == Mill.id)
        .join(Workshop, Mill.workshop_id == Workshop.id)
    )
    if workshop_id is not None:
        query = query.filter(Mill.workshop_id == workshop_id)
    if mill_id is not None:
        query = query.filter(ViscositySample.mill_id == mill_id)
    if start is not None:
        query = query.filter(ViscositySample.sampled_at >= start)
    if end is not None:
        query = query.filter(ViscositySample.sampled_at <= end)
    query = query.order_by(ViscositySample.sampled_at.asc(), ViscositySample.id.asc())

    records: list[dict] = []
    for sample, mill, workshop in query.all():
        records.append(
            {
                "millCode": mill.mill_code,
                "workshopId": workshop.id,
                "workshopName": workshop.name,
                "sampledAt": sample.sampled_at.strftime("%Y-%m-%d %H:%M:%S"),
                "viscosity": sample.viscosity_pa_s,
                "viscosityText": f"{sample.viscosity_pa_s:.4f}",
                "tempText": "" if sample.temp_c is None else f"{sample.temp_c:.2f}",
                "notes": sample.notes or "",
            }
        )
    return records, None


@bp.get("/export.csv")
@jwt_required()
def export_csv():
    db = SessionLocal()
    try:
        records, err = _export_dataset(db)
        if err:
            return error(err, 400)

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(EXPORT_COLUMNS)
        for r in records:
            writer.writerow(
                [
                    r["millCode"],
                    r["workshopName"],
                    r["sampledAt"],
                    r["viscosityText"],
                    r["tempText"],
                    r["notes"],
                ]
            )

        return Response(
            buf.getvalue().encode("utf-8-sig"),
            mimetype="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=viscosity-samples.csv"
            },
        )
    finally:
        db.close()


@bp.get("/export-check")
@jwt_required()
def export_check():
    db = SessionLocal()
    try:
        records, err = _export_dataset(db)
        if err:
            return error(err, 400)

        total = Decimal("0")
        grouped: dict[int, dict] = {}
        for r in records:
            total += r["viscosity"]
            bucket = grouped.get(r["workshopId"])
            if bucket is None:
                bucket = {
                    "workshopId": r["workshopId"],
                    "workshopName": r["workshopName"],
                    "count": 0,
                    "sumViscosity": Decimal("0"),
                }
                grouped[r["workshopId"]] = bucket
            bucket["count"] += 1
            bucket["sumViscosity"] += r["viscosity"]

        by_workshop = [
            {
                "workshopId": b["workshopId"],
                "workshopName": b["workshopName"],
                "count": b["count"],
                "sumViscosity": float(b["sumViscosity"]),
            }
            for b in grouped.values()
        ]
        return jsonify(
            {
                "rows": len(records),
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
