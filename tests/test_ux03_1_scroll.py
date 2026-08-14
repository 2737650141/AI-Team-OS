"""024-C ConversationScrollController 后端测试门禁 SCROLL01-10。

后端负责每个 conversation 的滚动状态持久化（scrollTop/anchorMessageId/
wasNearBottom）与会话隔离；前端 hook 负责实际滚动行为（见 web 侧测试）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.conversation.session import ConversationSession


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


def _new_session(session_id: str = "jarvis-test") -> ConversationSession:
    return ConversationSession(session_id=session_id)


# SCROLL01：会话默认状态为"在底部"（新会话应跟随最新消息）
def test_scroll01_default_near_bottom() -> None:
    session = _new_session()
    assert session.was_near_bottom is True
    assert session.scroll_top == 0
    assert session.anchor_message_id is None


# SCROLL02：set_scroll_state 保存 scrollTop / anchorMessageId / wasNearBottom
def test_scroll02_save_state() -> None:
    session = _new_session()
    session.set_scroll_state(scroll_top=420, anchor_message_id="msg-7", was_near_bottom=False)
    assert session.scroll_top == 420
    assert session.anchor_message_id == "msg-7"
    assert session.was_near_bottom is False


# SCROLL03：看历史（不在底部）时保存原位置；负值被钳制为 0
def test_scroll03_clamp_and_history() -> None:
    session = _new_session()
    session.set_scroll_state(scroll_top=-50, anchor_message_id=None, was_near_bottom=False)
    assert session.scroll_top == 0
    assert session.was_near_bottom is False


# SCROLL04：在底部时 was_near_bottom=True（回到会话 → 最新消息）
def test_scroll04_near_bottom_flag() -> None:
    session = _new_session()
    session.set_scroll_state(scroll_top=9999, anchor_message_id=None, was_near_bottom=True)
    assert session.was_near_bottom is True


# SCROLL05：状态随会话持久化（保存后重新加载仍存在 → route switch 不回到顶部）
def test_scroll05_persist_across_reload(data_dir: Path) -> None:
    session = _new_session()
    session.set_scroll_state(scroll_top=600, anchor_message_id="msg-9", was_near_bottom=False)
    session.save(data_dir)
    loaded = ConversationSession.load(data_dir, "jarvis-test")
    assert loaded is not None
    assert loaded.scroll_top == 600
    assert loaded.anchor_message_id == "msg-9"
    assert loaded.was_near_bottom is False


# SCROLL06：conversation switch 状态隔离（不同 session 互不覆盖）
def test_scroll06_session_isolation(data_dir: Path) -> None:
    a = ConversationSession(session_id="conv-a")
    b = ConversationSession(session_id="conv-b")
    a.set_scroll_state(scroll_top=100, anchor_message_id="a-1", was_near_bottom=False)
    b.set_scroll_state(scroll_top=0, anchor_message_id=None, was_near_bottom=True)
    a.save(data_dir)
    b.save(data_dir)
    loaded_a = ConversationSession.load(data_dir, "conv-a")
    loaded_b = ConversationSession.load(data_dir, "conv-b")
    assert loaded_a is not None and loaded_b is not None
    assert loaded_a.scroll_top == 100 and loaded_a.was_near_bottom is False
    assert loaded_b.scroll_top == 0 and loaded_b.was_near_bottom is True


# SCROLL07：新会话（清空）后滚动状态重置为默认（新对话 → 最新消息）
def test_scroll07_reset_on_clear(data_dir: Path) -> None:
    session = _new_session()
    session.set_scroll_state(scroll_top=800, anchor_message_id="old", was_near_bottom=False)
    session.save(data_dir)
    # 模拟"新对话"清空：重建同 id 空会话
    fresh = ConversationSession(session_id="jarvis-test")
    fresh.save(data_dir)
    loaded = ConversationSession.load(data_dir, "jarvis-test")
    assert loaded is not None
    assert loaded.scroll_top == 0
    assert loaded.anchor_message_id is None
    assert loaded.was_near_bottom is True


# SCROLL08：滚动状态保存不刷新 updated_at（Recent conversations 排序不受滚动干扰）
def test_scroll08_scroll_does_not_touch_updated_at(data_dir: Path) -> None:
    session = _new_session()
    before = session.updated_at
    session.set_scroll_state(scroll_top=10, anchor_message_id=None, was_near_bottom=True)
    assert session.updated_at == before  # 滚动保存不应改变"最后活跃时间"


# SCROLL09：to_dict/from_dict 往返保留滚动状态（checkpoint/序列化兼容）
def test_scroll09_serialization_roundtrip() -> None:
    session = _new_session()
    session.set_scroll_state(scroll_top=250, anchor_message_id="msg-2", was_near_bottom=True)
    restored = ConversationSession.from_dict(session.to_dict())
    assert restored.scroll_top == 250
    assert restored.anchor_message_id == "msg-2"
    assert restored.was_near_bottom is True


# SCROLL10：API 层 PUT scroll 保存状态并回读（前端 ConversationScrollController 持久化链路）
def test_scroll10_api_save_scroll(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app.api import server

    data = tmp_path / "api-data"
    data.mkdir(parents=True)
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(data))
    client = TestClient(server.app)

    # 先建一个会话（直接写文件）
    session = ConversationSession(session_id="conv-scroll")
    session.save(data)

    resp = client.put(
        "/jarvis/sessions/conv-scroll/scroll",
        json={"scroll_top": 320, "anchor_message_id": "msg-11", "was_near_bottom": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["scroll"] == {
        "scroll_top": 320,
        "anchor_message_id": "msg-11",
        "was_near_bottom": False,
    }

    # 会话列表包含该会话
    listing = client.get("/jarvis/sessions").json()
    assert any(s["session_id"] == "conv-scroll" for s in listing["sessions"])

    # 非法输入被拒（负 scroll_top）
    bad = client.put(
        "/jarvis/sessions/conv-scroll/scroll",
        json={"scroll_top": -5, "anchor_message_id": None, "was_near_bottom": True},
    )
    assert bad.status_code == 422
