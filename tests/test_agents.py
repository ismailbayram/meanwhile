import copy
import re
import shlex
import subprocess

import pytest

from waitgame import agents

SCRIPT = "/home/x/.waitgame/waitgame-state.sh"


def test_every_agent_has_a_distinct_slug_and_a_label():
    slugs = [a.slug for a in agents.AGENTS]
    assert sorted(slugs) == ["claude", "codex", "cursor"]
    assert len(set(slugs)) == len(slugs)
    assert all(a.label and agents.SLUG_PATTERN.match(a.slug) for a in agents.AGENTS)


def test_the_event_names_are_exactly_the_ones_each_agent_fires():
    """The four literals nothing else can check.

    A typo in any one of them is a total, permanently silent failure for that
    agent — the hook is registered under an event the agent never fires, so the
    pane simply never wakes. Every other test looks the events up through
    `registered_commands`, which reads them back out of the same constants
    `merge` wrote them under, so a wrong name is invisible there. Only spelling
    them out here can catch it.
    """
    events = {agent.slug: (agent.busy_event, agent.idle_event) for agent in agents.AGENTS}
    assert events == {
        "claude": ("UserPromptSubmit", "Stop"),
        "codex": ("UserPromptSubmit", "Stop"),
        "cursor": ("beforeSubmitPrompt", "stop"),
    }


def test_cursor_refuses_user_scope_and_the_others_allow_it():
    scopes = {a.slug: a.supports_user_scope for a in agents.AGENTS}
    assert scopes == {"claude": True, "codex": True, "cursor": False}


def test_label_for_known_and_unknown_slugs():
    assert agents.label_for("codex") == "Codex"
    assert agents.label_for("nope") is None
    assert agents.label_for(None) is None


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_merge_into_an_empty_document_registers_both_events(slug):
    agent = agents.agent_by_slug(slug)
    document = agents.merge({}, agent, SCRIPT)
    commands = agents.registered_commands(document, agent)
    assert len(commands) == 2
    assert any(c.endswith(f"busy {slug}") for c in commands)
    assert any(c.endswith(f"idle {slug}") for c in commands)
    assert all(SCRIPT in c for c in commands)


def test_cursor_documents_carry_the_version_field():
    document = agents.merge({}, agents.agent_by_slug("cursor"), SCRIPT)
    assert document["version"] == 1


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_merge_preserves_another_tools_hooks(slug):
    agent = agents.agent_by_slug(slug)
    theirs = {
        "hooks": {agent.busy_event: [{"command": "their-script.sh"}]},
        "somethingElse": {"keep": True},
    }
    before = copy.deepcopy(theirs)
    document = agents.merge(theirs, agent, SCRIPT)
    assert document["somethingElse"] == {"keep": True}
    assert json_contains(document, "their-script.sh")
    assert theirs == before, "merge must not mutate its argument"


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_merging_twice_does_not_duplicate(slug):
    agent = agents.agent_by_slug(slug)
    once = agents.merge({}, agent, SCRIPT)
    twice = agents.merge(once, agent, SCRIPT)
    assert agents.registered_commands(twice, agent) == agents.registered_commands(once, agent)


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_merging_a_new_script_path_replaces_the_old_entry(slug):
    agent = agents.agent_by_slug(slug)
    old = agents.merge({}, agent, "/old/waitgame-state.sh")
    new = agents.merge(old, agent, SCRIPT)
    commands = agents.registered_commands(new, agent)
    assert len(commands) == 2
    assert all(SCRIPT in c for c in commands)


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_unmerge_removes_only_our_entries(slug):
    agent = agents.agent_by_slug(slug)
    theirs = {"hooks": {agent.busy_event: [{"command": "their-script.sh"}]}}
    document = agents.unmerge(agents.merge(theirs, agent, SCRIPT), agent)
    assert agents.registered_commands(document, agent) == []
    assert json_contains(document, "their-script.sh")


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_unmerge_leaves_no_empty_event_behind(slug):
    agent = agents.agent_by_slug(slug)
    document = agents.unmerge(agents.merge({}, agent, SCRIPT), agent)
    assert not document.get("hooks")


@pytest.mark.parametrize("slug", ["claude", "codex"])
def test_merge_preserves_foreign_hooks_in_the_same_entry(slug):
    """An entry can bundle multiple commands under a shared matcher.
    When we merge, we strip our stale command but keep the foreign one and the matcher.
    """
    agent = agents.agent_by_slug(slug)
    # An entry with a foreign command and a stale waitgame command under one matcher
    theirs = {
        "hooks": {
            agent.busy_event: [
                {
                    "matcher": "some-condition",
                    "hooks": [
                        {"type": "command", "command": "their-command.sh", "timeout": 5},
                        {"type": "command", "command": "/old/waitgame-state.sh busy claude", "timeout": 5},
                    ],
                }
            ]
        }
    }
    document = agents.merge(theirs, agent, SCRIPT)

    # The foreign command survives
    assert json_contains(document, "their-command.sh")
    # Our commands are registered (busy + idle)
    commands = agents.registered_commands(document, agent)
    assert len(commands) == 2
    assert any(c.endswith(f"busy {slug}") for c in commands)
    assert any(c.endswith(f"idle {slug}") for c in commands)
    assert SCRIPT in commands[0]


@pytest.mark.parametrize("slug", ["claude", "codex"])
def test_unmerge_preserves_foreign_hooks_in_the_same_entry(slug):
    """When unmerging, the foreign command survives even if in the same entry."""
    agent = agents.agent_by_slug(slug)
    theirs = {
        "hooks": {
            agent.busy_event: [
                {
                    "matcher": "some-condition",
                    "hooks": [
                        {"type": "command", "command": "their-command.sh", "timeout": 5},
                        {"type": "command", "command": SCRIPT + f" busy {agent.slug}", "timeout": 5},
                    ],
                }
            ]
        }
    }
    document = agents.unmerge(theirs, agent)

    # The foreign command and entry survive
    assert json_contains(document, "their-command.sh")
    # Our command is gone
    assert agents.registered_commands(document, agent) == []


def test_unmerge_removes_empty_entries():
    """When an entry holds only our hooks, unmerge removes the entire entry."""
    agent = agents.agent_by_slug("claude")
    document = {
        "hooks": {
            agent.busy_event: [
                {
                    "hooks": [
                        {"type": "command", "command": SCRIPT + " busy claude", "timeout": 5}
                    ]
                }
            ]
        }
    }
    result = agents.unmerge(document, agent)

    # The entry should be completely removed
    assert not result.get("hooks")


def json_contains(document, needle: str) -> bool:
    import json

    return needle in json.dumps(document)


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_entries_that_are_not_hook_entries_are_carried_through(slug):
    """`merge` filters at the hook level, so it has to decide what to do with a
    neighbour it cannot read. Dropping it would be a silent deletion of
    somebody else's content."""
    agent = agents.agent_by_slug(slug)
    document = {"hooks": {agent.idle_event: ["a bare string", 7]}}

    merged = agents.merge(document, agent, SCRIPT)
    assert merged["hooks"][agent.idle_event][:2] == ["a bare string", 7]

    back = agents.unmerge(merged, agent)
    assert back["hooks"][agent.idle_event] == ["a bare string", 7]


def test_an_event_whose_value_is_not_an_array_is_not_thrown_away():
    """Malformed for every agent we know, but still somebody's content."""
    agent = agents.agent_by_slug("codex")
    stranger = {"hooks": [{"command": "theirs.sh"}]}

    merged = agents.merge({"hooks": {agent.idle_event: stranger}}, agent, SCRIPT)
    assert stranger in merged["hooks"][agent.idle_event]
    assert len(agents.registered_commands(merged, agent)) == 2

    # unmerge leaves a non-array value exactly as it found it: nothing of ours
    # can be inside one, because merge only ever writes an array.
    untouched = agents.unmerge({"hooks": {agent.idle_event: stranger}}, agent)
    assert untouched["hooks"][agent.idle_event] == stranger


# --- a script path the shell must not touch --------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        '/home/o"neill/.waitgame/waitgame-state.sh',
        "/home/$USER/.waitgame/waitgame-state.sh",
        "/home/`whoami`/.waitgame/waitgame-state.sh",
        "/home/a b/.waitgame/waitgame-state.sh",
    ],
)
def test_a_home_directory_the_shell_would_mangle_is_quoted(hostile):
    """The path comes from the user's home directory, so we do not get to
    assume it is tame. Inside a bare pair of double quotes a `"` ends the
    quoting and a `$` or a backtick is expanded — either way the hook runs
    against a path that does not exist, with no symptom but a pane that never
    wakes."""
    command = agents.command_for(hostile, agents.agent_by_slug("codex"), "busy")
    assert shlex.split(command) == [hostile, "busy", "codex"]


def test_the_shell_really_runs_a_hostile_path_unchanged(tmp_path):
    """`shlex.split` is our reading of the quoting; this is the shell's."""
    home = tmp_path / 'o"neill $HOME `whoami`'
    home.mkdir()
    script = home / "waitgame-state.sh"
    script.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$0" "$1" "$2"\n')
    script.chmod(0o755)

    command = agents.command_for(str(script), agents.agent_by_slug("codex"), "idle")
    result = subprocess.run(["bash", "-c", command], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [str(script), "idle", "codex"]
