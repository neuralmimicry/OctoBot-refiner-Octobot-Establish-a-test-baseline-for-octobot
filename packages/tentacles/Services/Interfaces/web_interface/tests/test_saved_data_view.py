"""Saved-data pages expose real progress without waiting for archive reads."""
import asyncio
import collections
import threading
import time

import flask
import pytest

import tentacles.Services.Interfaces.web_interface.controllers.backtesting as controller
import tentacles.Services.Interfaces.web_interface.models as exported_models
import tentacles.Services.Interfaces.web_interface.models.backtesting as models


@pytest.fixture
def isolated_view(monkeypatch):
    existing = models._data_file_view_future
    if existing is not None:
        existing.result(timeout=10)
    monkeypatch.setattr(models, '_data_file_view_cache', {})
    monkeypatch.setattr(models, '_data_file_view_fingerprints', {})
    monkeypatch.setattr(models, '_data_file_view_future', None)
    monkeypatch.setattr(models, '_data_file_view_error', False)
    yield
    pending = models._data_file_view_future
    if pending is not None:
        pending.result(timeout=10)


def test_page_read_returns_partial_progress_and_refreshes_changed_files(monkeypatch, isolated_view):
    files = [str(number) for number in range(6)]
    signatures = {name: 1 for name in files}
    release = threading.Event()
    partial = threading.Event()
    calls = collections.Counter()
    monkeypatch.setattr(models.backtesting_api, 'get_all_available_data_files', lambda: files)
    monkeypatch.setattr(models, '_data_file_fingerprint', lambda name: signatures.get(name))

    async def description(name, result):
        calls[name] += 1
        if name != '0':
            while not release.is_set():
                await asyncio.sleep(0.001)
        result.append((name, {'timestamp': int(name)}))
        if name == '0':
            partial.set()

    monkeypatch.setattr(models, '_get_description', description)
    start = time.monotonic()
    assert models.get_data_files_with_description() == []
    assert time.monotonic() - start < 0.5
    pending = models._data_file_view_future
    try:
        assert partial.wait(1)
        deadline = time.monotonic() + 1
        while '0' not in models._data_file_view_cache and time.monotonic() < deadline:
            time.sleep(0.001)
        assert models.get_data_files_with_description() == [('0', {'timestamp': 0})]
        assert models._data_file_view_future is pending
        assert models.get_data_file_description_status() == {
            'loading': True, 'read_files': 1, 'total_files': 6, 'error': False,
        }
    finally:
        release.set()
    pending.result(timeout=3)
    assert len(models.get_data_files_with_description()) == 6
    assert set(calls.values()) == {1}
    assert not models.get_data_file_description_status()['loading']
    signatures['0'] = 2
    changed = models.get_data_files_with_description()
    assert '0' not in [name for name, _ in changed]
    models._data_file_view_future.result(timeout=3)
    assert len(models.get_data_files_with_description()) == 6
    assert calls['0'] == 2
    files.remove('1')
    assert '1' not in [name for name, _ in models.get_data_files_with_description()]


def test_failed_view_reports_error_and_can_retry(monkeypatch, isolated_view):
    monkeypatch.setattr(models.backtesting_api, 'get_all_available_data_files', lambda: ['file'])
    monkeypatch.setattr(models, '_data_file_fingerprint', lambda name: 1)

    async def broken(name, result):
        raise ValueError('synthetic unreadable details')

    monkeypatch.setattr(models, '_get_description', broken)
    assert models.get_data_files_with_description() == []
    models._data_file_view_future.result(timeout=3)
    assert models.get_data_file_description_status()['error']

    async def recovered(name, result):
        result.append((name, {'timestamp': 1}))

    monkeypatch.setattr(models, '_get_description', recovered)
    models.get_data_files_with_description()
    models._data_file_view_future.result(timeout=3)
    assert models.get_data_files_with_description() == [('file', {'timestamp': 1})]
    assert not models.get_data_file_description_status()['error']


def test_actual_collector_controller_responds_while_details_are_pending(monkeypatch, isolated_view):
    release = threading.Event()
    monkeypatch.setattr(models.backtesting_api, 'get_all_available_data_files', lambda: ['file'])
    monkeypatch.setattr(models, '_data_file_fingerprint', lambda name: 1)

    async def slow(name, result):
        while not release.is_set():
            await asyncio.sleep(0.001)
        result.append((name, {'timestamp': 1}))

    monkeypatch.setattr(models, '_get_description', slow)
    monkeypatch.setattr(controller.login, 'login_required_when_activated', lambda method: method)
    monkeypatch.setattr(exported_models, 'is_backtesting_enabled', lambda: True)
    monkeypatch.setattr(exported_models, 'get_current_exchange', lambda: 'synthetic')
    monkeypatch.setattr(exported_models, 'get_other_history_exchange_list', lambda: [])
    monkeypatch.setattr(exported_models, 'get_full_candle_history_exchange_list', lambda: [])
    monkeypatch.setattr(exported_models, 'get_symbol_list', lambda exchanges: [])
    monkeypatch.setattr(exported_models, 'get_timeframes_list', lambda exchanges: [])
    monkeypatch.setattr(controller.flask, 'render_template', lambda template, **context: flask.jsonify(
        template=template, files=context['data_files'], status=context['data_files_status']))
    app = flask.Flask('saved-file-page-test')
    controller.register(app)
    try:
        start = time.monotonic()
        response = app.test_client().get('/data_collector')
        assert response.status_code == 200
        assert time.monotonic() - start < 0.5
        assert response.json['status']['loading']
        assert response.json['files'] == []
    finally:
        release.set()
