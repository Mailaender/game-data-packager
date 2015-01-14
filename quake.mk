# FOLDER, VERSION, PACKAGE and LONG must be supplied by caller

srcdir = $(CURDIR)
builddir = $(CURDIR)/build
outdir = $(CURDIR)/out

QUAKEDEB = $(outdir)/$(PACKAGE)_$(VERSION)_all.deb

ifeq ($(filter-out quake-music quake-%-music,$(PACKAGE)),)

all: do-$(PACKAGE)

do-${PACKAGE}: do-common
	install -m644 data/quake-music.copyright ${outdir}/${PACKAGE}.copyright
	( \
		md5sum ${outdir}/changelog.gz | \
			sed 's# .*#  usr/share/doc/${PACKAGE}/changelog.gz#'; \
		md5sum ${outdir}/${PACKAGE}.copyright | \
			sed 's# .*#  usr/share/doc/${PACKAGE}/copyright#'; \
	) > ${outdir}/quake/${PACKAGE}.md5sums
	chmod 0644 ${outdir}/quake/${PACKAGE}.md5sums

do-common:
	install -d ${outdir}/quake
	m4 -DVERSION=${VERSION} < data/${PACKAGE}.control.in > ${outdir}/quake/${PACKAGE}.control
	chmod 0644 ${outdir}/quake/${PACKAGE}.control

clean:
	rm -rf $(outdir)/quake/

else

do-${PACKAGE}: ${outdir}/${PACKAGE}.copyright

$(QUAKEDEB): \
	$(builddir)/$(PACKAGE)/DEBIAN/md5sums \
	$(builddir)/$(PACKAGE)/DEBIAN/control \
	fixperms
	install -d $(builddir)/$(PACKAGE)/usr/share/games/quake/$(FOLDER)
	if [ "$(FOLDER)" = hipnotic ] || [ "$(FOLDER)" = rogue ]; then \
		printf '#!/bin/sh\nexit 0\n' > $(builddir)/$(PACKAGE)/usr/share/games/quake/$(FOLDER)-tryexec.sh; \
		chmod 0755 $(builddir)/$(PACKAGE)/usr/share/games/quake/$(FOLDER)-tryexec.sh; \
	fi

	cd $(builddir) && \
	if [ `id -u` -eq 0 ]; then \
		dpkg-deb -b $(PACKAGE) $@ ; \
	else \
		fakeroot dpkg-deb -b $(PACKAGE) $@ ; \
	fi

$(builddir)/$(PACKAGE)/DEBIAN/md5sums: \
	$(builddir)/$(PACKAGE)/usr/share/doc/$(PACKAGE)/changelog.gz \
	$(builddir)/$(PACKAGE)/usr/share/doc/$(PACKAGE)/copyright
	install -d `dirname $@`
	cd $(builddir)/$(PACKAGE) && find usr/ -type f  -print0 |\
		xargs -0 md5sum >DEBIAN/md5sums

$(builddir)/$(PACKAGE)/usr/share/doc/$(PACKAGE)/changelog.gz: debian/changelog
	install -d `dirname $@`
	gzip -c9 debian/changelog > $@

${outdir}/${PACKAGE}.copyright:
	m4 -DPACKAGE=$(PACKAGE) quake-common/copyright.in > $@

$(builddir)/$(PACKAGE)/usr/share/doc/$(PACKAGE)/copyright: quake-common/copyright.in
	install -d `dirname $@`
	m4 -DPACKAGE=$(PACKAGE) quake-common/copyright.in > $@

$(builddir)/$(PACKAGE)/DEBIAN/control: quake-common/DEBIAN/control.in
	install -d `dirname $@`
	m4 -DVERSION=$(VERSION) -DPACKAGE=$(PACKAGE) -DLONG="$(LONG)" \
	     < quake-common/DEBIAN/control.in > $@
	if [ "$(PACKAGE)" = "quake-registered" ]; then \
	  echo Conflicts: quake-shareware >> $@; \
	  echo Replaces: quake-shareware >> $@; \
	elif [ "$(PACKAGE)" != "quake-shareware" ]; then \
	  echo Depends: quake-registered >> $@; \
	else \
	  echo Conflicts: quake-registered >> $@; \
	fi

fixperms:
	find $(builddir)/$(PACKAGE) -type f -print0 | xargs -0 chmod 644
	find $(builddir)/$(PACKAGE) -type d -print0 | xargs -0 chmod 755

clean:
	rm -rf $(QUAKEDEB) $(builddir)/$(PACKAGE)

endif
