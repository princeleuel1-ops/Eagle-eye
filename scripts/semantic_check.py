from pathlib import Path
from eagle_eye.semantics import inspect_frontend_contract

root = Path(__file__).resolve().parents[1]
result = inspect_frontend_contract(root / "web")
for key, value in result.items(): print(f"{key.upper()}={str(value).lower()}")
if not all(result.values()): raise SystemExit(1)
print("DIGITAL_TWIN_SEMANTIC_PASS")
