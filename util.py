# Copyright 2020 Michael Lodato <zvxryb@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import unicodedata

from functools import reduce

def char_width(c):
    w = unicodedata.east_asian_width(c)
    return 2 if w in ('A', 'F', 'W') else 1

def unicode_width(s):
    return reduce(lambda w, c: w + char_width(c), s, 0)

def unicode_ljust(s, width):
    n = width - unicode_width(s)
    return s + ' '*n

def unicode_center(s, width):
    n = width - unicode_width(s)
    n0 = n // 2
    n1 = n - n0
    return ' '*n0 + s + ' '*n1