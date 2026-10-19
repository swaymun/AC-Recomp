# Contributor and agent guidance

These rules apply to people and to coding agents working in this repository.

## What belongs in Git

- Only original code, tests, dependency notices and documentation.
- Never commit game content or anything derived from it. That includes dumps (NSP/XCI/NCA/NSO), keys,
  firmware, fonts extracted from firmware, lifted C/C++, shader binaries or translations, RomFS files, captures,
  screenshots of game output and logs that contain game data.
- Keep that material under the ignored `.local/` directory. Check `git status` and the staged paths before
  every commit.
- Do not commit personal paths, account names, machine names or credentials. Use environment variables or
  command-line arguments, for example `ACS_ROOT`, `ACS_DUMP_DIR` or `NX_SHARED_FONT_DIR`.

## Code

- Python tooling uses the standard library only.
- Tests use synthetic fixtures and temporary Git repositories. They must never need a game dump, keys, firmware,
  network access or cloud resources. Mock external commands such as `ssh` or `codex`. Tests that compose runtime
  patches need a clean pinned SuperMarioWonderRecomp checkout, passed through the `*_REFERENCE` variable named
  in their failure message.
- Runtime changes are patches in `runtime/patches/` against the pinned SuperMarioWonderRecomp revision.
  Preserve upstream MIT notices in any adapted code, and record new third-party sources, with their license and
  revision, in `THIRD_PARTY_NOTICES.md` and `dependencies.lock`.
- Keep strict failures strict. Unknown services, commands or relocations stop with a clear message rather than
  returning a fake success.

## Before sending a change

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
```

Describe what you verified and what you could not, for example "built and ran to the title screen on macOS" or
"tests only". Do not claim that a change works in game unless you ran it.
