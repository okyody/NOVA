# NOVA Product Execution

This file tracks the implementation backlog to move NOVA from the current codebase
to a production-ready Enterprise 1.0 product.

## Phase 0: Trustworthy Runtime

- [x] Fix server entrypoint import path for tracing
- [x] Add missing runtime dependency for health monitoring (`psutil`)
- [x] Align `docker-compose.yml` with `packages/core/config.py`
- [x] Restore valid monitoring volume paths in Docker Compose
- [x] Fix platform enum mismatches for Kuaishou / WeChat
- [x] Ensure Kuaishou adapter enters message receive loop
- [x] Verify app import smoke test
- [x] Verify full existing pytest suite still passes
- [x] Align `.env.example` with actual nested settings model
- [x] Align `nova.config.example.json` with actual settings schema
- [x] Add automated smoke/config consistency tests

## Phase 0 Next

- [x] Add compose-level startup validation in CI
- [x] Add a minimal `/health` startup test using FastAPI TestClient
- [x] Validate all platform config examples against platform manager
- [x] Normalize Windows/Linux startup paths in install scripts

## Phase 1: Productization Foundation

- [~] Replace in-process event bus for multi-instance mode
  Current status: dual-mode EventBus with local/external_consumer switching and Redis Streams transport foundation is in place; full distributed worker graph still pending.
- [x] Externalize hot session state to Redis
- [x] Add deterministic idempotency keys for inbound platform events
- [~] Split runtime roles: api / ingestion / orchestration / voice workers
  Current status: api/perception/cognitive/generation role-based startup, worker entrypoint, and k8s worker deployments are in place; further rollout/ops hardening remains.
- [x] Introduce persistent conversation and safety event storage

## Phase 2: Enterprise Control Plane

- [x] Add tenant, user, role, permission models
- [~] Add config revisioning and rollout management
  Current status: create/list/update/publish/rollback APIs exist; stricter revision state machine and rollout semantics still need hardening.
- [x] Add audit logs for all write operations
- [ ] Add knowledge base management with ACLs
- [~] Add runtime dashboard beyond the current debug-oriented Studio
  Current status: Studio now supports runtime status, control-plane reads/writes, and login-backed control requests; it still needs deeper workflow polish to become a complete admin workbench.

## Phase 3: Acceptance

- [x] Define Enterprise 1.0 acceptance scope
- [x] Freeze core permission-code set for 1.0
- [x] Add auth/me and DB-backed token issuance
- [x] Enforce tenant-scoped control-plane access
- [x] Align deploy SQL and k8s init schema with control-plane models

## Working Rule

No large planning-only work items should be marked complete without:

1. a code change,
2. a test or smoke check,
3. and a clear path to runtime verification.
