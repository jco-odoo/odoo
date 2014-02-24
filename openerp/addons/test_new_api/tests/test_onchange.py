# -*- coding: utf-8 -*-
import unittest2
from openerp.tests import common

class TestOnChange(common.TransactionCase):
    def setUp(self):
        super(TestOnChange, self).setUp()
        self.Model = self.registry('test_new_api.on_change')

    @unittest2.expectedFailure
    def test_default_get(self):
        # default_get behavior makes no sense? store=False fields are
        # completely ignored, but Field.null() does not matter a bit so this
        # yields a default for description but not trick or name_size
        fields = self.Model.fields_get()
        values = self.Model.default_get(fields.keys())
        self.assertEqual(values, {})

    @unittest2.expectedFailure
    def test_get_field(self):
        # BaseModel.__getattr__ always falls back to _get_field without caring
        # whether what is requested is or is not a field. And _get_field expects
        # to be called on a record and a record only, not on a model
        with self.assertRaises(AttributeError):
            self.Model.not_really_a_method()

    def test_new_onchange(self):
        result = self.Model.onchange('name', {
            'name': u"Bob the Builder",
            'name_size': 0,
            'name_utf8_size': 0,
            'description': False,
        })
        self.assertEqual(result['value'], {
            'name_size': 15,
            'name_utf8_size': 15,
            'description': u"Bob the Builder (15:15)",
        })

        result = self.Model.onchange('description', {
            'name': u"Bob the Builder",
            'name_size': 15,
            'name_utf8_size': 15,
            'description': u"Can we fix it? Yes we can!",
        })
        self.assertEqual(result['value'], {})

    def test_new_onchange_one2many(self):
        tocheck = ['lines.name']

        result = self.Model.onchange('name', {
            'name': u"Bob the Builder",
            'name_size': 0,
            'name_utf8_size': 0,
            'description': False,
            'lines': [(0, 0, {'name': False})]
        }, tocheck)
        self.assertEqual(result['value'], {
            'name_size': 15,
            'name_utf8_size': 15,
            'description': u"Bob the Builder (15:15)",
            'lines': [(0, 0, {'name': u"Bob the Builder (15)"})],
        })

        # create a new line
        line = self.registry('test_new_api.on_change_line').create({})
        self.assertFalse(line.name)

        # include the line in a new record
        result = self.Model.onchange('name', {
            'name': u"Bob the Builder",
            'name_size': 0,
            'name_utf8_size': 0,
            'description': False,
            'lines': [(4, line.id)]
        }, tocheck)
        self.assertEqual(result['value'], {
            'name_size': 15,
            'name_utf8_size': 15,
            'description': u"Bob the Builder (15:15)",
            'lines': [(1, line.id, {'name': u"Bob the Builder (15)"})],
        })