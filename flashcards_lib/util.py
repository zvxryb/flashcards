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

from __future__ import annotations

from typing import Optional, Generator
import unicodedata

from functools import reduce

def char_width(c: str) -> int:
    if c in ('\N{ZWSP}',):
        return 0
    w = unicodedata.east_asian_width(c)
    return 2 if w in ('F', 'W') else 1

def unicode_width(s: str) -> int:
    return reduce(lambda w, c: w + char_width(c), s, 0)

def unicode_ljust(s: str, width: int) -> str:
    n = width - unicode_width(s)
    return s + ' '*n

def unicode_center(s: str, width: int) -> str:
    n = width - unicode_width(s)
    n0 = n // 2
    n1 = n - n0
    return ' '*n0 + s + ' '*n1

class StringMask:
    __slots__ = 'bits'

    bits: int

    def __init__(self, bits: int = 0):
        self.bits = bits

    def __getitem__(self, key: int) -> bool:
        return self.bits & (1 << key) != 0

    def __setitem__(self, key: int, value: bool):
        if value:
            self.bits |= 1 << key
        else:
            self.bits &= ~(1 << key)

    def __invert__(self) -> StringMask:
        return StringMask(~self.bits)

    # lshift and rshift are "backwards" because they represent direction
    # of (left-to-right) character shift, not bits
    def __lshift__(self, other: int) -> StringMask:
        return StringMask(self.bits >> other)
    def __rshift__(self, other: int) -> StringMask:
        return StringMask(self.bits << other)

    def __not__(self) -> StringMask:
        return StringMask(~self.bits)

    def __and__(self, other: StringMask) -> StringMask:
        return StringMask(self.bits & other.bits)

    def __or__(self, other: StringMask) -> StringMask:
        return StringMask(self.bits | other.bits)

    def __iand__(self, other: StringMask) -> StringMask:
        self.bits &= other.bits
        return self

    def __ior__(self, other: StringMask) -> StringMask:
        self.bits |= other.bits
        return self

    def extend(self, gen: Generator[bool, None, None]):
        for i, bit in enumerate(gen):
            self[i] = bit

    @staticmethod
    def collect(gen: Generator[bool, None, None]) -> StringMask:
        mask = StringMask()
        mask.extend(gen)
        return mask

def is_breaking_space(c: str, cat: Optional[str] = None):
    if cat is None:
        cat = unicodedata.category(c)
    return cat == 'Zs' and c != '\N{NBSP}' or c == '\N{ZWSP}'

def is_breaking_hyphen(c: str, cat: Optional[str] = None):
    if cat is None:
        cat = unicodedata.category(c)
    return cat == 'Pd' and c != '\N{NON-BREAKING HYPHEN}'

def is_inner_punctuation(cat: str) -> bool:
    return cat in ('Pc', 'Po')

def is_starting_punctuation(cat: str) -> bool:
    return cat in ('Ps', 'Pi')

def is_ending_punctuation(cat: str) -> bool:
    return cat in ('Pd', 'Pe', 'Pf')

def line_break_opportunities(s: str) -> StringMask:
    cats = [unicodedata.category(c) for c in s]
    breaking_spaces = StringMask.collect(
        is_breaking_space(c, cat)
        for c, cat in zip(s, cats))
    breaking_hyphens = StringMask.collect(
        is_breaking_hyphen(c, cat)
        for c, cat in zip(s, cats))
    cjk_ideograms = StringMask.collect(
        (c >=     '\u3200' and c <=     '\u9fff') or
        (c >= '\U00020000' and c <= '\U0002ffff')
        for c in s)
    kana = StringMask.collect(c >= '\u3040' and c <= '\u30ff' for c in s)
    punctuation_inner  = StringMask.collect(is_inner_punctuation   (cat) for cat in cats)
    punctuation_before = StringMask.collect(is_starting_punctuation(cat) for cat in cats)
    punctuation_after  = StringMask.collect(is_ending_punctuation  (cat) for cat in cats)
    modifier = StringMask.collect(cat == 'Sk' for cat in cats)

    maybe_break_after = StringMask()
    maybe_break_after |= breaking_spaces
    maybe_break_after |= breaking_hyphens
    maybe_break_after |= cjk_ideograms
    maybe_break_after |= cjk_ideograms << 1
    maybe_break_after |= kana
    maybe_break_after |= kana << 1

    maybe_break_after &= ~punctuation_inner
    maybe_break_after &= ~(punctuation_inner << 1)
    maybe_break_after &= ~punctuation_before
    maybe_break_after &= ~(punctuation_after << 1)
    maybe_break_after &= ~(modifier << 1)

    return maybe_break_after