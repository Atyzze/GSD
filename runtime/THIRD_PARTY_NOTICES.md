# The bundled namespace bootstrap

The tree bundles only the small userspace bootstrap needed to create an
unprivileged Linux user namespace without depending on host utilities. PostgreSQL
itself is not copied into this source archive: the first database use downloads
the exact digest-pinned Docker Official Image layers into `./instance/` and
verifies their SHA-256 digests before use.

Bundled linux/amd64 bootstrap files:

- `unshare`: util-linux 2.41 (Debian package `util-linux` `2.41-5`), from
  Debian GNU/Linux 13 (trixie). util-linux is distributed under the GNU GPL
  version 2 and its upstream per-file free-software licenses
  (`runtime/licenses/GPL-2.txt`).
- `libc.so.6`, `ld-linux-x86-64.so.2`: GNU C Library 2.41 (Debian package
  `glibc` `2.41-12+deb13u3`), from Debian GNU/Linux 13. glibc is distributed
  under the GNU LGPL version 2.1 and related per-file licenses
  (`runtime/licenses/LGPL-2.1.txt`).

**Corresponding source.** The complete corresponding source of both binaries is
the Debian source packages of exactly these versions:

- util-linux 2.41-5: https://snapshot.debian.org/package/util-linux/2.41-5/
- glibc 2.41-12+deb13u3: https://snapshot.debian.org/package/glibc/2.41-12%2Bdeb13u3/

For three years from the date of this distribution, whoever distributed this
archive to you will also provide that source on request, at no more than the
cost of physically performing the distribution.

Pinned file SHA-256 values are enforced by `tools/postgres_instance.py` before
execution. The runtime refuses altered bootstrap binaries.

PostgreSQL runtime source/version: PostgreSQL 17.10. The pulled Docker Official
Image is pinned to the linux/amd64 manifest digest recorded in
`tools/postgres_instance.py`; PostgreSQL is distributed under the PostgreSQL
License. Runtime files remain under the extracted project directory.
