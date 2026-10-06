# Operations and troubleshooting

The [README](../README.md) has the one-command install and everyday launch/update
instructions. Stop the receiver before updating, backing up, or restoring.

## If a shortcut or command is missing

On Windows, run `C:\Users\<you>\BrutalOP25\Launch-Brutal-OP25.cmd` or rerun the
README's one-command installer. The Windows **OP25** Desktop folder normally has
Launch, Update, and Uninstall shortcuts, and the Start menu has Brutal OP25.

On Linux, run `~/.local/bin/brutal-op25`, or run
`bash "$HOME/brutal-op25/install-brutal-op25.sh"` from the default install path.
If you selected a custom path, use its `install-brutal-op25.sh` instead.

## Back up or restore saved systems

Windows:

```powershell
& (Join-Path $env:USERPROFILE 'BrutalOP25\Launch-Brutal-OP25.cmd') --backup
& (Join-Path $env:USERPROFILE 'BrutalOP25\Launch-Brutal-OP25.cmd') --restore 'C:\path\to\systems.zip'
```

Linux, from the default install path:

```bash
bash "$HOME/brutal-op25/install-brutal-op25.sh" --backup
bash "$HOME/brutal-op25/install-brutal-op25.sh" --restore /full/path/systems.zip
```

Windows backups are written under **Documents / Brutal OP25 Backups**; Linux
backups go under `~/.local/share/brutal-op25/backups`. Restore refuses to
overwrite a different saved system with the same ID. Backups exclude receiver
cache and RadioReference credentials.

## Image update and rollback

The normal Update shortcut on Windows, or `bootstrap/install-brutal-op25.sh
--update` on Linux, updates program files and the matching image. Neither
silently updates a working installation. To refresh only the image from an
existing checkout, use `Launch-Brutal-OP25.cmd --update-image` on Windows or
`bash install-brutal-op25.sh --update-image` on Linux. A successful image update
retains the previous image under a `-previous` tag. Use `--rollback-image` from
the same launcher if you need to revert. A failed pull leaves the current
image in place. After a successful update, older Brutal OP25 image tags and
verified previous program folders are cleaned up automatically, leaving one
rollback copy. Other Docker images, saved-system volumes, and the private
SDRplay addon currently in use are not pruned. The newest locally built SDRplay
addon is retained for rollback; older version-tagged addons are removed.
An old program folder with changed or extra files is left in place for you to
review rather than deleted automatically. Older folders from before the
verified-install manifest was added may also remain.

## Checks and alternative modes

- `--check` checks prerequisites without changing anything.
- `--prepare-only` prepares Docker and the base image without radio setup.
- On native Linux, `bash brutal-op25.sh --no-usb` permits system import and
  management only; it cannot start reception.
- On native Linux, `bash brutal-op25.sh --build` forces a local source build.

On Windows, only the guided launcher can forward the selected USB radio into
Ubuntu WSL. A bare `docker run` skips that bridge. On Linux, the launcher
selects a visible radio and passes only that device into the container. If
you reconnect a radio, its USB node may change; relaunch to select it again.

The dashboard is local to this computer at `http://127.0.0.1:8080/`. Port
9000 carries browser audio and is not a webpage. Do not expose either port
to your LAN or the internet. If browser autoplay is blocked, click **Enable
Audio** in the dashboard.

## Installation boundaries

Windows runs Docker Engine inside Ubuntu WSL, not Docker Desktop. The installer
does not delete or migrate existing Docker Desktop images or profiles. Its own
saved systems live in a separate Docker volume. The Windows uninstaller deletes
that volume, Brutal OP25 image tags, program files, and verified rollback
folders after explicit confirmation. It offers separately confirmed removal
of Ubuntu-24.04, which also removes its Docker Engine and any unrelated Linux
files in that distribution. The Windows WSL platform and USB bridge remain.

On supported Ubuntu and Debian versions, the Linux installer can offer Docker
Engine from Docker's official repository. Other distributions can install a
local Docker Engine separately, then use the launcher. Neither platform needs
a separate OP25 or RTL-SDR host-driver installation. SDRplay uses a separate
vendor download and license review on native Linux. Windows uses SDRplay's
Windows API and a local sample stream instead; see [SDR support](SDR-SUPPORT.txt).
