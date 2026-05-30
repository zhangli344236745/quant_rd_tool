from quant_rd_tool.rdagent_library import library_status


def test_library_status_shape() -> None:
    s = library_status()
    assert "package_version" in s
    assert "imports_ok" in s
