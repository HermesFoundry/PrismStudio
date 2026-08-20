# localdeps — the three -dev packages, unpacked into a prefix of our own.
#
# The machine has the runtime libraries (libxkbfile, libkrb5, libsecret) but
# not their headers, and installing those needs root. The .deb files carry
# nothing but headers, .pc files and the unversioned .so names, so they are
# unpacked into ~/.local/prismdeps and pointed at instead — the build gets what
# it needs and the system is left exactly as it was.
#
#   source branding/localdeps.sh
#
# branding/fetch-localdeps.sh puts the prefix together from scratch.
PRISM_DEPS="${PRISM_DEPS:-$HOME/.local/prismdeps}"
export CPATH="$PRISM_DEPS/usr/include:$PRISM_DEPS/usr/include/x86_64-linux-gnu${CPATH:+:$CPATH}"
export LIBRARY_PATH="$PRISM_DEPS/usr/lib/x86_64-linux-gnu${LIBRARY_PATH:+:$LIBRARY_PATH}"
export PKG_CONFIG_PATH="$PRISM_DEPS/usr/lib/x86_64-linux-gnu/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
export PATH="$PRISM_DEPS/usr/bin:$PATH"
