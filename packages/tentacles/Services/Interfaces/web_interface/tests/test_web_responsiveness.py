"""Real HTTP requests remain available while a page waits on an executor future."""
import asyncio
import concurrent.futures
import json
import logging
import socket
import threading
import time
import urllib.request

import pytest
import socketio

import octobot.enums as enums
import tentacles.Services.Interfaces.web_interface.web as web


def test_slow_page_does_not_block_ping_and_threaded_server_stops(monkeypatch):
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    instance = object.__new__(web.WebInterface)
    instance.host, instance.port = '127.0.0.1', port
    instance.logger = logging.getLogger('web-responsiveness-test')
    instance.registered_plugins = []
    instance.should_open_web_interface = False
    instance.started = False
    instance.http_server = None
    instance.websocket_instance = None
    pending = concurrent.futures.Future()
    entered = threading.Event()
    responses = []

    def register_routes(app, distribution):
        @app.get('/api/ping')
        def ping():
            return {'status': 'ok'}

        @app.get('/data_collector')
        def slow_page():
            entered.set()
            return {'description': pending.result(timeout=10)}

    monkeypatch.setattr(instance, 'is_bot_ready', lambda: True)
    monkeypatch.setattr(instance, '_register_routes', register_routes)
    monkeypatch.setattr(instance, 'init_flask_plugins_and_config', lambda app: app.config.update(SECRET_KEY='synthetic-test-only'))
    monkeypatch.setattr(web.configuration_manager, 'get_distribution', lambda config: enums.OctoBotDistribution.DEFAULT)
    monkeypatch.setattr(web.interfaces_util, 'get_edited_config', lambda: {})
    monkeypatch.setattr(web.web_interface_plugins, 'register_all_plugins', lambda app, plugins: plugins)
    monkeypatch.setattr(web.web_interface_root, 'update_registered_plugins', lambda plugins: None)
    monkeypatch.setattr(web.websockets, 'namespaces', [])
    monkeypatch.setattr(web.bot_logging, 'register_error_notifier', lambda callback: None)

    def serve():
        responses.append(asyncio.run(instance._async_run()))

    server_thread = threading.Thread(target=serve, daemon=True)
    server_thread.start()
    deadline = time.monotonic() + 5
    while not instance.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert instance.started
    base = f'http://127.0.0.1:{port}'

    def request_slow_page():
        with urllib.request.urlopen(base + '/data_collector', timeout=10) as response:
            responses.append(json.load(response))

    slow_thread = threading.Thread(target=request_slow_page, daemon=True)
    slow_thread.start()
    client = socketio.Client(logger=False, engineio_logger=False)
    try:
        assert entered.wait(2)
        assert not pending.done()
        for _ in range(10):
            with urllib.request.urlopen(base + '/api/ping', timeout=1) as response:
                assert response.status == 200
                assert json.load(response) == {'status': 'ok'}
        assert not pending.done()
        client.connect(base, transports=['polling'])
        assert client.connected
        client.disconnect()
        assert instance.websocket_instance.async_mode == 'threading'
    finally:
        if client.connected:
            client.disconnect()
        if not pending.done():
            pending.set_result('loaded')
        slow_thread.join(2)
        asyncio.run(instance.stop())
        server_thread.join(2)
    assert not server_thread.is_alive()
    assert not instance.started
    assert {'description': 'loaded'} in responses
