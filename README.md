# Linxira Completion Agent

The Completion Agent presents software that was selected during an offline
installation but still requires a download. It binds the installed catalog to
the installer receipt, displays source, size, license, repository impact, and
deferability, then delegates reviewed Arch leaves to `linxira-components`.

The agent accepts no package names, commands, URLs, or repository definitions.
AUR, Flatpak, Conda, proprietary, and review-channel items remain deferred until
their dedicated providers and review contracts are implemented.

## Development

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src
```
