"""Run.

Run actually performs hyper-parameter tuning,
combining a `Search`, which provides the suggestions and an
`Evaluator`, which defines how losses are computed.

The actual event loop and execution happens in a
ProcessPool provided by `pebble`.

Run also takes care of saving things to disk, resuming
itself, stuff like that.

This is the kitchen sink, in other words.

"""

from concurrent.futures import TimeoutError, wait, FIRST_COMPLETED
from multiprocessing import cpu_count
import traceback
import time
from pathlib import Path
import numpy as np
from datetime import datetime
from logging import FileHandler, INFO

from cmlkit.engine import Component, compute_hash
from cmlkit import from_config, logger
from cmlkit.engine import to_config, _from_config, makedir, save_yaml
from cmlkit.utility import humanize
from cmlkit.env import get_scratch

from .stopping import classes as stoppers
from .exceptions import get_exceptions, get_exceptions_spec
from .pool import EvaluationPool
from .resultdb import ResultDB
from .state import State


class Run(Component):

    kind = "run"

    default_context = {
        "max_workers": cpu_count(),
        "shutdown_duration": 30.0,
        "wait_per_loop": 5.0,
    }

    def __init__(
        self,
        search,
        evaluator,
        stop,
        trial_timeout=None,
        caught_exceptions=["TimeoutError"],
        name=None,
        context={},
    ):
        super().__init__(context=context)

        self.search = from_config(search)
        self.evaluator_config = to_config(evaluator)
        self.stop = _from_config(stop, classes=stoppers)
        self.trial_timeout = trial_timeout
        self.caught_exceptions = get_exceptions(caught_exceptions)

        self.id = compute_hash(time.time(), np.random.random(10))  # unique id of this run

        if name is None:
            self.name = humanize(self.id, words=2)

        self.ready = False  # run is not ready until prepared

    def _get_config(self):
        return {
            "search": self.search.get_config(),
            "evaluator": self.evaluator_config,
            "stop": self.stop.get_config(),
            "trial_timeout": self.trial_timeout,
            "caught_exceptions": get_exceptions_spec(self.caught_exceptions),
            "name": self.name,
        }

    def prepare(self, directory=Path(".")):
        self.work_directory = directory / f"run_{self.name}"
        makedir(self.work_directory)
        save_yaml(self.work_directory / "run.yml", self.get_config())

        evals = ResultDB()
        tape = []  # to be replaced by a file-backed SON tape

        self.pool = EvaluationPool(
            evals=evals,
            max_workers=self.context["max_workers"],
            evaluator_config=self.evaluator_config,
            evaluator_context=self.context,
            trial_timeout=self.trial_timeout,
            caught_exceptions=self.caught_exceptions,
        )
        self.state = State(search=self.search, evals=evals, tape=tape)

        logger.addHandler(FileHandler(f"{self.work_directory}/log.log"))
        logger.setLevel(INFO)
        logger.info(f"Prepared runner {self.name} in folder {self.work_directory}.")

        self.ready = True

    def __call__(self, duration=float("inf")):
        return self.run()

    def run(self, duration=float("inf")):
        assert self.ready, "prepare() must be called before starting run."

        start = time.monotonic()
        end = start + duration - self.context["shutdown_duration"]

        futures = {}

        while time.monotonic() < end and not self.stop.done(self.state):
            self.write_status("Running.", len(futures), time.monotonic()-start)
            logger.info(f"Run {self.name} is alive. State: {self.state.short_report()}")
            done, running = wait(
                futures,
                timeout=self.context["wait_per_loop"],
                return_when=FIRST_COMPLETED,
            )

            if not self.stop.done(self.state):
                for f in done:
                    tid = futures[f]
                    result = self.pool.finish(f)
                    self.state.submit(tid, result)
                    del futures[f]

                n_new_trials = max(0, self.context["max_workers"] + 1 - len(running))
                for i in range(n_new_trials):
                    tid, suggestion = self.state.suggest()
                    f = self.pool.schedule(suggestion)

                    futures[f] = tid

        duration = time.monotonic() - start
        logger.info(f"Finished run {self.name} in {duration:.2f}s. Starting shutdown...")
        self.write_status(f"{self.name}: Done, saving results.", 0, duration)
        self.write_results()
        self.write_status(f"{self.name}: Done, initiating shutdown.", 0, duration)
        self.pool.shutdown()
        self.write_status(f"{self.name}: Done. Have a good day!", 0, duration)

    def write_results(self):
        save_yaml(self.work_directory / "tape", self.state.tape)

        for i, config in enumerate(self.state.evals.top_suggestions()):
            save_yaml(self.work_directory / f"suggestion-{i}", config)
        logger.info(f"Saved top 5 suggestions into {self.work_directory}.")

        refined = self.state.evals.top_refined_suggestions()
        if any([r != {} for r in refined]):
            for i, config in enumerate(self.state.evals.top_suggestions()):
                save_yaml(self.work_directory / f"refined_suggestion-{i}", config)
            logger.info(f"Saved top 5 refined suggestions into {self.work_directory}.")

    def write_status(self, message, n_futures, duration):
        timestr = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = f"### Status of run {self.name} at {timestr} ###\n"
        status += f"{message} Runtime: {duration:.1f}. Active evaluations: {n_futures}.\n"
        component_status = "\n".join(
            [self.stop.short_report(self.state), self.state.short_report()]
        )

        with open(self.work_directory / "status.txt", "w+") as f:
            f.write(status + component_status)