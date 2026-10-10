"""Authenticated loopback-only UI for a single explicitly selected local workspace.

No cloud, CDN, arbitrary-file endpoint, active HTML import, or external PDF action.
Session tokens are per launch, in URL fragments (not HTTP query/logs), then held
in browser memory. This is not protection against a hostile local account or OS.
"""
from __future__ import annotations

import argparse
import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
from pathlib import Path
import secrets
import threading
import webbrowser

from .workspace import Workspace

MAX_REQUEST = 8 * 1024 * 1024
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8')}
CSP = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, workspace: Workspace, port: int = 0):
        self.workspace = workspace
        self.token = secrets.token_urlsafe(32)
        self.connection_slots = threading.BoundedSemaphore(16)
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = f'http://127.0.0.1:{self.server_port}'
        self.expected_host = f'127.0.0.1:{self.server_port}'

    def process_request(self, request, client_address):
        if not self.connection_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connection_slots.release()

    def server_close(self):
        self.workspace.close()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    server_version = 'EZCTD-local'

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):
        # URLs, paths and session credentials must not enter routine access logs.
        return

    def _send(self, status, body, mime='application/json; charset=utf-8'):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', CSP)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _host(self) -> bool:
        return self.headers.get_all('Host', []) == [self.server.expected_host]

    def do_GET(self):
        if not self._host():
            self._send(403, {'error': 'Unrecognized local host'})
            return
        if self.path not in ASSETS:
            self._send(404, {'error': 'Not found'})
            return
        name, mime = ASSETS[self.path]
        self._send(200, files('ezctd').joinpath('web', name).read_bytes(), mime)

    def do_POST(self):
        auth = self.headers.get_all('Authorization', [])
        if (not self._host() or self.headers.get_all('Origin', []) != [self.server.origin]
                or len(auth) != 1 or not hmac.compare_digest(auth[0], 'Bearer ' + self.server.token)
                or self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin', 'none')):
            self._send(403, {'error': 'Unauthorized local session or cross-origin request'})
            return
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            self._send(415, {'error': 'JSON content type required'})
            return
        try:
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or not lengths[0].isdigit() or self.headers.get('Transfer-Encoding'):
                raise ValueError('One finite content length is required')
            size = int(lengths[0])
            if not 0 < size <= MAX_REQUEST:
                raise ValueError('Request exceeds the 8 MiB limit')
            data = self.rfile.read(size)
            if len(data) != size:
                raise ValueError('Incomplete request body')
            payload = json.loads(data.decode('utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
            if not isinstance(payload, dict):
                raise ValueError('JSON object required')
            result = self._route(payload)
            self._send(200, result)
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
            message = str(exc)
            error = {'error': message[:2000], 'error_type': type(exc).__name__}
            if any(signal in message.lower() for signal in
                   ('source_changed', 'source changed', 'input changed', 'identity mismatch')):
                error['error_code'] = 'SOURCE_CHANGED'
            self._send(400, error)
        except Exception:
            self._send(500, {'error': 'Internal operation failed; no successful result is asserted'})

    def _route(self, p):
        w = self.server.workspace
        if self.path == '/api/session':
            return w.session()
        if self.path == '/api/details':
            return w.details(p['id'])
        if self.path == '/api/page':
            page, dpi, query = p.get('page', 1), p.get('dpi', 120), p.get('query')
            if type(page) is not int or page < 1 or type(dpi) is not int or not 36 <= dpi <= 300:
                raise ValueError('Invalid physical page or DPI')
            if query is not None and (not isinstance(query, str) or not 1 <= len(query) <= 256):
                raise ValueError('Invalid query')
            return w.document_action(p['id'], 'view-page', page=page, dpi=dpi, query=query)
        if self.path == '/api/navigation':
            return w.document_action(p['id'], 'navigation')
        if self.path == '/api/thumbnail':
            page = p.get('page', 1)
            if type(page) is not int or page < 1:
                raise ValueError('Invalid physical page')
            return w.document_action(p['id'], 'thumbnail', page=page)
        if self.path == '/api/search':
            start_page, page_limit, query = p.get('start_page', 1), p.get('page_limit', 200), p.get('query')
            if type(start_page) is not int or start_page < 1:
                raise ValueError('Invalid search start page')
            if type(page_limit) is not int or not 1 <= page_limit <= 2000:
                raise ValueError('Search page limit must be between 1 and 2000')
            if not isinstance(query, str) or not 1 <= len(query) <= 256 or '\x00' in query:
                raise ValueError('Invalid query')
            return w.document_action(p['id'], 'search-document', query=query,
                                     start_page=start_page, page_limit=page_limit)
        if self.path == '/api/history':
            return w.job_history()
        if self.path == '/api/retry':
            return {'job_id': w.retry(p['id'])}
        if self.path == '/api/context':
            w.set_context(p['id'], p['context'])
            return {'saved': True}
        if self.path in ('/api/scan', '/api/plan'):
            return {'job_id': w.start(self.path.rsplit('/', 1)[1], p['ids'])}
        if self.path == '/api/apply':
            return {'job_id': w.start('apply', plan_id=p['plan_id'], confirmed=p.get('confirmed'))}
        if self.path == '/api/job':
            job = w.job(p['id'], include_results=False)
            if job['status'] not in ('QUEUED', 'RUNNING', 'FINALIZING') or p.get('include_results') is True:
                full = w.job(p['id'])
                # UI receives compact rows; complete per-page proofs remain on disk.
                job['results'] = [{k: v for k, v in row.items() if k not in ('result', 'proof')}
                                  for row in full['results']]
                for src, dst in zip(full['results'], job['results'], strict=True):
                    if 'proof' in src:
                        dst['proof'] = {k: src['proof'][k] for k in
                                        ('page_count', 'verification_status', 'output_sha256')}
            return job
        if self.path == '/api/cancel':
            w.cancel(p['id'])
            return {'cancel_requested': True}
        if self.path == '/api/report':
            if not isinstance(p.get('report_base64'), str):
                raise ValueError('Base64 report bytes required to preserve original encoding and BOM')
            return w.import_report(base64.b64decode(p['report_base64'], validate=True))
        raise ValueError('Unknown API action; arbitrary filesystem operations are not supported')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='EZCTD local CRO PDF workspace')
    parser.add_argument('--root', type=Path)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--rulepack', type=Path)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    if args.root is None or args.workspace is None:
        # The UI grants no arbitrary path access. Root selection happens locally at startup.
        import tkinter as tk
        from tkinter import filedialog
        dialog = tk.Tk()
        dialog.withdraw()
        source = str(args.root) if args.root else filedialog.askdirectory(title='选择临床 PDF 输入文件夹（只读）')
        output = str(args.workspace) if args.workspace else filedialog.askdirectory(title='选择独立工作目录（不能在输入目录内）')
        dialog.destroy()
        if not source or not output:
            return 0
        args.root, args.workspace = Path(source), Path(output)
    from .cli import _default_rulepack
    workspace = Workspace(args.root, args.workspace, args.rulepack or _default_rulepack())
    with LocalServer(workspace, args.port) as server:
        url = server.origin + '/#key=' + server.token
        print('EZCTD local workspace (keep this session URL private):\n' + url, flush=True)
        print('Close the terminal or press Ctrl+C to stop. Source PDFs are not overwritten.', flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever(poll_interval=0.1)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
