#  This file is part of OctoBot (https://github.com/Drakkar-Software/OctoBot)
#  Copyright (c) 2025 Drakkar-Software, All rights reserved.
#
#  OctoBot is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either
#  version 3.0 of the License, or (at your option) any later version.
#
#  OctoBot is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  General Public License for more details.
#
#  You should have received a copy of the GNU General Public
#  License along with OctoBot. If not, see <https://www.gnu.org/licenses/>.
import asyncio
import logging
import pytest

from octobot_commons.logging.logging_util import get_logger
from octobot_trading.api.exchange import cancel_ccxt_throttle_task
from tentacles.Services.Interfaces.web_interface import WebInterface
from octobot_commons.tests.test_config import load_test_config
from octobot.commands import start_bot
from octobot.logger import init_logger
from octobot.octobot import OctoBot
import octobot.community as community


# Venue-backed initialization can perform several sequential network reads.
# Native CI observed a single market reload exceeding eleven seconds, so the
# readiness budget must not assume the whole startup fits within ten seconds.
# Keep the original ten-second observation window and bounded cleanup distinct.
# A thread deadline also terminates a teardown that ignores cancellation.
@pytest.mark.timeout(85, method="thread")
@pytest.mark.asyncio
async def test_run_bot():
    # use custom logs folder
    logs_folder = "tests/functional_tests/logs"
    # avoid web interface in this test
    web_interface_enabled = WebInterface.enabled
    WebInterface.enabled = False
    community.IdentifiersProvider.use_production()
    config = load_test_config(dict_only=False)
    bot = OctoBot(config, ignore_config=True)
    bot.task_manager.init_async_loop()
    try:
        async with asyncio.timeout(60):
            await start_bot(bot, init_logger(logs_folder=logs_folder))
            # Exchange construction and evaluator/data initialization continue
            # in channel tasks after initialize returns.
            await bot.exchange_producer.created_all_exchanges.wait()
            await bot._init_metadata_run_task
        assert bot.initialized
        assert bot.exchange_producer.exchange_manager_ids
        assert (
            len(bot.exchange_producer.exchange_manager_ids)
            == bot.exchange_producer.to_create_exchanges_count
        )
        # Preserve the original observation window: late price-conversion and
        # watched-pair work can start after the initial data-ready events.
        await asyncio.sleep(10)
    finally:
        # A startup/readiness failure must still close exchange sessions and
        # community tasks before pytest-asyncio cancels the remaining tasks.
        try:
            async with asyncio.timeout(10):
                await stop_bot(bot)
        finally:
            bot.task_manager.async_loop.close()
            WebInterface.enabled = web_interface_enabled
    assert bot.stopped.is_set()
    assert bot.task_manager.tools_task_group.done()


async def stop_bot(bot):
    # force all logger enable to display any error
    stop_logger = get_logger("StopBotLogger")
    for logger in logging.Logger.manager.loggerDict.values():
        logger.disabled = False

    stop_logger.info("Stopping tasks...")
    try:
        await bot.stop()
    finally:
        if bot.task_manager.tools_task_group is not None:
            bot.task_manager.tools_task_group.cancel()
            await asyncio.gather(bot.task_manager.tools_task_group, return_exceptions=True)
        cancel_ccxt_throttle_task()

    stop_logger.info("Tasks stopped.")
