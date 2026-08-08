"""Surface extraction for P7h's drift pins.

P7h mirrors four legacy surfaces as hexagon Protocols without moving anything:
the legacy modules stay where 1158 tests and an unedited ``bokeh_operator.py``
find them, and each port is a structural mirror beside them. A mirror that can
fall behind its subject is worse than no mirror -- it reads as a contract while
describing something that no longer exists -- so every P7h port test asserts
its two surfaces **set-equal in both directions**.

Both directions is the whole point. ``isinstance`` against a
``runtime_checkable`` Protocol compares *names only*, and only the names the
Protocol happens to declare: a Protocol that had dropped half the ABC would
keep passing. So would a Protocol that had grown a method the legacy surface
never had. The helpers here return plain name sets, and the pin is a bare
``==`` between them, which reports both differences at once.
"""

__all__ = [
    "abc_surface",
    "module_functions",
    "protocol_members",
]

import inspect
from typing import get_protocol_members


def protocol_members(protocol) -> set:
    """Every member name a ``Protocol`` declares.

    Includes annotated data attributes, not just methods -- ``OrchBackend``
    declares four library dicts alongside its 25 methods and a mirror that
    dropped them would be silently narrower than its subject.
    """
    return set(get_protocol_members(protocol))


def abc_surface(cls) -> set:
    """Every member name an ABC declares: abstract methods plus annotations.

    Annotations are part of the surface for the same reason as above. They are
    read off ``cls`` alone rather than walking the MRO, because what is being
    mirrored is what *this* class states -- a base class's fields belong to the
    base class's mirror.
    """
    return set(cls.__abstractmethods__) | set(getattr(cls, "__annotations__", {}))


def module_functions(*modules) -> set:
    """Public function names *defined* in the given modules.

    ``__module__`` filtering matters: these modules import each other
    (``sources`` imports ``readers.make_zip_locator``) and a re-export is not
    part of the importing module's own surface -- counting it would demand the
    same name twice in a two-module port and make the union depend on import
    order.

    Constants are deliberately excluded. ``PARAM_KINDS``, ``INDEX_COLUMNS`` and
    ``GROUPS`` are data a caller reads directly; they are not seam methods, and
    ``ports/param_store.py`` mirrors the one that is a contract
    (``PARAM_KINDS``) as a pinned constant instead.
    """
    names = set()
    for module in modules:
        for name, obj in vars(module).items():
            if name.startswith("_"):
                continue
            if inspect.isfunction(obj) and obj.__module__ == module.__name__:
                names.add(name)
    return names
