def ansi_sgr(code: int) -> str:
    return f'\033[{code}m'

def ansi_rgb24_fg(r: int, g: int, b: int) -> str:
    return f'\033[38;2;{r};{g};{b}m'

def ansi_rgb24_bg(r: int, g: int, b: int) -> str:
    return f'\033[48;2;{r};{g};{b}m'

ANSI_CLEAR   = '\033[H\033[J'
ANSI_RESET   = ansi_sgr(0)
ANSI_UP      = '\033[A'
ANSI_DOWN    = '\033[B'
ANSI_FORWARD = '\033[C'
ANSI_BACK    = '\033[D'
ANSI_UNDERLINE = ansi_sgr(4)
ANSI_REVERSE = ansi_sgr(7)
ANSI_BLACK   = ansi_sgr(30)
ANSI_RED     = ansi_sgr(31)
ANSI_GREEN   = ansi_sgr(32)
ANSI_YELLOW  = ansi_sgr(33)
ANSI_BLUE    = ansi_sgr(34)
ANSI_MAGENTA = ansi_sgr(35)
ANSI_CYAN    = ansi_sgr(36)
ANSI_WHITE   = ansi_sgr(37)
ANSI_DEFAULT = ansi_sgr(39)
ANSI_BRIGHT_BLACK   = ansi_sgr(90)
ANSI_BRIGHT_RED     = ansi_sgr(91)
ANSI_BRIGHT_GREEN   = ansi_sgr(92)
ANSI_BRIGHT_YELLOW  = ansi_sgr(93)
ANSI_BRIGHT_BLUE    = ansi_sgr(94)
ANSI_BRIGHT_MAGENTA = ansi_sgr(95)
ANSI_BRIGHT_CYAN    = ansi_sgr(96)
ANSI_BRIGHT_WHITE   = ansi_sgr(97)
ANSI_SAVE    = '\033[s'
ANSI_RESTORE = '\033[u'

def ansi_pos(row: int, col: int) -> str:
    return f'\033[{row};{col}H'

def ansi_col(col: int) -> str:
    return f'\033[{col}G'