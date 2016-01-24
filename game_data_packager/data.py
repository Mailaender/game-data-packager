#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2016 Simon McVittie <smcv@debian.org>
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
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

import hashlib
import io

class ProgressCallback:
    """API for a progress report."""

    def __call__(self, done, total=None, checkpoint=False):
        """Update progress: we have done @done bytes out of @total
        (None if unknown).

        If @checkpoint is True, it is a hint that this particular
        update is important (for instance the end of a file).
        """
        pass

    def __enter__(self):
        return self

    def __exit__(self, et=None, ev=None, tb=None):
        pass

class HashedFile:
    def __init__(self, name):
        self.name = name
        self._md5 = None
        self._sha1 = None
        self._sha256 = None
        self.skip_hash_matching = False

    @classmethod
    def from_file(cls, name, f, write_to=None, size=None, progress=None):
        return cls.from_concatenated_files(name, [f], write_to, size, progress)

    @classmethod
    def from_concatenated_files(cls, name, fs, write_to=None, size=None,
            progress=None):
        md5 = hashlib.new('md5')
        sha1 = hashlib.new('sha1')
        sha256 = hashlib.new('sha256')
        done = 0

        with (progress or ProgressCallback()) as update_progress:
            for f in fs:
                while True:
                    update_progress(done, size)

                    blob = f.read(io.DEFAULT_BUFFER_SIZE)

                    if not blob:
                        update_progress(done, size, checkpoint=True)
                        break

                    done += len(blob)

                    md5.update(blob)
                    sha1.update(blob)
                    sha256.update(blob)
                    if write_to is not None:
                        write_to.write(blob)

        self = cls(name)
        self.md5 = md5.hexdigest()
        self.sha1 = sha1.hexdigest()
        self.sha256 = sha256.hexdigest()
        return self

    @property
    def have_hashes(self):
        return ((self.md5 is not None) or
                (self.sha1 is not None) or
                (self.sha256 is not None))

    def matches(self, other):
        matched = False

        if self.skip_hash_matching or other.skip_hash_matching:
            return False

        if None not in (self.md5, other.md5):
            matched = True
            if self.md5 != other.md5:
                return False

        if None not in (self.sha1, other.sha1):
            matched = True
            if self.sha1 != other.sha1:
                return False

        if None not in (self.sha256, other.sha256):
            matched = True
            if self.sha256 != other.sha256:
                return False

        if not matched:
            raise ValueError(('Unable to determine whether checksums match:\n' +
                        '%s has:\n' +
                        '  md5:    %s\n' +
                        '  sha1:   %s\n' +
                        '  sha256: %s\n' +
                        '%s has:\n' +
                        '  md5:    %s\n' +
                        '  sha1:   %s\n' +
                        '  sha256: %s\n') % (
                        self.name,
                        self.md5,
                        self.sha1,
                        self.sha256,
                        other.name,
                        other.md5,
                        other.sha1,
                        other.sha256))

        return True

    @property
    def md5(self):
        return self._md5
    @md5.setter
    def md5(self, value):
        if self._md5 is not None and value != self._md5:
            raise AssertionError('trying to set md5 of "%s" to both %s '
                    + 'and %s', self.name, self._md5, value)
        self._md5 = value

    @property
    def sha1(self):
        return self._sha1
    @sha1.setter
    def sha1(self, value):
        if self._sha1 is not None and value != self._sha1:
            raise AssertionError('trying to set sha1 of "%s" to both %s '
                    + 'and %s', self.name, self._sha1, value)
        self._sha1 = value

    @property
    def sha256(self):
        return self._sha256
    @sha256.setter
    def sha256(self, value):
        if self._sha256 is not None and value != self._sha256:
            raise AssertionError('trying to set sha256 of "%s" to both %s '
                    + 'and %s', self.name, self._sha256, value)
        self._sha256 = value

class WantedFile(HashedFile):
    def __init__(self, name):
        super(WantedFile, self).__init__(name)
        self.alternatives = []
        self.doc = False
        self.group_members = None
        self._depends = set()
        self._distinctive_name = None
        self.distinctive_size = False
        self.download = None
        self.executable = False
        self.filename = name.split('?')[0]
        self.install_as = self.filename
        self._install_to = None
        self.license = False
        self._look_for = None
        self._provides = set()
        self.provides_files = None
        self._size = None
        self.unpack = None
        self.unsuitable = None

    def apply_group_attributes(self, attributes):
        for k, v in attributes.items():
            assert hasattr(self, k)
            setattr(self, k, v)

    @property
    def distinctive_name(self):
        if self._distinctive_name is not None:
            return self._distinctive_name
        return not self.license
    @distinctive_name.setter
    def distinctive_name(self, value):
        self._distinctive_name = value

    @property
    def install_to(self):
        if self._install_to is not None:
            return self._install_to
        if self.doc:
            return '$pkgdocdir'
        if self.license:
            return '$pkglicensedir'
        return None
    @install_to.setter
    def install_to(self, value):
        self._install_to = value

    @property
    def look_for(self):
        if self.alternatives:
            return set([])
        if self._look_for is not None:
            return self._look_for
        return set([self.filename.lower(), self.install_as.lower()])
    @look_for.setter
    def look_for(self, value):
        self._look_for = set(x.lower() for x in value)

    @property
    def size(self):
        return self._size
    @size.setter
    def size(self, value):
        if self._size is not None and value != self._size:
            raise AssertionError('trying to set size of "%s" to both %d '
                    + 'and %d', self.name, self._size, value)
        self._size = int(value)

    @property
    def provides(self):
        return self._provides
    @provides.setter
    def provides(self, value):
        self._provides = set(value)

    def to_yaml(self, expand=True):
        ret = {
            'name': self.name,
        }

        for k in (
                'alternatives',
                'distinctive_size',
                'executable',
                'license',
                'skip_hash_matching',
                ):
            v = getattr(self, k)
            if v:
                if isinstance(v, set):
                    ret[k] = sorted(v)
                else:
                    ret[k] = v

        if expand:
            if self.provides_files:
                ret['provides'] = sorted(f.name for f in self.provides_files)
        else:
            if self.provides:
                ret['provides'] = sorted(self.provides)

        for k in (
                'download',
                'group_members',
                'install_as',
                'size',
                'unsuitable',
                'unpack',
                ):
            v = getattr(self, k)
            if v is not None:
                if isinstance(v, set):
                    ret[k] = sorted(v)
                else:
                    ret[k] = v

        for k in (
                'distinctive_name',
                'install_to',
                'look_for',
                ):
            if expand:
                # use derived value
                v = getattr(self, k)
            else:
                v = getattr(self, '_' + k)

            if v is not None:
                if isinstance(v, set):
                    ret[k] = sorted(v)
                else:
                    ret[k] = v

        return ret