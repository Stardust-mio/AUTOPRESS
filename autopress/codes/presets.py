# OWNED BY G1 - replace this stub
"""Built-in code formats (extraction presets) - docs/research/ux.md section 3.

| id              | charset       | case     | length          | groups        |
|-----------------|---------------|----------|-----------------|---------------|
| generic         | A-Za-z0-9     | preserve | 6-24            | -             |
| hoyoverse       | A-Za-z0-9     | preserve | 6-16            | -             |
| wuthering_waves | A-Za-z0-9     | preserve | 6-20            | -             |
| blue_archive    | A-Za-z0-9     | preserve | 6-20            | -             |
| steam           | A-Z0-9        | upper    | 15              | [5, 5, 5]     |
| xbox            | A-Z0-9        | upper    | 25              | [5,5,5,5,5]   |
| nintendo        | A-HJ-NP-Y0-9  | upper    | 16-16           | -             |
| custom          | (as generic; the user edits it in the profile)                  |

"generic" keeps the case as written (= models.CodeFormat() defaults): AutoPress never changes
the case of a code unless the format says the platform is case-insensitive (steam, xbox,
nintendo upper-case; decision PX-19). Lengths count charset characters, not separators.
"""

from __future__ import annotations

from ..models import CodeFormat

__stub__ = True

BUILTIN_FORMAT_IDS: tuple[str, ...] = (
    "generic", "hoyoverse", "wuthering_waves", "blue_archive", "steam", "xbox", "nintendo", "custom",
)


def list_formats() -> list[CodeFormat]:
    """Copies of all built-in formats in BUILTIN_FORMAT_IDS order."""
    raise NotImplementedError


def get_format(format_id: str) -> CodeFormat:
    """A copy of the built-in format; unknown ids -> a copy of "generic"."""
    raise NotImplementedError


def format_label(format_id: str) -> str:
    """Localized name, e.g. "通用" / "Generic", "HoYoverse（原神／星鐵／絕區零）"."""
    raise NotImplementedError


def format_example(format_id: str) -> str:
    """Shape hint for the UI, e.g. "XXXXX-XXXXX-XXXXX" (never a real code)."""
    raise NotImplementedError


def detect_format(text: str) -> str:
    """Id of the built-in format that extracts the most likely candidates from ``text``
    (ties: the more specific format - fixed groups/length beat free length). "generic" when
    nothing matches. "custom" is never returned."""
    raise NotImplementedError
