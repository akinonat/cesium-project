from remote_agent.config import Config, hash_password, verify_password


def test_password_roundtrip():
    h = hash_password("dogru-parola-123", iterations=1000)
    assert verify_password("dogru-parola-123", h)
    assert not verify_password("yanlis-parola", h)
    assert not verify_password("x", "bozuk-ozet")


def test_config_save_load(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(name="Ofis", port=9000, password_hash="abc")
    cfg.save(path)
    loaded = Config.load(path)
    assert (loaded.name, loaded.port, loaded.password_hash) == ("Ofis", 9000, "abc")
