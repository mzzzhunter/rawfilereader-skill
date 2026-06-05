"""
RawFileAdapter — Python wrapper around the Thermo Fisher RawFileReader .NET assemblies.

All public methods return plain Python dataclasses from :mod:`rawfilereader.models`.
.NET objects never leak to callers.

Usage::

    from rawfilereader import RawFileAdapter

    with RawFileAdapter("sample.raw") as rf:
        info = rf.get_file_info()
        print(info.instrument_name)
"""

from __future__ import annotations

import os
from typing import Dict, Iterator, List, Optional, Tuple, Union

from .exceptions import (
    AssemblyLoadError,
    InstrumentSelectionError,
    RawFileInAcquisitionError,
    RawFileNotOpenError,
    ScanNotFoundError,
)
from .loader import load_assemblies
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


# ---------------------------------------------------------------------------
# .NET reflection helper
# ---------------------------------------------------------------------------

def _reflect_call(obj, method_name, *args):
    """
    Invoke a .NET instance method via reflection.

    pythonnet 3.x interface proxies only expose methods declared on the
    specific interface type.  Some methods (e.g. AverageScansInScanRange,
    SubtractScans) live on the concrete RawFileAccess class and are
    unreachable via normal attribute access.  Explicit interface
    implementations carry a fully-qualified name suffix, so we search
    public methods first, then widen to non-public with name-suffix matching.
    """
    import System  # type: ignore
    from System.Reflection import BindingFlags  # type: ignore

    nargs = len(args)

    method = next(
        (m for m in obj.GetType().GetMethods()
         if m.Name == method_name and m.GetParameters().Length == nargs),
        None,
    )

    if method is None:
        all_flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance
        method = next(
            (m for m in obj.GetType().GetMethods(all_flags)
             if (m.Name == method_name or m.Name.endswith("." + method_name))
             and m.GetParameters().Length == nargs),
            None,
        )

    if method is None:
        raise AttributeError(
            f"'{obj.GetType().Name}' has no method '{method_name}' "
            f"with {nargs} parameter(s)"
        )

    arg_array = System.Array[System.Object](list(args))
    return method.Invoke(obj, arg_array)


# ---------------------------------------------------------------------------
# Pure-Python helpers (no .NET dependency)
# ---------------------------------------------------------------------------

def _apply_mass_range(
    masses: List[float],
    intensities: List[float],
    mass_range: Optional[Tuple[float, float]],
) -> Tuple[List[float], List[float]]:
    """Filter parallel mass/intensity lists to *mass_range* (inclusive)."""
    if mass_range is None:
        return masses, intensities
    lo, hi = mass_range
    pairs = [(m, i) for m, i in zip(masses, intensities) if lo <= m <= hi]
    if not pairs:
        return [], []
    m_out, i_out = zip(*pairs)
    return list(m_out), list(i_out)


def _normalize_to_tic(intensities: List[float]) -> List[float]:
    """Divide all intensities by their sum (TIC normalisation)."""
    tic = sum(intensities)
    if tic == 0:
        return intensities[:]
    return [v / tic for v in intensities]


def _find_closest(
    target: float,
    sorted_masses: List[float],
    tol_ppm: float,
) -> Optional[int]:
    """Binary-search *sorted_masses* for the index closest to *target* within *tol_ppm*."""
    if not sorted_masses:
        return None
    tol_da = target * tol_ppm * 1e-6
    lo, hi = 0, len(sorted_masses) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if sorted_masses[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    best_idx: Optional[int] = None
    best_delta = tol_da
    for idx in (hi, lo):
        if 0 <= idx < len(sorted_masses):
            delta = abs(sorted_masses[idx] - target)
            if delta <= best_delta:
                best_delta = delta
                best_idx = idx
    return best_idx


def _py_subtract_peaks(
    fg_masses: List[float],
    fg_intensities: List[float],
    bg_masses: List[float],
    bg_intensities: List[float],
    tol_ppm: float = 5.0,
) -> Tuple[List[float], List[float]]:
    """Subtract background peaks from foreground peaks using ppm-tolerance matching.

    For each foreground peak, the closest background peak within *tol_ppm* is
    found and its intensity subtracted. Peaks with non-positive net intensity are
    dropped. Used as a fallback when the .NET AverageScans API is unavailable.
    """
    out_masses: List[float] = []
    out_intensities: List[float] = []
    for m, i in zip(fg_masses, fg_intensities):
        idx = _find_closest(m, bg_masses, tol_ppm)
        bg_i = bg_intensities[idx] if idx is not None else 0.0
        net_i = i - bg_i
        if net_i > 0:
            out_masses.append(m)
            out_intensities.append(net_i)
    return out_masses, out_intensities


def _linear_interp(
    x_out: List[float],
    x_in: List[float],
    y_in: List[float],
) -> List[float]:
    """Linearly interpolate (x_in, y_in) at each point in x_out. Out-of-range → 0."""
    if not x_in or not y_in:
        return [0.0] * len(x_out)
    result: List[float] = []
    j = 0
    n = len(x_in)
    for x in x_out:
        while j < n - 1 and x_in[j + 1] <= x:
            j += 1
        if x < x_in[0] or x > x_in[-1]:
            result.append(0.0)
        elif x == x_in[j]:
            result.append(y_in[j])
        elif j + 1 < n:
            t = (x - x_in[j]) / (x_in[j + 1] - x_in[j])
            result.append(y_in[j] + t * (y_in[j + 1] - y_in[j]))
        else:
            result.append(y_in[j])
    return result


def _average_centroid_peaks(
    scan_masses_list: List[List[float]],
    scan_intensities_list: List[List[float]],
    tol_ppm: float = 5.0,
) -> Tuple[List[float], List[float]]:
    """Merge and average centroid peaks from multiple scans.

    Peaks across scans that fall within *tol_ppm* of one another are grouped,
    their masses intensity-weighted averaged, and their intensities summed then
    divided by the total number of scans (so zeros are implicit for scans that
    had no peak in that window).
    """
    n_scans = len(scan_masses_list)
    if n_scans == 0:
        return [], []

    all_peaks: List[Tuple[float, float]] = []
    for masses, intensities in zip(scan_masses_list, scan_intensities_list):
        for m, i in zip(masses, intensities):
            all_peaks.append((m, i))

    if not all_peaks:
        return [], []

    all_peaks.sort(key=lambda p: p[0])

    out_masses: List[float] = []
    out_intensities: List[float] = []

    idx = 0
    while idx < len(all_peaks):
        ref_mass = all_peaks[idx][0]
        group_m: List[float] = []
        group_i: List[float] = []
        j = idx
        while j < len(all_peaks):
            m, i = all_peaks[j]
            if abs(m - ref_mass) / ref_mass * 1e6 <= tol_ppm:
                group_m.append(m)
                group_i.append(i)
                j += 1
            else:
                break
        total_i = sum(group_i)
        if total_i > 0:
            avg_mass = sum(m * i for m, i in zip(group_m, group_i)) / total_i
        else:
            avg_mass = sum(group_m) / len(group_m)
        out_masses.append(avg_mass)
        out_intensities.append(total_i / n_scans)
        idx = j

    return out_masses, out_intensities


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class RawFileAdapter:
    """
    Python adapter for reading Thermo Scientific RAW files via RawFileReader.

    Parameters
    ----------
    raw_file_path : str
        Path to the ``.raw`` file.
    libs_dir : str, optional
        Directory containing the RawFileReader DLLs. Falls back to the
        ``RAWFILEREADER_LIBS`` environment variable or auto-discovery.
    instrument_type : str
        Device type to select on open (default ``"MS"``).
    instrument_instance : int
        1-based device instance number (default ``1``).
    """

    DEVICE_TYPES = ("MS", "MSAnalog", "UV", "PDA", "Analog", "ADCard", "Lyra")

    def __init__(
        self,
        raw_file_path: str,
        libs_dir: Optional[str] = None,
        instrument_type: str = "MS",
        instrument_instance: int = 1,
    ) -> None:
        self._path = os.path.abspath(raw_file_path)
        self._libs_dir = libs_dir
        self._instrument_type = instrument_type
        self._instrument_instance = instrument_instance
        self._raw_file = None  # .NET IRawDataPlus object, set in open()

        # .NET types stored after open() — never imported inside method bodies
        self._Device = None
        self._MassRange = None
        self._MassOptions = None
        self._BackgroundSubtractor = None
        self._ScanAveragerPlus = None
        self._Scan = None
        self._DotNetList = None
        self._Int32 = None
        self._Array = None
        self._ChromatogramTraceSettings = None
        self._TraceType = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "RawFileAdapter":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self) -> str:
        state = "open" if self.is_open else "closed"
        return f"RawFileAdapter({os.path.basename(self._path)!r}, {state})"

    # ------------------------------------------------------------------
    # Open / close
    # ------------------------------------------------------------------

    def open(self) -> None:
        """
        Open the RAW file and select the default instrument device.

        All .NET assemblies are loaded and all required .NET types are imported
        here in one block — no method body ever performs its own import.

        Raises
        ------
        FileNotFoundError
        RawFileNotOpenError
        RawFileInAcquisitionError
        InstrumentSelectionError
        AssemblyLoadError
        """
        if not os.path.exists(self._path):
            raise FileNotFoundError(f"RAW file not found: {self._path}")

        load_assemblies(self._libs_dir)

        # ---- All .NET imports in one place --------------------------------
        from ThermoFisher.CommonCore.RawFileReader import RawFileReaderAdapter  # type: ignore
        from ThermoFisher.CommonCore.Data.Business import (  # type: ignore
            Device,
            ChromatogramTraceSettings,
            MassOptions,
            Range as MassRange,
            Scan,
            TraceType,
        )
        from ThermoFisher.CommonCore.BackgroundSubtraction import (  # type: ignore
            BackgroundSubtractor,
            ScanAveragerPlus,
        )
        from System.Collections.Generic import List as DotNetList  # type: ignore
        from System import Int32, Array, Enum as DotNetEnum  # type: ignore
        # -------------------------------------------------------------------

        self._Device = Device
        self._MassRange = MassRange
        self._MassOptions = MassOptions
        self._BackgroundSubtractor = BackgroundSubtractor
        self._ScanAveragerPlus = ScanAveragerPlus
        self._Scan = Scan
        self._DotNetList = DotNetList
        self._Int32 = Int32
        self._Array = Array
        self._DotNetEnum = DotNetEnum
        self._ChromatogramTraceSettings = ChromatogramTraceSettings
        self._TraceType = TraceType

        from ThermoFisher.CommonCore.Data.Business import ChromatogramSignal  # type: ignore
        self._ChromatogramSignal = ChromatogramSignal

        raw = RawFileReaderAdapter.FileFactory(self._path)
        if not raw.IsOpen or raw.IsError:
            raise RawFileNotOpenError(f"RawFileReader could not open: {self._path}")
        if raw.InAcquisition:
            raise RawFileInAcquisitionError(f"File is still being acquired: {self._path}")

        self._raw_file = raw
        self.select_instrument(self._instrument_type, self._instrument_instance)

    def close(self) -> None:
        """Close the RAW file and release .NET resources."""
        if self._raw_file is not None:
            self._raw_file.Dispose()
            self._raw_file = None

    @property
    def is_open(self) -> bool:
        """``True`` if the file is currently open."""
        return self._raw_file is not None and self._raw_file.IsOpen

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _check_open(self) -> None:
        if not self.is_open:
            raise RawFileNotOpenError("File is not open. Call open() first.")

    def _check_scan(self, scan_number: int) -> None:
        first, last = self.get_scan_range()
        if not (first <= scan_number <= last):
            raise ScanNotFoundError(
                f"Scan {scan_number} is outside the valid range [{first}, {last}]."
            )

    def _get_device(self, device_type: str):
        """Resolve a device-type string to the .NET Device enum value."""
        try:
            return self._DotNetEnum.Parse(self._Device, device_type)
        except Exception:
            raise InstrumentSelectionError(
                f"Unknown device type '{device_type}'. "
                f"Valid types: {self.DEVICE_TYPES}"
            )

    def _get_trailer_dict(self, scan_number: int) -> dict:
        """Return trailer-extra label→value dict for *scan_number*."""
        try:
            trailer = self._raw_file.GetTrailerExtraInformation(scan_number)
            return {str(k): str(v) for k, v in zip(trailer.Labels, trailer.Values)}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Instrument selection
    # ------------------------------------------------------------------

    def select_instrument(self, device_type: str, instance: int = 1) -> None:
        """Select an instrument device for subsequent data reads."""
        self._check_open()
        device = self._get_device(device_type)
        try:
            self._raw_file.SelectInstrument(device, instance)
        except Exception as exc:
            raise InstrumentSelectionError(
                f"Cannot select {device_type} instance {instance}: {exc}"
            ) from exc

    def get_instrument_count(self) -> int:
        """Return the total number of instrument devices in the file."""
        self._check_open()
        return int(self._raw_file.InstrumentCount)

    def get_instrument_count_of_type(self, device_type: str) -> int:
        """Return the number of devices of *device_type*."""
        self._check_open()
        return int(self._raw_file.GetInstrumentCountOfType(self._get_device(device_type)))

    def get_instrument_type(self, index: int) -> str:
        """Return the device-type string for the 0-based *index*."""
        self._check_open()
        return str(self._raw_file.GetInstrumentType(index))

    def get_instrument_data(self) -> InstrumentInfo:
        """Return metadata for the currently selected instrument device."""
        self._check_open()
        d = self._raw_file.GetInstrumentData()
        channel_labels: List[str] = []
        try:
            channel_labels = [str(label) for label in d.ChannelLabels]
        except Exception:
            pass
        return InstrumentInfo(
            device_type=self._instrument_type,
            instance_number=self._instrument_instance,
            name=str(d.Name),
            model=str(d.Model),
            serial_number=str(d.SerialNumber),
            software_version=str(d.SoftwareVersion),
            hardware_version=str(d.HardwareVersion),
            units=str(d.Units),
            channel_labels=channel_labels,
        )

    # ------------------------------------------------------------------
    # File / run metadata
    # ------------------------------------------------------------------

    def get_file_info(self) -> FileInfo:
        """Return file-level metadata (operator, sample, instrument, …)."""
        self._check_open()
        fh = self._raw_file.FileHeader
        si = self._raw_file.SampleInformation
        rh = self._raw_file.RunHeaderEx
        idata = self._raw_file.GetInstrumentData()
        def _s(obj, attr):
            return str(getattr(obj, attr, ""))
        def _i(obj, attr, default=0):
            try:
                return int(getattr(obj, attr, default) or default)
            except Exception:
                return default

        return FileInfo(
            file_name=str(self._raw_file.FileName),
            creation_date=_s(fh, "CreationDate"),
            operator=_s(fh, "WhoCreatedId"),
            comment=_s(si, "Comment"),
            sample_name=_s(si, "SampleName"),
            sample_id=_s(si, "SampleId"),
            sample_type=_s(si, "SampleType"),
            vial=_s(si, "Vial"),
            instrument_method=_s(si, "InstrumentMethod"),
            tune_method=_s(si, "TuneMethod"),
            acquisition_software_version=_s(fh, "FileDescription"),
            instrument_name=_s(idata, "Name"),
            instrument_serial_number=_s(idata, "SerialNumber"),
            number_of_ms_orders=int(getattr(rh, "MsOrderCount", 0)),
            has_ms_data=bool(getattr(rh, "HasMsData", True)),
            # Extended fields
            file_description=_s(fh, "FileDescription"),
            file_type=_s(fh, "FileType"),
            revision=_i(fh, "Revision"),
            modified_date=_s(fh, "ModifiedDate"),
            computer_name=_s(self._raw_file, "ComputerName"),
            path=_s(self._raw_file, "Path"),
            who_created_logon=_s(fh, "WhoCreatedLogon"),
            who_modified_logon=_s(fh, "WhoModifiedLogon"),
            number_of_times_calibrated=_i(fh, "NumberOfTimesCalibrated"),
            number_of_times_modified=_i(fh, "NumberOfTimesModified"),
        )

    def get_scan_range(self) -> Tuple[int, int]:
        """Return ``(first_scan, last_scan)`` for the selected instrument."""
        self._check_open()
        rh = self._raw_file.RunHeaderEx
        return int(rh.FirstSpectrum), int(rh.LastSpectrum)

    def get_start_time(self) -> float:
        """Return the acquisition start time in minutes."""
        self._check_open()
        return float(self._raw_file.RunHeaderEx.StartTime)

    def get_end_time(self) -> float:
        """Return the acquisition end time in minutes."""
        self._check_open()
        return float(self._raw_file.RunHeaderEx.EndTime)

    def get_instrument_method(self, index: int = 0) -> str:
        """Return the text of the instrument method at *index*."""
        self._check_open()
        return str(self._raw_file.GetInstrumentMethod(index))

    def get_all_instrument_names_from_method(self) -> List[str]:
        """Return the list of instrument names embedded in the method."""
        self._check_open()
        return [str(n) for n in self._raw_file.GetAllInstrumentNamesFromInstrumentMethod()]

    # ------------------------------------------------------------------
    # Scan filters & events
    # ------------------------------------------------------------------

    def get_filters(self) -> List[str]:
        """Return all unique scan-filter strings present in the file."""
        self._check_open()
        return [f.ToString() for f in self._raw_file.GetFilters()]

    def get_filter_for_scan(self, scan_number: int) -> str:
        """Return the scan-filter string for *scan_number*."""
        self._check_open()
        self._check_scan(scan_number)
        return self._raw_file.GetFilterForScanNumber(scan_number).ToString()

    def get_scan_event_for_scan(self, scan_number: int) -> dict:
        """Return a dict of scan-event parameters for *scan_number*."""
        self._check_open()
        self._check_scan(scan_number)
        ev = self._raw_file.GetScanEventForScanNumber(scan_number)
        result: dict = {}
        try:
            result["MSOrder"] = int(ev.MSOrder)
            result["Polarity"] = str(ev.Polarity)
            result["ScanType"] = str(ev.ScanType)
            result["Detector"] = str(ev.Detector)
            result["MassRangeCount"] = int(ev.MassRangeCount)
            if hasattr(ev, "ScanEventNumber"):
                result["ScanEventNumber"] = int(ev.ScanEventNumber)
        except Exception:
            pass
        return result

    # ------------------------------------------------------------------
    # Scan statistics & retention time
    # ------------------------------------------------------------------

    def get_scan_stats(self, scan_number: int) -> ScanStats:
        """Return per-scan statistics (TIC, base peak, mass range, …)."""
        self._check_open()
        self._check_scan(scan_number)
        st = self._raw_file.GetScanStatsForScanNumber(scan_number)
        filt = self._raw_file.GetFilterForScanNumber(scan_number).ToString()
        return ScanStats(
            scan_number=scan_number,
            start_time=float(st.StartTime),
            low_mass=float(st.LowMass),
            high_mass=float(st.HighMass),
            tic=float(st.TIC),
            base_peak_mass=float(st.BasePeakMass),
            base_peak_intensity=float(st.BasePeakIntensity),
            packet_count=int(st.PacketCount),
            scan_event_number=int(st.ScanEventNumber),
            master_index=int(getattr(st, "MasterIndex", 0)),
            is_centroid_scan=bool(getattr(st, "IsCentroidScan", "FTMS" in filt.upper())),
        )

    def get_retention_time(self, scan_number: int) -> float:
        """Return the retention time in minutes for *scan_number*."""
        self._check_open()
        self._check_scan(scan_number)
        return float(self._raw_file.RetentionTimeFromScanNumber(scan_number))

    def scan_number_from_retention_time(self, retention_time: float) -> int:
        """Return the scan number whose retention time is closest to *retention_time* (minutes)."""
        self._check_open()
        rh = self._raw_file.RunHeaderEx
        first_rt = float(self._raw_file.RetentionTimeFromScanNumber(int(rh.FirstSpectrum)))
        last_rt = float(self._raw_file.RetentionTimeFromScanNumber(int(rh.LastSpectrum)))
        if not (first_rt <= retention_time <= last_rt):
            raise ValueError(
                f"retention_time {retention_time:.4f} min is outside the file range "
                f"[{first_rt:.4f}, {last_rt:.4f}] min."
            )
        return int(self._raw_file.ScanNumberFromRetentionTime(retention_time))

    # ------------------------------------------------------------------
    # Spectral data
    # ------------------------------------------------------------------

    def get_centroid_stream(
        self, scan_number: int, prefer_profile_data: bool = False
    ) -> CentroidData:
        """Return centroid (peak-picked) mass spectrum data for *scan_number*."""
        self._check_open()
        self._check_scan(scan_number)
        cs = self._raw_file.GetCentroidStream(scan_number, prefer_profile_data)
        return CentroidData(
            scan_number=scan_number,
            masses=[float(m) for m in cs.Masses] if cs.Masses else [],
            intensities=[float(i) for i in cs.Intensities] if cs.Intensities else [],
            charges=[float(c) for c in cs.Charges] if cs.Charges else [],
            baselines=[float(b) for b in cs.Baselines] if cs.Baselines else [],
            noises=[float(n) for n in cs.Noises] if cs.Noises else [],
            resolutions=[float(r) for r in cs.Resolutions] if cs.Resolutions else [],
            is_exceptional=bool(getattr(cs, "IsExceptional", False)),
            is_reference=bool(getattr(cs, "IsReference", False)),
        )

    def get_profile_data(self, scan_number: int) -> ProfileData:
        """Return raw profile (continuous) data for *scan_number*."""
        self._check_open()
        self._check_scan(scan_number)
        stats = self._raw_file.GetScanStatsForScanNumber(scan_number)
        seg = self._raw_file.GetSegmentedScanFromScanNumber(scan_number, stats)
        segments: List[Tuple[List[float], List[float]]] = []
        if seg is not None:
            try:
                positions = [float(p) for p in seg.Positions]
                intensities = [float(i) for i in seg.Intensities]
                segments.append((positions, intensities))
            except Exception:
                pass
        return ProfileData(scan_number=scan_number, segments=segments)

    # ------------------------------------------------------------------
    # Comprehensive scan info
    # ------------------------------------------------------------------

    def get_scan_info(self, scan_number: int) -> ScanInfo:
        """Return a consolidated ScanInfo combining filter, event, stats, and trailer data."""
        self._check_open()
        self._check_scan(scan_number)

        filter_str = self._raw_file.GetFilterForScanNumber(scan_number).ToString()
        ev = self._raw_file.GetScanEventForScanNumber(scan_number)
        rt = float(self._raw_file.RetentionTimeFromScanNumber(scan_number))
        ms_order = int(ev.MSOrder)
        trailer = self._get_trailer_dict(scan_number)
        inj_time = float(trailer.get("Ion Injection Time (ms)", 0.0) or 0.0)

        precursor_mass: Optional[float] = None
        precursor_charge: Optional[int] = None
        collision_energy: Optional[float] = None
        isolation_width: Optional[float] = None
        monoisotopic_mass: Optional[float] = None

        if ms_order >= 2:
            try:
                reaction = ev.GetReaction(0)
                precursor_mass = float(reaction.PrecursorMass)
                collision_energy = float(reaction.CollisionEnergy)
                isolation_width = float(reaction.IsolationWidth)
            except Exception:
                pass
            try:
                mz = float(trailer.get("Monoisotopic M/Z:", 0.0) or 0.0)
                if mz:
                    precursor_mass = mz
                    monoisotopic_mass = mz
            except Exception:
                pass
            try:
                charge = int(trailer.get("Charge State:", 0) or 0)
                precursor_charge = charge or None
            except Exception:
                pass

        return ScanInfo(
            scan_number=scan_number,
            scan_filter=filter_str,
            ms_order=ms_order,
            retention_time=rt,
            injection_time=inj_time,
            is_centroid="FTMS" in filter_str.upper() or "FT" in filter_str.upper(),
            detector_type=str(getattr(ev, "Detector", "")),
            activation_type="",
            precursor_mass=precursor_mass,
            precursor_charge=precursor_charge,
            collision_energy=collision_energy,
            isolation_width=isolation_width,
            monoisotopic_mass=monoisotopic_mass,
            ion_injection_time=inj_time or None,
        )

    # ------------------------------------------------------------------
    # Scan averaging
    # ------------------------------------------------------------------

    def average_scans_in_range(
        self,
        first_scan: int,
        last_scan: int,
        filter_string: Optional[str] = None,
    ) -> AveragedScan:
        """Average all scans between *first_scan* and *last_scan* (inclusive).

        Tries the native ``AverageScansInScanRange`` DLL call first (faster
        for large ranges); falls back to per-scan centroid reads merged in
        Python if the method is not available on this DLL version.
        """
        self._check_open()
        opts = self._MassOptions()
        try:
            avg = _reflect_call(
                self._raw_file, "AverageScansInScanRange",
                first_scan, last_scan, filter_string or "", opts,
            )
            masses = [float(m) for m in avg.PreferredMasses] if avg.PreferredMasses else []
            intensities = [float(i) for i in avg.PreferredIntensities] if avg.PreferredIntensities else []
            return AveragedScan(first_scan=first_scan, last_scan=last_scan,
                                masses=masses, intensities=intensities)
        except (AttributeError, Exception):
            pass

        # Python fallback
        scan_masses: List[List[float]] = []
        scan_intensities: List[List[float]] = []
        for scan_num in range(first_scan, last_scan + 1):
            try:
                data = self.get_centroid_stream(scan_num)
                scan_masses.append(data.masses)
                scan_intensities.append(data.intensities)
            except Exception:
                continue
        masses, intensities = _average_centroid_peaks(scan_masses, scan_intensities)
        return AveragedScan(first_scan=first_scan, last_scan=last_scan,
                            masses=masses, intensities=intensities)

    def average_scans(self, scan_numbers: List[int]) -> AveragedScan:
        """Average the spectra for an arbitrary list of *scan_numbers*.

        Tries the native ``AverageScans(List<int>, MassOptions)`` DLL call
        first; falls back to per-scan centroid reads merged in Python.
        """
        self._check_open()
        opts = self._MassOptions()
        try:
            dn_list = self._DotNetList[self._Int32]()
            for s in scan_numbers:
                dn_list.Add(self._Int32(s))
            avg = _reflect_call(self._raw_file, "AverageScans", dn_list, opts)
            masses = [float(m) for m in avg.PreferredMasses] if avg.PreferredMasses else []
            intensities = [float(i) for i in avg.PreferredIntensities] if avg.PreferredIntensities else []
            return AveragedScan(first_scan=min(scan_numbers), last_scan=max(scan_numbers),
                                masses=masses, intensities=intensities)
        except (AttributeError, Exception):
            pass

        # Python fallback
        scan_masses: List[List[float]] = []
        scan_intensities: List[List[float]] = []
        for scan_num in scan_numbers:
            try:
                data = self.get_centroid_stream(scan_num)
                scan_masses.append(data.masses)
                scan_intensities.append(data.intensities)
            except Exception:
                continue
        masses, intensities = _average_centroid_peaks(scan_masses, scan_intensities)
        return AveragedScan(first_scan=min(scan_numbers), last_scan=max(scan_numbers),
                            masses=masses, intensities=intensities)

    # ------------------------------------------------------------------
    # Chromatogram
    # ------------------------------------------------------------------

    def get_chromatogram(
        self,
        trace_type: str = "BasePeak",
        mass_range: str = "",
        start_scan: int = -1,
        end_scan: int = -1,
    ) -> ChromatogramData:
        """
        Extract a chromatogram trace from the file.

        Parameters
        ----------
        trace_type : str
            One of ``"BasePeak"``, ``"TIC"``, ``"MassRange"``, ``"EIC"``, ``"NeutralLoss"``.
        mass_range : str
            Mass range string for ``"MassRange"`` / ``"EIC"`` traces, e.g. ``"500.0-510.0"``.
        start_scan, end_scan : int
            Scan range. Use ``-1`` for the full file range.
        """
        self._check_open()
        _nl = getattr(self._TraceType, "NeutralLoss", None)
        trace_map = {
            "BasePeak": self._TraceType.BasePeak,
            "TIC": self._TraceType.TIC,
            "MassRange": self._TraceType.MassRange,
            "EIC": self._TraceType.MassRange,
            **( {"NeutralLoss": _nl} if _nl is not None else {} ),
        }
        dn_trace = trace_map.get(trace_type, self._TraceType.BasePeak)
        settings = self._ChromatogramTraceSettings(dn_trace)
        if mass_range:
            lo_str, hi_str = mass_range.rsplit("-", 1)
            settings.MassRanges = self._Array[self._MassRange](
                [self._MassRange(float(lo_str), float(hi_str))]
            )

        first, last = self.get_scan_range()
        s0 = start_scan if start_scan > 0 else first
        s1 = end_scan if end_scan > 0 else last

        settings_array = self._Array[self._ChromatogramTraceSettings]([settings])
        data = self._raw_file.GetChromatogramData(settings_array, s0, s1)
        signals = self._ChromatogramSignal.FromChromatogramData(data)
        sig = signals[0]

        return ChromatogramData(
            trace_type=trace_type,
            mass_range=mass_range,
            times=[float(t) for t in sig.Times] if sig.Times else [],
            intensities=[float(i) for i in sig.Intensities] if sig.Intensities else [],
        )

    # ------------------------------------------------------------------
    # Trailer / status logs
    # ------------------------------------------------------------------

    def get_trailer_data(self, scan_number: int) -> TrailerData:
        """Return trailer-extra (auxiliary) data for *scan_number*."""
        self._check_open()
        self._check_scan(scan_number)
        return TrailerData(scan_number=scan_number, fields=self._get_trailer_dict(scan_number))

    def get_trailer_header_info(self) -> List[str]:
        """Return all trailer-extra field labels defined in the file."""
        self._check_open()
        return [str(h.Label) for h in self._raw_file.GetTrailerExtraHeaderInformation()]

    def get_status_log_header_info(self) -> List[str]:
        """Return all status-log field labels defined in the file."""
        self._check_open()
        return [str(h.Label) for h in self._raw_file.GetStatusLogHeaderInformation()]

    def get_status_log_for_retention_time(self, retention_time: float) -> StatusLogEntry:
        """Return the status log entry closest to *retention_time* (minutes)."""
        self._check_open()
        log = self._raw_file.GetStatusLogForRetentionTime(retention_time)
        fields: dict = {}
        try:
            fields = {str(k): str(v) for k, v in zip(log.Labels, log.Values)}
        except Exception:
            pass
        return StatusLogEntry(retention_time=retention_time, fields=fields)

    def get_status_log_for_scan(self, scan_number: int) -> StatusLogEntry:
        """Return the status log entry for *scan_number*."""
        return self.get_status_log_for_retention_time(self.get_retention_time(scan_number))

    # ------------------------------------------------------------------
    # Scan dependents & mass precision
    # ------------------------------------------------------------------

    def get_scan_dependents(self, scan_number: int, depth: int = 1) -> ScanDependent:
        """Return MS^n dependent scan relationships for *scan_number*."""
        self._check_open()
        self._check_scan(scan_number)
        deps = self._raw_file.GetScanDependents(scan_number, depth)
        dependent_scans: List[int] = []
        try:
            dependent_scans = [int(dep.ScanNumber) for dep in deps.ScanDependents]
        except Exception:
            pass
        return ScanDependent(scan_number=scan_number, dependent_scan_numbers=dependent_scans)

    def get_mass_precision(self, scan_number: int) -> List[MassPrecision]:
        """
        Return per-peak mass accuracy estimates for *scan_number*.

        Uses ``ThermoFisher.CommonCore.MassPrecisionEstimator``.  Returns an
        empty list if the estimator is unavailable or returns no results.

        Parameters
        ----------
        scan_number:
            1-based scan number.  Must be a high-resolution (FT) scan.
        """
        self._check_open()
        self._check_scan(scan_number)
        try:
            from ThermoFisher.CommonCore.MassPrecisionEstimator import PrecisionEstimate  # type: ignore
        except ImportError:
            return []
        try:
            results = PrecisionEstimate.GetMassPrecisionEstimate(
                self._raw_file, scan_number, False, 5.0
            )
            if results is None:
                return []
            out: List[MassPrecision] = []
            for r in results:
                out.append(MassPrecision(
                    mass=float(r.Mass),
                    intensity=float(r.Intensity),
                    resolution=float(r.Resolution),
                    mz_accuracy_ppm=float(r.MZAccuracyInPPM),
                    mz_accuracy_mmu=float(r.MZAccuracyInMMU),
                ))
            return out
        except Exception:
            return []

    def get_run_header_info(self) -> RunHeaderInfo:
        """Return extended run-header metadata from ``IRawData.RunHeaderEx``."""
        self._check_open()
        rh = self._raw_file.RunHeaderEx
        def _f(attr, default=0.0):
            try:
                return float(getattr(rh, attr, default) or default)
            except Exception:
                return float(default)
        def _i(attr, default=0):
            try:
                return int(getattr(rh, attr, default) or default)
            except Exception:
                return int(default)
        def _s(attr):
            try:
                return str(getattr(rh, attr, "") or "")
            except Exception:
                return ""
        return RunHeaderInfo(
            first_scan=_i("FirstSpectrum"),
            last_scan=_i("LastSpectrum"),
            start_time=_f("StartTime"),
            end_time=_f("EndTime"),
            low_mass=_f("LowMass"),
            high_mass=_f("HighMass"),
            mass_resolution=_f("MassResolution"),
            max_intensity=_f("MaxIntensity"),
            max_integrated_intensity=_f("MaxIntegratedIntensity"),
            spectra_count=_i("SpectraCount"),
            status_log_count=_i("StatusLogCount"),
            error_log_count=_i("ErrorLogCount"),
            trailer_extra_count=_i("TrailerExtraCount"),
            tune_data_count=_i("TuneDataCount"),
            expected_run_time=_f("ExpectedRunTime"),
            comment1=_s("Comment1"),
            comment2=_s("Comment2"),
            in_acquisition=bool(getattr(rh, "InAcquisition", False)),
            tolerance_unit=_s("ToleranceUnit"),
            filter_mass_precision=_i("FilterMassPrecision"),
            writer_protocol=_i("WriterProtocol"),
        )

    def get_file_error(self) -> FileError:
        """
        Return diagnostic error state from ``IRawDataPlus.FileError``.

        Useful for diagnosing why a file cannot be opened or is corrupted.
        ``has_error`` will be ``False`` for healthy files.
        """
        self._check_open()
        fe = getattr(self._raw_file, "FileError", None)
        if fe is None:
            return FileError(has_error=False, error_code=0, error_message="")
        try:
            has_error = bool(getattr(fe, "HasError", False))
            error_code = int(getattr(fe, "ErrorCode", 0) or 0)
            error_message = str(getattr(fe, "ErrorMessage", "") or "")
        except Exception:
            has_error = False
            error_code = 0
            error_message = ""
        return FileError(has_error=has_error, error_code=error_code, error_message=error_message)

    # ------------------------------------------------------------------
    # Scan filter helpers
    # ------------------------------------------------------------------

    def get_filtered_scan_numbers(
        self,
        filter_string: str,
        start_scan: Optional[int] = None,
        end_scan: Optional[int] = None,
    ) -> List[int]:
        """
        Return all scan numbers whose filter matches *filter_string*.

        Parameters
        ----------
        filter_string:
            Exact scan-filter string (as returned by :meth:`get_filters`).
        start_scan, end_scan:
            Optional 1-based scan range to restrict the search.
        """
        self._check_open()
        first, last = self.get_scan_range()
        s0 = start_scan if start_scan is not None else first
        s1 = end_scan if end_scan is not None else last
        try:
            nums = self._raw_file.GetFilteredScanEnumerator(filter_string)
            return [int(n) for n in nums if s0 <= int(n) <= s1]
        except Exception:
            return [
                n for n in range(s0, s1 + 1)
                if self._raw_file.GetFilterForScanNumber(n).ToString() == filter_string
            ]

    def iterate_filtered_scans(
        self,
        filter_string: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> Iterator[int]:
        """
        Lazily yield scan numbers whose filter matches *filter_string*.

        More memory-efficient than :meth:`get_filtered_scan_numbers` for
        very large files because scans are yielded one at a time.

        Parameters
        ----------
        filter_string:
            Exact scan-filter string.
        start_time, end_time:
            Optional retention-time window in minutes.
        """
        self._check_open()
        try:
            if start_time is not None and end_time is not None:
                nums = self._raw_file.GetFilteredScanEnumeratorOverTime(
                    filter_string, start_time, end_time
                )
            else:
                nums = self._raw_file.GetFilteredScanEnumerator(filter_string)
            for n in nums:
                yield int(n)
        except Exception:
            first, last = self.get_scan_range()
            if start_time is not None:
                first = int(self._raw_file.ScanNumberFromRetentionTime(start_time))
            if end_time is not None:
                last = int(self._raw_file.ScanNumberFromRetentionTime(end_time))
            for n in range(first, last + 1):
                if self._raw_file.GetFilterForScanNumber(n).ToString() == filter_string:
                    yield n

    # ------------------------------------------------------------------
    # Iteration helpers
    # ------------------------------------------------------------------

    def iter_scan_info(self, ms_order: Optional[int] = None) -> Iterator[ScanInfo]:
        """Yield ScanInfo for every scan. Pass *ms_order* to filter by MS level."""
        first, last = self.get_scan_range()
        for scan in range(first, last + 1):
            info = self.get_scan_info(scan)
            if ms_order is None or info.ms_order == ms_order:
                yield info

    def iter_centroid_data(self, ms_order: Optional[int] = None) -> Iterator[CentroidData]:
        """Yield CentroidData for every centroid scan. Pass *ms_order* to filter."""
        first, last = self.get_scan_range()
        for scan in range(first, last + 1):
            ev = self._raw_file.GetScanEventForScanNumber(scan)
            if ms_order is not None and int(ev.MSOrder) != ms_order:
                continue
            yield self.get_centroid_stream(scan)

    def analyze_all_scans(self) -> Dict[str, int]:
        """
        Walk every scan, verify m/z ordering, and return summary counts.

        Returns ``{"total", "centroid", "profile", "out_of_order"}``.
        """
        self._check_open()
        first, last = self.get_scan_range()
        total = centroid = profile = out_of_order = 0

        for scan in range(first, last + 1):
            total += 1
            stats = self._raw_file.GetScanStatsForScanNumber(scan)
            filt = self._raw_file.GetFilterForScanNumber(scan).ToString()
            is_ft = "FTMS" in filt.upper()

            if is_ft:
                centroid += 1
                cs = self._raw_file.GetCentroidStream(scan, False)
                masses = [float(m) for m in cs.Masses] if cs.Masses else []
            else:
                profile += 1
                seg = self._raw_file.GetSegmentedScanFromScanNumber(scan, stats)
                masses = [float(p) for p in seg.Positions] if seg and seg.Positions else []

            if any(masses[i] < masses[i - 1] for i in range(1, len(masses))):
                out_of_order += 1

        return {"total": total, "centroid": centroid, "profile": profile, "out_of_order": out_of_order}

    # ------------------------------------------------------------------
    # Spectral subtraction (pure-Python math, no new .NET calls)
    # ------------------------------------------------------------------

    def subtract_spectra(
        self,
        scan_a: int,
        scan_b: int,
        mass_range: Optional[Tuple[float, float]] = None,
        mass_tolerance_ppm: float = 5.0,
        normalize: bool = False,
    ) -> SubtractedSpectrum:
        """
        Subtract the spectrum of *scan_b* from *scan_a* (A − B).

        Both scans must share the same scan filter string. Use the ``peaks``
        property on the result to iterate surviving (positive) peaks.
        """
        self._check_open()
        self._check_scan(scan_a)
        self._check_scan(scan_b)

        filter_a = self._raw_file.GetFilterForScanNumber(scan_a).ToString()
        filter_b = self._raw_file.GetFilterForScanNumber(scan_b).ToString()
        if filter_a != filter_b:
            raise ValueError(
                f"Cannot subtract scans with different filters.\n"
                f"  scan {scan_a}: {filter_a!r}\n"
                f"  scan {scan_b}: {filter_b!r}"
            )

        use_centroid = "FTMS" in filter_a.upper()
        if use_centroid:
            masses, intensities = self._subtract_centroid(
                scan_a, scan_b, mass_range, mass_tolerance_ppm, normalize
            )
        else:
            masses, intensities = self._subtract_profile(scan_a, scan_b, mass_range, normalize)

        return SubtractedSpectrum(
            scan_a=scan_a,
            scan_b=scan_b,
            scan_filter=filter_a,
            mass_range=mass_range,
            is_centroid=use_centroid,
            masses=masses,
            intensities=intensities,
            intensities_clipped=[max(0.0, v) for v in intensities],
        )

    def _subtract_centroid(
        self,
        scan_a: int,
        scan_b: int,
        mass_range: Optional[Tuple[float, float]],
        tol_ppm: float,
        normalize: bool,
    ) -> Tuple[List[float], List[float]]:
        cs_a = self._raw_file.GetCentroidStream(scan_a, False)
        cs_b = self._raw_file.GetCentroidStream(scan_b, False)

        masses_a = [float(m) for m in cs_a.Masses] if cs_a.Masses else []
        inten_a  = [float(i) for i in cs_a.Intensities] if cs_a.Intensities else []
        masses_b = [float(m) for m in cs_b.Masses] if cs_b.Masses else []
        inten_b  = [float(i) for i in cs_b.Intensities] if cs_b.Intensities else []

        masses_a, inten_a = _apply_mass_range(masses_a, inten_a, mass_range)
        masses_b, inten_b = _apply_mass_range(masses_b, inten_b, mass_range)

        if normalize:
            inten_a = _normalize_to_tic(inten_a)
            inten_b = _normalize_to_tic(inten_b)

        matched_b = [False] * len(masses_b)
        out_masses: List[float] = []
        out_intensities: List[float] = []

        for m_a, i_a in zip(masses_a, inten_a):
            best_idx = _find_closest(m_a, masses_b, tol_ppm)
            if best_idx is not None:
                matched_b[best_idx] = True
                out_masses.append(m_a)
                out_intensities.append(i_a - inten_b[best_idx])
            else:
                out_masses.append(m_a)
                out_intensities.append(i_a)

        for idx, (m_b, i_b) in enumerate(zip(masses_b, inten_b)):
            if not matched_b[idx]:
                out_masses.append(m_b)
                out_intensities.append(-i_b)

        pairs = sorted(zip(out_masses, out_intensities), key=lambda x: x[0])
        if pairs:
            out_masses, out_intensities = zip(*pairs)
            return list(out_masses), list(out_intensities)
        return [], []

    def _subtract_profile(
        self,
        scan_a: int,
        scan_b: int,
        mass_range: Optional[Tuple[float, float]],
        normalize: bool,
    ) -> Tuple[List[float], List[float]]:
        stats_a = self._raw_file.GetScanStatsForScanNumber(scan_a)
        stats_b = self._raw_file.GetScanStatsForScanNumber(scan_b)
        seg_a = self._raw_file.GetSegmentedScanFromScanNumber(scan_a, stats_a)
        seg_b = self._raw_file.GetSegmentedScanFromScanNumber(scan_b, stats_b)

        masses_a = [float(p) for p in seg_a.Positions]  if seg_a and seg_a.Positions  else []
        inten_a  = [float(i) for i in seg_a.Intensities] if seg_a and seg_a.Intensities else []
        masses_b = [float(p) for p in seg_b.Positions]  if seg_b and seg_b.Positions  else []
        inten_b  = [float(i) for i in seg_b.Intensities] if seg_b and seg_b.Intensities else []

        masses_a, inten_a = _apply_mass_range(masses_a, inten_a, mass_range)
        masses_b, inten_b = _apply_mass_range(masses_b, inten_b, mass_range)

        if normalize:
            inten_a = _normalize_to_tic(inten_a)
            inten_b = _normalize_to_tic(inten_b)

        inten_b_interp = _linear_interp(masses_a, masses_b, inten_b)
        return masses_a, [a - b for a, b in zip(inten_a, inten_b_interp)]

    def subtract_background(
        self,
        scan_number: int,
        background_scan_numbers: Union[int, List[int]],
        mass_range: Optional[Tuple[float, float]] = None,
    ) -> BackgroundSubtractedSpectrum:
        """
        Remove background from *scan_number* using Thermo Fisher scan subtraction.

        Parameters
        ----------
        scan_number : int
            1-based foreground scan number.
        background_scan_numbers : int or list of int
            Background scan(s). A list is averaged by the .NET layer first.
        mass_range : tuple, optional
            ``(low_mz, high_mz)`` window applied to the result after subtraction.
        """
        self._check_open()
        self._check_scan(scan_number)

        if isinstance(background_scan_numbers, int):
            background_scan_numbers = [background_scan_numbers]
        for bg in background_scan_numbers:
            self._check_scan(bg)

        scan_filter = self._raw_file.GetFilterForScanNumber(scan_number).ToString()

        try:
            fg_scan = self._Scan.FromDetector(self._raw_file, self._Int32(scan_number))
            bg_scan = self._make_background_scan(background_scan_numbers)
            opts = self._MassOptions()
            averager = self._ScanAveragerPlus.FromFile(self._raw_file)
            result = _reflect_call(averager, "SubtractScans", fg_scan, bg_scan, opts)
            masses = [float(m) for m in result.PreferredMasses] if result and result.PreferredMasses else []
            intensities = [float(i) for i in result.PreferredIntensities] if result and result.PreferredIntensities else []
        except Exception:
            masses, intensities = self._subtract_background_python(scan_number, background_scan_numbers)

        if mass_range is not None:
            masses, intensities = _apply_mass_range(masses, intensities, mass_range)

        return BackgroundSubtractedSpectrum(
            scan_number=scan_number,
            background_scans=list(background_scan_numbers),
            scan_filter=scan_filter,
            masses=masses,
            intensities=intensities,
        )

    def _make_background_scan(self, background_scan_numbers: List[int]):
        """Return a native Scan for one background scan or an average of many."""
        if len(background_scan_numbers) == 1:
            return self._Scan.FromDetector(self._raw_file, self._Int32(background_scan_numbers[0]))

        dn_list = self._DotNetList[self._Int32]()
        for scan_number in background_scan_numbers:
            dn_list.Add(self._Int32(scan_number))

        opts = self._MassOptions()
        averager = self._ScanAveragerPlus.FromFile(self._raw_file)
        return _reflect_call(averager, "AverageScans", dn_list, opts, False)

    def _subtract_background_python(
        self,
        scan_number: int,
        background_scan_numbers: List[int],
    ) -> Tuple[List[float], List[float]]:
        """Fallback background subtraction using centroid peak matching."""
        fg_centroid = self._raw_file.GetCentroidStream(scan_number, False)
        fg_masses = [float(m) for m in fg_centroid.Masses] if fg_centroid and fg_centroid.Masses else []
        fg_intensities = [float(i) for i in fg_centroid.Intensities] if fg_centroid and fg_centroid.Intensities else []

        bg_masses_list: List[List[float]] = []
        bg_intensities_list: List[List[float]] = []
        for bg in background_scan_numbers:
            stream = self._raw_file.GetCentroidStream(bg, False)
            bg_masses_list.append([float(m) for m in stream.Masses] if stream and stream.Masses else [])
            bg_intensities_list.append([float(i) for i in stream.Intensities] if stream and stream.Intensities else [])

        avg_bg_masses, avg_bg_intensities = _average_centroid_peaks(bg_masses_list, bg_intensities_list)
        return _py_subtract_peaks(fg_masses, fg_intensities, avg_bg_masses, avg_bg_intensities)
