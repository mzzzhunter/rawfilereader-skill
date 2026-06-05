"""
Data models (plain Python dataclasses) returned by the RawFileAdapter.
All values are converted from .NET types to native Python types here so
callers never need to touch pythonnet objects directly.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class FileInfo:
    """Header-level metadata about the RAW file."""
    file_name: str
    creation_date: str
    operator: str
    comment: str
    sample_name: str
    sample_id: str
    sample_type: str
    vial: str
    instrument_method: str
    tune_method: str
    acquisition_software_version: str
    instrument_name: str
    instrument_serial_number: str
    number_of_ms_orders: int
    has_ms_data: bool
    # Extended IFileHeader fields (populated when available)
    file_description: str = ""
    file_type: str = ""
    revision: int = 0
    modified_date: str = ""
    computer_name: str = ""
    path: str = ""
    who_created_logon: str = ""
    who_modified_logon: str = ""
    number_of_times_calibrated: int = 0
    number_of_times_modified: int = 0


@dataclass
class InstrumentInfo:
    """Per-device instrument metadata."""
    device_type: str        # e.g. "MS", "UV", "PDA", "Analog"
    instance_number: int
    name: str
    model: str
    serial_number: str
    software_version: str
    hardware_version: str
    units: str
    channel_labels: List[str] = field(default_factory=list)


@dataclass
class ScanStats:
    """Statistics for a single scan."""
    scan_number: int
    start_time: float
    low_mass: float
    high_mass: float
    tic: float                # total ion current
    base_peak_mass: float
    base_peak_intensity: float
    packet_count: int
    scan_event_number: int
    master_index: int
    is_centroid_scan: bool


@dataclass
class CentroidData:
    """Centroid (peak-picked) mass spectrum data."""
    scan_number: int
    masses: List[float]
    intensities: List[float]
    charges: List[float]
    baselines: List[float]
    noises: List[float]
    resolutions: List[float]
    is_exceptional: bool
    is_reference: bool

    @property
    def peaks(self) -> List[Tuple[float, float]]:
        """Return (mass, intensity) tuples for all peaks."""
        return list(zip(self.masses, self.intensities))


@dataclass
class ProfileData:
    """Profile (raw) mass spectrum data, as segmented arrays."""
    scan_number: int
    # Each segment is a (positions, intensities) pair
    segments: List[Tuple[List[float], List[float]]] = field(default_factory=list)

    @property
    def masses(self) -> List[float]:
        """Flatten all segment positions into a single list."""
        result: List[float] = []
        for pos, _ in self.segments:
            result.extend(pos)
        return result

    @property
    def intensities(self) -> List[float]:
        """Flatten all segment intensities into a single list."""
        result: List[float] = []
        for _, inten in self.segments:
            result.extend(inten)
        return result


@dataclass
class ScanInfo:
    """High-level metadata about a single scan."""
    scan_number: int
    scan_filter: str            # e.g. "FTMS + p NSI Full ms [200.00-2000.00]"
    ms_order: int               # 1 = MS1, 2 = MS2, …
    retention_time: float       # minutes
    injection_time: float       # ms
    is_centroid: bool
    detector_type: str
    activation_type: str
    precursor_mass: Optional[float] = None
    precursor_charge: Optional[int] = None
    collision_energy: Optional[float] = None
    isolation_width: Optional[float] = None
    monoisotopic_mass: Optional[float] = None
    ion_injection_time: Optional[float] = None


@dataclass
class ChromatogramData:
    """A single chromatogram trace."""
    trace_type: str             # e.g. "BasePeak", "TIC", "MassRange"
    mass_range: str
    times: List[float]
    intensities: List[float]


@dataclass
class TrailerData:
    """Trailer-extra (auxiliary) data appended to a scan."""
    scan_number: int
    fields: dict  # label -> value mapping


@dataclass
class StatusLogEntry:
    """One row from the instrument status log."""
    retention_time: float
    fields: dict  # label -> value mapping


@dataclass
class ScanDependent:
    """Relationship between a parent scan and its dependent (MS^n) scans."""
    scan_number: int
    dependent_scan_numbers: List[int]


@dataclass
class AveragedScan:
    """Result from averaging multiple scans."""
    first_scan: int
    last_scan: int
    masses: List[float]
    intensities: List[float]


@dataclass
class BackgroundSubtractedSpectrum:
    """
    Result of background subtraction using the Thermo Fisher BackgroundSubtractor.

    Produced by :meth:`RawFileAdapter.subtract_background`.
    Requires ``ThermoFisher.CommonCore.BackgroundSubtraction.dll``.

    Unlike :class:`SubtractedSpectrum` (which computes scan A − scan B),
    this model is the output of Thermo's proprietary background-removal
    algorithm, which is aware of the instrument noise model.
    """
    scan_number: int
    background_scans: List[int]   # scan numbers used as background
    scan_filter: str
    masses: List[float]
    intensities: List[float]

    @property
    def peaks(self) -> List[Tuple[float, float]]:
        """Return ``(mass, intensity)`` tuples for all peaks."""
        return list(zip(self.masses, self.intensities))


@dataclass
class SubtractedSpectrum:
    """
    Result of subtracting one mass spectrum from another (scan_a − scan_b).

    Both input scans must share the same scan filter string.  Intensities are
    the signed difference; ``intensities_clipped`` zeros out any negative
    values (i.e. peaks present only in scan_b are removed).
    """
    scan_a: int
    scan_b: int
    scan_filter: str
    mass_range: Optional[Tuple[float, float]]   # None = full range
    is_centroid: bool
    masses: List[float]
    intensities: List[float]            # signed  (scan_a − scan_b)
    intensities_clipped: List[float]    # zeroed-negative version

    @property
    def peaks(self) -> List[Tuple[float, float]]:
        """Return ``(mass, intensity)`` tuples using the clipped intensities."""
        return [(m, i) for m, i in zip(self.masses, self.intensities_clipped) if i > 0]


@dataclass
class MassPrecision:
    """Mass accuracy / precision estimate for a single peak."""
    mass: float
    intensity: float
    resolution: float
    mz_accuracy_ppm: float
    mz_accuracy_mmu: float


@dataclass
class RunHeaderInfo:
    """Extended run-header metadata from IRawData.RunHeaderEx."""
    first_scan: int
    last_scan: int
    start_time: float
    end_time: float
    low_mass: float
    high_mass: float
    mass_resolution: float
    max_intensity: float
    max_integrated_intensity: float
    spectra_count: int
    status_log_count: int
    error_log_count: int
    trailer_extra_count: int
    tune_data_count: int
    expected_run_time: float
    comment1: str
    comment2: str
    in_acquisition: bool
    tolerance_unit: str
    filter_mass_precision: int
    writer_protocol: int


@dataclass
class FileError:
    """Diagnostic error state from IRawDataPlus.FileError."""
    has_error: bool
    error_code: int
    error_message: str
