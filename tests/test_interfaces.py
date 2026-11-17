"""Interface contract (OWNED BY A1): every group module keeps the public API recorded from the
stubs in tests/interface_snapshot.json - names, parameter names/order/kinds, optional
parameters, Qt signals and their signatures, properties, enum members, dataclass fields and
base classes. Additions (new functions, new optional parameters, new members) are allowed.
Also: every module imports without error.
"""

from __future__ import annotations

import builtins
import dataclasses
import importlib
import inspect
import json
from pathlib import Path

import pytest

SNAPSHOT = json.loads((Path(__file__).with_name("interface_snapshot.json")).read_text(encoding="utf-8"))
MODULES: dict[str, dict] = SNAPSHOT["modules"]


def _signal_signatures(cls: object) -> dict[str, str]:
    """Same rule as tools/interface_snapshot.py signal_signatures (class level, no instance)."""
    mo = getattr(cls, "staticMetaObject", None)
    if mo is None:
        return {}
    from PyQt6.QtCore import QMetaMethod

    out: dict[str, str] = {}
    for i in range(mo.methodCount()):
        meth = mo.method(i)
        if meth.methodType() == QMetaMethod.MethodType.Signal:
            sig = bytes(meth.methodSignature()).decode()
            out[sig.split("(", 1)[0]] = sig
    return out


def check_signal_signatures(where: str, cls: object, expected: dict[str, str]) -> list[str]:
    """T24: same signal names AND argument types (methodSignature), e.g. progress(int,int,double)."""
    actual = _signal_signatures(cls)
    return [f"{where}.{name}: signature {actual.get(name)!r}, expected {sig!r}"
            for name, sig in expected.items() if actual.get(name) != sig]

FOUNDATION = ["autopress", "autopress.models", "autopress.i18n", "autopress.paths", "autopress.textutil",
              "autopress.storage", "autopress.logsetup", "autopress.context"]

_KIND = {
    "positional_only": inspect.Parameter.POSITIONAL_ONLY,
    "positional_or_keyword": inspect.Parameter.POSITIONAL_OR_KEYWORD,
    "var_positional": inspect.Parameter.VAR_POSITIONAL,
    "keyword_only": inspect.Parameter.KEYWORD_ONLY,
    "var_keyword": inspect.Parameter.VAR_KEYWORD,
}


def _resolve(qualname: str) -> object:
    mod, _, name = qualname.rpartition(".")
    m = builtins if mod == "builtins" else importlib.import_module(mod)
    obj: object = m
    for part in name.split("."):
        obj = getattr(obj, part)
    return obj


def check_signature(where: str, func: object, expected: list[dict]) -> list[str]:
    try:
        sig = inspect.signature(func)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return []  # builtin (e.g. inherited Qt method): nothing to compare
    params = list(sig.parameters.values())
    problems: list[str] = []
    has_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params)
    positional = [p for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    exp_positional = [e for e in expected if e["kind"] in ("positional_only", "positional_or_keyword")]
    for i, e in enumerate(exp_positional):
        if i >= len(positional):
            problems.append(f"{where}: missing positional parameter '{e['name']}'")
            continue
        p = positional[i]
        if p.name != e["name"] and e["kind"] != "positional_only":
            problems.append(f"{where}: parameter {i} is '{p.name}', expected '{e['name']}'")
        if e["default"] and p.default is inspect.Parameter.empty:
            problems.append(f"{where}: parameter '{e['name']}' lost its default")
    for p in positional[len(exp_positional):]:
        if p.default is inspect.Parameter.empty:
            problems.append(f"{where}: new positional parameter '{p.name}' needs a default")
    by_name = {p.name: p for p in params}
    for e in expected:
        if e["kind"] == "keyword_only":
            p = by_name.get(e["name"])
            if p is None:
                if not has_var_kw:
                    problems.append(f"{where}: missing keyword parameter '{e['name']}'")
            elif p.kind not in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
                problems.append(f"{where}: '{e['name']}' must be usable as a keyword")
            elif e["default"] and p.default is inspect.Parameter.empty:
                problems.append(f"{where}: keyword '{e['name']}' lost its default")
        elif e["kind"] in ("var_positional", "var_keyword"):
            if not any(p.kind is _KIND[e["kind"]] for p in params):
                problems.append(f"{where}: missing *{e['name']} / **{e['name']}")
    exp_names = {e["name"] for e in expected}
    for p in params:
        if p.kind is inspect.Parameter.KEYWORD_ONLY and p.name not in exp_names and p.default is inspect.Parameter.empty:
            problems.append(f"{where}: new keyword parameter '{p.name}' needs a default")
    return problems


def check_module(modname: str, spec: dict) -> list[str]:
    mod = importlib.import_module(modname)
    problems: list[str] = []
    for name in spec["constants"]:
        if not hasattr(mod, name):
            problems.append(f"{modname}.{name}: missing")
    for name, params in spec["functions"].items():
        fn = getattr(mod, name, None)
        if fn is None or not callable(fn):
            problems.append(f"{modname}.{name}(): missing")
            continue
        problems += check_signature(f"{modname}.{name}()", fn, params)
    for cname, info in spec["classes"].items():
        cls = getattr(mod, cname, None)
        if not inspect.isclass(cls):
            problems.append(f"{modname}.{cname}: class missing")
            continue
        where = f"{modname}.{cname}"
        for base in info["bases"]:
            try:
                b = _resolve(base)
            except (ImportError, AttributeError):
                problems.append(f"{where}: base {base} not importable")
                continue
            if inspect.isclass(b) and not issubclass(cls, b):
                problems.append(f"{where}: must subclass {base}")
        for mname, params in info["methods"].items():
            m = getattr(cls, mname, None)
            if m is None:
                problems.append(f"{where}.{mname}(): missing")
                continue
            problems += check_signature(f"{where}.{mname}()", m, params)
        for prop in info["properties"]:
            if not isinstance(inspect.getattr_static(cls, prop, None), property):
                problems.append(f"{where}.{prop}: must be a property")
        for sig in info["signals"]:
            if "Signal" not in type(getattr(cls, sig, None)).__name__:
                problems.append(f"{where}.{sig}: Qt signal missing")
        problems += check_signal_signatures(where, cls, info.get("signal_signatures", {}))
        for member, value in info["enum_members"].items():
            members = getattr(cls, "__members__", None)
            if members is not None:
                if member not in members or members[member].value != value:
                    problems.append(f"{where}.{member}: enum member missing or changed")
            elif not hasattr(cls, member):
                problems.append(f"{where}.{member}: missing")
        for fname in info["fields"]:
            names = {f.name for f in dataclasses.fields(cls)} if dataclasses.is_dataclass(cls) else set(dir(cls))
            if fname not in names:
                problems.append(f"{where}.{fname}: field missing")
    return problems


@pytest.mark.parametrize("modname", FOUNDATION)
def test_foundation_imports(modname: str) -> None:
    importlib.import_module(modname)


@pytest.mark.parametrize("modname", sorted(MODULES))
def test_module_keeps_interface(modname: str) -> None:
    problems = check_module(modname, MODULES[modname])
    assert not problems, "interface changed:\n" + "\n".join(problems)


FAKES = [
    ("tests.fakes.FakeCodeQueue", "autopress.codes.queue", "CodeQueue"),
    ("tests.fakes.FakeHistoryStore", "autopress.codes.history", "HistoryStore"),
    ("tests.fakes.FakeOcrService", "autopress.ocr.service", "OcrService"),
    ("tests.fakes.FakeRunSession", "autopress.runner.engine", "RunSession"),
    ("tests.fakes.FakeHotkeys", "autopress.win32.hotkeys", "GlobalHotkeys"),
]


@pytest.mark.parametrize(("fake", "modname", "cname"), FAKES)
def test_fakes_follow_interfaces(fake: str, modname: str, cname: str) -> None:
    """tests/fakes.py must offer every method, property and signal of the real class."""
    info = MODULES[modname]["classes"][cname]
    cls = _resolve(fake)
    problems: list[str] = []
    for mname, params in info["methods"].items():
        if mname == "__init__":
            continue
        m = getattr(cls, mname, None)
        if m is None:
            problems.append(f"{fake}.{mname}: missing")
        else:
            problems += check_signature(f"{fake}.{mname}()", m, params)
    for prop in info["properties"]:
        if not isinstance(inspect.getattr_static(cls, prop, None), property):
            problems.append(f"{fake}.{prop}: must be a property")
    for sig in info["signals"]:
        if "Signal" not in type(getattr(cls, sig, None)).__name__:
            problems.append(f"{fake}.{sig}: signal missing")
    problems += check_signal_signatures(fake, cls, info.get("signal_signatures", {}))
    assert not problems, "\n".join(problems)


def test_signal_signatures_are_recorded() -> None:
    """The snapshot pins argument types, so e.g. progress(int, int) instead of (int, int, float) fails."""
    session = MODULES["autopress.runner.engine"]["classes"]["RunSession"]["signal_signatures"]
    assert session["progress"] == "progress(int,int,double)"
    assert session["attention"] == "attention(PyQt_PyObject)"


def test_snapshot_covers_all_groups() -> None:
    groups = {name.split(".")[1] if name.startswith("autopress.") and name.count(".") >= 1 else name for name in MODULES}
    assert {"codes", "ocr", "win32", "runner", "ui", "capture", "selftest"} <= groups
