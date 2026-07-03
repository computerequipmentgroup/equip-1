################################################################################
# libavc1394
################################################################################
LIBAVC1394_VERSION = 0.5.4
# Upstream SourceForge tarball is gone; Debian's mirror keeps the original.
LIBAVC1394_SITE = http://deb.debian.org/debian/pool/main/liba/libavc1394
LIBAVC1394_SOURCE = libavc1394_$(LIBAVC1394_VERSION).orig.tar.gz
LIBAVC1394_LICENSE = LGPL-2.1+
LIBAVC1394_LICENSE_FILES = COPYING
LIBAVC1394_INSTALL_STAGING = YES
LIBAVC1394_DEPENDENCIES = libraw1394 host-pkgconf
$(eval $(autotools-package))
