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

from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException
from selenium import webdriver
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


class MonthClickRetryTest(unittest.TestCase):

    def setUp(self):
        self.scraper = DeputyWebDriver(mock.Mock())
        self.scraper.current_month_index = 3
        self.previous = mock.Mock(text='febrero')
        selected = mock.Mock(text='marzo')
        self.select = self.enterContext(mock.patch.object(dg_gastos, 'Select'))
        self.select.return_value.options = [self.previous, selected]
        self.select.return_value.first_selected_option = selected
        self.find_dropdown = self.enterContext(
            mock.patch.object(self.scraper.webdriver_wait, 'until'))

    def test_persistent_click_failure_raises_after_three_attempts(self):
        for exception in (ElementClickInterceptedException, StaleElementReferenceException):
            with self.subTest(exception=exception.__name__):
                self.previous.click.reset_mock()
                self.find_dropdown.reset_mock()
                failure = exception('click failed')
                self.previous.click.side_effect = [failure] * 10 + [
                    AssertionError('Month selection did not stop retrying')]

                with self.assertRaisesRegex(RuntimeError, 'seleccionar el mes tras 3 intentos') as error:
                    self.scraper.set_one_month_backward()

                self.assertIs(error.exception.__cause__, failure)
                self.assertEqual(self.previous.click.call_count, 3)
                self.assertEqual(self.find_dropdown.call_count, 3)
                self.assertEqual(self.scraper.current_month_index, 3)

    def test_transient_click_failure_retries_and_updates_month(self):
        self.previous.click.side_effect = StaleElementReferenceException()
        initial_dropdown, refreshed_dropdown = mock.Mock(), mock.Mock()
        self.find_dropdown.side_effect = [initial_dropdown, refreshed_dropdown]
        refreshed_previous = mock.Mock(text='febrero')
        refreshed_selected = mock.Mock(text='marzo')
        refreshed_select = mock.Mock(options=[refreshed_previous, refreshed_selected],
                                     first_selected_option=refreshed_selected)
        self.select.side_effect = [self.select.return_value, refreshed_select]

        self.assertTrue(self.scraper.set_one_month_backward())

        self.previous.click.assert_called_once_with()
        refreshed_previous.click.assert_called_once_with()
        self.assertEqual(self.select.call_args_list,
                         [mock.call(initial_dropdown), mock.call(refreshed_dropdown)])
        self.assertEqual(self.find_dropdown.call_count, 2)
        self.assertEqual(self.scraper.current_month_index, 2)


if __name__ == '__main__':
    unittest.main()
