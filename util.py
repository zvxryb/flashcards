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

class StringMask:
    __slots__ = 'bits'

    def __init__(self, bits=0):
        self.bits = bits

    def __getitem__(self, key):
        return self.bits & (1 << key) != 0

    def __setitem__(self, key, value):
        if value:
            self.bits |= 1 << key
        else:
            self.bits &= ~(1 << key)

    def __invert__(self):
        return StringMask(~self.bits)

    # lshift and rshift are "backwards" because they represent direction
    # of (left-to-right) character shift, not bits
    def __lshift__(self, other):
        return StringMask(self.bits >> other)
    def __rshift__(self, other):
        return StringMask(self.bits << other)

    def __not__(self, other):
        return StringMask(~self.bits)

    def __and__(self, other):
        return StringMask(self.bits & other.bits)

    def __or__(self, other):
        return StringMask(self.bits | other.bits)

    def __iand__(self, other):
        self.bits &= other.bits
        return self

    def __ior__(self, other):
        self.bits |= other.bits
        return self

    def extend(self, gen):
        for i, bit in enumerate(gen):
            self[i] = bit

    @classmethod
    def collect(cls, gen):
        mask = cls()
        mask.extend(gen)
        return mask

def line_break_opportunities(s):
    cats = [unicodedata.category(c) for c in s]
    breaking_spaces = StringMask.collect(
        (cat == 'Zs' and c != '\N{NBSP}') or c == '\N{ZWSP}'
        for c, cat in zip(s, cats))
    breaking_hyphens = StringMask.collect(
        (cat == 'Pd' and c != '\N{NON-BREAKING HYPHEN}')
        for c, cat in zip(s, cats))
    cjk_ideograms = StringMask.collect(
        (c >=     '\u3200' and c <=     '\u9fff') or
        (c >= '\U00020000' and c <= '\U0002ffff')
        for c in s)
    kana = StringMask.collect(c >= '\u3040' and c <= '\u30ff' for c in s)
    punctuation_before = StringMask.collect(cat in ('Pc', 'Ps', 'Pi', 'Po')       for cat in cats)
    punctuation_after  = StringMask.collect(cat in ('Pc', 'Pd', 'Pe', 'Pf', 'Po') for cat in cats)
    modifier = StringMask.collect(cat == 'Sk' for cat in cats)

    maybe_break_after = StringMask()
    maybe_break_after |= breaking_spaces
    maybe_break_after |= breaking_hyphens
    maybe_break_after |= cjk_ideograms
    maybe_break_after |= cjk_ideograms << 1
    maybe_break_after |= kana
    maybe_break_after |= kana << 1

    maybe_break_after &= ~punctuation_before
    maybe_break_after &= ~(punctuation_after << 1)
    maybe_break_after &= ~(modifier << 1)

    return maybe_break_after