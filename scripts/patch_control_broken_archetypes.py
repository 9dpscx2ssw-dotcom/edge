#!/usr/bin/env python3
"""Set the chronically-losing "broken-archetype" strategies off in control.json.

Idempotent MERGE patch (stdlib only, no gungnir import needed): reads the
existing control file on the box, changes only the named strategy modes, and
writes it back atomically. Every other field — paused / kill / consensus_mode /
risk_settings / runtime / instruments / any filter override and every other
strategy — is preserved untouched. Safe to re-run and safe to drop onto a box
whose control.json has drifted since this repo was last synced.

Why these five: they are the level-state losers the 23-24 Jul runtime
counterfactual isolated — very low win rate plus high near-stop% (price runs to
the stop before it works = late entry), and still net-negative after the
deterministic entry gates (timeframe / separation / re-entry cooldown). Turning
them OFF removes them from the consensus vote as well as their own shadow book,
so they stop contaminating the aggregated decision.

    strategy         win%     pnl   near-stop%
    multi_bb          15    -64.9      75
    mean_reversion    25    -45.7      86
    fvg_m15            7    -46.0       -
    fvg_m30           20    -32.2       -
    cci_reversal      29    -31.2       -

Trade-off (read before running): OFF stops these strategies generating forward
attribution data, so you can no longer measure whether a future fresh-event /
thesis-confirmation entry fix would rescue them. If you want to keep collecting
that data while removing them from the real account, use `--mode shadow`
instead (they still paper-trade and still vote in consensus) or `--revert` to
drop the entries entirely and fall back to their strategies.yaml mode.

Usage:
    python3 scripts/patch_control_broken_archetypes.py                 # set off
    python3 scripts/patch_control_broken_archetypes.py --mode shadow   # keep data
    python3 scripts/patch_control_broken_archetypes.py --revert        # undo
    python3 scripts/patch_control_broken_archetypes.py --dry-run       # preview
    python3 scripts/patch_control_broken_archetypes.py /path/control.json
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BROKEN_ARCHETYPES = ("multi_bb", "mean_reversion", "fvg_m15", "fvg_m30", "cci_reversal")

# Same shape Control.read() falls back to, so a missing/corrupt file still
# produces a valid, complete control document.
_DEFAULTS: dict = {
    "strategies": {}, "instruments": {}, "paused": False, "kill": False,
    "risk_settings": {}, "runtime": {}, "consensus_mode": "shadow",
}


def _read(path: Path) -> dict:
    data = dict(_DEFAULTS)
    if path.exists():
        try:
            data.update(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError) as e:
            print(f"warning: could not parse {path} ({e}); starting from defaults",
                  file=sys.stderr)
    for k, v in _DEFAULTS.items():
        data.setdefault(k, v.copy() if isinstance(v, dict) else v)
    return data


def _write_atomic(path: Path, data: dict) -> None:
    data = {**data, "updated_at": datetime.now(timezone.utc).isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp") as tmp:
        json.dump(data, tmp)
        tmp_path = tmp.name
    Path(tmp_path).replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default="data/control.json",
                    help="control.json location (default: data/control.json)")
    ap.add_argument("--mode", choices=("off", "shadow", "live"), default="off",
                    help="target mode for the broken archetypes (default: off)")
    ap.add_argument("--revert", action="store_true",
                    help="remove these strategies' control entries entirely")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the changes without writing")
    args = ap.parse_args(argv)

    path = Path(args.path)
    data = _read(path)
    strategies = data["strategies"]

    changes: list[str] = []
    for name in BROKEN_ARCHETYPES:
        before = strategies.get(name, "(unset→strategies.yaml)")
        if args.revert:
            if name in strategies:
                del strategies[name]
                changes.append(f"  {name}: {before} -> (removed)")
        else:
            if before != args.mode:
                strategies[name] = args.mode
                changes.append(f"  {name}: {before} -> {args.mode}")

    if not changes:
        print(f"No change needed — {path} already in the requested state.")
        return 0

    print(f"{'Would apply' if args.dry_run else 'Applied'} to {path}:")
    print("\n".join(changes))
    if not args.dry_run:
        _write_atomic(path, data)
        print("Written atomically. The agent picks it up at the top of its next fast loop "
              "(no restart needed — control.json hot-applies).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
