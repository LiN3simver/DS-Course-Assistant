"""Fast, source-backed answers that never call an LLM or embedding model."""
import re

from .data import load_records
from .intent import normalize, constrain_sources
from .verification import validate_statements


def lexical_sources(question, intent, source=None, teacher=None, top_k=4):
    profile = bool(re.search(r'老師|教授|教師|專長|擅長|研究|faculty|professor|expert|speciali', question, re.I))
    if source is None and profile and not intent.named_courses and not intent.semester:
        source = 'professor'
    records = load_records()
    named_professors = [r.metadata['name'] for r in records if r.metadata['source'] == 'professor' and r.metadata['name'] in question]
    if source is None and named_professors and not intent.named_courses:
        source = 'professor'
    cleaned = re.sub(r'請問|可以|哪些|哪位|哪堂|老師|教師|教授|課程|介紹|推薦|內容|想要|我要|如何|什麼|擅長|專長|研究領域|的|是|嗎|呢|或|與|和', ' ', question)
    segments = re.findall(r'[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}', cleaned)
    terms = {normalize(term) for term in segments if term.lower() not in {'the', 'what', 'which', 'course', 'courses', 'professor'}}
    grams = {term[i:i + 2] for term in terms for i in range(max(0, len(term) - 1))}
    hits = []
    for record in records:
        meta = record.metadata
        if source and meta['source'] != source:
            continue
        if intent.semester and meta.get('semester') != intent.semester:
            continue
        if teacher and (meta.get('teacher') if meta['source'] == 'course' else meta['name']) != teacher:
            continue
        if named_professors and meta['source'] == 'professor' and meta['name'] not in named_professors:
            continue
        body = record.content
        if meta['source'] == 'professor' and profile and '研究領域' in body:
            body = '研究領域' + re.split(r'開設課程|履歷|學歷|著作|經歷', body.split('研究領域', 1)[1], maxsplit=1)[0]
        normalized = normalize(body)
        exact = sum(len(term) for term in terms if term in normalized)
        overlap = sum(gram in normalized for gram in grams)
        # Require a direct term or several overlapping characters, rather than
        # listing arbitrary records when the query has no recognizable topic.
        named = bool(intent.named_courses and normalize(meta['name'].split()[0]) in {normalize(n) for n in intent.named_courses})
        if not named and not named_professors and exact == 0 and overlap < 2:
            continue
        score = exact * 10 + overlap + (1000 if named else 0)
        hits.append((score, {'content': body, 'metadata': meta, 'similarity': None}))
    hits.sort(key=lambda item: (item[0], item[1]['metadata'].get('semester', '')), reverse=True)
    return constrain_sources([item[1] for item in hits], intent)[:max(top_k, intent.requested_count or 0)]


def structured_response(prepared, reason):
    if 'response' in prepared:
        result = prepared['response']
        result['fallback'] = {'reason': reason, 'llm_attempted': reason not in {'model_warming', 'model_busy'}}
        return result
    sources = prepared['sources']
    intent = prepared['intent']
    statements = []
    if prepared['mode'] == 'ranking_rag':
        direction = '由低到高' if intent.direction == 'asc' else '由高到低'
        for i, hit in enumerate(sources, 1):
            meta = hit['metadata']
            text = f"{meta['name']}（{meta['semester']}，{meta['teacher']}），歷史平均成績 {meta['average_score']:.2f} 分。"
            statements.append({'text': text, 'citations': [i]})
        if statements:
            statements[0]['text'] = f'依現有資料的歷史平均成績{direction}計算：\n' + statements[0]['text']
            statements.append({'text': '歷史平均不代表課程容易或保證未來成績。', 'citations': list(range(1, len(sources) + 1))})
        errors = validate_statements(statements, sources, intent, prepared['courses'], max_statements=21)
        if errors:
            return dict(answer='資料計算未通過核對，請補充課名或學期後再查詢。', sources=[], mode='verification_failed', model=None,
                        validation={'status': 'failed', 'issues': errors}, fallback={'reason': reason, 'llm_attempted': reason not in {'model_warming', 'model_busy'}})
        mode, method = 'computed_fallback', 'deterministic_calculation'
        checks = ['numeric_sort', 'course_scope', 'requested_count', 'semester', 'citations', 'numbers']
    else:
        for i, hit in enumerate(sources, 1):
            meta = hit['metadata']
            header = meta.get('name', '資料')
            if meta.get('semester'):
                header += f"（{meta['semester']}）"
            # This is a labeled verbatim excerpt, not a generated conclusion.
            content = hit['content']
            if '【評分方式】' in content and re.search(r'評分|配分|grading', prepared['question'], re.I):
                excerpt = content.split('【評分方式】', 1)[1].strip()
            else:
                excerpt = content.strip()
            displayed = excerpt[:1000]
            if not displayed or displayed not in content:
                continue
            suffix = '\n…（節錄）' if len(excerpt) > 1000 else ''
            statements.append({'text': f'{header}\n資料原文：\n{displayed}{suffix}', 'citations': [i]})
        mode, method = 'structured_fallback', 'verbatim_local_sources'
        checks = ['source_identity', 'verbatim_excerpt', 'requested_scope']
    answer = '\n\n'.join(s['text'] + ' ' + ''.join(f'[{i}]' for i in s['citations']) for s in statements)
    if not answer:
        answer = '現有資料找不到符合條件的內容，請補充完整課名、教師姓名或學期後再查詢。'
    course_count = len({s['metadata'].get('record_id') or (s['metadata'].get('name'), s['metadata'].get('semester'))
                        for s in sources if s['metadata'].get('source') == 'course'})
    return dict(answer=answer, sources=[dict(s, citation=i) for i, s in enumerate(sources, 1)], mode=mode,
                semester=intent.semester, model=None,
                validation={'status': 'data_checked' if statements else 'no_evidence', 'method': method, 'llm_reviewed': False,
                            'course_count': course_count, 'requested_count': intent.requested_count, 'checks': checks},
                fallback={'reason': reason, 'llm_attempted': reason not in {'model_warming', 'model_busy'}})
