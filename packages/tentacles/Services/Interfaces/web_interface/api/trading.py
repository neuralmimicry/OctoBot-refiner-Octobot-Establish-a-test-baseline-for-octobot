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
import decimal
import datetime

import octobot_services.interfaces.util as interfaces_util
import tentacles.Services.Interfaces.web_interface as web_interface
import tentacles.Services.Interfaces.web_interface.util as util
import tentacles.Services.Interfaces.web_interface.login as login
import tentacles.Services.Interfaces.web_interface.models as models
import octobot_trading.api as trading_api


def _json_safe(value):
    """Convert OctoBot runtime values into stable JSON primitives."""
    if isinstance(value, decimal.Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        return _json_safe(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _get_exchange_manager(exchange_name):
    if exchange_name:
        return models.get_first_exchange_data(exchange_name)[0]
    return models.get_first_exchange_data()[0]


def _get_market_ticker(exchange_name, symbol):
    if not symbol or not str(symbol).strip():
        raise ValueError("symbol is required")
    normalized_symbol = str(symbol).strip().replace("|", "/").upper()
    exchange_manager = _get_exchange_manager(exchange_name)
    exchange_name = trading_api.get_exchange_name(exchange_manager)
    exchange_id = trading_api.get_exchange_manager_id(exchange_manager)
    symbol_data = trading_api.get_symbol_data(
        exchange_manager, normalized_symbol, allow_creation=False
    )
    mark_price = interfaces_util.run_in_bot_main_loop(
        symbol_data.prices_manager.get_mark_price(timeout=30), timeout=35
    )
    mark_price = decimal.Decimal(str(mark_price))
    if not mark_price.is_finite() or mark_price <= decimal.Decimal("0"):
        raise RuntimeError(f"No valid mark price for {exchange_name} {normalized_symbol}")
    timestamp = exchange_manager.exchange.get_exchange_current_time()
    return {
        "exchange": exchange_name,
        "exchange_id": exchange_id,
        "symbol": normalized_symbol,
        "last": mark_price,
        "close": mark_price,
        "price": mark_price,
        "mark_price": mark_price,
        "timestamp": timestamp,
    }


def register(blueprint):
    @blueprint.route("/market/ticker", methods=['GET'])
    @login.login_required_when_activated
    def market_ticker():
        try:
            return flask.jsonify(_json_safe(_get_market_ticker(
                flask.request.args.get("exchange"),
                flask.request.args.get("symbol"),
            )))
        except (KeyError, ValueError) as err:
            return util.get_rest_reply(str(err), 404)
        except Exception as err:
            return util.get_rest_reply(str(err), 503)


    @blueprint.route("/portfolio", methods=['GET'])
    @login.login_required_when_activated
    def portfolio():
        return flask.jsonify(_json_safe(models.get_exchange_holdings_per_symbol()))


    @blueprint.route("/logs", methods=['GET'])
    @login.login_required_when_activated
    def logs():
        limit = flask.request.args.get("limit", default=25, type=int)
        limit = max(1, min(limit, 500))
        entries = list(web_interface.get_logs())[-limit:]
        notifications = list(web_interface.get_notifications_history())[-limit:]
        return flask.jsonify({
            "logs": _json_safe(entries),
            "notifications": _json_safe(notifications),
            "count": len(entries),
        })


    @blueprint.route("/orders", methods=['GET', 'POST'])
    @login.login_required_when_activated
    def orders():
        if flask.request.method == 'GET':
            return flask.jsonify(models.get_all_orders_data())
        elif flask.request.method == "POST":
            result = ""
            request_data = flask.request.get_json(silent=True)
            action = flask.request.args.get("action")
            if action is None and isinstance(request_data, dict):
                action = request_data.get("action")
            if action is None:
                if isinstance(request_data, list):
                    action = "create_orders"
                elif isinstance(request_data, dict) and any(
                    key in request_data for key in ("symbol", "pair", "market", "side", "order_side")
                ):
                    action = "create_order"
            if action == "cancel_order":
                if interfaces_util.cancel_orders([request_data]):
                    result = "Order cancelled"
                else:
                    return util.get_rest_reply('Impossible to cancel order: order not found.', 500)
            elif action == "cancel_orders":
                removed_count = interfaces_util.cancel_orders(request_data)
                result = f"{removed_count} orders cancelled"
            elif action == "create_order":
                try:
                    result = models.create_order(request_data)
                except ValueError as err:
                    return util.get_rest_reply(str(err), 400)
                except RuntimeError as err:
                    return util.get_rest_reply(str(err), 500)
            elif action == "create_orders":
                try:
                    result = models.create_orders(request_data)
                except ValueError as err:
                    return util.get_rest_reply(str(err), 400)
                except RuntimeError as err:
                    return util.get_rest_reply(str(err), 500)
            else:
                return util.get_rest_reply(f"Unsupported order action: {action}", 400)
            return flask.jsonify(result)


    @blueprint.route("/trades", methods=['GET'])
    @login.login_required_when_activated
    def trades():
        return flask.jsonify(models.get_all_trades_data())


    @blueprint.route("/positions", methods=['GET', 'POST'])
    @login.login_required_when_activated
    def positions():
        if flask.request.method == 'GET':
            return flask.jsonify(models.get_all_positions_data())
        elif flask.request.method == "POST":
            result = ""
            request_data = flask.request.get_json()
            action = flask.request.args.get("action")
            if action == "close_position":
                if interfaces_util.close_positions([request_data]):
                    result = "Position closed"
                else:
                    return util.get_rest_reply('Impossible to close position: position already closed.', 500)
            return flask.jsonify(result)


    @blueprint.route("/refresh_portfolio", methods=['POST'])
    @login.login_required_when_activated
    def refresh_portfolio():
        try:
            interfaces_util.trigger_portfolios_refresh()
            return flask.jsonify("Portfolio(s) refreshed")
        except RuntimeError:
            return util.get_rest_reply("No portfolio to refresh", 500)


    @blueprint.route("/currency_list", methods=['GET'])
    @login.login_required_when_activated
    def currency_list():
        return flask.jsonify(models.get_all_symbols_list())


    @blueprint.route("/historical_portfolio_value", methods=['GET'])
    @login.login_required_when_activated
    def historical_portfolio_value():
        currency = flask.request.args.get("currency", "USDT")
        time_frame = flask.request.args.get("time_frame")
        from_timestamp = flask.request.args.get("from_timestamp")
        to_timestamp = flask.request.args.get("to_timestamp")
        exchange = flask.request.args.get("exchange")
        try:
            return flask.jsonify(models.get_portfolio_historical_values(currency, time_frame,
                                                                        from_timestamp, to_timestamp,
                                                                        exchange))
        except KeyError:
            return util.get_rest_reply("No exchange portfolio", 404)


    @blueprint.route("/pnl_history", methods=['GET'])
    @login.login_required_when_activated
    def pnl_history():
        exchange = flask.request.args.get("exchange")
        symbol = flask.request.args.get("symbol")
        quote = flask.request.args.get("quote")
        since = flask.request.args.get("since")
        scale = flask.request.args.get("scale", "")
        return flask.jsonify(
            models.get_pnl_history(
                exchange=exchange,
                quote=quote,
                symbol=symbol,
                since=since,
                scale=scale,
            )
        )


    @blueprint.route("/clear_orders_history", methods=['POST'])
    @login.login_required_when_activated
    def clear_orders_history():
        return util.get_rest_reply(models.clear_exchanges_orders_history())


    @blueprint.route("/clear_trades_history", methods=['POST'])
    @login.login_required_when_activated
    def clear_trades_history():
        return util.get_rest_reply(models.clear_exchanges_trades_history())


    @blueprint.route("/clear_portfolio_history", methods=['POST'])
    @login.login_required_when_activated
    def clear_portfolio_history():
        return flask.jsonify(models.clear_exchanges_portfolio_history())


    @blueprint.route("/clear_transactions_history", methods=['POST'])
    @login.login_required_when_activated
    def clear_transactions_history():
        return flask.jsonify(models.clear_exchanges_transactions_history())
