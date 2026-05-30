def test_add_remove_list(tmp_path):
    from quant_rd_tool.watchlist import Watchlist

    wl = Watchlist(tmp_path / "watchlist.json")
    wl.add("600519", name="贵州茅台")
    items = wl.list_items()
    assert len(items) == 1
    assert items[0]["code"] == "600519"
    wl.remove("600519")
    assert wl.list_items() == []
