---
name: rawfilereader-method-section
description: Convert Thermo RAW instrument method metadata extracted with the RawFileReader skill into concise journal or thesis methods-section prose. Use when Codex has LC-MS method details such as LC gradient, source settings, Orbitrap scan settings, acquisition window, and wants publication-ready scientific text.
---

# RawFileReader Method Section

## Workflow

Use this example subskill after extracting methods from a Thermo `.raw` file with the parent RawFileReader skill.

1. Separate LC conditions from MS conditions.
2. Preserve exact acquisition values from the RAW method.
3. Write one compact paragraph suitable for a journal article or thesis methods section.
4. Use neutral scientific prose; do not infer column chemistry, injection volume, sample prep, or data processing settings unless present in the extracted method.
5. Use "arbitrary units" for gas settings when the source method reports unitless gas values.

## Example Input Facts

- LC system: Vanquish Flex
- MS system: Orbitrap Exploris 240
- Flow rate: 0.250 mL/min
- Column compartment: 40 deg C
- Autosampler: 12 deg C
- Mobile phase A: 0.1% formic acid in water
- Mobile phase B: methanol
- Gradient: 5% B from 0 to 1.5 min, 90% B at 2.0 min, 90% B until 4.0 min, 5% B at 4.5 min, stop at 14.0 min
- UV: 210 and 254 nm
- MS mode: positive H-ESI
- MS acquisition: 0 to 8 min, m/z 60-100, profile mode, 120,000 resolution
- Source settings: spray voltage 3500 V, sheath gas 50, auxiliary gas 10, sweep gas 1, ion transfer tube 325 deg C, vaporizer 330 deg C
- Scan settings: RF lens 70%, AGC target standard, one microscan

## Example Output

LC-MS data were acquired using a Vanquish Flex LC system coupled to an Orbitrap Exploris 240 mass spectrometer. Chromatography was performed at a flow rate of 0.250 mL/min with the column compartment maintained at 40 deg C and the autosampler at 12 deg C. Mobile phase A was 0.1% formic acid in water and mobile phase B was methanol. The gradient was held at 5% B from 0 to 1.5 min, increased to 90% B at 2.0 min, held until 4.0 min, returned to 5% B at 4.5 min, and re-equilibrated until 14.0 min. UV traces were collected at 210 and 254 nm. MS acquisition was performed in positive H-ESI mode from 0 to 8 min over an m/z range of 60-100 using profile data acquisition at 120,000 Orbitrap resolution, with sheath, auxiliary, and sweep gas settings of 50, 10, and 1 arbitrary units, respectively. The spray voltage was 3500 V, ion transfer tube temperature was 325 deg C, vaporizer temperature was 330 deg C, RF lens was 70%, AGC target was standard, and one microscan was acquired per scan.
