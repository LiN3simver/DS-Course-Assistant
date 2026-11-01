"""端到端實測：真實 Chroma、真實嵌入模型、真實本地 Ollama。"""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from scu_assistant.api import app, assistant


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    with TestClient(app) as client:
        # Startup preloads models in the background. Queries can already use
        # JSON fallback, but this smoke check also inspects the real index.
        ready_deadline = time.monotonic() + 180
        response = client.get('/health')
        while response.status_code == 503 and response.json().get('warming_up') and time.monotonic() < ready_deadline:
            time.sleep(1)
            response = client.get('/health')
        assert response.status_code == 200, response.text
        print('health:', response.json(), flush=True)
        response = client.post('/search', json={'question': '哪位老師擅長數位學習或電腦輔助教學？', 'top_k': 3})
        assert response.status_code == 200, response.text
        hits = response.json()['sources']
        assert hits and all(h['metadata']['source'] == 'professor' for h in hits)
        assert any('數位學習' in h['content'] or '電腦輔助教學' in h['content'] for h in hits), hits
        print('professor search:', [(h['metadata']['name'], h['similarity']) for h in hits], flush=True)
        bot = assistant()
        tokenizer = bot.index.encoder.tokenizer
        docs = bot.index.collection().get(include=['documents'])['documents']
        max_tokens = max(len(tokenizer.encode(text, verbose=False)) for text in docs)
        assert max_tokens <= bot.index.encoder.max_seq_length, max_tokens
        print('chunk token limit:', max_tokens, flush=True)
        response = client.post('/search', json={'question': '114-1 資料結構與演算法的評分方式？'})
        assert response.status_code == 200, response.text
        hits = response.json()['sources']
        assert hits and all(h['metadata']['semester'] == '114-1' and '資料結構' in h['metadata']['name'] for h in hits)
        print('semester filtering: OK', flush=True)
        response = client.post('/chat', json={'question': '114-1 平均成績最高的前3名課程'})
        assert response.status_code == 200, response.text
        scores = [h['metadata']['average_score'] for h in response.json()['sources']]
        assert len(scores) == 3 and scores == sorted(scores, reverse=True)
        assert response.json()['mode'] in {'ranking_rag', 'computed_fallback'}
        assert response.json()['validation']['status'] in {'passed', 'data_checked'}
        print('numeric ranking:', scores, flush=True)
        response = client.post('/search', json={'question': '課程內容', 'semester': '999-1'})
        assert response.status_code == 200 and not response.json()['sources']
        print('unknown semester: no sources', flush=True)
        response = client.post('/chat', json={'question': '哪位老師擅長數位學習或電腦輔助教學？', 'top_k': 3})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['mode'] in {'rag', 'structured_fallback'}
        assert result['model'] == (None if result.get('fallback') else bot.settings.model)
        assert result['answer'] and result['sources']
        assert '金凱儀' in result['answer'], result['answer']
        assert any(f'[{i}]' in result['answer'] for i in range(1, len(result['sources']) + 1))
        print('local answer mode:', result['mode'], result['answer'], flush=True)
        response = client.post('/chat', json={'question': '114-1 資料結構與演算法的評分比例是什麼？', 'top_k': 3})
        assert response.status_code == 200, response.text
        grading = response.json()
        assert grading['mode'] in {'rag', 'structured_fallback'} and '30' in grading['answer'] and '40' in grading['answer']
        assert all(s['metadata']['semester'] == '114-1' for s in grading['sources'])
        print('course grading answer:', grading['answer'], flush=True)
        count = bot.index.collection().count()
        rebuilt = bot.index.build()
        assert rebuilt['changed'] is False and bot.index.collection().count() == count
        legacy = bot.index.client.get_collection('langchain', embedding_function=None)
        assert legacy.count() == 452
        print('idempotent build and original 452 chunks preserved: OK', flush=True)
        target = Path(__file__).resolve().parent.parent / 'logs' / 'smoke_result.json'
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PASS: real local RAG and API', flush=True)


if __name__ == '__main__':
    main()
