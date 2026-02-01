# Cron Scripts for Asset Management

## Scripts

### 1. `initial_backfill.py` - Run ONCE on new server

Populates all historical data from the start date.

```bash
# Default: from 2025-12-11
python cron/initial_backfill.py

# Custom start date
python cron/initial_backfill.py --start-date 2025-12-11
```

### 2. `daily_sync.py` - Run daily at market close

Syncs today's data. Safe to run multiple times (idempotent).

```bash
# Sync today's data
python cron/daily_sync.py

# Sync specific date (for manual recovery)
python cron/daily_sync.py --date 2026-01-30
```

---

## Crontab Setup

### Option 1: Using crontab (Linux/Mac)

```bash
# Edit crontab
crontab -e

# Add this line (runs at 15:35 KST = 06:35 UTC)
35 6 * * 1-5 cd /path/to/asset && /path/to/venv/bin/python cron/daily_sync.py >> /var/log/asset_sync.log 2>&1
```

### Option 2: Using systemd timer (Linux)

Create `/etc/systemd/system/asset-sync.service`:
```ini
[Unit]
Description=Asset Management Daily Sync

[Service]
Type=oneshot
WorkingDirectory=/path/to/asset
ExecStart=/path/to/venv/bin/python cron/daily_sync.py
User=your_username

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/asset-sync.timer`:
```ini
[Unit]
Description=Run Asset Sync at 15:35 KST

[Timer]
OnCalendar=Mon-Fri 15:35
Persistent=true

[Install]
WantedBy=timers.target
```

Enable timer:
```bash
sudo systemctl enable asset-sync.timer
sudo systemctl start asset-sync.timer
```

---

## Server Setup Steps

1. **Clone repository**
   ```bash
   git clone <repo> /path/to/asset
   cd /path/to/asset
   ```

2. **Create virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

4. **Run initial backfill**
   ```bash
   python cron/initial_backfill.py
   ```

5. **Set up cron**
   ```bash
   crontab -e
   # Add the cron line above
   ```

---

## Idempotency

All sync operations are idempotent (safe to run multiple times):

| Function | Method | Notes |
|----------|--------|-------|
| `sync_trade_history` | INSERT IGNORE | Skips existing orders |
| `sync_holdings` | DELETE + INSERT by date | Replaces today's data |
| `sync_account_summary` | DELETE + INSERT by date | Replaces today's data |
| `sync_daily_snapshot` | DELETE + INSERT by date | Replaces today's data |
| `sync_market_index` | UPSERT | Updates existing records |
| `construct_daily_lots` | UPSERT | Updates existing lots |
| `create_portfolio_snapshot` | DELETE + INSERT by date | Replaces today's data |

Running cron manually + automatic cron = **no data loss or duplication**.
