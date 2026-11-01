from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

from .settings import ROOT


def clean(value) -> str:
    return re.sub(r'[\t \xa0]+', ' ', str(value or '')).strip()


@dataclass
class Record:
    id: str
    content: str
    metadata: dict


def load_courses(root: Path = ROOT) -> list[dict]:
    courses = []
    for path in sorted(root.glob('scu_courses_data_*.json')):
        match = re.fullmatch(r'scu_courses_data_(\d+)_(\d)\.json', path.name)
        if not match:
            continue
        year, term = map(int, match.groups())
        for item in json.loads(path.read_text(encoding='utf-8')):
            row = dict(item)
            for field in ('course_code', 'course_name', 'teacher'):
                row[field] = clean(row.get(field)) or '未知'
            score = row.get('average_score')
            row['average_score'] = float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score) and 0 <= score <= 100 else None
            row.update(year=year, term=term, semester=f'{year}-{term}', filename=path.name)
            row['record_id'] = f"course:{year}-{term}:{row['course_code']}"
            courses.append(row)
    return courses


def course_record(row: dict, summary: bool = False) -> Record:
    score = row['average_score']
    header = (f"學期：{row['semester']}\n課程名稱：{row['course_name']}\n"
              f"科目代碼：{row['course_code']}\n授課教師：{row['teacher']}\n"
              f"全班平均成績：{score if score is not None else '無資料'}\n")
    metadata = {k: row[k] for k in ('semester', 'year', 'term', 'course_code', 'teacher', 'filename', 'record_id')}
    metadata.update(source='course', name=row['course_name'])
    if score is not None:
        metadata['average_score'] = score
    if summary:
        return Record(row['record_id'], header, metadata)
    distribution = '\n'.join(f'{key} 分：{value} 人' for key, value in row.get('score_distribution', {}).items()) or '無資料'
    syllabus = row.get('syllabus') or {}
    content = (header + '\n【成績分布】\n' + distribution + '\n【課程內容】\n' +
               clean(syllabus.get('content')) + '\n【評分方式】\n' + clean(syllabus.get('grading')))
    return Record(row['record_id'], content, metadata)


def load_records(root: Path = ROOT) -> list[Record]:
    records = [course_record(row) for row in load_courses(root)]
    path = root / 'scu_professors_data.json'
    if path.exists():
        for row in json.loads(path.read_text(encoding='utf-8')):
            name = clean(row.get('name'))
            record_id = 'professor:' + hashlib.sha256(row['profile_url'].encode()).hexdigest()[:16]
            records.append(Record(record_id,
                f"教師姓名：{name}\n個人網頁：{row['profile_url']}\n【專長與簡歷】\n{clean(row.get('expertise_and_intro'))}",
                dict(source='professor', name=name, profile_url=row['profile_url'], filename=path.name, record_id=record_id)))
    return records


def quality_report(root: Path = ROOT) -> dict:
    courses = load_courses(root)
    records = load_records(root)
    return {
        'courses': len(courses), 'professors': sum(r.metadata['source'] == 'professor' for r in records),
        'semesters': sorted({row['semester'] for row in courses}),
        'missing_teacher': sum(row['teacher'] == '未知' for row in courses),
        'missing_average': sum(row['average_score'] is None for row in courses),
        'missing_syllabus': sum(not row.get('syllabus', {}).get('content') or row['syllabus']['content'] == '無資料' for row in courses),
    }
