from __future__ import annotations
import json, re
from typing import Any
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import ORJSONResponse, FileResponse
from .data_store import DataStore
from .indicators import catalog_payload
from .models import BacktestRequest, PreviewRequest, SaveStrategyRequest, AiStrategyPromptRequest, ResearchSweepRequest, AblationRequest, TrendDiscoveryRequest, ArchiveSyncRequest, ExecutionReplayRequest, HoldoutResearchRequest, FuturesValidationRequest
from .engine import run_backtest, chart_payload
from .jobs import jobs
from .config import project_root, result_root
from .analysis import build_analysis, build_analysis_package
from .ai_prompt import build_strategy_prompt
from .futures_validation import run_futures_validation
from .research import run_sweep, run_ablation, list_results, run_execution_replay, run_holdout
from .trend_discovery import run_trend_discovery
from .archive_sync import plan_archive_sync, ensure_archive_data
from .storage import storage_usage, save_settings, optimize_existing, cleanup_unpinned, pin_run, iter_csv_any

app = FastAPI(title='BTC Strategy Lab', version='15.1.0', default_response_class=ORJSONResponse)

@app.get('/api/health')
def health():
    return {'ok': True, 'version': '15.1.0', 'project_root': str(project_root())}

@app.get('/api/datasets')
def datasets():
    return DataStore().list_payload()

@app.get('/api/archive')
def archive():
    return DataStore().archive_payload()



@app.post('/api/archive/plan')
def archive_plan(req: ArchiveSyncRequest):
    try:
        return plan_archive_sync(req.start, req.end)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(400, str(exc))


@app.post('/api/archive/sync')
def archive_sync(req: ArchiveSyncRequest):
    jid = jobs.create(lambda progress: ensure_archive_data(req.start, req.end, progress))
    return {'job_id': jid}

@app.get('/api/storage')
def storage_status():
    return storage_usage()


@app.post('/api/storage/settings')
def update_storage_settings(payload: dict[str, Any]):
    try:
        return save_settings(payload)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc))


@app.post('/api/storage/optimize')
def optimize_storage():
    jid = jobs.create(lambda progress: optimize_existing(progress))
    return {'job_id': jid}


@app.post('/api/storage/cleanup')
def cleanup_storage(payload: dict[str, Any] | None = None):
    dry_run = bool((payload or {}).get('dry_run', False))
    return cleanup_unpinned(dry_run=dry_run)


@app.post('/api/storage/results/{run_id}/pin')
def set_result_pin(run_id: str, payload: dict[str, Any]):
    try:
        return pin_run(run_id, bool(payload.get('pinned', True)))
    except FileNotFoundError:
        raise HTTPException(404, 'Backtest result not found')


@app.get('/api/indicators')
def indicators():
    return catalog_payload()

@app.post('/api/chart/preview')
def preview(req: PreviewRequest):
    try:
        return chart_payload(req)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))



@app.post('/api/backtests')
def start_backtest(req: BacktestRequest):
    jid = jobs.create(lambda progress: run_backtest(req, progress))
    return {'job_id': jid}

@app.get('/api/backtests/{job_id}')
def get_job(job_id: str):
    try:
        return jobs.get(job_id)
    except KeyError:
        raise HTTPException(404, 'Unknown job')

@app.post('/api/backtests/{job_id}/cancel')
def cancel_job(job_id: str):
    try:
        return jobs.cancel(job_id)
    except KeyError:
        raise HTTPException(404, 'Unknown job')

@app.get('/api/results/{run_id}/decisions')
def decisions(
    run_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(250, ge=1, le=2000),
    direction: str | None = None,
    kind: str | None = None,
    passed: bool | None = None,
):
    base = result_root().resolve()
    path = (base / run_id / 'decision_events.csv').resolve()
    gz = Path(str(path) + '.gz')
    if base not in path.parents or (not path.exists() and not gz.exists()):
        raise HTTPException(404, 'Decision log not retained for this run (COMPACT storage or deleted artifact)')
    rows = []
    matched = 0
    for row in iter_csv_any(path):
        if direction and row.get('direction') != direction:
            continue
        if kind and row.get('kind') != kind:
            continue
        if passed is not None and (str(row.get('passed', '')).lower() == 'true') != passed:
            continue
        if matched >= offset and len(rows) < limit:
            rows.append(row)
        matched += 1
    return {'rows': rows, 'total': matched, 'offset': offset, 'limit': limit}

@app.post('/api/strategies/validate')
def validate_strategy(req: SaveStrategyRequest):
    # Pydantic has already validated nested rules, ranges, and chart-only usage.
    return {'valid': True, 'strategy': req.strategy.model_dump()}

@app.post('/api/strategies/save')
def save_strategy(req: SaveStrategyRequest):
    target = project_root() / 'strategy-lab' / 'strategies'
    target.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r'[^a-zA-Z0-9_-]+', '-', req.strategy.name).strip('-').lower() or 'strategy'
    path = target / f'{slug}.strategy.json'
    payload = {'schema_version': 15, 'app': 'BTC Strategy Lab', 'strategy': req.strategy.model_dump()}
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    return {'path': str(path), 'payload': payload}


@app.get('/api/strategies')
def list_strategies():
    root = project_root() / 'strategy-lab' / 'strategies'
    root.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(root.glob('*.strategy.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            strategy = payload.get('strategy', payload)
            items.append({
                'id': path.stem.replace('.strategy', ''),
                'name': str(strategy.get('name') or path.stem),
                'path': str(path),
                'modified_at': path.stat().st_mtime,
            })
        except Exception:
            continue
    return items


@app.get('/api/strategies/{strategy_id}')
def load_strategy(strategy_id: str):
    root = project_root() / 'strategy-lab' / 'strategies'.resolve()
    safe = re.sub(r'[^a-zA-Z0-9_-]+', '', strategy_id)
    candidates = [root / f'{safe}.strategy.json', root / f'{safe}.json']
    path = next((p for p in candidates if p.exists()), None)
    if not path:
        raise HTTPException(404, 'Saved strategy not found')
    payload = json.loads(path.read_text(encoding='utf-8'))
    strategy_raw = payload.get('strategy', payload)
    # Validate/migrate through Pydantic before returning project files to the UI.
    from .models import StrategyConfig
    strategy = StrategyConfig.model_validate(strategy_raw)
    return {'id': safe, 'path': str(path), 'strategy': strategy.model_dump(), 'payload': payload}


@app.post('/api/ai/strategy-prompt')
def ai_strategy_prompt(req: AiStrategyPromptRequest):
    return {'prompt': build_strategy_prompt(req)}

@app.get('/api/results/{run_id}/analysis')
def analysis(run_id: str):
    try:
        return build_analysis(run_id)
    except FileNotFoundError:
        raise HTTPException(404, 'Backtest result not found')

@app.get('/api/results/{run_id}/analysis-package')
def analysis_package(run_id: str):
    try:
        path = build_analysis_package(run_id)
    except FileNotFoundError:
        raise HTTPException(404, 'Backtest result not found')
    return FileResponse(path, filename=path.name, media_type='application/zip')


@app.post('/api/research/sweep')
def research_sweep(req: ResearchSweepRequest):
    jid = jobs.create(lambda progress: run_sweep(req, progress))
    return {'job_id': jid}


@app.post('/api/research/execution-replay')
def execution_replay(req: ExecutionReplayRequest):
    jid = jobs.create(lambda progress: run_execution_replay(req, progress))
    return {'job_id': jid}


@app.post('/api/research/holdout')
def research_holdout(req: HoldoutResearchRequest):
    jid = jobs.create(lambda progress: run_holdout(req, progress))
    return {'job_id': jid}


@app.post('/api/research/futures-validation')
def futures_validation(req: FuturesValidationRequest):
    jid = jobs.create(lambda progress: run_futures_validation(req, progress))
    return {'job_id': jid}


@app.post('/api/research/ablation')
def research_ablation(req: AblationRequest):
    jid = jobs.create(lambda progress: run_ablation(req, progress))
    return {'job_id': jid}

@app.post('/api/research/trend-discovery')
def research_trend_discovery(req: TrendDiscoveryRequest):
    jid = jobs.create(lambda progress: run_trend_discovery(req, progress))
    return {'job_id': jid}


@app.get('/api/results')
def results_list(limit: int = Query(100, ge=1, le=500)):
    return list_results(limit)
