# Third-party notices and source

Brutal OP25 builds on other projects. The repository's `LICENSE` covers Brutal
OP25's original code under GPL-3.0-or-later; it does not replace the licenses or
copyright notices in third-party files and packages. Preserve those notices
when redistributing modified source or container images.

| Component | Source used by this build | License and attribution |
| --- | --- | --- |
| OP25 receiver and browser UI | [boatbod/op25 at `71abcd0ead32f86f51615ea6cc8a6a4dba4c949a`](https://github.com/boatbod/op25/tree/71abcd0ead32f86f51615ea6cc8a6a4dba4c949a), derived from [Osmocom OP25](https://git.osmocom.org/op25/) | OP25 source headers identify the original authors and GPL-3.0-or-later terms. The image retains the source and headers at `/opt/op25`; the GPLv3 text is in `LICENSE`. |
| RTL-SDR Blog V3/V4 driver | [rtlsdrblog/rtl-sdr-blog at `aed0ea19f3a273370a13c9009b96313c75d54c7b`](https://github.com/rtlsdrblog/rtl-sdr-blog/tree/aed0ea19f3a273370a13c9009b96313c75d54c7b) | Driver source headers identify the authors and GPL-2.0-or-later terms. Its `COPYING` (GPLv2 text), source, and notices remain at `/opt/rtl-sdr-blog` in the image. |
| Ubuntu/GNU Radio and Python dependencies | Ubuntu 22.04 packages in `build/Dockerfile` and the pinned packages in `build/requirements.txt` | Each package keeps its own license. Consult its installed `/usr/share/doc` notice, Python distribution metadata, and upstream license as applicable. These components are not relicensed as Brutal OP25 code. |

The image is reproducibly assembled from the pinned upstream commits and
`build/Dockerfile`. Modifications to OP25 and RTL-SDR Blog are in
`build/op25-audio-origin.patch`, `build/rtl-usb-retry.patch`, and the versioned
runtime adaptations in `src/brutal_ui.py` and `src/brutal_runtime.py`. The image
label `org.opencontainers.image.revision` identifies the exact Brutal OP25
source commit used for a tagged release. The source and patches must remain
available to recipients of the corresponding image.

The separately built, local-only SDRplay addon is **not** part of the published
base image. It downloads SDRplay's proprietary API from the vendor after the
user reviews its license; do not publish that addon without distribution
permission. The addon's [SoapySDRPlay3 plugin](https://github.com/pothosware/SoapySDRPlay3)
is MIT-licensed, and its source and `LICENSE.txt` are retained in the local
addon image.

RadioReference database records and screenshots are not covered by this
software license. Review their redistribution rights separately before making
the repository public.
