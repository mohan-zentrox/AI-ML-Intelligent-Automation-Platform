# Project Synapse - Team & Roles

This document is the single source of truth for role identifiers used
throughout the codebase, seed data, and commit history. Per the source
BRD/FRD/SRS, **only these role IDs are ever used** - never real personal
names.

## Role Roster

| Role ID   | Function                          | Platform RBAC Role  | Primary Responsibilities                                          |
|-----------|------------------------------------|----------------------|---------------------------------------------------------------------|
| T6-LEAD   | ML Lead / AI Engineer              | `admin`              | Overall technical ownership, LLM provider strategy, RBAC/API key admin |
| T6-BE1    | Backend Engineer, Python           | `workflow_builder`   | FastAPI backend, ingestion pipeline, workflow builder backend contract |
| T6-DEV1   | Software Developer                 | `reviewer`           | Frontend, human-in-the-loop review queue UX and workflows            |
| T6-DATA1  | Data Analyst / ML Support          | `analyst`            | Retrieval quality, embedding/chunking tuning, usage analytics        |
| T6-DATA2  | Data Analyst / ML Support          | `analyst`            | Eval dataset curation, promptfoo regression fixtures                 |
| T6-DATA3  | Data Analyst / ML Support          | `api_consumer`       | Programmatic integration testing, API consumer perspective           |

## RBAC Role -> Capability Matrix

| Platform Role       | Ingest Documents | Query (RAG) | Review Queue | Usage Analytics | Issue API Keys |
|----------------------|:---:|:---:|:---:|:---:|:---:|
| `admin`              | Yes | Yes | Yes | Yes | Yes |
| `workflow_builder`   | Yes | Yes | No  | No  | No  |
| `reviewer`           | No  | Yes | Yes | No  | No  |
| `analyst`            | Yes | Yes | No  | Yes | No  |
| `api_consumer`       | No  | Yes | No  | No  | No  |

See `backend/app/core/security.py` (`Role` enum) and `backend/app/core/deps.py`
(`require_role`) for the enforced implementation, and
`backend/app/api/v1/*.py` for the per-endpoint gates.

## Local Dev Seed Accounts

`app.db.session.seed_reference_data()` seeds one user per role ID above on
first startup, all with email `<ROLE_ID>@synapse.example` and password
`ChangeMe123!`. For example: `T6-LEAD@synapse.example`.

The domain is `.example`, **not** `.local`: `.local` is an RFC 6762
special-use TLD that `email-validator` (behind pydantic's `EmailStr`) always
rejects, so a seeded `@synapse.local` address could never log in through
`POST /api/v1/auth/login`.

**This password is a local-development-only placeholder and must never be
used, or a variant of it reused, in any real deployment.** Seeding is gated on
`ENVIRONMENT=local` and these accounts are not created in any other
environment - see `should_seed_demo_users` in `backend/app/core/config.py`.
