import numpy as np
import logging
import time
import qmmltools.inout as qmtio
import qmmltools.autoload as qmta
from hyperopt import fmin, tpe, Trials
from hyperopt.mongoexp import MongoTrials
from qmmltools.autotune.objective import objective
from qmmltools.autotune.parse import preprocess
from qmmltools.model_spec import ModelSpec
from qmmltools.mbtr.cached_mbtr import cache_loc


def run_autotune(r):
    """Perform an autotune run.

    This is the main runner of autotune. It assumes a lot of things,
    mainly that it's being executed in the folder of the run being
    performed, so it will happily start creating folders and logs.

    For a more tailored experience, run the functions in core separately!

    Args:
        r: either a dict, or a yaml file specifying the run,
           for full docs see TODO

    Returns:
        None, everything is written to disk

    """

    if isinstance(r, str):
        r = qmtio.read_yaml(r)

    preprocess(r)
    setup_local(r)
    logging.info('Setup finished. Welcome to AutoTune.')
    trials = trials_setup(r)

    result, duration = run_hyperopt(r, trials)

    logging.info("Finished optimisation in %is, lowest achieved loss was %.4f ± %.4f" %
                 (duration, result.best_trial['result']['loss'], result.best_trial['result']['loss_variance']))

    postprocess(r, result, duration)


def setup_local(r):
    # Folders
    qmtio.makedir('logs')
    qmtio.makedir('cache')
    qmtio.makedir('out')

    # Logging
    logging.basicConfig(filename=("{}.log".format('logs/' + r['name'])), level=r['config']['loglevel'])
    app_log = logging.getLogger()
    app_log.addHandler(logging.StreamHandler())

    # Info
    logging.info('Cache location is {}'.format(cache_loc))


def trials_setup(r):
    # Trials object for hyperopt
    if r['config']['parallel'] is True:
        logging.info('Performing parallel run with db_name {}. Remember to start the db and the workers.'.format(r['config']['db_name']))
        trials = MongoTrials('{}/{}/jobs'.format(r['config']['db_url'], r['config']['db_name']), exp_key=r['name'])
    else:
        trials = Trials()
        logging.info('Performing serial run.')

    return trials


def run_hyperopt(r, trials):
    logging.info('Starting optimisation.')
    start = time.time()
    best = fmin(objective,
                space=r,
                algo=tpe.suggest,
                max_evals=r['config']['n_calls'],
                trials=trials)
    end = time.time()
    duration = int(end - start)

    return trials, duration


def postprocess(r, result, duration):
    to_save = {
        'final_loss': result.best_trial['result']['loss'],
        'final_loss_variance': result.best_trial['result']['loss_variance'],
        'duration': duration,
        'losses': result.losses(),
        'run_config': r['internal']['original_task']
    }

    qmtio.save('out/' + r['name'] + '.run', to_save)
    logging.info('Saved run results.')

    top = (np.array(result.losses())).argsort()[:r['config']['n_cands']]

    for i in range(r['config']['n_cands']):
        spec = ModelSpec.from_dict(result.trials[top[i]]['result']['spec_dict'])
        spec.name += '-' + 'best' + str(i)
        spec.save('out/')

    logging.info('Saved result top {} models; exiting. Have a good day!'.format(r['config']['n_cands']))
