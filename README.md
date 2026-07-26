# Oracle current runtime data

This branch contains only a point-in-time capture of the writable runtime data from the **running** `oracle` container.

- Capture UTC: `20260726T091320Z`
- Docker Compose project: `oracle`
- Docker volume: `oracle_oracle-data`
- Container source: `/app/data`
- Source code and `/app/config` are intentionally excluded.
- `data/` includes the captured runtime-volume tree, including its own runtime backup files where present. SQLite databases are published as deterministic `.db.gz` files because the raw current databases exceed GitHub's 100 MB blob limit; decompress them into the same paths with `gzip -dk data/gungnir.db.gz` (and equivalent backup paths). `ORIGINAL_RUNTIME_SHA256SUMS.txt` verifies decompressed runtime files. The volatile `data/gungnir.db-shm` is omitted: it changed during local read-only validation after capture; SQLite recreates it from the captured DB/WAL.

## Integrity and scope

- `MANIFEST.json` records capture scope, database integrity/counts, and limited secret-like scan results.
- `SHA256SUMS.txt` and `FILE_SIZES.txt` cover the files under `data/`.
- The limited scan found no text or binary-string secret-like patterns, but it does **not** certify SQLite, model, or opaque log payloads as non-sensitive.

This is operational data, not a broker-certified trading record and not source code.
