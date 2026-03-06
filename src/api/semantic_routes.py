from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from src.core.semantic_layer_db import get_semantic_layer_db


# ==========================================
# PYDANTIC MODELS
# ==========================================

class EntityCreate(BaseModel):
    catalog: Optional[str] = None
    schema_name: Optional[str] = None
    table_name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    primary_key: Optional[str] = None
    entity_type: str = 'table'


class EntityUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    primary_key: Optional[str] = None
    is_active: Optional[bool] = None


class ColumnCreate(BaseModel):
    entity_id: int
    column_name: str
    display_name: Optional[str] = None
    data_type: Optional[str] = None
    description: Optional[str] = None
    is_dimension: bool = False
    is_metric: bool = False
    format_type: Optional[str] = None
    aggregation_type: Optional[str] = None


class RelationshipCreate(BaseModel):
    name: str
    from_entity_id: int
    from_column: str
    to_entity_id: int
    to_column: str
    relationship_type: str = 'many_to_one'
    join_type: str = 'LEFT'
    description: Optional[str] = None


class MetricCreate(BaseModel):
    name: str
    sql_expression: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    format_type: Optional[str] = None
    category: Optional[str] = None
    requires_entities: Optional[List[str]] = None


# ==========================================
# ROUTER SETUP
# ==========================================

router = APIRouter(prefix="/api/semantic", tags=["semantic"])


# ==========================================
# ENTITY ENDPOINTS
# ==========================================

@router.get("/entities")
async def get_entities(
        catalog: Optional[str] = None,
        schema_name: Optional[str] = None,
        active_only: bool = True
):
    """
    Get all semantic entities

    Query params:
    - catalog: Filter by catalog
    - schema_name: Filter by schema
    - active_only: Only return active entities
    """
    try:
        semantic_db = get_semantic_layer_db()
        entities = semantic_db.get_entities(
            catalog=catalog,
            schema_name=schema_name,
            active_only=active_only
        )

        return {
            "success": True,
            "entities": entities,
            "count": len(entities)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: int):
    """Get a single entity with its columns"""
    try:
        semantic_db = get_semantic_layer_db()
        entity = semantic_db.get_entity(entity_id)

        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")

        columns = semantic_db.get_columns(entity_id)
        relationships = semantic_db.get_relationships(entity_id)

        return {
            "success": True,
            "entity": entity,
            "columns": columns,
            "relationships": relationships
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/entities")
async def create_entity(entity: EntityCreate):
    """Create a new semantic entity"""
    try:
        semantic_db = get_semantic_layer_db()

        entity_id = semantic_db.create_entity(
            catalog=entity.catalog,
            schema_name=entity.schema_name,
            table_name=entity.table_name,
            display_name=entity.display_name,
            description=entity.description,
            primary_key=entity.primary_key,
            entity_type=entity.entity_type
        )

        return {
            "success": True,
            "entity_id": entity_id,
            "message": f"Entity '{entity.display_name or entity.table_name}' created"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/entities/{entity_id}")
async def update_entity(entity_id: int, updates: EntityUpdate):
    """Update an entity"""
    try:
        semantic_db = get_semantic_layer_db()

        update_dict = updates.dict(exclude_unset=True)
        success = semantic_db.update_entity(entity_id, update_dict)

        if not success:
            raise HTTPException(status_code=404, detail="Entity not found or no changes made")

        return {
            "success": True,
            "message": "Entity updated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/entities/{entity_id}")
async def delete_entity(entity_id: int):
    """Soft delete an entity (sets is_active=False)"""
    try:
        semantic_db = get_semantic_layer_db()
        success = semantic_db.delete_entity(entity_id)

        if not success:
            raise HTTPException(status_code=404, detail="Entity not found")

        return {
            "success": True,
            "message": "Entity deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# COLUMN ENDPOINTS
# ==========================================

@router.get("/entities/{entity_id}/columns")
async def get_columns(entity_id: int):
    """Get all columns for an entity"""
    try:
        semantic_db = get_semantic_layer_db()
        columns = semantic_db.get_columns(entity_id)

        return {
            "success": True,
            "columns": columns,
            "count": len(columns)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/columns")
async def create_column(column: ColumnCreate):
    """Create a semantic column"""
    try:
        semantic_db = get_semantic_layer_db()

        column_id = semantic_db.create_column(
            entity_id=column.entity_id,
            column_name=column.column_name,
            display_name=column.display_name,
            data_type=column.data_type,
            description=column.description,
            is_dimension=column.is_dimension,
            is_metric=column.is_metric,
            format_type=column.format_type,
            aggregation_type=column.aggregation_type
        )

        return {
            "success": True,
            "column_id": column_id,
            "message": f"Column '{column.display_name or column.column_name}' created"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# RELATIONSHIP ENDPOINTS
# ==========================================

@router.get("/relationships")
async def get_relationships(entity_id: Optional[int] = None):
    """Get all relationships, optionally filtered by entity"""
    try:
        semantic_db = get_semantic_layer_db()
        relationships = semantic_db.get_relationships(entity_id=entity_id)

        return {
            "success": True,
            "relationships": relationships,
            "count": len(relationships)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/relationships")
async def create_relationship(relationship: RelationshipCreate):
    """Create a relationship (join definition)"""
    try:
        semantic_db = get_semantic_layer_db()

        rel_id = semantic_db.create_relationship(
            name=relationship.name,
            from_entity_id=relationship.from_entity_id,
            from_column=relationship.from_column,
            to_entity_id=relationship.to_entity_id,
            to_column=relationship.to_column,
            relationship_type=relationship.relationship_type,
            join_type=relationship.join_type,
            description=relationship.description
        )

        return {
            "success": True,
            "relationship_id": rel_id,
            "message": f"Relationship '{relationship.name}' created"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# METRIC ENDPOINTS
# ==========================================

@router.get("/metrics")
async def get_metrics(active_only: bool = True):
    """Get all metrics"""
    try:
        semantic_db = get_semantic_layer_db()
        metrics = semantic_db.get_metrics(active_only=active_only)

        return {
            "success": True,
            "metrics": metrics,
            "count": len(metrics)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/metrics")
async def create_metric(metric: MetricCreate):
    """Create a calculated metric"""
    try:
        semantic_db = get_semantic_layer_db()

        metric_id = semantic_db.create_metric(
            name=metric.name,
            sql_expression=metric.sql_expression,
            display_name=metric.display_name,
            description=metric.description,
            format_type=metric.format_type,
            category=metric.category,
            requires_entities=metric.requires_entities
        )

        return {
            "success": True,
            "metric_id": metric_id,
            "message": f"Metric '{metric.display_name or metric.name}' created"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# SEMANTIC CONTEXT ENDPOINT
# ==========================================

@router.get("/context")
async def get_semantic_context(
        catalog: Optional[str] = None,
        schema_name: Optional[str] = None
):
    """
    Get semantic context for LLM prompt enhancement

    Returns business-friendly metadata including:
    - Entity definitions
    - Relationships (joins)
    - Metrics (calculated fields)
    """
    try:
        semantic_db = get_semantic_layer_db()
        context = semantic_db.get_semantic_context(
            catalog=catalog,
            schema_name=schema_name
        )

        return {
            "success": True,
            "context": context
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# AUTO-DISCOVERY ENDPOINT
# ==========================================

@router.post("/discover")
async def discover_entities(request: Dict[str, Any]):
    """
    Auto-discover entities from database

    Request:
    {
        "catalog": "hive",
        "schema": "default",
        "tables": ["customers", "orders"]
    }

    Scans database and suggests entity definitions
    """
    try:
        from src.core.config_manager_enhanced import config_manager
        from src.core.provider_factory import ProviderFactory

        catalog = request.get('catalog')
        schema_name = request.get('schema')
        tables = request.get('tables', [])

        if not tables:
            raise HTTPException(status_code=400, detail="No tables provided")

        # Get database provider
        config = config_manager.get_config()
        db_provider = ProviderFactory.create_db_provider(config)

        discovered = []

        for table in tables:
            try:
                # Get schema from database
                schema_info = db_provider.get_table_schema(table)

                # Parse schema to extract columns
                # This is a simple parser - can be enhanced
                columns = []
                for line in schema_info.split('\n'):
                    if '|' in line:
                        parts = [p.strip() for p in line.split('|')]
                        if len(parts) >= 2 and parts[0] and not parts[0].startswith('-'):
                            col_name = parts[0]
                            col_type = parts[1] if len(parts) > 1 else 'unknown'

                            columns.append({
                                "name": col_name,
                                "type": col_type,
                                "is_dimension": col_type.lower() in ['varchar', 'string', 'date', 'timestamp'],
                                "is_metric": col_type.lower() in ['int', 'bigint', 'double', 'decimal', 'float']
                            })

                discovered.append({
                    "catalog": catalog,
                    "schema": schema_name,
                    "table_name": table,
                    "display_name": table.replace('_', ' ').title(),
                    "columns": columns,
                    "primary_key": columns[0]['name'] if columns else None  # Guess first column as PK
                })

            except Exception as e:
                print(f"❌ Failed to discover {table}: {e}")

        return {
            "success": True,
            "discovered": discovered,
            "count": len(discovered)
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))