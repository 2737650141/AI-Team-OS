"""M0 冒烟测试：确认包可导入、工具链可运行。"""


def test_smoke_import() -> None:
    import app  # noqa: F401

    assert app.__name__ == "app"
