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

import ctypes, logging, sys, time
from ctypes.wintypes import DWORD
from msvcrt import getwch, kbhit # type: ignore
from typing import Callable, List, Optional, Tuple, Union

LOG = logging.getLogger(__name__)

Box = Tuple[int, int, int, int]

import flashcards_lib.markup as markup
from flashcards_lib.ansi_esc import *
from flashcards_lib.util import char_width, unicode_width, line_break_opportunities

STD_OUTPUT_HANDLE = -11
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 4

kernel32 = ctypes.windll.kernel32

class WinAnsiMode:
    __slots__ = 'outdev', 'mode'

    def __enter__(self):
        self.outdev = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        self.mode   = DWORD()
        if not kernel32.GetConsoleMode(self.outdev, ctypes.pointer(self.mode)):
            raise Exception("failed to get console mode")
        kernel32.SetConsoleMode(self.outdev, self.mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)

    def __exit__(self, type, value, tb):
        kernel32.SetConsoleMode(self.outdev, self.mode)

ASCII_BACKSPACE = '\x08'
ASCII_ESC    = '\x1b'
MS_KEY_ESC0  = '\x00'
MS_KEY_ESC1  = '\xe0'
MS_KEY_UP    = '\x48'
MS_KEY_LEFT  = '\x4b'
MS_KEY_RIGHT = '\x4d'
MS_KEY_DOWN  = '\x50'
MS_KEY_HOME  = '\x47'
MS_KEY_END   = '\x4f'
MS_KEY_PAGE_UP   = '\x49'
MS_KEY_PAGE_DOWN = '\x51'

class Formatter:
    __slots__ = (
        '__row',
        '__col',
        '__rows',
        '__cols',
        '__center_h',
        '__center_v',
        '__style',
        '__text',
        '__modified',
        '__lines',
        '__error_ranges')

    __lines: List[Tuple[int, int, int]]
    __error_ranges: List[Tuple[int, bool]]

    def __init__(self,
        row: int,
        col: int,
        rows: int,
        cols: int,
        center_h: bool,
        center_v: bool,
        style: str = ''
    ):
        self.__row = row
        self.__col = col
        self.__rows = rows
        self.__cols = cols
        self.__center_h = center_h
        self.__center_v = center_v
        self.__style = style
        self.__error_ranges = []
        self.text = ''

    @property
    def text(self) -> str:
        return self.__text

    @text.setter
    def text(self, text: str):
        self.__text = text
        self.__modified = True

    @property
    def style(self) -> str:
        return self.__style

    @style.setter
    def style(self, style: str):
        self.__style = style

    @property
    def lines(self) -> List[Tuple[int, int, int]]:
        if not self.__modified:
            return self.__lines

        self.__modified = False
        self.__lines = []

        line_start = 0
        line_end   = 0
        line_break = 0
        line_width = 0

        maybe_break_after = line_break_opportunities(self.__text)
        while line_start < len(self.__text):
            line_end = line_start + 1
            while line_end < len(self.__text):
                c0 = self.__text[line_end-1]
                c1 = self.__text[line_end]
                if c0 in ('\u000a', '\u000b', '\u000c', '\u0085', '\u2028', '\u2029'):
                    break
                if c0 == '\u000d' and c1 != '\u000a':
                    break

                if maybe_break_after[line_end-1]:
                    line_break = line_end

                w = char_width(c0)
                if line_width + w >= self.__cols:
                    if line_break > line_start:
                        line_end = line_break
                    break

                line_end += 1
                line_width += w

            self.__lines.append((line_start, line_end, unicode_width(self.__text[line_start:line_end])))
            line_start = line_end
            line_width = 0

        return self.__lines

    @property
    def error_ranges(self) -> List[Tuple[int, bool]]:
        return self.__error_ranges

    def set_error_ranges(self, errors: List[Tuple[int, int]]):
        LOG.info('formatter error_ranges input %s', errors)
        self.__error_ranges = [
            *((start, True ) for start, end in errors),
            *((end  , False) for start, end in errors)]
        self.__error_ranges.sort(key = lambda error: error[0])
        LOG.info('formatter error_ranges result %s', self.__error_ranges)

    def local_cursor_pos(self, index: int) -> Tuple[int, int, int]:
        line, char, line_cols = 0, 0, 0
        for i, (start, end, width) in enumerate(self.lines):
            line = i
            line_cols = width
            if index <= end:
                char = unicode_width(self.__text[start : index])
                break
            char = width
        return line, char, line_cols

    def global_cursor_pos(self, index: int) -> Tuple[int, int]:
        n = len(self.lines)
        row, col, m = self.local_cursor_pos(index)

        row_offset = 0
        if self.__center_v and self.__rows > n:
            row_offset = (self.__rows - n)//2

        out_row = row + row_offset
        if out_row < 0:
            out_row = 0
            out_col = 0
        elif out_row >= self.__rows:
            out_row = self.__rows
            out_col = self.__cols
        elif self.__center_h:
            out_col = col + (self.__cols - m)//2
        else:
            out_col = col

        out_row += self.__row
        out_col += self.__col

        return out_row, out_col

    def redraw(self):
        sys.stdout.write(ANSI_SAVE + self.style)

        n = len(self.lines)

        row_offset = 0
        if self.__center_v and self.__rows > n:
            row_offset = (self.__rows - n)//2

        error_index = 0
        error_depth = 0
        for i in range(self.__rows):
            sys.stdout.write(ansi_pos(self.__row + i, self.__col))

            j = i - row_offset
            if j < 0 or j >= n:
                sys.stdout.write(' ' * self.__cols)
                continue

            start, end, width = self.lines[j]

            if self.__center_h:
                lpad = (self.__cols - width) // 2
            else:
                lpad = 0
            rpad = self.__cols - lpad - width

            sys.stdout.write(' '*lpad)
            if error_depth > 0:
                sys.stdout.write(ANSI_RED + ANSI_UNDERLINE)

            while error_index < len(self.error_ranges):
                k, is_error_start = self.error_ranges[error_index]
                if k >= end:
                    break

                error_index += 1

                sys.stdout.write(self.__text[start:k])
                start = k

                if is_error_start:
                    error_depth += 1
                    if error_depth == 1:
                        sys.stdout.write(ANSI_RED + ANSI_UNDERLINE)
                else:
                    error_depth -= 1
                    if error_depth == 0:
                        sys.stdout.write(ANSI_RESET + self.style)

            sys.stdout.write(self.__text[start:end])
            if error_depth > 0:
                sys.stdout.write(ANSI_RESET + self.style)
            sys.stdout.write(' '*rpad)

        if self.__rows < n:
            m = min(self.__cols, 3)
            sys.stdout.write(
                ansi_pos(
                    self.__row + self.__rows - 1,
                    self.__col + self.__cols - m
                ) + '.'*m)

        sys.stdout.write(ANSI_RESET + ANSI_RESTORE)
        sys.stdout.flush()

class MarkupDrawer:
    __slots__ = (
        '__row',
        '__col',
        '__rows',
        '__cols',
        '__center_h',
        '__center_v',
        '__text',
        '__modified',
        '__draw_list',
        '__quirks',
        'style')

    __draw_list: List[markup.Text]
    __quirks: List[Tuple[str, Optional[str], Optional[Tuple[int, int]]]]

    def __init__(self,
        row: int,
        col: int,
        rows: int,
        cols: int,
        center_h: bool,
        center_v: bool
    ):
        self.__row = row
        self.__col = col
        self.__rows = rows
        self.__cols = cols
        self.__center_h = center_h
        self.__center_v = center_v
        self.text = ''
        self.style = ''

    @property
    def text(self) -> str:
        return self.__text

    @text.setter
    def text(self, text: str):
        self.__text = text
        self.__modified = True
        self.__draw_list = []
        self.__quirks = []

    def __update(self):
        if not self.__modified:
            return

        self.__modified = False

        tokens = markup.tokenize(self.__text)
        tokens = markup.normalize(tokens)
        self.__quirks, group = markup.layout(tokens, self.__cols, self.__center_h)

        x_offset = 0
        y_offset = self.__rows - group.box.height
        if self.__center_h:
            x_offset = (self.__cols - group.box.width) // 2
        if self.__center_v:
            y_offset = (self.__rows - group.box.height - 1) // 2 + 1

        self.__draw_list = [
            markup.Text(item.x + x_offset, item.y + y_offset, item.text)
            for item in group.items if 0 <= item.y + y_offset < self.__rows]

    @property
    def draw_list(self) -> List[markup.Text]:
        self.__update()
        return self.__draw_list

    @property
    def error_ranges(self) -> List[Tuple[int, int]]:
        self.__update()
        return [range_ for description, scope, range_ in self.__quirks if scope is None and range_]

    def redraw(self):
        sys.stdout.write(ANSI_SAVE + self.style)
        for row in range(self.__rows):
            sys.stdout.write(ansi_pos(row + self.__row, self.__col) + ' ' * self.__cols)
        for item in self.draw_list:
            row = self.__row + self.__rows - item.y - 1
            col = self.__col + item.x
            sys.stdout.write(ansi_pos(row, col) + item.text)
        sys.stdout.write(ANSI_RESTORE + ANSI_RESET)
        sys.stdout.flush()

class Input:
    class Event:
        __slots__ = ()

    UNFOCUS   = Event()
    KEY_UP    = Event()
    KEY_DOWN  = Event()
    PAGE_UP   = Event()
    PAGE_DOWN = Event()
    TAB       = Event()
    TIMEOUT   = Event()

    __slots__ = '__text', 'cursor', 'formatter'

    def __init__(self, box: Box):
        self.__text       = u''
        self.cursor      = 0
        self.formatter   = Formatter(*box, False, False)

    def update_cursor(self):
        self.formatter.text = self.__text
        row, col = self.formatter.global_cursor_pos(self.cursor)
        sys.stdout.write(ansi_pos(row, col))

    def redraw_input(self):
        self.formatter.text = self.__text
        self.formatter.redraw()

    def focus(self):
        self.formatter.style = ANSI_REVERSE
        self.redraw_input()
        sys.stdout.flush()

    def unfocus(self):
        self.formatter.style = ''
        self.redraw_input()
        sys.stdout.flush()

    @property
    def text(self) -> str:
        return self.__text

    @text.setter
    def text(self, text: str):
        self.__text = text
        if self.cursor > len(text):
            self.cursor = len(text)
            self.update_cursor()

    def get_input(self,
        timeout_s: Optional[float] = None,
        on_timeout: Optional[Callable[[str], bool]] = None
    ) -> Union[Event, str]:
        self.focus()
        last_key_s: Optional[float] = None
        while True:
            if timeout_s is not None:
                time.sleep(0.0001)
                time_s = time.perf_counter()
                if kbhit():
                    last_key_s = time_s
                    result = self.process_char()
                    if result is not None:
                        return result
                elif last_key_s is not None and time_s > last_key_s + timeout_s:
                    assert on_timeout is not None
                    if on_timeout(self.text):
                        return Input.TIMEOUT
                    last_key_s = None
            else:
                result = self.process_char()
                if result is not None:
                    return result

    def process_char(self) -> Optional[Union[Event, str]]:
        char = getwch()
        if char == ASCII_ESC:
            self.unfocus()
            return Input.UNFOCUS
        elif char == '\x03' or char == '\x04':
            self.unfocus()
            raise KeyboardInterrupt()
        elif char == '\t':
            self.unfocus()
            return Input.TAB
        elif char == '\n':
            pass
        elif char == '\r':
            result = self.text
            self.text = ''
            self.update_cursor()
            self.redraw_input()
            sys.stdout.flush()
            return result
        elif char == ASCII_BACKSPACE:
            if self.cursor > 0:
                self.cursor -= 1
                self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]
                self.update_cursor()
                self.redraw_input()
        elif char == MS_KEY_ESC0 or char == MS_KEY_ESC1:
            char2 = getwch()
            if char2 == MS_KEY_UP:
                self.unfocus()
                return Input.KEY_UP
            elif char2 == MS_KEY_DOWN:
                self.unfocus()
                return Input.KEY_DOWN
            elif char2 == MS_KEY_PAGE_UP:
                self.unfocus()
                return Input.PAGE_UP
            elif char2 == MS_KEY_PAGE_DOWN:
                self.unfocus()
                return Input.PAGE_DOWN
            elif char2 == MS_KEY_LEFT or char2 == MS_KEY_RIGHT:
                if char2 == MS_KEY_LEFT:
                    if self.cursor > 0:
                        self.cursor -= 1
                        self.update_cursor()
                else:
                    if self.cursor < len(self.text):
                        self.cursor += 1
                        self.update_cursor()
            elif char2 == MS_KEY_HOME:
                self.cursor = 0
                self.update_cursor()
            elif char2 == MS_KEY_END:
                self.cursor = len(self.text)
                self.update_cursor()
        else:
            if self.cursor < len(self.text):
                self.text = self.text[:self.cursor] + char + self.text[self.cursor:]
            else:
                self.text += char
            self.cursor += 1
            self.update_cursor()
            self.redraw_input()
        sys.stdout.flush()
        return None