import os
import json
import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import azure.functions as func
from azure.servicebus import ServiceBusClient, ServiceBusMessage

import pytds, certifi
from dateutil import tz  # fallback tz provider

SQL_SERVER   = os.environ["SQL_SERVER"]
SQL_DB       = os.environ["SQL_DB"]
SQL_USER     = os.environ["SQL_USER"]
SQL_PASSWORD = os.environ["SQL_PASSWORD"]
SB_CONNSTR   = os.environ.get("SB_CONNSTR")
SB_QUEUE     = os.environ.get("SB_QUEUE", "reminders")

def get_db():
    return pytds.connect(
        server=SQL_SERVER,
        database=SQL_DB,
        user=SQL_USER,
        password=SQL_PASSWORD,
        port=1433,
        cafile=certifi.where(),
        validate_host=False,
    )

def get_zone(tz_name: str):
    """Prefer stdlib ZoneInfo, fall back to dateutil if tzdata isn't available."""
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        z = tz.gettz(tz_name)
        if z is None:
            # last-ditch fallback – don’t crash the booking
            return ZoneInfo("UTC")
        return z

def _parse_iso_local(iso_str: str, tz_name: str) -> tuple[dt.datetime, dt.datetime]:
    Y, M, D = map(int, iso_str[0:10].split("-"))
    h, m, s = map(int, iso_str[11:19].split(":"))
    local_dt = dt.datetime(Y, M, D, h, m, s, tzinfo=get_zone(tz_name))
    return local_dt, local_dt.astimezone(dt.timezone.utc)

def post(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse("Invalid JSON", status_code=400)

    user_id = (body.get("user_id") or "").strip()
    shift_local_iso = (body.get("shift_local_iso") or "").strip()
    tz_name = (body.get("tz") or "America/New_York").strip()
    notes = body.get("notes")

    if not user_id or not shift_local_iso:
        return func.HttpResponse("user_id and shift_local_iso required", status_code=400)

    try:
        local_dt, shift_utc = _parse_iso_local(shift_local_iso, tz_name)
    except Exception as ex:
        return func.HttpResponse(f"Invalid date/time or timezone: {ex}", status_code=400)

    local_naive = local_dt.replace(tzinfo=None)

    try:
        with get_db() as cxn, cxn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dbo.Shifts
                    (shift_id, user_id, shift_start_utc, shift_start_local, tz, notes, created_at)
                OUTPUT inserted.shift_id
                VALUES
                    (NEWID(), %s, %s, %s, %s, %s, SYSUTCDATETIME())
                """,
                (user_id, shift_utc, local_naive, tz_name, notes)
            )
            shift_id = str(cur.fetchone()[0])
            cxn.commit()
    except Exception as ex:
        return func.HttpResponse(f"DB error: {ex}", status_code=500)

    try:
        if SB_CONNSTR:
            day_before = shift_utc - dt.timedelta(hours=24)
            two_hours  = shift_utc - dt.timedelta(hours=2)
            with ServiceBusClient.from_connection_string(SB_CONNSTR) as sbc:
                with sbc.get_queue_sender(queue_name=SB_QUEUE) as sender:
                    sender.schedule_messages(
                        ServiceBusMessage(json.dumps({"shift_id": shift_id, "kind": "day_before"})),
                        schedule_time_utc=day_before
                    )
                    sender.schedule_messages(
                        ServiceBusMessage(json.dumps({"shift_id": shift_id, "kind": "two_hours"})),
                        schedule_time_utc=two_hours
                    )
    except Exception as ex:
        return func.HttpResponse(
            json.dumps({
                "shift_id": shift_id,
                "shift_start_utc": shift_utc.isoformat(),
                "warning": f"Scheduled reminders failed: {ex}"
            }),
            mimetype="application/json",
            status_code=200
        )

    return func.HttpResponse(
        json.dumps({"shift_id": shift_id, "shift_start_utc": shift_utc.isoformat()}),
        mimetype="application/json",
        status_code=201
    )

def get(req: func.HttpRequest) -> func.HttpResponse:
    user_id = req.params.get("user_id")
    if not user_id:
        return func.HttpResponse("user_id required", status_code=400)

    with get_db() as cxn, cxn.cursor() as cur:
        cur.execute(
            """
            SELECT shift_id, shift_start_local, tz, notes
            FROM dbo.Shifts
            WHERE user_id = %s
            ORDER BY shift_start_local DESC
            """,
            (user_id,)
        )
        rows = cur.fetchall()

    items = [{
        "shift_id": str(r[0]),
        "shift_start_local": r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1]),
        "tz": r[2],
        "notes": r[3] or ""
    } for r in rows]

    return func.HttpResponse(json.dumps({"items": items}), mimetype="application/json")

def main(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "POST":
        return post(req)
    if req.method == "GET":
        return get(req)
    return func.HttpResponse(status_code=405)
