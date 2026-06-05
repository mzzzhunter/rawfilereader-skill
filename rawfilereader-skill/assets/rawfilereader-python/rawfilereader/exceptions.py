"""Custom exceptions for the RawFileReader Python adapter."""


class RawFileError(Exception):
    """Base exception for all RawFileReader errors."""


class RawFileNotOpenError(RawFileError):
    """Raised when attempting to operate on a file that is not open."""


class RawFileInAcquisitionError(RawFileError):
    """Raised when the RAW file is still being acquired (instrument is still running)."""


class InstrumentSelectionError(RawFileError):
    """Raised when an instrument device cannot be selected."""


class ScanNotFoundError(RawFileError):
    """Raised when the requested scan number does not exist in the file."""


class AssemblyLoadError(RawFileError):
    """Raised when the RawFileReader .NET assemblies cannot be loaded."""
