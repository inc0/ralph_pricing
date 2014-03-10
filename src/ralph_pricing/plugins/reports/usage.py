# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import logging
from collections import defaultdict, OrderedDict
from decimal import Decimal as D

from django.utils.translation import ugettext_lazy as _

from ralph_pricing.plugins.base import register
from ralph_pricing.plugins.reports.base import BaseReportPlugin

logger = logging.getLogger(__name__)


class UsageBasePlugin(BaseReportPlugin):
    def _incomplete_price(self, usage_type, start, end, warehouse=None):
        """
        Calculate if for every day in report there is price defined for usage
        type

        :param list usage_type: usage type
        :param datetime start: Start date of the report
        :param datetime end: End date of the report
        :returns str: 'No price' or 'Incomplete price' or None (if all is ok)
        """
        total_days = (end - start).days + 1  # total report days
        ut_days = 0
        usage_prices = usage_type.usageprice_set.filter(
            end__gte=start,
            start__lte=end,
        )
        if usage_type.by_warehouse and warehouse:
            usage_prices = usage_prices.filter(warehouse=warehouse)
        # TODO: improve preformance
        for up in usage_prices:
            # add overlapping days
            ut_days += (min(end, up.end) - max(start, up.start)).days + 1
        if ut_days == 0:
            return _('No price')
        if ut_days != total_days:
            return _('Incomplete price')
        return None

    def _get_total_cost_by_warehouses(
        self,
        start,
        end,
        ventures,
        usage_type,
        forecast=False,
        **kwargs
    ):
        """
        Returns total cost of usage for ventures for every warehouse (if usage
        type is by venture).
        """
        if usage_type.by_warehouse:
            warehouses = self.get_warehouses()
        else:
            warehouses = [None]
        result = []
        total_cost = D(0)
        for warehouse in warehouses:
            usage_in_warehouse = 0
            cost_in_warehouse = 0
            usage_prices = usage_type.usageprice_set.filter(
                start__lte=end,
                end__gte=start,
                type=usage_type,
            )
            if warehouse:
                usage_prices = usage_prices.filter(warehouse=warehouse)
            usage_prices = usage_prices.order_by('start')
            for usage_price in usage_prices:
                if forecast:
                    price = usage_price.forecast_price
                else:
                    price = usage_price.price
                if usage_type.by_cost:
                    price = self._get_price_from_cost(
                        usage_price,
                        forecast,
                        warehouse
                    )

                up_start = max(start, usage_price.start)
                up_end = min(end, usage_price.end)

                total_usage = self._get_total_usage_in_period(
                    up_start,
                    up_end,
                    usage_type,
                    warehouse,
                    ventures
                )
                usage_in_warehouse += total_usage
                cost = D(total_usage) * price
                cost_in_warehouse += cost

            result.append(usage_in_warehouse)
            cost_in_warehouse = D(cost_in_warehouse)
            result.append(cost_in_warehouse)
            total_cost += cost_in_warehouse
        if usage_type.by_warehouse:
            result.append(total_cost)
        return result

    def _get_usages_per_warehouse(
        self,
        usage_type,
        start,
        end,
        forecast,
        ventures,
        no_price_msg=False,
    ):
        """
        Returns informations about usage (of usage type) count and cost
        per venture in period (between start and end) using forecast or real
        price. If no_price_msg is False, then even if there is no price
        defined cost will always be number. If no_price_msg is True then if
        price for period of time in undefined of partially defined (incomplete)
        cost will be message what's wrong with price (i.e. 'Incomplete price').
        """
        if usage_type.by_warehouse:
            warehouses = self.get_warehouses()
        else:
            warehouses = [None]
        result = defaultdict(lambda: defaultdict(int))

        for warehouse in warehouses:
            price_undefined = no_price_msg and self._incomplete_price(
                usage_type,
                start,
                end,
                warehouse
            )
            usage_prices = usage_type.usageprice_set.filter(
                start__lte=end,
                end__gte=start,
            )
            if warehouse:
                usage_prices = usage_prices.filter(warehouse=warehouse)
            usage_prices = usage_prices.order_by('start')

            if usage_type.by_warehouse:
                count_key = 'ut_{0}_count_wh_{1}'.format(
                    usage_type.id,
                    warehouse.id
                )
                cost_key = 'ut_{0}_cost_wh_{1}'.format(
                    usage_type.id,
                    warehouse.id
                )
                total_cost_key = 'ut_{0}_total_cost'.format(usage_type.id)
            else:
                count_key = 'ut_{0}_count'.format(usage_type.id)
                cost_key = 'ut_{0}_cost'.format(usage_type.id)

            def add_usages_per_venture(up_start, up_end, price):
                usages_per_venture = self._get_usages_in_period_per_venture(
                    up_start,
                    up_end,
                    usage_type,
                    warehouse,
                    ventures,
                )
                for v in usages_per_venture:
                    venture = v['pricing_venture']
                    result[venture][count_key] += v['usage']
                    cost = D(v['usage']) * price
                    if price_undefined:
                        result[venture][cost_key] = price_undefined
                    else:
                        result[venture][cost_key] += cost
                    if usage_type.by_warehouse and not price_undefined:
                        result[venture][total_cost_key] += cost

            if usage_prices:
                for usage_price in usage_prices:
                    if forecast:
                        price = usage_price.forecast_price
                    else:
                        price = usage_price.price
                    if usage_type.by_cost:
                        price = self._get_price_from_cost(
                            usage_price,
                            forecast,
                            warehouse
                        )

                    up_start = max(start, usage_price.start)
                    up_end = min(end, usage_price.end)
                    add_usages_per_venture(up_start, up_end, price)
            else:
                add_usages_per_venture(start, end, 0)

        return result

    def total_cost(self, *args, **kwargs):
        costs_by_wh = self._get_total_cost_by_warehouses(*args, **kwargs)
        return costs_by_wh[-1]

    def usages(
        self,
        start,
        end,
        ventures,
        usage_type,
        forecast=False,
        no_price_msg=False,
        **kwargs
    ):
        logger.debug("Get {0} usages".format(usage_type.name))
        return self._get_usages_per_warehouse(
            start=start,
            end=end,
            ventures=ventures,
            usage_type=usage_type,
            forecast=forecast,
            no_price_msg=no_price_msg,
        )

    def schema(self, usage_type, **kwargs):
        logger.debug("Get {0} schema".format(usage_type.name))
        if usage_type.by_warehouse:
            schema = OrderedDict()
            for warehouse in self.get_warehouses():
                count_key = 'ut_{0}_count_wh_{1}'.format(
                    usage_type.id,
                    warehouse.id
                )
                cost_key = 'ut_{0}_cost_wh_{1}'.format(
                    usage_type.id,
                    warehouse.id
                )
                schema[count_key] = {
                    'name': _("{0} count ({1})".format(
                        usage_type.name,
                        warehouse.name,
                    )),
                }
                schema[cost_key] = {
                    'name': _("{0} cost ({1})".format(
                        usage_type.name,
                        warehouse.name,
                    )),
                    'currency': True,
                }
            schema['ut_{0}_total_cost'.format(usage_type.id)] = {
                'name': _("{0} total cost".format(usage_type.name)),
                'currency': True,
                'total_cost': True,
            }
        else:
            schema = OrderedDict([
                ('ut_{0}_count'.format(usage_type.id), {
                    'name': _("{0} count".format(usage_type.name)),
                }),
                ('ut_{0}_cost'.format(usage_type.id), {
                    'name': _("{0} cost".format(usage_type.name)),
                    'currency': True,
                    'total_cost': True,
                }),
            ])
        return schema


@register(chain='reports')
class UsagePlugin(UsageBasePlugin):
    """
    Base Usage Plugin as ralph plugin. Splitting it into two classes gives
    ability to inherit from UsageBasePlugin.
    """
    pass