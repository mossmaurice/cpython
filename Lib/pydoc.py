#!/usr/bin/env python
"""Generate Python documentation in HTML or text for interactive use.

In the Python interpreter, do "from pydoc import help" to provide online
help.  Calling help(thing) on a Python object documents the object.

At the shell command line outside of Python:
    Run "pydoc <name>" to show documentation on something.  <name> may be
    the name of a function, module, package, or a dotted reference to a
    class or function within a module or module in a package.  If the
    argument contains a path segment delimiter (e.g. slash on Unix,
    backslash on Windows) it is treated as the path to a Python source file.

    Run "pydoc -k <keyword>" to search for a keyword in the synopsis lines
    of all available modules.

    Run "pydoc -p <port>" to start an HTTP server on a given port on the
    local machine to generate documentation web pages.

    For platforms without a command line, "pydoc -g" starts the HTTP server
    and also pops up a little window for controlling it.

    Run "pydoc -w <name>" to write out the HTML documentation for a module
    to a file named "<name>.html".
"""

__author__ = "Ka-Ping Yee <ping@lfw.org>"
__date__ = "26 February 2001"
__version__ = "$Revision$"
__credits__ = """Guido van Rossum, for an excellent programming language.
Tommy Burnette, the original creator of manpy.
Paul Prescod, for all his work on onlinehelp.
Richard Chamberlain, for the first implementation of textdoc.

Mynd you, m��se bites Kan be pretty nasti..."""

# Note: this module is designed to deploy instantly and run under any
# version of Python from 1.5 and up.  That's why it's a single file and
# some 2.0 features (like string methods) are conspicuously avoided.

import sys, imp, os, stat, re, types, inspect
from repr import Repr
from string import expandtabs, find, join, lower, split, strip, rstrip

# --------------------------------------------------------- common routines

def synopsis(filename, cache={}):
    """Get the one-line summary out of a module file."""
    mtime = os.stat(filename)[stat.ST_MTIME]
    lastupdate, result = cache.get(filename, (0, None))
    if lastupdate < mtime:
        file = open(filename)
        line = file.readline()
        while line[:1] == '#' or strip(line) == '':
            line = file.readline()
            if not line: break
        if line[-2:] == '\\\n':
            line = line[:-2] + file.readline()
        line = strip(line)
        if line[:3] == '"""':
            line = line[3:]
            while strip(line) == '':
                line = file.readline()
                if not line: break
            result = strip(split(line, '"""')[0])
        else: result = None
        file.close()
        cache[filename] = (mtime, result)
    return result

def pathdirs():
    """Convert sys.path into a list of absolute, existing, unique paths."""
    dirs = []
    normdirs = []
    for dir in sys.path:
        dir = os.path.abspath(dir or '.')
        normdir = os.path.normcase(dir)
        if normdir not in normdirs and os.path.isdir(dir):
            dirs.append(dir)
            normdirs.append(normdir)
    return dirs

def getdoc(object):
    """Get the doc string or comments for an object."""
    result = inspect.getdoc(object)
    if not result:
        try: result = inspect.getcomments(object)
        except: pass
    return result and re.sub('^ *\n', '', rstrip(result)) or ''

def classname(object, modname):
    """Get a class name and qualify it with a module name if necessary."""
    name = object.__name__
    if object.__module__ != modname:
        name = object.__module__ + '.' + name
    return name

def isconstant(object):
    """Check if an object is of a type that probably means it's a constant."""
    return type(object) in [
        types.FloatType, types.IntType, types.ListType, types.LongType,
        types.StringType, types.TupleType, types.TypeType,
        hasattr(types, 'UnicodeType') and types.UnicodeType or 0]

def replace(text, *pairs):
    """Do a series of global replacements on a string."""
    for old, new in pairs:
        text = join(split(text, old), new)
    return text

def cram(text, maxlen):
    """Omit part of a string if needed to make it fit in a maximum length."""
    if len(text) > maxlen:
        pre = max(0, (maxlen-3)/2)
        post = max(0, maxlen-3-pre)
        return text[:pre] + '...' + text[len(text)-post:]
    return text

def stripid(text):
    """Remove the hexadecimal id from a Python object representation."""
    # The behaviour of %p is implementation-dependent, so we need an example.
    for pattern in [' at 0x[0-9a-f]{6,}>$', ' at [0-9A-F]{8,}>$']:
        if re.search(pattern, repr(Exception)):
            return re.sub(pattern, '>', text)
    return text

def modulename(path):
    """Return the Python module name for a given path, or None."""
    filename = os.path.basename(path)
    suffixes = map(lambda (suffix, mode, kind): (len(suffix), suffix),
                   imp.get_suffixes())
    suffixes.sort()
    suffixes.reverse() # try longest suffixes first, in case they overlap
    for length, suffix in suffixes:
        if len(filename) > length and filename[-length:] == suffix:
            return filename[:-length]

class DocImportError(Exception):
    """Class for errors while trying to import something to document it."""
    def __init__(self, filename, etype, evalue):
        self.filename = filename
        self.etype = etype
        self.evalue = evalue
        if type(etype) is types.ClassType:
            etype = etype.__name__
        self.args = '%s: %s' % (etype, evalue)

def importfile(path):
    """Import a Python source file or compiled file given its path."""
    magic = imp.get_magic()
    file = open(path, 'r')
    if file.read(len(magic)) == magic:
        kind = imp.PY_COMPILED
    else:
        kind = imp.PY_SOURCE
    file.close()
    filename = os.path.basename(path)
    name, ext = os.path.splitext(filename)
    file = open(path, 'r')
    try:
        module = imp.load_module(name, file, path, (ext, 'r', kind))
    except:
        raise DocImportError(path, sys.exc_type, sys.exc_value)
    file.close()
    return module

def ispackage(path):
    """Guess whether a path refers to a package directory."""
    if os.path.isdir(path):
        init = os.path.join(path, '__init__.py')
        initc = os.path.join(path, '__init__.pyc')
        if os.path.isfile(init) or os.path.isfile(initc):
            return 1

# ---------------------------------------------------- formatter base class

class Doc:
    def document(self, object, *args):
        """Generate documentation for an object."""
        args = (object,) + args
        if inspect.ismodule(object): return apply(self.docmodule, args)
        if inspect.isclass(object): return apply(self.docclass, args)
        if inspect.isroutine(object): return apply(self.docroutine, args)
        raise TypeError, "don't know how to document objects of type " + \
            type(object).__name__

# -------------------------------------------- HTML documentation generator

class HTMLRepr(Repr):
    """Class for safely making an HTML representation of a Python object."""
    def __init__(self):
        Repr.__init__(self)
        self.maxlist = self.maxtuple = self.maxdict = 10
        self.maxstring = self.maxother = 50

    def escape(self, text):
        return replace(text, ('&', '&amp;'), ('<', '&lt;'), ('>', '&gt;'))

    def repr(self, object):
        result = Repr.repr(self, object)
        return result

    def repr1(self, x, level):
        methodname = 'repr_' + join(split(type(x).__name__), '_')
        if hasattr(self, methodname):
            return getattr(self, methodname)(x, level)
        else:
            return self.escape(cram(stripid(repr(x)), self.maxother))

    def repr_string(self, x, level):
        test = cram(x, self.maxstring)
        testrepr = repr(test)
        if '\\' in test and '\\' not in replace(testrepr, (r'\\', '')):
            # Backslashes are only literal in the string and are never
            # needed to make any special characters, so show a raw string.
            return 'r' + testrepr[0] + self.escape(test) + testrepr[0]
        return re.sub(r'((\\[\\abfnrtv\'"]|\\x..|\\u....)+)',
                      r'<font color="#c040c0">\1</font>',
                      self.escape(testrepr))

    def repr_instance(self, x, level):
        try:
            return cram(stripid(repr(x)), self.maxstring)
        except:
            return self.escape('<%s instance>' % x.__class__.__name__)

    repr_unicode = repr_string

class HTMLDoc(Doc):
    """Formatter class for HTML documentation."""

    # ------------------------------------------- HTML formatting utilities

    _repr_instance = HTMLRepr()
    repr = _repr_instance.repr
    escape = _repr_instance.escape

    def preformat(self, text):
        """Format literal preformatted text."""
        text = self.escape(expandtabs(text))
        return replace(text, ('\n\n', '\n \n'), ('\n\n', '\n \n'),
                             (' ', '&nbsp;'), ('\n', '<br>\n'))

    def multicolumn(self, list, format, cols=4):
        """Format a list of items into a multi-column list."""
        result = ''
        rows = (len(list)+cols-1)/cols

        for col in range(cols):
            result = result + '<td width="%d%%" valign=top>' % (100/cols)
            for i in range(rows*col, rows*col+rows):
                if i < len(list):
                    result = result + format(list[i]) + '<br>'
            result = result + '</td>'
        return '<table width="100%%"><tr>%s</tr></table>' % result

    def heading(self, title, fgcol, bgcol, extras=''):
        """Format a page heading."""
        return """
<p><table width="100%%" cellspacing=0 cellpadding=0 border=0>
<tr bgcolor="%s"><td>&nbsp;</td>
<td valign=bottom><small><small><br></small></small
><font color="%s" face="helvetica"><br>&nbsp;%s</font></td
><td align=right valign=bottom
><font color="%s" face="helvetica">%s</font></td><td>&nbsp;</td></tr></table>
    """ % (bgcol, fgcol, title, fgcol, extras or '&nbsp;')

    def section(self, title, fgcol, bgcol, contents, width=20,
                prelude='', marginalia=None, gap='&nbsp;&nbsp;&nbsp;'):
        """Format a section with a heading."""
        if marginalia is None:
            marginalia = '&nbsp;' * width
        result = """
<p><table width="100%%" cellspacing=0 cellpadding=0 border=0>
<tr bgcolor="%s"><td rowspan=2>&nbsp;</td>
<td colspan=3 valign=bottom><small><small><br></small></small
><font color="%s" face="helvetica, arial">&nbsp;%s</font></td></tr>
    """ % (bgcol, fgcol, title)
        if prelude:
            result = result + """
<tr><td bgcolor="%s">%s</td>
<td bgcolor="%s" colspan=2>%s</td></tr>
    """ % (bgcol, marginalia, bgcol, prelude)
        result = result + """
<tr><td bgcolor="%s">%s</td><td>%s</td>
    """ % (bgcol, marginalia, gap)

        result = result + '<td width="100%%">%s</td></tr></table>' % contents
        return result

    def bigsection(self, title, *args):
        """Format a section with a big heading."""
        title = '<big><strong>%s</strong></big>' % title
        return apply(self.section, (title,) + args)

    def namelink(self, name, *dicts):
        """Make a link for an identifier, given name-to-URL mappings."""
        for dict in dicts:
            if dict.has_key(name):
                return '<a href="%s">%s</a>' % (dict[name], name)
        return name

    def classlink(self, object, modname, *dicts):
        """Make a link for a class."""
        name = object.__name__
        if object.__module__ != modname:
            name = object.__module__ + '.' + name
        for dict in dicts:
            if dict.has_key(object):
                return '<a href="%s">%s</a>' % (dict[object], name)
        return name

    def modulelink(self, object):
        """Make a link for a module."""
        return '<a href="%s.html">%s</a>' % (object.__name__, object.__name__)

    def modpkglink(self, (name, path, ispackage, shadowed)):
        """Make a link for a module or package to display in an index."""
        if shadowed:
            return '<font color="#909090">%s</font>' % name
        if path:
            url = '%s.%s.html' % (path, name)
        else:
            url = '%s.html' % name
        if ispackage:
            text = '<strong>%s</strong>&nbsp;(package)' % name
        else:
            text = name
        return '<a href="%s">%s</a>' % (url, text)

    def markup(self, text, escape=None, funcs={}, classes={}, methods={}):
        """Mark up some plain text, given a context of symbols to look for.
        Each context dictionary maps object names to anchor names."""
        escape = escape or self.escape
        results = []
        here = 0
        pattern = re.compile(r'\b(((http|ftp)://\S+[\w/])|'
                                r'(RFC[- ]?(\d+))|'
                                r'(self\.)?(\w+))\b')
        while 1:
            match = pattern.search(text, here)
            if not match: break
            start, end = match.span()
            results.append(escape(text[here:start]))

            all, url, scheme, rfc, rfcnum, selfdot, name = match.groups()
            if url:
                results.append('<a href="%s">%s</a>' % (url, escape(url)))
            elif rfc:
                url = 'http://www.rfc-editor.org/rfc/rfc%s.txt' % rfcnum
                results.append('<a href="%s">%s</a>' % (url, escape(rfc)))
            else:
                if text[end:end+1] == '(':
                    results.append(self.namelink(name, methods, funcs, classes))
                elif selfdot:
                    results.append('self.<strong>%s</strong>' % name)
                else:
                    results.append(self.namelink(name, classes))
            here = end
        results.append(escape(text[here:]))
        return join(results, '')

    # ---------------------------------------------- type-specific routines

    def doctree(self, tree, modname, classes={}, parent=None):
        """Produce HTML for a class tree as given by inspect.getclasstree()."""
        result = ''
        for entry in tree:
            if type(entry) is type(()):
                c, bases = entry
                result = result + '<dt><font face="helvetica, arial"><small>'
                result = result + self.classlink(c, modname, classes)
                if bases and bases != (parent,):
                    parents = []
                    for base in bases:
                        parents.append(self.classlink(base, modname, classes))
                    result = result + '(' + join(parents, ', ') + ')'
                result = result + '\n</small></font></dt>'
            elif type(entry) is type([]):
                result = result + \
                    '<dd>\n%s</dd>\n' % self.doctree(entry, modname, classes, c)
        return '<dl>\n%s</dl>\n' % result

    def docmodule(self, object):
        """Produce HTML documentation for a module object."""
        name = object.__name__
        parts = split(name, '.')
        links = []
        for i in range(len(parts)-1):
            links.append(
                '<a href="%s.html"><font color="#ffffff">%s</font></a>' %
                (join(parts[:i+1], '.'), parts[i]))
        linkedname = join(links + parts[-1:], '.')
        head = '<big><big><strong>%s</strong></big></big>' % linkedname
        try:
            path = inspect.getabsfile(object)
            filelink = '<a href="file:%s">%s</a>' % (path, path)
        except TypeError:
            filelink = '(built-in)'
        info = []
        if hasattr(object, '__version__'):
            version = str(object.__version__)
            if version[:11] == '$' + 'Revision: ' and version[-1:] == '$':
                version = strip(version[11:-1])
            info.append('version %s' % self.escape(version))
        if hasattr(object, '__date__'):
            info.append(self.escape(str(object.__date__)))
        if info:
            head = head + ' (%s)' % join(info, ', ')
        result = self.heading(
            head, '#ffffff', '#7799ee', '<a href=".">index</a><br>' + filelink)

        second = lambda list: list[1]
        modules = map(second, inspect.getmembers(object, inspect.ismodule))

        classes, cdict = [], {}
        for key, value in inspect.getmembers(object, inspect.isclass):
            if (inspect.getmodule(value) or object) is object:
                classes.append(value)
                cdict[key] = cdict[value] = '#' + key
        funcs, fdict = [], {}
        for key, value in inspect.getmembers(object, inspect.isroutine):
            if inspect.isbuiltin(value) or inspect.getmodule(value) is object:
                funcs.append(value)
                fdict[key] = '#-' + key
                if inspect.isfunction(value): fdict[value] = fdict[key]
        for c in classes:
            for base in c.__bases__:
                key, modname = base.__name__, base.__module__
                if modname != name and sys.modules.has_key(modname):
                    module = sys.modules[modname]
                    if hasattr(module, key) and getattr(module, key) is base:
                        if not cdict.has_key(key):
                            cdict[key] = cdict[base] = modname + '.html#' + key
        constants = []
        for key, value in inspect.getmembers(object, isconstant):
            if key[:1] != '_':
                constants.append((key, value))

        doc = self.markup(getdoc(object), self.preformat, fdict, cdict)
        doc = doc and '<tt>%s</tt>' % doc
        result = result + '<p><small>%s</small></p>\n' % doc

        if hasattr(object, '__path__'):
            modpkgs = []
            modnames = []
            for file in os.listdir(object.__path__[0]):
                if file[:1] != '_':
                    path = os.path.join(object.__path__[0], file)
                    modname = modulename(file)
                    if modname and modname not in modnames:
                        modpkgs.append((modname, name, 0, 0))
                        modnames.append(modname)
                    elif ispackage(path):
                        modpkgs.append((file, name, 1, 0))
            modpkgs.sort()
            contents = self.multicolumn(modpkgs, self.modpkglink)
            result = result + self.bigsection(
                'Package Contents', '#ffffff', '#aa55cc', contents)

        elif modules:
            contents = self.multicolumn(modules, self.modulelink)
            result = result + self.bigsection(
                'Modules', '#fffff', '#aa55cc', contents)

        if classes:
            contents = self.doctree(
                inspect.getclasstree(classes, 1), name, cdict)
            for item in classes:
                contents = contents + self.document(item, fdict, cdict)
            result = result + self.bigsection(
                'Classes', '#ffffff', '#ee77aa', contents)
        if funcs:
            contents = ''
            for item in funcs:
                contents = contents + self.document(item, fdict, cdict)
            result = result + self.bigsection(
                'Functions', '#ffffff', '#eeaa77', contents)

        if constants:
            contents = ''
            for key, value in constants:
                contents = contents + ('<br><strong>%s</strong> = %s' %
                                       (key, self.repr(value)))
            result = result + self.bigsection(
                'Constants', '#ffffff', '#55aa55', contents)

        if hasattr(object, '__author__'):
            contents = self.markup(str(object.__author__), self.preformat)
            result = result + self.bigsection(
                'Author', '#ffffff', '#7799ee', contents)

        if hasattr(object, '__credits__'):
            contents = self.markup(str(object.__credits__), self.preformat)
            result = result + self.bigsection(
                'Credits', '#ffffff', '#7799ee', contents)

        return result

    def docclass(self, object, funcs={}, classes={}):
        """Produce HTML documentation for a class object."""
        name = object.__name__
        bases = object.__bases__
        contents = ''

        methods, mdict = [], {}
        for key, value in inspect.getmembers(object, inspect.ismethod):
            methods.append(value)
            mdict[key] = mdict[value] = '#' + name + '-' + key
        for item in methods:
            contents = contents + self.document(
                item, funcs, classes, mdict, name)

        title = '<a name="%s">class <strong>%s</strong></a>' % (name, name)
        if bases:
            parents = []
            for base in bases:
                parents.append(self.classlink(base, object.__module__, classes))
            title = title + '(%s)' % join(parents, ', ')
        doc = self.markup(getdoc(object), self.preformat,
                          funcs, classes, mdict)
        if doc: doc = '<small><tt>' + doc + '</tt></small>'
        return self.section(title, '#000000', '#ffc8d8', contents, 10, doc)

    def formatvalue(self, object):
        """Format an argument default value as text."""
        return ('<small><font color="#909090">=%s</font></small>' %
                self.repr(object))

    def docroutine(self, object, funcs={}, classes={}, methods={}, clname=''):
        """Produce HTML documentation for a function or method object."""
        if inspect.ismethod(object): object = object.im_func
        if inspect.isbuiltin(object):
            decl = '<a name="%s"><strong>%s</strong>(...)</a>\n' % (
                clname + '-' + object.__name__, object.__name__)
        else:
            args, varargs, varkw, defaults = inspect.getargspec(object)
            argspec = inspect.formatargspec(
                args, varargs, varkw, defaults, formatvalue=self.formatvalue)

            if object.__name__ == '<lambda>':
                decl = '<em>lambda</em> ' + argspec[1:-1]
            else:
                anchor = clname + '-' + object.__name__
                decl = '<a name="%s"\n><strong>%s</strong>%s</a>\n' % (
                    anchor, object.__name__, argspec)
        doc = self.markup(getdoc(object), self.preformat,
                          funcs, classes, methods)
        doc = replace(doc, ('<br>\n', '</tt></small\n><dd><small><tt>'))
        doc = doc and '<tt>%s</tt>' % doc
        return '<dl><dt>%s<dd><small>%s</small></dl>' % (decl, doc)

    def page(self, object):
        """Produce a complete HTML page of documentation for an object."""
        return '''
<!doctype html public "-//W3C//DTD HTML 4.0 Transitional//EN">
<html><title>Python: %s</title><body bgcolor="#ffffff">
%s
</body></html>
''' % (describe(object), self.document(object))

    def index(self, dir, shadowed=None):
        """Generate an HTML index for a directory of modules."""
        modpkgs = []
        if shadowed is None: shadowed = {}
        seen = {}
        files = os.listdir(dir)

        def found(name, ispackage,
                  modpkgs=modpkgs, shadowed=shadowed, seen=seen):
            if not seen.has_key(name):
                modpkgs.append((name, '', ispackage, shadowed.has_key(name)))
                seen[name] = 1
                shadowed[name] = 1

        # Package spam/__init__.py takes precedence over module spam.py.
        for file in files:
            path = os.path.join(dir, file)
            if ispackage(path): found(file, 1)
        for file in files:
            path = os.path.join(dir, file)
            if file[:1] != '_' and os.path.isfile(path):
                modname = modulename(file)
                if modname: found(modname, 0)

        modpkgs.sort()
        contents = self.multicolumn(modpkgs, self.modpkglink)
        return self.bigsection(dir, '#ffffff', '#ee77aa', contents)

# -------------------------------------------- text documentation generator

class TextRepr(Repr):
    """Class for safely making a text representation of a Python object."""
    def __init__(self):
        Repr.__init__(self)
        self.maxlist = self.maxtuple = self.maxdict = 10
        self.maxstring = self.maxother = 50

    def repr1(self, x, level):
        methodname = 'repr_' + join(split(type(x).__name__), '_')
        if hasattr(self, methodname):
            return getattr(self, methodname)(x, level)
        else:
            return cram(stripid(repr(x)), self.maxother)

    def repr_string(self, x, level):
        test = cram(x, self.maxstring)
        testrepr = repr(test)
        if '\\' in test and '\\' not in replace(testrepr, (r'\\', '')):
            # Backslashes are only literal in the string and are never
            # needed to make any special characters, so show a raw string.
            return 'r' + testrepr[0] + test + testrepr[0]
        return testrepr

    def repr_instance(self, x, level):
        try:
            return cram(stripid(repr(x)), self.maxstring)
        except:
            return '<%s instance>' % x.__class__.__name__

class TextDoc(Doc):
    """Formatter class for text documentation."""

    # ------------------------------------------- text formatting utilities

    _repr_instance = TextRepr()
    repr = _repr_instance.repr

    def bold(self, text):
        """Format a string in bold by overstriking."""
        return join(map(lambda ch: ch + '\b' + ch, text), '')

    def indent(self, text, prefix='    '):
        """Indent text by prepending a given prefix to each line."""
        if not text: return ''
        lines = split(text, '\n')
        lines = map(lambda line, prefix=prefix: prefix + line, lines)
        if lines: lines[-1] = rstrip(lines[-1])
        return join(lines, '\n')

    def section(self, title, contents):
        """Format a section with a given heading."""
        return self.bold(title) + '\n' + rstrip(self.indent(contents)) + '\n\n'

    # ---------------------------------------------- type-specific routines

    def doctree(self, tree, modname, parent=None, prefix=''):
        """Render in text a class tree as returned by inspect.getclasstree()."""
        result = ''
        for entry in tree:
            if type(entry) is type(()):
                cl, bases = entry
                result = result + prefix + classname(cl, modname)
                if bases and bases != (parent,):
                    parents = map(lambda cl, m=modname: classname(cl, m), bases)
                    result = result + '(%s)' % join(parents, ', ')
                result = result + '\n'
            elif type(entry) is type([]):
                result = result + self.doctree(
                    entry, modname, cl, prefix + '    ')
        return result

    def docmodule(self, object):
        """Produce text documentation for a given module object."""
        result = ''

        name = object.__name__
        lines = split(strip(getdoc(object)), '\n')
        if len(lines) == 1:
            if lines[0]: name = name + ' - ' + lines[0]
            lines = []
        elif len(lines) >= 2 and not rstrip(lines[1]):
            if lines[0]: name = name + ' - ' + lines[0]
            lines = lines[2:]
        result = result + self.section('NAME', name)
        try: file = inspect.getabsfile(object)
        except TypeError: file = '(built-in)'
        result = result + self.section('FILE', file)
        if lines:
            result = result + self.section('DESCRIPTION', join(lines, '\n'))

        classes = []
        for key, value in inspect.getmembers(object, inspect.isclass):
            if (inspect.getmodule(value) or object) is object:
                classes.append(value)
        funcs = []
        for key, value in inspect.getmembers(object, inspect.isroutine):
            if inspect.isbuiltin(value) or inspect.getmodule(value) is object:
                funcs.append(value)
        constants = []
        for key, value in inspect.getmembers(object, isconstant):
            if key[:1] != '_':
                constants.append((key, value))

        if hasattr(object, '__path__'):
            modpkgs = []
            for file in os.listdir(object.__path__[0]):
                if file[:1] != '_':
                    path = os.path.join(object.__path__[0], file)
                    modname = modulename(file)
                    if modname and modname not in modpkgs:
                        modpkgs.append(modname)
                    elif ispackage(path):
                        modpkgs.append(file + ' (package)')
            modpkgs.sort()
            result = result + self.section(
                'PACKAGE CONTENTS', join(modpkgs, '\n'))

        if classes:
            contents = self.doctree(
                inspect.getclasstree(classes, 1), object.__name__) + '\n'
            for item in classes:
                contents = contents + self.document(item) + '\n'
            result = result + self.section('CLASSES', contents)

        if funcs:
            contents = ''
            for item in funcs:
                contents = contents + self.document(item) + '\n'
            result = result + self.section('FUNCTIONS', contents)

        if constants:
            contents = ''
            for key, value in constants:
                line = key + ' = ' + self.repr(value)
                chop = 70 - len(line)
                line = self.bold(key) + ' = ' + self.repr(value)
                if chop < 0: line = line[:chop] + '...'
                contents = contents + line + '\n'
            result = result + self.section('CONSTANTS', contents)

        if hasattr(object, '__version__'):
            version = str(object.__version__)
            if version[:11] == '$' + 'Revision: ' and version[-1:] == '$':
                version = strip(version[11:-1])
            result = result + self.section('VERSION', version)
        if hasattr(object, '__date__'):
            result = result + self.section('DATE', str(object.__date__))
        if hasattr(object, '__author__'):
            result = result + self.section('AUTHOR', str(object.__author__))
        if hasattr(object, '__credits__'):
            result = result + self.section('CREDITS', str(object.__credits__))
        return result

    def docclass(self, object):
        """Produce text documentation for a given class object."""
        name = object.__name__
        bases = object.__bases__

        title = 'class ' + self.bold(name)
        if bases:
            parents = map(lambda c, m=object.__module__: classname(c, m), bases)
            title = title + '(%s)' % join(parents, ', ')

        doc = getdoc(object)
        contents = doc and doc + '\n'
        methods = map(lambda (key, value): value,
                      inspect.getmembers(object, inspect.ismethod))
        for item in methods:
            contents = contents + '\n' + self.document(item)

        if not contents: return title + '\n'
        return title + '\n' + self.indent(rstrip(contents), ' |  ') + '\n'

    def formatvalue(self, object):
        """Format an argument default value as text."""
        return '=' + self.repr(object)

    def docroutine(self, object):
        """Produce text documentation for a function or method object."""
        if inspect.ismethod(object): object = object.im_func
        if inspect.isbuiltin(object):
            decl = self.bold(object.__name__) + '(...)'
        else:
            args, varargs, varkw, defaults = inspect.getargspec(object)
            argspec = inspect.formatargspec(
                args, varargs, varkw, defaults, formatvalue=self.formatvalue)
            if object.__name__ == '<lambda>':
                decl = '<lambda> ' + argspec[1:-1]
            else:
                decl = self.bold(object.__name__) + argspec
        doc = getdoc(object)
        if doc:
            return decl + '\n' + rstrip(self.indent(doc)) + '\n'
        else:
            return decl + '\n'

# --------------------------------------------------------- user interfaces

def pager(text):
    """The first time this is called, determine what kind of pager to use."""
    global pager
    pager = getpager()
    pager(text)

def getpager():
    """Decide what method to use for paging through text."""
    if type(sys.stdout) is not types.FileType:
        return plainpager
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return plainpager
    if os.environ.has_key('PAGER'):
        return lambda a: pipepager(a, os.environ['PAGER'])
    if sys.platform == 'win32':
        return lambda a: tempfilepager(a, 'more <')
    if hasattr(os, 'system') and os.system('less 2>/dev/null') == 0:
        return lambda a: pipepager(a, 'less')

    import tempfile
    filename = tempfile.mktemp()
    open(filename, 'w').close()
    try:
        if hasattr(os, 'system') and os.system('more %s' % filename) == 0:
            return lambda text: pipepager(text, 'more')
        else:
            return ttypager
    finally:
        os.unlink(filename)

def pipepager(text, cmd):
    """Page through text by feeding it to another program."""
    pipe = os.popen(cmd, 'w')
    try:
        pipe.write(text)
        pipe.close()
    except IOError:
        # Ignore broken pipes caused by quitting the pager program.
        pass

def tempfilepager(text, cmd):
    """Page through text by invoking a program on a temporary file."""
    import tempfile
    filename = tempfile.mktemp()
    file = open(filename, 'w')
    file.write(text)
    file.close()
    try:
        os.system(cmd + ' ' + filename)
    finally:
        os.unlink(filename)

def plain(text):
    """Remove boldface formatting from text."""
    return re.sub('.\b', '', text)

def ttypager(text):
    """Page through text on a text terminal."""
    lines = split(plain(text), '\n')
    try:
        import tty
        fd = sys.stdin.fileno()
        old = tty.tcgetattr(fd)
        tty.setcbreak(fd)
        getchar = lambda: sys.stdin.read(1)
    except (ImportError, AttributeError):
        tty = None
        getchar = lambda: sys.stdin.readline()[:-1][:1]

    try:
        r = inc = os.environ.get('LINES', 25) - 1
        sys.stdout.write(join(lines[:inc], '\n') + '\n')
        while lines[r:]:
            sys.stdout.write('-- more --')
            sys.stdout.flush()
            c = getchar()

            if c in ['q', 'Q']:
                sys.stdout.write('\r          \r')
                break
            elif c in ['\r', '\n']:
                sys.stdout.write('\r          \r' + lines[r] + '\n')
                r = r + 1
                continue
            if c in ['b', 'B', '\x1b']:
                r = r - inc - inc
                if r < 0: r = 0
            sys.stdout.write('\n' + join(lines[r:r+inc], '\n') + '\n')
            r = r + inc

    finally:
        if tty:
            tty.tcsetattr(fd, tty.TCSAFLUSH, old)

def plainpager(text):
    """Simply print unformatted text.  This is the ultimate fallback."""
    sys.stdout.write(plain(text))

def describe(thing):
    """Produce a short description of the given kind of thing."""
    if inspect.ismodule(thing):
        if thing.__name__ in sys.builtin_module_names:
            return 'built-in module ' + thing.__name__
        if hasattr(thing, '__path__'):
            return 'package ' + thing.__name__
        else:
            return 'module ' + thing.__name__
    if inspect.isbuiltin(thing):
        return 'built-in function ' + thing.__name__
    if inspect.isclass(thing):
        return 'class ' + thing.__name__
    if inspect.isfunction(thing):
        return 'function ' + thing.__name__
    if inspect.ismethod(thing):
        return 'method ' + thing.__name__
    return repr(thing)

def locate(path):
    """Locate an object by name (or dotted path), importing as necessary."""
    if not path: # special case: imp.find_module('') strangely succeeds
        return None, None
    if type(path) is not types.StringType:
        return None, path
    parts = split(path, '.')
    n = 1
    while n <= len(parts):
        path = join(parts[:n], '.')
        try:
            module = __import__(path)
            module = reload(module)
        except:
            # determine if error occurred before or after module was found
            if sys.modules.has_key(path):
                filename = sys.modules[path].__file__
            elif sys.exc_type is SyntaxError:
                filename = sys.exc_value.filename
            else:
                # module not found, so stop looking
                break
            # error occurred in the imported module, so report it
            raise DocImportError(filename, sys.exc_type, sys.exc_value)
        try:
            x = module
            for p in parts[1:]:
                x = getattr(x, p)
            return join(parts[:-1], '.'), x
        except AttributeError:
            n = n + 1
            continue
    if hasattr(__builtins__, path):
        return None, getattr(__builtins__, path)
    return None, None

# --------------------------------------- interactive interpreter interface

text = TextDoc()
html = HTMLDoc()

def doc(thing):
    """Display documentation on an object (for interactive use)."""
    if type(thing) is type(""):
        try:
            path, x = locate(thing)
        except DocImportError, value:
            print 'Problem in %s - %s' % (value.filename, value.args)
            return
        if x:
            thing = x
        else:
            print 'No Python documentation found for %s.' % repr(thing)
            return

    desc = describe(thing)
    module = inspect.getmodule(thing)
    if module and module is not thing:
        desc = desc + ' in module ' + module.__name__
    pager('Help on %s:\n\n' % desc + text.document(thing))

def writedoc(key):
    """Write HTML documentation to a file in the current directory."""
    path, object = locate(key)
    if object:
        file = open(key + '.html', 'w')
        file.write(html.page(object))
        file.close()
        print 'wrote', key + '.html'

class Helper:
    def __repr__(self):
        return """To get help on a Python object, call help(object).
To get help on a module or package, either import it before calling
help(module) or call help('modulename')."""

    def __call__(self, *args):
        if args:
            doc(args[0])
        else:
            print repr(self)

help = Helper()

def man(key):
    """Display documentation on an object in a form similar to man(1)."""
    path, object = locate(key)
    if object:
        title = 'Python Library Documentation: ' + describe(object)
        if path: title = title + ' in ' + path
        pager('\n' + title + '\n\n' + text.document(object))
        found = 1
    else:
        print 'No Python documentation found for %s.' % repr(key)

class Scanner:
    """A generic tree iterator."""
    def __init__(self, roots, children, recurse):
        self.roots = roots[:]
        self.state = []
        self.children = children
        self.recurse = recurse

    def next(self):
        if not self.state:
            if not self.roots:
                return None
            root = self.roots.pop(0)
            self.state = [(root, self.children(root))]
        node, children = self.state[-1]
        if not children:
            self.state.pop()
            return self.next()
        child = children.pop(0)
        if self.recurse(child):
            self.state.append((child, self.children(child)))
        return child

class ModuleScanner(Scanner):
    """An interruptible scanner that searches module synopses."""
    def __init__(self):
        roots = map(lambda dir: (dir, ''), pathdirs())
        Scanner.__init__(self, roots, self.submodules, self.ispackage)

    def submodules(self, (dir, package)):
        children = []
        for file in os.listdir(dir):
            path = os.path.join(dir, file)
            if ispackage(path): 
                children.append((path, package + (package and '.') + file))
            else:
                children.append((path, package))
        children.sort()
        return children

    def ispackage(self, (dir, package)):
        return ispackage(dir)

    def run(self, key, callback, completer=None):
        self.quit = 0
        seen = {}

        for modname in sys.builtin_module_names:
            if modname != '__main__':
                seen[modname] = 1
                desc = split(__import__(modname).__doc__ or '', '\n')[0]
                if find(lower(modname + ' - ' + desc), lower(key)) >= 0:
                    callback(None, modname, desc)

        while not self.quit:
            node = self.next()
            if not node: break
            path, package = node
            modname = modulename(path)
            if os.path.isfile(path) and modname:
                modname = package + (package and '.') + modname
                if not seen.has_key(modname):
                    seen[modname] = 1
                    desc = synopsis(path) or ''
                    if find(lower(modname + ' - ' + desc), lower(key)) >= 0:
                        callback(path, modname, desc)
        if completer: completer()

def apropos(key):
    """Print all the one-line module summaries that contain a substring."""
    def callback(path, modname, desc):
        if modname[-9:] == '.__init__':
            modname = modname[:-9] + ' (package)'
        print modname, '-', desc or '(no description)'
    ModuleScanner().run(key, callback)

# --------------------------------------------------- web browser interface

def serve(port, callback=None):
    import BaseHTTPServer, mimetools, select

    # Patch up mimetools.Message so it doesn't break if rfc822 is reloaded.
    class Message(mimetools.Message):
        def __init__(self, fp, seekable=1):
            Message = self.__class__
            Message.__bases__[0].__bases__[0].__init__(self, fp, seekable)
            self.encodingheader = self.getheader('content-transfer-encoding')
            self.typeheader = self.getheader('content-type')
            self.parsetype()
            self.parseplist()

    class DocHandler(BaseHTTPServer.BaseHTTPRequestHandler):
        def send_document(self, title, contents):
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write('''
<!doctype html public "-//W3C//DTD HTML 4.0 Transitional//EN">
<html><title>Python: %s</title><body bgcolor="#ffffff">
%s
</body></html>''' % (title, contents))
            except IOError: pass

        def do_GET(self):
            path = self.path
            if path[-5:] == '.html': path = path[:-5]
            if path[:1] == '/': path = path[1:]
            if path and path != '.':
                try:
                    p, x = locate(path)
                except DocImportError, value:
                    self.send_document(path, html.escape(
                        'Problem in %s - %s' % (value.filename, value.args)))
                    return
                if x:
                    self.send_document(describe(x), html.document(x))
                else:
                    self.send_document(path,
'No Python documentation found for %s.' % repr(path))
            else:
                heading = html.heading(
'<big><big><strong>Python: Index of Modules</strong></big></big>',
'#ffffff', '#7799ee')
                def bltinlink(name):
                    return '<a href="%s.html">%s</a>' % (name, name)
                names = filter(lambda x: x != '__main__', sys.builtin_module_names)
                contents = html.multicolumn(names, bltinlink)
                indices = ['<p>' + html.bigsection(
                    'Built-in Modules', '#ffffff', '#ee77aa', contents)]

                seen = {}
                for dir in pathdirs():
                    indices.append(html.index(dir, seen))
                contents = heading + join(indices) + """<p align=right>
<small><small><font color="#909090" face="helvetica, arial"><strong>
pydoc</strong> by Ka-Ping Yee &lt;ping@lfw.org&gt;</font></small></small>"""
                self.send_document('Index of Modules', contents)

        def log_message(self, *args): pass

    class DocServer(BaseHTTPServer.HTTPServer):
        def __init__(self, port, callback):
            self.address = ('127.0.0.1', port)
            self.url = 'http://127.0.0.1:%d/' % port
            self.callback = callback
            self.base.__init__(self, self.address, self.handler)

        def serve_until_quit(self):
            import select
            self.quit = 0
            while not self.quit:
                rd, wr, ex = select.select([self.socket.fileno()], [], [], 1)
                if rd: self.handle_request()

        def server_activate(self):
            self.base.server_activate(self)
            if self.callback: self.callback(self)

    DocServer.base = BaseHTTPServer.HTTPServer
    DocServer.handler = DocHandler
    DocHandler.MessageClass = Message
    try:
        DocServer(port, callback).serve_until_quit()
    except (KeyboardInterrupt, select.error):
        pass
    print 'server stopped'

# ----------------------------------------------------- graphical interface

def gui():
    """Graphical interface (starts web server and pops up a control window)."""
    class GUI:
        def __init__(self, window, port=7464):
            self.window = window
            self.server = None
            self.scanner = None

            import Tkinter
            self.server_frm = Tkinter.Frame(window)
            self.title_lbl = Tkinter.Label(self.server_frm,
                text='Starting server...\n ')
            self.open_btn = Tkinter.Button(self.server_frm,
                text='open browser', command=self.open, state='disabled')
            self.quit_btn = Tkinter.Button(self.server_frm,
                text='quit serving', command=self.quit, state='disabled')

            self.search_frm = Tkinter.Frame(window)
            self.search_lbl = Tkinter.Label(self.search_frm, text='Search for')
            self.search_ent = Tkinter.Entry(self.search_frm)
            self.search_ent.bind('<Return>', self.search)
            self.stop_btn = Tkinter.Button(self.search_frm,
                text='stop', pady=0, command=self.stop, state='disabled')
            if sys.platform == 'win32':
                # Trying to hide and show this button crashes under Windows.
                self.stop_btn.pack(side='right')

            self.window.title('pydoc')
            self.window.protocol('WM_DELETE_WINDOW', self.quit)
            self.title_lbl.pack(side='top', fill='x')
            self.open_btn.pack(side='left', fill='x', expand=1)
            self.quit_btn.pack(side='right', fill='x', expand=1)
            self.server_frm.pack(side='top', fill='x')

            self.search_lbl.pack(side='left')
            self.search_ent.pack(side='right', fill='x', expand=1)
            self.search_frm.pack(side='top', fill='x')
            self.search_ent.focus_set()

            font = ('helvetica', sys.platform == 'win32' and 8 or 10)
            self.result_lst = Tkinter.Listbox(window, font=font, height=6)
            self.result_lst.bind('<Button-1>', self.select)
            self.result_lst.bind('<Double-Button-1>', self.goto)
            self.result_scr = Tkinter.Scrollbar(window,
                orient='vertical', command=self.result_lst.yview)
            self.result_lst.config(yscrollcommand=self.result_scr.set)

            self.result_frm = Tkinter.Frame(window)
            self.goto_btn = Tkinter.Button(self.result_frm,
                text='go to selected', command=self.goto)
            self.hide_btn = Tkinter.Button(self.result_frm,
                text='hide results', command=self.hide)
            self.goto_btn.pack(side='left', fill='x', expand=1)
            self.hide_btn.pack(side='right', fill='x', expand=1)

            self.window.update()
            self.minwidth = self.window.winfo_width()
            self.minheight = self.window.winfo_height()
            self.bigminheight = (self.server_frm.winfo_reqheight() +
                                 self.search_frm.winfo_reqheight() +
                                 self.result_lst.winfo_reqheight() +
                                 self.result_frm.winfo_reqheight())
            self.bigwidth, self.bigheight = self.minwidth, self.bigminheight
            self.expanded = 0
            self.window.wm_geometry('%dx%d' % (self.minwidth, self.minheight))
            self.window.wm_minsize(self.minwidth, self.minheight)

            import threading
            threading.Thread(target=serve, args=(port, self.ready)).start()

        def ready(self, server):
            self.server = server
            self.title_lbl.config(
                text='Python documentation server at\n' + server.url)
            self.open_btn.config(state='normal')
            self.quit_btn.config(state='normal')

        def open(self, event=None, url=None):
            url = url or self.server.url
            try:
                import webbrowser
                webbrowser.open(url)
            except ImportError: # pre-webbrowser.py compatibility
                if sys.platform == 'win32':
                    os.system('start "%s"' % url)
                elif sys.platform == 'mac':
                    try:
                        import ic
                        ic.launchurl(url)
                    except ImportError: pass
                else:
                    rc = os.system('netscape -remote "openURL(%s)" &' % url)
                    if rc: os.system('netscape "%s" &' % url)

        def quit(self, event=None):
            if self.server:
                self.server.quit = 1
            self.window.quit()

        def search(self, event=None):
            key = self.search_ent.get()
            self.stop_btn.pack(side='right')
            self.stop_btn.config(state='normal')
            self.search_lbl.config(text='Searching for "%s"...' % key)
            self.search_ent.forget()
            self.search_lbl.pack(side='left')
            self.result_lst.delete(0, 'end')
            self.goto_btn.config(state='disabled')
            self.expand()

            import threading
            if self.scanner:
                self.scanner.quit = 1
            self.scanner = ModuleScanner()
            threading.Thread(target=self.scanner.run,
                             args=(key, self.update, self.done)).start()

        def update(self, path, modname, desc):
            if modname[-9:] == '.__init__':
                modname = modname[:-9] + ' (package)'
            self.result_lst.insert('end',
                modname + ' - ' + (desc or '(no description)'))

        def stop(self, event=None):
            if self.scanner:
                self.scanner.quit = 1
                self.scanner = None

        def done(self):
            self.scanner = None
            self.search_lbl.config(text='Search for')
            self.search_lbl.pack(side='left')
            self.search_ent.pack(side='right', fill='x', expand=1)
            if sys.platform != 'win32': self.stop_btn.forget()
            self.stop_btn.config(state='disabled')

        def select(self, event=None):
            self.goto_btn.config(state='normal')

        def goto(self, event=None):
            selection = self.result_lst.curselection()
            if selection:
                modname = split(self.result_lst.get(selection[0]))[0]
                self.open(url=self.server.url + modname + '.html')

        def collapse(self):
            if not self.expanded: return
            self.result_frm.forget()
            self.result_scr.forget()
            self.result_lst.forget()
            self.bigwidth = self.window.winfo_width()
            self.bigheight = self.window.winfo_height()
            self.window.wm_geometry('%dx%d' % (self.minwidth, self.minheight))
            self.window.wm_minsize(self.minwidth, self.minheight)
            self.expanded = 0

        def expand(self):
            if self.expanded: return
            self.result_frm.pack(side='bottom', fill='x')
            self.result_scr.pack(side='right', fill='y')
            self.result_lst.pack(side='top', fill='both', expand=1)
            self.window.wm_geometry('%dx%d' % (self.bigwidth, self.bigheight))
            self.window.wm_minsize(self.minwidth, self.bigminheight)
            self.expanded = 1

        def hide(self, event=None):
            self.stop()
            self.collapse()

    import Tkinter
    try:
        gui = GUI(Tkinter.Tk())
        Tkinter.mainloop()
    except KeyboardInterrupt:
        pass

# -------------------------------------------------- command-line interface

def cli():
    """Command-line interface (looks at sys.argv to decide what to do)."""
    import getopt
    class BadUsage: pass

    try:
        if sys.platform in ['mac', 'win32'] and not sys.argv[1:]:
            # graphical platforms with threading (and no CLI)
            gui()
            return

        opts, args = getopt.getopt(sys.argv[1:], 'gk:p:w')
        writing = 0

        for opt, val in opts:
            if opt == '-g':
                gui()
                return
            if opt == '-k':
                apropos(val)
                return
            if opt == '-p':
                try:
                    port = int(val)
                except ValueError:
                    raise BadUsage
                def ready(server):
                    print 'server ready at %s' % server.url
                serve(port, ready)
                return
            if opt == '-w':
                writing = 1

        if not args: raise BadUsage
        for arg in args:
            try:
                if find(arg, os.sep) >= 0 and os.path.isfile(arg):
                    arg = importfile(arg)
                if writing: writedoc(arg)
                else: man(arg)
            except DocImportError, value:
                print 'Problem in %s - %s' % (value.filename, value.args)

    except (getopt.error, BadUsage):
        cmd = sys.argv[0]
        print """pydoc - the Python documentation tool

%s <name> ...
    Show text documentation on something.  <name> may be the name of a
    function, module, or package, or a dotted reference to a class or
    function within a module or module in a package.  If <name> contains
    a '%s', it is used as the path to a Python source file to document.

%s -k <keyword>
    Search for a keyword in the synopsis lines of all available modules.

%s -p <port>
    Start an HTTP server on the given port on the local machine.

%s -g
    Pop up a graphical interface for serving and finding documentation.

%s -w <name> ...
    Write out the HTML documentation for a module to a file in the current
    directory.  If <name> contains a '%s', it is treated as a filename.
""" % (cmd, os.sep, cmd, cmd, cmd, cmd, os.sep)

if __name__ == '__main__': cli()


