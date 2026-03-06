from typing import Dict, Any, Optional
from src.core.semantic_layer_db import get_semantic_layer_db


class SemanticPromptEnhancer:
    """
    Enhances LLM prompts with semantic layer context
    """

    def __init__(self):
        self.semantic_db = None
        try:
            self.semantic_db = get_semantic_layer_db()
        except Exception as e:
            print(f"⚠️ Semantic layer not available: {e}")

    def enhance_schema_info(self,
                            schema_info: str,
                            catalog: Optional[str] = None,
                            schema_name: Optional[str] = None) -> str:
        """
        Enhance schema information with semantic layer metadata

        Args:
            schema_info: Raw database schema
            catalog: Optional catalog filter
            schema_name: Optional schema filter

        Returns:
            Enhanced schema with business context
        """
        if not self.semantic_db:
            # No semantic layer - return original
            return schema_info

        try:
            # Get semantic context
            context = self.semantic_db.get_semantic_context(
                catalog=catalog,
                schema_name=schema_name
            )

            if not context or not context.get('entities'):
                # No semantic metadata - return original
                return schema_info

            # Build enhanced schema
            enhanced = self._build_enhanced_schema(schema_info, context)
            return enhanced

        except Exception as e:
            print(f"⚠️ Failed to enhance schema: {e}")
            return schema_info

    def _build_enhanced_schema(self,
                               original_schema: str,
                               semantic_context: Dict[str, Any]) -> str:
        """
        Build enhanced schema with semantic metadata
        """
        parts = []

        # Add original schema first
        parts.append("=== DATABASE SCHEMA ===")
        parts.append(original_schema)
        parts.append("")

        # Add semantic layer metadata
        if semantic_context.get('entities'):
            parts.append("=== BUSINESS CONTEXT (Semantic Layer) ===")
            parts.append("")

            # Entities with business names
            parts.append("📊 Available Entities (Tables with Business Names):")
            for entity in semantic_context['entities']:
                table_ref = f"{entity.get('catalog', '')}.{entity.get('schema', '')}.{entity['name']}" if entity.get(
                    'catalog') else entity['name']
                display = entity.get('display_name', entity['name'])
                desc = entity.get('description', '')

                parts.append(f"  • {table_ref}")
                if display != entity['name']:
                    parts.append(f"    Business Name: {display}")
                if desc:
                    parts.append(f"    Description: {desc}")

                # Show dimensions
                if entity.get('dimensions'):
                    dim_names = [d.get('display_name') or d['name'] for d in entity['dimensions']]
                    parts.append(f"    Dimensions: {', '.join(dim_names)}")

                # Show metrics
                if entity.get('metrics'):
                    metric_names = [m.get('display_name') or m['name'] for m in entity['metrics']]
                    parts.append(f"    Metrics: {', '.join(metric_names)}")

                parts.append("")

        # Add relationships (automatic joins)
        if semantic_context.get('relationships'):
            parts.append("🔗 Available Relationships (Automatic JOINs):")
            for rel in semantic_context['relationships']:
                parts.append(f"  • {rel['name']}: {rel['from']} → {rel['to']} ({rel.get('type', 'unknown')})")
            parts.append("")

        # Add calculated metrics
        if semantic_context.get('metrics'):
            parts.append("📈 Calculated Metrics (Business Logic):")
            for metric in semantic_context['metrics']:
                display = metric.get('display_name', metric['name'])
                desc = metric.get('description', '')
                sql = metric['sql']

                parts.append(f"  • {display}")
                if desc:
                    parts.append(f"    Description: {desc}")
                parts.append(f"    SQL: {sql}")
                parts.append("")

        return "\n".join(parts)

    def get_sql_generation_instructions(self) -> str:
        """
        Get additional SQL generation instructions when semantic layer is active
        """
        if not self.semantic_db:
            return ""

        try:
            context = self.semantic_db.get_semantic_context()

            if not context or not any([context.get('entities'),
                                       context.get('relationships'),
                                       context.get('metrics')]):
                return ""

            instructions = []

            instructions.append("\n=== SEMANTIC LAYER INSTRUCTIONS ===")

            if context.get('relationships'):
                instructions.append("""
When joining tables:
1. Check if a relationship exists in the "Available Relationships" section
2. If a relationship exists, use the exact join condition specified
3. Prefer LEFT JOIN unless specified otherwise
4. The semantic layer defines the correct join paths
""")

            if context.get('metrics'):
                instructions.append("""
When calculating metrics:
1. Check if a calculated metric exists in the "Calculated Metrics" section
2. If it exists, use the exact SQL expression provided
3. Do not recalculate - use the business-approved formula
4. Example: "revenue" should use SUM(orders.amount), not COUNT(*)
""")

            instructions.append("""
General rules:
1. Use business names (display names) when they exist
2. Follow the semantic layer definitions for consistency
3. The semantic layer ensures everyone calculates metrics the same way
""")

            return "\n".join(instructions)

        except Exception as e:
            print(f"⚠️ Failed to get instructions: {e}")
            return ""

    def extract_catalog_schema(self, schema_info: str) -> tuple[Optional[str], Optional[str]]:
        """
        Extract catalog and schema from schema info

        Returns:
            (catalog, schema_name) tuple
        """
        catalog = None
        schema_name = None

        # Try to parse from schema info
        # Format: "Table: catalog.schema.table" or "Table: schema.table"
        for line in schema_info.split('\n'):
            if line.startswith('Table:'):
                table_ref = line.replace('Table:', '').strip()
                parts = table_ref.split('.')

                if len(parts) == 3:
                    catalog = parts[0]
                    schema_name = parts[1]
                    break
                elif len(parts) == 2:
                    schema_name = parts[0]
                    break

        return catalog, schema_name


# Singleton instance
_semantic_enhancer = None


def get_semantic_enhancer() -> SemanticPromptEnhancer:
    """Get singleton instance of semantic enhancer"""
    global _semantic_enhancer

    if _semantic_enhancer is None:
        _semantic_enhancer = SemanticPromptEnhancer()

    return _semantic_enhancer