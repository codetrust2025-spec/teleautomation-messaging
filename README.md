# teleautomation-messaging

Independent TeleAutomation Marketing service. Its public hostname is supplied at deployment time.

## Local run

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\uvicorn main:app --reload
cd dashboard; npm ci; npm run dev
```

Runtime data and secrets are intentionally excluded. See `docs/migration/` for frozen contracts and cutover plans.
