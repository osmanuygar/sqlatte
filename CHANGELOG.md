## [0.6.3] - 2026-08-24

### Fixed
- `ConfigDB`'s single shared Postgres connection now runs with `autocommit=True`. Read-only calls like `get_config()` never committed, leaving the connection "idle in transaction" indefinitely (visible in `pg_stat_activity`) — since it's a process-wide singleton, that starved every subsequent DB-backed request, surfacing as MCP tool calls (`list_tables`, `ask_database`, etc.) timing out well after auth itself succeeded.
- `TrinoProvider.discover_tables()`'s auto-DESCRIBE batch default raised from 5 to 25 matches (`DEFAULT_DESCRIBE_LIMIT`, overridable via a new `describe_limit` param), and it now reuses one connection for the whole batch instead of opening a fresh one per table.

### Added
- `rate_limiting.path_overrides` (optional): per-path `requests_per_window`/`window_seconds` that take priority over the section's global defaults — e.g. a stricter cap on `/auth/query` (real LLM+DB round trip) than on `/query` (legacy widget), or a burst guard on `/auth/discover` distinct from its own daily discover budget. Longest-prefix match wins; a path with only an override entry (not listed in `protected_paths`) is still protected.

### Changed - Unified catalog-less tokens
- Merged the "query" and "discovery" token models: the token screen (`frontend/tokens.html`) no longer collects a catalog/schema for Trino when discovery is enabled — sign-in is catalog-less (username/password only), and every token from it is scoped entirely by `plugins.auth.allowed_catalogs` instead of a single catalog picked up front. What used to be the separate "Discovery Token" mini-form is now just how sign-in works.
- Which enforcement path applies (single-catalog lock vs. allowlist) is now derived from the session/token's actual connection (`AuthPlugin._config_catalog` — does it have a catalog set?) instead of the stored `token_type`. This is fully backward compatible with no migration: a pre-existing "query" token still carries a fixed catalog and behaves exactly as before; a pre-existing "discovery" token, and every token minted from now on, has none and gets the allowlist behavior.
- `discover_tables` (`TrinoProvider.discover_tables`, `POST /auth/discover`) is now restricted server-side to `allowed_catalogs` when configured, instead of searching every catalog the DB user can see — less noise for the LLM, and a catalog-less token can no longer discover metadata for catalogs it isn't allowed to query anyway. It also now accepts an empty `search_term` to mean "list everything."
- `GET /auth/tables` (`list_tables`) now works for a catalog-less session — it falls back to `discover_tables` with an empty search term instead of erroring with "no default catalog," returning fully-qualified `catalog.schema.table` names.
- `GET /auth/schema/{table_name}` and `POST /auth/schema/multiple` (describe) are now gated by the same allowlist for a catalog-less session — `table_name` must be fully qualified and within `allowed_catalogs` (new `sql_validator.qualified_table_allowlist_violation`). Previously describe had no allowlist check at all for discovery tokens.

## [0.6.2] - 2026-08-17

### Added - Trino Catalog Lock & Discovery Tokens
- **Catalog lock enforcement** (`plugins.auth.enforce_catalog_lock`, on by default): rejects generated SQL that references a Trino catalog other than the one the session/token is scoped to — closes off an MCP client steering `ask_database` at a foreign catalog. No effect without `allowed_catalogs` configured or on non-Trino providers.
- **Discovery tokens** (`plugins.auth.enable_discovery_tokens`, **off by default**): cross-catalog table/collection name search, metadata only, no row data, no `ask_database` access.
  - New MCP tool `discover_tables` (only advertised to clients when the flag is on)
  - `POST /auth/discovery-token` — issue a token directly from Trino credentials
  - `POST /auth/discover` — search by session
  - `POST /auth/token/generate-discovery` — issue from an active session
  - `POST /admin/discovery-token` — admin-issued, backend-only for now (no self-service UI)
  - `TrinoProvider.discover_tables()` — federated search via `system.jdbc.tables`, Trino only

### Changed
- `/auth/config` now reports `discovery_enabled` so the frontend and MCP server know whether to surface discovery UI/tools.
- `frontend/tokens.html`: token list shows a Query/Discovery type badge; the discovery mini-form only renders when `discovery_enabled` is true.

## [0.5.0-beta] - 2025-01-XX

### Added - Semantic Layer (Beta) 🧠
- **Semantic Layer System**: Business intelligence metadata layer (BETA)
  - Entity definitions with business-friendly names
  - Relationship management for automatic JOINs
  - Calculated metrics with centralized business logic
  - Multi-catalog/schema support

- **Auto-Discovery Feature**: Automatically scan database and suggest entity definitions

- **Admin UI**: Visual management interface
  - Entities tab - Manage table definitions
  - Relationships tab - Define JOINs visually
  - Metrics tab - Create calculated fields
  - Auto-Discover tab - Database scanning
  - How to Use tab - Complete integration guide

- **LLM Prompt Enhancement**: Semantic context automatically added to LLM prompts
  - Business names and descriptions
  - Dimension and metric definitions
  - JOIN path instructions
  - Metric calculation rules

- **REST API**: Full CRUD operations for semantic metadata
  - `/api/semantic/entities` - Entity management
  - `/api/semantic/relationships` - Relationship management
  - `/api/semantic/metrics` - Metric management
  - `/api/semantic/discover` - Auto-discovery
  - `/api/semantic/context` - Get semantic context

- **Database Support**: PostgreSQL and SQLite (in-memory)
  - Auto-initialization on server startup
  - Graceful fallback to in-memory SQLite

### Changed
- Enhanced LLM providers with semantic context (backward compatible)
- Expanded admin panel with semantic layer tab
- Updated startup initialization sequence

### Technical Details
- New files: `semantic_layer_db.py`, `semantic_routes.py`, `semantic_prompt_enhancer.py`
- Database schema: 4 new tables for semantic metadata
- 100% backward compatible - existing queries unchanged

### Known Issues (Beta)
- Semantic layer UI may evolve in future releases
- Some edge cases in auto-discovery
- API endpoints may change based on feedback