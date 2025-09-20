import os, json
import azure.functions as func
import certifi
import pytds as pytds
import logging


def get_db():
    server = "ppsql26632.database.windows.net"
    database = "patient_portal"
    user = "sqladmin"
    password = os.environ["SQL_PASSWORD"] 
    return pytds.connect(
        server=os.environ["SQL_SERVER"],
        database=os.environ["SQL_DB"],
        user=os.environ["SQL_USER"],
        password=os.environ["SQL_PASSWORD"],
        port=1433,
        cafile=certifi.where(),   # enables TLS
        validate_host=False,      # skip strict host validation (fine for Azure SQL)
    )

def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse("Invalid JSON", status_code=400)

    name  = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip()
    phone = (body.get("phone_e164") or "").strip()
    tz    = (body.get("tz") or "America/New_York").strip()

    if not name or not email:
        return func.HttpResponse("name and email required", status_code=400)

    try:
        with get_db() as cxn, cxn.cursor() as cur:
            # Reuse existing user by email
            cur.execute("SELECT user_id FROM dbo.Users WHERE email=%s", (email,))
            row = cur.fetchone()
            if row:
                user_id = str(row[0])
            else:
                # user_id is uniqueidentifier; generate with NEWID()
                cur.execute(
                    """
                    INSERT INTO dbo.Users (user_id, name, email, phone_e164, tz, created_at)
                    OUTPUT inserted.user_id
                    VALUES (NEWID(), %s, %s, %s, %s, SYSUTCDATETIME())
                    """,
                    (name, email, phone, tz)
                )
                user_id = str(cur.fetchone()[0])
                cxn.commit()

        return func.HttpResponse(
            json.dumps({"user_id": user_id}),
            mimetype="application/json",
            status_code=201
        )
    except Exception as ex:
        logging.exception("users endpoint failed")
        return func.HttpResponse(f"Server error: {ex}", status_code=500)