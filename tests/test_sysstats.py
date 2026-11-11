import numpy as np

from sysstats import LevelMeter, SystemStats, level_db


def write_proc(path, idle, total_busy):
    # cpu user nice system idle iowait irq softirq steal
    path.joinpath("stat").write_text(f"cpu  {total_busy} 0 0 {idle} 0 0 0 0 0 0\ncpu0 1 2 3 4\n")


def test_cpu_percent(tmp_path):
    stats = SystemStats(tmp_path)
    write_proc(tmp_path, idle=1000, total_busy=1000)
    assert stats.cpu_percent() is None          # erster Aufruf: noch kein Vergleich
    write_proc(tmp_path, idle=1100, total_busy=1300)
    assert stats.cpu_percent() == 75            # 300 belegt von 400


def test_ram_percent(tmp_path):
    tmp_path.joinpath("meminfo").write_text(
        "MemTotal:        2000000 kB\nMemFree:          100000 kB\nMemAvailable:     500000 kB\n")
    assert SystemStats(tmp_path).ram_percent() == 75


def test_missing_proc_files(tmp_path):
    stats = SystemStats(tmp_path / "gibt-es-nicht")
    assert stats.cpu_percent() is None
    assert stats.ram_percent() is None


def test_real_proc_on_linux():
    stats = SystemStats()
    stats.cpu_percent()
    ram = stats.ram_percent()
    assert ram is None or 0 <= ram <= 100


def test_level_db():
    assert level_db(np.zeros(1024, dtype=np.int16)) == -90.0
    full = np.full(1024, 32767, dtype=np.int16)
    assert abs(level_db(full)) < 0.01
    half = np.full(1024, 16384, dtype=np.int16)
    assert abs(level_db(half) + 6.02) < 0.05


def test_level_meter_keeps_peak():
    meter = LevelMeter()
    meter.add(np.full(256, 16384, dtype=np.int16))
    meter.add(np.zeros(256, dtype=np.int16))
    assert abs(meter.take() + 6.02) < 0.05
    assert meter.take() == -90.0
