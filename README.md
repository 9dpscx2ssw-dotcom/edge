# Oracle runtime data payload — corrected 2026-07-24

This branch contains the requested Oracle runtime data from the **currently running** `oracle` container's `/app/data` directory, plus the deep-audit archive.

Authoritative live container evidence at capture time:

- Compose project: `oracle`
- Compose workdir: `/mnt/store/oracle`
- Runtime data mount: Docker volume `oracle_oracle-data` mounted at `/app/data`
- Config bind mount: `/mnt/store/oracle/config` mounted at `/app/config`

## Included

- `audit_archive/oracle_32_strategy_deep_audit_20260724.tar`
- `runtime_data/oracle_data/` — exact captured contents of running container `/app/data`
- `runtime_data/archive/oracle_current_runtime_data_20260724T1113Z.tar.gz` — tarball of the same current runtime-data capture
- `runtime_data/oracle_runtime_metadata.txt` — container label/mount/file manifest captured from live runtime
- `runtime_data/config_presence.txt` — config file presence check

## Config note

At capture time `/app/data/config.json` was **absent** in the running Oracle container. The running mounted config file present was `/app/config/config.yaml`; `/app/data/strategies.yaml` was present and included.

## Evidence boundary

This is runtime state from the running Oracle container, not broker-reconciled performance evidence.
