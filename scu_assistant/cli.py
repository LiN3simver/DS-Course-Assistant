import argparse
import json
import sys

from .service import Assistant


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='本地東吳課程與師資問答')
    parser.add_argument('question', nargs='?')
    parser.add_argument('--semester')
    parser.add_argument('--top-k', type=int, default=4)
    parser.add_argument('--health', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    bot = Assistant()
    try:
        if args.health:
            health = bot.health()
            print(json.dumps(health, ensure_ascii=False, indent=2))
            return 0 if health['ready'] else 1
        history = []
        while True:
            question = args.question or input('你（exit 離開）> ').strip()
            if question.lower() in {'exit', 'quit', '離開'}:
                break
            if not question:
                continue
            result = bot.ask(question, top_k=args.top_k, semester=args.semester, history=history)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print('\n' + result['answer'])
                print('\n來源：')
                for source in result['sources']:
                    meta = source['metadata']
                    print(f"[{source['citation']}] {meta['name']} | {meta.get('semester', '師資')} | {meta['filename']}")
                    if meta.get('profile_url'):
                        print(meta['profile_url'])
                print()
            if args.question:
                break
            history.extend([{'role': 'user', 'content': question},
                            {'role': 'assistant', 'content': result['answer'][:2000]}])
            history = history[-6:]
    except (RuntimeError, ValueError) as exc:
        print(f'錯誤：{exc}', file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('\n結束對話。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
