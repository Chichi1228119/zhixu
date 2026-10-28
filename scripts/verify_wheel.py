"""Install a wheel outside its source tree and exercise the public CLI and API.

Uses a new venv and the caller's normal pip index/cache. No model downloads or API
keys are required. Pass --find-links for an offline wheelhouse.
"""
import argparse
from contextlib import contextmanager
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


SERVER = '''import json, os, socket, threading, time
from pathlib import Path
import app, uvicorn
assert Path(app.__file__).resolve().is_relative_to(Path(os.environ["ZHIXU_VERIFY_VENV"]).resolve())
sock=socket.socket(); sock.bind(("127.0.0.1",0)); sock.listen()
Path("worker.json").write_text(json.dumps({"port":sock.getsockname()[1],"pid":os.getpid()}))
server=uvicorn.Server(uvicorn.Config("app.main:create_app",factory=True,log_level="warning",access_log=False,timeout_graceful_shutdown=5))
def shutdown():
    while not Path("stop.txt").exists(): time.sleep(.1)
    server.should_exit=True
threading.Thread(target=shutdown,daemon=True).start()
try: server.run(sockets=[sock])
finally: sock.close()
'''

BOOTSTRAP = '''import getpass, json, os
from pathlib import Path
import app
from app.cli import main
from app.identity import IdentityStore
assert Path(app.__file__).resolve().is_relative_to(Path(os.environ["ZHIXU_VERIFY_VENV"]).resolve())
getpass.getpass=lambda *args,**kwargs: os.environ["ZHIXU_VERIFY_PASSWORD"]
assert main(["admin","init","--data-dir",os.environ["ZHIXU_DATA_DIR"],"--username","wheel-owner"])==0
store=IdentityStore(Path(os.environ["ZHIXU_DATA_DIR"])/"control.db")
viewer=store.create_user("wheel-viewer",os.environ["ZHIXU_VERIFY_PASSWORD"])
owner=next(user for user in store.list_users() if user["is_admin"])
allowed=store.workspaces_for(owner["id"])[0]
denied=store.create_workspace("Isolated workspace")
store.grant(allowed["id"],viewer["id"],"viewer")
Path("identities.json").write_text(json.dumps({"allowed":allowed["id"],"denied":denied["id"]}))
'''


def _client():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _request(client, base, path, method='GET', payload=None, headers=None, expected=200, timeout=15):
    fields = {'Origin': base, **(headers or {})}
    data = None
    if payload is not None:
        fields['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(base + path, data=data, headers=fields, method=method)
    try:
        response = client.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        status = response.code
        body = response.read(4 * 1024 * 1024 + 1)
    if status != expected:
        raise AssertionError(f'{method} {path}: expected HTTP {expected}, received {status}')
    if len(body) > 4 * 1024 * 1024:
        raise AssertionError('Wheel response exceeded the verification budget.')
    return json.loads(body) if body else None


def _run(command, cwd, env, label, timeout=180):
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        else:
            process.kill()
        process.communicate(timeout=10)
        raise RuntimeError(f'Installed-wheel {label} timed out after {timeout} seconds.') from None
    if process.returncode:
        detail = stderr + stdout
        password = env.get('ZHIXU_VERIFY_PASSWORD')
        if password:
            detail = detail.replace(password, '[redacted]')
        raise RuntimeError(f'Installed-wheel {label} failed:\n{detail}')
    return stdout.strip()


def _port_open(port):
    if not port:
        return False
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=.3):
            return True
    except OSError:
        return False


@contextmanager
def _server(python, cwd, data_dir, env, enterprise=False):
    cwd.mkdir()
    script = cwd / 'serve.py'
    script.write_text(SERVER, encoding='utf-8')
    server_env = {**env, 'ZHIXU_DATA_DIR': str(data_dir), 'ZHIXU_ENTERPRISE': '1' if enterprise else '0'}
    process = None
    worker = {}
    with (cwd / 'server.log').open('wb') as log:
        try:
            process = subprocess.Popen([str(python), str(script)], cwd=cwd, env=server_env,
                stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            client = _client()
            deadline = time.monotonic() + 60
            last_error = 'worker metadata not yet available'
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('Wheel server exited: ' + (cwd / 'server.log').read_text(encoding='utf-8', errors='replace'))
                try:
                    worker = json.loads((cwd / 'worker.json').read_text())
                    base = 'http://127.0.0.1:' + str(worker['port'])
                    health = _request(client, base, '/api/health', timeout=1)
                    break
                except (OSError, ValueError, urllib.error.URLError) as error:
                    last_error = f'{type(error).__name__}: {str(error)[:200]}'
                    time.sleep(.2)
            else:
                raise RuntimeError(f'Wheel server did not become ready: {last_error}; worker metadata available={bool(worker)}. '
                                   + (cwd / 'server.log').read_text(encoding='utf-8', errors='replace')[-2000:])
            yield base, health
        finally:
            (cwd / 'stop.txt').touch()
            if process:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if process.poll() is not None and not _port_open(worker.get('port')):
                        break
                    time.sleep(.1)
                else:
                    # The PID comes from this private child's file, not a port
                    # owner search. Terminate the actual worker before its Windows shim.
                    if worker.get('pid'):
                        try:
                            os.kill(worker['pid'], signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=5)
                    closed_deadline = time.monotonic() + 5
                    while _port_open(worker.get('port')) and time.monotonic() < closed_deadline:
                        time.sleep(.1)
                    if _port_open(worker.get('port')):
                        if sys.exc_info()[0] is None:
                            raise RuntimeError('The installed-wheel worker did not stop.')
                        print('Cleanup warning: worker port did not close within the cleanup budget.', file=sys.stderr)


def _personal(python, root, env):
    client = _client()
    with _server(python, root / 'personal-server', root / 'personal-data', env) as (base, health):
        assert health['version'] == '1.2.0' and health['document_count'] == 0
        assert Path(health['data_location']).samefile(root / 'personal-data')
        for path in ['/', '/static/app.js', '/api/config-template']:
            with client.open(base + path, timeout=5) as response:
                assert response.status == 200
        assert _request(client, base, '/api/lessons')['lessons']
        assert len(_request(client, base, '/api/demo/restore', method='POST')['documents']) == 8
        answer = _request(client, base, '/api/ask', method='POST', payload={'question': '试用期多久？'})
        assert answer['mode'] == 'extractive' and answer['sources']
    print('PASS: isolated install, packaged resources/demo, personal HTTP and source-backed answer.', flush=True)


def _login(client, base, username, password):
    state = _request(client, base, '/api/auth/login', method='POST',
                     payload={'username': username, 'password': password})
    assert state['authenticated'] is True and state['user']['username'] == username
    return state


def _enterprise(python, root, env):
    password = secrets.token_urlsafe(32)
    data_dir = root / 'team-data'
    bootstrap_env = {**env, 'ZHIXU_DATA_DIR': str(data_dir), 'ZHIXU_VERIFY_PASSWORD': password}
    _run([str(python), '-c', BOOTSTRAP], root, bootstrap_env, 'bootstrap')
    spaces = json.loads((root / 'identities.json').read_text())
    owner, viewer = _client(), _client()
    with _server(python, root / 'team-server', data_dir, env, enterprise=True) as (base, health):
        assert health['version'] == '1.2.0' and health['enterprise'] is True
        assert 'document_count' not in health and 'data_location' not in health
        _request(_client(), base, '/api/documents', expected=401)
        administrator = _login(owner, base, 'wheel-owner', password)
        owner_headers = {'X-CSRF-Token': administrator['csrf_token'], 'X-Workspace-ID': spaces['allowed']}
        assert _request(owner, base, '/api/documents', headers=owner_headers)['documents'] == []
        _request(owner, base, '/api/demo/restore', method='POST',
                 headers={'X-Workspace-ID': spaces['allowed']}, expected=403)
        assert len(_request(owner, base, '/api/demo/restore', method='POST', headers=owner_headers)['documents']) == 8
        documents = _request(owner, base, '/api/documents', headers=owner_headers)['documents']
        document_ids = {document['id'] for document in documents}
        _request(owner, base, '/api/documents/' + documents[0]['id'],
                 headers={**owner_headers, 'X-Workspace-ID': spaces['denied']}, expected=404)
        reader = _login(viewer, base, 'wheel-viewer', password)
        viewer_headers = {'X-CSRF-Token': reader['csrf_token'], 'X-Workspace-ID': spaces['allowed']}
        assert len(_request(viewer, base, '/api/documents', headers=viewer_headers)['documents']) == 8
        answer = _request(viewer, base, '/api/ask', method='POST',
                          payload={'question': '试用期多久？', 'mode': 'extractive'}, headers=viewer_headers)
        assert answer['sources'] and answer['mode'] == 'extractive'
        assert all(source['document_id'] in document_ids for source in answer['sources'])
        _request(viewer, base, '/api/demo/restore', method='POST', headers=viewer_headers, expected=403)
        _request(viewer, base, '/api/documents',
                 headers={**viewer_headers, 'X-Workspace-ID': spaces['denied']}, expected=403)
        _request(viewer, base, '/api/admin/users', headers=viewer_headers, expected=403)
    print('PASS: installed CLI bootstrap via getpass test double; enterprise startup, 401, cookie login, CSRF, viewer 403, workspace isolation and authorized answer.', flush=True)
    archive, restored = root / 'team-backup.zip', root / 'restored-data'
    _run([str(python), '-m', 'app.cli', 'backup', 'create', '--data-dir', str(data_dir), '--output', str(archive)], root, env, 'backup create')
    _run([str(python), '-m', 'app.cli', 'backup', 'restore', '--archive', str(archive), '--destination', str(restored)], root, env, 'backup restore')
    with _server(python, root / 'restored-server', restored, env, enterprise=True) as (base, _):
        probe = urllib.request.Request(base + '/api/documents')
        for handler in owner.handlers:
            if isinstance(handler, urllib.request.HTTPCookieProcessor):
                handler.cookiejar.add_cookie_header(probe)
        assert 'zhixu_session=' in (probe.get_header('Cookie') or '')
        _request(owner, base, '/api/documents', headers={'X-Workspace-ID': spaces['allowed']}, expected=401)
        fresh = _client()
        account = _login(fresh, base, 'wheel-viewer', password)
        headers = {'X-CSRF-Token': account['csrf_token'], 'X-Workspace-ID': spaces['allowed']}
        recovered = _request(fresh, base, '/api/documents', headers=headers)['documents']
        assert {document['id'] for document in recovered} == document_ids
        _request(fresh, base, '/api/documents', headers={**headers, 'X-Workspace-ID': spaces['denied']}, expected=403)
    print('PASS: installed CLI backup/restore preserves documents and membership; old session is rejected and fresh login works.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel-dir', type=Path, default=Path('dist'))
    parser.add_argument('--find-links', type=Path)
    args = parser.parse_args()
    wheels = list(args.wheel_dir.resolve().glob('zhixu_knowledge_assistant-*.whl'))
    if len(wheels) != 1:
        parser.error('Expected exactly one zhixu wheel in --wheel-dir.')
    env = {key: value for key, value in os.environ.items()
           if key not in {'PYTHONPATH', 'PYTHONHOME'} and not key.startswith(('RAG_', 'ZHIXU_'))}
    env['PYTHONPATH'] = ''
    env['PYTHONIOENCODING'] = 'utf-8'
    with tempfile.TemporaryDirectory(prefix='zhixu-wheel-') as directory:
        root = Path(directory)
        environment = root / 'venv'
        _run([sys.executable, '-m', 'venv', str(environment)], root, env, 'venv creation')
        python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        cli = environment / ('Scripts/zhixu.exe' if os.name == 'nt' else 'bin/zhixu')
        env['ZHIXU_VERIFY_VENV'] = str(environment)
        install = [str(python), '-m', 'pip', 'install', '--disable-pip-version-check', str(wheels[0])]
        if args.find_links:
            install += ['--no-index', '--find-links', str(args.find_links.resolve())]
        print('CHECK: installing release wheel into one fresh venv.', flush=True)
        _run(install, root, env, 'installation', timeout=600)
        assert _run([str(cli), '--version'], root, env, 'CLI version') == 'zhixu 1.2.0'
        _personal(python, root, env)
        _enterprise(python, root, env)


if __name__ == '__main__':
    main()

