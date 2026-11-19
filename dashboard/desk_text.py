"""Share desk-owned UI copy with the browser. Never translate user or terminal content."""

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    """Load the bilingual copy catalog once per process."""
    return json.loads(Path(__file__).with_name("strings.json").read_text(encoding="utf-8"))


def preferred_language(header):
    """Pick the highest-priority supported language; command-line diagnostics default to English."""
    chosen, highest = "en", 0.0
    for entry in header.lower().split(","):
        tag, _, weight = entry.strip().partition(";")
        lang = tag.strip().partition("-")[0]
        if lang not in ("fa", "en"):
            continue
        try:
            priority = float(weight.strip().removeprefix("q=")) if weight else 1.0
        except ValueError:
            continue
        if highest < priority <= 1:
            chosen, highest = lang, priority
    return chosen


_FA_NUMERALS = str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬")


class Message:
    """A translatable desk string: a catalog key plus its substitution values."""

    def __init__(self, key, **values):
        """Store the key and the values used to format it."""
        self.key, self.values = key, values

    def render(self, lang="en"):
        """Format the copy in one language, localizing numerals for Persian."""

        def display(value):
            """Render a nested value: Message, localized number, or untouched text."""
            if isinstance(value, Message):
                return value.render(lang)
            if isinstance(value, int) and not isinstance(value, bool):
                number = f"{value:,}"
                return number.translate(_FA_NUMERALS) if lang == "fa" else number
            return value  # identifiers, URLs and user text are not numerals to translate

        return catalog()[self.key][lang].format_map({k: display(v) for k, v in self.values.items()})

    def wire(self):
        """Return the ``{key, vars}`` form the browser re-renders after a language switch."""
        return {
            "key": self.key,
            "vars": {k: v.wire() if isinstance(v, Message) else v for k, v in self.values.items()},
        }

    def __str__(self):
        """Render in English for command-line diagnostics."""
        return self.render()


def error_detail(exc):
    """Preserve structured copy through wrappers (e.g. failure after partial creation)."""
    if isinstance(exc, BaseException):
        if exc.args and isinstance(exc.args[0], Message):
            return exc.args[0]
        return str(exc)
    return exc
