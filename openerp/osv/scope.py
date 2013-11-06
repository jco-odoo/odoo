# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2013 OpenERP (<http://www.openerp.com>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

""" This module provides the elements for managing execution environments or
    "scopes". Scopes are nestable and provides convenient access to shared
    objects. The object :obj:`proxy` is a proxy object to the current scope.
"""

from contextlib import contextmanager
from werkzeug.local import Local, release_local


class ScopeProxy(object):
    """ This a proxy object to the current scope. """
    def __init__(self):
        self._local = Local()

    def release(self):
        """ release the werkzeug local variable """
        release_local(self._local)

    @property
    def stack(self):
        """ return the stack of scopes (as a list) """
        try:
            return self._local.stack
        except AttributeError:
            self._local.stack = stack = []
            return stack

    @property
    def root(self):
        stack = self.stack
        return stack[0] if stack else None

    @property
    def current(self):
        stack = self.stack
        return stack[-1] if stack else None

    def __getitem__(self, name):
        return self.current[name]

    def __getattr__(self, name):
        return getattr(self.current, name)

    def __call__(self, *args, **kwargs):
        # apply current scope or instantiate one
        return (self.current or Scope)(*args, **kwargs)

    @property
    def all_scopes(self):
        """ return the list of known scopes """
        try:
            return self._local.scopes
        except AttributeError:
            self._local.scopes = scopes = []
            return scopes

    def invalidate(self, model, field, ids=None):
        """ Invalidate a field for the given record ids in the caches. """
        for scope in self.all_scopes:
            scope.cache.invalidate(model, field, ids)

    def invalidate_all(self):
        """ Invalidate the record caches in all scopes. """
        for scope in self.all_scopes:
            scope.cache.invalidate_all()

    def check_cache(self):
        """ Check the record caches in all scopes. """
        for scope in self.all_scopes:
            with scope:
                scope.cache.check()

    @property
    def recomputation(self):
        """ Return the recomputation manager object. """
        try:
            return self._local.recomputation
        except AttributeError:
            self._local.recomputation = recomputation = Recomputation()
            return recomputation

    @property
    def draft(self):
        """ Return the draft switch. """
        try:
            return self._local.draft
        except AttributeError:
            self._local.draft = draft = DraftSwitch()
            return draft

proxy = ScopeProxy()


class Scope(object):
    """ A scope wraps environment data for the ORM instances:

         - :attr:`cr`, the current database cursor;
         - :attr:`uid`, the current user id;
         - :attr:`context`, the current context dictionary.

        An execution environment is created by a statement ``with``::

            with Scope(cr, uid, context):
                # statements execute in given scope

                # retrieve environment data
                cr, uid, context = scope.args

        The scope provides extra attributes:

         - :attr:`registry`, the model registry of the current database,
         - :attr:`cache`, a records cache (see :class:`openerp.osv.cache.Cache`),
         - :attr:`draft`, a boolean indicating whether the scope is in draft mode.
    """
    def __new__(cls, cr, uid, context):
        if context is None:
            context = {}
        args = (cr, uid, context)

        # if scope already exists, return it
        scope_list = proxy.all_scopes
        for scope in scope_list:
            if scope.args == args:
                return scope

        # otherwise create scope, and add it in the list
        scope = object.__new__(cls)
        scope.cr, scope.uid, scope.context = scope.args = args
        scope.registry = RegistryManager.get(cr.dbname)
        scope.cache = Cache()
        scope.draft = proxy.draft
        scope_list.append(scope)
        return scope

    def __eq__(self, other):
        if isinstance(other, Scope):
            other = other.args
        return self.args == tuple(other)

    def __ne__(self, other):
        return not self == other

    def __enter__(self):
        proxy.stack.append(self)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        stack = proxy.stack
        stack.pop()
        if not stack:
            proxy.release()

    def __getitem__(self, model_name):
        """ return a given model """
        return self.registry[model_name]

    def __call__(self, cr=None, user=None, context=(), **kwargs):
        """ Return a scope based on `self` with modified parameters.

            :param cr: optional database cursor to change the current cursor
            :param user: optional user/user id to change the current user
            :param context: optional context dictionary to change the current context
            :param kwargs: a set of key-value pairs to update the context
        """
        # determine cr, uid, context
        if cr is None:
            cr = self.cr

        if user is None:
            uid = self.uid
        elif isinstance(user, BaseModel):
            assert user._name == 'res.users'
            uid = user.id
        else:
            uid = user

        if context == ():
            context = self.context
        context = dict(context or {}, **kwargs)

        return Scope(cr, uid, context)

    def SUDO(self):
        """ Return a scope based on `self`, with the superuser. """
        return self(user=SUPERUSER_ID)

    def ref(self, xml_id):
        """ return the record corresponding to the given `xml_id` """
        module, name = xml_id.split('.')
        return self.registry['ir.model.data'].get_object(module, name)

    @property
    def user(self):
        """ return the current user (as an instance) """
        with proxy.SUDO():
            return self.registry['res.users'].browse(self.uid)

    @property
    def lang(self):
        """ return the current language code """
        return self.context.get('lang') or 'en_US'


#
# DraftSwitch - manages the mode switching between draft and non-draft
#

class DraftSwitch(object):
    """ An object that manages the draft mode associated to all the scopes of a
        werkzeug session::

            # calling returns a context manager that switches to draft mode
            with scope.draft():
                # here we are in draft mode

                # testing returns the state
                assert scope.draft

                # nesting has no effect
                with scope.draft():
                    assert scope.draft

            # testing returns the state
            assert not scope.draft
    """
    def __init__(self):
        self._state = False

    def __nonzero__(self):
        return self._state

    @contextmanager
    def __call__(self):
        old = self._state
        self._state = True
        yield
        self._state = old


#
# Recomputation manager - stores the field/record to recompute
#

class Recomputation(object):
    """ Collection of (`field`, `records`) to recompute.
        Use it as a context manager to handle all recomputations at one level
        only, and clear the recomputation manager after an exception.
    """
    _level = 0                          # nesting level for recomputations

    def __init__(self):
        self._todo = {}                 # {field: records, ...}

    def clear(self):
        """ Empty the collection. """
        self._todo.clear()

    def __nonzero__(self):
        return bool(self._todo)

    def __iter__(self):
        return self._todo.iteritems()

    def todo(self, field, records=None):
        """ Add or return records to recompute for `field`. """
        if records is None:
            return self._todo.get(field) or field.model.browse()
        elif records:
            records0 = self._todo.get(field) or field.model.browse()
            self._todo[field] = records0 | records

    def done(self, field, records):
        """ Remove records that have been recomputed for `field`. """
        remain = (self._todo.get(field) or field.model.browse()) - records
        if remain:
            self._todo[field] = remain
        else:
            self._todo.pop(field, None)

    def __enter__(self):
        self._level += 1
        # return an empty collection at higher levels to let the top-level
        # recomputation handle all recomputations
        return () if self._level > 1 else self

    def __exit__(self, exc_type, exc_value, traceback):
        self._level -= 1


# keep those imports here in order to handle cyclic dependencies correctly
from openerp import SUPERUSER_ID
from openerp.osv.cache import Cache
from openerp.osv.orm import BaseModel
from openerp.modules.registry import RegistryManager
