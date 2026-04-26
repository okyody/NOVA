# NOVA Enterprise 1.0 Acceptance

This document defines what counts as "done" for a deliverable NOVA Enterprise
1.0 release. It is intentionally narrower than the long-term platform vision.

## 1. Product Scope

NOVA Enterprise 1.0 is accepted as a product when it can run one complete
interactive digital-agent workflow in a private deployment with:

- a stable runtime topology
- a working control plane
- tenant-scoped access control
- persistent audit and runtime history
- a repeatable deployment process

Out of scope for 1.0:

- adding more platforms beyond the primary delivery path
- generalized autonomous multi-agent orchestration
- broad avatar/render ecosystem expansion
- consumer-facing marketplace features

## 2. Runtime Topology

The reference runtime topology is:

- `nova-api`
- `nova-perception`
- `nova-cognitive`
- `nova-generation`
- `redis`
- `postgres`
- `qdrant`
- `ollama`

The product is accepted only if this topology is supported in:

- `docker-compose.yml`
- `deploy/k8s/nova-deployment.yaml`

## 3. Control Plane Requirements

The control plane must support the following resources:

- tenants
- users
- roles
- permissions
- role_permissions
- user_roles
- config_revisions
- audit_logs

The control plane is accepted only if:

1. Users can be created and updated.
2. Roles can be created and updated.
3. Permissions can be created and bound to roles.
4. Roles can be bound to users.
5. Config revisions can be created, published, and rolled back.
6. All write operations produce audit records.

## 4. Auth and RBAC Requirements

The auth model must satisfy all of the following:

- token issuance is database-backed
- tokens contain `sub`, `roles`, `permissions`, and `tenant_ids`
- `/api/auth/me` returns the authenticated user context
- control-plane endpoints enforce permission-code checks
- control-plane endpoints enforce tenant scope checks
- global admins may cross tenant boundaries
- tenant-scoped users may only access their own tenant resources

Reference permission codes for 1.0:

- `tenant.read`
- `tenant.write`
- `user.read`
- `user.write`
- `role.read`
- `role.write`
- `permission.read`
- `permission.write`
- `config_revision.read`
- `config_revision.write`
- `config_revision.publish`
- `config_revision.rollback`

## 5. Runtime Behavior Requirements

The runtime is accepted only if:

1. Events enter through the platform/perception path.
2. Semantic aggregation runs on embeddings, not TF-IDF.
3. NLU and emotion influence routing decisions.
4. Runtime outputs are persisted where enabled.
5. DLQ/retry infrastructure is present for external-consumer mode.
6. Runtime state can be inspected through health, metrics, and Studio.

## 6. Deployment Requirements

### Docker Compose

Compose is accepted only if:

- all required services are declared
- nested env var names match the current settings model
- startup smoke checks pass

### Kubernetes

Kubernetes is accepted only if:

- Postgres runs as a `StatefulSet`
- backup is configured as a `CronJob`
- schema init is available through SQL config and migration job
- worker roles are deployed separately
- secrets are externalized through `Secret` resources

## 7. Studio Requirements

Studio is accepted as the 1.0 control console only if:

- it can display current runtime status
- it can display current authenticated user context
- it can read control-plane resources
- it can execute the minimal control-plane write flows
- it sends authenticated control-plane requests with the active token

## 8. Test Gate

The release is accepted only if:

- the full automated test suite passes
- control-plane auth tests pass
- productization smoke tests pass
- deployment manifest smoke tests pass

## 9. Go/No-Go Checklist

Release only if all answers are "yes":

- Can an authenticated user obtain a DB-backed token?
- Can `/api/auth/me` return the same user's roles and tenant scope?
- Can tenant scoping deny cross-tenant access?
- Can a tenant admin manage only the allowed resources?
- Can a config revision be created, published, and rolled back?
- Are runtime events persisted and queryable?
- Are audit records produced for control-plane writes?
- Does the reference deployment topology exist in both Compose and K8s?
- Does the full test suite pass?

If any answer is "no", the release is not 1.0-complete.
