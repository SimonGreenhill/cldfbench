import sys
import collections
import shutil
import pathlib
import subprocess

import attr
import csvw
from pycldf.dataset import get_modules, MD_SUFFIX, Dataset
from pycldf.util import pkg_path

from cldfbench.catalogs import Catalog

__all__ = ['CLDFWriter', 'CLDFSpec']


@attr.s
class CLDFSpec(object):
    """
    Basic specification to initialize a CLDF Dataset.
    """
    module = attr.ib(
        default='Generic',
        converter=lambda cls: getattr(cls, '__name__', cls),
        validator=attr.validators.in_([m.id for m in get_modules()])
    )  # Dataset subclass or name of a module
    # Path to the source file for the default metadata for a dataset:
    default_metadata_path = attr.ib(default=None)
    # Filename to be used for the actual copy of the metadata:
    metadata_fname = attr.ib(default=None)
    # A `dict` mapping component names to custom csv file names (which may be important
    # if multiple different CLDF datasets are created in the same directory):
    data_fnames = attr.ib(default=attr.Factory(dict))

    def __attrs_post_init__(self):
        if self.default_metadata_path:
            self.default_metadata_path = pathlib.Path(self.default_metadata_path)
            try:
                Dataset.from_metadata(self.default_metadata_path)
            except Exception:
                raise ValueError('invalid default metadata: {0}'.format(self.default_metadata_path))
        else:
            self.default_metadata_path = pkg_path(
                'modules', '{0}{1}'.format(self.module, MD_SUFFIX))

        if not self.metadata_fname:
            self.metadata_fname = self.default_metadata_path.name

    @property
    def cls(self):
        for m in get_modules():
            if m.id == self.module:
                return m.cls


class CLDFWriter(object):
    """
    An object mediating writing data as proper CLDF dataset.

    In particular, this class
    - implements a context manager which upon exiting will write all objects acquired within the
      context to disk,
    - provides a facade for most of the relevant attributes of a `pycldf.Dataset`.

    Usage:
    >>> with Writer(outdir, cldf_spec) as writer:
    ...     writer.objects['ValueTable'].append(...)
    """
    def __init__(self, outdir, cldf_spec=None, args=None, dataset=None):
        """
        :param outdir: Directory to which to write the CLDF dataset
        :param cldf_spec: `CLDFSpec` instance
        :param args: `argparse.Namespace`, passed if the writer is instantiated from a cli command.
        :param dataset: `cldfbench.Dataset`, passed if instantiated from a dataset method.
        """
        self.cldf_spec = cldf_spec or CLDFSpec()
        self.objects = collections.defaultdict(list)
        self.args = args
        self.dataset = dataset

        outdir = pathlib.Path(outdir)
        if not outdir.exists():
            outdir.mkdir()
        self.dir = outdir
        shutil.copy(
            str(self.cldf_spec.default_metadata_path), str(outdir / self.cldf_spec.metadata_fname))

        # Now we can initialize the CLDF Dataset:
        self.cldf = self.cldf_spec.cls.from_metadata(outdir / self.cldf_spec.metadata_fname)

    def validate(self, log=None):
        return self.cldf.validate(log)

    def __getitem__(self, type_):
        return self.cldf[type_]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.write(**self.objects)

    def write(self, **kw):
        self.cldf.properties['rdf:type'] = 'http://www.w3.org/ns/dcat#Distribution'
        srcs = []
        # Let's see whether self.dataset is repository:
        if self.dataset and self.dataset.repo:
            srcs.append(self.dataset.repo.json_ld())
        if self.args:
            # We inspect the cli arguments to see whether some `Catalog`'s were used.
            for cat in vars(self.args).values():
                if isinstance(cat, Catalog):
                    srcs.append(cat.json_ld())
        if srcs:
            self.cldf.add_provenance(wasDerivedFrom=srcs)
        reqs = [
            collections.OrderedDict([
                ('dc:title', "python"),
                ('dc:description', sys.version.split()[0])])]
        try:
            subprocess.run(
                ['pip', 'freeze'],
                stdout=self.dir.joinpath('requirements.txt').open('wb'),
                check=True)
            reqs.append(
                collections.OrderedDict([
                    ('dc:title', "python-packages"), ('dc:relation', 'requirements.txt')]))
        except subprocess.CalledProcessError:  # pragma: no cover
            pass

        self.cldf.add_provenance(wasGeneratedBy=reqs)

        for comp, fname in self.cldf_spec.data_fnames.items():
            self.cldf[comp].url = csvw.Link(fname)
        self.cldf.write(**kw)
