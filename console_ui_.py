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

import codecs, ctypes, logging, msvcrt, sys, time
from ctypes.wintypes import DWORD
from typing import Any, Callable, List, Optional, Tuple, Union

LOG = logging.getLogger(__name__)

Box = Tuple[int, int, int, int]

import markup
from ansi_esc import *
from util import char_width, unicode_width, line_break_opportunities

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

class QuestionResult:
    __slots__ = ()

RESULT_PASS = QuestionResult()
RESULT_FAIL = QuestionResult()

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

class HistoryData:
    __slots__ = 'id', 'modified', 'result', 'question', 'expected', 'answered'

    def __init__(self,
        id: Any = None,
        result: Optional[QuestionResult] = None,
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
        self.result   = Formatter(*result  , False, False)
        self.question = Formatter(*question, False, False)
        self.expected = Formatter(*expected, False, False)
        self.answered = Formatter(*answered, False, False)

    def update_result(self, result: Optional[QuestionResult], highlight: bool):
        if result is None:
            self.result.style = ''
            self.result.text  = 'Question'
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
    HistoryForm((16, 3, 1, 9), (16, 14, 2, 104), (18, 14, 2, 104), (20, 14, 2, 104)),
    HistoryForm(( 9, 3, 1, 9), ( 9, 14, 2, 104), (11, 14, 2, 104), (13, 14, 2, 104)),
    HistoryForm(( 2, 3, 1, 9), ( 2, 14, 2, 104), ( 4, 14, 2, 104), ( 6, 14, 2, 104)))

QUESTION_BOX = (23, 3, 3, 115)
NUMBER_BOX   = (22, 3, 1,   2)
TOTAL_BOX    = (22, 6, 1,   2)
ANSWER_BOX   = (27, 3, 2, 115)

class PracticeApp:
    selected: Optional[int]

    def __init__(self, on_submit: Callable[[str], bool], on_revise: Callable[[Any, QuestionResult], None]):
        self.answer    = Input(ANSWER_BOX)
        self.history   = [HistoryData() for _ in HISTORY_FORMS]
        self.question_formatter = Formatter(*QUESTION_BOX, True , True )
        self.selected  = None
        self.on_submit = on_submit
        self.on_revise = on_revise

        sys.stdout.write(ANSI_CLEAR + ANSI_RESET)

        with codecs.open('practice_ui_utf8.txt', 'r', 'utf-8') as f:
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

    def push_history(self, id: Any, result: QuestionResult, question: str, expected: str, answered: str):
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
                    if not self.on_submit(event_or_input):
                        return 0
                elif event_or_input == Input.UNFOCUS:
                    return 0
                elif event_or_input == Input.KEY_UP:
                    self.select_item(True)
                elif event_or_input == Input.KEY_DOWN:
                    self.select_item(False)
            else:
                char = msvcrt.getwch()
                if char == ASCII_ESC:
                    self.set_selected(None)
                elif char == '\x03' or char == '\x04':
                    raise KeyboardInterrupt()
                elif char == MS_KEY_ESC0 or char == MS_KEY_ESC1:
                    char2 = msvcrt.getwch()
                    if char2 == MS_KEY_UP or char2 == MS_KEY_DOWN:
                        self.select_item(char2 == MS_KEY_UP)
                elif char == ' ':
                    self.toggle_item()
                    self.set_selected(None)
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
                if msvcrt.kbhit():
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
        char = msvcrt.getwch()
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
            char2 = msvcrt.getwch()
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

class EditorApp:
    class Card:
        __slots__ = 'card_id', 'front', 'back'

        card_id: Any

        def __init__(self, card_id, box_front, box_back):
            self.card_id = card_id
            self.front = MarkupDrawer(*box_front, True, True)
            self.back  = MarkupDrawer(*box_back , True, True)

        def get_side(self, front: bool) -> MarkupDrawer:
            return self.front if front else self.back

    selected: Optional[int]

    INPUT_BOX     = (26,  3, 3, 115)
    PREVIEW_FRONT = (20,  3, 5,  56)
    PREVIEW_BACK  = (20, 62, 5,  56)
    CARD_BROWSER  = (
        (( 2, 3, 5, 56), ( 2, 62, 5, 56)),
        (( 8, 3, 5, 56), ( 8, 62, 5, 56)),
        ((14, 3, 5, 56), (14, 62, 5, 56)),
    )

    def __init__(self, on_submit: Callable[[Any, str, str], None], on_scroll: Callable[[bool], None]):
        self.input      = Input(EditorApp.INPUT_BOX)
        self.preview    = EditorApp.Card(None, EditorApp.PREVIEW_FRONT, EditorApp.PREVIEW_BACK)
        self.edit_front = True
        self.browser    = [
            EditorApp.Card(None, box_front, box_back)
            for box_front, box_back in EditorApp.CARD_BROWSER]
        self.selected   = None
        self.on_submit  = on_submit
        self.on_scroll  = on_scroll

        sys.stdout.write(ANSI_CLEAR + ANSI_RESET)

        with codecs.open('editor_ui_utf8.txt', 'r', 'utf-8') as f:
            sys.stdout.write(f.read())

        sys.stdout.write(ansi_pos(
            EditorApp.INPUT_BOX[0],
            EditorApp.INPUT_BOX[1]))
        sys.stdout.flush()

    def __del__(self):
        sys.stdout.write(ansi_col(0) + ANSI_DOWN * 4)
        sys.stdout.flush()

    @property
    def first_card_id(self) -> Any:
        return self.browser[0].card_id

    @property
    def last_card_id(self) -> Any:
        return self.browser[-1].card_id

    def set_browser_cards(self, cards: List[Tuple[Any, str, str]]):
        for i in range(len(self.browser)):
            try: 
                card_id, front, back = cards[i]
            except IndexError:
                card_id, front, back = None, '', ''
            self.browser[i].card_id    = card_id
            self.browser[i].front.text = front
            self.browser[i].back .text = back
        self.redraw_browser()

    def redraw_browser(self):
        for card in self.browser:
            card.front.redraw()
            card.back .redraw()

    def set_selected(self, selected: Optional[int]):
        if self.selected is not None:
            self.browser[self.selected].front.style = ''
            self.browser[self.selected].back .style = ''
            self.browser[self.selected].front.redraw()
            self.browser[self.selected].back .redraw()

        self.selected = selected

        if self.selected is not None:
            self.browser[self.selected].front.style = ANSI_REVERSE
            self.browser[self.selected].back .style = ANSI_REVERSE
            self.browser[self.selected].front.redraw()
            self.browser[self.selected].back .redraw()

    def select_card(self, up: bool):
        n = len(self.browser)
        if up:
            if self.selected is None:
                self.set_selected(n - 1)
            elif self.selected > 0:
                self.set_selected(self.selected - 1)
            else:
                self.set_selected(None)
        else:
            if self.selected is None:
                self.set_selected(0)
            elif self.selected < n - 1:
                self.set_selected(self.selected + 1)
            else:
                self.set_selected(None)

    def edit(self, card_id: Any, front: str, back: str):
        self.preview.card_id    = card_id
        self.preview.front.text = front
        self.preview.back .text = back
        self.preview.front.redraw()
        self.preview.back .redraw()
        self.edit_front = True
        self.input.text = front
        self.update_input()
        self.set_selected(None)

    def edit_selected(self):
        if self.selected is None:
            return

        self.edit(
            self.browser[self.selected].card_id,
            self.browser[self.selected].front.text,
            self.browser[self.selected].back .text)

    def update_input(self, text: Optional[str] = None):
        preview = self.preview.get_side(self.edit_front)
        if text is not None:
            preview.text = text
            preview.redraw()
        self.input.formatter.set_error_ranges(preview.error_ranges)
        self.input.redraw_input()

    def flip_card(self, update_input: bool):
        if update_input:
            self.preview.get_side(self.edit_front).text = self.input.text
        self.edit_front = not self.edit_front
        self.input.text = self.preview.get_side(self.edit_front).text

    def main(self) -> int:
        def on_timeout(text: str) -> bool:
            self.update_input(text)
            return False

        while True:
            if self.selected is None:
                preview = self.preview.get_side(self.edit_front)
                preview.style = ANSI_REVERSE
                preview.redraw()

                event_or_input = self.input.get_input(0.3, on_timeout)

                preview.style = ''
                preview.redraw()

                if isinstance(event_or_input, str):
                    LOG.debug('user input \"%s\"', event_or_input)
                    LOG.debug('\tpreview data \"%s\" \"%s\"',
                        self.preview.front.text,
                        self.preview.back .text)
                    self.update_input(event_or_input)
                    LOG.debug('\tpreview data \"%s\" \"%s\"',
                        self.preview.front.text,
                        self.preview.back .text)
                    if self.preview.front.text and self.preview.back.text:
                        card_id    = self.preview.card_id
                        front_text = self.preview.front.text
                        back_text  = self.preview.back .text
                        self.preview.card_id    = None
                        self.preview.front.text = ''
                        self.preview.back .text = ''
                        self.on_submit(card_id, front_text, back_text)
                        self.edit_front = True
                        self.preview.front.redraw()
                        self.preview.back .redraw()
                    else:
                        self.flip_card(False)
                elif event_or_input == Input.UNFOCUS:
                    return 0
                elif event_or_input == Input.KEY_UP:
                    self.select_card(True)
                elif event_or_input == Input.KEY_DOWN:
                    self.select_card(False)
                elif event_or_input == Input.PAGE_UP:
                    self.on_scroll(True)
                elif event_or_input == Input.PAGE_DOWN:
                    self.on_scroll(False)
                elif event_or_input == Input.TAB:
                    self.flip_card(True)
            else:
                char = msvcrt.getwch()
                if char == ASCII_ESC:
                    self.set_selected(None)
                elif char == '\x03' or char == '\x04':
                    raise KeyboardInterrupt()
                elif char == MS_KEY_ESC0 or char == MS_KEY_ESC1:
                    char2 = msvcrt.getwch()
                    if char2 == MS_KEY_UP or char2 == MS_KEY_DOWN:
                        self.select_card(char2 == MS_KEY_UP)
                    elif char2 == MS_KEY_PAGE_UP:
                        self.on_scroll(True)
                    elif char2 == MS_KEY_PAGE_DOWN:
                        self.on_scroll(False)
                elif char in (' ', '\r'):
                    self.edit_selected()
            sys.stdout.flush()

def example_main():
    log_handler = logging.FileHandler('console_ui.log', encoding='utf-8')
    log_handler.setLevel(logging.DEBUG)
    LOG.setLevel(logging.DEBUG)
    LOG.addHandler(log_handler)

    app: Optional[EditorApp] = None
    start_id = 0
    def on_scroll(scroll_up: bool):
        nonlocal start_id
        if scroll_up:
            start_id -= 1
        else:
            start_id += 1

        assert app is not None
        app.set_browser_cards([
            (start_id + i, f'card {start_id + i} front', f'card {start_id + i} back')
            for i in range(3)
        ])

    from console_ui import WinAnsiMode
    with WinAnsiMode():
        app = EditorApp(lambda id, front, back: None, on_scroll)
        app.main()

if __name__ == '__main__':
    example_main()