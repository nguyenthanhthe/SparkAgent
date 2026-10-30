# Runbook: backup drills

Backups only count if they restore. This runbook is the periodic drill —
create, tag, verify the whole retention window, restore into a scratch
dir, and what to do differently on the day you restore for real.

## The drill (monthly)

```bash
# 1. create a tagged backup (vault secrets excluded by default)
python -m ops.backup create --data-dir data --skills-dir skills \
    --output-dir backups --tag drill-$(date +%Y%m%d)

# 2. verify every archive in the retention window
python -m ops.backup verify-all --output-dir backups

# 3. restore the newest archive into a scratch dir — never data/
python -m ops.backup drill backups/sparkagent-backup-<stamp>.zip
```

Expected output: `create` prints the archive path and digest; `verify-all`
prints `{"ok": true, ...}`; `drill` prints `{"ok": true, "files": N}` and
leaves no scratch dir behind. Any `ok: false` — stop, investigate before
the next backup overwrites the evidence.

## Reading the signals

| Signal | Meaning | Action |
|---|---|---|
| `verify-all` flags one archive | corruption or tampering in that file | `drill` a different archive; delete the bad one; check disk health |
| `hash mismatch ... backup corrupted` | bytes changed after creation | suspect storage failure; restore from an older archive |
| `manifest digest mismatch — tampered backup` | file list edited after creation | treat as compromise; check quarantine/audit before restoring |
| `no backups found` | wrong `--output-dir` or pruning wiped the window | fix the path; check the retention `--keep` value |
| backup panel age on the dashboard grows | the scheduled create stopped running | check the cron/systemd timer and its exit code |

## Restore for real (incident day)

1. Stop the daemon first: `sudo systemctl stop sparkagent` (or Ctrl-C) —
   restoring into a live data dir races the writer.
2. `python -m ops.backup restore backups/<archive>.zip --data-dir data
   --overwrite` — hashes are verified before a single byte is written.
3. Restart, then `GET /api/health` and the dashboard backup panel — the
   newest archive age should reset on the next scheduled create.
4. Audit what caused the restore (`GET /api/audit?limit=50`); if the
   cause was a bad skill or a runaway tool, quarantine it before it
   corrupts the next backup too.

## Notes

- `vault.bin` is excluded by design — a backup without the master key
  cannot restore API keys. Keep the vault separately (password manager,
  encrypted USB); test *that* restore path too, not just the data.
- Tags ride in the manifest: `verify` and `verify-all` output show them,
  and the dashboard backup panel lists the newest archive's tag.
- A backup you have never restored is a hope, not a backup.
- The dashboard backup panel and telegram `/backup` hash-verify the
  newest archive on every view; `unverified` means that check failed.
  See the FAQ entry [why does my backup show unverified?](faq.md) for
  what that means and what to do next.
