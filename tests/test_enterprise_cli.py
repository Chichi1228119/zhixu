from pathlib import Path

import pytest

from app.cli import main


@pytest.fixture(autouse=True)
def isolated_cli_environment(monkeypatch):
    for key in ('ZHIXU_DATA_DIR', 'ZHIXU_MODEL_DIR', 'ZHIXU_REPORT_DIR', 'ZHIXU_ENTERPRISE', 'ZHIXU_SEED_DEMO', 'ZHIXU_HOST', 'ZHIXU_PORT'):
        monkeypatch.delenv(key, raising=False)


def test_admin_init_prompts_for_password_and_has_no_default(tmp_path, monkeypatch, capsys):
    from app.identity import IdentityStore
    answers = iter(['Synthetic-bootstrap-pass!', 'Synthetic-bootstrap-pass!'])
    monkeypatch.setattr('getpass.getpass', lambda prompt: next(answers))
    assert main(['admin', 'init', '--data-dir', str(tmp_path / 'data'), '--username', 'root-admin']) == 0
    store = IdentityStore(tmp_path / 'data' / 'control.db')
    assert store.list_users()[0]['username'] == 'root-admin'
    assert len(store.workspaces_for(store.list_users()[0]['id'])) == 1
    assert 'Synthetic-bootstrap-pass!' not in capsys.readouterr().out


def test_mismatched_bootstrap_password_does_not_create_account(tmp_path, monkeypatch):
    from app.identity import IdentityStore
    answers = iter(['Synthetic-bootstrap-pass!', 'different-password'])
    monkeypatch.setattr('getpass.getpass', lambda prompt: next(answers))
    assert main(['admin', 'init', '--data-dir', str(tmp_path / 'data'), '--username', 'root-admin']) == 1
    assert IdentityStore(tmp_path / 'data' / 'control.db').list_users() == []


def test_enterprise_serve_sets_explicit_mode_without_network_exposure(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    calls = []
    monkeypatch.setitem(sys.modules, 'uvicorn', SimpleNamespace(run=lambda *a, **k: calls.append(k)))
    monkeypatch.delenv('ZHIXU_ENTERPRISE', raising=False)
    assert main(['serve', '--enterprise', '--data-dir', str(tmp_path)]) == 0
    import os
    assert os.environ['ZHIXU_ENTERPRISE'] == '1'
    assert calls[0]['host'] == '127.0.0.1'


def test_backup_cli_roundtrip_to_new_directory(tmp_path):
    from app.identity import IdentityStore
    store = IdentityStore(tmp_path / 'source' / 'control.db')
    store.bootstrap('admin', 'Synthetic-backup-pass!')
    assert main(['backup', 'create', '--data-dir', str(tmp_path / 'source'), '--output', str(tmp_path / 'snapshot.zip')]) == 0
    assert main(['backup', 'restore', '--archive', str(tmp_path / 'snapshot.zip'), '--destination', str(tmp_path / 'restored')]) == 0
    assert IdentityStore(tmp_path / 'restored' / 'control.db').list_users()[0]['username'] == 'admin'


def test_cli_password_reset_revokes_existing_session(tmp_path, monkeypatch, capsys):
    from app.identity import IdentityStore
    identity = IdentityStore(tmp_path / 'data' / 'control.db')
    identity.bootstrap('admin', 'Synthetic-old-password!')
    token, *_ = identity.authenticate('admin', 'Synthetic-old-password!')
    answers = iter(['Synthetic-new-password!', 'Synthetic-new-password!'])
    monkeypatch.setattr('getpass.getpass', lambda prompt: next(answers))
    assert main(['admin', 'reset-password', '--data-dir', str(tmp_path / 'data'), '--username', 'admin']) == 0
    assert identity.resolve_session(token) is None
    assert identity.authenticate('admin', 'Synthetic-new-password!')
    assert 'Synthetic-new-password!' not in capsys.readouterr().out
