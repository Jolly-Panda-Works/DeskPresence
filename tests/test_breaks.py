from deskpresence.i18n import t


def popups(sim):
    return [e[1] for e in sim.ui.log if e[0] == "popup"]


def test_water_reminder_every_hour(sim):
    sim.ctrl.cfg["forced_break"]["enabled"] = False
    sim.run(59 * 60, True)
    assert t("water.title") not in popups(sim)
    sim.run(2 * 60, True)
    assert popups(sim).count(t("water.title")) == 1
    sim.ui.pending(None)  # not answered
    sim.run(60 * 60, True)
    assert popups(sim).count(t("water.title")) == 2


def test_water_timer_pauses_while_away(sim):
    sim.ctrl.cfg["forced_break"]["enabled"] = False
    sim.run(30 * 60, True)
    sim.run(40 * 60, False)  # away: does not count
    sim.run(29 * 60, True)
    assert t("water.title") not in popups(sim)
    sim.run(2 * 60, True)
    assert t("water.title") in popups(sim)


def test_drank_water_restarts_the_timer(sim):
    sim.ctrl.cfg["forced_break"]["enabled"] = False
    sim.run(50 * 60, True)
    sim.ctrl.drank_water()
    sim.run(50 * 60, True)
    assert t("water.title") not in popups(sim)
    assert 9 * 60 < sim.ctrl.timers()["water_left"] <= 10 * 60


def test_water_later_asks_again_in_10_minutes(sim):
    sim.ctrl.cfg["forced_break"]["enabled"] = False
    sim.run(61 * 60, True)
    sim.ui.pending(False)  # "in 10 minutes"
    sim.run(9 * 60, True)
    assert popups(sim).count(t("water.title")) == 1
    sim.run(2 * 60, True)
    assert popups(sim).count(t("water.title")) == 2


def test_break_starts_after_90_minutes(sim):
    sim.run(89 * 60, True)
    assert not sim.ctrl.break_active
    sim.run(2 * 60, True)
    assert sim.ctrl.break_active
    assert ("show",) in sim.ui.log


def test_break_timer_does_not_run_while_you_sit(sim):
    sim.run(91 * 60, True)
    sim.run(10 * 60, True)  # still at the desk
    assert sim.ctrl.break_active
    assert sim.ui.last_break == (600, False)


def test_break_timer_runs_only_while_away_and_pauses_on_return(sim):
    sim.run(91 * 60, True)
    sim.run(4 * 60, False)
    left, counting = sim.ui.last_break
    assert counting and 360 <= left <= 380
    sim.run(60, True)  # came back too early: paused
    assert sim.ui.last_break[1] is False
    assert abs(sim.ui.last_break[0] - left) <= 3
    sim.run(7 * 60, False)
    assert not sim.ctrl.break_active
    assert ("hide",) in sim.ui.log


def test_break_done_notice_on_return(sim):
    sim.run(91 * 60, True)
    sim.run(11 * 60, False)
    assert t("break.done.title") not in popups(sim)
    sim.run(5, True)
    assert t("break.done.title") in popups(sim)
    assert sim.ctrl.next_break_minutes() >= 89


def test_natural_long_absence_counts_as_break(sim):
    sim.run(60 * 60, True)
    sim.run(12 * 60, False)
    sim.run(5, True)
    assert sim.ctrl.next_break_minutes() >= 89


def test_short_absence_pauses_the_work_timer(sim):
    sim.run(60 * 60, True)
    sim.run(5 * 60, False)  # 5 min away: paused, not reset
    sim.run(5, True)
    assert sim.ctrl.next_break_minutes() == 29


def test_standup_reminder_pauses_and_resets(sim):
    sim.ctrl.cfg["forced_break"]["enabled"] = False
    sim.ctrl.cfg["break_reminder_minutes"] = 50
    sim.run(40 * 60, True)
    sim.run(5 * 60, False)   # short absence: paused
    sim.run(9 * 60, True)
    assert t("remind.title") not in popups(sim)
    sim.run(2 * 60, True)
    assert t("remind.title") in popups(sim)
    sim.run(11 * 60, False)  # long absence: reset
    sim.run(5, True)
    assert sim.ctrl.sit_elapsed < 10


def test_skip_ends_break(sim):
    sim.run(91 * 60, True)
    sim.ctrl.end_break(skipped=True)
    assert not sim.ctrl.break_active
    assert t("break.done.title") not in popups(sim)


def test_sleep_or_hibernate_restarts_every_timer(sim):
    sim.run(85 * 60, True)
    sim.ctrl.drank_water()
    sim.run(30 * 60, True)  # 30 min toward the next water reminder, break already running
    assert sim.ctrl.break_active
    wall = sim.ctrl._last_wall
    sim.ctrl._check_resume(wall + 1)          # a normal half-second tick: nothing happens
    assert sim.ctrl.break_active
    sim.ctrl._check_resume(wall + 1 + 3 * 3600)  # woke up after 3 hours of sleep
    assert not sim.ctrl.break_active
    assert ("hide",) in sim.ui.log
    t = sim.ctrl.timers()
    assert t["water_left"] == 60 * 60 and t["break_left"] == 90 * 60 and t["sitting"] == 0


def test_countdown_fades_to_black_then_away(sim):
    sim.run(60, True)
    assert sim.ui.countdown == []          # at the desk: nothing on screen
    sim.run(1.5, False)
    assert sim.ui.countdown == []          # one missed glance does not start it
    sim.run(5, False)
    shown = sim.ui.countdown
    assert shown, "the countdown should be on screen"
    lefts = [c[0] for c in shown]
    darkness = [c[1] for c in shown]
    assert lefts == sorted(lefts, reverse=True)       # counting down
    assert darkness == sorted(darkness) and darkness[-1] > 0.2  # getting darker
    sim.run(10, False)
    assert sim.ctrl.state == "away"
    assert ("countdown_hide",) in sim.ui.log           # removed once the screens are off


def test_countdown_cancelled_when_you_look_back(sim):
    sim.run(60, True)
    sim.run(5, False)
    assert sim.ui.countdown
    sim.run(2, True)                         # face seen again
    assert ("countdown_hide",) in sim.ui.log
    assert sim.ctrl.state == "present"


def test_countdown_can_be_turned_off(sim):
    sim.ctrl.cfg["away_countdown"] = False
    sim.run(60, True)
    sim.run(30, False)
    assert sim.ui.countdown == [] and sim.ctrl.state == "away"
