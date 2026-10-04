"""
Verification harness for the AI arena advisor.

Exercises the real bot code paths (custom_core.ask_ollama,
config_logic.advisor_url_status, task_logic.arena_of_kings) against a stub
Ollama-compatible HTTP server, and optionally makes exactly one live query
against a real Ollama-compatible endpoint.

Usage:
    python3 tests/verify_advisor.py                       # stub verification only
    python3 tests/verify_advisor.py --live URL MODEL     # also: one live probe + one live battle query

Proven by the stub:
    a) a `FIGHT 73`-style answer flows into the arena decision (battle taken)
    b) a `CANCEL` answer flows through the fallback path (go_home + cooldown)
    c) the config dialog's URL verify accepts a non-Ollama base URL
    d) the screenshot is dropped gracefully when the model has no vision capability
"""
import ctypes
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer

# main/ targets Windows, where ctypes.windll exists. The macOS branch
# (separate work) removes the usage, but the module-level import still breaks
# non-Windows hosts. Provide a no-op stand-in so the core module is importable
# anywhere; it is only referenced inside get_active_windowtitle().
if not hasattr(ctypes, 'windll'):
    ctypes.windll = None  # pylint: disable=protected-access

SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
os.chdir(SRC_DIR)
sys.path.insert(0, SRC_DIR)

import numpy as np  # noqa: E402

import config_logic  # noqa: E402
import custom_core  # noqa: E402
import task_logic  # noqa: E402


class StubServer(ThreadingHTTPServer):
    """ Ollama-compatible stub server with scripted /api/chat answers """

    def __init__(self, profile: dict) -> None:
        """
        Args:
            profile (dict): 'version' and/or 'tags' entries; omit either to make
                that endpoint answer 404 (a non-Ollama server, e.g. LM Studio 0.3+)
        """
        super().__init__(('127.0.0.1', 0), AdvisorStub)
        self.advisor_profile = profile
        self.advisor_lock = threading.Lock()
        self.chat_script: list = []
        self.chat_requests: list = []

    def url(self) -> str:
        """ The stub base url on its free localhost port """
        return f'http://127.0.0.1:{self.server_address[1]}'

    def script(self, *answers) -> None:
        """ Queue scripted /api/chat answers (str) or errors (Exception) """
        self.chat_script.extend(answers)

    def start(self) -> None:
        """ Serve in the background """
        threading.Thread(target=self.serve_forever, daemon=True).start()


class AdvisorStub(BaseHTTPRequestHandler):
    """ HTTP handler for the Ollama-compatible stub server """

    def log_message(self, fmt, *args) -> None:
        """ Silence the default stderr logging """

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        """ Answer /api/version and /api/tags according to the stub profile """
        profile = self.server.advisor_profile  # pylint: disable=protected-access

        if self.path == '/api/version':
            if profile.get('version'):
                self._send(200, {'version': profile['version']})
            else:
                self._send(404, {'error': 'Unexpected endpoint or method. (GET /api/version)'})
            return

        if self.path == '/api/tags':
            if profile.get('tags'):
                self._send(200, {'models': profile['tags']})
            else:
                self._send(404, {'error': 'Unexpected endpoint or method. (GET /api/tags)'})
            return

        self._send(404, {'error': f'Unexpected endpoint or method. (GET {self.path})'})

    def do_POST(self) -> None:
        """ Serve the next scripted /api/chat answer and record the request """
        if self.path != '/api/chat':
            self._send(404, {'error': 'no such endpoint'})
            return

        request = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        last_message = request['messages'][-1]
        record = {
            'model': request.get('model'),
            'content': last_message.get('content', ''),
            'images': last_message.get('images', [])
        }
        with self.server.advisor_lock:  # pylint: disable=protected-access
            self.server.chat_requests.append(record)  # pylint: disable=protected-access
            if self.server.chat_script and self.server.chat_script[0] is not None:  # pylint: disable=protected-access
                answer = self.server.chat_script.pop(0)  # pylint: disable=protected-access
            else:
                answer = 'STUB: no scripted answer left'

        if isinstance(answer, Exception):
            self._send(500, {'error': str(answer)})
            return

        self._send(200, {
            'model': record['model'],
            'created_at': '2026-01-01T00:00:00Z',
            'message': {'role': 'assistant', 'content': str(answer)}
        })


def reset_advisor(url: str, model: str) -> None:
    """ Point the advisor at the given server/model and clear its chat cache """
    custom_core.config['ollama_url'] = url
    custom_core.config['ollama_model'] = model
    custom_core._ollama_cache = []  # pylint: disable=protected-access
    custom_core._model_vision_cache.clear()  # pylint: disable=protected-access


def run_arena() -> tuple:
    """
    Execute the real arena_of_kings() with screen/keyboard side effects stubbed,
    then restore every stubbed function.

    Returns:
        tuple: (arena return value, number of go_home calls)
    """
    calls = {'go_home': 0}
    screenshot = np.zeros((64, 64, 3), dtype=np.uint8)
    saved = {
        'page_wait': task_logic.page_wait,
        'go_home': task_logic.go_home,
        'press_key': task_logic.press_key,
        'grab_screen_to_mat': task_logic.grab_screen_to_mat,
        'text': custom_core.Region.text,
    }
    task_logic.page_wait = lambda page: True
    task_logic.go_home = lambda: calls.__setitem__('go_home', calls['go_home'] + 1)
    task_logic.press_key = lambda key: None
    task_logic.grab_screen_to_mat = lambda region=None: screenshot
    custom_core.Region.text = lambda self, *args, **kwargs: 'Opponent: Boris, Luana, Talia'
    try:
        return task_logic.arena_of_kings(), calls['go_home']
    finally:
        task_logic.page_wait = saved['page_wait']
        task_logic.go_home = saved['go_home']
        task_logic.press_key = saved['press_key']
        task_logic.grab_screen_to_mat = saved['grab_screen_to_mat']
        custom_core.Region.text = saved['text']


def check(label: str, condition: bool, detail: str = '') -> bool:
    """ Record one verification outcome and return whether it passed """
    mark = 'PASS' if condition else 'FAIL'
    suffix = f'  ({detail})' if detail else ''
    print(f'  [{mark}] {label}{suffix}')
    return bool(condition)


def stub_verification() -> bool:
    """ Run the four stub-based checks; returns True when all passed """
    tags = [
        {'name': 'llama3.2:latest', 'capabilities': ['completion']},
        {'name': 'qwen3.8:27b', 'capabilities': ['completion', 'vision']},
        {'name': 'llava:7b', 'capabilities': [], 'details': {'family': 'llava'}},
    ]
    all_ok = True
    screenshot = np.zeros((16, 16, 3), dtype=np.uint8)

    print('\n(a) FIGHT answer flows into the arena decision')
    server = StubServer({'version': '0.35.0', 'tags': tags})
    server.start()
    reset_advisor(server.url(), 'qwen3.8:27b')
    server.script('OK, ready', 'FIGHT 73')
    result, go_home_calls = run_arena()
    all_ok &= check('advisor answer parses as FIGHT 73', custom_core.parse_advisor_answer('FIGHT 73') == ('FIGHT', '73'))
    all_ok &= check('arena returned 0 (battle taken), no go_home', result == 0 and go_home_calls == 0, f'ret={result} go_home={go_home_calls}')
    all_ok &= check('chat reached the stub (handshake + battle query)', len(server.chat_requests) == 2 and server.chat_requests[-1]['content'].startswith('[aok]'))
    all_ok &= check('screenshot attached for a vision model', bool(server.chat_requests[-1]['images']), f"{len(server.chat_requests[-1]['images'])} chars")
    server.shutdown()

    print('\n(b) CANCEL answer flows through the fallback path')
    server = StubServer({'version': '0.35.0', 'tags': tags})
    server.start()
    reset_advisor(server.url(), 'qwen3.8:27b')
    custom_core.config['arena_advisor_cooldown'] = 600
    server.script('OK, ready', 'CANCEL 12')
    before = time.time()
    result, go_home_calls = run_arena()
    all_ok &= check('go_home called once', go_home_calls == 1, f'go_home={go_home_calls}')
    all_ok &= check('cooldown timestamp in the future', result > before + 590, f'ret={result - before:.0f}s from now')
    server.shutdown()

    print('\n    ...and a failed or unusable answer keeps the previous behavior')
    server = StubServer({'version': '0.35.0', 'tags': tags})
    server.start()
    reset_advisor(server.url(), 'qwen3.8:27b')
    server.script('OK, ready', RuntimeError('stub: model ran out of memory'))
    all_ok &= check('query failure answered FAIL', custom_core.ask_ollama('[aok] test') == 'FAIL')
    server.script('I cannot tell from that')
    result, go_home_calls = run_arena()
    all_ok &= check('unparseable answer: default flow, no go_home', result == 0 and go_home_calls == 0, f'ret={result} go_home={go_home_calls}')
    server.shutdown()

    print('\n(c) config dialog URL verify accepts a non-Ollama base URL')
    ollama_server = StubServer({'version': '0.35.0', 'tags': tags})
    lm_server = StubServer({'tags': [{'name': 'llama-3.2-11b-vision', 'capabilities': ['completion']}]})
    ollama_server.start()
    lm_server.start()
    all_ok &= check('Ollama url accepted (via /api/version)', config_logic.advisor_url_status(ollama_server.url()) == 'green')
    all_ok &= check('non-Ollama url accepted (via /api/tags only)', config_logic.advisor_url_status(lm_server.url()) == 'green')
    all_ok &= check('dead url rejected', config_logic.advisor_url_status('http://127.0.0.1:1') == 'red')
    ollama_server.shutdown()
    lm_server.shutdown()

    print('\n(d) vision image dropped gracefully for non-vision models')
    server = StubServer({'version': '0.35.0', 'tags': tags})
    server.start()

    reset_advisor(server.url(), 'llama3.2:latest')  # listed, but no vision capability
    server.script('OK, ready', 'FIGHT 55')
    answer = custom_core.ask_ollama('[aok] test', screenshot)
    all_ok &= check('query still answered (text-only)', answer == 'FIGHT 55', f'ans={answer!r}')
    all_ok &= check('no image attached', all(rec['images'] == [] for rec in server.chat_requests))

    server.chat_requests.clear()
    reset_advisor(server.url(), 'mystery:7b')  # not listed by the server at all
    server.script('OK, ready', 'FIGHT 60')
    answer = custom_core.ask_ollama('[aok] test', screenshot)
    all_ok &= check('model missing from /api/tags: query kept, no image', answer == 'FIGHT 60', f'ans={answer!r}')
    all_ok &= check('no image attached', all(rec['images'] == [] for rec in server.chat_requests))

    server.shutdown()

    down_server = StubServer({'version': '0.35.0'})  # /api/tags missing: probe fails
    down_server.start()
    reset_advisor(down_server.url(), 'llama3.2:latest')
    down_server.script('OK, ready', 'FIGHT 91')
    answer = custom_core.ask_ollama('[aok] test', screenshot)
    all_ok &= check('probe failure: text query still made', answer == 'FIGHT 91', f'ans={answer!r}')
    all_ok &= check('probe failure: no image attached', all(rec['images'] == [] for rec in down_server.chat_requests))
    down_server.shutdown()

    return all_ok


def live_verification(url: str, model: str) -> None:
    """
    Make exactly one live probe and one live battle query against a real
    Ollama-compatible endpoint (no retries).
    """
    print(f'\n(live) probing {url} / {model}')
    print(f'  url status: {config_logic.advisor_url_status(url)}')
    print(f'  model supports vision: {custom_core.advisor_model_supports_vision(url, model)}')

    reset_advisor(url, model)
    started = time.time()
    answer = custom_core.ask_ollama(
        '[aok]\nOpponent team: Boris (healer), Luana, Talia. My team is evenly matched.'
    )
    decision, chance = custom_core.parse_advisor_answer(answer)
    print(f'  live answer ({time.time() - started:.1f}s): {answer!r} -> decision={decision or "none"} chance={chance or "n/a"}')
    if decision == 'FIGHT':
        print('  arena flow would: take the battle')
    elif decision == 'CANCEL':
        print('  arena flow would: skip the arena and cool down')
    else:
        print('  arena flow would: fall back to the default behavior')


def main() -> int:
    """ Run the harness; returns 0 when every stub check passed """
    all_ok = stub_verification()

    if len(sys.argv) >= 4 and sys.argv[1] == '--live':
        try:
            live_verification(sys.argv[2], sys.argv[3])
        except Exception as error:
            print(f'  live attempt failed: {error!r} - the bot would fall back to its previous behavior')

    print('\n' + ('ALL STUB CHECKS PASSED' if all_ok else 'SOME STUB CHECKS FAILED'))
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
