# openvegas

`openvegas` is a thin npm wrapper around the OpenVegas CLI binary.

On install, the package downloads the correct prebuilt binary for your platform from GitHub Releases, verifies its SHA256 checksum, and stores it under `~/.openvegas/bin/<version>/`.

## Install

```bash
npm install -g openvegas
```

## Supported Platforms

- `linux-x64`
- `darwin-arm64`
- `win-x64`

Intel macOS is not currently shipped as a native binary. Use Rosetta or install from source if needed.

## Upgrade

```bash
openvegas --upgrade
```

## How It Works

- npm installs this package
- the `postinstall` hook downloads the matching binary from GitHub Releases
- the wrapper verifies the checksum before marking the binary ready
- future CLI invocations execute the cached binary

## Releases

This package is version-matched with the GitHub Release tag. For example, npm package version `0.1.1` expects binary assets under GitHub tag `v0.1.1`.

Project repo:

- https://github.com/jar0ch0/OpenVegasDeployed
