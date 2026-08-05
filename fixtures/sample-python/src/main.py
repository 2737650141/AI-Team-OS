"""sample-python 合成项目：确定性 Bug（007 GT-W02 沙箱演示用）。

buggy() 恒返回 False；test_main.py 断言其为 True（修复前必失败）。
Executor 的确定性修复：return False → return True（最小变更）。
"""


def buggy() -> bool:
    # 确定性 bug：应返回 True
    return False


def main() -> int:
    return 0 if buggy() else 1
