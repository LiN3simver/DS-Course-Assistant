"""建立或更新本地中文索引；保留原本 langchain collection。"""
import json
import sys
from scu_assistant.data import load_records, quality_report
from scu_assistant.index import LocalIndex
from scu_assistant.settings import Settings


def load_and_format_data():
    return load_records()


def build_vector_database():
    result = LocalIndex(Settings()).build()
    print(json.dumps(dict(result, data=quality_report()), ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    build_vector_database()
