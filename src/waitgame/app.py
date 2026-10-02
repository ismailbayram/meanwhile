"""The terminal UI. Renders cards; all rules live in waitgame.game."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Static

from . import agents, game, scores, strings
from .pool import Pool, QuizItem

# Lifecycle phases. The pane is opened once and left open: it waits for the
# agent to start, plays for exactly as long as it is busy, then waits again.
WAITING = "waiting"
PLAYING = "playing"
DONE = "done"


class WaitgameApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "waitgame"

    # Every key the game can ever offer is declared here, statically. Which of
    # them the footer actually shows is decided per card by `check_action`.
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("space", "next", "Next card"),
        *[(str(n), f"choose({n})", f"Choice {n}") for n in range(1, 10)],
    ]

    # The actions `check_action` gates; everything else is always available.
    CARD_ACTIONS = ("choose",)

    def __init__(
        self,
        pool: Pool,
        repo_dir: Path,
        status_source: Callable[[], str],
        banner: str = "",
        poll_seconds: float = 0.5,
        language: str = "en",
        agent_source: Callable[[], str | None] = lambda: None,
    ) -> None:
        super().__init__()
        self.pool = pool
        self.repo_dir = repo_dir
        self.status_source = status_source
        self.banner = banner
        self.poll_seconds = poll_seconds
        self.language = language
        self.agent_source = agent_source
        self.session = game.start_session(pool)
        self.phase = WAITING
        self._last_status = "idle"
        self._answered = False

    def _agent_name(self) -> str:
        return agents.label_for(self.agent_source()) or strings.text(self.language, "agent")

    # --- dynamic bindings -------------------------------------------------

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Offer only the keys the card on screen can actually take.

        A three-choice card should not fill a narrow pane's footer with
        "Choice 4" .. "Choice 9". Returning False is what *removes* a binding:
        verified on Textual 8.2.8, True shows it, None shows it greyed out,
        and only False keeps it out of `Screen.active_bindings` — and so out
        of the Footer — entirely.

        This decides what the footer advertises and what a keypress may reach;
        the guards in the action handlers stay the last line of defence.
        """
        if action not in self.CARD_ACTIONS:
            return True
        if self.phase != PLAYING:
            return False
        item = game.current(self.session)
        return isinstance(item, QuizItem) and 1 <= int(parameters[0]) <= len(item.choices)

    def compose(self) -> ComposeResult:
        # markup=False: card/feedback text comes from an untrusted pool.json
        # (see pool.py) and from literal "[space] next" hints — neither should
        # be parsed as Textual console markup.
        with Vertical():
            yield Static(self.banner, id="banner", markup=False)
            yield Static("", id="status", markup=False)
            yield Static("", id="card", markup=False)
            yield Static("", id="feedback", markup=False)
            yield Static("", id="score", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#banner").display = bool(self.banner)
        self._render()
        # Poll once up front so a pane opened while the agent is already busy
        # joins that wait instead of sitting out until the first tick.
        self._poll_status()
        self.set_interval(self.poll_seconds, self._poll_status)

    # --- status ---------------------------------------------------------

    def _poll_status(self) -> None:
        """Drive the lifecycle off the edges of the busy/idle state file."""
        status = self.status_source()
        if status == self._last_status:
            return
        self._last_status = status
        if status == "busy":
            self._start_playing()
        else:
            self._finish_playing()

    def _start_playing(self) -> None:
        self.phase = PLAYING
        self.session = game.start_session(self.pool)  # re-shuffled: the cards come back
        self._answered = False
        self.query_one("#status").update("")
        self.query_one("#feedback").update("")
        self._render()

    def _finish_playing(self) -> None:
        if self.phase != PLAYING:
            return
        self.phase = DONE
        self.refresh_bindings()  # DONE takes no input: the card keys leave the footer
        self.query_one("#status").update(strings.text(self.language, "done", agent=self._agent_name()))
        # Exactly once per session: the `phase != PLAYING` guard above is what
        # guarantees it — the only way back into PLAYING is _start_playing,
        # which deals a new session.
        if self.repo_dir is not None and self.session.answered:
            scores.record_session(self.repo_dir, self.session)

    # --- actions --------------------------------------------------------

    def action_choose(self, number: int) -> None:
        item = game.current(self.session)
        if self.phase != PLAYING or self._answered or not isinstance(item, QuizItem):
            return
        index = number - 1
        if not 0 <= index < len(item.choices):
            return
        self._resolve(game.answer(self.session, index))

    def action_next(self) -> None:
        if self.phase != PLAYING or not self._answered:
            return
        game.advance(self.session)
        self._answered = False
        self.query_one("#feedback").update("")
        self._render()

    # --- rendering ------------------------------------------------------

    def _resolve(self, verdict: game.Verdict) -> None:
        self._answered = True
        mark = strings.text(self.language, "correct" if verdict.correct else "wrong")
        self.query_one("#feedback").update(f"{mark} — {verdict.explanation}   [space] next")
        self._render_score()

    def _render(self) -> None:
        # The card (or the phase) has just changed, so the footer's answer for
        # `check_action` has too.
        self.refresh_bindings()
        card = self.query_one("#card")
        if self.phase == WAITING:
            self.query_one("#status").update(strings.text(self.language, "waiting", agent=self._agent_name()))
            card.update("")
            self.query_one("#score").update("")
            return

        item = game.current(self.session)
        if item is None:
            card.update(strings.text(self.language, "exhausted"))
        elif isinstance(item, QuizItem):
            choices = "\n".join(f"  {n}. {text}" for n, text in enumerate(item.choices, start=1))
            card.update(f"{item.q}\n\n{choices}\n\n({item.source})")
        self._render_score()

    def _render_score(self) -> None:
        self.query_one("#score").update(
            f"{self.session.correct}/{self.session.answered} correct   "
            f"streak {self.session.streak} (best {self.session.best_streak})"
        )
