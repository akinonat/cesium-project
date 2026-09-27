from remote_agent.input_win import VK_CODES, RecordingBackend


def test_vk_mapping():
    assert VK_CODES["KeyA"] == 0x41
    assert VK_CODES["Digit0"] == 0x30
    assert VK_CODES["F12"] == 0x7B
    assert VK_CODES["ArrowLeft"] == 0x25


def test_combo_order_and_release_all():
    b = RecordingBackend()
    b.combo(["ControlLeft", "ShiftLeft", "Escape", "Bogus"])
    assert [e[1:] for e in b.events] == [
        (0xA2, True), (0xA0, True), (0x1B, True), (0x1B, False), (0xA0, False), (0xA2, False),
    ]
    b.events.clear()
    b.key("ControlLeft", True)
    b.button("left", True)
    b.release_all()
    assert ("key", 0xA2, False) in b.events and ("button", "left", False) in b.events
    assert not b.pressed_keys and not b.pressed_buttons


def test_unknown_key_and_button_ignored():
    b = RecordingBackend()
    assert b.key("NoSuchKey", True) is False
    b.button("side", True)
    assert b.events == []
