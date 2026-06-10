"""Tests for TV strategy catalog."""

from quant_rd_tool.crypto_zipline_strategies import STRATEGY_REGISTRY, list_strategies
from quant_rd_tool.crypto_zipline_strategies.tv_catalog import (
    ML_STRATEGIES,
    NEW_TV_IDS,
    TV_STRATEGIES,
    list_tv_strategies,
)


def test_tv_catalog_has_exactly_50():
    assert len(TV_STRATEGIES) == 50
    ids = [s["id"] for s in list_tv_strategies()]
    assert len(ids) == len(set(ids))


def test_registry_has_all_tv_and_ml():
    for spec in TV_STRATEGIES:
        assert spec["id"] in STRATEGY_REGISTRY
    for spec in ML_STRATEGIES:
        assert spec["id"] in STRATEGY_REGISTRY


def test_list_strategies_at_least_53():
    assert len(list_strategies()) >= 53


def test_new_tv_ids_count():
    assert len(NEW_TV_IDS) == 31
