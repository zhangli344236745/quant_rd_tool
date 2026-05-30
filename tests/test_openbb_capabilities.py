from quant_rd_tool.openbb_capabilities import list_capabilities, OPENBB_FEATURES


def test_registry_has_integrated_features():
    assert len(OPENBB_FEATURES) >= 10
    caps = list_capabilities(integrated_only=True)
    assert caps["openbb_installed"] in (True, False)
    assert any(f["id"] == "economy.country_profile" for f in caps["features"])
