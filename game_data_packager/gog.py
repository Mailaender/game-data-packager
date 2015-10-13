#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Alexandre Detiste <alexandre@detiste.be>
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

import json
import logging
import os
import subprocess

from .util import (PACKAGE_CACHE,
        ascii_safe,
        lang_score,
        which)

logger = logging.getLogger('game-data-packager.gog')

class Gog:
    available = None

    def owned_games(self):
        if self.available is not None:
            return self.available

        self.available = []
        cache = os.path.expanduser('~/.cache/lgogdownloader/gamedetails.json')
        if not which('lgogdownloader'):
            pass
        elif os.path.isfile(cache):
            data = json.load(open(cache, encoding='utf-8'))
            for key in data['games']:
                self.available.append(key['gamename'])
        else:
            try:
                list = subprocess.check_output(['lgogdownloader', '--list'],
                               stdin=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               universal_newlines=True)
                self.available = list.splitlines()
            except subprocess.CalledProcessError:
                pass

        return self.available

    def is_native(self, wanted):
        cache = os.path.expanduser('~/.cache/lgogdownloader/gamedetails.json')
        if not os.path.isfile(cache):
            return

        data = json.load(open(cache, encoding='utf-8'))
        for game in data['games']:
            if game['gamename'] != wanted:
                continue
            for installer in game['installers']:
                if installer['platform'] == 4:
                    return True
            return False

    def get_id_from_archive(self, archive):
        cache = os.path.expanduser('~/.cache/lgogdownloader/gamedetails.json')
        if not os.path.isfile(cache):
            return None

        archive = os.path.basename(archive)

        data = json.load(open(cache, encoding='utf-8'))
        for game in data['games']:
            for installer in game['installers']:
                if installer['path'].endswith(archive):
                    return game['gamename']

    def verify_checksum(self, archive, size, md5):
        basename = os.path.basename(archive)
        extension = os.path.splitext(basename)[1]
        if not (basename.startswith('gog_') and extension == '.sh'
             or basename.startswith('setup_') and extension == '.exe'):
            return False

        xml_root = os.path.expanduser('~/.cache/lgogdownloader/xml/')
        if not os.path.isdir(xml_root):
            return False

        for dirpath, dirnames, filenames in os.walk(xml_root):
            for fn in filenames:
                if fn != basename + '.xml':
                    continue
                xml_file = os.path.join(dirpath, fn)
                xml = open(xml_file, 'r', encoding='utf-8').readline()
                xml = xml.strip('<>\n')
                for tag in xml.split(' '):
                    if '=' not in tag:
                        continue
                    k,v = tag.split('=', 2)
                    v = v.strip('"')
                    if k == 'md5' and v != md5:
                        return False
                    elif k == 'total_size' and int(v) != size:
                        return False
                else:
                    return True
        return False

GOG = Gog()

def run_gog_meta_mode(parsed, games):
    logger.info('Visit game-data-packager @ GOG.com: https://www.gog.com/mix/games_supported_by_debians_gamedatapackager')
    if not which('lgogdownloader') or not which('innoextract'):
        logger.error("You need to install lgogdownloader & innoextract first")
        logger.error("$ su -c 'apt-get install lgogdownloader innoextract'")
        return

    owned = GOG.owned_games()
    if not owned:
        logger.error("Couldn't locate any game, running 'lgogdownloader --login'")
        subprocess.call(['lgogdownloader', '--login'])
        logger.info("... and now 'lgogdownloader --update-cache'")
        subprocess.call(['lgogdownloader', '--update-cache'])
        GOG.available = None
        owned = GOG.owned_games()
    logger.info("Found %d game(s) !" % len(owned))

    found_games = set()
    found_packages = []
    for game, data in games.items():
        for package in data.packages.values():
            id = data.gog_download_name(package)
            if id is None or id not in owned:
                continue
            if lang_score(package.lang) == 0:
                continue
            if package.better_version:
                if data.gog_download_name(data.packages[package.better_version]):
                    continue
            installed = PACKAGE_CACHE.is_installed(package.name)
            if parsed.new and installed:
                continue
            found_games.add(game)
            found_packages.append({
                'game' : game,
                'type' : 1 if package.type == 'full' else 2,
                'package': package.name,
                'installed': installed,
                'longname': package.longname or data.longname,
                'id': id,
               })
    if not found_games:
        logger.error('No supported GOG.com games found')
        return

    print('[x] = package is already installed')
    found_packages = sorted(found_packages, key=lambda k: (k['game'], k['type'], k['longname']))
    for g in sorted(found_games):
        ids = set()
        for p in found_packages:
            if p['game'] == g:
                ids.add('"%s"' % p['id'])
        print('%s - provided by %s' % (g, ','.join(ids)))
        for p in found_packages:
            if p['game'] == g:
                print('[%s] %-42s    %s' % ('x' if p['installed'] else ' ',
                                        p['package'], ascii_safe(p['longname'])))
        print()
