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