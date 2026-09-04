#  Drakkar-Software OctoBot-Interfaces
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3.0 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library.
import flask

import octobot_trading.api as trading_api
import octobot_services.interfaces.util as interfaces_util
import tentacles.Services.Interfaces.web_interface.login as login
import tentacles.Services.Interfaces.web_interface.models as models
import tentacles.Services.Interfaces.web_interface.util as util


def register(blueprint):
    @blueprint.route("/exchanges")
    @login.login_required_when_activated
    def exchanges():
        """Return the live exchange managers available to Gail.

        The upstream web UI exposes exchange configuration through HTML pages,
        but Gail needs a small machine-readable inventory to select the venue
        used by the subsequent ticker and order calls.
        """
        result = []
        for exchange_manager in interfaces_util.get_exchange_managers():
            exchange_name = trading_api.get_exchange_name(exchange_manager)
            exchange_id = trading_api.get_exchange_manager_id(exchange_manager)
            result.append({
                "name": exchange_name,
                "exchange": exchange_name,
                "id": exchange_id,
                "exchange_id": exchange_id,
                "enabled": True,
                "trading": trading_api.is_trader_existing_and_enabled(exchange_manager),
                "symbols": sorted(trading_api.get_trading_pairs(exchange_manager)),
            })
        return flask.jsonify(result)


    @blueprint.route("/are_compatible_accounts", methods=['POST'])
    @login.login_required_when_activated
    def are_compatible_accounts():
        request_data = flask.request.get_json()
        return flask.jsonify(models.are_compatible_accounts(request_data))


    @blueprint.route("/first_exchange_details")
    @login.login_required_when_activated
    def first_exchange_details():
        exchange_name = flask.request.args.get('exchange_name', None)
        try:
            exchange_manager, exchange_name, exchange_id = models.get_first_exchange_data(exchange_name)
            return util.get_rest_reply(
                {
                    "exchange_name": exchange_name,
                    "exchange_id": exchange_id
                },
                200
            )
        except KeyError as e:
            return util.get_rest_reply(str(e), 404)
