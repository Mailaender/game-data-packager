#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
#           © 2015 Alexandre Detiste <alexandre@detiste.be>
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

import argparse
import logging
import os
import subprocess
import sys
import tarfile
import glob

from debian.deb822 import Deb822
import yaml

from . import HashedFile
from .steam import parse_acf
from .util import which

logging.basicConfig()
logger = logging.getLogger('game_data_packager.make-template')


def is_license(file):
    name, ext = os.path.splitext(file.lower())
    if ext not in ('.doc', '.htm', '.html', '.pdf', '.txt', ''):
        return False
    for word in ('eula', 'license', 'vendor'):
        if word in name:
            return True
    return False

def is_doc(file):
    name, ext = os.path.splitext(file.lower())
    if ext not in ('.doc', '.htm', '.html', '.pdf', '.txt', ''):
        return False
    for word in ('changes', 'manual', 'quickstart', 'readme'):
        if word in name:
            return True
    return False

def is_dosbox(file):
    basename = os.path.basename(file)
    if basename in ('dosbox.conf', 'dosbox-0.71.tar.gz', 'dosbox.exe',
                    'SDL_net.dll', 'SDL.dll', 'zmbv.dll', 'zmbv.inf'):
         return True
    # to check: COPYING.txt INSTALL.txt NEWS.txt THANKS.txt *.conf
    if basename not in ('AUTHORS.txt', 'README.txt'):
         return False
    with open(file, 'r', encoding='latin1') as txt:
         line = txt.readline()
         return 'dosbox' in line.lower()

def do_one_dir(destdir,lower):
    data = dict()
    files = dict(files={})
    game = os.path.basename(os.path.abspath(destdir))
    if game.endswith('-data'):
        game = game[:len(game) - 5]

    longname = None
    steam = max(destdir.find('/SteamApps/common/'),
                destdir.find('/steamapps/common/'))
    if steam > 0:
          steam_dict = dict()
          steam_id = 'FIXME'
          for acf in parse_acf(destdir[:steam+11]):
              if '/common/' + acf['installdir'] in destdir:
                   steam_id = acf['appid']
                   longname = game = acf['name']
                   break
          steam_dict['id'] = steam_id
          steam_dict['path'] = destdir[steam+11:]

    game = game.replace(' ','').replace(':','').replace('-','').lower()
    package = data.setdefault('packages', {}).setdefault(game + '-data', {})

    if steam > 0:
          package['steam'] = steam_dict

    package['install_to'] = 'usr/share/games/' + game

    install = set()
    license = set()
    optional = set()
    sums = dict(sha1={}, md5={}, sha256={}, ck={})
    has_dosbox = False

    for dirpath, dirnames, filenames in os.walk(destdir):
        dir_l = dirpath.lower()
        if dir_l.endswith('/directx'):
            logger.warning('ignoring DirectX runtime at %s' % dirpath)
            continue
        if dir_l.endswith('/data.now'):
            logger.warning('ignoring Sold Out runtime at %s' % dirpath)
            continue
        if '/directx/' in dir_l or '/data.now/' in dir_l:
            continue

        for fn in filenames:
            path = os.path.join(dirpath, fn)

            assert path.startswith(destdir + '/')
            name = path[len(destdir) + 1:]
            out_name = name
            if lower:
                out_name = out_name.lower()

            if os.path.isdir(path):
                continue
            elif is_dosbox(path):
                has_dosbox = True
            elif os.path.splitext(fn.lower())[1] in ('.exe', '.ovl', '.dll', '.bat', '.386'):
                logger.warning('ignoring dos/windows binary %s' % fn)
            elif os.path.islink(path):
                package.setdefault('symlinks', {})[name] = os.path.realpath(path).lstrip('/')
            elif os.path.isfile(path):
                if is_license(fn):
                     out_name = os.path.basename(out_name)
                     license.add(out_name)
                elif is_doc(fn):
                     optional.add(out_name)
                     files['files'][out_name] = dict(install_to='$docdir')
                else:
                     install.add(out_name)

                hf = HashedFile.from_file(name, open(path, 'rb'))
                sums['ck'][out_name] = os.path.getsize(path)
                sums['md5'][out_name] = hf.md5
                sums['sha1'][out_name] = hf.sha1
                sums['sha256'][out_name] = hf.sha256
            else:
                logger.warning('ignoring unknown file type at %s' % path)

    if has_dosbox:
        logger.warning('DOSBOX files detected, make sure not to include those in your package')

    print('---')
    if longname:
        print('longname: %s\n' % longname)
    print('copyright: © 1970 FIXME')
    if destdir.startswith('/usr/local') or destdir.startswith('/opt/'):
        print('try_repack_from:\n- %s\n' % destdir)
    yaml.safe_dump(data, stream=sys.stdout, default_flow_style=False)

    print('    install:')
    for file in sorted(install):
        print('    - %s' % file)

    if optional:
        print('    optional:')
        for file in sorted(optional):
            print('    - %s' % file)
    if license:
        print('    license:')
        for file in sorted(license):
            print('    - %s' % file)

    if files['files']:
        yaml.safe_dump(files, stream=sys.stdout, default_flow_style=False)

    for alg, files in sorted(sums.items()):
        print('%ssums: |' % alg)
        for filename, sum_ in sorted(files.items()):
            if alg == 'ck':
                print('  _ %-9s %s' % (sum_, filename))
            else:
                print('  %s  %s' % (sum_, filename))

    print('...')
    print('')

def do_one_file(name,lower):
    hf = HashedFile.from_file(name, open(name, 'rb'))
    out_name = os.path.basename(name)
    if lower:
        out_name = out_name.lower()

    # sniff Makeself archives
    # http://megastep.org/makeself/
    has_makeself = False
    trailer = None
    SHEBANG = bytes('/bin/sh', 'ascii')
    HEADER_V1 = bytes('# This script was generated using Makeself 1.', 'ascii')
    HEADER_V2 = bytes('# This script was generated using Makeself 2.', 'ascii')
    TRAILER_V1 = bytes('END_OF_STUB', 'ascii')
    TRAILER_V2 = bytes('eval $finish; exit $res', 'ascii')
    with open(name, 'rb') as raw:
        skip = 0
        pos = 0
        for line in raw:
            pos += 1
            skip += len(line)
            if pos == 1 and SHEBANG not in line:
                break
            elif has_makeself:
                if trailer in line:
                    break
            elif HEADER_V1 in line:
                has_makeself = True
                trailer = TRAILER_V1
            elif HEADER_V2 in line:
                has_makeself = True
                trailer = TRAILER_V2
            elif pos > 3:
                break
    if has_makeself:
        print('  %s' % out_name)
        print('    unpack: tar.gz')
        print('    skip: %d' % skip)
        print()

    print('  _ %-9s %s' % (os.path.getsize(name), out_name))
    print('  %s  %s' % (hf.md5, out_name))
    print('  %s  %s' % (hf.sha1, out_name))
    print('  %s  %s' % (hf.sha256, out_name))

def do_one_deb(deb):
    control = None

    with subprocess.Popen(['dpkg-deb', '--ctrl-tarfile', deb],
            stdout=subprocess.PIPE) as ctrl_process:
        with tarfile.open(deb + '//control.tar.*', mode='r|',
                fileobj=ctrl_process.stdout) as ctrl_tarfile:
            for entry in ctrl_tarfile:
                name = entry.name
                if name == '.':
                    continue

                if name.startswith('./'):
                    name = name[2:]
                if name == 'control':
                    reader = ctrl_tarfile.extractfile(entry)
                    control = Deb822(reader)
                    print('# data/%s.control.in' % control['package'])
                    control['version'] = 'VERSION'
                    control.dump(fd=sys.stdout, text_mode=True)
                    print('')
                elif name == 'preinst':
                    logger.warning('ignoring preinst, not supported yet')
                elif name == 'md5sums':
                    pass
                else:
                    logger.warning('unknown control member: %s', name)

    if control is None:
        logger.error('Could not find DEBIAN/control')

    data = dict(packages={ control['package']: {} })
    files = dict(files={})
    package = data['packages'][control['package']]
    package['install_to'] = None
    install = set()
    optional = set()
    sums = dict(sha1={}, md5={}, sha256={}, ck={})

    with subprocess.Popen(['dpkg-deb', '--fsys-tarfile', deb],
            stdout=subprocess.PIPE) as fsys_process:
        with tarfile.open(deb + '//data.tar.*', mode='r|',
                fileobj=fsys_process.stdout) as fsys_tarfile:
            for entry in fsys_tarfile:
                name = entry.name
                if name.startswith('./'):
                    name = name[2:]

                if (name.startswith('usr/share/doc/') and
                        name.endswith('changelog.gz')):
                    continue

                if (name.startswith('usr/share/doc/') and
                        name.endswith('changelog.Debian.gz')):
                    continue

                if (name.startswith('usr/share/doc/') and
                        name.endswith('copyright')):
                    print('# data/%s.copyright' % control['package'])
                    for line in fsys_tarfile.extractfile(entry):
                        print(line.decode('utf-8'), end='')
                    print('')
                    continue

                if (name.startswith('usr/share/games/') and
                        entry.isfile() and
                        package['install_to'] is None):
                    # assume this is the place
                    there = name[len('usr/share/games/'):]
                    there = there.split('/', 1)[0]
                    package['install_to'] = ('usr/share/games/' + there)

                if entry.isfile():
                    hf = HashedFile.from_file(deb + '//data.tar.*//' + name,
                            fsys_tarfile.extractfile(entry))

                    if (package['install_to'] is not None and
                            name.startswith(package['install_to'] + '/')):
                        name = name[len(package['install_to']) + 1:]
                        install.add(name)
                    else:
                        optional.add(name)
                        files['files'][name] = dict(install_to='.')

                    sums['ck'][name] = entry.size
                    sums['md5'][name] = hf.md5
                    sums['sha1'][name] = hf.sha1
                    sums['sha256'][name] = hf.sha256

                elif entry.isdir():
                    pass
                elif entry.issym():
                    package.setdefault('symlinks', {})[name] = os.path.join(
                            os.path.dirname(name), entry.linkname)
                else:
                    logger.warning('unhandled data.tar entry type: %s: %s',
                            name, entry.type)

    print('# data/%s.yaml' % control['package'])
    print('%YAML 1.2')
    print('---')
    print('copyright: © 1970 FIXME')
    yaml.safe_dump(data, stream=sys.stdout, default_flow_style=False)

    print('    install:')
    for file in sorted(install):
        print('    - %s' % file)

    if optional:
        print('    optional:')
        for file in sorted(optional):
             print('    - %s' % file)

    if files['files']:
        yaml.safe_dump(files, stream=sys.stdout, default_flow_style=False)

    for alg, files in sorted(sums.items()):
        print('%ssums: |' % alg)
        for filename, sum_ in sorted(files.items()):
            if alg == 'ck':
                print('  _ %-9s %s' % (sum_, filename))
            else:
                print('  %s  %s' % (sum_, filename))

    print('...')
    print('')

def do_one_exec(pgm,lower):
    print('running:', pgm)
    with subprocess.Popen(['strace', '-e', 'open',
                           '-s', '100'] + pgm,
           stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
           universal_newlines=True) as proc:
        used = set()
        missing = set()
        while proc.poll() == None:
            line = proc.stderr.readline().strip()
            if not line.startswith('open('):
                continue
            file = line.split('"')[1]
            if (not file.startswith('/usr/share/games')
              and not file.startswith('/usr/local/')):
                continue
            if 'ENOENT' in line:
               missing.add(file)
            else:
               used.add(file)

        dirs = set()
        print('# used')
        for file in sorted(used):
            dirs.add(os.path.dirname(file))
            print("    - %s" % file)
        if missing:
            print('# missing ?')
            for file in sorted(missing):
                print("    - %s" % file)

        present = set()
        for dir in dirs:
            for dirpath, dirnames, filenames in os.walk(dir):
                for fn in filenames:
                    present.add(os.path.join(dirpath, fn))

        unused = present - used
        if unused:
            print('# not used')
            for file in sorted(unused):
                print("    - %s" % file)

def do_flacsums(destdir, lower):
    if which('ffmpeg'): tool = 'ffmpeg'
    elif which('avconv'): tool = 'avconv'
    else:
        exit('Install either ffmpeg or avconv')
    if not which('metaflac'):
        exit('Install metaflac')

    fla_or_flac = '.fla'
    md5s = dict()
    done_wav = 0
    done_flac = 0
    for filename in glob.glob(os.path.join(destdir, '*')):
        file = os.path.basename(filename).lower()
        file, ext = os.path.splitext(file)
        if ext == '.wav':
            md5 = subprocess.check_output([tool, '-i', filename, '-f', 'md5', '-'],
                     stderr=subprocess.DEVNULL,
                     universal_newlines=True)
            md5 = md5.rstrip().split('=')[1]
            assert file not in md5s or md5s[file] == md5, \
                   "got differents md5's for %s.wav|flac" % file
            md5s[file] = md5
            done_wav += 1
        if ext == '.flac':
            fla_or_flac = '.flac'
        if ext in ('.fla','.flac'):
            md5 = subprocess.check_output(['metaflac', '--show-md5sum', filename],
                     universal_newlines=True)
            md5 = md5.rstrip()
            assert file not in md5s or md5s[file] == md5, \
                   "got differents md5's for %s.wav|flac" % file
            md5s[file] = md5
            done_flac += 1

    if not md5s:
        exit("Couldn' find any .wav or .flac file")

    print('flacsums: |')
    for file in sorted(md5s.keys()):
        print('  %s  %s' % (md5s[file], file + fla_or_flac))

    print("\n#processed %i .wav and %i .fla[c] files" % (done_wav, done_flac))

def main():
    parser = argparse.ArgumentParser(
            description='Produce a template for game-data-packager YAML ' +
                'based on an existing .deb file or installed directory',
            prog='game-data-packager guess-contents')
    parser.add_argument('args', nargs='+', metavar='DEB|DIRECTORY|FILE')
    parser.add_argument('-l', '--lower', action='store_true', dest='lower',
            help='make all files lowercase')
    parser.add_argument('-e', '--execute', action='store_true', dest='execute',
            help='run this game through strace and see which files from '
                 '/usr/share/games or /usr/local/games are needed')
    parser.add_argument('-f', '--flacsums', action='store_true', dest='flacsums',
            help='compute "flacsums" from .wav files')
    args = parser.parse_args()

    # ./run make-template -e -- scummvm -p /usr/share/games/spacequest1/ sq1
    if args.execute:
        do_one_exec(args.args,args.lower)
        return

    for arg in args.args:
        if args.flacsums:
            do_flacsums(arg,args.lower)
        elif os.path.isdir(arg):
            do_one_dir(arg.rstrip('/'),args.lower)
        elif arg.endswith('.deb'):
            do_one_deb(arg)
        else:
            do_one_file(arg,args.lower)

if __name__ == '__main__':
    try:
        main()
    except BrokenPipeError:
        pass
