"""Validate scope, citations, numbers and the model's evidence review."""
import re

from .intent import course_name, normalize


def validate_statements(statements, sources, intent, catalog, max_statements=10):
    errors = []
    if not isinstance(statements, list) or not 1 <= len(statements) <= max_statements:
        return ['invalid_statements']
    allowed_names = {normalize(course_name(s['metadata']['name'])) for s in sources
                     if s['metadata'].get('source') == 'course' and s['metadata'].get('name')}
    all_names = {normalize(course_name(r['course_name'])) for r in catalog}
    seen_names = set()
    used_citations = set()
    for statement in statements:
        if not isinstance(statement, dict) or not isinstance(statement.get('text'), str) or not statement['text'].strip():
            errors.append('invalid_statement'); continue
        citations = statement.get('citations')
        if not isinstance(citations, list) or not citations or any(type(i) is not int or not 1 <= i <= len(sources) for i in citations):
            errors.append('invalid_citation'); continue
        used_citations.update(citations)
        text = normalize(statement['text'])
        mentioned = {name for name in all_names if name in text}
        # Ignore a shorter title embedded in a longer valid title.
        mentioned = {name for name in mentioned if not any(name != other and name in other for other in mentioned)}
        seen_names.update(mentioned)
        if mentioned - allowed_names:
            errors.append('unrequested_course')
        evidence = [sources[i - 1] for i in citations]
        cited_names = {normalize(course_name(s['metadata'].get('name', ''))) for s in evidence}
        if mentioned and not mentioned <= cited_names:
            errors.append('course_citation_mismatch')
        professor_names = {s['metadata'].get('name') for s in sources if s['metadata'].get('source') == 'professor'}
        named_professors = {name for name in professor_names if name and normalize(name) in text}
        if named_professors and not named_professors <= {s['metadata'].get('name') for s in evidence}:
            errors.append('professor_citation_mismatch')
        # Numbers in a factual paragraph must occur in the cited evidence.
        # Numbered-list prefixes and source markers are formatting, not claims.
        factual_text = re.sub(r'^\s*\d+[.、)]\s*', '', statement['text'])
        factual_text = re.sub(r'\[\d+\]', '', factual_text)
        factual_text = re.sub(r'(\d+)\s*(?:堂|門|筆|courses?\b)',
            lambda m: '' if int(m[1]) in {intent.requested_count, len(allowed_names)} else m[0], factual_text, flags=re.I)
        cited_numbers = {float(number) for s in evidence for number in re.findall(r'\d+(?:\.\d+)?', s['content'])}
        if any(float(number) not in cited_numbers for number in re.findall(r'\d+(?:\.\d+)?', factual_text)):
            errors.append('unsupported_number')
        percentages = {float(n) for s in evidence for n in re.findall(r'(\d+(?:\.\d+)?)\s*%', s['content'])}
        if any(float(n) not in percentages for n in re.findall(r'(\d+(?:\.\d+)?)\s*%', factual_text)):
            errors.append('unsupported_percentage')
        averages = {s['metadata']['average_score'] for s in evidence if 'average_score' in s['metadata']}
        stated_averages = re.findall(r'(?:平均(?:成績|分數)?|average(?:\s+score)?)(?:\s*(?:為|是|達|約|:|：|is|was|of))?\s*(\d+(?:\.\d+)?)', factual_text, re.I)
        if averages and any(float(n) not in averages for n in stated_averages):
            errors.append('wrong_average')
        if any(s['metadata'].get('average_score') is not None for s in evidence):
            positive_claims = re.sub(r'(?:不代表|不等於|不能推論|並非|不意味著)[^。！!\n]*', '', statement['text'])
            if re.search(r'(?<!不)(?<!不能)(?<!無法)(?:一定|保證|絕對).{0,8}(?:好過|容易|高分|甜|及格)', positive_claims):
                errors.append('unsupported_grade_guarantee')
    if intent.requested_count and allowed_names:
        if len(seen_names) > intent.requested_count:
            errors.append('too_many_courses')
        expected = min(intent.requested_count, len(allowed_names))
        if len(seen_names) < expected:
            errors.append('missing_requested_courses')
    if intent.semester:
        if any(sources[i - 1]['metadata'].get('source') == 'course' and
               sources[i - 1]['metadata'].get('semester') != intent.semester for i in used_citations):
            errors.append('wrong_semester')
    if intent.direction and allowed_names:
        combined = '\n'.join(s.get('text', '') for s in statements if isinstance(s, dict))
        scores = {float(n) for n in re.findall(r'\d+(?:\.\d+)?', combined)}
        expected_scores = {s['metadata']['average_score'] for s in sources if 'average_score' in s['metadata']}
        if not expected_scores <= scores:
            errors.append('missing_rank_scores')
        if not re.search(r'歷史|平均|現有資料|historical|average', combined, re.I):
            errors.append('missing_ranking_basis')
        if not intent.semester and any(normalize(s['metadata'].get('semester', '')) not in normalize(combined) for s in sources):
            errors.append('missing_semester_disclosure')
        if not re.search(r'不代表|不保證|不能保證|不能推論|不等於|僅供|cannot|does not|not guarantee', combined, re.I):
            errors.append('missing_grade_caveat')
    return sorted(set(errors))
