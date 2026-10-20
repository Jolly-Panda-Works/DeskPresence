from deskpresence.i18n import t


def popups(sim):
    return [e[1] for e in sim.ui.log if e[0] == "popup"]


def test_water_reminder_every_hour(sim):
    sim.ctrl.cfg["forced_break"]["enabled"] = False
    sim.run(59 * 60, True)
    assert t("water.title") not in popups(sim)
    sim.run(2 * 60, True)
    assert popups(sim).count(t("water.title")) == 1
    sim.run(60 * 60, True)
    assert popups(sim).count(t("water.title")) == 2


def test_water_reminder_waits_until_you_are_back(sim):
    sim.run(30, True)
    sim.run(40 * 60, False)
    sim.run(30 * 60, False)
    assert t("water.title") not in popups(sim)
    sim.run(5, True)
    assert t("water.title") in popups(sim)


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


def test_short_absence_does_not_reset_work_timer(sim):
    sim.run(60 * 60, True)
    sim.run(2 * 60, False)
    sim.run(5, True)
    assert sim.ctrl.next_break_minutes() < 30


def test_skip_ends_break(sim):
    sim.run(91 * 60, True)
    sim.ctrl.end_break(skipped=True)
    assert not sim.ctrl.break_active
    assert t("break.done.title") not in popups(sim)
