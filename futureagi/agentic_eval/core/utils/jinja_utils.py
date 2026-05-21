"""Shared helpers for Jinja-based prompt rendering across evaluators."""

from __future__ import annotations

from typing import Any


def nest_dotted_value(container: dict, parts: list[str], value: Any) -> None:
    """Nest ``value`` at ``parts`` path; numeric components become list indices."""
    target: Any = container
    for i, part in enumerate(parts[:-1]):
        next_is_numeric = parts[i + 1].isdigit()
        child_factory = list if next_is_numeric else dict
        if isinstance(target, list):
            idx = int(part)
            while len(target) <= idx:
                target.append(None)
            if not isinstance(target[idx], child_factory):
                target[idx] = child_factory()
            target = target[idx]
        else:
            existing = target.get(part)
            if not isinstance(existing, child_factory):
                existing = child_factory()
                target[part] = existing
            target = existing

    leaf = parts[-1]
    if isinstance(target, list):
        idx = int(leaf)
        while len(target) <= idx:
            target.append(None)
        target[idx] = value
    else:
        target[leaf] = value
