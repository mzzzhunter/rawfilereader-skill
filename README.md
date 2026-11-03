# RawFileReader Skill

AI Agent skill for working with Thermo RAW files.

GitHub skill URL:

https://github.com/mzzzhunter/rawfilereader-skill/tree/master/rawfilereader-skill

## Install With a Prompt

Copy and paste this prompt into Codex or Claude Code:

```text
Install the rawfilereader-skill from https://github.com/mzzzhunter/rawfilereader-skill/tree/master/rawfilereader-skill as a personal skill. In Codex, use the skill installer. In Claude Code, copy the rawfilereader-skill directory, including all bundled assets, into ~/.claude/skills/rawfilereader-skill (on Windows, use %USERPROFILE%\.claude\skills\rawfilereader-skill). If the skill is already installed, ask before replacing it. Verify that SKILL.md and the bundled scripts and assets are present, then tell me whether I need to restart the app.
```

## Install From Codex

In Codex, run:

```text
$skill-installer install https://github.com/mzzzhunter/rawfilereader-skill/tree/master/rawfilereader-skill
```

Restart Codex after installing.

## Install From Claude Code

Claude Code skills can be installed as personal skills under `~/.claude/skills/`.

On Windows PowerShell:

```powershell
git clone --depth 1 https://github.com/mzzzhunter/rawfilereader-skill.git .rawfilereader-skill-install
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
Copy-Item -Recurse .\.rawfilereader-skill-install\rawfilereader-skill "$env:USERPROFILE\.claude\skills\rawfilereader-skill"
Remove-Item -Recurse -Force .\.rawfilereader-skill-install
```

On macOS/Linux:

```bash
git clone --depth 1 https://github.com/mzzzhunter/rawfilereader-skill.git .rawfilereader-skill-install
mkdir -p ~/.claude/skills
cp -R .rawfilereader-skill-install/rawfilereader-skill ~/.claude/skills/rawfilereader-skill
rm -rf .rawfilereader-skill-install
```

Restart Claude Code after installing if the skill does not appear.

## Example Usage

After installing, paste one of these prompts into Codex or Claude Code. Replace the example paths with your own Thermo `.raw` file and output directory. Keep data files outside the skill folder.

### Inspect a RAW file

```text
Use the rawfilereader-skill to inspect /path/to/sample.raw. Report the file metadata, scan range, and first five scan filters. Stage the bundled adapter in my working directory and check the Python and .NET requirements before reading the file.
```

### Export a total ion chromatogram

```text
Use the rawfilereader-skill to extract the total ion chromatogram (TIC) from /path/to/sample.raw. Save the retention times and intensities to /path/to/output/tic.csv with a header row, and report the retention-time units.
```

### Inspect a spectrum

```text
Use the rawfilereader-skill to read the first scan in /path/to/sample.raw. Show its scan metadata and the first ten centroid peaks as m/z and intensity pairs. If centroid data is unavailable, explain what is available.
```

### Draft an LC-MS methods summary

```text
Use the rawfilereader-skill and its examples/method-section-summary example to extract the instrument method metadata from /path/to/sample.raw and draft an LC-MS methods paragraph. Only include settings supported by the extracted metadata, and list any missing details I need to supply.
```

## Citation

Chen, T. (2026). *RawFileReader Skill for AI Agent* [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.23932107
