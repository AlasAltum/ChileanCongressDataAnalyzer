"""
Runs the scraper's table readers against local copies of the camara.cl
tables in a headless Firefox. Needs the scraper's own dependencies
(selenium, pandas) and Firefox. Run from diputados/, where dg_gastos.py
runs and imports driver_utils:
    python -m unittest test_dg_gastos
"""
import pathlib
import tempfile
import unittest
from unittest import mock

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

import dg_gastos
from dg_gastos import DeputyWebDriver

PAGE = '''<html><body>
<a id="ContentPlaceHolder1_ContentPlaceHolder1_btnAsexterna" href="#"
   onclick="document.title='asesorias'">Asesorías externas</a>
{content}
</body></html>'''
NO_DATA = ('<div id="ContentPlaceHolder1_ContentPlaceHolder1_DetallePlaceHolder_nodata">'
           '<p>Los datos aún no han sido publicados</p></div>')


def table(*rows):
    body = ''.join('<tr>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>'
                   for row in rows)
    return f'<table class="tabla"><tbody>{body}</tbody></table>'


class ScraperBrowserLifecycleTest(unittest.TestCase):

    def setUp(self):
        self.driver = mock.Mock(spec=webdriver.Remote)
        driver_patch = mock.patch.object(dg_gastos, 'get_driver', return_value=self.driver)
        driver_patch.start()
        self.addCleanup(driver_patch.stop)

    def test_main_quits_driver_on_success(self):
        with mock.patch.object(DeputyWebDriver, 'get_deputies_names_from_dropdown',
                               return_value=([], None)):
            dg_gastos.main()

        self.driver.quit.assert_called_once_with()

    def test_main_logs_quit_failure_without_interrupting_success(self):
        error = OSError('Could not stop geckodriver')
        self.driver.quit.side_effect = error

        with mock.patch.object(DeputyWebDriver, 'get_deputies_names_from_dropdown',
                               return_value=([], None)):
            with self.assertLogs(dg_gastos.__name__, level='ERROR') as logs:
                dg_gastos.main()

        self.assertIs(logs.records[0].exc_info[1], error)
        self.driver.quit.assert_called_once_with()

    def test_main_quits_driver_when_initial_navigation_fails(self):
        error = WebDriverException('Initial navigation failed')
        self.driver.get.side_effect = error

        with self.assertRaises(WebDriverException) as raised:
            dg_gastos.main()

        self.assertIs(raised.exception, error)
        self.driver.quit.assert_called_once_with()

    def test_main_preserves_navigation_error_when_quit_also_fails(self):
        navigation_error = WebDriverException('Initial navigation failed')
        shutdown_error = OSError('Could not stop geckodriver')
        self.driver.get.side_effect = navigation_error
        self.driver.quit.side_effect = shutdown_error

        with self.assertLogs(dg_gastos.__name__, level='ERROR') as logs:
            with self.assertRaises(WebDriverException) as raised:
                dg_gastos.main()

        self.assertIs(raised.exception, navigation_error)
        self.assertIs(logs.records[0].exc_info[1], shutdown_error)
        self.driver.quit.assert_called_once_with()


class DeputyWebDriverLocatorsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        options = webdriver.FirefoxOptions()
        options.add_argument('-headless')
        cls.driver = webdriver.Firefox(options=options)
        cls.pages_dir = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.pages_dir.cleanup()

    def setUp(self):
        for collected in (dg_gastos.operational_costs,
                          dg_gastos.external_consultancies,
                          dg_gastos.support_staff):
            for values in collected.values():
                values.clear()

    def open_scraper_on(self, content: str) -> DeputyWebDriver:
        page = pathlib.Path(self.pages_dir.name, f'{self.id()}.html')
        page.write_text(PAGE.format(content=content), encoding='utf-8')
        with mock.patch.object(dg_gastos, 'FIRST_DIPUTY_URL', page.as_uri()):
            scraper = DeputyWebDriver(self.driver)
        scraper.current_deputy = 'Florcita Alarcón Rojas'
        scraper.current_year = 2021
        scraper.current_month_index = 3
        return scraper

    def test_reads_operational_costs_table(self):
        scraper = self.open_scraper_on(table(('TELEFONÍA', '$43.452'),
                                             ('TRASPASO DESDE GASTOS OPERACIONALES', '$1.000')))

        scraper.get_data_from_operational_costs_table()

        self.assertEqual(dg_gastos.operational_costs, {
            'diputado': ['Florcita Alarcón Rojas'] * 2,
            'Anio': [2021, 2021],
            'Mes': [3, 3],
            'Gastos': ['TELEFONÍA', 'TRASPASO DESDE GASTOS OPERACIONALES'],
            'Montos': ['$43.452', '$1.000'],
        })

    def test_opens_operational_costs_when_link_is_obscured(self):
        destination = pathlib.Path(self.pages_dir.name, 'gastosoperacionales.html')
        destination.write_text('<title>Gastos operacionales</title>', encoding='utf-8')
        scraper = self.open_scraper_on(f'''
            <a id="ContentPlaceHolder1_ContentPlaceHolder1_btGasop"
               href="{destination.name}#ficha-diputados">Gastos operacionales</a>
            <div id="ajax-container">
                <div style="position: relative; top: -2rem; height: 4rem;">Panel de detalle</div>
            </div>
        ''')

        scraper.get_into_operational_costs_section()

        self.assertEqual(self.driver.current_url, f'{destination.as_uri()}#ficha-diputados')
        self.assertEqual(self.driver.title, 'Gastos operacionales')

    def test_detects_month_without_published_data(self):
        scraper = self.open_scraper_on(NO_DATA)

        self.assertIs(scraper._fast_check_if_there_is_data_section(), False)

    def test_opens_and_reads_external_consultancies(self):
        scraper = self.open_scraper_on(
            table(('Ver', '12', '01/03/2021', 'Juan Pérez', 'Informe legislativo', '$822.400')))

        scraper.get_into_external_consultancies()
        scraper.get_data_from_external_consultancies()

        self.assertEqual(self.driver.title, 'asesorias')
        self.assertEqual(dg_gastos.external_consultancies['Asesor'], ['Juan Pérez'])
        self.assertEqual(dg_gastos.external_consultancies['Monto'], ['$822.400'])

    def test_reads_support_staff_table(self):
        scraper = self.open_scraper_on(
            table(('Personal de apoyo', '1', 'Ana Soto', 'Secretaria', '$1.200.000', 'No', '')))

        scraper.get_data_from_support_staff()

        self.assertEqual(dg_gastos.support_staff['Nombre'], ['Ana Soto'])
        self.assertEqual(dg_gastos.support_staff['Sueldo'], ['$1.200.000'])

    def test_steps_through_sparse_month_options_and_stops_at_boundary(self):
        months = ['marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
                  'septiembre', 'octubre', 'noviembre']
        options = ''.join(f'<option value="{number}">{month}</option>'
                          for number, month in enumerate(months[:-1], start=3))
        scraper = self.open_scraper_on(
            f'<select id="{dg_gastos.YEAR_SELECTOR_CSS[1:]}"><option>2026</option></select>'
            f'<select id="{dg_gastos.MONTH_SELECTOR_CSS[1:]}">{options}'
            '<option value="11" selected="selected">noviembre</option></select>')
        scraper._reset_dates_for_another_section()

        def selected_month():
            dropdown = self.driver.find_element(By.CSS_SELECTOR, dg_gastos.MONTH_SELECTOR_CSS)
            return Select(dropdown).first_selected_option.text

        self.assertEqual((selected_month(), scraper.current_month_index), ('noviembre', 11))
        for number, month in reversed(list(enumerate(months[:-1], start=3))):
            with self.subTest(month=month):
                self.assertTrue(scraper.set_one_month_backward())
                self.assertEqual((selected_month(), scraper.current_month_index), (month, number))

        self.assertFalse(scraper.set_one_month_backward())
        self.assertFalse(scraper.there_is_more_data_to_scrap)
        self.assertEqual((selected_month(), scraper.current_month_index), ('marzo', 3))

    def test_starts_previous_year_at_its_last_listed_month(self):
        scraper = self.open_scraper_on(
            f'<select id="{dg_gastos.YEAR_SELECTOR_CSS[1:]}">'
            '<option>2025</option><option selected="selected">2026</option></select>'
            f'<select id="{dg_gastos.MONTH_SELECTOR_CSS[1:]}"><option>marzo</option></select>')
        self.driver.execute_script(
            'const year = document.querySelector(arguments[0]);'
            'const month = document.querySelector(arguments[1]);'
            'year.addEventListener("change", () => {'
            '    month.replaceChildren(new Option("febrero"), new Option("octubre"));'
            '});',
            dg_gastos.YEAR_SELECTOR_CSS, dg_gastos.MONTH_SELECTOR_CSS)
        scraper._reset_dates_for_another_section()

        self.assertTrue(scraper.set_one_month_backward())

        dropdown = self.driver.find_element(By.CSS_SELECTOR, dg_gastos.MONTH_SELECTOR_CSS)
        self.assertEqual(Select(dropdown).first_selected_option.text, 'octubre')
        self.assertEqual((scraper.current_year, scraper.current_month_index), (2025, 10))

    def test_does_not_look_up_month_after_year_exhaustion(self):
        scraper = self.open_scraper_on(
            f'<select id="{dg_gastos.YEAR_SELECTOR_CSS[1:]}"><option>2026</option></select>'
            f'<select id="{dg_gastos.MONTH_SELECTOR_CSS[1:]}">'
            '<option selected="selected">Todos</option></select>')
        scraper._reset_dates_for_another_section()

        set_one_year_backward = scraper.set_one_year_backward

        def exhaust_years():
            result = set_one_year_backward()
            self.driver.execute_script(
                'document.querySelector(arguments[0]).remove()', dg_gastos.MONTH_SELECTOR_CSS)
            return result

        with mock.patch.object(scraper, 'set_one_year_backward', side_effect=exhaust_years):
            self.assertFalse(scraper.set_one_month_backward())
        self.assertFalse(scraper.there_is_more_data_to_scrap)
        self.assertFalse(scraper.set_one_month_backward())


if __name__ == '__main__':
    unittest.main()
