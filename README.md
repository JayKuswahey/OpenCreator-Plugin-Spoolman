# OpenCreator Spoolman plugin

TL;DR -- A Spoolman spool config per tool on the Creator 5 and Creator 5 Pro.

A filament start G-code like `SET_ACTIVE_SPOOL ID=174` ties a spool to a *slicer profile*. With four tools,
one single profile (say Qidi PETG) can be loaded as yellow on T0 and blue on T1, and both would book their filament on
spool 174, meaning that one spool depleted while the other does not. 

This plugin ties the spool to the *tool* instead, using AFC, which OpenCreator already uses. This plugin will make sure that:

- Each tool (AFC lane `extruder0` to `extruder3` for T0 to T3) keeps its own Spoolman spool ID, across restarts.
- When a tool is picked up, at print start or at a tool change, that tool's spool becomes the active spool in
  Spoolman, so usage is booked on the spool that is actually printing. AFC doesn't do this itself on the
  Creator 5, so the plugin hooks into `C5_TOOL_SELECT`, the command every tool pickup goes through.
- There are macros to assign, clear, activate and list spools per tool, and to turn the plugin's messages on and off.

## Install

On the printer over SSH, or on the SBC if the printer is tunneled to one:

```sh
oc-plugin install https://github.com/JayKuswahey/OpenCreator-Plugin-Spoolman.git
```

Installing:

- adds the macros below to Klipper
- creates `oc-spoolman.conf` in Klipper's config folder, next to `moonraker.conf`
- adds this line to `moonraker.conf`:

  ```
  [include oc-spoolman.conf]
  ```

Klipper and Moonraker then restart, unless the printer is printing.

If `moonraker.conf` already has an active `[spoolman]` section, the install leaves `moonraker.conf` as it is and
uses that section. In that case, skip step 1.

## Setup

### 1. Put in your Spoolman server's address

1. In Fluidd or Mainsail, open the configuration files and edit `oc-spoolman.conf`. Over SSH, the file is
   `/usr/data/opencreator/klipper/config/oc-spoolman.conf` on the printer, or
   `~/printer_data/config/oc-spoolman.conf` on an SBC.
2. Set `server:` to the address you open Spoolman with in your browser, including the port (Spoolman's default
   is 7912).
3. Remove the `#` in front of the three lines. The file then ends like this:

   ```ini
   [spoolman]
   server: http://192.168.1.100:7912
   sync_rate: 30
   ```

4. Save, restart Moonraker, then run `FIRMWARE_RESTART` in the console. AFC only checks for Spoolman when Klipper
   starts.
5. Run `SPOOLMAN_STATUS`. Its first line should show your server's address.

Plugin updates don't change `oc-spoolman.conf`, so your address stays.

### 2. Give each tool its spool

Find the spool's ID in Spoolman (the `#` number on the spool), then in the console:

```gcode
SPOOLMAN_SET_TOOL TOOL=0 SPOOL=174    ; Qidi PETG yellow on T0
SPOOLMAN_SET_TOOL TOOL=1 SPOOL=175    ; Qidi PETG blue on T1
SPOOLMAN_STATUS
```

AFC looks each spool up in Spoolman and fills in the tool's material, color and weight. If a spool was on
another tool, it moves to the new one. If you swap a spool on a tool, run `SPOOLMAN_SET_TOOL` again, setting up the new ID.

### 3. Change the filament start G-code in your slicer

Take `SET_ACTIVE_SPOOL ID=174` out of the filament profile. Then use one of the two options below.

**A. One profile for several spools** (the same Qidi PETG profile for the yellow and the blue spool). Assign
the spools on the printer as in step 2, and put this in the filament start G-code:

```gcode
;set spoolman
SPOOLMAN_ACTIVATE_TOOL
```

This makes the printing tool's spool the active spool. The plugin already does that whenever a tool is picked
up, so this line is optional and only makes sure of it. If the tool has no spool assigned, you get a warning in
the console and no spool is active, so the filament isn't booked on the wrong spool.

**B. One profile per spool** (a separate profile for the yellow and the blue spool):

```gcode
;set spoolman
SPOOLMAN_SET_TOOL SPOOL=174
```

This assigns spool 174 to whichever tool prints with this profile and makes it the active spool. If the tool
already has that spool, it doesn't contact Spoolman. When the spool changes, AFC looks it up in Spoolman, which
pauses the G-code for as long as Spoolman takes to answer. That is usually a fraction of a second.

In both options `TOOL` is optional. It defaults to the tool that is printing, which is what the filament start
G-code needs. Pass `TOOL=` only to set up a tool that isn't active, as in step 2.

### 4. Messages

The macros report what they did in the console, for example `Spoolman: Tool 1 has spool 175 (active)`. With
filament start G-code that runs at every tool change, that adds up. Use these commands to toggle those echoes:

```gcode
SPOOLMAN_ECHO_OFF   ; hide routine messages
SPOOLMAN_ECHO_ON    ; show them again (the default)
```

The setting is saved, so it lasts across restarts. Problems are always shown, whatever the setting. When the
printer is idle they are errors. During a print they are warnings, so they don't stop the print.

You can use the same switch in your own G-code:

```gcode
SPOOLMAN_ECHO MSG="Qidi PETG yellow loaded"
```

### 5. Group the macros in Fluidd (optional)

Fluidd lists new macros under **Uncategorized**. To give the plugin's macros their own group on the dashboard:

1. Open Fluidd's **Settings** (the cog icon) and scroll to **Macros**.
2. Click **Add Category**, name it `Spoolman`, and save.
3. Click **Uncategorized** to see the macros in it. For each of these macros, click its name, set **Category**
   to `Spoolman`, and click **Save**:
   - `SPOOLMAN_SET_TOOL`
   - `SPOOLMAN_CLEAR_TOOL`
   - `SPOOLMAN_ACTIVATE_TOOL`
   - `SPOOLMAN_STATUS`
   - `SPOOLMAN_ECHO_ON`
   - `SPOOLMAN_ECHO_OFF`
   - `SPOOLMAN_ECHO`
4. Hide `SPOOLMAN_ECHO`. It only does something with a `MSG`, so it's for G-code, not for a dashboard button.
   Open **Spoolman** in the category list and turn off the switch next to `SPOOLMAN_ECHO`. You can also turn
   off **Visible** in its settings. The macro still works from G-code and the console.
5. Optionally, drag the macros into the order you want, and give them a color or an **Alias** (a shorter button
   name) in the same settings.

Macros whose names start with `_`, like `_SPOOLMAN_PROBLEM`, are the plugin's helpers. Fluidd doesn't show
them.

`C5_TOOL_SELECT` also shows up under **Uncategorized** once the plugin is installed. It's OpenCreator's tool
pickup command, which the plugin wraps to switch spools. Leave it where it is, or hide it the same way as
`SPOOLMAN_ECHO`. It works the same either way.

Fluidd saves these settings in Moonraker, so they apply in every browser and survive plugin updates. If Fluidd
is open in another browser tab, reload that tab afterwards. Otherwise its next change to a macro setting can
undo yours.

## Macros

| Macro | What it does |
| --- | --- |
| `SPOOLMAN_SET_TOOL SPOOL=<id> [TOOL=<0-3>] [ACTIVATE=0/1]` | Assigns a spool to a tool. Activates it when the tool is the one in use; `ACTIVATE` overrides that. `SPOOL=0` clears the tool. `ID=` works as well as `SPOOL=`. |
| `SPOOLMAN_CLEAR_TOOL [TOOL=<0-3>]` / `ALL=1` | Takes the spool off a tool, or off all tools. |
| `SPOOLMAN_ACTIVATE_TOOL [TOOL=<0-3>]` | Makes a tool's assigned spool the active spool, or clears the active spool if the tool has none. |
| `SPOOLMAN_STATUS` | Shows the Spoolman server, each tool's spool, material and color, the active tool, and whether messages are on. |
| `SPOOLMAN_ECHO MSG="..."` | Shows `MSG` while messages are on. |
| `SPOOLMAN_ECHO_ON` / `SPOOLMAN_ECHO_OFF` | Turns the messages on or off. The setting is saved as `oc_spoolman_echo` in Klipper's saved variables. |
| `C5_TOOL_SELECT T=<0-3>` | OpenCreator's tool pickup, wrapped by the plugin: after the pickup it makes that tool's spool the active spool. The original command is kept as `_OC_SPOOLMAN_TOOL_SELECT`. |

AFC's own `SET_SPOOL_ID LANE=extruder1 SPOOL_ID=175` changes the same assignments, as does any AFC panel that
sets a lane's spool.

## Updating and removing

Updates show up in Fluidd/Mainsail's update manager as **oc-plugin-oc_spoolman_integration**, or run
`oc-plugin update oc_spoolman_integration`. An update adds the `moonraker.conf` include again if it went missing.

`oc-plugin remove oc_spoolman_integration` removes the macros and the `[include oc-spoolman.conf]` line. It keeps
`oc-spoolman.conf` with your address in it. Restart Moonraker afterwards to disconnect from Spoolman. The spool IDs
stay with AFC.

## Layout

```
opencreator-plugin.json     the manifest
config/oc-spoolman.cfg      the Klipper macros, included while the plugin is enabled
moonraker/oc-spoolman.conf  template for the config folder's oc-spoolman.conf
scripts/install.sh          install and update: oc-spoolman.conf and the moonraker.conf include
scripts/uninstall.sh        takes the include out again
tests/                      python3 -m unittest discover -s tests (the macro tests need jinja2)
```

The Spoolman settings don't go through the manifest's `moonraker_config`. `oc-plugin` rewrites that file at
every sync, so an address typed into it would be lost.

The plugin works wherever Klipper and Moonraker run: on the printer itself, or on an SBC. For a printer
tunneled to an SBC, install it on the SBC, not on the printer. On the printer, the install script stops
with a message, since Klipper and Moonraker aren't there.

## Developing

To try changes before they are released, clone the repo on the printer and install the plugin straight from
that folder.

A folder install is a copy, so `oc-plugin` doesn't see later changes to the folder. After each change, remove
the plugin and install it again from the folder. A folder install also isn't offered in Fluidd/Mainsail's
update manager, because that needs a git URL.

The working copies go in their own folder, `/usr/data/localPluginTrials`, away from the installed plugins. The
commands below are for the printer itself. On an SBC, use `~/localPluginTrials` instead, and the SBC's user
and address.

### Clone and install

Clone the repo on the printer once, over SSH:

```sh
ssh root@<printer>
mkdir -p /usr/data/localPluginTrials
cd /usr/data/localPluginTrials
git clone https://github.com/JayKuswahey/OpenCreator-Plugin-Spoolman.git
```

Then, for every change you push to GitHub:

```sh
cd /usr/data/localPluginTrials/OpenCreator-Plugin-Spoolman
git fetch -p ## Fetch repo data, prune/purge branches which are deleted on origin
git checkout <branch> ## Switch to a branch if need be
git pull
oc-plugin remove oc_spoolman_integration
oc-plugin install /usr/data/localPluginTrials/OpenCreator-Plugin-Spoolman
```

### Notes

- The first time, skip `oc-plugin remove`: there's nothing to remove yet.
- Removing runs `scripts/uninstall.sh` and installing runs `scripts/install.sh`, so each round also tests
  both scripts. Your `oc-spoolman.conf` with the Spoolman address is kept in between.
- Install restarts Klipper and Moonraker, unless the printer is printing. Add `--no-restart` to skip that, and
  run `FIRMWARE_RESTART` yourself when you're ready to load the new macros.
- To go back to the released plugin: `oc-plugin remove oc_spoolman_integration`, then install it from the git URL as under
  **Install**.
- A pushed branch can also be installed from GitHub instead of a folder:
  `oc-plugin install https://github.com/JayKuswahey/OpenCreator-Plugin-Spoolman.git --ref <branch>`. That
  install is a git checkout, so `oc-plugin update oc_spoolman_integration` pulls new commits on that branch.

### Tests

Run the tests on your computer before copying:

```sh
python3 -m unittest discover -s tests
```

The macro tests need `jinja2` (`pip install jinja2`) and are skipped without it.

The full plugin system documentation is on the OpenCreator docs site, under **Plugins**, and in the
[example plugin](https://github.com/FlashForge-C5-Modding-Group/OpenCreator-Plugin-Example).

## License

GNU General Public License v3.0. See [LICENSE.md](LICENSE.md).
