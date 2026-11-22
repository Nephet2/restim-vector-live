import unittest
from unittest.mock import Mock
from vector1a.app import VectorApp


class Variable:
    def __init__(self, value=None):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class HowlDirectorTests(unittest.TestCase):
    def test_all_choices_select_and_report_correct_model(self):
        app = object.__new__(VectorApp)
        app.four_phase_spatial_model = Variable()
        app.director_primary_spatial = Variable()
        app.apply_config = Mock()
        app._save_settings = Mock()
        for choice, model in app.PRIMARY_SPATIAL_MODELS.items():
            app._set_director_primary_spatial(choice)
            self.assertEqual(app.four_phase_spatial_model.get(), model)
            self.assertEqual(app._primary_spatial_choice(), choice)
            self.assertEqual(app.director_primary_spatial.get(), choice)
            self.assertIn(choice, app.PRIMARY_SPATIAL_NAMES)
        app.four_phase_spatial_model.set('Howl Dynamic')
        app._sync_primary_spatial()
        self.assertEqual(app.director_primary_spatial.get(), 'top_howl_dynamic')
        with self.assertRaises(ValueError):
            app._set_director_primary_spatial('invalid')
