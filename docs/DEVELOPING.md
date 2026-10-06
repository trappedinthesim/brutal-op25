# Developing or forking Brutal OP25

You can use GitHub's **Fork** button and clone your fork. The normal build and
tests do not require a RadioReference application key. Manual P25 setup also
works without one. On Windows, run these commands inside Ubuntu WSL; on native
Linux, run them in a terminal with Docker Engine available.

| Path | Purpose |
|---|---|
| `src/` | Receiver, terminal setup, RadioReference import, and dashboard |
| `install/` | Host prerequisites, USB bridge, shortcuts, and image setup |
| `bootstrap/` | Git-free installer and updater |
| `build/` | Dockerfiles, pinned upstream dependencies, and image version |
| `tests/` | Automated tests |
| `docs/` | Operations, hardware boundaries, privacy, and maintainer notes |

Build a base image from your checkout, using a local tag of your choice:

```bash
docker build -f build/Dockerfile -t brutal-op25:local .
```

After changing app files, you can refresh an already-built image without
recompiling upstream OP25:

```bash
docker build -f build/Dockerfile.refresh --build-arg INSTALLED_IMAGE=brutal-op25:local -t brutal-op25:local .
```

Run the tests against the built image:

```bash
bash tests/run-container-tests.sh
```

The test runner mounts only named source and test inputs, not private local
files. The dashboard patches target the upstream UI shipped in the image, so
container tests matter even when Python unit tests pass on the host.

## RadioReference and forks

An approved key is needed for live RadioReference imports, not for routine
development. If you have authorization for your own key, supply it locally
through `BRUTAL_RR_APP_KEY` or the git-ignored
`.setup-cache/radioreference_app_key`; never commit it. A fork does not inherit
this project's GitHub Actions secret. Its tagged image-publishing workflow
requires the fork owner to configure an authorized key for their own release;
normal builds and tests do not run that workflow. Review [privacy and key
distribution](INSTALLATION-PRIVACY.txt) before shipping any image.

## Maintainer image releases

An `image-v<version>` tag triggers `.github/workflows/image.yml`. The workflow
checks the tag against `build/image-release.txt`, builds with the repository's
Actions secret through a temporary BuildKit secret mount, runs tests and image
checks, and publishes to GitHub Container Registry. The approved application
key is not committed to source; the distributed client includes it, so the
client image must not be treated as a secure place to keep a private key.

## Upstream OP25

The build is pinned to boatbod/op25 commit `71abcd0` (2026-08-23). When moving
to another upstream revision, update `OP25_COMMIT` in `build/Dockerfile` and
`UPSTREAM_COMMIT` in `src/brutal_ui.py`, rebuild, and run the tests. The runtime
patches intentionally refuse to start when their expected upstream code has
changed, rather than running half-patched. Rebuild the private SDRplay addon
after a base-image update, subject to its license. Experimental upstream
branches are not assumed compatible without a receiver test.

Keep [upstream credit and license notices](../THIRD-PARTY-NOTICES.md) with any
distributed fork. See [SDR support](SDR-SUPPORT.txt) for hardware-validation
limits and the [release checklist](RELEASE-CHECKLIST.md) for remaining tests.
