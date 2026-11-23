"""白名单同步 CLI 单元测试：手动触发入口。

模块名称：server/scripts/sync_fund_catalog.py
所测功能：参数解析、参数透传到同步服务、退出码语义（0 成功 / 1 有失败行 / 2 未取到锁）
测试方法：直测 _parse_args + monkeypatch 同步服务与锁，全程不联网、不连 Supabase。
"""
import pytest

from server.scripts import sync_fund_catalog as cli


@pytest.fixture(autouse=True)
def _锁文件隔离(monkeypatch, tmp_path):
    """把锁文件指到 tmp 目录，避免用例碰到机器上真实的 /tmp/fund_catalog_sync.lock。"""
    from server.services import fund_catalog_sync as mod

    monkeypatch.setattr(mod, "SYNC_LOCK_PATH", str(tmp_path / "sync.lock"))


# ==================== 参数解析 ====================

def test_默认参数():
    args = cli._parse_args([])
    assert args.limit is None
    assert args.codes is None
    assert args.interval == cli.DEFAULT_REQUEST_INTERVAL
    assert args.dry_run is False


def test_解析limit_codes_interval_dryrun():
    args = cli._parse_args(
        ["--limit", "5", "--codes", "110020,000071", "--interval", "1.5", "--dry-run"]
    )
    assert args.limit == 5
    assert args.codes == "110020,000071"
    assert args.interval == 1.5
    assert args.dry_run is True


# ==================== 执行与退出码 ====================

class _假服务:
    def __init__(self, stats):
        self.stats, self.调用 = stats, None

    def run(self, codes=None, limit=None, interval=None, dry_run=False):
        self.调用 = {"codes": codes, "limit": limit, "interval": interval, "dry_run": dry_run}
        return self.stats


def _打桩服务(monkeypatch, stats):
    假服务 = _假服务(stats)
    monkeypatch.setattr(cli, "FundCatalogSync", lambda: 假服务)
    return 假服务


def test_全部成功时退出码0(monkeypatch):
    假服务 = _打桩服务(monkeypatch, {"synced": 3, "failed": 0})

    assert cli.main(["--limit", "3"]) == 0
    assert 假服务.调用["limit"] == 3


def test_有失败行时退出码1(monkeypatch):
    """坏行不中断整轮，但运维必须能通过退出码/日志知道本轮不干净。"""
    _打桩服务(monkeypatch, {"synced": 2, "failed": 1})

    assert cli.main([]) == 1


def test_codes按逗号拆分并去除空白(monkeypatch):
    假服务 = _打桩服务(monkeypatch, {"synced": 2, "failed": 0})

    cli.main(["--codes", "110020, 000071 ,"])

    assert 假服务.调用["codes"] == ["110020", "000071"]


def test_不传codes时为None_表示自动发现(monkeypatch):
    假服务 = _打桩服务(monkeypatch, {"synced": 0, "failed": 0})

    cli.main([])

    assert 假服务.调用["codes"] is None


def test_未取到锁时退出码2且不跑同步(monkeypatch):
    """已有同步在跑时不该再启动一轮：两个进程同时写同一批 fund_code 会互相覆盖。"""
    from server.services.fund_catalog_sync import SyncLockBusy

    class _已被占用的锁:
        def __enter__(self):
            raise SyncLockBusy("已有同步任务在跑")

        def __exit__(self, *exc):
            return False

    假服务 = _打桩服务(monkeypatch, {"synced": 9, "failed": 0})
    monkeypatch.setattr(cli, "sync_lock", lambda: _已被占用的锁())

    assert cli.main([]) == 2
    assert 假服务.调用 is None


def test_dry_run透传到服务(monkeypatch):
    假服务 = _打桩服务(monkeypatch, {"synced": 5, "failed": 0})

    cli.main(["--dry-run"])

    assert 假服务.调用["dry_run"] is True
