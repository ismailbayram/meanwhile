#!/usr/bin/env bash
# Writes meanwhile's busy/idle state file. Invoked by the coding agent's hooks
# (Claude Code, Codex, Cursor).
# Pure bash on purpose: this runs on every prompt submit and must be instant.
set -euo pipefail

# The agent sends a JSON payload on stdin. We do not need it, but we must
# drain it so the writing end never blocks on a full pipe.
cat >/dev/null 2>&1 || true

# Only the two statuses meanwhile.state understands. Anything else — a typo in
# hooks.json, say — would be written verbatim and then silently read back as
# "idle", so refuse it loudly instead. stdout stays empty on purpose: a
# prompt-submit hook's stdout is injected into the agent's context.
status="${1:-}"
case "$status" in
  busy | idle) ;;
  *)
    printf 'meanwhile-state.sh: status must be "busy" or "idle", got %s\n' \
      "${status:-<missing>}" >&2
    exit 1
    ;;
esac

# Optional second argument: which agent is running. Validated rather than
# interpolated blind — this string ends up inside a JSON document.
agent="${2:-}"
if [ -n "$agent" ] && ! [[ "$agent" =~ ^[a-z][a-z-]{0,15}$ ]]; then
  printf 'meanwhile-state.sh: agent must match ^[a-z][a-z-]{0,15}$, got %s\n' "$agent" >&2
  exit 1
fi

# Normalize to match Python's Path(project_dir).resolve() (see
# meanwhile.state.project_key): resolve symlinks and collapse "." / ".." and
# relative or trailing-slash forms to one canonical absolute path. `pwd -P`
# only works on a directory that exists, and resolve() normalizes paths that
# do not, so resolve the deepest existing ancestor and fold the rest in
# lexically — exactly what resolve() does with its non-existent tail.
normalize_dir() {
  local path="$1" head suffix="" part old_ifs
  case "$path" in
    /*) ;;
    *) path="$PWD/$path" ;;
  esac
  while [ "$path" != "/" ] && [ "${path%/}" != "$path" ]; do
    path="${path%/}"
  done

  head="$path"
  while [ "$head" != "/" ] && [ ! -d "$head" ]; do
    suffix="${head##*/}${suffix:+/$suffix}"
    head="${head%/*}"
    [ -n "$head" ] || head="/"
  done
  # `cd -P`, not plain `cd`: bash's default is -L, which folds a ".." that
  # follows a symlinked component lexically instead of resolving the link
  # first. resolve() resolves the link first, so -L would key
  # ".../real/tolink/.." on real's parent rather than on the link's target.
  head="$(cd -P "$head" 2>/dev/null && pwd -P)" || head="/"

  # `head` is now symlink-free and canonical, so the (possibly non-existent)
  # tail can be folded in lexically, exactly as resolve() folds its own:
  # "." drops, ".." pops, anything else appends.
  old_ifs="$IFS"
  IFS='/'
  set -f
  for part in $suffix; do
    case "$part" in
      '' | .) ;;
      ..)
        head="${head%/*}"
        [ -n "$head" ] || head="/"
        ;;
      *)
        if [ "$head" = "/" ]; then head="/$part"; else head="$head/$part"; fi
        ;;
    esac
  done
  set +f
  IFS="$old_ifs"
  printf '%s' "$head"
}

# Claude Code sets CLAUDE_PROJECT_DIR to the directory the session started in.
# Codex and Cursor set nothing, so their hooks fall back to the directory they
# were run from — which is that same directory.
dir="$(normalize_dir "${CLAUDE_PROJECT_DIR:-$PWD}")"

if command -v sha256sum >/dev/null 2>&1; then
  key="$(printf '%s' "$dir" | sha256sum | cut -c1-16)"
else
  key="$(printf '%s' "$dir" | shasum -a 256 | cut -c1-16)"
fi

state_dir="$HOME/.meanwhile/state"
mkdir -p "$state_dir"
tmp="$state_dir/$key.json.tmp.$$"
if [ -n "$agent" ]; then
  printf '{"status":"%s","ts":%s,"agent":"%s"}' "$status" "$(date +%s)" "$agent" > "$tmp"
else
  printf '{"status":"%s","ts":%s}' "$status" "$(date +%s)" > "$tmp"
fi
mv -f "$tmp" "$state_dir/$key.json"
