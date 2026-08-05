"""sample-python 合成项目：失败测试（GT-W02 沙箱演示用）。"""

from src.main import buggy


def test_buggy_returns_true() -> None:
    assert buggy() is True  # 修复前失败 → 修复后通过
