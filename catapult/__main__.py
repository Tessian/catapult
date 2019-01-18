"""
Collection of tasks for *catapult*.
"""
import logging
import os
import sys
import invoke

from catapult.deploy import deploy
from catapult.release import release
from catapult.projects import projects

__version__ = "0.1"

root = invoke.Collection()


class _Executor(invoke.Executor):
    def expand_calls(self, calls, args=None, kwargs=None):
        """
        Expand a list of `.Call` objects into a near-final list of same.
        The default implementation of this method simply adds a task's
        pre/post-task list before/after the task itself, as necessary.
        Subclasses may wish to do other things in addition (or instead of) the
        above, such as multiplying the `calls <.Call>` by argument vectors or
        similar.
        """
        ret = []
        for call in calls:
            # Normalize to Call (this method is sometimes called with pre/post
            # task lists, which may contain 'raw' Task objects)
            if isinstance(call, invoke.Task):
                # TODO find common kwargs
                task_args = {arg.name for arg in call.get_arguments()}
                call_kwargs = {
                    k: v for k, v in kwargs.items() if k in call.name in task_args
                }
                call_args = tuple(
                    kwargs[arg] for arg in call.positional if arg in kwargs
                )
                call = invoke.Call(task=call, args=call_args, kwargs=call_kwargs)

            ret.extend(
                self.expand_calls(calls=call.pre, args=call.args, kwargs=call.kwargs)
            )
            ret.append(call)
            ret.extend(
                self.expand_calls(calls=call.post, args=call.args, kwargs=call.kwargs)
            )

        return ret


def create_collection():
    """
    Create the root collection and populates with all
    the sub-collections.

    Returns:
        invoke.Collection: root collection.
    """
    root.add_collection(release, name="release")
    root.add_collection(deploy, name="deploy")
    root.add_collection(projects, name="projects")
    return root


def _main():
    logging.basicConfig(
        level=os.environ.get("LOGLEVEL", "INFO").upper(), stream=sys.stderr
    )

    invoke.Program(
        version=__version__,
        namespace=create_collection(),
        name="catapult",
        executor_class=_Executor,
    ).run()


def main():
    try:
        _main()

    except BrokenPipeError:
        # Python flushes standard streams on exit; redirect remaining output
        # to /dev/null to avoid another BrokenPipeError at shutdown
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.dup2(devnull, sys.stderr.fileno())
        sys.exit(1)  # Python exits with error code 1 on EPIPE


if __name__ == "__main__":
    main()
