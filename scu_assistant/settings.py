from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')


def project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


@dataclass(frozen=True)
class Settings:
    ollama_url: str = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
    model: str = os.getenv('OLLAMA_MODEL', 'qwen3-vl:4b-instruct')
    timeout: float = float(os.getenv('OLLAMA_TIMEOUT', '180'))
    num_ctx: int = int(os.getenv('OLLAMA_NUM_CTX', '4096'))
    num_predict: int = int(os.getenv('OLLAMA_NUM_PREDICT', '220'))
    response_deadline: float = float(os.getenv('RESPONSE_DEADLINE_SECONDS', '14'))
    llm_deadline: float = float(os.getenv('LLM_DEADLINE_SECONDS', '10'))
    keep_alive: str = os.getenv('OLLAMA_KEEP_ALIVE', '30m')
    embedding_path: Path = project_path(os.getenv('EMBEDDING_MODEL_PATH', '.models/bge-small-zh-v1.5'))
    embedding_device: str = os.getenv('EMBEDDING_DEVICE', 'cpu')
    chroma_path: Path = project_path(os.getenv('CHROMA_PATH', 'chroma_db'))
    collection: str = os.getenv('CHROMA_COLLECTION', 'scu_bge_small_zh_v2')
    min_similarity: float = float(os.getenv('RETRIEVAL_MIN_SIMILARITY', '0.45'))

    def __post_init__(self):
        url = urlparse(self.ollama_url)
        if url.scheme != 'http' or url.hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise ValueError('OLLAMA_BASE_URL 必須是本機 http 位址。')
        if self.num_ctx < 2048 or not 1 <= self.num_predict < self.num_ctx - 512:
            raise ValueError('OLLAMA_NUM_CTX 至少為 2048，且需保留足夠的輸入與輸出空間。')
        if not 0 < self.response_deadline <= 14:
            raise ValueError('RESPONSE_DEADLINE_SECONDS 需大於 0 且不超過 14，保留前端回傳時間。')
        if not 0 < self.llm_deadline <= 10:
            raise ValueError('LLM_DEADLINE_SECONDS 需大於 0 且不超過 10。')
