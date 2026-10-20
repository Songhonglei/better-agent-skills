"""A request-local process keeps existing single-project globals isolated."""
import json
import os
import sys


def main():
    from project_registry import project_entry
    code = sys.argv[1]
    project_entry(code)
    os.environ['OVK_PROJECT'] = code
    import readonly_mcp as legacy
    from pilot_state import StateError
    try:
        payload = json.load(sys.stdin)
        function = {'find': legacy.find, 'read': legacy.read,
                    'list': legacy.list_entries, 'tree': legacy.tree}[payload['tool']]
        result = function(**payload['arguments'])
        print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False))
    except (ValueError, StateError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
    except Exception:
        print(json.dumps({'ok': False, 'error': 'Project index unavailable; use local files and rg.'}))


if __name__ == '__main__':
    main()
