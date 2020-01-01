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

import codecs, ctypes, msvcrt, sys
from ctypes.wintypes import DWORD
from textwrap import TextWrapper

from util import char_width, unicode_width, unicode_ljust, unicode_center

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

def ansi_pos(row, col):
    return f'\033[{row};{col}H'

def ansi_col(col):
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

RESULT_PASS = 0
RESULT_FAIL = 1

def redraw_box(text, row, col, rows, cols, center_h, center_v, style=None):
    out = ANSI_SAVE

    if style:
        out += style

    wrapper = TextWrapper(width=cols, max_lines=rows, placeholder='...')
    lines = [line for group in (text or '').splitlines() for line in wrapper.wrap(group)]
    for i in range(rows):
        out += ansi_pos(row + i, col)

        n = len(lines)
        j = i - (rows - n)//2 if center_v else i
        line = lines[j] if j >= 0 and j < n else ''
        if center_v:
            out += unicode_center(line, cols)
        else:
            out += unicode_ljust(line, cols)

    out += ANSI_RESET + ANSI_RESTORE
    sys.stdout.write(out)

class HistoryForm:
    __slots__ = 'result', 'question', 'expected', 'answered'

    def __init__(self, result, question, expected, answered):
        self.result   = result
        self.question = question
        self.expected = expected
        self.answered = answered

    def update_result(self, result, highlight):
        row, col, rows, cols = self.result

        if result is None:
            style = ''
            text  = ''
        elif result == RESULT_PASS:
            style = ANSI_GREEN
            text  = u'\u2713\nRight'
        elif result == RESULT_FAIL:
            style = ANSI_RED
            text  = u'\u2717\nWrong'

        if highlight:
            style += ANSI_REVERSE

        redraw_box(text, row, col, rows, cols, True, True, style)

    def update_question(self, text):
        redraw_box(text, *self.question, False, False)

    def update_expected(self, text):
        redraw_box(text, *self.expected, False, False)

    def update_answered(self, text):
        redraw_box(text, *self.answered, False, False)

    def update(self, data, highlight):
        self.update_result(data.result, highlight)
        self.update_question(data.question)
        self.update_expected(data.expected)
        self.update_answered(data.answered)

HISTORY_FORMS = (
    HistoryForm((18, 3, 3, 5), (18, 22, 1, 96), (19, 22, 1, 96), (20, 22, 1, 96)),
    HistoryForm((14, 3, 3, 5), (14, 22, 1, 96), (15, 22, 1, 96), (16, 22, 1, 96)),
    HistoryForm((10, 3, 3, 5), (10, 22, 1, 96), (11, 22, 1, 96), (12, 22, 1, 96)),
    HistoryForm(( 6, 3, 3, 5), ( 6, 22, 1, 96), ( 7, 22, 1, 96), ( 8, 22, 1, 96)),
    HistoryForm(( 2, 3, 3, 5), ( 2, 22, 1, 96), ( 3, 22, 1, 96), ( 4, 22, 1, 96)))

QUESTION_BOX = (23, 3, 2, 115)
NUMBER_BOX   = (21, 3, 1,   2)
TOTAL_BOX    = (21, 6, 1,   2)
ANSWER_BOX   = (27, 3, 1, 115)

class HistoryData:
    __slots__ = 'id', 'result', 'question', 'expected', 'answered'

    def __init__(self, id=None, result=None, question=None, expected=None, answered=None):
        self.id       = id
        self.result   = result
        self.question = question
        self.expected = expected
        self.answered = answered

class Display:
    def __init__(self, on_submit, on_revise):
        self.input     = u''
        self.cursor    = 0
        self.history   = [HistoryData() for _ in HISTORY_FORMS]
        self.selected  = None
        self.on_submit = on_submit
        self.on_revise = on_revise

        sys.stdout.write(ANSI_CLEAR + ANSI_RESET)

        with codecs.open('ui_utf8.txt', 'r', 'utf-8') as f:
            sys.stdout.write(f.read())

        sys.stdout.write(ansi_pos(ANSWER_BOX[0], ANSWER_BOX[1]))
        sys.stdout.flush()

    def __del__(self):
        sys.stdout.write(ansi_col(0) + ANSI_DOWN * 2)
        sys.stdout.flush()

    def cursor_col(self):
        return unicode_width(self.input[:self.cursor])

    def cursor_char_width(self):
        return char_width(self.input[self.cursor])

    def backspace(self):
        if self.cursor > 0:
            self.cursor -= 1
            n = self.cursor_char_width()
            sys.stdout.write(ANSI_BACK * n + ANSI_SAVE + self.input[self.cursor + 1:] + ' ' * n + ANSI_RESTORE)
            self.input = self.input[:self.cursor] + self.input[self.cursor + 1:]

    def redraw_history(self):
        for i, (form, data) in enumerate(zip(HISTORY_FORMS, self.history)):
            form.update(data, i == self.selected)

    def clear_history(self):
        self.history = [HistoryData() for _ in HISTORY_FORMS]
        self.redraw_history()

    def push_history(self, id, result, question, expected, answered):
        item = HistoryData(id, result, question, expected, answered)
        self.history = [item] + self.history[:len(HISTORY_FORMS)-1]
        self.redraw_history()

    def update_question(self, question, number, total):
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

        redraw_box(question, *QUESTION_BOX, True, True)

    def set_selected(self, selected):
        if self.selected is not None:
            HISTORY_FORMS[self.selected].update_result(self.history[self.selected].result, False)

        self.selected = selected

        if self.selected is not None:
            HISTORY_FORMS[self.selected].update_result(self.history[self.selected].result, True)

    def select_item(self, up):
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

    def main(self):
        while True:
            char = msvcrt.getwch()
            if char == ASCII_ESC:
                if self.selected is None:
                    return 0
                else:
                    HISTORY_FORMS[self.selected].update_result(self.history[self.selected].result, False)
                    self.selected = None
            elif char == '\x03' or char == '\x04':
                return 0
            elif char == '\n':
                pass
            elif char == '\r':
                if self.selected is None:
                    if not self.on_submit(self.input):
                        return 0
                    self.input = ''
                    self.cursor = 0
                    sys.stdout.write(ansi_col(ANSWER_BOX[1]) + ANSI_SAVE + ' ' * ANSWER_BOX[3] + ANSI_RESTORE)
            elif char == ASCII_BACKSPACE:
                self.backspace()
            elif char == MS_KEY_ESC0 or char == MS_KEY_ESC1:
                char2 = msvcrt.getwch()
                if char2 == MS_KEY_UP:
                    self.select_item(True)
                elif char2 == MS_KEY_DOWN:
                    self.select_item(False)
                elif char2 == MS_KEY_LEFT:
                    if self.selected is None:
                        if self.cursor > 0:
                            self.cursor -= 1
                            sys.stdout.write(ANSI_BACK * self.cursor_char_width())
                elif char2 == MS_KEY_RIGHT:
                    if self.selected is None:
                        if self.cursor < len(self.input):
                            sys.stdout.write(ANSI_FORWARD * self.cursor_char_width())
                            self.cursor += 1
                elif char2 == MS_KEY_HOME:
                    if self.selected is None:
                        self.cursor = 0
                        sys.stdout.write(ansi_col(ANSWER_BOX[1] + self.cursor_col()))
                elif char2 == MS_KEY_END:
                    if self.selected is None:
                        self.cursor = len(self.input)
                        sys.stdout.write(ansi_col(ANSWER_BOX[1] + self.cursor_col()))
            elif self.selected is None:
                if self.cursor < len(self.input):
                    self.input = self.input[:self.cursor] + char + self.input[self.cursor:]
                else:
                    self.input += char
                self.cursor += 1
                sys.stdout.write(char + ANSI_SAVE + self.input[self.cursor:] + ANSI_RESTORE)
            sys.stdout.flush()

if __name__ == '__main__':
    with WinAnsiMode():
        def on_submit(answer):
            pass
        def on_revise(id, result):
            pass
        display = Display(on_submit, on_revise)
        display.main()