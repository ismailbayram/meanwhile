"""The interface's six strings, in the languages meanwhile ships.

A dictionary, deliberately, and not an i18n framework: there is no catalog to
extract, no compilation step and no locale negotiation. The cards themselves
are written in whatever language the pool was built in; this is only the
chrome around them.
"""

from __future__ import annotations

DEFAULT_LANGUAGE = "en"

KEYS = ("waiting", "done", "exhausted", "stale", "correct", "wrong", "agent")

_TABLE = {
    "en": {
        "agent": "the agent",
        "waiting": "Waiting for {agent} to start working — submit a prompt and the game begins.",
        "done": "{agent} is done ^ — switch back to the diff; this pane keeps running.",
        "exhausted": "Pool exhausted for this wait — the next one deals a fresh round.",
        "stale": "pool is {behind} commits behind — run the build command for fresh questions",
        "correct": "correct",
        "wrong": "wrong",
    },
    "tr": {
        "agent": "ajan",
        "waiting": "{agent} çalışmaya başlayınca oyun başlıyor — bir istem gönder.",
        "done": "{agent} bitirdi ^ — diff'e dön; bu pencere açık kalıyor.",
        "exhausted": "Bu bekleme için havuz bitti — sonraki bekleme yeni bir tur dağıtıyor.",
        "stale": "havuz {behind} commit geride — tazelemek için build komutunu çalıştır",
        "correct": "doğru",
        "wrong": "yanlış",
    },
}


def text(language: str, key: str, **fields) -> str:
    """One string, in `language` if it is shipped and in English otherwise."""
    table = _TABLE.get(language, _TABLE[DEFAULT_LANGUAGE])
    if key not in KEYS:
        raise KeyError(key)
    return table[key].format(**fields) if fields else table[key]
