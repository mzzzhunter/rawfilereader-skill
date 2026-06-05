"""
Assembly loader for the Thermo Fisher RawFileReader .NET libraries.

Supported layouts
-----------------
1. Assemblies alongside this package (installed alongside the Python wheel).
2. User-supplied directory via the RAWFILEREADER_LIBS environment variable.
3. Explicit path passed to :func:`load_assemblies`.

Required DLLs (NetCore build)
------------------------------
- ThermoFisher.CommonCore.Data.dll
- ThermoFisher.CommonCore.RawFileReader.dll
- ThermoFisher.CommonCore.BackgroundSubtraction.dll (optional)
"""

import os
import sys
from pathlib import Path
from typing import Optional

from .exceptions import AssemblyLoadError

_REQUIRED_DLLS = [
    "OpenMcdf",
    "OpenMcdf.Extensions",
    "ThermoFisher.CommonCore.Data",
    "ThermoFisher.CommonCore.RawFileReader",
    "ThermoFisher.CommonCore.BackgroundSubtraction",
]

_loaded = False  # module-level flag to avoid loading twice


def _find_libs_dir() -> Optional[Path]:
    """Return the best candidate directory containing RawFileReader DLLs."""
    # 1. Environment variable
    env = os.environ.get("RAWFILEREADER_LIBS")
    if env:
        return Path(env)

    # 2. Relative to this file (packaged alongside the adapter)
    candidates = [
        Path(__file__).parent.parent / "lib" / "Net8" / "Assemblies",
        Path(__file__).parent.parent / "libs" / "Net8" / "Assemblies",
        Path(__file__).parent.parent / "libs",
        Path(__file__).parent.parent / "Libs",
        Path(__file__).parent / "libs",
    ]
    for c in candidates:
        if c.is_dir():
            return c

    return None


def load_assemblies(libs_dir: Optional[str] = None) -> None:
    """
    Load the RawFileReader .NET assemblies into the current process.

    Parameters
    ----------
    libs_dir:
        Path to the folder containing the RawFileReader DLLs.  When
        *None* the loader searches for a *libs/* directory next to the
        package, then falls back to the ``RAWFILEREADER_LIBS`` environment
        variable.

    Raises
    ------
    AssemblyLoadError
        If pythonnet cannot be imported or required DLLs are missing.
    """
    global _loaded
    if _loaded:
        return

    # pythonnet 3.x needs the runtime selected before `import clr`.
    # The DLLs are built for .NET Core / .NET 5+, so request "coreclr".
    # This is a no-op if the runtime was already initialised.
    try:
        from pythonnet import load as _load_runtime
        _load_runtime("coreclr")
    except Exception:
        pass  # pythonnet < 3.0, or runtime already set

    try:
        import clr  # noqa: F401 (pythonnet)
    except ImportError as exc:
        raise AssemblyLoadError(
            "pythonnet is not installed.  Install it with:  pip install pythonnet"
        ) from exc

    # Resolve the libs directory
    search_dir = Path(libs_dir) if libs_dir else _find_libs_dir()
    if search_dir is None or not search_dir.is_dir():
        raise AssemblyLoadError(
            "Cannot locate the RawFileReader DLL directory.  "
            "Set the RAWFILEREADER_LIBS environment variable to the folder that "
            "contains ThermoFisher.CommonCore.*.dll files, or pass libs_dir= to "
            "load_assemblies()."
        )

    # Add the directory to the .NET search path
    sys.path.append(str(search_dir))

    # Load required assemblies by name (directory is already in sys.path).
    # Passing the name rather than the full path is the reliable pattern for
    # pythonnet 3.x with .NET Core runtimes.
    missing = []
    for name in _REQUIRED_DLLS:
        dll_path = search_dir / f"{name}.dll"
        if not dll_path.exists():
            missing.append(str(dll_path))
            continue
        try:
            clr.AddReference(name)
        except Exception as exc:
            raise AssemblyLoadError(
                f"Failed to load assembly '{name}': {exc}"
            ) from exc

    if missing:
        raise AssemblyLoadError(
            "The following required DLLs were not found:\n" + "\n".join(missing)
        )

    _loaded = True
