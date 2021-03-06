#!/usr/bin/python3
# encoding=utf-8

# game-data-packager Gtk launcher stub. See doc/launcher.mdwn for design

# Copyright © 2015-2016 Simon McVittie <smcv@debian.org>
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
import glob
import fnmatch
import json
import logging
import os
import shutil
import string
import sys
import traceback

import gi
gi.require_version('Gtk', '3.0')

from gi.repository import (GLib, GObject)
from gi.repository import Gtk

if 'GDP_UNINSTALLED' in os.environ:
    GDP_DIR = './runtime'
else:
    GDP_DIR = '/usr/share/games/game-data-packager'

# Normalize environment so we can use ${XDG_DATA_HOME} unconditionally.
# Do this before we use GLib functions that might create worker threads,
# because setenv() is not thread-safe.
ORIG_ENVIRON = os.environ.copy()
os.environ.setdefault('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
os.environ.setdefault('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
os.environ.setdefault('XDG_CONFIG_DIRS', '/etc/xdg')
os.environ.setdefault('XDG_DATA_HOME', os.path.expanduser('~/.local/share'))
os.environ.setdefault('XDG_DATA_DIRS', '/usr/local/share:/usr/share')

logger = logging.getLogger('game-data-packager.launcher')

if os.environ.get('GDP_DEBUG'):
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)

DISTRO = 'the distribution'

try:
    os_release = open('/usr/lib/os-release')
except:
    pass
else:
    for line in os_release:
        if line.startswith('NAME='):
            line = line[5:].strip()
            if line.startswith('"'):
                line = line.strip('"')
            elif line.startswith("'"):
                line = line.strip("'")
            DISTRO = line

def expand(path):
    if path is None:
        return None

    return os.path.expanduser(os.path.expandvars(path))

class IniEditor:
    def __init__(self, edits):
        self.lines = []
        self.edits = edits
        self.__section = None
        self.__section_lines = []
        self.__sections = set()

    def load(self, reader):
        # Simple INI parser. Not using ConfigParser because Unreal
        # uses duplicate keys within sections, and we want to preserve
        # comments, blank lines etc.
        self.__section = None
        self.__section_lines = []
        self.__sections = set()

        for line in reader:
            line = line.rstrip('\r\n')

            if line.startswith('[') and line.endswith(']'):
                self.__end_section()
                self.__section = line[1:-1]

            self.__section_lines.append(line)

        self.__end_section()

        for edit in self.edits:
            if edit['section'] not in self.__sections:
                self.__section = edit['section']
                self.__section_lines = ['[%s]' % edit['section']]
                self.__end_section()

    def __end_section(self):
        self.__sections.add(self.__section)

        for edit in self.edits:
            if edit['section'] != self.__section:
                continue

            logger.debug('editing %s', self.__section)
            extra_lines = []

            for k, v in sorted(edit.get('replace_key', {}).items()):
                logger.debug('replacing %s with %s', k, v)
                self.__section_lines = [l for l in self.__section_lines
                        if not l.startswith(k + '=')]
                extra_lines.append('%s=%s' % (k, v))

            for pattern in sorted(edit.get('delete_matched', [])):
                logger.debug('deleting lines matching %s', pattern)
                self.__section_lines = [l for l in self.__section_lines
                        if not fnmatch.fnmatchcase(l, pattern)]

            for pattern in edit.get('comment_out_matched', []):
                logger.debug('commenting out lines matching %s', pattern)
                for i in range(len(self.__section_lines)):
                    if fnmatch.fnmatchcase(self.__section_lines[i], pattern):
                        self.__section_lines[i] = ';' + self.__section_lines[i]
                        self.__section_lines.insert(i, '; ' +
                                edit['comment_out_reason'])

            for append in edit.get('append_unique', []):
                logger.debug('appending unique line %s', append)
                for line in self.__section_lines:
                    if line == append:
                        break
                else:
                    extra_lines.append(append)

            i = len(self.__section_lines) - 1

            while i >= 0:
                if self.__section_lines[i]:
                    # _s_l[i] is the last non-empty line, insert after it
                    self.__section_lines[i + 1:i + 1] = extra_lines
                    break
                i -= 1
            else:
                # no non-empty lines, insert after the section-opening heading
                self.__section_lines[1:1] = extra_lines

        self.lines.extend(self.__section_lines)
        self.__section_lines = []
        self.__section = None

    def save(self, writer):
        for line in self.lines:
            print(line, file=writer)

class Launcher:
    def __init__(self, argv=None):
        name = os.path.basename(sys.argv[0])

        if name.endswith('.py'):
            name = name[:-3]

        parser = argparse.ArgumentParser()
        parser.add_argument('--id', default=name,
                help='identity of launched game (default: %s)' % name)
        parser.add_argument('arguments', nargs='*',
                help='arguments for the launched game')
        self.args = parser.parse_args(argv)

        self.id = self.args.id
        self.keyfile = GLib.KeyFile()
        self.keyfile.load_from_file(os.path.join(GDP_DIR,
                    self.id + '.desktop'),
                GLib.KeyFileFlags.NONE)

        self.name = self.keyfile.get_string(GLib.KEY_FILE_DESKTOP_GROUP,
            GLib.KEY_FILE_DESKTOP_KEY_NAME)
        logger.debug('Name: %s', self.name)
        GLib.set_application_name(self.name)

        self.icon_name = self.keyfile.get_string(GLib.KEY_FILE_DESKTOP_GROUP,
            GLib.KEY_FILE_DESKTOP_KEY_ICON)
        logger.debug('Icon: %s', self.icon_name)

        if 'GDP_UNINSTALLED' in os.environ:
            import yaml
            self.data = yaml.load(open('%s/launch-%s.yaml' % (GDP_DIR, self.id),
                encoding='utf-8'), Loader=yaml.CSafeLoader)
        else:
            self.data = json.load(open('%s/launch-%s.json' % (GDP_DIR, self.id),
                encoding='utf-8'))

        self.binary_only = self.data['binary_only']
        logger.debug('Binary-only: %r', self.binary_only)
        self.required_files = list(map(expand, self.data['required_files']))
        logger.debug('Checked files: %r', sorted(self.required_files))

        self.dot_directory = expand(self.data.get('dot_directory',
                    '${XDG_DATA_HOME}/' + self.id))
        logger.debug('Dot directory: %s', self.dot_directory)

        self.base_directories = list(map(expand,
                        self.data.get('base_directories',
                            '/usr/lib/' + self.id)))
        logger.debug('Base directories: %r', self.base_directories)

        self.library_path = self.data.get('library_path', [])
        logger.debug('Library path: %r', self.library_path)

        self.working_directory = expand(self.data.get('working_directory',
                    None))
        logger.debug('Working directory: %s', self.working_directory)

        self.argv = list(map(expand, self.data.get('argv', False)))
        logger.debug('Arguments: %r', self.argv)

        self.exit_status = 1

    def main(self):
        have_all_data = True
        warning_stamp = os.path.join(self.dot_directory,
                'confirmed-binary-only.stamp')

        for p in self.base_directories:
            logger.debug('Searching: %s' % p)

        # sanity check: game engines often don't cope well with missing data
        for f in self.required_files:
            logger.debug('looking for %s', f)
            for p in self.base_directories:
                logger.debug('looking for %s in %s', f, p)
                if os.path.exists(os.path.join(p, f)):
                    logger.debug('found %s in %s', f, p)
                    break
            else:
                logger.warning('Data file is missing: %s' % f)
                have_all_data = False

        os.makedirs(self.dot_directory, exist_ok=True)

        if not have_all_data:
            gui = Gui(self)
            gui.text_view.get_buffer().set_text(
                    self.load_text('missing-data.txt', 'Data files missing'))
            gui.window.show_all()
            gui.check_box.hide()
            Gtk.main()
            sys.exit(72)    # EX_OSFILE

        elif self.binary_only and not os.path.exists(warning_stamp):
            self.exit_status = 77   # EX_NOPERM
            gui = Gui(self)
            gui.text_view.get_buffer().set_text(
                    self.load_text('confirm-binary-only.txt',
                        'Binary-only game, we cannot fix bugs or security '
                        'vulnerabilities!'))
            gui.check_box.bind_property('active', gui.ok_button, 'sensitive',
                    GObject.BindingFlags.SYNC_CREATE)
            gui.ok_button.connect('clicked', lambda _:
                    self._confirm_binary_only_cb(gui))

            gui.window.show_all()
            Gtk.main()
            sys.exit(self.exit_status)

        else:
            try:
                self.exec_game()
            except:
                gui = Gui(self)
                gui.text_view.get_buffer().set_text(traceback.format_exc())
                gui.ok_button.set_sensitive(False)
                gui.window.show_all()
                gui.check_box.hide()
                Gtk.main()
                sys.exit(self.exit_status)
            else:
                raise AssertionError('exec_game should never return')

    def flush(self):
        for f in (sys.stdout, sys.stderr):
            f.flush()

    def _confirm_binary_only_cb(self, gui):
        warning_stamp = os.path.join(self.dot_directory,
                'confirmed-binary-only.stamp')

        try:
            open(warning_stamp, 'a').close()
            self.exec_game()
        except:
            gui.text_view.get_buffer().set_text(traceback.format_exc())
            gui.check_box.hide()
            gui.ok_button.set_sensitive(False)

    def exec_game(self, _unused=None):
        self.exit_status = 69   # EX_UNAVAILABLE

        # Edit before copying, so that we can detect whether this is
        # the first run or not
        for ini, details in self.data.get('edit_unreal_ini', {}).items():
            target = os.path.join(self.dot_directory, ini)
            encoding = details.get('encoding', 'windows-1252')

            if os.path.exists(target):
                first_time = False
                try:
                    reader = open(target, encoding='utf-16')
                    reader.readline()
                except:
                    reader = open(target, encoding=encoding)
                else:
                    reader.seek(0)
            else:
                first_time = True

                if os.path.lexists(target):
                    logger.info('Removing dangling symlink %s', target)
                    os.remove(target)

                for base in self.base_directories:
                    source = os.path.join(base, ini)

                    if os.path.exists(source):
                        try:
                            reader = open(source, encoding='utf-16')
                            reader.readline()
                        except:
                            reader = open(source, encoding=encoding)
                        else:
                            reader.seek(0)
                        break
                else:
                    raise AssertionError('Required file %s not found', ini)

            if first_time:
                edits = details.get('once', []) + details.get('always', [])
            else:
                edits = details.get('always', [])

            logger.debug('%s', edits)
            editor = IniEditor(edits)

            with reader:
                editor.load(reader)

            d = os.path.dirname(target)

            if d:
                logger.info('Creating directory: %s', d)
                os.makedirs(d, exist_ok=True)

            with open(target, 'w', encoding=encoding,
                    newline=details.get('newline', '\n')) as writer:
                editor.save(writer)

        # Copy before linking, so that the copies will suppress symlink
        # creation
        for pattern in self.data.get('copy_into_dot_directory', ()):
            # copy from all base directories, highest priority first
            for base in self.base_directories:
                for f in glob.glob(os.path.join(base, pattern)):
                    assert f.startswith(base + '/')
                    target = os.path.join(self.dot_directory,
                            f[len(base) + 1:])
                    d = os.path.dirname(target)

                    if os.path.exists(target):
                        logger.debug('Already exists: %s', target)
                        continue

                    if d:
                        logger.info('Creating directory: %s', d)
                        os.makedirs(d, exist_ok=True)

                    logger.info('Copying %s -> %s', f, target)
                    shutil.copyfile(f, target)

        for subdir in self.data.get('symlink_into_dot_directory', ()):
            dot_subdir = os.path.join(self.dot_directory, subdir)
            logger.debug('symlinking ${each base directory}/%s/** as %s/**',
                    subdir, dot_subdir)
            # prune dangling symbolic links
            if os.path.exists(dot_subdir):
                logger.debug('checking %r for dangling symlinks',
                        dot_subdir)
                for dirpath, dirnames, filenames in os.walk(dot_subdir):
                    logger.debug('walking: %r %r %r', dirpath, dirnames,
                            filenames)
                    for filename in filenames:
                        logger.debug('checking whether %r is a dangling '
                                'symlink', filename)
                        f = os.path.join(dirpath, filename)

                    if not os.path.exists(f):
                        logger.info('Removing dangling symlink %s', f)
                        os.remove(f)

            # symlink in all base directories, highest priority first
            for base in self.base_directories:
                base_subdir = os.path.join(base, subdir)
                logger.debug('Searching for files to link in %s', base_subdir)
                for dirpath, dirnames, filenames in os.walk(base_subdir):
                    logger.debug('walking: %r %r %r', dirpath, dirnames,
                            filenames)
                    for filename in filenames:
                        logger.debug('ensuring that %s is symlinked in',
                                filename)

                        f = os.path.join(dirpath, filename)
                        logger.debug('%s', f)
                        assert f.startswith(base_subdir + '/')

                        target = os.path.join(dot_subdir,
                                f[len(base_subdir) + 1:])
                        d = os.path.dirname(target)

                        if os.path.exists(target):
                            logger.debug('Already exists: %s', target)
                            continue

                        if os.path.lexists(target):
                            logger.info('Removing dangling symlink %s', target)
                            os.remove(target)

                        if d:
                            logger.info('Creating directory: %s', d)
                            os.makedirs(d, exist_ok=True)

                        logger.info('Symlinking %s -> %s', f, target)
                        os.symlink(f, target)

        if self.working_directory is not None:
            os.chdir(self.working_directory)

        self.flush()

        environ = os.environ.copy()

        library_path = self.library_path[:]

        if 'LD_LIBRARY_PATH' in environ:
            library_path.append(environ['LD_LIBRARY_PATH'])

        environ['LD_LIBRARY_PATH'] = ':'.join(library_path)

        os.execve(self.argv[0], self.argv + self.args.arguments, environ)

        raise AssertionError('os.execve should never return')

    def load_text(self, filename, placeholder):
        for f in ('%s.%s' % (self.id, filename), filename):
            try:
                path = os.path.join(GDP_DIR, f)
                text = open(path).read()
            except OSError:
                pass
            else:
                text = string.Template(text).safe_substitute(
                        distro=DISTRO,
                        name=self.name,
                        )
                # strip single \n
                text = text.replace('\n\n', '\r\r').replace('\n', ' ')
                text = text.replace('\r', '\n')
                return text
        else:
            return placeholder

class Gui:
    def __init__(self, launcher):
        self.window = Gtk.Window()
        self.window.set_default_size(600, 300)
        self.window.connect('delete-event', Gtk.main_quit)
        self.window.set_title(launcher.name)
        self.window.set_icon_name(launcher.icon_name)

        self.grid = Gtk.Grid(row_spacing=6, column_spacing=6,
                margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.window.add(self.grid)

        image = Gtk.Image.new_from_icon_name(launcher.icon_name,
                Gtk.IconSize.DIALOG)
        image.set_valign(Gtk.Align.START)
        self.grid.attach(image, 0, 0, 1, 1)

        self.text_view = Gtk.TextView(editable=False, cursor_visible=False,
            hexpand=True, vexpand=True, wrap_mode=Gtk.WrapMode.WORD,
            top_margin=6, left_margin=6, right_margin=6, bottom_margin=6)
        self.grid.attach(self.text_view, 1, 0, 1, 1)

        subgrid = Gtk.Grid(column_spacing=6, column_homogeneous=True,
                halign=Gtk.Align.END)

        cancel_button = Gtk.Button.new_with_label('Cancel')
        cancel_button.connect('clicked', Gtk.main_quit)
        subgrid.attach(cancel_button, 0, 0, 1, 1)

        self.check_box = Gtk.CheckButton.new_with_label("I'll be careful")
        self.check_box.set_hexpand(True)
        self.grid.attach(self.check_box, 0, 1, 2, 1)

        self.ok_button = Gtk.Button.new_with_label('Run')
        self.ok_button.set_sensitive(False)
        subgrid.attach(self.ok_button, 1, 0, 1, 1)

        self.grid.attach(subgrid, 0, 2, 2, 1)

        self.window.show_all()

if __name__ == '__main__':
    Launcher().main()
