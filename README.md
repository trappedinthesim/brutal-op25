# Brutal OP25

Brutal OP25 makes receive-only P25 monitoring easier to set up and use. It builds on
[boatbod/op25](https://github.com/boatbod/op25) with guided SDR and USB setup, a prebuilt
Linux receiver image, RadioReference system and talkgroup imports, saved receiver
profiles, live browser audio, listening controls, and signal analysis. Run it on
Linux or Windows through WSL—no separate OP25 build or Docker Desktop account required.

This is a development preview. Ready to try it? Pick your one-command setup:
[Windows](#windows-one-command) or
[Linux](#linux-one-command). After installation, use the Windows Desktop shortcuts
or the `brutal-op25` command on Linux.

## Screenshots

Live dashboard showing the receiver, call history, and signal plots:

![Brutal OP25 live dashboard with receiver telemetry, call history, and signal plots](docs/screenshots/dashboard-live.png)

Terminal launcher and onboarding:

![Brutal OP25 terminal launcher with block-letter title, radio tower, project link, and setup menu](docs/screenshots/terminal-setup.png)

Narrow or non-UTF-8 terminals use a compact text banner.

## What it adds on top of OP25
- **Guided launch** (Windows and Linux/WSL): picks your radio, connects it to the receiver, and opens the dashboard. Windows forwards RTL-SDR USB to WSL; the RSPdx-R2 streams samples locally from its Windows driver to the Linux receiver.
- **Terminal onboarding**: choose a radio, then save the first P25 system or skip importing and open the dashboard's Systems panel. Nothing listens until a saved system and connected radio are selected.
- **Brutal dashboard theme**: one graphite palette and one accent colour, flat plot tabs, live status strip, tower logo.
- **RadioReference import**: browse P25 systems by country, state, and county right in the dashboard—no copying frequencies from the website. Pick a receiver site and Brutal OP25 imports its control channels, talkgroup names, and available category data. Save multiple systems with your own RadioReference Premium account; credentials are used for the current session, not stored in your profile.
- **Systems panel** (in the dashboard): add systems from RadioReference or manually, switch between saved systems (the receiver restarts for a few seconds), and remove them. Saved systems are shared with the terminal menu.
- **Additional SDR profiles** (terminal menu option 6): copy a saved system, site, talkgroups, and listening preferences to another radio without a fresh install or another RadioReference login. Only one physical radio receives at a time; stop and relaunch to change SDRs.
- **Listening controls** (in the same panel): mark talkgroups **Priority** (they interrupt lower-priority calls) or **Blocked**, filter by RadioReference category, listen only to your Priority talkgroups, name individual radios (click any ID on the dashboard), choose how encrypted talkgroups are handled, and set the hold time. Changes are saved as a new version of the system and the receiver restarts for a few seconds.
- **Volume slider** for browser audio in the status strip. Audio starts automatically when the browser permits it; if autoplay is blocked, the dashboard shows **Enable Audio** for the required click instead of making you move the volume slider.
- **Recovery and performance**: the dashboard shows a recovery page if the receiver stops, and limits background plot and table work.

## Requirements
- x86-64 Windows 10/11 with WSL 2 support, or x86-64 Linux. Windows setup installs Ubuntu 24.04 in WSL and Docker Engine inside Ubuntu; Docker Desktop and a Docker account are not needed.
- Windows uses built-in PowerShell to set up WSL and connect the USB radio. Administrator approval may be needed on the first run.
- An RTL-SDR (including Blog V4) or an SDRplay RSPdx-R2. On native Linux, the RSPdx-R2 uses a locally built private driver addon.
- Optional: a RadioReference Premium account for imports. Users enter their own credentials; no application-key setup is needed.

No Docker account or Docker Desktop sign-in is required.

## Windows: one command

Open **Windows PowerShell** and paste this entire line. It downloads Brutal OP25 and
the prebuilt receiver image; you do not need Git, Docker Desktop, or a Docker account.

```powershell
$installer = Join-Path $env:TEMP 'Install-Brutal-OP25.ps1'; curl.exe -fsSL 'https://raw.githubusercontent.com/trappedinthesim/brutal-op25/main/bootstrap/Install-Brutal-OP25.ps1' -o $installer; if ($LASTEXITCODE -eq 0) { powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer }
```

Follow the on-screen prompts. On a new Windows setup, Windows may ask to install WSL,
approve administrator access, or restart. **If a restart is required, run the same
command again afterward.** A one-time Microsoft WSL Welcome window may open; it
needs no sign-in and can be closed. The installer starts Brutal OP25 when setup finishes.

### Next time on Windows

Open the **OP25** folder on your Desktop. The installer creates three shortcuts there:

- **Launch Brutal OP25** starts the receiver. You can also search the Start menu for **Brutal OP25**.
- **Update Brutal OP25** downloads the latest program files and matching receiver image. Stop the receiver first, then use **Launch Brutal OP25** when the update finishes. Updates never happen silently.
- **Uninstall Brutal OP25** asks you to type `DELETE`, then permanently removes saved systems and settings, Brutal OP25 images, program files, managed shortcuts, and verified program rollbacks. Close the receiver first. It also offers an optional, separately confirmed removal of the entire Ubuntu-24.04 WSL distribution (which may contain other apps or files). The Windows WSL platform and usbipd-win USB bridge are shared and remain installed; remove them separately from Windows Settings only if you no longer use them. Files you added inside the installed program folder are removed; unrelated items in the Desktop **OP25** folder and unverified old program folders are left alone.

The Desktop folder is also created if your Desktop is redirected into OneDrive. If a
shortcut is missing, launch directly from PowerShell:

```powershell
& (Join-Path $env:USERPROFILE 'BrutalOP25\Launch-Brutal-OP25.cmd')
```

## Linux: one command

On native Linux, open a terminal and paste this line. It downloads the program and
prebuilt receiver image without Git. Supported Ubuntu and Debian versions can install
Docker Engine during setup; the installer will ask before making system changes.

```bash
curl -fsSL https://raw.githubusercontent.com/trappedinthesim/brutal-op25/main/bootstrap/install-brutal-op25.sh -o /tmp/install-brutal-op25.sh && bash /tmp/install-brutal-op25.sh
```

### Next time on Linux

Run `brutal-op25` to launch. Setup creates that personal command without changing
your shell profile. If your shell does not find it yet, run
`~/.local/bin/brutal-op25` or log in again. You can also launch directly from the
default installation folder:

```bash
bash "$HOME/brutal-op25/install-brutal-op25.sh"
```

To update, stop the receiver and run:

```bash
bash "$HOME/brutal-op25/bootstrap/install-brutal-op25.sh" --update
```

If you chose a custom installation path, use its `bootstrap/install-brutal-op25.sh`
instead. A failed update restores the previous program folder. Saved systems live in
a separate Docker volume, not in the program folder. Successful updates keep one
verified previous program folder and one receiver-image rollback; older Brutal
OP25 versions are removed without pruning unrelated Docker images or data.
If you add or change files inside an old program folder, cleanup leaves that
folder alone so your files are not lost; keep personal files outside the
installation folder for predictable updates.

## After installation

Use the terminal menu to listen to a saved system, add another SDR, or check your radio.
The dashboard opens at `http://127.0.0.1:8080/` on this computer. Its **Systems** panel
adds, updates, and switches between systems. Only one system and radio can receive at a time.

RadioReference import requires your own eligible account. Your credentials go directly
from your local receiver to RadioReference and are not saved in your profile.
See [installation and privacy](docs/INSTALLATION-PRIVACY.txt).

RSPdx-R2 setup uses SDRplay's separate driver and asks you to review its license if
that driver must be installed. On Windows, the driver runs locally on Windows and
streams samples to the Linux receiver; no SDRplay driver is put in the public image.
On native Linux, the installer builds a private local addon. RTL-SDR users do not
see the SDRplay license. RSPdx-R2 control-channel reception was verified on one
Windows/WSL machine; browser audio and other hosts still need a live check. See
[tested hardware boundaries](docs/SDR-SUPPORT.txt).

For backup, restore, image rollback, and other launcher options, see
[operations and troubleshooting](docs/OPERATIONS.md). To change the code or make a
fork, see [developing and forking](docs/DEVELOPING.md).

## Credits and license
Built on [boatbod/op25](https://github.com/boatbod/op25), itself derived from the original
[osmocom OP25](https://git.osmocom.org/op25); thanks to its authors. This project is not affiliated with or
endorsed by them. Brutal OP25's original code is licensed under
[GPL-3.0-or-later](LICENSE). Upstream components keep their own copyrights and
licenses; see [third-party notices and exact source revisions](THIRD-PARTY-NOTICES.md).
Encrypted voice cannot be decoded. Hardware presets are starting points, not proof of reception.
