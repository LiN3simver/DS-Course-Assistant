import asyncio
from dataclasses import replace
import json
import time
from threading import BoundedSemaphore
import unittest
from unittest.mock import Mock, patch

import httpx

from scu_assistant.api import app, runtime
from scu_assistant.deadline import ResponseDeadlineExceeded
from scu_assistant.service import Assistant
from scu_assistant.settings import Settings


class LatencyTests(unittest.TestCase):
    def test_deadline_is_shared_by_generation_and_review(self):
        bot = Assistant()
        clock = [100.0]
        def slow(*args, **kwargs):
            clock[0] += 15
            return json.dumps({'statements': [{'text': 'not published', 'citations': [1]}]})
        bot.llm.chat = Mock(side_effect=slow)
        with patch('scu_assistant.deadline.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(ResponseDeadlineExceeded):
                bot.ask('給分最甜的課是哪堂')
        self.assertEqual(bot.llm.chat.call_count, 1)

    def test_http_deadline_returns_without_waiting_for_an_uncancellable_worker(self):
        bot = Assistant(replace(Settings(), response_deadline=.3, llm_deadline=.04))
        def blocked(**kwargs):
            time.sleep(.2)
            return {'answer': 'late answer must not be served', 'sources': []}
        bot.ask = Mock(side_effect=blocked)
        async def run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
                started = time.monotonic()
                first = await client.post('/chat', json={'question': '給分最甜的課是哪堂'})
                elapsed = time.monotonic() - started
                self.assertEqual(first.status_code, 200)
                self.assertLess(elapsed, .18)
                self.assertNotIn('late answer', first.text)
                self.assertEqual(first.json()['mode'], 'computed_fallback')
                self.assertEqual(first.json()['fallback']['reason'], 'llm_timeout')
                self.assertEqual(first.json()['validation']['course_count'], 1)
                self.assertIsNone(first.json()['model'])
                busy = await client.post('/chat', json={'question': '114-1 平均最高的前三名課程'})
                self.assertEqual(busy.status_code, 200)
                self.assertEqual(busy.json()['fallback']['reason'], 'model_busy')
                self.assertEqual(len(busy.json()['sources']), 3)
                self.assertEqual(bot.ask.call_count, 1)
                await asyncio.sleep(.23)
                bot.ask.side_effect = None
                bot.ask.return_value = {'answer': 'ready', 'sources': []}
                final = await client.post('/chat', json={'question': 'third'})
                self.assertEqual(final.status_code, 200)
        with patch('scu_assistant.api.assistant', return_value=bot), patch('scu_assistant.api.query_slot', BoundedSemaphore(1)), patch.dict(runtime, {'started': False}):
            asyncio.run(run())

    def test_warmup_uses_data_instead_of_queueing_a_query(self):
        bot = Assistant()
        bot.ask = Mock(side_effect=AssertionError('warming queries must not execute'))
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await client.post('/chat', json={'question': '給分最甜的課是哪堂'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['mode'], 'computed_fallback')
                self.assertEqual(response.json()['fallback']['reason'], 'model_warming')
                self.assertFalse(response.json()['fallback']['llm_attempted'])
                health = await client.get('/health')
                self.assertEqual(health.status_code, 503)
                self.assertTrue(health.json()['warming_up'])
        with patch('scu_assistant.api.assistant', return_value=bot), patch.dict(runtime, {'started': True, 'ready': False, 'error': None}):
            asyncio.run(run())
        bot.ask.assert_not_called()


if __name__ == '__main__':
    unittest.main()
