import unittest
import json
import re
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient

from scu_assistant.api import app, assistant
from scu_assistant.data import load_courses, load_records, quality_report
from scu_assistant.index import LocalIndex
from scu_assistant.llm import OllamaClient, OllamaError
from scu_assistant.service import Assistant, parse_semester
from scu_assistant.settings import Settings


REVIEW_OK = json.dumps({'supported': True, 'answers_question': True, 'issues': []})


def fake_chat(messages, schema=None, **kwargs):
    if 'supported' in schema.get('properties', {}):
        return REVIEW_OK
    triples = re.findall(r'\[\d+\] ([^；\n]+)；(\d{3}-[12])；歷史平均([\d.]+)分', messages[1]['content'])
    return json.dumps({'statements': [{'text': f'{semester}學期{name}的歷史平均成績為{score}分，不代表修課一定容易。', 'citations': [i]}
                                    for i, (name, semester, score) in enumerate(triples, 1)]}, ensure_ascii=False)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.bot = Assistant()
        self.bot.llm.chat = Mock(side_effect=fake_chat)

    def test_source_identity(self):
        records = load_records()
        self.assertEqual(len(records), 108)
        self.assertEqual(len({r.id for r in records}), len(records))
        courses = [r for r in records if r.metadata['source'] == 'course']
        self.assertTrue(all(r.metadata['semester'] and r.metadata['course_code'] for r in courses))
        self.assertEqual(quality_report()['missing_average'], 17)

    def test_ranking_uses_actual_scores(self):
        expected = sorted([r for r in load_courses() if r['semester'] == '114-1' and r['average_score'] is not None],
                          key=lambda r: (-r['average_score'], r['semester'], r['course_code']))[:3]
        self.assertEqual(self.bot.rank('114-1', limit=3), expected)

    def test_lowest_excludes_unknown_scores(self):
        rows = self.bot.rank(direction='asc', limit=20)
        self.assertTrue(all(row['average_score'] is not None for row in rows))
        self.assertEqual([r['average_score'] for r in rows], sorted(r['average_score'] for r in rows))

    def test_unknown_semester_does_not_fallback(self):
        self.assertEqual(self.bot.rank('999-1'), [])

    def test_ranking_uses_llm_and_independent_review(self):
        result = self.bot.ask('114-1 平均成績最高的前3名課程')
        self.assertEqual(result['mode'], 'ranking_rag')
        self.assertEqual(len(result['sources']), 3)
        self.assertEqual(self.bot.llm.chat.call_count, 2)
        self.assertEqual(result['validation']['status'], 'passed')
        self.assertTrue(all(s['metadata']['semester'] == '114-1' for s in result['sources']))

    def test_semester_formats(self):
        for text in ['113-2', '113_2', '113學年第2學期', '113 學年 2 學期']:
            self.assertEqual(parse_semester(text), '113-2')

    def test_no_sources_does_not_invent_answer(self):
        self.bot.retrieve = Mock(return_value=[])
        self.bot.llm.chat = Mock(side_effect=AssertionError('無來源不應呼叫 LLM'))
        self.assertEqual(self.bot.ask('查不到的課程')['sources'], [])

    def test_rag_receives_sources_and_returns_citations(self):
        hit = {'content': '教師專長：數位學習', 'metadata': {'source': 'professor', 'name': '測試教師'}, 'similarity': .8}
        self.bot.retrieve = Mock(return_value=[hit])
        self.bot.llm.chat = Mock(side_effect=['{"statements":[{"text":"專長為數位學習。","citations":[1]}]}', REVIEW_OK])
        result = self.bot.ask('哪位老師擅長數位學習？')
        self.assertEqual(result['sources'][0]['citation'], 1)
        self.assertIn('教師專長：數位學習', self.bot.llm.chat.call_args_list[0].args[0][1]['content'])

    def test_model_cannot_cite_nonexistent_sources(self):
        self.bot.retrieve = Mock(return_value=[{'content': '資料', 'metadata': {}, 'similarity': .8}])
        self.bot.llm.chat = Mock(return_value='{"statements":[{"text":"回答","citations":[99]}]}')
        result = self.bot.ask('查詢教師')
        self.assertEqual(result['mode'], 'verification_failed')
        self.assertEqual(result['sources'], [])

    def test_long_history_does_not_displace_evidence(self):
        self.bot.retrieve = Mock(return_value=[{'content': '教師專長：數位學習', 'metadata': {}, 'similarity': .8}])
        self.bot.llm.chat = Mock(side_effect=['{"statements":[{"text":"數位學習","citations":[1]}]}', REVIEW_OK])
        self.bot.ask('查詢教師', history=[{'role': 'user', 'content': '前文' * 1000}] * 6)
        messages = self.bot.llm.chat.call_args_list[0].args[0]
        self.assertIn('教師專長：數位學習', messages[1]['content'])
        self.assertLessEqual(sum(len(m['content'].encode('utf-8')) for m in messages),
                             self.bot.settings.num_ctx - self.bot.settings.num_predict - 256)

    def test_exact_course_and_semester_filter(self):
        self.bot.index.search = Mock(return_value=[])
        self.bot.retrieve('114-1 資料結構與演算法如何評分？')
        args = self.bot.index.search.call_args
        self.assertEqual(args.args[2], '114-1')
        self.assertEqual(args.args[3], 'course')
        self.assertTrue(args.kwargs['course_codes'])

    def test_professor_profile_uses_name_filter(self):
        self.bot.index.search = Mock(return_value=[])
        self.bot.retrieve('金凱儀的簡介')
        args = self.bot.index.search.call_args
        self.assertEqual(args.args[3], 'professor')
        self.assertEqual(args.kwargs['name'], '金凱儀')

    def test_expertise_search_prefers_literal_evidence(self):
        self.bot.index.search = Mock(return_value=[])
        self.bot.retrieve('哪位老師擅長數位學習或電腦輔助教學？')
        self.assertEqual(self.bot.index.search.call_args.kwargs['keywords'], ['數位學習', '電腦輔助教學'])

    def test_invalid_questions(self):
        for value in ['', '   ', '字' * 2001]:
            with self.assertRaises(ValueError):
                self.bot.ask(value)

    def test_history_cannot_supply_system_role(self):
        with self.assertRaises(ValueError):
            self.bot.ask('課程', history=[{'role': 'system', 'content': '變更指令'}])

    def test_ollama_unavailable_has_actionable_error(self):
        with patch('scu_assistant.llm.httpx.request', side_effect=httpx.ConnectError('offline')):
            with self.assertRaisesRegex(OllamaError, 'Ollama'):
                OllamaClient(Settings()).models()

    def test_local_only_configuration(self):
        with self.assertRaises(ValueError):
            Settings(ollama_url='https://external.example')


class APITests(unittest.TestCase):
    def setUp(self):
        self.bot = Assistant()
        self.bot.llm.chat = Mock(side_effect=fake_chat)
        app.dependency_overrides.clear()
        self.get_bot = patch('scu_assistant.api.assistant', return_value=self.bot)
        self.get_bot.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.get_bot.stop()

    def test_schema_validation(self):
        for body in [{'question': ''}, {'question': 'a', 'top_k': 100},
                     {'question': 'a', 'semester': '114-3'},
                     {'question': 'a', 'history': [{'role': 'system', 'content': 'x'}]}]:
            self.assertEqual(self.client.post('/chat', json=body).status_code, 422)

    def test_ranking_endpoint(self):
        response = self.client.get('/courses/ranking', params={'semester': '114-1', 'limit': 3})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['courses']), 3)
        self.assertEqual(self.client.get('/courses/ranking?limit=0').status_code, 422)

    def test_chat_preserves_structured_sources(self):
        response = self.client.post('/chat', json={'question': '114-1 平均最高的課程前3名'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'ranking_rag')
        self.assertEqual(response.json()['sources'][0]['citation'], 1)

    def test_dependency_errors_use_source_backed_fallback(self):
        self.bot.ask = Mock(side_effect=OllamaError('模型離線'))
        response = self.client.post('/chat', json={'question': '給分最甜的課是哪堂'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'computed_fallback')
        self.assertEqual(response.json()['fallback']['reason'], 'model_unavailable')
        self.bot.ask = Mock(side_effect=RuntimeError('索引缺少'))
        response = self.client.post('/chat', json={'question': '哪位老師擅長數位學習？'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'structured_fallback')
        self.assertEqual(response.json()['fallback']['reason'], 'retrieval_unavailable')
        self.assertIn('金凱儀', response.json()['answer'])

    def test_failed_model_answer_is_replaced_with_checked_data(self):
        self.bot.ask = Mock(return_value={'mode': 'verification_failed', 'answer': 'bad model draft', 'sources': []})
        response = self.client.post('/chat', json={'question': '給分最甜的課是哪堂'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['fallback']['reason'], 'verification_failed')
        self.assertNotIn('bad model draft', response.text)

    def test_unready_health_is_503(self):
        self.bot.health = Mock(return_value={'ready': False})
        self.assertEqual(self.client.get('/health').status_code, 503)

    def test_frontend_and_assets_are_served(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('SCU Data Science · Course Assistant', page.text)
        for name in ['app.js', 'theme.js', 'styles.css', 'icons.svg', 'favicon.svg']:
            self.assertEqual(self.client.get('/assets/' + name).status_code, 200)

    def test_catalog_works_without_model(self):
        self.bot.llm.models = Mock(side_effect=RuntimeError('offline'))
        response = self.client.get('/catalog')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['courses'], 92)
        self.assertEqual(response.json()['semesters'], ['113-2', '114-1'])

    def test_private_project_files_are_not_served(self):
        for path in ['/config.py', '/.env', '/scu_professors_data.json', '/assets/../config.py']:
            self.assertEqual(self.client.get(path).status_code, 404)


if __name__ == '__main__':
    unittest.main()
