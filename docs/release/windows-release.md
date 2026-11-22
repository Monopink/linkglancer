# Windows Release

This document describes the current Windows packaging and GitHub Release flow for LinkGlancer.

## Scope

This flow covers:

- building the Windows app folder with PyInstaller
- building the Windows installer with Inno Setup 6
- publishing release assets to GitHub Releases

This flow does not cover:

- code signing
- auto-update distribution
- Microsoft Store packaging

## Prerequisites

Required local environment:

- Windows
- repository-local `.venv`
- Python `3.12`
- Playwright installed for the local virtual environment
- Inno Setup 6

Required project files:

- `packaging/icon.svg`
- `packaging/link_glancer_windows.spec`
- `packaging/link_glancer_windows.iss`
- `scripts/build_windows.ps1`
- `scripts/build_windows_installer.ps1`

## Build Outputs

App folder output:

- `dist/LinkGlancer`

Installer output:

- `dist/installer/LinkGlancer-Setup.exe`

Important:

- `dist/` and `build/` are build outputs and must not be committed into git
- publish build artifacts through GitHub Releases, not through the source repository

## Step 1: Build The Windows App

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

What this script does:

- installs build dependencies into `.venv`
- ensures Playwright runtime is installed
- runs `ruff check`
- compiles `src`
- generates `packaging/icon.ico` from `packaging/icon.svg`
- removes old `build/` and `dist/`
- builds `dist/LinkGlancer` with PyInstaller

Expected result:

- `dist/LinkGlancer/LinkGlancer.exe`

## Step 2: Build The Windows Installer

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_installer.ps1
```

What this script does:

- checks whether `dist/LinkGlancer/LinkGlancer.exe` already exists
- builds the app folder first if it is missing
- locates `ISCC.exe`
- compiles `packaging/link_glancer_windows.iss`
- writes the installer to `dist/installer/LinkGlancer-Setup.exe`

Expected result:

- `dist/installer/LinkGlancer-Setup.exe`

## Step 3: Sanity Check Before Release

Before publishing:

1. Install using `dist/installer/LinkGlancer-Setup.exe`.
2. Launch the installed app.
3. Verify the app icon is correct.
4. Verify startup works on a clean machine or clean user session.
5. Verify at least one end-to-end workflow:
   - create task
   - open browser
   - start review
   - export

Recommended additional checks:

- verify the creator collection flow still launches and saves
- verify browser profile persistence still works
- verify installer creates shortcuts as expected
- verify uninstall removes the app cleanly

## Step 4: Prepare GitHub Release Assets

Recommended release assets:

- `LinkGlancer-Setup.exe`

Optional additional assets:

- `LinkGlancer-portable.zip`

If you want a portable zip:

1. Compress the entire `dist/LinkGlancer` directory.
2. Name it something stable such as `LinkGlancer-portable.zip`.

Do not upload:

- raw `build/`
- raw `dist/LinkGlancer/_internal` contents separately
- local runtime data under `.runtime/`

## Step 5: Publish To GitHub Releases

Recommended release flow:

1. Push the release commit to GitHub.
2. Create a git tag such as `v0.1.0`.
3. Open the repository `Releases` page.
4. Create a new release from that tag.
5. Upload:
   - `dist/installer/LinkGlancer-Setup.exe`
   - optional `LinkGlancer-portable.zip`
6. Add release notes.
7. Mark as `pre-release` if the build is still being validated externally.
8. Publish the release.

## GitHub CLI Example

Example:

```powershell
gh release create v0.1.0 `
  dist/installer/LinkGlancer-Setup.exe `
  --title "v0.1.0" `
  --generate-notes `
  --prerelease
```

If uploading both assets:

```powershell
gh release create v0.1.0 `
  dist/installer/LinkGlancer-Setup.exe `
  dist/installer/LinkGlancer-portable.zip `
  --title "v0.1.0" `
  --generate-notes `
  --prerelease
```

## Versioning Guidance

Recommended tag format:

- `v0.1.0`
- `v0.1.1`
- `v0.2.0`

Suggested meaning:

- patch: small fixes only
- minor: new user-visible features or workflow changes
- major: incompatible workflow or data model changes

## Current Packaging Notes

Current implementation facts:

- runtime app icon uses `packaging/icon.svg`
- Windows installer icon uses `packaging/icon.ico`, generated from `packaging/icon.svg`
- installer is currently built with the default Inno Setup language set available on the build machine
- this repository currently publishes a Windows `onedir` build, then wraps it with an installer

## Troubleshooting

If `build_windows.ps1` fails:

- confirm `.venv` exists
- confirm `python -m playwright install` has completed successfully
- rerun `ruff check` manually

If `build_windows_installer.ps1` fails:

- confirm Inno Setup 6 is installed
- confirm `ISCC.exe` exists
- confirm `dist/LinkGlancer/LinkGlancer.exe` exists

If the installer builds but the app does not start after install:

- test the same build first from `dist/LinkGlancer/LinkGlancer.exe`
- if the folder build fails too, the issue is not the installer layer
- if the folder build works but installed app fails, inspect installer output and installed files
