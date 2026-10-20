"""Daily statistics: glasses of water and time worked at the desk (kept for 60 days)."""
import datetime
import json
import logging
import os
import threading

from .config import APP_DIR

log = logging.getLogger(__name__)

STATS_PATH = os.path.join(APP_DIR, "stats.json")
KEEP_DAYS = 60


def today():
    return datetime.date.today().isoformat()


class Stats:
    def __init__(self, path=None):
        self.path = path or STATS_PATH
        self._lock = threading.Lock()
        self._days = {}
        self._dirty = False
        try:
            with open(self.path, encoding="utf-8") as f:
                self._days = json.load(f)
        except FileNotFoundError:
            pass
        except Exception:
            log.exception("stats.json unreadable, starting fresh")

    def _day(self):
        return self._days.setdefault(today(), {"water": 0, "work_seconds": 0.0})

    def add_water(self):
        with self._lock:
            self._day()["water"] += 1
            self._dirty = True
        self.save()

    def add_work(self, seconds):
        with self._lock:
            self._day()["work_seconds"] += seconds
            self._dirty = True

    def today(self):
        with self._lock:
            d = dict(self._day())
        return {"water": int(d["water"]), "work_seconds": int(d["work_seconds"])}

    def save(self):
        with self._lock:
            if not self._dirty:
                return
            cutoff = (datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
            self._days = {k: v for k, v in self._days.items() if k >= cutoff}
            data = json.dumps(self._days, indent=1)
            self._dirty = False
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, self.path)
        except Exception:
            log.exception("Saving stats failed")
