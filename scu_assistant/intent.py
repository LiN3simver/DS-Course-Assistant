"""Hard query constraints, kept separate from the retrieval chunk budget."""
from dataclasses import asdict, dataclass
import re
import unicodedata


def normalize(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(text))).lower()


def course_name(value):
    parts = str(value or '').split()
    return parts[0] if parts else ''


def count_number(value):
    digits = {'一': 1, '二': 2, '兩': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
              'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}
    if value.isdigit():
        return int(value)
    if value.lower() in digits:
        return digits[value.lower()]
    if '十' in value:
        tens, ones = value.split('十', 1)
        return digits.get(tens, 1) * 10 + digits.get(ones, 0)
    return None


@dataclass
class Intent:
    requested_count: int | None
    named_courses: list[str]
    direction: str | None
    semester: str | None

    def to_dict(self):
        return asdict(self)


def parse_intent(question, courses, direction=None, semester=None):
    text = normalize(question)
    names = sorted({course_name(r['course_name']) for r in courses}, key=len, reverse=True)
    named = []
    for name in names:
        if normalize(name) in text and not any(normalize(name) in normalize(n) for n in named):
            named.append(name)
    # Common shortened course names are accepted only for a course-specific
    # question; a topic recommendation must remain a broader search.
    if not named and re.search(r'評分|給分|平均|成績|課程內容|大綱|怎麼教', question) and not re.search(r'推薦|相關|想學', question):
        for alias, full in [('資料結構', '資料結構與演算法'), ('機器學習', '機器學習導論')]:
            if alias in question and full in names:
                named.append(full)
    count = None
    for pattern in [r'(?:前|top\s*)(\d+|[一二兩三四五六七八九十]{1,3})',
                    r'(\d+|[一二兩三四五六七八九十]{1,3})\s*(?:堂|門|個課程|筆課程)',
                    r'\b(one|two|three|four|five|\d+)\s+courses?\b']:
        match = re.search(pattern, question, re.I)
        if match:
            count = count_number(match[1]); break
    if count is not None and not 1 <= count <= 20:
        raise ValueError('請指定 1 到 20 堂課。')
    if count is None:
        if named:
            count = len(named)
        elif re.search(r'哪(?:一)?(?:堂|門)|只要一|單一|\b(?:which course|a course|single course)\b', question, re.I):
            count = 1
        elif re.search(r'哪(?:一)?位(?:老師|教授|教師)', question):
            count = 1
        elif direction:
            count = 3 if re.search(r'哪些|有哪些|排名|排行|排序|courses\b', question, re.I) else 1
    return Intent(count, named, direction, semester)


def constrain_sources(sources, intent):
    """A requested course count is a count of records, never a chunk count."""
    hits = list(sources)
    if intent.requested_count and hits and all(s['metadata'].get('source') == 'professor' for s in hits):
        names = list(dict.fromkeys(s['metadata'].get('name') for s in hits))[:intent.requested_count]
        hits = [s for s in hits if s['metadata'].get('name') in names]
    if intent.semester:
        hits = [s for s in hits if s['metadata'].get('source') != 'course' or s['metadata'].get('semester') == intent.semester]
    if intent.named_courses:
        wanted = {normalize(name) for name in intent.named_courses}
        hits = [s for s in hits if s['metadata'].get('source') == 'course'
                and normalize(course_name(s['metadata'].get('name', ''))) in wanted]
        # For a named course without a semester, use the latest available
        # offering and make that semester visible in the evidence.
        if not intent.semester:
            latest = {}
            for s in hits:
                name = normalize(course_name(s['metadata']['name']))
                latest[name] = max(latest.get(name, ''), s['metadata'].get('semester', ''))
            hits = [s for s in hits if s['metadata'].get('semester', '') == latest[normalize(course_name(s['metadata']['name']))]]
    if intent.requested_count:
        allowed = []
        for s in hits:
            meta = s['metadata']
            if meta.get('source') != 'course':
                continue
            key = meta.get('record_id') or (meta.get('name'), meta.get('semester'), meta.get('course_code'))
            if key not in allowed and len(allowed) < intent.requested_count:
                allowed.append(key)
        hits = [s for s in hits if s['metadata'].get('source') != 'course' or
                (s['metadata'].get('record_id') or (s['metadata'].get('name'), s['metadata'].get('semester'), s['metadata'].get('course_code'))) in allowed]
    return hits
