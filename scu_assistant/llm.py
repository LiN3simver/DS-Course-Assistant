import httpx
from threading import local

from .settings import Settings


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._metrics = local()

    @property
    def last_metrics(self):
        return getattr(self._metrics, 'value', {})

    def warmup(self):
        self._request('POST', '/api/generate', json={'model': self.settings.model, 'prompt': '',
            'keep_alive': self.settings.keep_alive, 'options': {'num_ctx': self.settings.num_ctx}}, timeout=180)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            timeout = kwargs.pop('timeout', self.settings.timeout)
            response = httpx.request(method, self.settings.ollama_url + path,
                timeout=timeout, trust_env=False, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            raise OllamaError('本地模型未能在期限內完成，請縮短問題或稍後重試。') from exc
        except httpx.ConnectError as exc:
            raise OllamaError('無法連線至 Ollama，請先開啟 Ollama 或執行 ollama serve。') from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise OllamaError(f'Ollama 請求失敗：{exc}') from exc

    def models(self) -> list[dict]:
        return self._request('GET', '/api/tags').get('models', [])

    def chat(self, messages: list[dict], schema: dict | None = None,
             max_tokens: int | None = None, timeout: float | None = None) -> str:
        payload = {
            'model': self.settings.model, 'messages': messages, 'stream': False,
            'think': False, 'keep_alive': self.settings.keep_alive,
            'options': {'temperature': 0.1, 'num_ctx': self.settings.num_ctx,
                        'num_predict': max_tokens or self.settings.num_predict},
        }
        if schema:
            payload['format'] = schema
        result = self._request('POST', '/api/chat', json=payload, timeout=timeout or self.settings.timeout)
        self._metrics.value = {key: result.get(key, 0) for key in (
            'load_duration', 'prompt_eval_duration', 'eval_duration', 'prompt_eval_count', 'eval_count')}
        answer = result.get('message', {}).get('content', '').strip()
        if not answer:
            raise OllamaError('模型沒有產生文字回答，請檢查 Ollama 模型是否支援聊天。')
        return answer
