# macOS Release

This document describes the current internal macOS packaging and release flow for LinkGlancer.

## Scope

This flow covers:

- Apple Silicon only
- building a local `.app` with PyInstaller
- signing the `.app`
- notarizing the `.app` and release `.dmg`
- producing a `.dmg` for internal distribution

This flow does not cover:

- Intel Mac support
- automatic updates
- database schema migrations
- public distribution under a long-term personal signing identity

## Outputs

Development build output:

- `dist/LinkGlancer.app`

Release build outputs:

- `dist/LinkGlancer.app`
- `dist/release/LinkGlancer-<version>-macos-arm64.dmg`

Temporary build assets:

- `packaging/icon.icns`
- `build/macos/icon.iconset`

## Prerequisites

Required local environment:

- macOS 15 on Apple Silicon
- Xcode Command Line Tools
- repository-local `.venv`
- Python `3.12`
- Apple Developer signing identity installed in Keychain
- notarization credentials stored with `notarytool`

Required project files:

- `packaging/icon.svg`
- `packaging/link_glancer_macos.spec`
- `packaging/link_glancer_macos.entitlements`
- `scripts/generate_macos_icon.py`
- `scripts/build_macos.sh`
- `scripts/build_macos_release.sh`

## One-Time Setup

Install Xcode Command Line Tools if needed:

```bash
xcode-select --install
```

Create the virtual environment and install dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[build]"
python -m playwright install
```

Store notarization credentials in the macOS keychain:

```bash
xcrun notarytool store-credentials "link-glancer-notary" \
  --apple-id "YOUR_APPLE_ID" \
  --team-id "YOUR_TEAM_ID" \
  --password "YOUR_APP_SPECIFIC_PASSWORD"
```

Export your signing identity before release builds:

```bash
export CODESIGN_IDENTITY="Developer ID Application: Your Name Or Company (TEAMID)"
export NOTARY_PROFILE="link-glancer-notary"
```

## Development Build

Run:

```bash
bash scripts/build_macos.sh
```

What this script does:

- verifies the host is Apple Silicon macOS
- installs build dependencies into `.venv`
- installs Playwright for the local environment
- runs `ruff check`
- compiles `src`
- generates `build/macos/icon.iconset`
- builds `packaging/icon.icns`
- removes old `build/` and `dist/`
- builds `dist/LinkGlancer.app` with PyInstaller

Use this path for local smoke testing before signing.

## Release Build

Run:

```bash
source .venv/bin/activate
export CODESIGN_IDENTITY="Developer ID Application: Your Name Or Company (TEAMID)"
export NOTARY_PROFILE="link-glancer-notary"
bash scripts/build_macos_release.sh
```

What this script does:

- runs the development build first
- signs `dist/LinkGlancer.app`
- verifies the signature
- notarizes the `.app`
- staples the notarization ticket to the `.app`
- creates `dist/release/LinkGlancer-<version>-macos-arm64.dmg`
- signs the `.dmg`
- notarizes the `.dmg`
- staples the notarization ticket to the `.dmg`

## Internal Distribution

Recommended distribution asset:

- `dist/release/LinkGlancer-<version>-macos-arm64.dmg`

Recommended internal upgrade flow:

1. Download the new `.dmg`.
2. Open the `.dmg`.
3. Drag `LinkGlancer.app` into `Applications`, replacing the existing app.
4. Start the app normally.

Current note:

- user data lives outside the app bundle, so replacing the `.app` should preserve application data as long as the database schema remains compatible

## Verification Checklist

Before handing the build to other users:

1. Launch the app from `/Applications`.
2. Confirm the dock icon is correct.
3. Confirm the app starts without Gatekeeper warnings.
4. Confirm a browser configuration can be created and launched.
5. Confirm the creator collection flow can start and save.
6. Confirm a task can be created from `xlsx`.
7. Confirm a task can be reviewed and exported.
8. Confirm notifications still appear.
9. Confirm replacing an older app build preserves existing data.

Useful validation commands:

```bash
codesign --verify --deep --strict --verbose=2 dist/LinkGlancer.app
spctl --assess --type execute --verbose dist/LinkGlancer.app
spctl --assess --type open --verbose dist/release/LinkGlancer-<version>-macos-arm64.dmg
```

## Identity Exposure

Signed macOS apps expose the signing subject to recipients.

Implications:

- a personal Apple Developer identity may reveal your personal name
- a company Apple Developer identity is usually better for broad distribution
- for internal company distribution, this is usually acceptable if recipients already know the publisher

## Troubleshooting

If `build_macos.sh` fails:

- confirm `.venv` exists
- confirm `python -m playwright install` completed successfully
- confirm `iconutil` is available
- rerun `python -m ruff check .`

If `build_macos_release.sh` fails during signing:

- confirm `CODESIGN_IDENTITY` exactly matches a valid Keychain identity
- run `security find-identity -v -p codesigning`

If notarization fails:

- confirm the `NOTARY_PROFILE` exists
- rerun `xcrun notarytool history --keychain-profile "$NOTARY_PROFILE"`
- inspect the notarization log from `notarytool`

If the app launches locally but another Mac blocks it:

- confirm you distributed the notarized `.dmg`, not a raw unsigned `.app`
- confirm stapling succeeded on both the `.app` and `.dmg`
