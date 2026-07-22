"""Regression guard: dashboard and agent must share the configured journal."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
config = (ROOT / "config" / "config.yaml").read_text()
compose = (ROOT / "docker-compose.yml").read_text()
configured = re.search(r"^\s*db_path:\s*([^\s#]+)", config, re.M)
assert configured, "persistence.db_path missing from config"
expected = "/app/" + configured.group(1).lstrip("./")
assert f"GUNGNIR_DB_PATH: {expected}" in compose, (
    "dashboard journal must match persistence.db_path; "
    f"expected GUNGNIR_DB_PATH: {expected}"
)
print("PASS", expected)
