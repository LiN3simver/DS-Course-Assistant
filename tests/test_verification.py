import json
import unittest
from unittest.mock import Mock

from scu_assistant.data import course_record, load_courses
from scu_assistant.intent import Intent, parse_intent
from scu_assistant.llm import OllamaError
from scu_assistant.service import Assistant, ranking_direction
from scu_assistant.verification import validate_statements

PASS = json.dumps({'supported': True, 'answers_question': True, 'issues': []})
FAIL = json.dumps({'supported': False, 'answers_question': False, 'issues': ['沒有資料支持免考試的說法']})


def draft(text, citations=None):
    return json.dumps({'statements': [{'text': text, 'citations': citations or [1]}]}, ensure_ascii=False)


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.bot = Assistant()
        self.courses = load_courses()
        self.highest = self.bot.rank(limit=1)[0]
        record = course_record(self.highest, summary=True)
        self.source = {'content': record.content, 'metadata': record.metadata, 'similarity': None}
        self.name = self.highest['course_name']
        self.good = draft(f"{self.highest['semester']}學期{self.name}的歷史平均成績為{self.highest['average_score']}分，不代表修課容易。")

    def test_reported_question_means_one_not_top_k(self):
        for top_k in [1, 4, 8]:
            self.bot.llm.chat = Mock(side_effect=[self.good, PASS])
            result = self.bot.ask('給分最甜的課是哪堂', top_k=top_k)
            self.assertEqual(result['validation']['requested_count'], 1)
            self.assertEqual(result['validation']['course_count'], 1)
            self.assertEqual(len(result['sources']), 1)
            self.assertEqual(self.bot.llm.chat.call_count, 2)
            self.assertEqual(result['model'], self.bot.settings.model)

    def test_explicit_counts_and_implicit_superlative(self):
        examples = [('給分最甜的課是哪堂', 1), ('只要一堂平均最高的課', 1),
                    ('推薦兩門給分最甜的課', 2), ('平均成績最高的前3名課程', 3),
                    ('平均成績最高的前十二名', 12), ('平均成績最高的前二十名', 20),
                    ('Which course has the highest average score?', 1), ('top 3 courses by average score', 3)]
        for question, expected in examples:
            with self.subTest(question=question):
                intent = parse_intent(question, self.courses, ranking_direction(question))
                self.assertEqual(intent.requested_count, expected)

    def test_wrong_course_and_count_trigger_repair(self):
        other = self.bot.rank(limit=2)[1]['course_name']
        self.bot.llm.chat = Mock(side_effect=[draft(f'{self.name}與{other}都推薦。'), self.good, PASS])
        result = self.bot.ask('給分最甜的課是哪堂')
        self.assertEqual(result['validation']['status'], 'passed')
        self.assertEqual(len(result['validation']['attempts']), 2)
        self.assertIn('unrequested_course', result['validation']['attempts'][0]['issues'])
        self.assertIn('驗證失敗', self.bot.llm.chat.call_args_list[1].args[0][-1]['content'])
        self.assertNotIn(other, result['answer'])

    def test_semantic_reviewer_can_reject_and_repair_a_plausible_draft(self):
        self.bot.llm.chat = Mock(side_effect=[draft(f"{self.highest['semester']}學期{self.name}歷史平均{self.highest['average_score']}分，不代表容易。這門課不用考試。"), FAIL, self.good, PASS])
        result = self.bot.ask('給分最甜的課是哪堂')
        self.assertEqual(result['validation']['status'], 'passed')
        self.assertEqual(result['validation']['llm_calls'], 4)
        self.assertIn('semantic_review_failed', result['validation']['attempts'][0]['issues'])

    def test_two_failed_reviews_abstain_without_showing_bad_draft(self):
        self.bot.llm.chat = Mock(side_effect=[draft(f"{self.highest['semester']}學期{self.name}歷史平均{self.highest['average_score']}分，不代表容易。這門課不用考試。"), FAIL] * 2)
        result = self.bot.ask('給分最甜的課是哪堂')
        self.assertEqual(result['mode'], 'verification_failed')
        self.assertEqual(result['validation']['status'], 'failed')
        self.assertEqual(result['sources'], [])
        self.assertNotIn('不用考試', result['answer'])
        self.assertEqual(self.bot.llm.chat.call_count, 4)

    def test_no_static_answer_when_ollama_is_unavailable(self):
        self.bot.llm.chat = Mock(side_effect=OllamaError('Ollama offline'))
        with self.assertRaises(OllamaError):
            self.bot.ask('給分最甜的課是哪堂')

    def test_specific_course_ranking_cannot_rank_other_courses(self):
        name = '資料結構與演算法'
        rows = [r for r in self.courses if r['course_name'] == name and r['average_score'] is not None]
        best = max(rows, key=lambda r: r['average_score'])
        self.bot.llm.chat = Mock(side_effect=[draft(f"{best['semester']}學期{name}的歷史平均成績為{best['average_score']}分，不代表修課容易。"), PASS])
        result = self.bot.ask(f'{name}最高的平均成績是多少？')
        self.assertEqual(result['validation']['status'], 'passed')
        self.assertTrue(all(s['metadata']['name'] == name for s in result['sources']))

    def test_unknown_semester_does_not_fallback_or_call_llm(self):
        self.bot.llm.chat = Mock(side_effect=AssertionError('no evidence'))
        result = self.bot.ask('999-1 平均成績最高的是哪堂')
        self.assertEqual(result['validation']['status'], 'no_evidence')
        self.assertEqual(result['sources'], [])

    def test_wrong_average_is_rejected_even_when_number_occurs_elsewhere(self):
        source = dict(self.source, content=self.source['content'] + '\n成績分布：80 分有 20 人')
        intent = Intent(1, [], 'desc', None)
        errors = validate_statements([{'text': f'{self.name}平均成績為80分。', 'citations': [1]}], [source], intent, self.courses)
        self.assertIn('wrong_average', errors)

    def test_wrong_semester_and_percentage_are_rejected(self):
        intent = Intent(1, [], None, '113-2')
        errors = validate_statements([{'text': f'{self.name}作業佔20%。', 'citations': [1]}], [self.source], intent, self.courses)
        self.assertIn('wrong_semester', errors)
        self.assertIn('unsupported_percentage', errors)

    def test_rank_answer_must_include_basis_score_semester_and_caveat(self):
        errors = validate_statements([{'text': f'{self.name}最甜。', 'citations': [1]}],
            [self.source], Intent(1, [], 'desc', None), self.courses)
        for code in ['missing_rank_scores', 'missing_ranking_basis', 'missing_semester_disclosure', 'missing_grade_caveat']:
            self.assertIn(code, errors)

    def test_history_caveat_is_not_mistaken_for_a_grade_guarantee(self):
        statements = json.loads(self.good)['statements']
        statements[0]['text'] += '不代表未來一定高分。'
        errors = validate_statements(statements, [self.source], Intent(1, [], 'desc', None), self.courses)
        self.assertNotIn('unsupported_grade_guarantee', errors)

    def test_citation_cannot_reference_another_professor(self):
        sources = [{'content': '甲老師：數位學習', 'metadata': {'source': 'professor', 'name': '甲老師'}},
                   {'content': '乙老師：人工智慧', 'metadata': {'source': 'professor', 'name': '乙老師'}}]
        errors = validate_statements([{'text': '甲老師擅長人工智慧。', 'citations': [2]}], sources, Intent(None, [], None, None), self.courses)
        self.assertIn('professor_citation_mismatch', errors)

    def test_ambiguous_followup_asks_which_course(self):
        names = [r['course_name'] for r in self.bot.rank(limit=2)]
        self.bot.llm.chat = Mock(side_effect=AssertionError('ambiguity must not be guessed'))
        result = self.bot.ask('這堂怎麼評分？', history=[{'role': 'user', 'content': '推薦課程'},
            {'role': 'assistant', 'content': '、'.join(names)}])
        self.assertEqual(result['mode'], 'clarification')
        self.assertEqual(result['sources'], [])


if __name__ == '__main__':
    unittest.main()
