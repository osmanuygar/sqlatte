# Kubernetes Deployment

**Manifests:** `k8s/`
**Status:** Deployed and smoke-tested end-to-end on a local cluster (OrbStack, single node) — see [Tested Configuration](#tested-configuration).

---

## Architecture

```
Ingress (TLS termination)
    │
    ▼
Service: sqlatte (ClusterIP :80 → :8000)
    │
    ▼
Deployment: sqlatte (replicas: 1)
    │  reads config.yaml from Secret: sqlatte-config
    ▼
Service: postgres (headless, :5432)
    │
    ▼
StatefulSet: postgres (replicas: 1, PVC-backed)
    databases: sqlatte_analytics, sqlatte_config
```

Two logical databases, one Postgres instance:

| Database | Used by | Config block |
|---|---|---|
| `sqlatte_analytics` | `queries`, `audit_logs`, `scheduled_queries`, `schedule_executions`, `email_deliveries`, `dashboards` | `analytics.postgresql` |
| `sqlatte_config` | `configurations`, `config_history`, `config_snapshots`, `api_tokens`, `mcp_mask_rules`, `semantic_entities`, `semantic_columns`, `semantic_relationships`, `semantic_metrics` | `config_db.postgresql` |

All tables are created by the app itself at runtime (`CREATE TABLE IF NOT EXISTS` — see the "no PostgreSQL init script" note in the main README). The Postgres StatefulSet only creates the *databases* and the app role, via `02-postgres-init-configmap.yaml`.

## Why `replicas: 1`

`admin_auth.py` and `auth_plugin.py`'s `SessionManager` hold sessions **in-memory, per-process**. With more than one replica (or more than one gunicorn worker inside the pod), a user's session may not exist on whichever pod/worker handles their next request → random "session expired" errors. `10-deployment.yaml` pins `replicas: 1` and uses `strategy: Recreate` (so a rollout doesn't briefly run two pods in parallel) specifically because of this. Don't raise it without first moving session storage to something shared (Redis/Postgres) — that's app-code work, not a manifest change.

## Deploy order

```bash
kubectl apply -f k8s/00-namespace.yaml

kubectl create secret generic postgres-credentials -n sqlatte \
  --from-literal=POSTGRES_PASSWORD='<superuser-password>' \
  --from-literal=SQLATTE_APP_PASSWORD='<app-role-password>'

kubectl apply -f k8s/02-postgres-init-configmap.yaml \
              -f k8s/03-postgres-statefulset.yaml \
              -f k8s/04-postgres-service.yaml

# wait for postgres-0 to be Ready before continuing
kubectl -n sqlatte wait --for=condition=ready pod -l app=postgres --timeout=120s

kubectl create secret generic sqlatte-config -n sqlatte \
  --from-file=config.yaml=./config/config.yaml

kubectl apply -f k8s/10-deployment.yaml \
              -f k8s/11-service.yaml \
              -f k8s/12-ingress.yaml   # requires an ingress controller (e.g. ingress-nginx) + cert-manager for TLS
```

See `01-postgres-secret.yaml.example` and `05-app-config-secret.yaml.example` for the exact Secret shapes — both are templates, not meant to be applied directly (real values only ever go in via `kubectl create secret`, never committed).

`config.yaml`'s `analytics.postgresql` / `config_db.postgresql` blocks should point at:
```yaml
host: postgres.sqlatte.svc.cluster.local   # or just "postgres" from within the sqlatte namespace
port: 5432
user: sqlatte_app
password: <same value as SQLATTE_APP_PASSWORD>
database: sqlatte_analytics   # or sqlatte_config, respectively
```

## Updating an existing deployment

Two independent things can change between deploys — a new image (code) and/or
a new `config.yaml` (config) — update whichever actually changed.

**1. New code — build, push, roll out:**

```bash
# Build (run from the repo root, where Dockerfile lives)
docker build -t <your-registry>/sqlatte:latest .

# Push to whatever registry the cluster pulls from
docker push <your-registry>/sqlatte:latest

# 10-deployment.yaml pins `image: sqlatte:latest` — a mutable tag. Re-applying
# identical manifest text is a no-op: kubectl only restarts pods on a spec
# diff, and pushing a new image doesn't change the manifest text, so an
# already-running pod keeps its already-pulled image indefinitely. Force it:
kubectl rollout restart deployment/sqlatte -n sqlatte
kubectl -n sqlatte rollout status deployment/sqlatte   # watch it come back healthy
```

Prefer a versioned tag (`sqlatte:v0.7.0`) over `:latest` where practical —
`kubectl set image deployment/sqlatte sqlatte=<registry>/sqlatte:v0.7.0 -n sqlatte`
both updates the manifest *and* triggers the rollout in one step, and makes
`kubectl rollout undo` meaningful if the new version misbehaves. `:latest`
can only be rolled back by re-pushing the old image under the same tag.

Because of `strategy: Recreate` (see [Why replicas: 1](#why-replicas-1)),
the rollout briefly takes the app fully offline — the old pod terminates
completely before the new one starts. Every active session (UI logins, MCP
SSE connections) is dropped and must reconnect; API tokens themselves are
unaffected (they're persisted in Postgres, not session state).

**2. New config — no image change needed:**

```bash
kubectl create secret generic sqlatte-config -n sqlatte \
  --from-file=config.yaml=./config/config.k8s.yaml \
  --dry-run=client -o yaml | kubectl apply -f -

# Secret volumes update in the pod's filesystem within ~60s on their own,
# but the running Python process already has the old config in memory
# (config.yaml is only read once at startup — see src/api/app.py's
# module-level `config = config_manager.load_from_file(...)`), so it still
# needs an explicit restart to pick the new values up:
kubectl rollout restart deployment/sqlatte -n sqlatte
```

Schema changes (new Postgres columns/tables) never need a manual migration
step — every module creates/alters its own tables on startup (see the "no
PostgreSQL init script" note in the main README), so a plain restart against
the existing database is enough even when the new image expects new columns.

## TLS

Terminated at the Ingress (`12-ingress.yaml`), not in the app — same reasoning as the reverse-proxy recommendation for the Docker/bare-metal deployment. Needs an ingress controller and, for automatic certs, cert-manager; neither is included here (cluster-level installs).

## Health checks

Both the Deployment's probes and the Postgres StatefulSet's probes hit real endpoints:
- App: `GET /health` (`app.py`) — returns `database.healthy` / `llm.healthy` flags, but the top-level `status` field is currently hardcoded to `"healthy"` regardless of those flags, so it's only useful as a liveness signal ("is the process responding"), not a dependency-health signal yet.
- Postgres: `pg_isready`.

---

## Tested Configuration

Verified end-to-end on 2026-07-17 against a local OrbStack Kubernetes cluster (single node), using an image built from this repo's `Dockerfile` and a minimal test `config.yaml` (dummy LLM key, real in-cluster Postgres credentials):

- `postgres-0` started, ran the init script, created `sqlatte_app` role + both databases.
- `sqlatte` pod started, connected to `sqlatte_analytics`/`sqlatte_config` over the headless `postgres` Service, initialized Analytics DB, Audit Log DB, Config DB (Postgres-backed), Semantic Layer, Session Manager.
- `GET /health` → `200`, `database.healthy: true` (`llm.healthy: false` as expected — dummy key).
- `GET /` → `200`; `GET /admin` → `307` to `/admin/login`; `GET /admin/login` → `200`.
- No errors in steady-state logs.

One real bug was found and fixed during this test: the `Dockerfile`'s `CMD` ran `python src/api/app.py` (direct script path), which raised `ModuleNotFoundError: No module named 'src'` — running a script directly (vs. `python -m src.api.app`, which is what the README documents for local dev) doesn't put the project root on `sys.path`, breaking the `src.*` absolute imports used throughout the codebase. Fixed to `CMD ["python", "-m", "src.api.app"]`.
