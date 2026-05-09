# Section-Aware Blueprint Slots — Final Plan (v3)

## Rules
- **No extra LLM calls** — all assignment, fill-missing, validation in code
- **`scope_units` is source of truth**
- **`_normalize_section_fields` called after EVERY path that mutates blueprint slots**
- **`section_id=None` is NOT a valid lookup key** — use `scope_unit_key` instead
- **Every scope_unit gets a stable `scope_unit_key`** regardless of whether it has a canonical `section_id`

---

## Key Concept: `scope_unit_key`

Every unit in `scope_units` is assigned a stable synthetic key used by both the prompt and normalization:

```python
def _make_scope_unit_key(unit: dict) -> str:
    if unit.get("section_id"):
        return unit["section_id"]          # canonical: "ch2_sec1"
    elif unit.get("section_title"):
        # synthetic for textbook (title-based, normalized)
        ch = _norm(unit.get("chapter_title", ""))
        sec = _norm(unit.get("section_title", ""))
        return f"{ch}>{sec}"               # e.g. "dien hoc>dien truong"
    else:
        return _norm(unit.get("chapter_title", "unknown"))  # chapter-level fallback
```

This key is stored on each unit: `unit["scope_unit_key"] = _make_scope_unit_key(unit)`.

**Collision prevention**: if multiple units produce the same base key (same chapter + section title in same chapter), append `#n` index:
```python
seen_keys: dict[str, int] = {}
for unit in scope_units:
    base = _make_scope_unit_key_base(unit)
    n = seen_keys.get(base, 0)
    unit["scope_unit_key"] = base if n == 0 else f"{base}#{n}"
    seen_keys[base] = n + 1
```

The LLM is told to output `primary_scope_unit_key` / `secondary_scope_unit_keys` (alongside `primary_section_id` where available).

---

## 1. `generate.py` — `_resolve_scope_section_ids` returns `scope_units`

### [MODIFY] [generate.py](file:///e:/Đồ%20án/Project/backend/app/routers/generate.py)

**Remove early return guard** for plain-chapter scope entries:
```python
# Remove: if not has_sections: return scope_sections, scope_section_ids
# Always build scope_units for all scope entries
```

**New return signature**:
```python
async def _resolve_scope_section_ids(scope, document_id, db) \
    -> tuple[list[str], list[str], list[dict]]:
    # Returns: (scope_sections, scope_section_ids, scope_units)
```

**scope_units building**:

| Entry type | heading_tree | `section_id` | `section_title` | `scope_unit_key` |
|---|---|---|---|---|
| `"Ch > Sec"` | has canonical id | `"ch2_sec1"` | `"Điện trường"` | `"ch2_sec1"` |
| `"Ch > Sec"` | textbook / no id | `None` | `"Điện trường"` | `"dien hoc>dien truong"` |
| `"Chapter"` plain | has sections | one unit per section | varies | per-section key |
| `"Chapter"` plain | no sections | `None` | `None` | `norm(chapter_title)` |

Each unit shape:
```python
{
    "chapter_id": "ch2",           # None for textbook
    "chapter_title": "Điện học",
    "section_id": "ch2_sec1",      # None if textbook/unavailable
    "section_title": "Điện trường", # None if chapter-level
    "scope_unit_key": "ch2_sec1",  # always set, never None
}
```

**Update all 3 callers** (unpack 3-tuple):
- `_run_generation_inline`
- `generate_exam_fe`
- `exams.py`

Add `scope_units` into `exam_config`.

---

## 2. `outline.py`

### [MODIFY] [outline.py](file:///e:/Đồ%20án/Project/backend/app/agents/outline.py)

### A. `_build_outline_prompt()` — include ALL scope_units via `scope_unit_key`

Emit ONLY units with `section_title` in the section list (chapter-level units with `section_title=None` are excluded — they are not valid section targets for the LLM). If ALL scope_units are chapter-level (no section_title), omit section constraints entirely:
```
Danh sách mục có thể thi:
- ch2_sec1              | Điện học > Điện trường         [section_id available]
- dien hoc>dien truong  | Điện học > Điện trường         [textbook, key only]
- ch2_sec2              | Điện học > Định lý Gauss
```

Prompt instructs LLM to output:
```json
{
  "primary_scope_unit_key": "ch2_sec1",
  "primary_section_id": "ch2_sec1",        // if available, same as key
  "primary_section_title": "Điện trường",  // copy from unit
  "secondary_scope_unit_keys": [],
  "secondary_section_ids": [],
  "secondary_section_titles": []
}
```

For textbook units where `section_id=None`, LLM outputs `primary_scope_unit_key = "dien hoc>dien truong"` and `primary_section_id = null`.

Bloom-level rules (same as before):
- NB/TH → secondary empty
- VD → max 1 secondary
- VDC → max 2 secondary

### B. `_normalize_section_fields(blueprint, scope_units)` — deterministic, no LLM

**Lookups**:
```python
key_lookup: dict[str, dict] = {u["scope_unit_key"]: u for u in scope_units}
# Also index by section_id for direct lookup
sec_id_lookup: dict[str, dict] = {u["section_id"]: u for u in scope_units if u.get("section_id")}
# Per-chapter units (with real section key)
ch_id_units: dict[str, list[dict]] = {}   # chapter_id → [units]
ch_title_units: dict[str, list[dict]] = {} # norm(chapter_title) → [units]
for u in scope_units:
    if u.get("scope_unit_key") != _norm(u.get("chapter_title", "")):  # has section
        if u.get("chapter_id"):
            ch_id_units.setdefault(u["chapter_id"], []).append(u)
        ch_title_units.setdefault(_norm(u["chapter_title"]), []).append(u)
```

**Slot resolution** (prefer section_id, fall back to scope_unit_key):
```python
def _resolve_unit(slot):
    # 1. Try primary_section_id in sec_id_lookup
    sid = slot.get("primary_section_id")
    if sid and sid in sec_id_lookup:
        return sec_id_lookup[sid]
    # 2. Try primary_scope_unit_key in key_lookup
    key = slot.get("primary_scope_unit_key")
    if key and key in key_lookup:
        return key_lookup[key]
    # 3. Assign deterministically by chapter
    ch_id = slot.get("chapter")  # chapter_id string
    units = ch_id_units.get(ch_id) or ch_title_units.get(_norm(ch_id), [])
    if units:
        return units[rr_counter[ch_id] % len(units)]  # round-robin
    return None
```

**Per-slot logic**:
1. Resolve unit via `_resolve_unit(slot)` → set `primary_section_id`, `primary_section_title`, `primary_scope_unit_key`
2. **Remove self-secondary**: filter out primary key from secondary keys:
   ```python
   secondary_keys = [k for k in raw_secondary_keys if k != resolved_primary_key]
   ```
3. Also accept `secondary_section_ids` → convert to keys via `sec_id_lookup`
4. Filter remaining secondary keys to those present in `key_lookup`
5. Cap by Bloom level (NB/TH=0, VD=1, VDC=2)
6. Rebuild `secondary_section_ids`, `secondary_section_titles` from final key list
7. **Set legacy field**: `slot["section"] = slot["primary_section_title"]` (backward compat for builder/UI)

**`_resolve_unit(slot)` implementation** (safe rr_counter):
```python
def _resolve_unit(slot, sec_id_lookup, key_lookup, ch_id_units, ch_title_units,
                  scope_units, rr_counter):
    # 1. Try primary_section_id
    sid = slot.get("primary_section_id")
    if sid and sid in sec_id_lookup:
        return sec_id_lookup[sid]
    # 2. Try primary_scope_unit_key
    key = slot.get("primary_scope_unit_key")
    if key and key in key_lookup:
        return key_lookup[key]
    # 3. Chapter-scoped round-robin
    ch_id = slot.get("chapter", "")
    units = ch_id_units.get(ch_id) or ch_title_units.get(_norm(ch_id), [])
    rr_key = ch_id or "__global__"
    if not units:
        # 4. Global fallback — round-robin all section units
        units = [u for u in scope_units if u.get("section_title")]
        rr_key = "__global__"
    if not units:
        return None
    idx = rr_counter.get(rr_key, 0)
    rr_counter[rr_key] = idx + 1
    return units[idx % len(units)]
```

**Called at 5 points**:
1. After LLM output parsed
2. After `_enforce_type_counts`
3. After `_enforce_chapter_coverage`
4. In fallback/retry/deterministic paths (after pad/redistribute)
5. Right before `return OutlineOutput`

### C. Fallback/enforce/pad paths

All `slot["section"] = ""` / `None` → assign from ch_id_units/ch_title_units round-robin. If no scope_units → keep existing behavior.

---

## 3. `builder.py` — Section_id + title fallback for both primary AND secondary

### [MODIFY] [builder.py](file:///e:/Đồ%20án/Project/backend/app/agents/builder.py)

```python
primary_sec_id    = slot.get("primary_section_id") or ""
primary_sec_title = slot.get("primary_section_title") or slot.get("section") or ""
secondary_sec_ids  = set(slot.get("secondary_section_ids") or [])
secondary_sec_keys = set(slot.get("secondary_scope_unit_keys") or [])
secondary_sec_titles = set(slot.get("secondary_section_titles") or [])

def _match_chunk_primary(c):
    if c.get("role") == "background": return False
    if primary_sec_id and c.get("section_id") == primary_sec_id: return True
    if primary_sec_title and _norm(c.get("section", "")) == _norm(primary_sec_title): return True
    return False

def _match_chunk_secondary(c):
    if c.get("role") == "background": return False
    sec_id = c.get("section_id", "")
    sec_title = _norm(c.get("section", ""))
    if sec_id and sec_id in secondary_sec_ids: return True
    if sec_title and (
        sec_title in {_norm(t) for t in secondary_sec_titles}
    ): return True
    return False

primary_chunks   = [c for c in retrieved_context if _match_chunk_primary(c)]
secondary_chunks = [c for c in retrieved_context if _match_chunk_secondary(c)]
topic_chunks = primary_chunks + secondary_chunks

if not topic_chunks:
    # existing chapter-level fallback (unchanged)
    ...

# Background prereq chunks injected separately (unchanged)
```

---

## 4. Frontend

### [MODIFY] [generation-live-viewer.tsx](file:///e:/Đồ%20án/Project/Frontend/components/generation-live-viewer.tsx)

```typescript
interface BlueprintSlot {
  // ... existing ...
  primary_scope_unit_key?: string
  primary_section_id?: string
  primary_section_title?: string
  secondary_scope_unit_keys?: string[]
  secondary_section_ids?: string[]
  secondary_section_titles?: string[]
}
```

Display: `primary_section_title || section || "—"` + secondary badge tags.

---

## Implementation Order
1. `generate.py` — scope_units + scope_unit_key
2. `outline.py` — `_normalize_section_fields` + prompt + 5-call points + fallback paths
3. `builder.py` — primary + secondary title fallback
4. `generation-live-viewer.tsx` — type + display

## Acceptance Criteria
- User selects 1 section → all slots have `primary_scope_unit_key` = that section's key
- Textbook `"Chapter > Section"` → `primary_section_title` shown in blueprint without `section_id`
- Full chapter → expanded to all heading_tree sections
- NB/TH slots: `secondary_section_ids = []`, VD max 1, VDC max 2
- No slot references section outside user-selected scope
- Builder matches secondary sections by title when `section_id` absent
- Section normalization runs after every mutating path
- Chapter-only generation unchanged
