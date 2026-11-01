from functools import lru_cache
from typing import Literal
import asyncio
import time
from threading import BoundedSemaphore

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .llm import OllamaError
from .service import Assistant
from .data import load_courses, quality_report
from .settings import ROOT
from .deadline import ResponseDeadlineExceeded

app = FastAPI(title='SCU Data Science Course Assistant', version='0.3.0')
FRONTEND = ROOT / 'frontend'
app.mount('/assets', StaticFiles(directory=str(FRONTEND / 'assets')), name='assets')
runtime = {'started': False, 'ready': False, 'error': None}
query_slot = BoundedSemaphore(1)


def prepare_models():
    try:
        bot = assistant()
        bot.index.encoder
        bot.index.collection()
        bot.llm.warmup()
        runtime.update(ready=True, error=None)
    except Exception as exc:
        runtime.update(ready=False, error=str(exc))


@app.on_event('startup')
async def preload_models():
    runtime.update(started=True, ready=False, error=None)
    app.state.warmup_task = asyncio.create_task(asyncio.to_thread(prepare_models))


@app.get('/', include_in_schema=False)
def frontend():
    return FileResponse(FRONTEND / 'index.html', headers={'Cache-Control': 'no-cache'})


@app.get('/catalog')
def catalog():
    courses = load_courses()
    return dict(quality_report(), teachers=sorted({row['teacher'] for row in courses if row['teacher'] != '未知'}))


@lru_cache
def assistant() -> Assistant:
    return Assistant()


class Message(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=2000)


class SearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    semester: str | None = Field(default=None, pattern=r'^\d{3}-[12]$')
    source: Literal['course', 'professor'] | None = None
    teacher: str | None = Field(default=None, max_length=50)
    top_k: int = Field(default=4, ge=1, le=8)


class ChatRequest(SearchRequest):
    history: list[Message] = Field(default_factory=list, max_length=6)


@app.get('/health')
def health():
    if runtime['started'] and not runtime['ready']:
        return JSONResponse(status_code=503, content={'ready': False, 'warming_up': not runtime['error'],
            'model': assistant().settings.model, 'warmup_error': runtime['error']})
    status = assistant().health()
    status['response_deadline_seconds'] = assistant().settings.response_deadline
    status['llm_deadline_seconds'] = assistant().settings.llm_deadline
    return JSONResponse(status_code=200 if status['ready'] else 503, content=status)


@app.get('/models')
def models():
    try:
        return {'selected': assistant().settings.model, 'models': assistant().llm.models()}
    except OllamaError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post('/search')
def search(request: SearchRequest):
    if not request.question.strip():
        raise HTTPException(422, '問題不可為空白。')
    try:
        return {'sources': assistant().retrieve(**request.model_dump())}
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post('/chat')
async def chat(request: ChatRequest):
    started = time.monotonic()
    bot = assistant()
    payload = request.model_dump()
    if not request.question.strip():
        raise HTTPException(422, '問題不可為空白。')
    total_budget = bot.settings.response_deadline
    # Reserve time for a JSON-only fallback and delivering the response.
    llm_budget = min(bot.settings.llm_deadline, total_budget * .85)

    def timed(result):
        result['timing'] = {'response_ms': round((time.monotonic() - started) * 1000),
                            'deadline_ms': round(total_budget * 1000),
                            'llm_deadline_ms': round(llm_budget * 1000)}
        return result

    async def fallback(reason):
        try:
            budget = max(.001, total_budget - (time.monotonic() - started))
            result = await asyncio.wait_for(asyncio.to_thread(bot.fallback, **payload, reason=reason), timeout=budget)
            return timed(result)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except asyncio.TimeoutError as exc:
            raise HTTPException(504, 'Local source lookup exceeded the response deadline. Please try again.') from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(503, 'Local source data could not be read. Please check the data files.') from exc

    if runtime['started'] and not runtime['ready']:
        # If Ollama was closed during startup, allow a later user query to
        # trigger preparation again after they reopen it; do not stay stuck.
        if runtime['error']:
            task = getattr(app.state, 'warmup_task', None)
            if task is None or task.done():
                runtime.update(error=None)
                app.state.warmup_task = asyncio.create_task(asyncio.to_thread(prepare_models))
        return await fallback('model_warming')
    slot = query_slot
    if not slot.acquire(blocking=False):
        return await fallback('model_busy')
    deadline = started + llm_budget
    def work():
        try:
            return bot.ask(**payload, deadline=deadline)
        finally:
            # Keep the slot until the worker really exits, even if the HTTP
            # deadline expires first. This prevents a growing model queue.
            slot.release()
    try:
        task = asyncio.create_task(asyncio.to_thread(work))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        result = await asyncio.wait_for(asyncio.shield(task), timeout=max(.001, deadline - time.monotonic()))
        if result.get('mode') == 'verification_failed':
            return await fallback('verification_failed')
        return timed(result)
    except (asyncio.TimeoutError, ResponseDeadlineExceeded):
        return await fallback('llm_timeout')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OllamaError:
        return await fallback('model_unavailable')
    except RuntimeError:
        return await fallback('retrieval_unavailable')


@app.get('/courses/ranking')
def ranking(semester: str | None = Query(default=None, pattern=r'^\d{3}-[12]$'),
            teacher: str | None = Query(default=None, max_length=50),
            limit: int = Query(default=5, ge=1, le=20), direction: Literal['asc', 'desc'] = 'desc',
            min_average: float | None = Query(default=None, ge=0, le=100)):
    return {'courses': assistant().rank(semester, teacher, limit, direction, min_average),
            'note': '缺少平均成績的課程未列入；歷史平均不能保證未來成績。'}
