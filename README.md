# Oracle runtime data payload

This branch contains only:

1. `audit_archive/oracle_32_strategy_deep_audit_20260724.tar`
2. `data/` — the captured contents of the currently running Oracle container writable runtime directory `/app/data` from Docker volume `oracle_oracle-data`
3. `ORACLE_RUNTIME_SOURCE.txt`, `FILE_SIZES.txt`, and `SHA256SUMS.txt` for provenance/verification

No Oracle source tree is included.

At capture time `/app/data/config.json` was absent. The container's mounted config file existed at `/app/config/config.yaml`, outside `/app/data`, so it is not included here.
