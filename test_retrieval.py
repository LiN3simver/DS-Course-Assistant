"""人工檢索檢查，不呼叫 LLM。自動測試位於 tests/。"""
import sys
from scu_assistant.service import Assistant


def test_retrieval():
    bot = Assistant()
    for question in ['請問哪位老師擅長數位學習或電腦輔助教學？', '114-1 資料結構的評分方式是什麼？']:
        print(f'\n問題：{question}')
        results = bot.retrieve(question, top_k=3)
        if not results:
            raise RuntimeError('未檢索到來源，請檢查模型與索引。')
        for result in results:
            print(result['metadata'], 'cosine similarity:', result['similarity'])
            print(result['content'])


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    test_retrieval()
