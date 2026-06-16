# Lead Finder Stage D Runbook

## Purpose

This runbook covers the daily operating and recovery steps for the local Lead Finder system.

It focuses on:

- budget stops
- retry behavior
- safe reruns
- backup and restore
- local workbench and CRM troubleshooting

---

## 1. Current Stability Behavior

### Budget guards

Lead Finder now supports soft limits for:

- `Serper`
- `Apollo.io`
- `Hunter.io`

Environment variables:

```powershell
LEADFINDER_SERPER_RUN_LIMIT=10
LEADFINDER_SERPER_DAILY_LIMIT=50
LEADFINDER_APOLLO_RUN_LIMIT=10
LEADFINDER_APOLLO_DAILY_LIMIT=50
LEADFINDER_HUNTER_RUN_LIMIT=10
LEADFINDER_HUNTER_DAILY_LIMIT=50
```

Rules:

- `0` means disabled
- run limit stops the current run only
- daily limit stops further calls for the current local day
- budget stop messages appear in the workbench summary card

### Retry policy

Automatic retry is intentionally narrow.

Retried once:

- `UN Comtrade`
- local CRM HTTP requests
- public website crawl fetches

Not aggressively retried:

- `Serper`
- `Apollo.io`
- `Hunter.io`

Reason:

- those providers may consume paid quota or credits
- repeated paid calls should be a deliberate operator decision

Task-level behavior:

- completed paid tasks are deduped and skipped by default
- failed or interrupted paid tasks are not rerun automatically
- rerun requires an explicit retry marker

### Safe rerun principle

If a run stops because of:

- local CRM temporary error
- Comtrade temporary network error
- public website timeout

then rerun is normally safe.

If a run stops because of:

- Hunter quota
- Apollo quota
- Serper quota

then fix the budget or wait for the next day before rerunning.

---

## 2. Daily Operator Checklist

1. Start the workbench:

```powershell
python cli.py serve
```

Or start the managed background process:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\leadfinder-workbench.ps1 -Action start
```

2. Open:

- Lead Finder: `http://127.0.0.1:8765`
- CRM: `http://127.0.0.1:5173`

3. Check the top usage row:

- latest run usage
- daily usage
- whether budget limits are near exhaustion

4. Run small campaign batches first:

```powershell
python cli.py campaign --market-limit 1 --per-market-limit 3
```

5. Only after review:

- batch requalify
- enrich qualified emails
- verify qualified emails
- sync CRM
- pull CRM feedback

---

## 3. Backup

### Create backup

Recommended: back up to a directory outside the repo.

Database only:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\backup-leadfinder.ps1 -DestinationRoot C:\tmp
```

Database + exports:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\backup-leadfinder.ps1 -DestinationRoot C:\tmp -IncludeExports
```

Database + exports + env:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\backup-leadfinder.ps1 -DestinationRoot C:\tmp -IncludeExports -IncludeEnv
```

Notes:

- `.env` backup is optional because it contains secrets
- repo-local `backups/` is git-ignored if you choose to use it

### What is backed up

Always:

- `data/leadfinder.sqlite`

Optional:

- `exports/`
- `.env` copied as `.env.backup`

Each backup also writes a `manifest.json`.

---

## 4. Restore

### Restore database only

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\restore-leadfinder.ps1 -BackupPath C:\tmp\leadfinder-backup-YYYYMMDD-HHMMSS
```

### Restore database + exports

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\restore-leadfinder.ps1 -BackupPath C:\tmp\leadfinder-backup-YYYYMMDD-HHMMSS -RestoreExports
```

### Restore database + exports + env

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\restore-leadfinder.ps1 -BackupPath C:\tmp\leadfinder-backup-YYYYMMDD-HHMMSS -RestoreExports -RestoreEnv
```

Restore notes:

- the restore script replaces `data/leadfinder.sqlite`
- when `-RestoreExports` is used, the current `exports/` directory is replaced
- restore `.env` only when you trust the backup source

---

## 5. Common Failures

### 8765 refuses connection

Check whether the server is running:

```powershell
python cli.py serve
```

If the port is occupied, stop the old process and restart.

Preferred managed commands:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\leadfinder-workbench.ps1 -Action status
powershell -ExecutionPolicy Bypass -File .\tools\leadfinder-workbench.ps1 -Action restart
```

Managed runtime files:

- `runtime/leadfinder-8765.pid`
- `runtime/leadfinder-8765.out.log`
- `runtime/leadfinder-8765.err.log`

### CRM not connected

Check:

- CRM is running on `http://127.0.0.1:5173`
- `.env` has the correct `LEADFINDER_CRM_URL`

Expected behavior:

- sync and feedback actions remain disabled or return readable local error messages

### Budget stop triggered

Symptoms:

- summary card says provider budget reached
- latest run usage stops increasing for that provider

Actions:

1. inspect `.env` limits
2. decide whether to raise the limit
3. or wait until the next local day for daily budget reset

Do not keep rerunning the same workflow blindly.

### SSL certificate failures during crawl

Expected behavior:

- SSL verification stays enabled
- failures are recorded
- crawl may become partial or fail

Do not disable certificate verification.

### Hunter or Apollo produced partial work

If budget stops after partial progress:

- do not assume the remaining candidates were processed
- review the lead table and notes
- rerun only after the budget condition is cleared

### Paid task retry marker

Inspect failed tasks:

```powershell
python cli.py provider-task-report --provider Serper --status error
python cli.py provider-task-report --provider Hunter.io --status error --lead-id 12
```

Mark tasks so they can run again:

```powershell
python cli.py mark-provider-retry --provider Serper --task-type search --limit 20 --reason "quota reset"
python cli.py mark-provider-retry --provider Hunter.io --task-type domain_search --lead-id 12 --reason "site back online"
python cli.py mark-provider-retry --provider Hunter.io --task-type verify_email --lead-id 12 --reason "email corrected"
python cli.py mark-provider-retry --provider Apollo.io --task-type contact --lead-id 12 --reason "manual approval"
```

Rule:

- do not mark everything blindly
- inspect the previous failure first
- only mark the tasks you intentionally want to pay for again
- record a short retry reason so later operators know why the rerun was approved

---

## 6. Safe Rerun Rules

### Safe to rerun immediately

- Comtrade transient error
- local CRM transient error
- public crawl timeout
- workbench process restart

### Rerun with caution

- Hunter enrich
- Hunter verify
- Apollo contact search
- Serper discovery

Before rerun:

1. confirm budget is available
2. confirm previous partial results were persisted
3. confirm you are not replaying the same paid call without reason

---

## 7. Key Rotation Reminder

API keys have appeared in conversation before. Treat them as exposed and rotate them.

After rotation:

1. update `.env`
2. restart the workbench
3. verify provider availability on the workbench

---

## 8. CI

GitHub Actions now runs:

```powershell
python -m unittest discover -s tests -p test_*.py
```

Workflow file:

- `.github/workflows/python-tests.yml`

If CI fails:

1. reproduce locally with the same command
2. fix the test or regression
3. rerun locally before pushing again
