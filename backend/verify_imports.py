"""Quick verification that all new modules import correctly."""
import sys
errors = []

try:
    from services.export_service import ExportService
    print("✓ services.export_service")
except Exception as e:
    errors.append(f"✗ services.export_service: {e}")

try:
    from routers.export import router
    print(f"✓ routers.export (prefix={router.prefix})")
except Exception as e:
    errors.append(f"✗ routers.export: {e}")

try:
    from agents.requirement_parser import RequirementParserAgent
    print("✓ agents.requirement_parser")
except Exception as e:
    errors.append(f"✗ agents.requirement_parser: {e}")

try:
    from agents.scope_auditor import ScopeAuditorAgent
    print("✓ agents.scope_auditor")
except Exception as e:
    errors.append(f"✗ agents.scope_auditor: {e}")

try:
    from agents.bloom_auditor import BloomAuditorAgent
    print("✓ agents.bloom_auditor")
except Exception as e:
    errors.append(f"✗ agents.bloom_auditor: {e}")

try:
    from agents.guidance_agent import GuidanceAgent
    print("✓ agents.guidance_agent")
except Exception as e:
    errors.append(f"✗ agents.guidance_agent: {e}")

try:
    from models.student import StudentSubmission, MasteryProfile
    print("✓ models.student")
except Exception as e:
    errors.append(f"✗ models.student: {e}")

try:
    from services.guidance_service import GuidanceService
    print("✓ services.guidance_service")
except Exception as e:
    errors.append(f"✗ services.guidance_service: {e}")

try:
    from routers.guidance import router as guidance_router
    print("✓ routers.guidance")
except Exception as e:
    errors.append(f"✗ routers.guidance: {e}")

try:
    from agents.state import AgentState
    assert "scope_audit_results" in AgentState.__annotations__
    assert "bloom_audit_results" in AgentState.__annotations__
    print("✓ agents.state (audit fields present)")
except Exception as e:
    errors.append(f"✗ agents.state: {e}")

print()
if errors:
    print(f"FAILED: {len(errors)} import error(s)")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print("ALL IMPORTS VERIFIED SUCCESSFULLY")
