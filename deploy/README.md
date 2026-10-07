# Chromium seccomp policy

`chromium-seccomp.json` uses the Docker/Moby default profile from commit
`2ceae35d351c156cb5a8efc0fdc4a08cf94569d8`:

https://github.com/moby/profiles/blob/2ceae35d351c156cb5a8efc0fdc4a08cf94569d8/seccomp/default.json

It appends the existing Playwright user-namespace allowance from:

https://github.com/microsoft/playwright/blob/v1.60.0/utils/docker/seccomp_profile.json

That rule allows `clone`, `setns`, and `unshare` without argument restrictions.
These syscalls allow Chromium to establish its own Linux namespace sandbox.
They also expose kernel namespace operations to container processes. The profile
still defaults to deny (`SCMP_ACT_ERRNO`); it is not an unconfined policy.
Docker's modern compatibility rules include `openat2` and a `clone3` ENOSYS
fallback. The old Playwright profile failed before application startup under this
tested runc/libpathrs runtime. This profile retains a default-deny policy while
allowing Chromium's namespace sandbox to initialize.

The app runs as a non-root user, with all Docker capabilities dropped except
`SYS_CHROOT` (a standard Docker capability needed for Chromium sandbox setup),
no-new-privileges, a read-only filesystem, bounded temporary storage, CPU/memory/process limits,
and an internal-only network. Only the separate guarded proxy has outbound
network access. The proxy drops every capability and uses no-new-privileges.
The tested Playwright 1.63.0 browser supports these settings. Earlier smoke
tests with Playwright 1.60.0 failed under the added restrictions, which is why
CI tests the exact installed browser rather than assuming compatibility. Never add SYS_ADMIN, run privileged, use
seccomp unconfined,
or disable Chromium's sandbox to make rendering start.

Host kernels and security modules must allow unprivileged user namespaces.
Verify the exact shipped browser with `scripts/browser_regression.py` in the
bounded container before deploying. Sandbox startup failures are deployment
blockers; static-only operation remains available with rendering disabled.

Upstream Docker/Moby profiles use Apache-2.0 licensing; Playwright uses
Apache-2.0. Preserve upstream licensing when redistributing.
