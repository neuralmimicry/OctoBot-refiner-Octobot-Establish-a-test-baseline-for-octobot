"""Saved-file metadata reads stay bounded and survive disconnected page waiters."""
import asyncio
import collections
import concurrent.futures
import threading

import pytest

import tentacles.Services.Interfaces.web_interface.models.backtesting as models


@pytest.mark.asyncio
async def test_large_overlapping_loads_have_bounded_workers_and_keep_all_results(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = collections.Counter()
    active = 0
    peak = 0

    async def description(name, results):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        calls[name] += 1
        if active == models.DATA_DESCRIPTION_WORKERS:
            entered.set()
        while not release.is_set():
            await asyncio.sleep(0.001)
        await asyncio.sleep(0)
        results.append((name, {'timestamp': int(name)}))
        active -= 1

    monkeypatch.setattr(models, '_get_description', description)
    files = [str(number) for number in range(1800)]
    first = asyncio.create_task(models._retrieve_data_files_with_description(files))
    second = asyncio.create_task(models._retrieve_data_files_with_description(list(reversed(files))))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        assert sum(calls.values()) == models.DATA_DESCRIPTION_WORKERS
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not second.done()
    finally:
        release.set()
    results = await asyncio.wait_for(second, 3)
    assert peak == models.DATA_DESCRIPTION_WORKERS
    assert len(results) == len(files)
    assert set(calls.values()) == {1}
    assert [item[1]['timestamp'] for item in results] == list(reversed(range(1800)))
    await asyncio.sleep(0)
    assert not models._data_description_loads
    await models._retrieve_data_files_with_description(['0'])
    assert calls['0'] == 2  # A later request reads fresh metadata.


@pytest.mark.asyncio
async def test_failed_load_is_released_and_next_request_can_retry(monkeypatch):
    entered = asyncio.Event()
    active = 0

    async def broken(name, results):
        nonlocal active
        if name == '0':
            await entered.wait()
            raise ValueError('unreadable test metadata')
        active += 1
        if active == models.DATA_DESCRIPTION_WORKERS - 1:
            entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    monkeypatch.setattr(models, '_get_description', broken)
    with pytest.raises(ValueError, match='unreadable'):
        await asyncio.wait_for(models._retrieve_data_files_with_description(['0', '1', '2', '3', '4']), 1)
    await asyncio.sleep(0)
    assert not models._data_description_loads
    assert active == 0

    async def recovered(name, results):
        results.append((name, {'timestamp': 1}))

    monkeypatch.setattr(models, '_get_description', recovered)
    assert await models._retrieve_data_files_with_description(['file']) == [('file', {'timestamp': 1})]


@pytest.mark.asyncio
async def test_empty_saved_file_list_needs_no_worker(monkeypatch):
    async def unexpected(name, results):
        raise AssertionError('No description is needed')

    monkeypatch.setattr(models, '_get_description', unexpected)
    assert await models._retrieve_data_files_with_description([]) == []


def test_requests_on_distinct_executor_loops_share_one_bounded_load(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = collections.Counter()
    active = 0
    peak = 0

    async def description(name, results):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        calls[name] += 1
        if active == models.DATA_DESCRIPTION_WORKERS:
            entered.set()
        try:
            while not release.is_set():
                await asyncio.sleep(0.001)
            results.append((name, {'timestamp': int(name)}))
        finally:
            active -= 1

    monkeypatch.setattr(models, '_get_description', description)
    files = [str(number) for number in range(20)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as browsers:
        first = browsers.submit(asyncio.run, models._retrieve_data_files_with_description(files))
        try:
            assert entered.wait(1)
            # Both loops attach before allowing the shared I/O to finish.
            second_started = threading.Event()
            original_wrap = models.asyncio.wrap_future

            def wrapped(future, **kwargs):
                second_started.set()
                return original_wrap(future, **kwargs)

            monkeypatch.setattr(models.asyncio, 'wrap_future', wrapped)
            second = browsers.submit(asyncio.run, models._retrieve_data_files_with_description(list(reversed(files))))
            assert second_started.wait(1)
        finally:
            release.set()
        assert first.result(timeout=3) == second.result(timeout=3)
    assert peak == models.DATA_DESCRIPTION_WORKERS
    assert len(calls) == len(files)
    assert set(calls.values()) == {1}
