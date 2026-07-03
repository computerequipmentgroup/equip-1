################################################################################
# libdv
################################################################################
LIBDV_VERSION = 1.0.0
LIBDV_SITE = http://downloads.sourceforge.net/project/libdv/libdv/$(LIBDV_VERSION)
LIBDV_SOURCE = libdv-$(LIBDV_VERSION).tar.gz
LIBDV_LICENSE = LGPL-2.1+
LIBDV_LICENSE_FILES = COPYING.LIB
LIBDV_INSTALL_STAGING = YES
LIBDV_DEPENDENCIES = popt host-pkgconf
# No x86 asm on aarch64; skip the GTK/Xv playdv tool (encodedv still builds, needs popt).
LIBDV_CONF_OPTS = --disable-asm --disable-gtk --disable-xv --disable-gprof
$(eval $(autotools-package))
