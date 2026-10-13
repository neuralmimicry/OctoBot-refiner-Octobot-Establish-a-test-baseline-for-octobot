"""Saved-file metadata reads stay bounded and survive disconnected page waiters."""
import asyncio
import collections

import pytest

import tentacles.Services.Interfaces.web_interface.models.backtesting as models


@pytest.mark.asyncio
async def test_large_overlapping_loads_have_bounded_workers_and_keep_all_results(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
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
        await release.wait()
        await asyncio.sleep(0)
        results.append((name, {'timestamp': int(name)}))
        active -= 1

    monkeypatch.setattr(models, '_get_description', description)
    files = [str(number) for number in range(1800)]
    first = asyncio.create_task(models._retrieve_data_files_with_description(files))
    second = asyncio.create_task(models._retrieve_data_files_with_description(list(reversed(files))))
    await asyncio.wait_for(entered.wait(), 1)
    assert sum(calls.values()) == models.DATA_DESCRIPTION_WORKERS
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not second.done()
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
    async def broken(name, results):
        raise ValueError('unreadable test metadata')

    monkeypatch.setattr(models, '_get_description', broken)
    with pytest.raises(ValueError, match='unreadable'):
        await models._retrieve_data_files_with_description(['file'])
    await asyncio.sleep(0)
    assert not models._data_description_loads

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
