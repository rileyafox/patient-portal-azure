# Patient Shift Portal (Azure SWA + Python Functions)

Microsoft-inspired Fluent UI front end with Azure Functions backend, Azure SQL storage, Service Bus scheduled reminders, and Azure Communication Services (SMS + Email).

## Prereqs
- Node 18+ (for frontend)
- Python 3.11 + Azure Functions Core Tools v4
- Azure CLI (`az`)
- For SQL locally, you'll need the ODBC Driver 18 and `pyodbc` build deps; in Azure, the Function runtime has it.
- An Azure subscription

## Run Frontend (locally)
```bash
cd frontend
npm i
npm run dev
```

## Run API (locally)
1. Edit `api/local.settings.json` with your connection strings (or leave Storage emulator for dev).
2. Install Python deps and start Functions:
```bash
cd api
python -m venv .venv && source .venv/bin/activate  # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
func start
```

Endpoints:
- `POST http://localhost:7071/api/users`
- `POST http://localhost:7071/api/shifts`
- `GET  http://localhost:7071/api/shifts?user_id=...`

## One-shot Azure setup (quickstart)
```bash
cd infra
./deploy.sh
# Run the printed steps to publish Functions and run SQL DDL.
```

## Deploy Functions
```bash
cd api
func azure functionapp publish <YOUR_FUNCTION_APP_NAME>
```

## Deploy Frontend to Azure Static Web Apps
The best way is to push this project to GitHub and use SWA GitHub Action:
- In Azure Portal: Static Web Apps → Create → connect your repo
- App location: `frontend`
- Build command: `npm run build`
- Output location: `dist`
- Api location: `api` (optional; can also be a separate Function App you've deployed above)

For local test against Azure-hosted API, set `VITE_API_BASE` or use the `/api/*` proxy in `staticwebapp.config.json`.

## Configure Auth (optional now, recommended later)
- SWA provides `/.auth/me` when you turn on login (AAD or B2C). The UI auto-prefills email/name if present.
- For patients, prefer **Azure AD B2C** (email/password + social providers).
- For staff-only, standard **AAD** is fine.

## Azure Communication Services
- Purchase a phone number in ACS (SMS) and assign to `FROM_PHONE`.
- Verify a sending domain (Email) and set `FROM_EMAIL`.
- Update Function App settings accordingly.

## Timezones and Scheduling
- Frontend sends local wall time + IANA tz.
- Backend stores both local and UTC, schedules **Service Bus** messages at UTC T-24h and T-2h.

## Next Steps
- Add reschedule/cancel endpoints (delete and re-schedule SB messages, or track a cancel flag).
- Switch SQL to AAD Managed Identity (no passwords).
- Add inbound SMS webhook (Event Grid → Function) to record acknowledgments.
