# Compatibility And Legacy Zones

## Active Zone

- Canonical runtime package: [backend/app](e:/Đồ án/Project/backend/app)
- New code should import from `app.*`
- All audit, tests, and future refactors should treat `app/*` as the source of truth

## Compatibility Zone

These paths still exist so older imports do not break:

- `backend/main.py`
- `backend/config.py`
- `backend/database.py`
- `backend/core/*`
- `backend/models/*`
- `backend/repositories/*`
- `backend/routers/*`
- `backend/schemas/*`
- `backend/services/*`
- `backend/agents/*`
- `backend/utils/*`

Rule:

- keep them as thin forwarding shims only
- do not add new business logic there
- when touching runtime code, move the real change into `backend/app/*`

## Legacy Zone

- [legacy](e:/Đồ án/Project/backend/legacy) remains off the critical path
- legacy routers are not mounted by [app/main.py](e:/Đồ án/Project/backend/app/main.py)
- code in `legacy/*` can inform migration work, but it should not be reintroduced into the active flow without a deliberate design pass

## Persistence Compatibility

The runtime is document-first, but the database still carries legacy naming in places:

- `textbooks` acts as the persisted document table
- `textbook_chunks` still stores document chunk records

This is why [document.py](e:/Đồ án/Project/backend/app/models/document.py) exists as a document-first alias layer over the older table names. Keep the naming mismatch documented until a deliberate migration removes it.
