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
