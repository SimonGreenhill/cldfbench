"""
Display basic info about a dataset
"""
from cldfbench.cli_util import with_dataset, add_dataset_spec


def register(parser):
    add_dataset_spec(parser)


def run(args):
    with_dataset(args, lambda ds, _: print(ds))
