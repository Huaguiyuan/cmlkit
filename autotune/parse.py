import copy
from hyperopt import hp
import qmmltools.autotune.grid as gr
import qmmltools.inout as qmtio
import qmmltools.helpers as qmth
import qmmltools.stats as qmts


def parse(d):
    """Convert a dict conveniently writeable settings into the 'real' ones.

    Syntax:
        'loss': 'str' -> 'loss': qmts.str
        ('gr_log2', min, max, n) -> np.logspace(...)
        ('hp_func', 'id', arg) -> hp.func('id', arg)

    In particular, the following operations are performed:
        - Convert losses into functions (from strings)
        - Generate grids in-place
        - Find hyperopt functions and create them

    """

    qmth.find_key_apply_f(d, 'loss', string_to_loss)
    qmth.find_pattern_apply_f(d, is_grid, to_grid)
    qmth.find_pattern_apply_f(d, is_hyperopt, to_hyperopt)


def string_to_loss(s):

    try:
        f = getattr(qmts, s)
    except AttributeError:
        raise NotImplementedError("Loss named {} is not implemented.".format(s))

    return f


def is_hyperopt(x):
    """Check whether a given object is a hyperopt argument

    The format expected is ('hp_NAME_OF_FUNCTION', 'name for hyperopt', remaining, arguments)

    """

    if isinstance(x, (tuple, list)):
        if isinstance(x[0], str):
            s = x[0].split('_', 1)
            if s[0] == 'hp':
                return True

    return False


def to_hyperopt(x):
    """Convert a sequence to a hyperopt function

    Example: ('hp_choice', 'mbtr_1', [1, 2, 3])
             -> hp.choice('mbtr_1', [1, 2, 3])

    """

    s = x[0].split('_', 1)
    try:
        f = getattr(hp, s[1])
    except AttributeError:
        raise NotImplementedError("Hyperopt can't find function named {}!".format(s[1]))

    f = f(*x[1:])
    return f


def is_grid(x):
    """Check whether a given object is a grid argument

    The format expected is ('gr_NAME_OF_GRID', remaining, arguments)

    """

    if isinstance(x, (tuple, list)):
        if isinstance(x[0], str):
            s = x[0].split('_', 1)
            if s[0] == 'gr':
                return True

    return False


def to_grid(x):
    """Convert a sequence to a grid

    Supported functions:
        'log2': base 2 grid
        'lin': linear grid

    Example: ('grid_log2', -20, 20, 11)
             -> np.logspace(-20, 20, base=2, num=11)

    """

    s = x[0].split('_', 1)
    try:
        f = getattr(gr, s[1])
    except AttributeError:
        raise NotImplementedError("Grid named {} is not (yet) implemented!".format(s[1]))

    return f(*x[1:])