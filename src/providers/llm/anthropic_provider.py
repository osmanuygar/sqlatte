"""
Anthropic Claude LLM Provider
"""

import anthropic
from typing import Tuple, Dict
from src.core.llm_provider import LLMProvider


class AnthropicProvider(LLMProvider):
    """Anthropic Claude LLM provider implementation"""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get('api_key')
        self.model = config.get('model', 'claude-sonnet-4-20250514')
        self.max_tokens = config.get('max_tokens', 1000)
        
        if not self.api_key:
            raise ValueError("Anthropic API key is required")
        
        self.client = anthropic.Anthropic(api_key=self.api_key)
    
    def determine_intent(self, question: str, schema_info: str) -> Dict[str, any]:
        """
        Determine if the question requires SQL or is general chat
        
        Returns:
            {
                "intent": "sql" or "chat",
                "confidence": 0.0-1.0,
                "reasoning": "explanation"
            }
        """
        prompt = f"""Analyze this user question and determine if it requires a SQL query or is general conversation.

Available Tables Schema:
{schema_info if schema_info and schema_info != "No schema provided." else "No tables selected"}

User Question: {question}

Rules:
1. If question asks about data, analytics, or queries related to the available tables → intent: "sql"
2. If question is greeting, general chat, help, or unrelated to tables → intent: "chat"
3. If tables are not selected but question seems like SQL query → intent: "chat" (explain they need to select tables)

Respond in this exact format:
INTENT: sql or chat
CONFIDENCE: 0.0 to 1.0
REASONING: brief explanation
"""

        message = self.client.messages.create(
            model=self.model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text
        
        # Parse response
        intent = "chat"  # default
        confidence = 0.5
        reasoning = ""
        
        for line in response_text.split('\n'):
            if line.startswith('INTENT:'):
                intent = line.split(':', 1)[1].strip().lower()
            elif line.startswith('CONFIDENCE:'):
                try:
                    confidence = float(line.split(':', 1)[1].strip())
                except:
                    confidence = 0.5
            elif line.startswith('REASONING:'):
                reasoning = line.split(':', 1)[1].strip()
        
        return {
            "intent": intent,
            "confidence": confidence,
            "reasoning": reasoning
        }
    
    def generate_chat_response(self, question: str, context: str = "") -> str:
        """
        Generate conversational response (non-SQL)
        
        Args:
            question: User's question
            context: Optional context (e.g., available tables)
            
        Returns:
            Chat response
        """
        system_prompt = """You are SQLatte ☕ - a friendly AI assistant that helps users query their databases with natural language.

Your personality:
- Helpful and friendly, like a barista serving the perfect drink
- Knowledgeable about SQL and databases
- Can have casual conversations too
- Use coffee/brewing metaphors occasionally when appropriate

When users ask general questions (not about data):
- Respond naturally and helpfully
- If they seem lost, guide them on how to use SQLatte
- Be concise but friendly
"""

        user_message = question
        if context and context != "No schema provided.":
            user_message = f"Available context:\n{context}\n\nUser question: {question}"
        
        message = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}]
        )
        
        return message.content[0].text
    
    def generate_sql(self, question: str, schema_info: str) -> Tuple[str, str]:
        """Generate SQL query using Claude"""
        
        prompt = f"""You are a SQL expert. Generate a SQL query based on the user's question.

Table Schema(s):
{schema_info}

User Question: {question}

Rules:
1. Generate ONLY valid SQL syntax
2. If multiple tables are provided, use appropriate JOINs
3. Infer JOIN conditions from table relationships (common column names)
4. Use table aliases for readability (e.g., orders o, customers c)
5. Include LIMIT clause for safety (default 100 rows)
6. For aggregations, use GROUP BY appropriately
7. Use explicit JOIN syntax (INNER JOIN, LEFT JOIN, etc.)
⚡ PERFORMANCE OPTIMIZATION (CRITICAL):
8. **PARTITION COLUMN**: If schema contains a 'dt' column (VARCHAR format YYYYMMDD, e.g., '20251218'), this is a PARTITION KEY
   - ALWAYS add WHERE clause with 'dt' filter when possible
   - Date filters MUST use dt column in format: dt = '20251218' or dt BETWEEN '20251201' AND '20251218'
   - For "recent", "latest", "today" queries → use last 7-30 days: dt >= '20251201'
   - For "yesterday" → use dt = '20251218' (current date - 1)
   - For specific date range → convert to dt format (e.g., "last week" → dt >= '20251211')
   - ⚠️ NEVER query without dt filter unless explicitly asked for "all time" data
9. If 'datetime' column exists alongside 'dt', use 'dt' for filtering (faster) and 'datetime' for display
10. Example optimized query: 
    SELECT * FROM orders WHERE dt >= '20251201' AND status = 'completed' LIMIT 100
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')  -> Yesterday's dt=yesterday 
Format your response as:
SQL:
```sql
[your SQL query here]
```

EXPLANATION:
[brief explanation including JOIN strategy if applicable]
"""

        message = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text
        
        # Extract SQL
        sql_query = ""
        explanation = ""
        
        if "```sql" in response_text:
            parts = response_text.split("```sql")
            if len(parts) > 1:
                sql_query = parts[1].split("```")[0].strip()
        
        if "EXPLANATION:" in response_text:
            explanation = response_text.split("EXPLANATION:")[1].strip()
        elif "Explanation:" in response_text:
            explanation = response_text.split("Explanation:")[1].strip()
        else:
            explanation = "Query generated from natural language"
        
        if not sql_query:
            lines = response_text.split('\n')
            sql_lines = [line for line in lines if any(kw in line.upper() 
                        for kw in ['SELECT', 'FROM', 'WHERE'])]
            sql_query = '\n'.join(sql_lines)
        
        return sql_query.strip(), explanation.strip()
    
    def get_model_name(self) -> str:
        """Get the model name"""
        return self.model
    
    def health_check(self) -> bool:
        """Check if Anthropic API is accessible"""
        try:
            # Simple ping test
            message = self.client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": "user", "content": "Hello"}]
            )
            return True
        except Exception:
            return False
