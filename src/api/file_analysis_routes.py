"""
File Analysis Routes
Handles widget file uploads, LLM-powered anomaly detection, and scheduled auto-deletion.
"""

import asyncio
import os
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/file-analysis", tags=["file-analysis"])

# In-memory job registry: file_id -> job dict
_jobs: Dict[str, dict] = {}


def _fa_config() -> dict:
    try:
        from src.core.config_manager_enhanced import config_manager
        return config_manager.get_config().get('file_analysis', {})
    except Exception:
        return {}


async def _auto_delete(file_id: str, file_path: str, delay_seconds: int):
    await asyncio.sleep(delay_seconds)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
        _jobs.pop(file_id, None)
        print(f"🗑️  Auto-deleted file [{file_id}]: {file_path}")
    except Exception as exc:
        print(f"⚠️  Auto-delete failed [{file_id}]: {exc}")


async def _run_llm_analysis(file_id: str, content: str, props: dict, template_id: Optional[str]):
    job = _jobs.get(file_id)
    if not job:
        return
    job['status'] = 'analyzing'
    try:
        from src.core.file_anomaly_detector import build_anomaly_prompt, parse_anomaly_response
        from src.core.provider_factory import ProviderFactory
        from src.core.config_manager_enhanced import config_manager

        cfg = config_manager.get_config()
        llm = ProviderFactory.create_llm_provider(cfg)

        prompt = build_anomaly_prompt(
            file_name=props['name'],
            file_size=props['size_bytes'],
            total_lines=props['total_lines'],
            file_type=props['file_type'],
            code_content=content,
            props=props,
            template_id=template_id,
        )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: llm.generate_chat_response(prompt, "")
        )

        anomalies = parse_anomaly_response(response)
        job['status'] = 'done'
        job['result'] = anomalies
        print(f"✅ File analysis done [{file_id}] template={template_id or 'auto'}: {len(anomalies)} anomaly(ies)")

    except Exception as exc:
        import traceback
        traceback.print_exc()
        job['status'] = 'error'
        job['result'] = [{
            'type': 'quality', 'icon': '⚠️', 'severity': 'low',
            'line': None, 'message': f'Analysis failed: {exc}', 'detail': '',
        }]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/templates")
async def list_templates():
    """Return all available anomaly detection templates (without raw prompt text)."""
    from src.core.file_anomaly_detector import get_templates
    return JSONResponse(get_templates())


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    template_id: Optional[str] = Form(default=None),
):
    """
    Upload a file for anomaly analysis.
    - Returns file props and the resolved template immediately.
    - Kicks off background LLM analysis.
    - File is auto-deleted after the configured minutes.

    Pass `template_id` to override auto-detection.
    """
    fa_cfg = _fa_config()
    if not fa_cfg.get('enabled', False):
        raise HTTPException(status_code=404, detail="File analysis is disabled in config")

    upload_path = fa_cfg.get('upload_path', 'uploads/widget_files')
    auto_delete_minutes = int(fa_cfg.get('auto_delete_minutes', 10))

    Path(upload_path).mkdir(parents=True, exist_ok=True)

    content_bytes = await file.read()

    max_bytes = int(fa_cfg.get('max_file_size_mb', 5)) * 1024 * 1024
    if len(content_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {len(content_bytes) / 1024 / 1024:.1f} MB. Maximum allowed size is {max_bytes // 1024 // 1024} MB.",
        )

    content_str = content_bytes.decode('utf-8', errors='replace')

    file_id = str(uuid.uuid4())
    save_path = os.path.join(upload_path, f"{file_id}_{file.filename}")
    with open(save_path, 'wb') as fh:
        fh.write(content_bytes)

    from src.core.file_anomaly_detector import extract_file_props, resolve_template, get_templates
    props = extract_file_props(
        file_name=file.filename or 'file.txt',
        content=content_str,
        content_bytes=len(content_bytes),
    )

    # Resolve which template will be used and return it to the client
    resolved = resolve_template(file.filename or 'file.txt', template_id)
    # Strip raw prompt from response — client only needs metadata
    resolved_meta = {k: v for k, v in resolved.items() if k != 'prompt'}

    _jobs[file_id] = {
        'status': 'pending',
        'props': props,
        'result': None,
        'file_path': save_path,
        'uploaded_at': datetime.utcnow().isoformat() + 'Z',
        'auto_delete_minutes': auto_delete_minutes,
        'template_id': resolved['id'],
    }

    asyncio.create_task(_run_llm_analysis(file_id, content_str, props, resolved['id']))
    asyncio.create_task(_auto_delete(file_id, save_path, auto_delete_minutes * 60))

    return JSONResponse({
        'file_id': file_id,
        'props': props,
        'template': resolved_meta,
        'status': 'analyzing',
        'auto_delete_minutes': auto_delete_minutes,
    })


@router.get("/result/{file_id}")
async def get_analysis_result(file_id: str):
    """Poll for anomaly analysis result."""
    job = _jobs.get(file_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or file already deleted")
    return JSONResponse({
        'file_id': file_id,
        'status': job['status'],
        'props': job['props'],
        'result': job.get('result'),
        'template_id': job.get('template_id'),
        'auto_delete_minutes': job.get('auto_delete_minutes'),
        'uploaded_at': job.get('uploaded_at'),
    })
