import re
import time

from .data import course_record, load_courses, load_records, quality_report
from .index import LocalIndex
from .llm import OllamaClient
from .settings import Settings
from .intent import parse_intent, constrain_sources, course_name
from .answering import verified_answer
from .deadline import remaining
from .fallback import lexical_sources, structured_response

def parse_semester(question: str) -> str | None:
    match = re.search(r'(\d{3})\s*(?:[-_/]|學年(?:度)?\s*第?\s*)([12])\s*(?:學期)?', question)
    return f'{match[1]}-{match[2]}' if match else None


def ranking_direction(question: str) -> str | None:
    if not re.search(r'平均|分數|成績|給分|甜|average|grade|score', question, re.I):
        return None
    if re.search(r'最低|最差|由低到高|低分|最不甜|lowest', question, re.I):
        return 'asc'
    if re.search(r'最高|很高|高分|最甜|排名|排序|排行|前\s*\d+|highest|top\s*\d+', question, re.I):
        return 'desc'
    return None


class Assistant:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.index = LocalIndex(self.settings)
        self.llm = OllamaClient(self.settings)

    def retrieve(self, question: str, top_k=4, semester=None, source=None, teacher=None) -> list[dict]:
        semester = semester or parse_semester(question)
        courses = load_courses()
        professor_name = next((r.metadata['name'] for r in load_records()
            if r.metadata['source'] == 'professor' and r.metadata['name'] in question), None)
        profile_intent = bool(re.search(r'擅長|專長|研究|專業|簡介|背景|學歷|介紹', question))
        if source is None and not semester and ((re.search(r'老師|教師|教授', question) and profile_intent)
                or (professor_name and (profile_intent or not re.search(r'課|成績|分數|評分|平均', question)))):
            source = 'professor'
        name = None
        codes = None
        if source == 'professor':
            name = teacher or professor_name
            teacher = None
        else:
            teacher = teacher or next((r['teacher'] for r in courses if r['teacher'] != '未知' and r['teacher'] in question), None)
            exact = [r for r in courses if r['course_code'] in question or r['course_name'].split()[0] in question]
            if exact:
                names = {r['course_name'].split()[0] for r in exact}
                names = {name for name in names if not any(name != other and name in other for other in names)}
                codes = sorted({r['course_code'] for r in exact if r['course_name'].split()[0] in names or r['course_code'] in question})
                source = 'course'
        keywords = []
        if source == 'professor':
            topic = re.search(r'(?:擅長|專長(?:是|為)?|研究領域(?:是|為)?)([^？?]+)', question)
            if topic:
                keywords = [term.strip(' 。，的') for term in re.split(r'或|與|和|、|，|,', topic[1])]
                keywords = [term for term in keywords if 2 <= len(term) <= 20 and term not in {'什麼', '哪些'}]
        return self.index.search(question, top_k, semester, source, teacher, course_codes=codes, name=name, keywords=keywords)

    def rank(self, semester=None, teacher=None, limit=5, direction='desc', min_average=None) -> list[dict]:
        if not 1 <= limit <= 20 or direction not in {'asc', 'desc'}:
            raise ValueError('limit 需介於 1 到 20，direction 需為 asc 或 desc。')
        rows = [row for row in load_courses() if row['average_score'] is not None
                and (not semester or row['semester'] == semester)
                and (not teacher or row['teacher'] == teacher)
                and (min_average is None or row['average_score'] >= min_average)]
        rows.sort(key=lambda row: ((-1 if direction == 'desc' else 1) * row['average_score'], row['semester'], row['course_code']))
        return rows[:limit]

    def ask(self, question: str, top_k=4, semester=None, source=None, teacher=None, history=None, deadline=None) -> dict:
        deadline = deadline or (time.monotonic() + self.settings.llm_deadline)
        remaining(deadline)
        prepared = self._prepare(question, top_k, semester, source, teacher, history)
        remaining(deadline)
        if 'response' in prepared:
            return prepared['response']
        return verified_answer(self.llm, self.settings, question.strip(), prepared['history'],
                               prepared['sources'], prepared['intent'], prepared['courses'], prepared['mode'], deadline=deadline)

    def fallback(self, question: str, top_k=4, semester=None, source=None, teacher=None, history=None, reason='llm_timeout') -> dict:
        # This path only reads local JSON. It must work even while the model or
        # embedding worker is blocked, offline, or warming up.
        prepared = self._prepare(question, top_k, semester, source, teacher, history, structured=True)
        return structured_response(prepared, reason)

    def _prepare(self, question, top_k, semester, source, teacher, history, structured=False):
        question = question.strip()
        if not question or len(question) > 2000:
            raise ValueError('問題需為 1 到 2000 字。')
        if not 1 <= top_k <= 8:
            raise ValueError('top_k 需介於 1 到 8。')
        history = (history or [])[-6:]
        if any(m.get('role') not in {'user', 'assistant'} or len(m.get('content', '')) > 2000 for m in history):
            raise ValueError('對話記錄僅接受 user/assistant，每則最多 2000 字。')
        courses = load_courses()
        previous = next((m['content'] for m in reversed(history) if m['role'] == 'user'), '')
        retrieval_question = question
        followup = bool(re.search(r'這位|那位|這門|那門|這堂|那堂|他(?:的|呢)|她(?:的|呢)|只要|就一堂', question))
        if followup and previous:
            retrieval_question = previous + '\n' + question
        semester = semester or parse_semester(question) or (parse_semester(previous) if followup else None)
        direction = ranking_direction(question)
        if not direction and followup and re.search(r'只要|就一堂', question):
            direction = ranking_direction(previous)
        intent = parse_intent(question, courses, direction, semester)
        if followup and not intent.named_courses and re.search(r'這門|那門|這堂|那堂', question):
            prior_answer = next((m['content'] for m in reversed(history) if m['role'] == 'assistant'), '')
            previous_intent = parse_intent(prior_answer, courses)
            if len(previous_intent.named_courses) == 1:
                intent.named_courses = previous_intent.named_courses
                intent.requested_count = 1
            elif len(previous_intent.named_courses) > 1:
                return {'response': self._response('上一則回答提到不只一堂課。請告訴我你要問哪一堂的課名，我再查證回答。', [], 'clarification', semester, None)}
        teacher = teacher or next((r['teacher'] for r in courses if r['teacher'] != '未知' and r['teacher'] in question), None)
        if direction and source != 'professor':
            rows = [r for r in courses if r['average_score'] is not None
                    and (not semester or r['semester'] == semester)
                    and (not teacher or r['teacher'] == teacher)
                    and (not intent.named_courses or course_name(r['course_name']) in intent.named_courses)]
            rows.sort(key=lambda r: ((-1 if direction == 'desc' else 1) * r['average_score'], r['semester'], r['course_code']))
            rows = rows[:intent.requested_count or 3]
            sources = []
            for row in rows:
                record = course_record(row, summary=True)
                sources.append({'content': record.content, 'metadata': record.metadata, 'similarity': None})
            mode = 'ranking_rag'
        elif intent.named_courses and re.search(r'評分|配分|grading|平均成績|平均分數|授課教師|誰教', question, re.I):
            # Exact fields already exist in the source JSON. Do not run a
            # vector search just to rediscover a known course's grading table.
            sources = []
            for name in intent.named_courses:
                rows = [r for r in courses if course_name(r['course_name']) == name
                        and (not semester or r['semester'] == semester)
                        and (not teacher or r['teacher'] == teacher)]
                rows.sort(key=lambda r: (r['year'], r['term']), reverse=True)
                if not rows:
                    continue
                latest = [r for r in rows if r['semester'] == rows[0]['semester']]
                specified = [r for r in latest if r['course_code'] in question]
                if len(latest) > 1 and not teacher and not specified:
                    return {'response': self._response('這門課有不同班級，請補充授課教師或科目代碼後再查詢。', [], 'clarification', semester, None)}
                row = (specified or latest)[0]
                record = course_record(row, summary=True)
                if re.search(r'評分|配分|grading', question, re.I):
                    record.content += '\n【評分方式】\n' + str(row.get('syllabus', {}).get('grading', '無資料'))
                sources.append({'content': record.content, 'metadata': record.metadata, 'similarity': None})
            mode = 'rag'
        else:
            query = retrieval_question
            if intent.named_courses:
                query += '\n指定課程：' + '、'.join(intent.named_courses)
            sources = (lexical_sources(query, intent, source, teacher, top_k) if structured
                       else self.retrieve(query, top_k, semester, source, teacher))
            # Exact course identities are resolved from the original JSON before
            # retrieval. Never answer with neighboring courses if retrieval drifts.
            sources = constrain_sources(sources, intent)
            if intent.named_courses and not sources:
                rows = [r for r in courses if course_name(r['course_name']) in intent.named_courses
                        and (not semester or r['semester'] == semester) and (not teacher or r['teacher'] == teacher)]
                rows.sort(key=lambda r: (r['year'], r['term']), reverse=True)
                for name in intent.named_courses:
                    row = next((r for r in rows if course_name(r['course_name']) == name), None)
                    if row:
                        record = course_record(row, summary=True)
                        record.content += '\n【課程內容】\n' + str(row.get('syllabus', {}).get('content', '無資料'))[:900]
                        record.content += '\n【評分方式】\n' + str(row.get('syllabus', {}).get('grading', '無資料'))
                        sources.append({'content': record.content, 'metadata': record.metadata, 'similarity': None})
            mode = 'rag'
        sources = constrain_sources(sources, intent)
        if not sources:
            result = self._response('現有資料找不到符合這個課名、學期或條件的來源，無法確認。請補充完整課名或學期後再查詢。', [], 'retrieval', semester, None)
            result['validation'] = {'status': 'no_evidence', 'requested_count': intent.requested_count, 'llm_calls': 0}
            return {'response': result}
        return dict(question=question, history=history, sources=sources, intent=intent, courses=courses, mode=mode)

    def _response(self, answer, sources, mode, semester, model):
        return dict(answer=answer, sources=[dict(s, citation=i) for i, s in enumerate(sources, 1)],
                    mode=mode, semester=semester, model=model)

    def health(self) -> dict:
        status = {'model': self.settings.model, 'data': quality_report()}
        status['embedding_weights'] = all((self.settings.embedding_path / filename).is_file()
            for filename in ['model.safetensors', 'config.json', 'tokenizer_config.json'])
        try:
            models = [m['name'] for m in self.llm.models()]
            status.update(ollama=True, available_models=models, model_available=self.settings.model in models)
        except RuntimeError as exc:
            status.update(ollama=False, model_available=False, ollama_error=str(exc))
        try:
            collection = self.index.collection()
            count = collection.count()
            status.update(index=count > 0, chunks=count)
        except RuntimeError as exc:
            status.update(index=False, index_error=str(exc))
        status['ready'] = status['ollama'] and status['model_available'] and status['index'] and status['embedding_weights']
        return status
