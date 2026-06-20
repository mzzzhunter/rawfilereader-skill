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


def _runtime_config_path() -> Path:
    """Return the bundled configuration that selects a .NET 8+ CoreCLR."""
    return Path(__file__).with_name("rawfilereader.runtimeconfig.json")


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

    # Python.NET defaults to .NET Framework on Windows unless CoreCLR is
    # selected before `import clr`. These assemblies target .NET 8, so use the
    # bundled runtime configuration rather than relying on host defaults.
    runtime_config = _runtime_config_path()
    if not runtime_config.is_file():
        raise AssemblyLoadError(
            f"Missing .NET 8 runtime configuration: {runtime_config}"
        )

    try:
        from pythonnet import load as _load_runtime
    except ImportError as exc:
        raise AssemblyLoadError(
            "pythonnet 3.0.3 or newer is required. Install it with: "
            "pip install 'pythonnet>=3.0.3'"
        ) from exc

    try:
        _load_runtime("coreclr", runtime_config=str(runtime_config))
    except Exception as exc:
        raise AssemblyLoadError(
            "Failed to start the .NET 8 CoreCLR required by the bundled "
            "RawFileReader assemblies. Install the .NET 8 runtime and ensure "
            "that clr has not already been imported with another runtime."
        ) from exc

    try:
        import clr  # noqa: F401 (pythonnet)
    except ImportError as exc:
        raise AssemblyLoadError(
            "pythonnet could not import clr after loading the .NET 8 CoreCLR."
        ) from exc

    from System import Environment

    if Environment.Version.Major < 8:
        raise AssemblyLoadError(
            "The active CLR is "
            f"{Environment.Version}, but the bundled RawFileReader assemblies "
            "require .NET 8 or newer. Start a fresh Python process without "
            "importing clr first."
        )

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
