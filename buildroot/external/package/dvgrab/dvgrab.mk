################################################################################
# dvgrab
################################################################################
DVGRAB_VERSION = 3.5
DVGRAB_SITE = http://downloads.sourceforge.net/project/kino/dvgrab/$(DVGRAB_VERSION)
DVGRAB_SOURCE = dvgrab-$(DVGRAB_VERSION).tar.gz
DVGRAB_LICENSE = GPL-2.0+
DVGRAB_LICENSE_FILES = COPYING
DVGRAB_DEPENDENCIES = libraw1394 libavc1394 libiec61883 libdv host-pkgconf
$(eval $(autotools-package))
