# Backend Repo Report (Vietnamese)

## 1) Backend hien tai da lam duoc nhung gi

Backend hien tai da duoc dinh hinh thanh mot MVP tap trung hep cho bai toan sinh de trac nghiem mon Vat ly, voi boundary ro rang va flow van hanh tu dau den cuoi.

### 1.1 Pham vi san pham dang hoat dong
- Mon hoc: Vat ly.
- Ngon ngu dau ra: tieng Viet.
- Dau vao tai lieu: PDF.
- Dinh dang de: trac nghiem 1 dap an (MCQ single-answer).
- Sinh de theo pham vi curriculum (chapter/lesson/topic), co rang buoc grounding theo nguon.

### 1.2 Pipeline runtime da co (end-to-end)
1. User upload PDF qua documents API, backend validate file type/size va quyen truy cap course.
2. He thong tao document record (status=processing), luu file vao storage va kiem tra duplicate theo file_hash.
3. DocumentProcessor parse PDF, clean noise, chunk theo semantic boundary, suy ra chapter/section tree.
4. Chunk duoc gan metadata truy vet (document_id, chapter, parent_heading, section_id) va index vao retrieval stack:
   - Vector search (Pinecone namespace theo document)
   - SQL chunk store cho BM25/fallback.
5. Curriculum tree + sections + learning objectives duoc persist, document chuyen sang status=processed.

6. User gui yeu cau generate exam (document_id/course_id + scope + so cau + rao buoc MVP).
7. Scope service resolve scope duoc chon thanh selected_section_ids hop le (hard boundary cho generation).
8. ExamSpecService chuan hoa request thanh ExamSpec (MCQ-only, vi-only, strict_scope=true).
9. BlueprintService lap Blueprint (cells/slots, bloom distribution, over-generate quota) truoc khi sinh.

10. ScopedRetrievalService retrieve context theo tung slot:
  - Hybrid merge vector + BM25
  - Filter lai theo section_id da duoc phep
  - Neu can thi dung deterministic/legacy fallback co kiem soat.
11. MCQGenerationService + LLM router sinh cau hoi tu chunk assignment, kem source evidence traceable.
12. MCQVerifierService verify theo nhieu lop: cau truc MCQ, scope check, answerability, duplicate, grounding.
13. ExamService chon tap cau hoi cuoi, persist exam_version + exam_questions + quality/grounding reports.
14. FeedbackEventService ghi event retrieval/verifier/review/playbook de phuc vu analytics va ACE foundation.

15. Review flow cho phep edit/lock/delete/regenerate mot phan, sau do re-verify va tao version moi.
16. Publish chi duoc phep khi version hien tai dat dieu kien (khong failed verifier, co evidence hop le).

### 1.3 Nang luc da duoc bo sung cho quality va hoc tu phan hoi
- Feedback event store co cau truc (theo exam/version/question/stage/source/category).
- Playbook store voi vong doi bullet (approved/candidate/archived/rejected) va retrieval mode theo feature flag (`off`, `shadow`, `limited`).
- Reflection candidate: rut mau loi/phan hoi thanh de xuat bullet co the promote vao playbook.
- Warmup export: xuat offline datasets gom exam/question/feedback/playbook seed de phuc vu giai doan ACE foundation.

### 1.4 Khuon kho bo test/eval da co
- Smoke checks cho MVP runtime.
- Quality/foundation checks cho cac giai doan.
- Script eval va error analysis offline.
- Script verify import cho active package va compatibility shims.

---

## 2) Kien truc backend (chi backend)

Backend hien tai duoc to chuc theo 3 vung: active runtime, compatibility zone, legacy zone.

### 2.1 Active runtime (source of truth): `backend/app`

#### a) API layer
- `app/api/routers/*`: dinh nghia HTTP endpoints (auth, courses, documents, generation, exams, playbook).
- `app/api/serializers/*`: chuan hoa response payload.

#### b) Core layer
- `app/core/config.py`: doc bien moi truong + settings runtime.
- `app/core/database.py`: ket noi DB + init session/base.
- `app/core/mvp.py`: rang buoc/normalization theo pham vi MVP.
- `app/core/runtime_models.py`: dataclass/model trung gian cho pipeline (spec, blueprint, retrieved context, generated question...).

#### c) Domain persistence layer
- `app/models/*`: SQLAlchemy models (course, curriculum, document/textbook alias, exam/version/question, playbook, user, token blacklist...).
- `app/repositories/*`: data access helpers (hien co document repository la chinh).

#### d) Contract layer
- `app/schemas/*`: Pydantic schemas cho request/response (auth, course, document, exam, playbook).

#### e) Service orchestration layer
- `app/services/documents/*`: upload + parse + chunk + curriculum persistence.
- `app/services/curriculum/*`: resolve scope sang section IDs hop le.
- `app/services/exam_planning/*`: tao exam spec + blueprint.
- `app/services/retrieval/*`: retrieval engine, scoped retrieval, rag setup, fallback embeddings.
- `app/services/generation/*`: llm backend/router, question generator, mcq generation orchestration.
- `app/services/verification/*`: validator, grounding checker, verifier tong hop.
- `app/services/review/*`: xu ly edit/regenerate co muc tieu.
- `app/services/exams/*`: orchestration end-to-end + luu version + publish.
- `app/services/feedback/*`: log su kien feedback/workflow + truy van store.
- `app/services/playbook/*`: luu/retrieve playbook, reflection candidates, warmup export.
- `app/services/analytics/*`: quality summary + phan loai error categories.
- `app/services/courses/*`: nghiep vu lien quan khoa hoc.

#### f) Shared utilities
- `app/utils/*`: security, rate-limit helper, bloom-level normalization utilities, email helpers.

#### g) Entrypoint
- `app/main.py`: FastAPI app, lifespan startup, khoi tao DB, preload retrieval stack, mount routers.

### 2.2 Compatibility zone (giu import cu khong vo)
- Cac module top-level nhu `backend/main.py`, `backend/config.py`, `backend/database.py`, `backend/services/*`, `backend/routers/*`, `backend/models/*`... duoc giu nhu shim/chuyen tiep import sang `app/*`.
- Muc dich: khong pha vo ma nguon cu trong qua trinh chuyen doi sang package `app`.
- Nguyen tac: logic moi dat o `app/*`, khong phat trien logic nghiep vu moi trong shim.

### 2.3 Legacy zone
- `backend/legacy/*` luu code cu tham khao, khong nam tren critical runtime path.
- Legacy routers khong duoc mount trong entrypoint active.

---

## 3) So do thu muc backend (rut gon)

```text
backend/
  app/                    # active runtime package
    api/
      routers/
      serializers/
    core/
    models/
    repositories/
    schemas/
    services/
      analytics/
      courses/
      curriculum/
      documents/
      exam_planning/
      exams/
      feedback/
      generation/
      playbook/
      retrieval/
      review/
      verification/
    utils/
    main.py

  alembic/                # migrations
  docs/                   # backend architecture docs
  evals/                  # offline evaluation + datasets/output/samples
  tests/                  # smoke/quality/foundation checks

  # compatibility shims (top-level)
  main.py
  config.py
  database.py
  core/
  models/
  repositories/
  routers/
  schemas/
  services/
  agents/
  utils/

  legacy/                 # non-critical legacy code
```

---

## 4) Ghi chu van hanh va onboarding
- Neu code moi cho runtime: uu tien dat trong `backend/app/*`.
- Neu can sua import cu: chi sua shim toi thieu, tranh dat business logic vao compatibility zone.
- Thu tu doc de onboarding nhanh:
  1. `backend/app/main.py`
  2. `backend/app/services/documents/service.py`
  3. `backend/app/services/exams/service.py`
  4. `backend/app/services/exam_planning/blueprint_service.py`
  5. `backend/app/services/retrieval/scoped_retrieval_service.py`
  6. `backend/app/services/generation/question_generator.py`
  7. `backend/app/services/verification/mcq_verifier_service.py`

## 5) Tom tat 1 cau
Backend da dat duoc mot nen tang MVP sinh de MCQ Vat ly theo huong grounded, co day du pipeline upload->parse->scope->generate->verify->review/version/publish, dong thoi bo sung feedback/playbook/warmup de san sang cho huong ACE foundation.
