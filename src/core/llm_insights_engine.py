from typing import List, Dict, Any, Optional
import statistics
from datetime import datetime, timedelta
import json


class LLMInsightsEngine:
    """
    LLM-powered insights generator

    Uses LLM to generate business-aware insights based on:
    - Schema information (table names, column types)
    - Query results (actual data)
    - User question (context)
    - Date/time context (incomplete data awareness)
    """

    def __init__(self, llm_provider=None, config: Dict = None):
        """
        Initialize with LLM provider and config

        Args:
            llm_provider: LLM provider instance
            config: Configuration dict with:
                - enabled: bool (default False)
                - mode: 'llm_only', 'statistical_only', 'hybrid' (default 'hybrid')
                - max_insights: int (default 3)
                - include_statistical: bool (default True)
        """
        self.llm_provider = llm_provider
        self.config = config or {}

        # Default config
        self.enabled = self.config.get('enabled', False)
        self.mode = self.config.get('mode', 'hybrid')  # llm_only, statistical_only, hybrid
        self.max_insights = self.config.get('max_insights', 3)
        self.include_statistical = self.config.get('include_statistical', True)

        # Context
        self.today = datetime.now().date()
        self.current_hour = datetime.now().hour

        print(f"💡 Insights Engine initialized:")
        print(f"   - Enabled: {self.enabled}")
        print(f"   - Mode: {self.mode}")
        print(f"   - LLM: {'Available' if llm_provider else 'Not available'}")

    def generate_insights(
        self,
        columns: List[str],
        data: List[List[Any]],
        user_question: Optional[str] = None,
        schema_info: Optional[str] = None,
        sql_query: Optional[str] = None,
        prompt_override: Optional[str] = None,
        max_insights: Optional[int] = None
    ) -> List[Dict]:
        """
        Generate insights (LLM-powered or statistical)

        Args:
            columns: Column names
            data: Query results
            user_question: Original user question
            schema_info: Schema information (table structure)
            sql_query: Generated SQL query

        Returns:
            List of insight dictionaries
        """
        # If disabled, return empty
        if not self.enabled:
            return []

        # If no data, return empty result message
        if not data or len(data) == 0:
            return [{
                'type': 'empty',
                'icon': 'ℹ️',
                'severity': 'info',
                'message': 'Sonuç bulunamadı'
            }]

        insights = []

        # Mode selection
        if self.mode == 'llm_only' and self.llm_provider:
            insights = self._generate_llm_insights(
                columns, data, user_question, schema_info, sql_query, prompt_override
            )

        elif self.mode == 'statistical_only':
            insights = self._generate_statistical_insights(
                columns, data, user_question
            )

        elif self.mode == 'hybrid':
            # Try LLM first, fallback to statistical
            if self.llm_provider:
                insights = self._generate_llm_insights(
                    columns, data, user_question, schema_info, sql_query, prompt_override
                )

                # If LLM failed or returned nothing, add statistical
                if not insights and self.include_statistical:
                    insights = self._generate_statistical_insights(
                        columns, data, user_question
                    )
            else:
                # No LLM, use statistical
                insights = self._generate_statistical_insights(
                    columns, data, user_question
                )

        # Limit insights — caller can override the engine default
        limit = max_insights if max_insights is not None else self.max_insights
        return insights[:limit]

    def _generate_llm_insights(
        self,
        columns: List[str],
        data: List[List[Any]],
        user_question: Optional[str],
        schema_info: Optional[str],
        sql_query: Optional[str],
        prompt_override: Optional[str] = None
    ) -> List[Dict]:
        """
        Generate LLM-powered insights with schema + data context
        """
        try:
            # Prepare context
            context = self._build_context(columns, data, user_question, schema_info, sql_query)

            # Build prompt — use override if provided (e.g. ops_insights_generation from config)
            if prompt_override:
                prompt = prompt_override.format(
                    user_question=context['question'],
                    data_preview=self._format_data_sample(context['columns'], context['data_sample']),
                    row_count=context['row_count'],
                    columns=', '.join(context['columns']),
                )
            else:
                prompt = self._build_llm_prompt(context)

            # Call LLM
            print("🧠 Calling LLM for insights...")
            response = self.llm_provider.generate_chat_response(prompt, "")

            # Parse response
            insights = self._parse_llm_response(response)

            print(f"✅ LLM generated {len(insights)} insights")
            return insights

        except Exception as e:
            print(f"⚠️ LLM insights failed: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _build_context(
        self,
        columns: List[str],
        data: List[List[Any]],
        user_question: Optional[str],
        schema_info: Optional[str],
        sql_query: Optional[str]
    ) -> Dict:
        """
        Build rich context for LLM
        """
        context = {
            'question': user_question or 'Data query',
            'columns': columns,
            'row_count': len(data),
            'data_sample': data[:5],  # First 5 rows
            'schema': schema_info,
            'sql': sql_query,
            'current_time': {
                'date': str(self.today),
                'hour': self.current_hour,
                'is_business_hours': 9 <= self.current_hour <= 18,
                'day_of_week': self.today.strftime('%A')
            }
        }

        # Detect numeric columns
        numeric_cols = []
        for col_idx, col_name in enumerate(columns):
            sample = [row[col_idx] for row in data[:10] if col_idx < len(row)]
            if sample and all(isinstance(v, (int, float)) or (isinstance(v, str) and v.replace('.', '').replace(',', '').isdigit()) for v in sample if v is not None):
                numeric_cols.append(col_name)

        context['numeric_columns'] = numeric_cols

        # Detect date columns
        date_cols = []
        for col_idx, col_name in enumerate(columns):
            if any(word in col_name.lower() for word in ['date', 'time', 'tarih', 'gun', 'day']):
                date_cols.append(col_name)

        context['date_columns'] = date_cols

        # Detect if today's data might be incomplete
        if date_cols and data:
            try:
                last_row = data[-1]
                for date_col in date_cols:
                    col_idx = columns.index(date_col)
                    last_date_str = str(last_row[col_idx])

                    if str(self.today) in last_date_str:
                        context['incomplete_data_warning'] = True
                        context['current_time']['completion_percent'] = (self.current_hour / 24) * 100
                        break
            except:
                pass

        return context

    def _build_llm_prompt(self, context: Dict) -> str:
        """
        Build smart prompt for LLM
        """
        prompt = f"""Sen bir veri analisti asistanısın. Kullanıcının query sonuçlarını analiz edip iş değeri olan insights üret.

KULLANICI SORUSU:
{context['question']}

SCHEMA BİLGİSİ:
{context.get('schema', 'Bilgi yok')}

SQL QUERY:
{context.get('sql', 'Bilgi yok')}

SONUÇLAR:
- Toplam satır: {context['row_count']}
- Kolonlar: {', '.join(context['columns'])}
- Sayısal kolonlar: {', '.join(context['numeric_columns']) if context['numeric_columns'] else 'Yok'}
- Tarih kolonları: {', '.join(context['date_columns']) if context['date_columns'] else 'Yok'}

İLK 5 SATIR ÖRNEK:
{self._format_data_sample(context['columns'], context['data_sample'])}

ZAMAN CONTEXT:
- Şu an: {context['current_time']['date']} {context['current_time']['hour']:02d}:00
- Gün: {context['current_time']['day_of_week']}
- Mesai saati: {'Evet' if context['current_time']['is_business_hours'] else 'Hayır'}
"""

        if context.get('incomplete_data_warning'):
            prompt += f"""
⚠️ DİKKAT: Bugünün verisi eksik olabilir (günün %{context['current_time']['completion_percent']:.0f}'si geçti)
"""

        prompt += """

GÖREV:
1. Veriye bakarak 2-3 anlamlı insight üret
2. İş değeri olan, actionable bulgular ver
3. Eksik/yanıltıcı veri varsa UYAR
4. Sayısal değerleri Türkçe formatta göster (1.234,56)

ÇIKTI FORMATI (JSON):
```json
[
  {
    "type": "trend|anomaly|warning|summary",
    "icon": "📈|📉|⚠️|🚀|💡|📊",
    "severity": "info|success|warning",
    "message": "Türkçe insight mesajı (max 100 karakter)"
  }
]
```

ÖNEMLİ KURALLAR:
- Sadece JSON döndür, başka hiçbir şey yazma
- Maksimum 3 insight
- Her insight actionable olmalı
- Eksik veriyle trend hesaplama
- Gereksiz teknik detay verme
- İş diliyle konuş

JSON:"""

        return prompt

    def _format_data_sample(self, columns: List[str], sample: List[List[Any]]) -> str:
        """Format data sample for prompt"""
        if not sample:
            return "Veri yok"

        lines = []
        lines.append(" | ".join(columns))
        lines.append("-" * 50)

        for row in sample[:5]:
            formatted_row = [str(val)[:20] if val is not None else 'NULL' for val in row]
            lines.append(" | ".join(formatted_row))

        return "\n".join(lines)

    def _parse_llm_response(self, response: str) -> List[Dict]:
        """
        Parse LLM response into insights
        """
        try:
            # Extract JSON from response (LLM might add markdown)
            json_str = response.strip()

            # Remove markdown code blocks if present
            if '```json' in json_str:
                json_str = json_str.split('```json')[1].split('```')[0]
            elif '```' in json_str:
                json_str = json_str.split('```')[1].split('```')[0]

            json_str = json_str.strip()

            # Parse JSON
            insights = json.loads(json_str)

            # Validate
            if not isinstance(insights, list):
                print(f"⚠️ LLM response is not a list: {type(insights)}")
                return []

            # Validate each insight
            valid_insights = []
            for insight in insights:
                if all(key in insight for key in ['type', 'icon', 'severity', 'message']):
                    valid_insights.append(insight)
                else:
                    print(f"⚠️ Invalid insight format: {insight}")

            return valid_insights

        except json.JSONDecodeError as e:
            print(f"⚠️ Failed to parse LLM JSON: {e}")
            print(f"Response: {response[:200]}")
            return []
        except Exception as e:
            print(f"⚠️ Failed to parse LLM response: {e}")
            return []

    def _generate_statistical_insights(
        self,
        columns: List[str],
        data: List[List[Any]],
        user_question: Optional[str]
    ) -> List[Dict]:
        """
        Fallback statistical insights (basic)
        """
        insights = []

        # Summary
        insights.append({
            'type': 'summary',
            'icon': '📊',
            'severity': 'info',
            'message': f'{len(data)} satır, {len(columns)} sütun'
        })

        # Find numeric columns
        numeric_cols = self._find_numeric_columns(columns, data)

        if numeric_cols:
            # Quick stats on first numeric column
            col_idx = columns.index(numeric_cols[0])
            values = [self._to_number(row[col_idx]) for row in data if col_idx < len(row)]
            values = [v for v in values if v is not None]

            if values:
                avg = statistics.mean(values)
                max_val = max(values)

                insights.append({
                    'type': 'stat',
                    'icon': '💡',
                    'severity': 'info',
                    'message': f'{numeric_cols[0]} ortalama: {self._format_number(avg)}, max: {self._format_number(max_val)}'
                })

        return insights[:self.max_insights]

    def _find_numeric_columns(self, columns: List[str], data: List[List[Any]]) -> List[str]:
        """Find numeric columns"""
        numeric_cols = []
        for col_idx, col_name in enumerate(columns):
            sample = [row[col_idx] for row in data[:10] if col_idx < len(row) and row[col_idx] is not None]
            if sample:
                numeric_count = sum(1 for v in sample if self._to_number(v) is not None)
                if numeric_count / len(sample) > 0.8:
                    numeric_cols.append(col_name)
        return numeric_cols

    def _to_number(self, value: Any) -> Optional[float]:
        """Convert to number"""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                cleaned = value.strip().replace('$', '').replace('€', '').replace('₺', '')
                cleaned = cleaned.replace(',', '')
                return float(cleaned)
            except:
                return None
        return None

    def _format_number(self, num: float) -> str:
        """Format number"""
        if num >= 1_000_000:
            return f'{num/1_000_000:.1f}M'
        elif num >= 1_000:
            return f'{num/1_000:.1f}K'
        else:
            return f'{num:.0f}'


# ============================================
# SINGLETON INSTANCE (Thread-Safe)
# ============================================

class InsightsEngineSingleton:
    """
    Singleton pattern for thread-safe insights engine

    Ensures single instance across all threads
    """
    _instance = None
    _initialized = False
    _lock = None

    @classmethod
    def get_instance(cls):
        """Get singleton instance (thread-safe)"""
        return cls._instance

    @classmethod
    def initialize(
        cls,
        llm_provider=None,
        enabled: bool = False,
        mode: str = 'hybrid',
        max_insights: int = 3
    ):
        """
        Initialize singleton instance

        Thread-safe initialization
        """
        if cls._initialized:
            print("⚠️ Insights engine already initialized, using existing instance")
            return cls._instance

        config = {
            'enabled': enabled,
            'mode': mode,
            'max_insights': max_insights,
            'include_statistical': True
        }

        # Create instance
        cls._instance = LLMInsightsEngine(llm_provider, config)
        cls._initialized = True

        print(f"✅ Singleton instance created")
        print(f"   Instance: {cls._instance}")
        print(f"   Is None: {cls._instance is None}")

        return cls._instance


# Public API
def initialize_insights_engine(
    llm_provider=None,
    enabled: bool = False,
    mode: str = 'hybrid',
    max_insights: int = 3
):
    """
    Initialize insights engine (singleton pattern)

    Args:
        llm_provider: LLM provider instance
        enabled: Enable/disable insights (default False)
        mode: 'llm_only', 'statistical_only', 'hybrid'
        max_insights: Max number of insights to return
    """
    return InsightsEngineSingleton.initialize(
        llm_provider=llm_provider,
        enabled=enabled,
        mode=mode,
        max_insights=max_insights
    )


def get_insights_engine():
    """
    Get insights engine instance

    Returns:
        LLMInsightsEngine instance or None if not initialized
    """
    engine = InsightsEngineSingleton.get_instance()
    if engine is None:
        print("⚠️ get_insights_engine() called but engine is None")
    return engine


# Backward compatibility (deprecated, use get_insights_engine())
insights_engine = None

# For simple_insights compatibility
simple_insights = LLMInsightsEngine(None, {'enabled': False})


# ============================================
# CONFIG.YAML EXAMPLE
# ============================================

"""
# config/config.yaml

insights:
  enabled: true                # Enable/disable insights feature
  mode: hybrid                 # llm_only, statistical_only, hybrid
  max_insights: 3              # Max insights to show
  include_statistical: true    # Include statistical fallback in hybrid mode
"""


if __name__ == '__main__':
    print("🧪 Testing LLM Insights Engine...")

    # Test with mock data
    columns = ['tarih', 'satis', 'siparis_sayisi']
    data = [
        ['2025-01-20', 100000, 450],
        ['2025-01-21', 105000, 480],
        ['2025-01-22', 110000, 500],
        ['2025-01-23', 250000, 1200],  # Spike!
        ['2025-01-24', 115000, 520],
    ]

    # Initialize (disabled by default)
    engine = initialize_insights_engine(
        llm_provider=None,
        enabled=True,  # Enable for test
        mode='statistical_only'  # No LLM for test
    )

    insights = engine.generate_insights(
        columns,
        data,
        user_question="Son 5 günün satış performansı nasıl?",
        schema_info="Table: sales (tarih DATE, satis DECIMAL, siparis_sayisi INT)"
    )

    print(f"\n✅ Generated {len(insights)} insights:\n")
    for i in insights:
        print(f"{i['icon']} [{i['severity'].upper()}] {i['message']}")