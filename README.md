# RawFileReader Skill

Codex/Claude skill for working with Thermo RawFileReader files.

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


