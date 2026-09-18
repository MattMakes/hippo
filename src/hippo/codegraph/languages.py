"""
The language registry: `RULES[lang]` is everything the extractor knows about a language
that is not its grammar.

A language is a *registration*, not a branch. `extract.py`, `resolve.py` and the chunker
ask `RULES` and never name a language; adding one means writing a walker module with a
module-level `RULES_ENTRY` and adding one line here.

**A walker is optional.** A language may be registered for its suffix (`model.LANG_BY_SUFFIX`),
its grammar (`treesitter.GRAMMARS`) and its comment style before anything can parse it: its
files then keep today's line windows and OpenIE and are counted in `files_skipped` as
`unsupported`, exactly as a language we have no grammar for at all. That is what lets the
three grammars ship ahead of the three walkers.

`LanguageRules` itself lives in `model.py` -- the leaf every walker imports -- so that a
walker can build its own entry without importing this module back. It is re-exported here
because `from .languages import LanguageRules, RULES` is the one import a new walker needs.
"""

from __future__ import annotations

from . import csharp as csharp_walker
from . import go as go_walker
from . import python as python_walker
from . import rust as rust_walker
from . import typescript as typescript_walker
from .model import LanguageRules

__all__ = ["PARSED_LANGS", "RULES", "LanguageRules"]

RULES: dict[str, LanguageRules] = {}


def register(entry: LanguageRules) -> LanguageRules:
    """Add one language. Called once per language, at import, in a fixed order."""
    RULES[entry.name] = entry
    return entry


register(python_walker.RULES_ENTRY)
register(typescript_walker.RULES_ENTRY)
register(go_walker.RULES_ENTRY)
register(csharp_walker.RULES_ENTRY)
register(rust_walker.RULES_ENTRY)

# Every language now brings its own walker. `self_names` / `super_names` stay per language
# on purpose: `Self` is Rust's and `base` is C#'s `super`, but `base` is also an ordinary
# Python module name -- `from . import base` then `base.helper()` is a real INVOKES edge,
# and a shared `SUPER_NAMES` holding `base` would silently route it to the MRO instead.

# The languages a walker turns into symbols, derived rather than listed: `git_history.py`
# only reads hunks in files it can parse, and a hand-kept literal would be one more thing a
# new walker has to remember (and one more shared file it has to edit).
PARSED_LANGS = tuple(name for name, rules in RULES.items() if rules.walk is not None)
