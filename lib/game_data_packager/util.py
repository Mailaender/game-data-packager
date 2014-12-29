#!/usr/bin/python3
# vim:set fenc=utf-8:
#
# Copyright © 2014 Simon McVittie <smcv@debian.org>
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

import os

class TemporaryUmask(object):
    """Context manager to set the umask. Not thread-safe.

    Use like this::

        with TemporaryUmask(0o022):
            os.makedirs('usr/share/misc')
    """

    def __init__(self, desired_mask):
        self.desired_mask = desired_mask
        self.saved_mask = None

    def __enter__(self):
        self.saved_mask = os.umask(self.desired_mask)

    def __exit__(self, et, ev, tb):
        os.umask(self.saved_mask)
