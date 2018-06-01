# coding: utf-8
"""# The [Import Loader](https://docs.python.org/3/reference/import.html#loaders)

`importnb` uses context manager to import Notebooks as Python packages and modules.  `importnb.Notebook` simplest context manager.  It will find and load any notebook as a module.

    >>> m = Notebook().from_filename('loader.ipynb', 'importnb.notebooks')
    >>> assert m and m.Notebook
 
     
### `importnb.Partial` 

    >>> with Notebook(exceptions=BaseException): 
    ...     from importnb.notebooks import loader
    >>> assert loader._exception is None
    
## There is a [lazy importer]()

The Lazy importer will delay the module execution until it is used the first time.  It is a useful approach for delaying visualization or data loading.

    >>> with Notebook(lazy=True): 
    ...     from importnb.notebooks import loader
    
## Loading from resources

Not all notebooks may be loaded as modules throught the standard python import finder.  `from_resource`, or the uncomfortably named `Notebook.from_filename` attributes, support [`importlib_resources`]() style imports and raw file imports.

    >>> from importnb.loader import from_resource
    >>> assert from_resource(Notebook(), 'loader.ipynb', 'importnb.notebooks')
    >>> assert Notebook().from_filename('loader.ipynb', 'importnb.notebooks')
    >>> assert Notebook().from_filename(m.__file__)
    

## Capturing stdin, stdout, and display objects

    >>> with Notebook(stdout=True, stderr=True, display=True, globals=dict(show=True)):
    ...     from importnb.notebooks import loader
    >>> assert loader._capture

## Assigning globals

    >>> nb = Notebook(stdout=True, globals={'show': True}).from_filename('loader.ipynb', 'importnb.notebooks')
    >>> assert nb._capture.stdout
"""

if globals().get("show", None):
    print("Catch me if you can")

try:
    from .capture import capture_output
    from .decoder import loads, dedent
    from .path_hooks import PathHooksContext, modify_sys_path, add_path_hooks, remove_one_path_hook
except:
    from capture import capture_output
    from decoder import loads, dedent
    from path_hooks import PathHooksContext, modify_sys_path, add_path_hooks, remove_one_path_hook

import ast, sys
from copy import copy
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader


try:
    from importlib._bootstrap_external import decode_source
    from importlib.util import module_from_spec
except:
    # python 3.4
    from importlib._bootstrap import _SpecMethods
    from importlib.util import decode_source

    def module_from_spec(spec):
        return _SpecMethods(spec).create()


from importlib import reload
from contextlib import contextmanager, ExitStack
from pathlib import Path

try:
    from importlib.resources import path
except:
    from importlib_resources import path

__all__ = "Notebook", "reload",


class ImportNbException(BaseException):
    """ImportNbException allows all exceptions to be raised, a null except statement always passes."""


"""## Converting cells to code

These functions are attached to the loaders.s
"""

"""## Loading from resources
"""


def from_resource(loader, file=None, resource=None, exec=True, **globals):
    """Load a python module or notebook from a file location.

    from_filename is not reloadable because it is not in the sys.modules.

    This still needs some work for packages.
    
    >> assert from_resource(Notebook(), 'loader.ipynb', 'importnb.notebooks')
    """
    with ExitStack() as stack:
        if resource is not None:
            file = Path(stack.enter_context(path(resource, file)))
        else:
            file = Path(file or loader.path)
        name = (getattr(loader, "name", False) == "__main__" and "__main__") or file.stem
        if file.suffixes[-1] == ".ipynb":
            loader = loader(name, file)
        else:
            loader = SourceFileLoader(name, str(file))

        lazy = getattr(loader, "lazy", False)
        if lazy:
            try:
                from importlib.util import LazyLoader

                loader = LazyLoader(loader)
            except:
                ImportWarning("""LazyLoading is only available in > Python 3.5""")

        module = module_from_spec(spec_from_loader(name, loader))
        if exec:
            stack.enter_context(modify_sys_path(file))
            module.__loader__.exec_module(module, **globals)
    return module


"""# The Notebook Loader
"""


def assign_line_numbers(cell, node):
    return ast.fix_missing_locations(ast.increment_lineno(node, cell["metadata"].get("lineno", 1)))


def markdown_string_expression(cell):
    return ast.Module(body=[ast.Expr(ast.Str(s="".join(cell["source"])))])


class NotebookLoader(SourceFileLoader, PathHooksContext):
    """The simplest implementation of a Notebook Source File Loader.
    >>> with NotebookLoader():
    ...    from importnb.notebooks import decoder
    >>> assert decoder.__file__.endswith('.ipynb')
    """
    EXTENSION_SUFFIXES = ".ipynb",
    __slots__ = "name", "path",

    def __init__(self, fullname=None, path=None):
        super().__init__(fullname, path)
        PathHooksContext.__init__(self)

    @property
    def format(self):
        return dedent

    from_filename = from_resource

    def __call__(self, fullname=None, path=None):
        self = copy(self)
        return SourceFileLoader.__init__(self, str(fullname), str(path)) or self

    def _iter_cells(self, nb):
        for i, cell in enumerate(nb["cells"]):
            node = None
            if cell["cell_type"] == "markdown":
                node = markdown_string_expression(cell)
            if cell["cell_type"] == "code":
                node = ast.parse(self.format("".join(cell["source"])))
            if node is not None:
                yield cell, assign_line_numbers(cell, node)

    def nb_to_ast(self, nb):
        module = ast.Module(body=[])
        for i, (cell, node) in enumerate(self._iter_cells(nb)):
            module.body.extend(node.body)
        return module

    def source_to_code(self, object, path=None):
        nb = loads(decode_source(object))
        module = self.nb_to_ast(nb)
        return compile(module, path or "<importnb>", "exec")


"""## An advanced `exec_module` decorator.
"""


def advanced_exec_module(exec_module):
    """Decorate `SourceFileLoader.exec_module` objects with abilities to:
    * Capture output in Python and IPython
    * Prepopulate a model namespace.
    * Allow exceptions while notebooks are loading.s
    
    >>> assert advanced_exec_module(SourceFileLoader.exec_module)
    """

    def _exec_module(loader, module, **globals):
        module._exception = None
        module.__dict__.update(getattr(loader, "globals", {}))
        module.__dict__.update(globals)
        with capture_output(
            stdout=loader.stdout, stderr=loader.stderr, display=loader.display
        ) as out:
            module._capture = out
            try:
                exec_module(loader, module)
            except loader.exceptions as Exception:
                module._exception = Exception

    return _exec_module


"""# The Advanced Notebook loader
"""


class Notebook(NotebookLoader):
    """The Notebook loader is an advanced loader for IPython notebooks:
    
    * Capture stdout, stderr, and display objects.
    * Partially evaluate notebook with known exceptions.
    * Supply extra global values into notebooks.
    
    >>> assert Notebook().from_filename('loader.ipynb', 'importnb.notebooks')
    """
    EXTENSION_SUFFIXES = ".ipynb",

    format = _transform = staticmethod(dedent)

    __slots__ = "stdout", "stderr", "display", "lazy", "exceptions", "globals", "dir", "no_docs"

    def __init__(
        self,
        fullname=None,
        path=None,
        *,
        stdout=False,
        stderr=False,
        display=False,
        lazy=False,
        globals=None,
        exceptions=ImportNbException,
        dir=None,
        no_docs=True
    ):
        super().__init__(fullname, path)
        self.stdout = stdout
        self.stderr = stderr
        self.display = display
        self.lazy = lazy
        self.globals = {} if globals is None else globals
        self.exceptions = exceptions
        self.dir = dir
        self.no_docs = no_docs

    exec_module = advanced_exec_module(NotebookLoader.exec_module)


def load_ipython_extension(ip=None):
    add_path_hooks(Notebook, Notebook.EXTENSION_SUFFIXES)


def unload_ipython_extension(ip=None):
    remove_one_path_hook(Notebook)


def main(*files):
    loader = Notebook("__main__")
    if not files:
        files = sys.argv[1:]
    return {file: loader.from_filename(file) for file in files}


"""# Developer
"""

if __name__ == "__main__":
    try:
        from utils.export import export
    except:
        from .utils.export import export
    export("loader.ipynb", "../loader.py")
    m = Notebook().from_filename("loader.ipynb")
    print(__import__("doctest").testmod(m, verbose=2))

"""   !jupyter nbconvert --to python --stdout loader.ipynb > ../loader.py
"""

"""# More Information

The `importnb.loader` module recreates basic Python importing abilities.  Have a look at [`execute.ipynb`](execute.ipynb) for more advanced usages.
"""
