"""
RawFileReader Python Adapter
============================
A Python wrapper around the Thermo Fisher Scientific RawFileReader .NET assemblies.
Uses pythonnet (clr) to bridge Python and .NET.
"""

from .adapter import RawFileAdapter
from .models import (
    AveragedScan,
    BackgroundSubtractedSpectrum,
    CentroidData,
    ChromatogramData,
    FileError,
    FileInfo,
    InstrumentInfo,
    MassPrecision,
    ProfileData,
    RunHeaderInfo,
    ScanDependent,
    ScanInfo,
    ScanStats,
    StatusLogEntry,
    SubtractedSpectrum,
    TrailerData,
)
from .exceptions import (
    AssemblyLoadError,
    RawFileError,
    RawFileNotOpenError,
    RawFileInAcquisitionError,
    InstrumentSelectionError,
    ScanNotFoundError,
)

__version__ = "2.0.0"
__all__ = [
    # Main class
    "RawFileAdapter",
    # Models
    "AveragedScan",
    "BackgroundSubtractedSpectrum",
    "CentroidData",
    "ChromatogramData",
    "FileError",
    "FileInfo",
    "InstrumentInfo",
    "MassPrecision",
    "ProfileData",
    "RunHeaderInfo",
    "ScanDependent",
    "ScanInfo",
    "ScanStats",
    "StatusLogEntry",
    "SubtractedSpectrum",
    "TrailerData",
    # Exceptions
    "AssemblyLoadError",
    "RawFileError",
    "RawFileNotOpenError",
    "RawFileInAcquisitionError",
    "InstrumentSelectionError",
    "ScanNotFoundError",
]
