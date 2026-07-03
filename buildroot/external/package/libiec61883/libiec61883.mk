################################################################################
# libiec61883
################################################################################
LIBIEC61883_VERSION = 1.2.0
LIBIEC61883_SITE = $(BR2_KERNEL_MIRROR)/linux/libs/ieee1394
LIBIEC61883_SOURCE = libiec61883-$(LIBIEC61883_VERSION).tar.gz
LIBIEC61883_LICENSE = LGPL-2.1+
LIBIEC61883_LICENSE_FILES = COPYING
LIBIEC61883_INSTALL_STAGING = YES
LIBIEC61883_DEPENDENCIES = libraw1394 host-pkgconf
$(eval $(autotools-package))
