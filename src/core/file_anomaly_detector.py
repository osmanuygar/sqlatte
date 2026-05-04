"""
File Anomaly Detector
Analyzes uploaded files using format-aware LLM prompt templates.

Templates are stored in TEMPLATE_REGISTRY — a plain list of dicts that can
later be loaded from a database or config file without changing any other code.
"""

import csv
import io
import json
import re
from typing import Any, Dict, List, Optional


# ── Template Registry ─────────────────────────────────────────────────────────
# Each entry is a self-contained template descriptor.
# The 'prompt' field is the actual LLM prompt (supports .format(**kwargs)).
# Future: load from DB / config and merge with this default list.

TEMPLATE_REGISTRY: List[Dict[str, Any]] = [
    {
        'id':          'code',
        'name':        'Code / Widget',
        'icon':        '🧩',
        'file_types':  ['.js', '.ts', '.jsx', '.tsx', '.mjs'],
        'description': 'Analyzes JavaScript/TypeScript widget and source files.',
        'checks': [
            'Security vulnerabilities (XSS, eval, dangerous DOM APIs)',
            'Suspicious network calls and data exfiltration',
            'Auth anomalies (insecure token storage, session leaks)',
            'Code quality issues (obfuscation, dead code)',
            'Undocumented API endpoints',
        ],
        'anomaly_types': 'security|network|auth|quality|api',
        'prompt': """\
You are a security analyst specialized in JavaScript/TypeScript widget code analysis.

File: {file_name}  |  Size: {file_size} bytes  |  Lines: {total_lines}

Code sample ({sample_lines} lines):
{code_sample}

Detect:
1. Security vulnerabilities (XSS, eval, dangerous DOM APIs, credential exposure)
2. Suspicious network calls (unexpected endpoints, data exfiltration)
3. Authentication anomalies (insecure token storage, session leaks)
4. Code quality issues (obfuscation, dead code, unusually large functions)
5. API anomalies (undocumented endpoints, excessive third-party data transfer)

Respond ONLY with a JSON array:
```json
[{{"type":"security|network|auth|quality|api","icon":"🔒|🌐|🔑|⚠️|🔌","severity":"low|medium|high|critical","line":<int|null>,"message":"<max 150 chars>","detail":"<optional>"}}]
```
JSON:""",
    },
    {
        'id':          'data',
        'name':        'Tabular Data',
        'icon':        '📊',
        'file_types':  ['.csv', '.tsv', '.vy'],
        'description': 'Analyzes CSV, TSV, and VY delimited data files for quality issues.',
        'checks': [
            'Missing or null values in critical columns',
            'Duplicate rows or keys',
            'Inconsistent data types within a column',
            'Statistical outliers',
            'Encoding or formatting issues',
            'Unexpected column counts per row',
        ],
        'anomaly_types': 'missing|duplicate|type_mismatch|outlier|encoding|schema',
        'prompt': """\
You are a data quality analyst. Analyze the following delimited data file for anomalies.

File: {file_name}  |  Size: {file_size} bytes  |  Rows: {total_lines}
Delimiter: {delimiter}  |  Columns ({col_count}): {columns}

Data sample:
{code_sample}

Detect:
1. Missing or null values in critical columns
2. Duplicate rows or keys
3. Inconsistent data types within a column
4. Statistical outliers (values far outside the normal range)
5. Encoding or formatting issues (garbled text, mixed separators)
6. Schema anomalies (unexpected column count per row)

Respond ONLY with a JSON array:
```json
[{{"type":"missing|duplicate|type_mismatch|outlier|encoding|schema","icon":"🔍|♻️|🔢|📊|🔤|📋","severity":"low|medium|high|critical","line":<int|null>,"message":"<max 150 chars>","detail":"<optional>"}}]
```
JSON:""",
    },
    {
        'id':          'json',
        'name':        'JSON',
        'icon':        '{ }',
        'file_types':  ['.json', '.jsonl', '.ndjson'],
        'description': 'Analyzes JSON files for schema issues, sensitive data, and bloat.',
        'checks': [
            'Missing required fields or unexpected nulls',
            'Schema inconsistencies (mixed types for the same key)',
            'Sensitive data exposed (passwords, tokens, PII)',
            'Deeply nested structures (performance risk)',
            'Large arrays or strings (data bloat)',
        ],
        'anomaly_types': 'missing|schema|security|performance|bloat',
        'prompt': """\
You are a data quality and security analyst. Analyze the following JSON file.

File: {file_name}  |  Size: {file_size} bytes  |  Lines: {total_lines}

Content sample:
{code_sample}

Detect:
1. Missing required fields or unexpected nulls
2. Schema inconsistencies (mixed types for the same key)
3. Sensitive data exposed (passwords, tokens, PII)
4. Deeply nested structures that may cause performance issues
5. Large arrays or strings that indicate data bloat

Respond ONLY with a JSON array:
```json
[{{"type":"missing|schema|security|performance|bloat","icon":"🔍|📋|🔒|⚡|💾","severity":"low|medium|high|critical","line":<int|null>,"message":"<max 150 chars>","detail":"<optional>"}}]
```
JSON:""",
    },
    {
        'id':          'yaml',
        'name':        'YAML / Config',
        'icon':        '⚙️',
        'file_types':  ['.yaml', '.yml'],
        'description': 'Analyzes YAML configuration files for secrets and misconfigurations.',
        'checks': [
            'Hardcoded secrets, passwords, or API keys',
            'Overly permissive settings',
            'Missing required configuration keys',
            'Deprecated or unsafe directives',
            'Inconsistent indentation or syntax issues',
        ],
        'anomaly_types': 'secret|permission|missing|deprecated|syntax',
        'prompt': """\
You are a DevOps security and configuration analyst. Analyze the following YAML configuration file.

File: {file_name}  |  Size: {file_size} bytes  |  Lines: {total_lines}

Content sample:
{code_sample}

Detect:
1. Hardcoded secrets, passwords, or API keys
2. Overly permissive settings (e.g. allow_all, disable_auth)
3. Missing required configuration keys
4. Deprecated or unsafe directives
5. Inconsistent indentation or YAML syntax issues

Respond ONLY with a JSON array:
```json
[{{"type":"secret|permission|missing|deprecated|syntax","icon":"🔑|🚪|⚠️|🗑️|📝","severity":"low|medium|high|critical","line":<int|null>,"message":"<max 150 chars>","detail":"<optional>"}}]
```
JSON:""",
    },
    {
        'id':          'sql',
        'name':        'SQL',
        'icon':        '🗄️',
        'file_types':  ['.sql'],
        'description': 'Analyzes SQL files for dangerous statements, injection vectors, and performance issues.',
        'checks': [
            'Dangerous DDL/DML (DROP, TRUNCATE, DELETE without WHERE)',
            'SQL injection vectors (dynamic string concatenation)',
            'Missing WHERE clauses on UPDATE/DELETE',
            'Exposed credentials or connection strings',
            'Performance red flags (SELECT *, missing LIMIT)',
        ],
        'anomaly_types': 'dangerous|injection|missing_where|credentials|performance',
        'prompt': """\
You are a database security analyst. Analyze the following SQL file.

File: {file_name}  |  Size: {file_size} bytes  |  Lines: {total_lines}

Content sample:
{code_sample}

Detect:
1. Dangerous write/DDL statements (DROP, TRUNCATE, DELETE without WHERE)
2. SQL injection vectors (dynamic string concatenation)
3. Missing WHERE clauses on UPDATE/DELETE
4. Exposed credentials or connection strings
5. Performance red flags (SELECT *, missing LIMIT, unindexed JOINs)

Respond ONLY with a JSON array:
```json
[{{"type":"dangerous|injection|missing_where|credentials|performance","icon":"💣|🔓|⚠️|🔑|🐢","severity":"low|medium|high|critical","line":<int|null>,"message":"<max 150 chars>","detail":"<optional>"}}]
```
JSON:""",
    },
    {
        'id':          'xml',
        'name':        'XML',
        'icon':        '📄',
        'file_types':  ['.xml', '.svg', '.xsd'],
        'description': 'Analyzes XML files for XXE injection, malformed tags, and schema issues.',
        'checks': [
            'XXE (XML External Entity) injection vectors',
            'Sensitive data in attributes or CDATA sections',
            'Malformed or unclosed tags',
            'Unusually deep nesting (DoS risk)',
            'Namespace or schema inconsistencies',
        ],
        'anomaly_types': 'xxe|security|malformed|nesting|schema',
        'prompt': """\
You are a security and data analyst. Analyze the following XML file.

File: {file_name}  |  Size: {file_size} bytes  |  Lines: {total_lines}

Content sample:
{code_sample}

Detect:
1. XXE (XML External Entity) injection vectors
2. Sensitive data in attributes or CDATA sections
3. Malformed or unclosed tags
4. Unusually deep nesting (DoS risk)
5. Schema or namespace inconsistencies

Respond ONLY with a JSON array:
```json
[{{"type":"xxe|security|malformed|nesting|schema","icon":"🔓|🔒|❌|🌀|📋","severity":"low|medium|high|critical","line":<int|null>,"message":"<max 150 chars>","detail":"<optional>"}}]
```
JSON:""",
    },
    {
        'id':          'text',
        'name':        'Plain Text',
        'icon':        '📋',
        'file_types':  ['.txt'],
        'description': 'General-purpose analysis for any plain text file.',
        'checks': [
            'Sensitive data (passwords, tokens, PII)',
            'Unusual patterns or encoding issues',
            'Structural anomalies',
        ],
        'anomaly_types': 'security|quality|encoding|structure',
        'prompt': """\
You are a data and security analyst. Analyze the following text file for anomalies.

File: {file_name}  |  Size: {file_size} bytes  |  Lines: {total_lines}

Content sample:
{code_sample}

Detect any anomalies: sensitive data, unusual patterns, encoding issues, or structural problems.

Respond ONLY with a JSON array:
```json
[{{"type":"security|quality|encoding|structure","icon":"🔒|⚠️|🔤|📋","severity":"low|medium|high|critical","line":<int|null>,"message":"<max 150 chars>","detail":"<optional>"}}]
```
JSON:""",
    },
]

# Fast lookup by id
_REGISTRY_BY_ID: Dict[str, Dict] = {t['id']: t for t in TEMPLATE_REGISTRY}

# Extension → template id
_EXT_MAP: Dict[str, str] = {}
for _t in TEMPLATE_REGISTRY:
    for _ext in _t['file_types']:
        _EXT_MAP[_ext] = _t['id']


# ── Public API ────────────────────────────────────────────────────────────────

def get_templates(include_prompt: bool = False) -> List[Dict]:
    """Return template registry (without raw prompt by default)."""
    result = []
    for t in TEMPLATE_REGISTRY:
        entry = {k: v for k, v in t.items() if k != 'prompt'}
        if include_prompt:
            entry['prompt'] = t['prompt']
        result.append(entry)
    return result


def resolve_template(file_name: str, template_id: Optional[str] = None) -> Dict:
    """Return the template to use for a given file, with optional override."""
    if template_id and template_id in _REGISTRY_BY_ID:
        return _REGISTRY_BY_ID[template_id]
    ext = _ext(file_name)
    tid = _EXT_MAP.get(ext, 'text')
    return _REGISTRY_BY_ID.get(tid, _REGISTRY_BY_ID['text'])


def file_category(file_name: str) -> str:
    return resolve_template(file_name)['id']


def build_anomaly_prompt(
    file_name: str,
    file_size: int,
    total_lines: int,
    file_type: str,
    code_content: str,
    props: Optional[Dict] = None,
    template_id: Optional[str] = None,
    sample_lines: int = 200,
) -> str:
    template = resolve_template(file_name, template_id)
    lines = code_content.split('\n')
    sample = '\n'.join(lines[:sample_lines])

    fmt_args: Dict[str, Any] = dict(
        file_name=file_name,
        file_size=file_size,
        total_lines=total_lines,
        code_sample=sample,
        sample_lines=min(sample_lines, total_lines),
    )

    if template['id'] == 'data' and props:
        fmt_args['delimiter'] = props.get('delimiter', "','")
        fmt_args['col_count'] = props.get('col_count', '?')
        fmt_args['columns']   = ', '.join(str(c) for c in (props.get('columns') or []))

    return template['prompt'].format(**fmt_args)


def parse_anomaly_response(response: str) -> List[Dict]:
    cleaned = re.sub(r'```(?:json)?\s*', '', response).strip().rstrip('`').strip()
    match = re.search(r'\[.*\]', cleaned, re.DOTALL)
    if not match:
        return []
    try:
        items = json.loads(match.group())
        result = []
        for item in items:
            if not isinstance(item, dict) or 'message' not in item:
                continue
            result.append({
                'type':     item.get('type', 'quality'),
                'icon':     item.get('icon', '⚠️'),
                'severity': item.get('severity', 'low'),
                'line':     item.get('line'),
                'message':  str(item.get('message', ''))[:200],
                'detail':   str(item.get('detail', '')),
            })
        return result
    except (json.JSONDecodeError, ValueError):
        return []


# ── Props extraction ──────────────────────────────────────────────────────────

def extract_file_props(file_name: str, content: str, content_bytes: int) -> Dict[str, Any]:
    category = file_category(file_name)
    base = {
        'name':        file_name,
        'size_bytes':  content_bytes,
        'size_human':  _format_size(content_bytes),
        'total_lines': len(content.split('\n')),
        'file_type':   _mime(file_name),
        'category':    category,
    }
    if category == 'code':
        base.update(_props_code(content))
    elif category == 'data':
        base.update(_props_data(content))
    elif category == 'json':
        base.update(_props_json(content))
    elif category == 'sql':
        base.update(_props_sql(content))
    return base


def _props_code(content: str) -> Dict:
    return {
        'function_count':     len(re.findall(r'\bfunction\b|=>\s*\{', content)),
        'network_calls':      len(re.findall(r'\bfetch\s*\(|\bXMLHttpRequest\b|\.ajax\s*\(', content)),
        'dangerous_patterns': len(re.findall(r'\beval\s*\(|\bnew\s+Function\s*\(|document\.write\s*\(', content)),
        'sample_endpoints':   list(dict.fromkeys(re.findall(r"['\"`](/[\w\-/{}:]+)['\"`]", content)))[:10],
    }


def _props_data(content: str) -> Dict:
    delimiter = _detect_delimiter(content)
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    rows = list(reader)
    header    = rows[0] if rows else []
    data_rows = rows[1:] if len(rows) > 1 else []
    null_count = sum(
        1 for row in data_rows for cell in row
        if cell.strip() == '' or cell.strip().lower() in ('null', 'none', 'na', 'n/a', '#n/a')
    )
    dupe_count = len(data_rows) - len({tuple(r) for r in data_rows})
    return {
        'delimiter':  repr(delimiter),
        'col_count':  len(header),
        'columns':    header[:20],
        'row_count':  len(data_rows),
        'null_count': null_count,
        'dupe_count': dupe_count,
    }


def _props_json(content: str) -> Dict:
    try:
        obj = json.loads(content)
        return {
            'top_keys':     list(obj.keys())[:10] if isinstance(obj, dict) else [],
            'is_array':     isinstance(obj, list),
            'array_length': len(obj) if isinstance(obj, list) else None,
        }
    except Exception:
        return {'parse_error': True}


def _props_sql(content: str) -> Dict:
    u = content.upper()
    return {
        'select_count':   len(re.findall(r'\bSELECT\b', u)),
        'insert_count':   len(re.findall(r'\bINSERT\b', u)),
        'update_count':   len(re.findall(r'\bUPDATE\b', u)),
        'delete_count':   len(re.findall(r'\bDELETE\b', u)),
        'drop_count':     len(re.findall(r'\bDROP\b', u)),
        'truncate_count': len(re.findall(r'\bTRUNCATE\b', u)),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ext(file_name: str) -> str:
    dot = file_name.rfind('.')
    return file_name[dot:].lower() if dot != -1 else ''


def _detect_delimiter(content: str) -> str:
    sample = '\n'.join(content.splitlines()[:5])
    counts = {d: sample.count(d) for d in [',', '\t', ';', '|']}
    return max(counts, key=counts.get)


def _mime(file_name: str) -> str:
    return {
        '.js': 'text/javascript', '.ts': 'text/typescript',
        '.csv': 'text/csv',       '.tsv': 'text/tab-separated-values',
        '.vy': 'text/vy',
        '.json': 'application/json', '.jsonl': 'application/jsonl',
        '.yaml': 'text/yaml',    '.yml': 'text/yaml',
        '.sql': 'text/sql',      '.xml': 'text/xml',
    }.get(_ext(file_name), 'text/plain')


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:    return f"{size_bytes} B"
    if size_bytes < 1024**2: return f"{size_bytes/1024:.1f} KB"
    return f"{size_bytes/1024**2:.1f} MB"
