import os
import json
import logging
import datetime as dt

import azure.functions as func
from azure.communication.email import EmailClient
try:
    # SMS is optional; import only if you enable it
    from azure.communication.sms import SmsClient  # type: ignore
except Exception:  # pragma: no cover
    SmsClient = None  # SMS disabled if package isn't present

import pytds
import certifi

# ---------- Configuration ----------
SQL_SERVER   = os.environ["SQL_SERVER"]
SQL_DB       = os.environ["SQL_DB"]
SQL_USER     = os.environ["SQL_USER"]
SQL_PASSWORD = os.environ["SQL_PASSWORD"]

ACS_CONNSTR  = os.environ.get("ACS_CONNSTR", "")
FROM_EMAIL   = os.environ.get("FROM_EMAIL", "")

# SMS is optional (defaults OFF)
ENABLE_SMS   = os.environ.get("ENABLE_SMS", "false").lower() == "true"
FROM_PHONE   = os.environ.get("FROM_PHONE", "")

ENABLE_EMAIL = os.environ.get("ENABLE_EMAIL", "true").lower() == "true"

# ---------- DB helper ----------
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

# ---------- Email helper ----------
def _send_email(to_addr: str, display: str, subject: str, body_text: str) -> bool:
    if not ENABLE_EMAIL:
        logging.info("Email disabled; would send to %s: %s", to_addr, subject)
        return True  # treat as success so we don't retry forever
    if not ACS_CONNSTR or not FROM_EMAIL:
        raise RuntimeError("Email is enabled but ACS_CONNSTR or FROM_EMAIL is not configured")

    client = EmailClient.from_connection_string(ACS_CONNSTR)
    message = {
        "senderAddress": FROM_EMAIL,
        "recipients": {"to": [{"address": to_addr, "displayName": display}]},
        "content": {"subject": subject, "plainText": body_text},
    }
    poller = client.begin_send(message)
    _ = poller.result()  # will raise on failure
    logging.info("Email accepted by ACS to=%s subject=%s", to_addr, subject)
    return True

# ---------- SMS helper (optional) ----------
def _send_sms(to_phone: str, body_text: str) -> bool:
    if not ENABLE_SMS:
        logging.info("SMS disabled; would send to %s: %s", to_phone, body_text)
        return True
    if not SmsClient:
        raise RuntimeError("SMS enabled but azure-communication-sms package is not available")
    if not ACS_CONNSTR or not FROM_PHONE:
        raise RuntimeError("SMS enabled but ACS_CONNSTR or FROM_PHONE not set")

    sms = SmsClient.from_connection_string(ACS_CONNSTR)  # type: ignore
    resp = sms.send(from_=FROM_PHONE, to=[to_phone], message=body_text)
    logging.info("SMS send response: %s", resp)
    return True

# ---------- Main trigger ----------
def main(msg: func.ServiceBusMessage):
    """
    Expects a JSON body: { "shift_id": "<guid>", "kind": "day_before" | "two_hours" }
    """
    body = msg.get_body().decode("utf-8")
    logging.info("Reminder message received: %s", body)

    try:
        data = json.loads(body)
        shift_id = data["shift_id"]
        kind     = data["kind"]
    except Exception as ex:
        logging.exception("Bad message format: %s", ex)
        return

    # Fetch shift + user
    try:
        with get_db() as cxn, cxn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    s.shift_id,
                    s.shift_start_utc,
                    s.shift_start_local,
                    s.tz,
                    u.name,
                    u.email,
                    u.phone_e164
                FROM dbo.Shifts s
                JOIN dbo.Users u ON s.user_id = u.user_id
                WHERE s.shift_id = %s
                """,
                (shift_id,)
            )
            row = cur.fetchone()

        if not row:
            logging.warning("Shift not found for shift_id=%s; dropping message", shift_id)
            return

        _shift_id, shift_start_utc, shift_start_local, tz_name, name, email, phone = row
    except Exception as ex:
        logging.exception("DB read failed for shift_id=%s: %s", shift_id, ex)
        # raise so SB will retry; if it keeps failing, it will DLQ
        raise

    # Message content
    if kind == "day_before":
        subject = "Reminder: your shift is tomorrow"
        col     = "day_before_sent_at"
        window  = "tomorrow"
    else:
        subject = "Reminder: your shift is in ~2 hours"
        col     = "two_hours_sent_at"
        window  = "in about 2 hours"

    local_str = (
        shift_start_local.isoformat() if hasattr(shift_start_local, "isoformat")
        else str(shift_start_local or "")
    )
    utc_str = (
        shift_start_utc.isoformat() if hasattr(shift_start_utc, "isoformat")
        else str(shift_start_utc or "")
    )
    text = (
        f"Hi {name}, this is a reminder that your shift is {window}.\n"
        f"Local time: {local_str} ({tz_name})\n"
        f"UTC time:   {utc_str}\n"
        "Reply YES to acknowledge (if SMS is enabled)."
    )

    # Try to deliver at least one channel
    delivered = False
    try:
        if email:
            delivered = _send_email(email, name, subject, text) or delivered
    except Exception as ex:
        logging.exception("Email send failed: %s", ex)

    try:
        if phone and ENABLE_SMS and FROM_PHONE:
            delivered = _send_sms(phone, text) or delivered
    except Exception as ex:
        logging.exception("SMS send failed: %s", ex)

    if not delivered:
        logging.error("No delivery channel succeeded for shift_id=%s", shift_id)
        raise RuntimeError("Reminder delivery failed")

    try:
        with get_db() as cxn, cxn.cursor() as cur:
            cur.execute(
                f"UPDATE dbo.Shifts SET {col} = SYSUTCDATETIME() WHERE shift_id = %s",
                (shift_id,)
            )
            cxn.commit()
        logging.info("Marked %s for shift_id=%s", col, shift_id)
    except Exception as ex:
        logging.exception("DB update failed for shift_id=%s: %s", shift_id, ex)
        raise
