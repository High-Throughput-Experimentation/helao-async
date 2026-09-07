"""Load the EC-Lib 2.0 Python layer from a configured path.

The SDK ships no installable distribution -- no ``pyproject.toml``, no
``setup.py`` -- and its package directory is named, unhelpfully, ``Python``, so
there is nothing to pin in ``helao_dev_win-64.yml``. A station unpacks the SDK
somewhere and names it in the server's config (``sdk_path``); off-station,
:mod:`sim` stands in.

**It has to be registered as top-level ``Python``, and only once.** Almost every
internal import is relative, which would have let us pick our own module name --
but ``Exceptions/EC_SDK_Runtime_Error.py`` does
``from Python.Constants.bl_constants import ErrorCode``, an absolute import of
that literal name, so ``sys.modules["Python"]`` must exist for the package to
import at all. Registering it under a private name *as well as* ``Python`` by
importing it twice would be worse than the ugly name: there would then be two
``ErrorCode`` enums and two of every struct, and an ``except``/``is`` against
the wrong copy would silently never match. So it is imported once under
``Python`` and aliased to :data:`VENDOR_MODULE_NAME`, and a foreign
``sys.modules["Python"]`` is refused rather than clobbered.

Layout expected under ``sdk_path``::

    <sdk_path>/Python/ECLibAPI.py       the API class
    <sdk_path>/Python/Constants/        enums, structs, ctypes specs
    <sdk_path>/lib/eclib64.dll          the library itself
    <sdk_path>/license_biologic_*.lic   per the SDK's "Using the library"

Enum members are resolved *by name* here, never by value, for two reasons the
shipped enums make concrete: ``VsInitial`` gives ``EC_SDK_VS_IREF`` and
``EC_SDK_VS_EREF`` the same value ``0`` (so the second is a Python alias whose
``.name`` reads back as the first), and ``IRangeValue`` gives
``EC_SDK_IRANGE_BOOSTER_3A0`` and ``..._30A`` both the value ``14``. Name
lookup handles aliases correctly; a value round-trip would not.
"""

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The name the vendor package *must* be registered under, because one of its
#: own modules imports ``Python.Constants.bl_constants`` absolutely. Not a
#: choice.
VENDOR_PACKAGE_NAME = "Python"

#: Alias registered alongside :data:`VENDOR_PACKAGE_NAME`, pointing at the same
#: module object, so nothing downstream has to say ``import Python``.
VENDOR_MODULE_NAME = "helao_vendor_eclib2"

#: Stamped on the loaded module so a second load can tell our package from
#: someone else's top-level ``Python``, and can tell which SDK root it came
#: from.
SDK_ROOT_MARKER = "__helao_eclib2_sdk_root__"

DLL_RELATIVE_PATH = Path("lib") / "eclib64.dll"
PACKAGE_RELATIVE_PATH = Path("Python")
LICENSE_GLOB = "license_biologic_*.lic"


@dataclass(frozen=True)
class SdkModules:
    """The pieces of the vendor package the driver needs.

    Attributes:
        api_class: The vendor ``ECLibAPI`` class, constructed with a DLL path.
        constants: The ``Constants`` module, holding every enum and struct.
        error_class: ``EC_SDK_Runtime_Error``, which every vendor call raises
            on a non-zero return.
        sdk_root: Where this was loaded from.
    """

    api_class: type
    constants: Any
    error_class: type
    sdk_root: Path


def _import_vendor_package(package_dir: Path, sdk_root: Path) -> Any:
    """Import a package directory as top-level :data:`VENDOR_PACKAGE_NAME`."""
    init = package_dir / "__init__.py"
    if not init.is_file():
        raise FileNotFoundError(f"not a Python package: {package_dir} (no __init__.py)")
    spec = importlib.util.spec_from_file_location(
        VENDOR_PACKAGE_NAME, init, submodule_search_locations=[str(package_dir)]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not build an import spec for {package_dir}")
    module = importlib.util.module_from_spec(spec)
    setattr(module, SDK_ROOT_MARKER, str(sdk_root))
    # Registered before exec_module, so both the package's relative imports and
    # its one absolute `Python.Constants.bl_constants` import resolve.
    sys.modules[VENDOR_PACKAGE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        # A registered-but-unexecuted module would make the next load return a
        # stub whose attributes are all missing, with no error.
        sys.modules.pop(VENDOR_PACKAGE_NAME, None)
        for name in [
            n for n in list(sys.modules) if n.startswith(f"{VENDOR_PACKAGE_NAME}.")
        ]:
            del sys.modules[name]
        raise
    return module


def _existing_vendor_package(sdk_root: Path) -> Any | None:
    """The already-loaded vendor package, if it is ours and from ``sdk_root``.

    Raises:
        ImportError: If something else owns top-level ``Python``, or if a
            different SDK root is already loaded in this process. Two SDK roots
            cannot coexist: the second would need the same module name, and
            silently serving the first one's DLL bindings under the second
            one's config would be undiagnosable.
    """
    module = sys.modules.get(VENDOR_PACKAGE_NAME)
    if module is None:
        return None
    loaded_root = getattr(module, SDK_ROOT_MARKER, None)
    if loaded_root is None:
        raise ImportError(
            f"a foreign top-level {VENDOR_PACKAGE_NAME!r} module is already "
            f"imported ({getattr(module, '__file__', '?')}); the EC-Lib 2.0 SDK "
            "requires that name and will not clobber it"
        )
    if loaded_root != str(sdk_root):
        raise ImportError(
            f"the EC-Lib 2.0 SDK is already loaded from {loaded_root}; "
            f"cannot also load {sdk_root} in the same process"
        )
    return module


def load_sdk(sdk_path: str | Path, module_name: str = VENDOR_MODULE_NAME) -> SdkModules:
    """Import the vendor Python layer from ``sdk_path``.

    Does not load the DLL; see :func:`open_api`. Splitting the two lets a
    station verify its SDK layout without touching hardware.

    Args:
        sdk_path: SDK root, containing ``Python/`` and ``lib/``.
        module_name: Alias to register alongside ``Python``, pointing at the
            same module object.

    Raises:
        FileNotFoundError: If the SDK layout is not what is expected.
        ImportError: If top-level ``Python`` is taken, or a different SDK root
            is already loaded in this process.
    """
    root = Path(sdk_path).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"sdk_path is not a directory: {root}")
    package_dir = root / PACKAGE_RELATIVE_PATH
    if not package_dir.is_dir():
        raise FileNotFoundError(
            f"no {PACKAGE_RELATIVE_PATH} package under {root}; "
            "point sdk_path at the unpacked biologic_ec_sdk root"
        )

    module = _existing_vendor_package(root)
    if module is None:
        module = _import_vendor_package(package_dir, root)
    # Same object under both names, so there is exactly one copy of every enum.
    sys.modules[module_name] = module
    constants = importlib.import_module(f"{VENDOR_PACKAGE_NAME}.Constants")
    exceptions = importlib.import_module(f"{VENDOR_PACKAGE_NAME}.Exceptions")
    return SdkModules(
        api_class=module.ECLibAPI,
        constants=constants,
        error_class=exceptions.EC_SDK_Runtime_Error,
        sdk_root=root,
    )


def unload(module_name: str = VENDOR_MODULE_NAME) -> None:
    """Forget the loaded vendor package.

    Only useful for tests and for pointing a process at a different SDK root;
    the DLL itself is not unloaded, so this does not reset device state.
    """
    module = sys.modules.get(VENDOR_PACKAGE_NAME)
    if module is not None and hasattr(module, SDK_ROOT_MARKER):
        for name in [
            n
            for n in list(sys.modules)
            if n == VENDOR_PACKAGE_NAME or n.startswith(f"{VENDOR_PACKAGE_NAME}.")
        ]:
            del sys.modules[name]
    sys.modules.pop(module_name, None)


def dll_path(sdk_path: str | Path) -> Path:
    """Where the library lives under an SDK root."""
    return Path(sdk_path).expanduser() / DLL_RELATIVE_PATH


def has_license(sdk_path: str | Path) -> bool:
    """Whether a license file is present where the SDK expects one.

    Per the SDK's "Using the library": the ``license_biologic_<hexblob>.lic``
    file must sit at the package root, and it is what authorises instrument
    models, techniques and options (EIS is licensed separately). Without it
    every call fails with ``EC_SDK_ERROR_LICENSE_NOT_VALID`` (-99900), which is
    worth naming up front rather than discovering at the first acquisition.
    """
    root = Path(sdk_path).expanduser()
    return any(root.glob(LICENSE_GLOB))


def open_api(sdk_path: str | Path, module_name: str = VENDOR_MODULE_NAME) -> tuple:
    """Load the vendor package and construct its API object over the DLL.

    Returns:
        ``(api, modules)`` -- the ``ECLibAPI`` instance and its
        :class:`SdkModules`.

    Raises:
        FileNotFoundError: If the SDK layout or the DLL is missing.
    """
    modules = load_sdk(sdk_path, module_name)
    dll = dll_path(sdk_path)
    if not dll.is_file():
        raise FileNotFoundError(f"no EC-Lib library at {dll}")
    return modules.api_class(str(dll)), modules


def member(constants: Any, enum_name: str, member_name: str) -> Any:
    """Resolve ``member_name`` in the vendor enum ``enum_name``.

    Args:
        constants: A vendor ``Constants`` module (or the simulator's stand-in).
        enum_name: e.g. ``"IRangeValue"``.
        member_name: e.g. ``"EC_SDK_IRANGE_1mA"``.

    Raises:
        ValueError: If either name is absent. A missing member means this SDK
            build does not have the value the plan asked for, which must not be
            silently coerced into a neighbouring range.
    """
    try:
        enum_cls = getattr(constants, enum_name)
    except AttributeError:
        raise ValueError(f"vendor constants have no enum {enum_name!r}") from None
    try:
        return enum_cls[member_name]
    except KeyError:
        raise ValueError(
            f"{enum_name} has no member {member_name!r} in this SDK build"
        ) from None
