import unittest
from unittest.mock import Mock, patch

from scu_assistant.data import load_courses, load_records
from scu_assistant.service import Assistant
from scu_assistant.settings import Settings


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.bot = Assistant()
        self.bot.retrieve = Mock(side_effect=AssertionError('fallback must not use embeddings'))
        self.bot.llm.chat = Mock(side_effect=AssertionError('fallback must not call the model'))

    def test_single_best_course_uses_actual_data_not_a_fixed_answer(self):
        for semester in [None, '113-2', '114-1']:
            result = self.bot.fallback('給分最甜的課是哪堂', semester=semester)
            expected = self.bot.rank(semester=semester, limit=1)[0]
            self.assertEqual(result['mode'], 'computed_fallback')
            self.assertEqual(result['validation']['status'], 'data_checked')
            self.assertFalse(result['validation']['llm_reviewed'])
            self.assertEqual(result['sources'][0]['metadata']['record_id'], expected['record_id'])
            self.assertEqual(result['validation']['course_count'], 1)
            self.assertIn(f"{expected['average_score']:.2f}", result['answer'])
            self.assertIsNone(result['model'])
        with patch('scu_assistant.service.load_courses', return_value=[dict(load_courses()[0], average_score=99.12)]):
            result = self.bot.fallback('給分最甜的課是哪堂')
        self.assertIn('99.12', result['answer'])

    def test_rank_counts_and_order_are_independent_of_chunk_count(self):
        for count in [1, 3, 12, 20]:
            for direction, term in [('desc', '最高'), ('asc', '最低')]:
                result = self.bot.fallback(f'114-1 平均成績{term}的前{count}名', top_k=1)
                expected = self.bot.rank(semester='114-1', limit=count, direction=direction)
                self.assertEqual(result['mode'], 'computed_fallback', result)
                self.assertEqual([s['metadata']['record_id'] for s in result['sources']], [r['record_id'] for r in expected])
                self.assertEqual(result['validation']['course_count'], count)

    def test_exact_grading_returns_verbatim_selected_semester(self):
        result = self.bot.fallback('114-1 資料結構與演算法的評分比例是什麼？')
        expected = next(r for r in load_courses() if r['course_name'] == '資料結構與演算法' and r['semester'] == '114-1')
        self.assertEqual(result['mode'], 'structured_fallback')
        self.assertEqual(result['validation']['course_count'], 1)
        self.assertEqual(result['sources'][0]['metadata']['record_id'], expected['record_id'])
        self.assertIn(str(expected['syllabus']['grading']).strip()[:1000], result['answer'])
        self.assertIn('資料原文', result['answer'])

    def test_expertise_is_a_verbatim_profile_not_an_invented_conclusion(self):
        result = self.bot.fallback('哪位老師擅長數位學習或電腦輔助教學？')
        self.assertEqual(result['mode'], 'structured_fallback')
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['sources'][0]['metadata']['name'], '金凱儀')
        original = next(r for r in load_records() if r.metadata['name'] == '金凱儀')
        self.assertIn(result['sources'][0]['content'], original.content)
        self.assertIn('數位學習', result['answer'])

    def test_unknown_conditions_do_not_relax_or_invent_results(self):
        for question in ['999-1 平均最高的是哪堂', '火星殖民課程的教室位置？']:
            result = self.bot.fallback(question)
            self.assertEqual(result['sources'], [])
            self.assertEqual(result['validation']['status'], 'no_evidence')

    def test_named_course_and_teacher_scope(self):
        result = self.bot.fallback('資料結構與演算法最高的平均成績是多少？')
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['sources'][0]['metadata']['name'], '資料結構與演算法')
        teacher = self.bot.rank(limit=1)[0]['teacher']
        result = self.bot.fallback('114-1 平均成績最高的前3名', teacher=teacher)
        self.assertTrue(all(s['metadata']['teacher'] == teacher for s in result['sources']))

    def test_ambiguous_followup_still_requests_clarification(self):
        names = [r['course_name'] for r in self.bot.rank(limit=2)]
        result = self.bot.fallback('這堂怎麼評分？', history=[{'role': 'user', 'content': '推薦課程'},
            {'role': 'assistant', 'content': '、'.join(names)}])
        self.assertEqual(result['mode'], 'clarification')
        self.assertEqual(result['sources'], [])

    def test_llm_budget_cannot_exceed_ten_seconds(self):
        with self.assertRaises(ValueError):
            Settings(llm_deadline=10.1)


if __name__ == '__main__':
    unittest.main()
