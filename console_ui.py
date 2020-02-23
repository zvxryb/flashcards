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

import codecs, ctypes, msvcrt, re, sys, unicodedata
from ctypes.wintypes import DWORD
from textwrap import TextWrapper
from typing import Any, Callable, List, Optional, Tuple, Union

Box = Tuple[int, int, int, int]

from util import char_width, unicode_width, unicode_ljust, unicode_center, line_break_opportunities

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

def getwch() -> str:
    return msvcrt.getwch()

ANSI_CLEAR   = '\033[H\033[J'
ANSI_RESET   = '\033[0m'
ANSI_UP      = '\033[A'
ANSI_DOWN    = '\033[B'
ANSI_FORWARD = '\033[C'
ANSI_BACK    = '\033[D'
ANSI_REVERSE = '\033[7m'
ANSI_RED     = '\033[31m'
ANSI_GREEN   = '\033[32m'
ANSI_CYAN    = '\033[36m'
ANSI_WHITE   = '\033[37m'
ANSI_SAVE    = '\033[s'
ANSI_RESTORE = '\033[u'

def ansi_pos(row: int, col: int) -> str:
    return f'\033[{row};{col}H'

def ansi_col(col: int) -> str:
    return f'\033[{col}G'

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

class TestResult:
    __slots__ = ()

RESULT_PASS = TestResult()
RESULT_FAIL = TestResult()

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
        '__lines')

    __lines: List[Tuple[int, int, int]]

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
        out = ANSI_SAVE + self.style

        n = len(self.lines)

        row_offset = 0
        if self.__center_v and self.__rows > n:
            row_offset = (self.__rows - n)//2

        for i in range(self.__rows):
            out += ansi_pos(self.__row + i, self.__col)

            j = i - row_offset
            if j < 0 or j >= n:
                out += ' ' * self.__cols
                continue

            start, end, width = self.lines[j]

            if self.__center_h:
                lpad = (self.__cols - width) // 2
            else:
                lpad = 0
            rpad = self.__cols - lpad - width

            line = ' '*lpad + self.__text[start:end] + ' '*rpad
            if i == self.__rows - 1 and i < n - 1:
                line = line[:-3] + '...'
            out += line

        out += ANSI_RESET + ANSI_RESTORE
        sys.stdout.write(out)

class HistoryData:
    __slots__ = 'id', 'modified', 'result', 'question', 'expected', 'answered'

    def __init__(self,
        id: Any = None,
        result: Optional[TestResult] = None,
        question: str = '',
        expected: str = '',
        answered: str = ''
    ):
        self.id       = id
        self.modified = False
        self.result   = result
        self.question = question
        self.expected = expected
        self.answered = answered

class HistoryForm:
    __slots__ = 'result', 'question', 'expected', 'answered'

    def __init__(self,
        result  : Box,
        question: Box,
        expected: Box,
        answered: Box
    ):
        self.result   = Formatter(*result  , True , True )
        self.question = Formatter(*question, False, False)
        self.expected = Formatter(*expected, False, False)
        self.answered = Formatter(*answered, False, False)

    def update_result(self, result: Optional[TestResult], highlight: bool):
        if result is None:
            self.result.style = ''
            self.result.text  = ''
        elif result == RESULT_PASS:
            self.result.style = ANSI_GREEN
            self.result.text  = u'\u2713 Right'
        elif result == RESULT_FAIL:
            self.result.style = ANSI_RED
            self.result.text  = u'\u2717 Wrong'

        if highlight:
            self.result.style += ANSI_REVERSE

        self.result.redraw()

    def update_question(self, text: str):
        self.question.text = text
        self.question.redraw()

    def update_expected(self, text: str):
        self.expected.text = text
        self.expected.redraw()

    def update_answered(self, text: str):
        self.answered.text = text
        self.answered.redraw()

    def update(self, data: HistoryData, highlight: bool):
        self.update_result(data.result, highlight)
        self.update_question((f'{data.id}: ' + data.question) if data.question else '')
        self.update_expected(data.expected)
        self.update_answered(data.answered)

HISTORY_FORMS = (
    HistoryForm(( 21, 3, 1, 9), (16, 14, 2, 104), (18, 14, 2, 104), (20, 14, 2, 104)),
    HistoryForm(( 14, 3, 1, 9), ( 9, 14, 2, 104), (11, 14, 2, 104), (13, 14, 2, 104)),
    HistoryForm((  7, 3, 1, 9), ( 2, 14, 2, 104), ( 4, 14, 2, 104), ( 6, 14, 2, 104)))

QUESTION_BOX = (23, 3, 3, 115)
NUMBER_BOX   = (22, 3, 1,   2)
TOTAL_BOX    = (22, 6, 1,   2)
ANSWER_BOX   = (27, 3, 2, 115)

class Display:
    selected: Optional[int]

    def __init__(self, on_submit: Callable[[str], None], on_revise: Callable[[Any, TestResult], None]):
        self.answer    = Input(ANSWER_BOX)
        self.history   = [HistoryData() for _ in HISTORY_FORMS]
        self.question_formatter = Formatter(*QUESTION_BOX, True , True )
        self.selected  = None
        self.on_submit = on_submit
        self.on_revise = on_revise

        sys.stdout.write(ANSI_CLEAR + ANSI_RESET)

        with codecs.open('ui_utf8.txt', 'r', 'utf-8') as f:
            sys.stdout.write(f.read())

        sys.stdout.write(ansi_pos(ANSWER_BOX[0], ANSWER_BOX[1]))
        sys.stdout.flush()

    def __del__(self):
        sys.stdout.write(ansi_col(0) + ANSI_DOWN * 3)
        sys.stdout.flush()

    def redraw_history(self):
        for i, (form, data) in enumerate(zip(HISTORY_FORMS, self.history)):
            form.update(data, i == self.selected)

    def clear_history(self):
        self.history = [HistoryData() for _ in HISTORY_FORMS]
        self.redraw_history()

    def push_history(self, id: Any, result: TestResult, question: str, expected: str, answered: str):
        item = HistoryData(id, result, question, expected, answered)
        self.history = [item] + self.history[:len(HISTORY_FORMS)-1]
        self.redraw_history()

    def update_question(self, question: str, number: Union[int, str], total: Union[int, str]):
        number = str(number)
        if len(number) > NUMBER_BOX[3]:
            number = '#' * NUMBER_BOX[3]
        else:
            number = number.rjust(NUMBER_BOX[3])

        total = str(total)
        if len(total) > TOTAL_BOX[3]:
            total = '#' * TOTAL_BOX[3]
        else:
            total = total.rjust(TOTAL_BOX[3])

        sys.stdout.write(
            ANSI_SAVE +
            ansi_pos(NUMBER_BOX[0], NUMBER_BOX[1]) + number +
            ansi_pos(TOTAL_BOX [0], TOTAL_BOX [1]) + total  +
            ANSI_RESTORE)

        self.question_formatter.text = question
        self.question_formatter.redraw()

    def set_selected(self, selected: Optional[int]):
        if self.selected is not None:
            history_data = self.history[self.selected]
            if history_data.modified:
                history_data.modified = False
                assert history_data.result is not None
                self.on_revise(history_data.id, history_data.result)
            HISTORY_FORMS[self.selected].update_result(history_data.result, False)

        self.selected = selected

        if self.selected is not None:
            history_data = self.history[self.selected]
            HISTORY_FORMS[self.selected].update_result(history_data.result, True)

    def select_item(self, up: bool):
        n = len(HISTORY_FORMS)
        if up:
            if self.selected is None:
                self.set_selected(0)
            elif self.selected < n - 1:
                self.set_selected(self.selected + 1)
            else:
                self.set_selected(None)
        else:
            if self.selected is None:
                self.set_selected(n - 1)
            elif self.selected > 0:
                self.set_selected(self.selected - 1)
            else:
                self.set_selected(None)

    def toggle_item(self):
        if self.selected is None:
            return
        history_data = self.history[self.selected]
        if history_data.result is None:
            return
        if history_data.result == RESULT_PASS:
            history_data.result = RESULT_FAIL
        else:
            history_data.result = RESULT_PASS
        history_data.modified = True
        HISTORY_FORMS[self.selected].update_result(history_data.result, True)

    def main(self) -> int:
        while True:
            if self.selected is None:
                event_or_input = self.answer.get_input()
                if isinstance(event_or_input, str):
                    self.on_submit(event_or_input)
                elif event_or_input == Input.UNFOCUS:
                    return 0
                elif event_or_input == Input.KEY_UP:
                    self.select_item(True)
                elif event_or_input == Input.KEY_DOWN:
                    self.select_item(False)
            else:
                char = getwch()
                if char == ASCII_ESC:
                    self.set_selected(None)
                elif char == '\x03' or char == '\x04':
                    raise KeyboardInterrupt()
                elif char == MS_KEY_ESC0 or char == MS_KEY_ESC1:
                    char2 = getwch()
                    if char2 == MS_KEY_UP or char2 == MS_KEY_DOWN:
                        self.select_item(char2 == MS_KEY_UP)
                elif char == ' ':
                    self.toggle_item()
                    self.set_selected(None)
            sys.stdout.flush()

class Input:
    class Event:
        __slots__ = ()

    UNFOCUS  = Event()
    KEY_UP   = Event()
    KEY_DOWN = Event()

    def __init__(self, box: Box):
        self.input     = u''
        self.cursor    = 0
        self.formatter = Formatter(*box, False, False)

    def update_cursor(self):
        self.formatter.text = self.input
        row, col = self.formatter.global_cursor_pos(self.cursor)
        sys.stdout.write(ansi_pos(row, col))

    def redraw_input(self):
        self.formatter.text = self.input
        self.formatter.redraw()

    def get_input(self) -> Union[Event, str]:
        while True:
            char = getwch()
            if char == ASCII_ESC:
                return Input.UNFOCUS
            elif char == '\x03' or char == '\x04':
                raise KeyboardInterrupt()
            elif char == '\n':
                pass
            elif char == '\r':
                result = self.input
                self.input = ''
                self.cursor = 0
                self.update_cursor()
                self.redraw_input()
                sys.stdout.flush()
                return result
            elif char == ASCII_BACKSPACE:
                if self.cursor > 0:
                    self.cursor -= 1
                    self.input = self.input[:self.cursor] + self.input[self.cursor + 1:]
                    self.update_cursor()
                    self.redraw_input()
            elif char == MS_KEY_ESC0 or char == MS_KEY_ESC1:
                char2 = getwch()
                if char2 == MS_KEY_UP:
                    return Input.KEY_UP
                elif char2 == MS_KEY_DOWN:
                    return Input.KEY_DOWN
                elif char2 == MS_KEY_LEFT or char2 == MS_KEY_RIGHT:
                    if char2 == MS_KEY_LEFT:
                        if self.cursor > 0:
                            self.cursor -= 1
                            self.update_cursor()
                    else:
                        if self.cursor < len(self.input):
                            self.cursor += 1
                            self.update_cursor()
                elif char2 == MS_KEY_HOME:
                    self.cursor = 0
                    self.update_cursor()
                elif char2 == MS_KEY_END:
                    self.cursor = len(self.input)
                    self.update_cursor()
            else:
                if self.cursor < len(self.input):
                    self.input = self.input[:self.cursor] + char + self.input[self.cursor:]
                else:
                    self.input += char
                self.cursor += 1
                self.update_cursor()
                self.redraw_input()
            sys.stdout.flush()

if __name__ == '__main__':
    with WinAnsiMode():
        def on_submit(answer):
            pass
        def on_revise(id, result):
            pass
        display = Display(on_submit, on_revise)
        display.main()