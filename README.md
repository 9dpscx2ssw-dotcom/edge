# Oracle runtime data payload — 2026-07-24

Payload requested for branch `oracle-runtime-data`.

Included:

- `audit_archive/oracle_32_strategy_deep_audit_20260724.tar`
- `runtime_data/active-postdelegation.db`
- `runtime_data/historical-2026-07-23.backup.db`
- runtime integrity manifests and DB inventory under `runtime_data/manifests/`

Excluded:

- source tree
- generated report directories outside the tar archive
- legacy audit scratch files
- Python cache files

Evidence boundary: internal Oracle runtime ledger data only; not broker-reconciled.
