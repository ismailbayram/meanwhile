import json

import pytest
from textual.app import App
from textual.binding import Binding
from textual.widgets import Footer

from waitgame import game, scores, state, strings
from waitgame.app import DONE, PLAYING, WAITING, WaitgameApp
from waitgame.pool import Pool, QuizItem
from waitgame.scores import SCORES_RELPATH

pytestmark = pytest.mark.asyncio

QUIZ = QuizItem(
    q="What is passport_groups for?",
    choices=["Tags", "Binds passport groups", "Images"],
    answer=1,
    why="Links passport groups to the category.",
    source="apps/products/models.py",
)
NARROW = QuizItem(q="Two?", choices=["a", "b"], answer=0, why="Because a.", source="x.py")


def app_for(items, status="busy", tmp_path=None, banner="", language="en", agent_source=lambda: None):
    pool = Pool(built_at="2026-08-28", head_sha="abc", repo="demo", items=list(items))
    return WaitgameApp(
        pool=pool,
        repo_dir=tmp_path,
        status_source=lambda: status,
        banner=banner,
        language=language,
        agent_source=agent_source,
    )


def text_of(widget) -> str:
    """Textual 8.2.8 has no `renderable_text`; `visual.plain` is the widget's
    rendered plain text (verified empirically — see task-6-report.md)."""
    return widget.visual.plain


def card_keys(app) -> list[str]:
    """The card keys the Footer is actually displaying.

    Read off the rendered Footer's own children rather than
    `Screen.active_bindings`: active_bindings recomputes on every access, so
    it would look right even if nothing ever called `refresh_bindings()` and
    the footer on screen had gone stale.

    Not every node under the Footer carries a `key`: `Footer.compose` also
    emits `KeyGroup` / `FooterLabel` widgets for grouped bindings, and it nests
    the grouped keys *inside* the KeyGroup rather than yielding them directly.
    This app has no grouped bindings today, so walking the whole subtree and
    skipping anything without a `key` keeps the helper honest either way —
    rather than raising AttributeError, or quietly reporting no keys at all, if
    a grouped binding is ever added.
    """
    return sorted(
        node.key
        for node in app.query_one(Footer).walk_children()
        if hasattr(node, "key") and node.key.isdigit()
    )


def poll(app, times: int = 1) -> None:
    """Drive the busy/idle edge by hand instead of waiting on the interval.

    Every lifecycle test but test_the_poll_interval_is_wired uses this: the
    transitions under test are the app's reaction to a *status change*, not to
    the clock, and a wall-clock pause only makes the same assertion flakier.
    """
    for _ in range(times):
        app._poll_status()


async def drive_to_done(app, pilot) -> None:
    """Drive the fixture to DONE: flip to busy, poll, flip to idle, poll.

    Lifted out of the busy/poll/idle/poll sequence the lifecycle tests below
    already write out inline, rather than writing it a fourth time.
    """
    app.status_source = lambda: "busy"
    poll(app)
    await pilot.pause()
    app.status_source = lambda: "idle"
    poll(app)
    await pilot.pause()


async def test_shows_the_question_text(tmp_path):
    app = app_for([QUIZ], tmp_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "passport_groups" in text_of(app.query_one("#card"))


async def test_correct_key_marks_correct_and_shows_why(tmp_path):
    app = app_for([QUIZ], tmp_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("2")  # 1-indexed: choice 2 is answer index 1
        await pilot.pause()
        assert app.session.correct == 1
        assert "Links passport groups" in text_of(app.query_one("#feedback"))


async def test_out_of_range_choice_is_ignored(tmp_path):
    # Called directly, not via a key: check_action hides every digit past the
    # current card's choice count (3 here), so "9" never reaches the app and a
    # key press would prove nothing about action_choose's own range guard.
    app = app_for([QUIZ], tmp_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_choose(9)
        await pilot.pause()
        assert app.session.answered == 0


async def test_space_advances_to_the_next_card(tmp_path):
    # Two copies of QUIZ, not [QUIZ, NARROW]: game.start_session shuffles with
    # an unseeded random.Random() and WaitgameApp's constructor has no way to
    # inject a seed, so a pool of differently-shaped cards makes this test
    # flaky — "2" is only a valid answer key when the wider card lands first.
    # See tests/test_game.py's own test_wrong_quiz_answer_... for the same
    # [QUIZ, QUIZ] pattern used to sidestep shuffle order.
    app = app_for([QUIZ, QUIZ], tmp_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.press("space")
        await pilot.pause()
        assert app.session.index == 1


async def test_banner_is_rendered_when_the_pool_is_stale(tmp_path):
    app = app_for([QUIZ], tmp_path=tmp_path, banner="pool is 80 commits behind")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "80 commits behind" in text_of(app.query_one("#banner"))


async def test_the_poll_interval_is_wired(tmp_path):
    """The one deliberately timing-based test: everything else drives the edge
    by hand, so this is what proves on_mount's set_interval exists at all —
    nobody calls _poll_status here."""
    status = {"value": "busy"}
    pool = Pool(built_at="x", head_sha="abc", repo="demo", items=[QUIZ])
    app = WaitgameApp(pool=pool, repo_dir=tmp_path, status_source=lambda: status["value"], poll_seconds=0.01)
    async with app.run_test() as pilot:
        await pilot.pause()
        status["value"] = "idle"
        await pilot.pause(0.05)  # five poll intervals
        assert app.phase == DONE


async def test_going_idle_freezes_the_card_and_says_claude_is_done(tmp_path):
    status = {"value": "busy"}
    pool = Pool(built_at="x", head_sha="abc", repo="demo", items=[QUIZ])
    app = WaitgameApp(pool=pool, repo_dir=tmp_path, status_source=lambda: status["value"], poll_seconds=60)
    async with app.run_test() as pilot:
        await pilot.pause()
        status["value"] = "idle"
        poll(app)
        await pilot.pause()
        assert "done" in text_of(app.query_one("#status")).lower()
        assert app.phase == DONE
        await pilot.press("2")
        assert app.session.answered == 0  # done: key not even bound
        app.action_choose(2)  # and the handler refuses it too
        assert app.session.answered == 0


async def test_going_idle_persists_the_session_to_scores_json(tmp_path):
    status = {"value": "busy"}
    pool = Pool(built_at="x", head_sha="abc", repo="demo", items=[QUIZ])
    app = WaitgameApp(pool=pool, repo_dir=tmp_path, status_source=lambda: status["value"], poll_seconds=60)
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()
        assert app.session.answered == 1
        assert app.session.correct == 1

        status["value"] = "idle"
        poll(app)
        await pilot.pause()

        scores_path = tmp_path / SCORES_RELPATH
        assert scores_path.exists()
        saved = json.loads(scores_path.read_text(encoding="utf-8"))
        assert saved["answered"] == app.session.answered
        assert saved["correct"] == app.session.correct


async def test_going_idle_with_no_repo_dir_does_not_write_or_raise(tmp_path):
    status = {"value": "busy"}
    pool = Pool(built_at="x", head_sha="abc", repo="demo", items=[QUIZ])
    app = WaitgameApp(pool=pool, repo_dir=None, status_source=lambda: status["value"], poll_seconds=60)
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()

        status["value"] = "idle"
        poll(app)  # must not raise despite repo_dir=None
        await pilot.pause()

        assert app.phase == DONE
        assert "done" in text_of(app.query_one("#status")).lower()
        assert not (tmp_path / SCORES_RELPATH).exists()


# --- lifecycle: waiting -> playing -> done -> playing ----------------------


def lifecycle_app(items, status, tmp_path, poll_seconds=60):
    # poll_seconds=60: long enough that the interval never fires inside a test,
    # so the only polls are the explicit `poll(app)` calls.
    pool = Pool(built_at="x", head_sha="abc", repo="demo", items=list(items))
    return WaitgameApp(
        pool=pool,
        repo_dir=tmp_path,
        status_source=lambda: status["value"],
        poll_seconds=poll_seconds,
    )


async def test_launching_while_idle_with_no_state_file_waits(tmp_path):
    """The order the README documents: open the pane before submitting a prompt."""
    project = tmp_path / "project"
    project.mkdir()
    empty_state_root = tmp_path / "no-state-here"  # the hooks have never run

    pool = Pool(built_at="x", head_sha="abc", repo="demo", items=[QUIZ])
    app = WaitgameApp(
        pool=pool,
        repo_dir=tmp_path,
        status_source=lambda: state.read_state(project, root=empty_state_root)["status"],
        poll_seconds=60,
    )
    async with app.run_test() as pilot:
        poll(app, times=5)  # several polls: none of them may end the game
        await pilot.pause()
        assert app.phase == WAITING
        assert "done" not in text_of(app.query_one("#status")).lower()
        assert "waiting" in text_of(app.query_one("#status")).lower()
        assert text_of(app.query_one("#card")) == ""

        await pilot.press("2")  # waiting: no card, no input
        assert app.session.answered == 0
        app.action_choose(2)  # and the handler refuses it too
        assert app.session.answered == 0
        assert not (tmp_path / SCORES_RELPATH).exists()


async def test_a_second_busy_period_plays_a_fresh_session(tmp_path):
    status = {"value": "idle"}
    app = lifecycle_app([QUIZ, QUIZ], status, tmp_path)
    async with app.run_test() as pilot:
        poll(app)
        await pilot.pause()
        assert app.phase == WAITING

        status["value"] = "busy"
        poll(app)
        await pilot.pause()
        assert app.phase == PLAYING
        first_session = app.session
        await pilot.press("2")
        await pilot.pause()
        assert app.session.answered == 1

        status["value"] = "idle"
        poll(app)
        await pilot.pause()
        assert app.phase == DONE

        status["value"] = "busy"
        poll(app)
        await pilot.pause()
        assert app.phase == PLAYING
        assert app.session is not first_session
        assert app.session.answered == 0  # a brand-new, re-shuffled session
        assert "done" not in text_of(app.query_one("#status")).lower()

        await pilot.press("2")  # and it takes answers again
        await pilot.pause()
        assert app.session.answered == 1

        status["value"] = "idle"
        poll(app)
        await pilot.pause()
        saved = json.loads((tmp_path / SCORES_RELPATH).read_text(encoding="utf-8"))
        assert saved["answered"] == 2  # both sessions banked, neither one twice


async def test_a_session_is_banked_once_no_matter_how_many_idle_polls(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(scores, "record_session", lambda repo_dir, session: calls.append(session))

    status = {"value": "busy"}
    app = lifecycle_app([QUIZ], status, tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()

        status["value"] = "idle"
        poll(app, times=20)
        # And once more past the busy/idle edge guard, straight at the phase
        # guard that is the only thing standing between DONE and a double bank.
        app._finish_playing()
        await pilot.pause()
        assert len(calls) == 1


async def test_a_session_with_no_answers_is_not_banked(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(scores, "record_session", lambda repo_dir, session: calls.append(session))

    status = {"value": "busy"}
    app = lifecycle_app([QUIZ], status, tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        status["value"] = "idle"
        poll(app)
        await pilot.pause()
        assert app.phase == DONE
        assert calls == []
        assert not (tmp_path / SCORES_RELPATH).exists()


# --- what the footer offers ------------------------------------------------


async def test_a_quiz_card_offers_exactly_its_own_digits(tmp_path):
    app = app_for([QUIZ], tmp_path=tmp_path)  # QUIZ has 3 choices
    async with app.run_test() as pilot:
        await pilot.pause()
        assert card_keys(app) == ["1", "2", "3"]


async def test_the_footer_follows_the_card_not_the_widest_card_in_the_pool(tmp_path):
    """A 2-choice card must offer 1 2 even when the pool holds a 3-choice one."""
    app = app_for([QUIZ, NARROW], tmp_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        seen = []
        for _ in range(2):  # shuffle order is unknown; assert against each card
            item = game.current(app.session)
            seen.append(len(item.choices))
            assert card_keys(app) == [str(n) for n in range(1, len(item.choices) + 1)]
            app.action_choose(1)
            await pilot.pause()
            app.action_next()
            await pilot.pause()
        assert sorted(seen) == [2, 3]  # both widths really were on screen


async def test_the_waiting_screen_offers_no_card_keys(tmp_path):
    app = app_for([QUIZ, NARROW], status="idle", tmp_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.phase == WAITING
        assert card_keys(app) == []


async def test_the_done_screen_offers_no_card_keys(tmp_path):
    status = {"value": "busy"}
    app = lifecycle_app([QUIZ, NARROW], status, tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert card_keys(app) != []  # playing: the current card offers something

        status["value"] = "idle"
        poll(app)
        await pilot.pause()
        assert app.phase == DONE
        assert card_keys(app) == []


# --- odds and ends ---------------------------------------------------------


async def test_the_banner_is_hidden_when_there_is_nothing_to_say(tmp_path):
    app = app_for([QUIZ], tmp_path=tmp_path, banner="")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#banner").display is False


async def test_space_does_nothing_before_the_card_is_answered(tmp_path):
    app = app_for([QUIZ, QUIZ], tmp_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        first = text_of(app.query_one("#card"))
        await pilot.press("space")
        await pilot.pause()
        assert app.session.index == 0
        assert text_of(app.query_one("#card")) == first


# --- language ---------------------------------------------------------


async def test_the_waiting_line_is_turkish_when_the_pool_is(tmp_path):
    app = app_for([QUIZ], status="idle", tmp_path=tmp_path, language="tr")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert text_of(app.query_one("#status")) == strings.text(
            "tr", "waiting", agent=strings.text("tr", "agent")
        )


async def test_the_done_line_names_the_agent_from_the_state_file(tmp_path):
    app = app_for([QUIZ], tmp_path=tmp_path, agent_source=lambda: "codex")
    async with app.run_test() as pilot:
        await drive_to_done(app, pilot)
        assert "Codex" in text_of(app.query_one("#status"))


async def test_an_unknown_agent_falls_back_to_neutral_wording(tmp_path):
    app = app_for([QUIZ], tmp_path=tmp_path, agent_source=lambda: None)
    async with app.run_test() as pilot:
        await drive_to_done(app, pilot)
        status = text_of(app.query_one("#status"))
        assert "Claude" not in status and "Codex" not in status


class GroupedFooterApp(App):
    """A footer whose keys are grouped, which `Footer.compose` renders as a
    `KeyGroup` container plus a `FooterLabel` — neither of which has a `key`."""

    _GROUP = Binding.Group(description="Choices")
    BINDINGS = [
        Binding("1", "choose(1)", "Choice 1", group=_GROUP),
        Binding("2", "choose(2)", "Choice 2", group=_GROUP),
    ]

    def compose(self):
        yield Footer()

    def action_choose(self, number: int) -> None:  # pragma: no cover - never pressed
        pass


async def test_card_keys_survives_a_footer_it_did_not_expect():
    """Guards the helper the footer tests all lean on: a grouped binding must
    make it report the wrong keys and fail an assertion, never AttributeError
    on a Footer child that has no `key`."""
    app = GroupedFooterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        footer_children = app.query_one(Footer).children
        assert any(not hasattr(child, "key") for child in footer_children), (
            f"expected a keyless Footer child; got {[type(c).__name__ for c in footer_children]}"
        )
        assert card_keys(app) == ["1", "2"]
