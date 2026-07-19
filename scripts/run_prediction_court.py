from pathlib import Path

from eagle_eye.prediction_court import run_prediction_court

root = Path(__file__).resolve().parents[1]
receipt = run_prediction_court(root / "artifacts" / "prediction-court" / "latest")

print(f"COURT_SPEC={receipt['spec']}")
print(f"DEVELOPMENT_SHA256={receipt['development_sha256']}")
print(f"HOLDOUT_SHA256={receipt['holdout_sha256']}")
print(f"REGISTRY_MANIFEST_SHA256={receipt['registry_manifest_sha256']}")
print(f"CONTAMINATION_DETECTED={str(receipt['contamination']['contamination_detected']).lower()}")
print(f"LEAKAGE_DEFENDED={str(receipt['leakage']['all_defended']).lower()}")
for decision in receipt["decisions"]:
    print(f"DECISION {decision['candidate']}={decision['status']}"
          + (f" reasons={','.join(decision['reasons'])}" if decision["reasons"] else ""))
print(f"BENEFICIAL_CANDIDATE_PROMOTED={str(receipt['proofs']['beneficial_candidate_promoted']).lower()}")
print(f"ATTRACTIVE_REGRESSION_REJECTED={str(receipt['proofs']['attractive_regression_rejected']).lower()}")
print(f"PREDICTION_COURT_RECEIPT_ID={receipt['court_receipt_id']}")
if receipt["contamination"]["contamination_detected"] or not all(receipt["proofs"].values()):
    raise SystemExit(1)
