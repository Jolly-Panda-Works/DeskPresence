import importlib.util
from pathlib import Path

from deskpresence import config, i18n
from deskpresence.vision import GazeClassifier

ROOT = Path(__file__).resolve().parent.parent


def _load_set_version():
    spec = importlib.util.spec_from_file_location("set_version", ROOT / "tools" / "set_version.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_string_has_both_languages():
    for key, entry in i18n.STRINGS.items():
        assert entry.get("fa") and entry.get("en"), key


def test_translation_switch():
    i18n.set_language("en")
    assert i18n.t("menu.quit") == "Quit"
    i18n.set_language("fa")
    assert i18n.t("menu.quit") == "‫خروج‬"
    assert i18n.is_rtl()
    i18n.set_language("en")


def test_config_merge_keeps_new_defaults():
    merged = config._merge(config.DEFAULTS, {"forced_break": {"work_minutes": 60}, "calibration": {"a": [1, 2]}})
    assert merged["forced_break"]["work_minutes"] == 60
    assert merged["forced_break"]["break_minutes"] == 10
    assert merged["calibration"] == {"a": [1, 2]}


def test_gaze_needs_stable_look():
    g = GazeClassifier({"monitor0": [-0.3, 0.5], "monitor1": [0.3, 0.5]}, stable_seconds=0.5)
    results = [g.update(0.3, 0.5, i / 10) for i in range(10)]
    assert results.count("monitor1") == 1
    assert g.current == "monitor1"


def test_gaze_not_ready_without_calibration():
    assert GazeClassifier({}, 0.5).update(0, 0, 0) is None


def test_versions():
    sv = _load_set_version()
    assert sv.compute_version("refs/heads/main", "main", "42", "1.1.0") == "1.1.42"
    assert sv.compute_version("refs/tags/v2.0.0", "v2.0.0", "9", "1.1.0") == "2.0.0"
    assert sv.compute_version("refs/heads/dev", "dev", "7", "1.1.0") == "1.1.0-dev.7"
    assert sv.numeric_version("1.1.0-dev.7") == (1, 1, 0, 7)
    assert sv.numeric_version("1.1.42") == (1, 1, 42, 0)
