import json
from pathlib import Path
import sys

from eagle_eye.evidence import verify_evidence_room

archive = Path(sys.argv[1])
trust_registry = Path(sys.argv[2]) if len(sys.argv) > 2 else None
expected_tenant = sys.argv[3] if len(sys.argv) > 3 else None
result = verify_evidence_room(
    archive,
    trust_registry=trust_registry,
    expected_tenant=expected_tenant,
)
print(json.dumps(result, sort_keys=True))
print(f"HASHES_VERIFIED={str(result.get('hashes_verified', False)).lower()}")
print(f"SIGNATURE_VERIFIED={str(result.get('signature_verified', False)).lower()}")
print(f"SIGNER_TRUSTED={str(result.get('signer_trusted', False)).lower()}")
print(f"TENANT_VERIFIED={str(result['tenant_verified']).lower()}")
print(f"AUDIT_VERIFIED={str(result['audit_verified']).lower()}")
print(f"IDENTITY_VERIFIED={str(result['identity_verified']).lower()}")
print(f"POLICY_VERIFIED={str(result['policy_verified']).lower()}")
print(f"POLICY_BUNDLE_VERIFIED={str(result['policy_bundle_verified']).lower()}")
print(f"POSTERIOR_VERIFIED={str(result.get('posterior_verified')).lower()}")
print(f"EVIDENCE_ROOM_VERIFIED={str(result['verified']).lower()}")
raise SystemExit(0 if result.get("verified") else 1)
