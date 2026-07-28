# Linxira Completion Agent

The Completion Agent presents explicitly deferred software from an installer
receipt. It binds the installed catalog to that receipt and displays source,
size, license, repository impact, and deferability.

Reviewed official Arch applications and components are installed into the
Calamares target before first boot and are rejected if a receipt incorrectly
hands them to Completion. Operation leaves remain deferred until their dedicated
action implementation exists.
The agent accepts no package names, commands, URLs, or repository definitions.
AUR, Flatpak, Conda, proprietary, and review-channel items remain deferred until
their dedicated providers and review contracts are implemented.

## Development

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src
```
