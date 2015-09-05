#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
#             2015 Alexandre Detiste <alexandre@detiste.be>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# You can find the GPL license text on a Debian system under
# /usr/share/common-licenses/GPL-2.

import configparser
import logging
import os
import subprocess

from .. import GameData
from ..paths import DATADIR
from ..util import mkdir_p

logger = logging.getLogger('game-data-packager.games.residualvm-common')

def install_data(from_, to):
    subprocess.check_call(['cp', '--reflink=auto', from_, to])

class ResidualvmGameData(GameData):
    def __init__(self, shortname, data, workdir=None):
        super(ResidualvmGameData, self).__init__(shortname, data,
                workdir=workdir)

        self.wikibase = 'http://wiki.residualvm.org/index.php/'
        assert self.wiki

        self.gameid = self.data['gameid']
        if self.gameid != shortname:
            self.aliases.add(self.gameid)

        if self.engine is None:
            self.engine = 'residualvm'
        if self.genre is None:
            self.genre = 'Adventure'

    def fill_extra_files(self, package, destdir):
        super(ResidualvmGameData, self).fill_extra_files(package, destdir)
        if package.type == 'expansion':
            return

        icon = package.name
        for from_ in (self.locate_steam_icon(package),
                      os.path.join(DATADIR, package.name + '.png'),
                      os.path.join(DATADIR, self.shortname + '.png'),
                      os.path.join('/usr/share/pixmaps', icon + '.png'),
                      os.path.join(DATADIR, self.shortname.strip('1234567890') + '.png')):
            if from_ and os.path.exists(from_):
                pixdir = os.path.join(destdir, 'usr/share/pixmaps')
                mkdir_p(pixdir)
                install_data(from_, os.path.join(pixdir, '%s.png' % icon))
                break
        else:
            icon = 'residualvm'

        from_ = os.path.splitext(from_)[0] + '.svgz'
        if os.path.exists(from_):
            svgdir = os.path.join(destdir, 'usr/share/icons/hicolor/scalable/apps')
            mkdir_p(svgdir)
            install_data(from_, os.path.join(svgdir, '%s.svgz' % icon))

        appdir = os.path.join(destdir, 'usr/share/applications')
        mkdir_p(appdir)

        desktop = configparser.RawConfigParser()
        desktop.optionxform = lambda option: option
        desktop['Desktop Entry'] = {}
        entry = desktop['Desktop Entry']
        entry['Name'] = package.longname or self.longname
        entry['GenericName'] = self.genre + ' Game'
        entry['TryExec'] = 'residualvm'
        entry['Icon'] = icon
        entry['Terminal'] = 'false'
        entry['Type'] = 'Application'
        entry['Categories'] = 'Game'
        entry['Exec'] = 'residualvm -p /%s %s' % (package.install_to, self.gameid)
        with open(os.path.join(appdir, '%s.desktop' % package.name),
                  'w', encoding='utf-8') as output:
             desktop.write(output, space_around_delimiters=False)

        lintiandir = os.path.join(destdir, 'usr/share/lintian/overrides')
        mkdir_p(lintiandir)
        with open(os.path.join(lintiandir, package.name),
                  'a', encoding='utf-8') as o:
             o.write('%s: desktop-command-not-in-package '
                     'usr/share/applications/%s.desktop residualvm\n'
                     % (package.name, package.name))

GAME_DATA_SUBCLASS = ResidualvmGameData
