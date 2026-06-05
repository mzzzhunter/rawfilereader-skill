---
name: rawfilereader-skill
description: Read Thermo Fisher Scientific .raw mass-spectrometry files from Python using the bundled RawFileReaderPyAdapter package and Thermo RawFileReader Net8 DLL assets. Use when Codex needs to inspect, extract metadata from, iterate scans in, or export spectra/chromatograms from Thermo .raw files with pythonnet and RawFileAdapter.
---

# RawFileReader

## Quick Start

Use this skill when working with Thermo `.raw` mass-spectrometry files from Python.

1. Stage the bundled adapter into a working directory:

```powershell
python <skill>/scripts/stage_rawfilereader.py --target <workdir>
```

2. Install the Python dependency in the active environment if needed:

```powershell
python -m pip install pythonnet>=3.0.3
```

3. Use the printed `RAWFILEREADER_LIBS` value, or pass `libs_dir` explicitly:

```python
from rawfilereader import RawFileAdapter

with RawFileAdapter("sample.raw", libs_dir=r"<skill>\assets\libs\Net8\Assemblies") as rf:
    info = rf.get_file_info()
    first_scan, last_scan = rf.get_scan_range()
    centroid = rf.get_centroid_stream(first_scan)
```

## Bundled Resources

- `assets/rawfilereader-python/` contains a vendored snapshot of `mzzzhunter/RawFileReaderPyAdapter`.
- `assets/libs/Net8/Assemblies/` contains the bundled RawFileReader DLL assets expected by the adapter.
- `references/upstream-snapshot.md` records the upstream commit and asset inventory.
- `scripts/stage_rawfilereader.py` copies the vendored package into a target directory and prints the environment values needed to use it.
- `examples/method-section-summary/` contains an example subskill for turning extracted LC-MS method metadata into journal/thesis methods prose.

## Workflow

- Prefer staging the adapter into the user's current project or a temporary workspace rather than editing the skill assets directly.
- Set `RAWFILEREADER_LIBS` to the bundled `assets/libs/Net8/Assemblies` directory unless the user provides a different DLL location.
- Keep `.raw` files outside the skill folder; they are user data, not skill assets.
- Use `RawFileAdapter` as a context manager so the underlying .NET file handle is disposed.
- If imports fail before opening a file, check `pythonnet` and the local .NET runtime first. If opening fails, check the `.raw` path and whether the file is still being acquired.

## Common Tasks

```python
from rawfilereader import RawFileAdapter

with RawFileAdapter("sample.raw") as rf:
    print(rf.get_file_info())
    print(rf.get_scan_range())
    print(rf.get_filters()[:5])
```

```python
with RawFileAdapter("sample.raw") as rf:
    first, _ = rf.get_scan_range()
    scan = rf.get_scan_info(first)
    centroid = rf.get_centroid_stream(first)
    peaks = list(centroid.peaks[:10])
```

```python
with RawFileAdapter("sample.raw") as rf:
    tic = rf.get_chromatogram(trace_type="TIC")
    rows = list(zip(tic.times, tic.intensities))
```

## Example Subskills

Use `examples/method-section-summary/` as a copyable pattern when the user wants extracted instrument methods rewritten into publication-ready methods text. Keep task-specific examples there rather than expanding this core skill with writing guidance.
