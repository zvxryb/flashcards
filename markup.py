from __future__ import annotations

import logging, sys, unicodedata
from functools import reduce
from typing import Callable, Dict, Generator, Iterator, List, Optional, Tuple, Union

from ansi_esc import *
from console_ui import WinAnsiMode
from util import is_breaking_space, is_inner_punctuation, is_starting_punctuation, is_ending_punctuation, line_break_opportunities, StringMask, unicode_width, unicode_center

LOG = logging.getLogger(__name__)

def token_boundaries(s: str) -> StringMask:
    cats = [unicodedata.category(c) for c in s]
    delim = StringMask.collect(
        c in ('\\', '{', '}', '`', '^', '_') or
        is_breaking_space(c, cat) or
        is_inner_punctuation(cat) or
        is_starting_punctuation(cat) or
        is_ending_punctuation(cat)
        for c, cat in zip(s, cats))
    return line_break_opportunities(s) | delim | delim << 1

class Token:
    __slots__ = 'type', 'range', 'value'

    class Type:
        __slots__ = 'ident',

        def __init__(self, ident: str):
            self.ident = ident

        def __str__(self) -> str:
            return self.ident

    LITERAL  = Type('literal')
    SPACE    = Type('whitespace')
    INFIX    = Type('infix')
    LBRACKET = Type('lbracket')
    RBRACKET = Type('rbracket')

    def __init__(self, type_: Type, range_: Optional[Tuple[int, int]], value: str):
        self.type  = type_
        self.range = range_
        self.value = value

    def __repr__(self) -> str:
        return f'Token{{{str(self.type)}, {self.range}, \"{self.value}\"}}'

def tokenize(s: str) -> Generator[Token, None, None]:
    breaks = token_boundaries(s)
    i = 0
    j = 0
    while j < len(s):
        if breaks[j]:
            yield Token(Token.LITERAL, (i, j), s[i:j+1])
            i = j+1
        j = j+1
    if i < len(s):
        yield Token(Token.LITERAL, (i, j), s[i:])

def normalize(tokens: Iterator[Token]) -> Generator[Token, None, None]:
    global INFIX_OPERATORS

    t0: Optional[Token] = None

    while True:
        try:
            t1 = next(tokens)
        except StopIteration:
            break

        if t1.value in INFIX_OPERATORS:
            t1.type = Token.INFIX
            if t0:
                if t0.type == Token.SPACE:
                    t0.type = Token.LITERAL
                    yield Token(Token.SPACE, None, '')
                yield t0
            t0 = t1
        elif t1.value == '{':
            t1.type = Token.LBRACKET
            if t0:
                yield t0
                if t0.type in (Token.LITERAL, Token.RBRACKET):
                    yield Token(Token.SPACE, None, '')
            t0 = t1
        elif t1.value == '}':
            t1.type = Token.RBRACKET
            if t0:
                yield t0
                if t0.type == Token.LBRACKET:
                    assert t0.value == '{'
                    yield Token(Token.LITERAL, None, '')
            t0 = t1
        elif all(is_breaking_space(c) for c in t1.value):
            if t0 and t0.type == Token.SPACE:
                t0.value += t1.value
            else:
                if t0 and t0.type == Token.LITERAL:
                    t1.type = Token.SPACE
                else:
                    t1.type = Token.LITERAL
                if t0:
                    yield t0
                t0 = t1
        else:
            t1.type = Token.LITERAL
            if t0:
                yield t0
                if t0.type in (Token.LITERAL, Token.RBRACKET):
                    yield Token(Token.SPACE, None, '')
            t0 = t1

    if t0:
        yield t0

class Text:
    __slots__ = 'x', 'y', 'text'

    def __init__(self, x: int, y: int, text: str):
        self.x = x
        self.y = y
        self.text = text

    def __repr__(self) -> str:
        return f'Text{{{self.x}, {self.y}, \"{self.text}\"}}'

    @staticmethod
    def from_str(text: str) -> Text:
        return Text(0, 0, text)

class TextBox:
    __slots__ = 'width', 'height', 'baseline'

    def __init__(self, width: int, height: int, baseline: int):
        self.width    = width
        self.height   = height
        self.baseline = baseline

    def __repr__(self) -> str:
        return f'TextBox{{{self.width}x{self.height}, {self.baseline}}}'

    @staticmethod
    def from_str(text: str) -> TextBox:
        return TextBox(unicode_width(text), 1, 0)

class TextGroup:
    __slots__ = 'box', 'items'

    def __init__(self, box: TextBox, items: List[Text]):
        self.box = box
        self.items = items

    def __repr__(self) -> str:
        return f'TextGroup{{{self.box}, {self.items}}}'

    def concat(self,
        other: TextGroup,
        x_offset: Optional[int] = None,
        y_offset: Optional[int] = None,
        baseline: Optional[int] = None
    ) -> TextGroup:
        if x_offset is None:
            x_offset = self.box.width
        if y_offset is None:
            y_offset = self.box.baseline - other.box.baseline

        x0 = min(0, x_offset)
        x1 = max(self.box.width, other.box.width + x_offset)
        y0 = min(0, y_offset)
        y1 = max(self.box.height, other.box.height + y_offset)

        if baseline is None:
            baseline = self.box.baseline - y0

        box = TextBox(x1 - x0, y1 - y0, baseline)
        items = [
            *(Text(
                item.x - x0,
                item.y - y0,
                item.text)
            for item in self.items),
            *(Text(
                item.x + x_offset - x0,
                item.y + y_offset - y0,
                item.text)
            for item in other.items)]
        return TextGroup(box, items)

    @staticmethod
    def from_str(text: str) -> TextGroup:
        return TextGroup(TextBox.from_str(text), [Text.from_str(text)])

    @staticmethod
    def empty() -> TextGroup:
        return TextGroup(TextBox(0, 0, 0), [])

class Template:
    __slots__ = 'argn', 'definition'

    def __init__(self, argn: int, definition: str):
        self.argn = argn
        self.definition = definition

    def evaluate(self, *args: TextGroup) -> Generator[Union[Token, TextGroup], None, None]:
        assert self.argn == len(args)

        def match_group(argn: int, text: str) -> Optional[int]:
            if len(text) < 2:
                return None
            if text[0] != '#':
                return None
            try:
                group = int(text[1:])
            except ValueError:
                return None
            if 0 <= group < argn:
                return group
            return None

        for token in tokenize(self.definition):
            group = match_group(self.argn, token.value)
            if group is None:
                yield token
            else:
                yield args[group]

class InfixOperator:
    __slots__ = 'symbol', 'precedence', 'math_mode', 'evaluate'

    def __init__(self,
        symbol: str,
        precedence: int,
        math_mode: bool,
        evaluate: Callable[[TextGroup, TextGroup], TextGroup]
    ):
        self.symbol = symbol
        self.precedence = precedence
        self.math_mode = math_mode
        self.evaluate = evaluate

INFIX_OPERATORS: Dict[str, InfixOperator] = {}
def infix_operator(symbol: str, precedence: int, math_mode: bool
) -> Callable[[Callable[[TextGroup, TextGroup], TextGroup]], InfixOperator]:
    def f(g: Callable[[TextGroup, TextGroup], TextGroup]) -> InfixOperator:
        global INFIX_OPERATORS
        operator = InfixOperator(symbol, precedence, math_mode, g)
        INFIX_OPERATORS[symbol] = operator
        return operator
    return f

@infix_operator('^', 10, False)
def infix_text_over(lhs: TextGroup, rhs: TextGroup) -> TextGroup:
    width = max(lhs.box.width, rhs.box.width)
    lhs_pad = (width - lhs.box.width) // 2
    rhs_pad = (width - rhs.box.width) // 2
    x_offset = rhs_pad - lhs_pad
    y_offset = lhs.box.height
    return lhs.concat(rhs, x_offset = x_offset, y_offset = y_offset)

@infix_operator('_', 10, False)
def infix_text_under(lhs: TextGroup, rhs: TextGroup) -> TextGroup:
    width = max(lhs.box.width, rhs.box.width)
    lhs_pad = (width - lhs.box.width) // 2
    rhs_pad = (width - rhs.box.width) // 2
    x_offset = rhs_pad - lhs_pad
    y_offset = -rhs.box.height
    return lhs.concat(rhs, x_offset = x_offset, y_offset = y_offset)

# combined parsing and evaluation; uses shunting-yard based algorithm
def layout(tokens: Iterator[Token]) -> Tuple[List[Tuple[str, Optional[Tuple[int, int]]]], TextGroup]:
    LOG.info('beginning parsing/layout')

    output: List[TextGroup] = []
    operators: List[Tuple[int, Token]] = []
    quirks: List[Tuple[str, Optional[Tuple[int, int]]]] = []

    def evaluate(token: Token):
        nonlocal output, quirks
        LOG.debug(f'eval {token}')
        if token.type == Token.INFIX:
            op = INFIX_OPERATORS[token.value]
            rhs = TextGroup.empty()
            lhs = TextGroup.empty()
            try:
                rhs = output.pop()
                LOG.debug(f'rhs {rhs}')
                LOG.debug(f'\ttail {output}')
                lhs = output.pop()
                LOG.debug(f'lhs {lhs}')
                LOG.debug(f'\ttail {output}')
            except IndexError:
                quirks += [('missing operand', token.range)]
            output += [op.evaluate(lhs, rhs)]
            LOG.debug(f'result {output[-1]}')
        elif token.type == Token.SPACE:
            rhs = TextGroup.empty()
            lhs = TextGroup.empty()
            try:
                rhs = output.pop()
                LOG.debug(f'rhs {rhs}')
                LOG.debug(f'\ttail {output}')
                lhs = output.pop()
                LOG.debug(f'lhs {lhs}')
                LOG.debug(f'\ttail {output}')
            except IndexError:
                pass
            output += [lhs.concat(TextGroup.from_str(token.value)).concat(rhs)]
            LOG.debug(f'result {output[-1]}')
        else:
            assert False

    for token in tokens:
        LOG.debug('-'*80)
        LOG.debug(f'input {token}')
        if token.type == Token.LBRACKET:
            assert token.value == '{'
            operators += [(0, token)]
        elif token.type == Token.RBRACKET:
            while True:
                try:
                    _, token_ = operators.pop()
                except IndexError:
                    quirks += [('unmatched right brace', token.range)]
                    break
                if token_.value == '{':
                    break
                else:
                    evaluate(token_)
        elif token.type == Token.INFIX:
            op = INFIX_OPERATORS[token.value]
            while operators and op.precedence <= operators[-1][0]:
                _, token_ = operators.pop()
                evaluate(token_)
            operators += [(op.precedence, token)]
        elif token.type == Token.SPACE:
            while operators and operators[-1][1].type != Token.LBRACKET:
                _, token_ = operators.pop()
                evaluate(token_)
            operators += [(1, token)]
        else:
            output += [TextGroup.from_str(token.value)]
        LOG.debug(f'output state {output}')
        LOG.debug(f'operators state {operators}')

    while operators:
        _, token = operators.pop()
        if token.value == '{':
            quirks += [('unmatched left brace', token.range)]
        else:
            evaluate(token)

    if not output:
        quirks += [('empty output', None)]
    elif len(output) > 1:
        quirks += [('unprocessed operands in output', None)]

    LOG.info(f'quirks {quirks}')
    return quirks, reduce(lambda output, item: output.concat(item), output, TextGroup.empty())

with WinAnsiMode():
    log_handler = logging.FileHandler('markup.log', encoding='utf-8')
    log_handler.setLevel(logging.DEBUG)
    LOG.setLevel(logging.DEBUG)
    LOG.addHandler(log_handler)

    try:
        input = raw_input
    except NameError:
        pass

    quirks, group = layout(normalize(tokenize(input('> '))))

    sys.stdout.write(ANSI_SAVE + ANSI_CLEAR)
    for item in group.items:
        sys.stdout.write(ANSI_SAVE + ansi_pos(10 - item.y, item.x + 1) + item.text + ANSI_RESTORE)
    sys.stdout.write(ANSI_RESTORE)

    sys.stdout.flush()