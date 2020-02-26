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