# Ultimate Mapper for Playlite

An optional plugin using Playlite’s core Lutris support.
Adds **Use Ultimate Mapper for this play action** to Windows/Wine play actions.
There is no global default. Native games and other integrations are unaffected.

The checkbox is saved to the selected Lutris entry only when the game editor is
saved. Cancel leaves it unchanged. A failed library save rolls back configuration
updates. Play actions sharing a Lutris game ID share that entry's configuration.
Existing `UltimateMapper` action fields and Elden Ring's configured entries are
recognized without migration or rewriting files when the editor opens.

Enabling sets these values in the selected entry's `system.env`:

```
PROTON_USE_SDL: '1'
SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT: '0x0001/0x0001'
```

This selects Ultimate Mapper's virtual controller with Proton/GE-Proton. Earlier
values are retained in `playlite_ultimate_mapper.previous_environment` and restored
when disabled. Unrelated settings are preserved. Writes are atomic and preserve
permissions. Saved settings also apply when that entry is launched from Lutris.

Before launching an enabled action, the plugin checks for the virtual controller.
If missing, it offers to start Ultimate Mapper and waits up to 15 seconds, with a
Cancel option. The mapper must have its executable on PATH or an installed
`ultimate-mapper.desktop` launcher. Controller output must become active before
the game launches. Only the selected action is checked.

The plugin uses Playlite's primary action contributions, save transaction, and
selected-action launch hooks. Playlite’s core Lutris support contains no mapper UI or
mapper-specific launch logic. No system-wide environment, game binaries, or
additional packages are changed.

Run tests with Playlite on PYTHONPATH:

```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```
