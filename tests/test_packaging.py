import importlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from types import SimpleNamespace
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_runtime_environment(monkeypatch):
    for name in ('ZHIXU_DATA_DIR', 'ZHIXU_MODEL_DIR', 'ZHIXU_REPORT_DIR',
                 'ZHIXU_SEED_DEMO', 'ZHIXU_HOST', 'ZHIXU_PORT'):
        monkeypatch.setenv(name, '')
        monkeypatch.delenv(name, raising=False)


def test_distribution_metadata_declares_pep517_cli_and_extras():
    metadata = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    assert metadata['build-system']['build-backend'] == 'setuptools.build_meta'
    project = metadata['project']
    assert project['name'] == 'zhixu-knowledge-assistant'
    assert project['requires-python'] == '>=3.12'
    assert project['license'] == 'MIT'
    assert project['scripts']['zhixu'] == 'app.cli:main'
    assert {'semantic', 'dev', 'authoring'} <= project['optional-dependencies'].keys()
    assert any(item.startswith('python-docx') for item in project['dependencies'])
    assert any(item.startswith('reportlab') for item in project['optional-dependencies']['authoring'])
    assert any(item.startswith('pypdfium2') for item in project['optional-dependencies']['authoring'])
    assert any(item.startswith('setuptools') for item in project['optional-dependencies']['dev'])
    assert any(item.startswith('wheel') for item in project['optional-dependencies']['dev'])


def test_version_is_110():
    assert importlib.import_module('app.version').__version__ == '1.2.0'


def test_default_paths_use_current_workspace_without_creating_directories(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = importlib.import_module('app.paths')
    paths = module.RuntimePaths.discover()
    assert paths.resource_root == Path(module.__file__).resolve().parent.parent
    assert paths.data_dir == tmp_path / 'data'
    assert paths.model_dir == tmp_path / 'models'
    assert paths.report_dir == tmp_path / 'reports'
    assert not paths.data_dir.exists()
    assert not paths.model_dir.exists()
    assert not paths.report_dir.exists()


def test_path_environment_and_explicit_precedence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = importlib.import_module('app.paths')
    monkeypatch.setenv('ZHIXU_DATA_DIR', str(tmp_path / 'env-data'))
    monkeypatch.setenv('ZHIXU_MODEL_DIR', str(tmp_path / 'env-models'))
    monkeypatch.setenv('ZHIXU_REPORT_DIR', str(tmp_path / 'env-reports'))
    environment = module.RuntimePaths.discover()
    assert environment.data_dir == tmp_path / 'env-data'
    assert environment.model_dir == tmp_path / 'env-models'
    assert environment.report_dir == tmp_path / 'env-reports'
    explicit = module.RuntimePaths.discover(data_dir=Path('chosen/data'), model_dir=Path('chosen/weights'))
    assert explicit.data_dir == tmp_path / 'chosen' / 'data'
    assert explicit.model_dir == tmp_path / 'chosen' / 'weights'
    assert explicit.report_dir == tmp_path / 'env-reports'


def test_model_and_report_defaults_follow_explicit_data_parent(tmp_path):
    paths = importlib.import_module('app.paths').RuntimePaths.discover(data_dir=tmp_path / 'chosen' / 'data')
    assert paths.model_dir == tmp_path / 'chosen' / 'models'
    assert paths.report_dir == tmp_path / 'chosen' / 'reports'


def test_resource_properties_are_package_local(tmp_path):
    paths = importlib.import_module('app.paths').RuntimePaths.discover(data_dir=tmp_path / 'data')
    package = paths.resource_root / 'app'
    assert paths.static_dir == package / 'static'
    assert paths.demo_dir == package / 'resources' / 'demo'
    assert paths.evaluation_dir == package / 'resources' / 'evaluation'
    assert paths.config_template_path == package / 'resources' / 'env.example'


def test_cli_version_exits_without_loading_server(capsys, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, 'uvicorn', SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs))))
    cli = importlib.import_module('app.cli')
    with pytest.raises(SystemExit) as result:
        cli.main(['--version'])
    assert result.value.code == 0
    assert capsys.readouterr().out.strip() == 'zhixu 1.2.0'
    assert calls == []


def test_cli_serve_defaults_are_local_and_do_not_seed_or_change_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setitem(sys.modules, 'uvicorn', SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs))))
    cli = importlib.import_module('app.cli')
    assert cli.main(['serve']) == 0
    assert calls == [(('app.main:create_app',), {'factory': True, 'host': '127.0.0.1', 'port': 18765, 'log_level': 'info'})]
    assert os.environ['ZHIXU_DATA_DIR'] == str(tmp_path / 'data')
    assert os.environ['ZHIXU_MODEL_DIR'] == str(tmp_path / 'models')
    assert os.environ['ZHIXU_SEED_DEMO'] == '0'
    assert os.environ['ZHIXU_HOST'] == '127.0.0.1'
    assert os.environ['ZHIXU_PORT'] == '18765'
    assert Path.cwd() == tmp_path
    assert not (tmp_path / 'data').exists()


def test_cli_explicit_paths_demo_and_loopback_options(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setitem(sys.modules, 'uvicorn', SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs))))
    cli = importlib.import_module('app.cli')
    cli.main(['serve', '--data-dir', 'chosen/data', '--model-dir', 'chosen/weights',
              '--demo', '--no-browser', '--host', '::1', '--port', '19123'])
    assert os.environ['ZHIXU_DATA_DIR'] == str(tmp_path / 'chosen' / 'data')
    assert os.environ['ZHIXU_MODEL_DIR'] == str(tmp_path / 'chosen' / 'weights')
    assert os.environ['ZHIXU_SEED_DEMO'] == '1'
    assert calls[0][1]['host'] == '::1'
    assert calls[0][1]['port'] == 19123
    assert Path.cwd() == tmp_path


def test_cli_uses_environment_directories_without_explicit_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv('ZHIXU_DATA_DIR', str(tmp_path / 'configured-data'))
    monkeypatch.setenv('ZHIXU_MODEL_DIR', str(tmp_path / 'configured-models'))
    monkeypatch.setenv('ZHIXU_REPORT_DIR', str(tmp_path / 'configured-reports'))
    monkeypatch.setitem(sys.modules, 'uvicorn', SimpleNamespace(run=lambda *args, **kwargs: None))
    importlib.import_module('app.cli').main(['serve', '--no-browser'])
    assert os.environ['ZHIXU_DATA_DIR'] == str(tmp_path / 'configured-data')
    assert os.environ['ZHIXU_MODEL_DIR'] == str(tmp_path / 'configured-models')
    assert os.environ['ZHIXU_REPORT_DIR'] == str(tmp_path / 'configured-reports')


def test_cli_without_command_shows_help(capsys):
    assert importlib.import_module('app.cli').main([]) == 0
    assert 'serve' in capsys.readouterr().out


@pytest.mark.parametrize('host', ['0.0.0.0', '192.168.1.8', 'example.com', '127.0.0.1.evil.test'])
def test_cli_rejects_non_loopback_without_starting_or_mutating_environment(host, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, 'uvicorn', SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs))))
    with pytest.raises(SystemExit) as result:
        importlib.import_module('app.cli').main(['serve', '--host', host])
    assert result.value.code == 2
    assert calls == []
    assert 'ZHIXU_DATA_DIR' not in os.environ


@pytest.mark.parametrize('port', ['0', '-1', '65536', 'not-a-port'])
def test_cli_rejects_invalid_port(port, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, 'uvicorn', SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs))))
    with pytest.raises(SystemExit) as result:
        importlib.import_module('app.cli').main(['serve', '--port', port])
    assert result.value.code == 2
    assert calls == []


def test_importing_cli_does_not_import_http_app():
    result = subprocess.run([sys.executable, '-c', "import sys; import app.cli; assert 'app.main' not in sys.modules"],
                            cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_wheel_contains_public_runtime_resources_and_no_private_directories(tmp_path):
    if importlib.util.find_spec('build') is None:
        pytest.skip('Install the dev extra to run the wheel build check.')
    required_resources = ['app/static/index.html', 'app/resources/demo/travel.md',
                          'app/resources/evaluation/cases.json', 'app/resources/env.example']
    if not all((ROOT / item).is_file() for item in required_resources) or not (ROOT / 'LICENSE').is_file():
        pytest.skip('Public resources or LICENSE have not been staged by the integration task yet.')
    source = tmp_path / 'source'
    source.mkdir()
    shutil.copytree(ROOT / 'app', source / 'app', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('pyproject.toml', 'README.md', 'LICENSE'):
        shutil.copy2(ROOT / name, source / name)
    for private in ('tests', 'data', 'models', 'reports', 'private'):
        directory = source / private
        directory.mkdir()
        (directory / 'must-not-ship.txt').write_text('private sentinel', encoding='utf-8')
    (source / '.env').write_text('SECRET=must-not-ship', encoding='utf-8')
    output = tmp_path / 'dist'
    result = subprocess.run([sys.executable, '-m', 'build', '--wheel', '--no-isolation', '--outdir', str(output)],
                            cwd=source, capture_output=True, text=True, encoding='utf-8', timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list(output.glob('*.whl'))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        assert set(required_resources + ['app/paths.py', 'app/cli.py', 'app/version.py']) <= set(names)
        assert not any('must-not-ship' in name or name.startswith(('tests/', 'data/', 'models/', 'reports/', 'private/')) for name in names)
        assert not any(name.endswith('/.env') or name == '.env' for name in names)
        entry = next(name for name in names if name.endswith('.dist-info/entry_points.txt'))
        assert 'zhixu = app.cli:main' in wheel.read(entry).decode('utf-8')
        metadata = next(name for name in names if name.endswith('.dist-info/METADATA'))
        content = wheel.read(metadata).decode('utf-8')
        assert 'Version: 1.2.0' in content
        assert 'License-Expression: MIT' in content
