# Services

Supporting services that run alongside the agent stack.

## dispatch_arbitrator.py

Manages the QR-code technician dispatch flow.

**Subscribes to:**
- `factory/line-A/dispatch/qr-shown` — presenter clicked Show QR (new round)
- `factory/line-A/dispatch/availability` — phone tapped "I'm Available"
- `factory/line-A/+/workorder/created` — agent created a work order (trigger assignment)
- `factory/line-A/control/demo/reset` — hard reset, clear pool

**Publishes to:**
- `factory/line-A/dispatch/assignment` — winner selected
- `factory/line-A/dispatch/pool-update` — pool size updated (live counter)

**Pool logic:**
- First-in-pool wins
- Each phone gets a tech_id (random, browser-generated)
- Duplicates deduplicated by tech_id
- Round bounded by round_id (incremented each Show QR click)
- Stale availability events (wrong round_id) are ignored

## Running

The arbitrator uses the same `.env` file as the agent (`../agent/.env`).
Make sure your venv is set up at `../agent/.venv`.

```bash
cd services
./run_arbitrator.sh
```

Or manually:

```bash
cd services
source ../agent/.venv/bin/activate
python dispatch_arbitrator.py
```

## Dependencies

```bash
pip install -r requirements.txt
```

(`paho-mqtt` and `python-dotenv` — already installed if you've set up the agent venv.)
