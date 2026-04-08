"""Lightweight reactive state primitives for NiceGUI pages.

Replaces the common ``dict[str, X] = {"value": ...}`` pattern used throughout
the codebase to work around Python's closure-rebinding limitation.

Usage::

    count = Ref(0)
    count.value += 1

    items = ListRef[Task]()
    items.extend(new_tasks)
    items.clear()

    selected = SetRef[int]()
    selected.add(42)
"""

from __future__ import annotations

from typing import Generic, Iterator, TypeVar

T = TypeVar("T")


class Ref(Generic[T]):
    """A mutable reference wrapper — the equivalent of ``React.useRef`` / ``Vue ref()``.

    Holds a single ``.value`` that can be read and written inside closures
    without the dict-based workaround.
    """

    __slots__ = ("value",)

    def __init__(self, value: T) -> None:
        self.value: T = value

    def __repr__(self) -> str:
        return f"Ref({self.value!r})"

    def set(self, value: T) -> None:
        """Alias for ``self.value = value``."""
        self.value = value

    def get(self) -> T:
        """Alias for ``self.value``."""
        return self.value


class ListRef(Generic[T]):
    """A mutable list wrapper that can be shared across closures.

    Supports common list operations directly (no ``.value`` indirection).
    """

    __slots__ = ("_data",)

    def __init__(self, initial: list[T] | None = None) -> None:
        self._data: list[T] = list(initial) if initial else []

    def __repr__(self) -> str:
        return f"ListRef({self._data!r})"

    def __iter__(self) -> Iterator[T]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, index: int | slice) -> T | list[T]:
        return self._data[index]  # type: ignore[return-value]

    def __bool__(self) -> bool:
        return bool(self._data)

    @property
    def items(self) -> list[T]:
        """Return the underlying list (read-only alias)."""
        return self._data

    def clear(self) -> None:
        self._data.clear()

    def append(self, item: T) -> None:
        self._data.append(item)

    def extend(self, items: list[T] | tuple[T, ...]) -> None:
        self._data.extend(items)

    def replace(self, items: list[T]) -> None:
        """Clear and replace all items at once."""
        self._data.clear()
        self._data.extend(items)


class SetRef(Generic[T]):
    """A mutable set wrapper that can be shared across closures."""

    __slots__ = ("_data",)

    def __init__(self, initial: set[T] | None = None) -> None:
        self._data: set[T] = set(initial) if initial else set()

    def __repr__(self) -> str:
        return f"SetRef({self._data!r})"

    def __iter__(self) -> Iterator[T]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, item: T) -> bool:  # type: ignore[override]
        return item in self._data

    def __bool__(self) -> bool:
        return bool(self._data)

    def add(self, item: T) -> None:
        self._data.add(item)

    def discard(self, item: T) -> None:
        self._data.discard(item)

    def clear(self) -> None:
        self._data.clear()

    def intersection_update(self, other: set[T]) -> None:
        self._data.intersection_update(other)
