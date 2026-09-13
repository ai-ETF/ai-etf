"""settings 单元测试：配置项读取与默认值。

模块名称：server/config/settings.py
所测功能：Settings 从环境变量读取配置，未设置时回退默认值
测试方法：monkeypatch 控制环境变量，构造新的 Settings 实例，全程不联网、不连 Supabase。
"""
import logging

from server.config.settings import Settings


_DEFAULT_VARS = [
    "LOG_LEVEL",
    "ETFSERVER_DB_PATH",
    "ETFSERVER_EMBED_DIM",
    "LYRA_MODEL",
    "LYRA_MAX_TOKENS",
    "XIAOYAN_CACHE_TTL",
    "XIAOYAN_TIMEOUT",
    "EMOTION_DETECTION_ENABLED",
]


def test_默认值(monkeypatch):
    for var in _DEFAULT_VARS:
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.LOG_LEVEL == logging.DEBUG
    assert s.DB_PATH == "server_data.db"
    assert s.EMBED_DIM == 768
    assert s.LYRA_MODEL == "claude-sonnet-4-20250514"
    assert s.LYRA_MAX_TOKENS == 4096
    assert s.XIAOYAN_CACHE_TTL == 86400
    assert s.XIAOYAN_TIMEOUT == 30
    assert s.EMOTION_DETECTION_ENABLED is True


def test_读取环境变量(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("ETFSERVER_DB_PATH", "/tmp/etf-test.db")
    monkeypatch.setenv("ETFSERVER_EMBED_DIM", "512")
    monkeypatch.setenv("LYRA_MAX_TOKENS", "2048")
    monkeypatch.setenv("EMOTION_DETECTION_ENABLED", "false")
    s = Settings()
    assert s.LOG_LEVEL == logging.WARNING
    assert s.DB_PATH == "/tmp/etf-test.db"
    assert s.EMBED_DIM == 512
    assert s.LYRA_MAX_TOKENS == 2048
    assert s.EMOTION_DETECTION_ENABLED is False


def test_无效日志级别_回退DEBUG(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "NOT_A_LEVEL")
    s = Settings()
    assert s.LOG_LEVEL == logging.DEBUG
