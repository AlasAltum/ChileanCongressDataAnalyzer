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
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.command import Command
from selenium.webdriver.support.ui import Select

import dg_gastos
from dg_gastos import DeputyWebDriver

PAGE = '''<html><body>
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
        with mock.patch.object(DeputyWebDriver, 'get_deputies_from_dropdown', return_value=[]):
            dg_gastos.main()

        self.driver.quit.assert_called_once_with()

    def test_main_logs_quit_failure_without_interrupting_success(self):
        error = OSError('Could not stop geckodriver')
        self.driver.quit.side_effect = error

        with mock.patch.object(DeputyWebDriver, 'get_deputies_from_dropdown', return_value=[]):
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

    def open_scraper_on(self, content: str, query='prmId=1008') -> DeputyWebDriver:
        page = pathlib.Path(self.pages_dir.name, f'{self.id()}.html')
        page.write_text(PAGE.format(content=content), encoding='utf-8')
        with mock.patch.object(dg_gastos, 'FIRST_DIPUTY_URL', f'{page.as_uri()}?{query}'):
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
               href="{destination.name}?prmId=1008#ficha-diputados">Gastos operacionales</a>
            <div id="ajax-container">
                <div style="position: relative; top: -2rem; height: 4rem;">Panel de detalle</div>
            </div>
        ''')

        scraper.get_into_operational_costs_section()

        self.assertEqual(self.driver.current_url,
                         f'{destination.as_uri()}?prmId=1008#ficha-diputados')
        self.assertEqual(self.driver.title, 'Gastos operacionales')

    def test_switches_deputies_without_rereading_roster(self):
        scraper = self.open_scraper_on(f'''
            <select id="{dg_gastos.DEPUTIES_DROPDOWN_ID}"
                    onchange="this.replaceWith(this.cloneNode(true));
                              document.title = this.value">
                <option value="1008">Jorge Rathgeb</option>
                <option value="1186">Ignacio Achurra</option>
                <option value="803">René Alinco</option>
            </select>
        ''')

        with mock.patch.object(self.driver, 'execute', wraps=self.driver.execute) as execute:
            deputies = scraper.get_deputies_from_dropdown()
            self.assertEqual(deputies, [('Jorge Rathgeb', '1008'),
                                        ('Ignacio Achurra', '1186'),
                                        ('René Alinco', '803')])
            for _, deputy_id in deputies[1:]:
                scraper._handle_select_to_change_deputy(deputy_id)
                self.assertEqual(self.driver.title, deputy_id)

        commands = [call.args[0] for call in execute.call_args_list]
        self.assertNotIn(Command.GET_ELEMENT_TEXT, commands)
        roster_reads = [call for call in execute.call_args_list
                        if call.args[0] == Command.W3C_EXECUTE_SCRIPT
                        and 'arguments[0].options' in call.args[1]['script']]
        self.assertEqual(len(roster_reads), 1)

    def test_switches_deputies_from_supporting_staff_by_cached_id(self):
        staff_page = pathlib.Path(self.pages_dir.name, 'supporting-staff.html')
        staff_page.write_text(f'''
            <title>Personal de apoyo</title>
            <select id="{dg_gastos.DEPUTIES_DROPDOWN_ID}" onchange="document.title = this.value">
                <option value="1008">Jorge Rathgeb</option>
                <option value="803">René Alinco</option>
                <option value="1186">Ignacio Achurra</option>
            </select>
        ''', encoding='utf-8')
        scraper = self.open_scraper_on(f'''
            <a id="ContentPlaceHolder1_ContentPlaceHolder1_btpeapo"
               href="{staff_page.name}">Personal de apoyo</a>
            <select id="{dg_gastos.DEPUTIES_DROPDOWN_ID}">
                <option value="1008">Jorge Rathgeb</option>
                <option value="1186">Ignacio Achurra</option>
                <option value="803">René Alinco</option>
            </select>
        ''')
        _, deputy_id = scraper.get_deputies_from_dropdown()[1]

        self.assertTrue(scraper.get_into_supporting_staff())
        self.assertEqual(self.driver.title, 'Personal de apoyo')
        scraper._handle_select_to_change_deputy(deputy_id)

        self.assertEqual(self.driver.title, '1186')

    def test_opens_sections_for_page_deputy_when_links_lose_its_id(self):
        # After a month or year postback camara.cl renders the section links
        # with an unformatted prmId={0}; the page URL still names the deputy.
        sections = (
            ('btGasop', 'gastosoperacionales.html', DeputyWebDriver.get_into_operational_costs_section),
            ('btnAsexterna', 'asesoriaexterna.html', DeputyWebDriver.get_into_external_consultancies),
            ('btpeapo', 'personaldepoyo.html', DeputyWebDriver.get_into_supporting_staff),
        )
        links = ''.join(f'<a id="ContentPlaceHolder1_ContentPlaceHolder1_{link_id}" '
                        f'href="{name}?prmId={{0}}#ficha-diputados">{name}</a>'
                        for link_id, name, _ in sections)
        for _, name, open_section in sections:
            with self.subTest(section=name):
                destination = pathlib.Path(self.pages_dir.name, name)
                destination.write_text(f'<title>{name}</title>', encoding='utf-8')
                scraper = self.open_scraper_on(links, query='prmID=1009')

                open_section(scraper)

                self.assertEqual(self.driver.current_url,
                                 f'{destination.as_uri()}?prmId=1009#ficha-diputados')
                self.assertEqual(self.driver.title, name)

    def test_retries_staff_navigation_when_the_consultancy_page_remains(self):
        staff_page = pathlib.Path(self.pages_dir.name, 'supporting-staff.html')
        staff_page.write_text('<title>Personal de apoyo</title>', encoding='utf-8')
        staff_url = f'{staff_page.as_uri()}?prmId=1008'
        scraper = self.open_scraper_on(
            f'<a id="{dg_gastos.SUPPORT_STAFF_CSS[1:]}" href="{staff_page.name}">Personal de apoyo</a>')

        with mock.patch.object(self.driver, 'get', wraps=self.driver.get,
                               side_effect=[None, mock.DEFAULT]) as navigate:
            scraper.get_into_supporting_staff()

        self.assertEqual(navigate.call_args_list, [mock.call(staff_url), mock.call(staff_url)])
        self.assertEqual(self.driver.current_url, staff_url)

    def test_detects_month_without_published_data(self):
        scraper = self.open_scraper_on(NO_DATA)

        self.assertIs(scraper._fast_check_if_there_is_data_section(), False)

    def test_reads_external_consultancies_table(self):
        scraper = self.open_scraper_on(
            table(('Ver', '12', '01/03/2021', 'Juan Pérez', 'Informe legislativo', '$822.400')))

        scraper.get_data_from_external_consultancies()

        self.assertEqual(dg_gastos.external_consultancies['Asesor'], ['Juan Pérez'])
        self.assertEqual(dg_gastos.external_consultancies['Monto'], ['$822.400'])

    def test_reads_consultancies_wrapped_in_a_layout_table(self):
        consultancies = table(('Ver', '12', '01/03/2021', 'Juan Pérez', 'Informe legislativo', '$822.400'))
        scraper = self.open_scraper_on(f'<table><tr><td>{consultancies}</td></tr></table>')

        scraper.get_data_from_external_consultancies()

        self.assertEqual(dg_gastos.external_consultancies['Folio'], ['12'])
        self.assertEqual(dg_gastos.external_consultancies['Monto'], ['$822.400'])

    def test_reads_consultancies_without_treating_nested_document_tables_as_records(self):
        documents = table(('<a href="report.pdf">Ver</a>', '', ''))
        scraper = self.open_scraper_on(
            table((documents, '3639', 'Jan 2026', 'FUNDACION JAIME GUZMAN', 'Asesoría', '$650.000'),
                  ('Ver', '3640', 'Jan 2026', 'Otro asesor', 'Informe', '$822.400')))

        scraper.get_data_from_external_consultancies()

        self.assertEqual(dg_gastos.external_consultancies['Doc'], ['Ver', 'Ver'])
        self.assertEqual(dg_gastos.external_consultancies['Folio'], ['3639', '3640'])
        self.assertEqual(dg_gastos.external_consultancies['Asesor'],
                         ['FUNDACION JAIME GUZMAN', 'Otro asesor'])
        self.assertEqual(dg_gastos.external_consultancies['Monto'], ['$650.000', '$822.400'])

    def test_reads_support_staff_table(self):
        scraper = self.open_scraper_on(
            table(('Personal de apoyo', '1', 'Ana Soto', 'Secretaria', '$1.200.000', 'No', '')))

        scraper.get_data_from_support_staff()

        self.assertEqual(dg_gastos.support_staff['Nombre'], ['Ana Soto'])
        self.assertEqual(dg_gastos.support_staff['Sueldo'], ['$1.200.000'])

    def test_readers_reject_malformed_rows_before_collecting_data(self):
        for reader, section, collected, row in (
            ('get_data_from_operational_costs_table', 'Costos operacionales',
             dg_gastos.operational_costs, ('TELEFONÍA', '$43.452')),
            ('get_data_from_external_consultancies', 'Asesorías externas',
             dg_gastos.external_consultancies,
             ('Ver', '12', '01/03/2021', 'Juan Pérez', 'Informe legislativo', '$822.400')),
            ('get_data_from_support_staff', 'Personal de apoyo',
             dg_gastos.support_staff,
             ('Personal de apoyo', '1', 'Ana Soto', 'Secretaria', '$1.200.000', 'No', '')),
        ):
            for malformed in (row[:-1], (*row, 'Celda inesperada')):
                with self.subTest(reader=reader, cells=len(malformed)):
                    scraper = self.open_scraper_on(table(row, malformed, row))
                    with self.assertRaisesRegex(
                            ValueError, f'{section}.*fila 2.*{len(row)}.*{len(malformed)}'):
                        getattr(scraper, reader)()
                    self.assertFalse(any(collected.values()))

    def test_operational_costs_rejects_header_cells_in_data_rows(self):
        for cells in ('<td>$43.452</td><th>Encabezado</th>', '<th>Encabezado</th>'):
            with self.subTest(cells=cells):
                scraper = self.open_scraper_on(table(('TRASLACIÓN', '$10.000')).replace(
                    '</tbody>', f'<tr><td>TELEFONÍA</td>{cells}</tr></tbody>'))

                with self.assertRaisesRegex(ValueError, 'Costos operacionales.*fila 2.*celdas td'):
                    scraper.get_data_from_operational_costs_table()
                self.assertFalse(any(dg_gastos.operational_costs.values()))

    def test_reads_operational_costs_with_unlabelled_site_column(self):
        content = table(('TELEFONÍA', '$43.452', '&nbsp;')).replace(
            '<tbody>', '<thead><tr><th>Gastos</th><th>Monto</th><th>&nbsp;</th></tr></thead><tbody>')
        scraper = self.open_scraper_on(content)

        scraper.get_data_from_operational_costs_table()

        self.assertEqual(dg_gastos.operational_costs['Gastos'], ['TELEFONÍA'])
        self.assertEqual(dg_gastos.operational_costs['Montos'], ['$43.452'])

    def test_support_staff_scrape_starts_at_latest_period(self):
        def postback(page):
            return f' onchange="setTimeout(() => location.href = \'{page}\', 250)"' if page else ''

        def date_controls(*months, latest=False, year_page=None, month_page=None, selected_month=None):
            selected_year = ' selected' if latest else ''
            month_options = ''.join(
                f'<option{" selected" if month == selected_month else ""}>{month}</option>'
                for month in months)
            return (
                f'<select id="{dg_gastos.YEAR_SELECTOR_CSS[1:]}"{postback(year_page)}>'
                f'<option>2025</option><option{selected_year}>2026</option></select>'
                f'<select id="{dg_gastos.MONTH_SELECTOR_CSS[1:]}"{postback(month_page)}>{month_options}</select>')

        def staff_table(name):
            return table(('Personal de apoyo', '1', name, 'Secretaria', '$1.200.000', 'No', ''))

        staff_link = f'<a id="{dg_gastos.SUPPORT_STAFF_CSS[1:]}" href="staff.html">Staff</a>'
        pages = {
            'costs.html': (
                f'<select id="{dg_gastos.DEPUTIES_DROPDOWN_ID}"><option value="1009">Deputy</option></select>'
                '<div class="rotulo">Deputy</div>'
                f'<a id="{dg_gastos.OPERATIONAL_COSTS_CSS[1:]}" href="costs.html">Costs</a>'
                f'<a id="{dg_gastos.EXTERNAL_CONSULTANCIES_CSS[1:]}" href="consultancies.html">Consultancies</a>'
                + date_controls('marzo', latest=True, year_page='costs-old.html?prmId=1009') + NO_DATA),
            'costs-old.html': (
                f'<a id="{dg_gastos.EXTERNAL_CONSULTANCIES_CSS[1:]}" href="consultancies.html">Consultancies</a>'
                + date_controls('marzo') + NO_DATA),
            'consultancies.html': (
                staff_link + date_controls('Todos', latest=True,
                                           year_page='consultancies-old.html?prmId=1009') + NO_DATA),
            'consultancies-old.html': staff_link + date_controls('Todos') + NO_DATA,
            'staff.html': date_controls('marzo', year_page='staff-latest.html') + staff_table('Ana Soto'),
            'staff-latest.html': (
                date_controls('marzo', 'Noviembre', latest=True, year_page='staff.html',
                              month_page='staff-november.html')
                + staff_table('Carla Ruiz')),
            'staff-november.html': (
                date_controls('marzo', 'Noviembre', latest=True, selected_month='Noviembre',
                              month_page='staff-latest.html')
                + staff_table('Beatriz Díaz')),
        }
        for filename, content in pages.items():
            pathlib.Path(self.pages_dir.name, filename).write_text(
                PAGE.format(content=content), encoding='utf-8')
        start = pathlib.Path(self.pages_dir.name, 'costs.html').as_uri()

        with mock.patch.object(dg_gastos, 'FIRST_DIPUTY_URL', f'{start}?prmId=1009'):
            dg_gastos._scrape_deputies(self.driver)

        staff = dg_gastos.support_staff
        self.assertEqual(list(zip(staff['Anio'], staff['Mes'], staff['Nombre'])),
                         [(2026, 11, 'Beatriz Díaz'), (2026, 3, 'Carla Ruiz'), (2025, 3, 'Ana Soto')])

    def test_staff_month_step_rejects_postback_with_different_month(self):
        month_id = dg_gastos.MONTH_SELECTOR_CSS[1:]
        returned_page = pathlib.Path(self.pages_dir.name, 'unchanged-month.html')
        returned_page.write_text(
            f'<select id="{month_id}"><option>marzo</option><option selected>abril</option></select>',
            encoding='utf-8')
        scraper = self.open_scraper_on(f'''
            <select id="{month_id}" onchange="setTimeout(() => location.href = '{returned_page.name}', 250)">
                <option>marzo</option><option selected>abril</option>
            </select>
        ''')
        scraper.get_and_update_current_month()

        with self.assertRaisesRegex(ValueError, 'abril en vez de marzo'):
            scraper.set_one_month_backward(wait_for_refresh=True)

        self.assertEqual(scraper.current_month_index, 4)

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

    def test_year_step_fails_when_postback_returns_another_year(self):
        pathlib.Path(self.pages_dir.name, 'same_year.html').write_text(PAGE.format(content=(
            f'<select id="{dg_gastos.YEAR_SELECTOR_CSS[1:]}">'
            '<option>2025</option><option selected>2026</option></select>'
        )), encoding='utf-8')
        scraper = self.open_scraper_on(
            f'<select id="{dg_gastos.YEAR_SELECTOR_CSS[1:]}" onchange="location.href = \'same_year.html\'">'
            '<option>2025</option><option selected>2026</option></select>'
        )
        scraper.available_years = [2026, 2025]
        scraper.current_year = 2026

        with self.assertRaisesRegex(RuntimeError, 'No se pudo cambiar del año 2026 al año 2025') as error:
            scraper.set_one_year_backward()

        self.assertIn('La página cargó el año 2026', str(error.exception.__cause__))
        self.assertEqual(scraper.current_year, 2026)

    def test_starts_previous_year_at_its_last_listed_month(self):
        pathlib.Path(self.pages_dir.name, 'year_2025.html').write_text(PAGE.format(content=(
            f'<select id="{dg_gastos.YEAR_SELECTOR_CSS[1:]}">'
            '<option selected="selected">2025</option><option>2026</option></select>'
            f'<select id="{dg_gastos.MONTH_SELECTOR_CSS[1:]}">'
            '<option>febrero</option><option>octubre</option></select>')), encoding='utf-8')
        scraper = self.open_scraper_on(
            f'<select id="{dg_gastos.YEAR_SELECTOR_CSS[1:]}"'
            ' onchange="location.href = \'year_2025.html\'">'
            '<option>2025</option><option selected="selected">2026</option></select>'
            f'<select id="{dg_gastos.MONTH_SELECTOR_CSS[1:]}"><option>marzo</option></select>')
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

    def test_reads_each_year_of_consultancies_after_its_postback_loads(self):
        # camara.cl posts the whole form on a year change and keeps showing the
        # previous year's table until the new page arrives.
        def year_page(year):
            options = ''.join(
                f'<option value="{option}"'
                f'{" selected" if option == year else ""}>{option}</option>'
                for option in (2024, 2025, 2026))
            return (
                f'<select id="{dg_gastos.YEAR_SELECTOR_CSS[1:]}" onchange="setTimeout('
                f'() => {{ location.href = `consultancies_${{this.value}}.html`; }}, '
                f'{(dg_gastos.WAITING_TIME + 1) * 1000})">{options}</select>'
                f'<select id="{dg_gastos.MONTH_SELECTOR_CSS[1:]}">'
                '<option selected>Todos</option><option>Enero</option></select>'
                + table(('Ver', str(year), f'01/03/{year}', f'Asesor {year}', 'Informe', '$1.000')))

        for year in (2024, 2025):
            pathlib.Path(self.pages_dir.name, f'consultancies_{year}.html').write_text(
                PAGE.format(content=year_page(year)), encoding='utf-8')
        scraper = self.open_scraper_on(year_page(2026))

        scraper._reset_dates_for_another_section()
        while scraper.there_is_more_data_to_scrap:
            scraper.select_all_months_in_month_dropwdown()
            scraper.get_data_from_external_consultancies()
            scraper.set_one_year_backward()

        self.assertEqual(dg_gastos.external_consultancies['Anio'], [2026, 2025, 2024])
        self.assertEqual(dg_gastos.external_consultancies['Asesor'],
                         ['Asesor 2026', 'Asesor 2025', 'Asesor 2024'])

    def test_reads_consultancies_when_rows_load_after_the_table(self):
        scraper = self.open_scraper_on(table())
        row = ('Ver', '12', '01/03/2021', 'Juan Pérez', 'Informe legislativo', '$822.400')
        self.driver.execute_script("""
            const cells = arguments[0];
            setTimeout(() => {
                const row = document.querySelector('table.tabla tbody').insertRow();
                cells.forEach(text => { row.insertCell().textContent = text; });
            }, 750);
        """, row)

        scraper.get_data_from_external_consultancies()

        self.assertEqual(dg_gastos.external_consultancies['Asesor'], ['Juan Pérez'])

    def test_consultancies_leave_live_empty_panel_empty(self):
        fixture = pathlib.Path(__file__).with_name('fixtures') / 'empty_consultancies.html'
        scraper = self.open_scraper_on(fixture.read_text(encoding='utf-8'))
        scraper.get_and_update_current_year()
        scraper.select_all_months_in_month_dropwdown()

        scraper.get_data_from_external_consultancies()

        self.assertFalse(any(dg_gastos.external_consultancies.values()))

    def test_consultancy_scrape_waits_for_year_refresh(self):
        fixture = pathlib.Path(__file__).with_name('fixtures') / 'empty_consultancies.html'
        scraper = self.open_scraper_on(fixture.read_text(encoding='utf-8'))
        self.driver.execute_script("""
            const [yearSelector, result] = arguments;
            const year = document.querySelector(yearSelector);
            year.add(new Option('2025', '2025'), 0);
            year.addEventListener('change', () => {
                const selected = year.value;
                setTimeout(() => {
                    const panel = year.closest('[id$="_UpdatePanel1"]');
                    const refreshed = panel.firstElementChild.cloneNode(true);
                    refreshed.querySelector(yearSelector).value = selected;
                    refreshed.querySelector('#body').innerHTML = result;
                    panel.replaceChildren(refreshed);
                }, 750);
            });
        """, dg_gastos.YEAR_SELECTOR_CSS,
            table(('Ver', '12', '01/03/2025', 'Juan Pérez', 'Informe legislativo', '$822.400')))

        reset_dates = scraper._reset_dates_for_another_section
        is_consultancies = iter((False, True, False))

        def reset_dates_only_for_consultancies(**options):
            if next(is_consultancies):
                reset_dates(**options)
            else:
                scraper.there_is_more_data_to_scrap = False

        with mock.patch.object(dg_gastos, 'DeputyWebDriver', return_value=scraper), \
             mock.patch.multiple(
                 scraper,
                 get_deputies_from_dropdown=mock.Mock(return_value=[('Deputy', '1008')]),
                 _handle_select_to_change_deputy=mock.Mock(),
                 get_deputy_name=mock.Mock(return_value='Deputy'),
                 get_into_operational_costs_section=mock.Mock(),
                 get_into_external_consultancies=mock.Mock(),
                 get_into_supporting_staff=mock.Mock(),
                 _reset_dates_for_another_section=reset_dates_only_for_consultancies):
            dg_gastos._scrape_deputies(self.driver)

        self.assertEqual(dg_gastos.external_consultancies['Anio'], [2025])
        self.assertEqual(dg_gastos.external_consultancies['Asesor'], ['Juan Pérez'])

    def test_consultancies_raise_when_loaded_panel_does_not_show_results(self):
        fixture = pathlib.Path(__file__).with_name('fixtures') / 'empty_consultancies.html'
        content = fixture.read_text(encoding='utf-8').replace(
            '<div id="body" class="table-responsive">', '<div id="body" class="table-responsive">Error')
        scraper = self.open_scraper_on(content)

        with self.assertRaises(TimeoutException):
            scraper.get_data_from_external_consultancies()

    def test_readers_leave_empty_months_empty(self):
        for content in (NO_DATA, table()):
            scraper = self.open_scraper_on(content)
            for read, collected in (
                (scraper.get_data_from_operational_costs_table, dg_gastos.operational_costs),
                (scraper.get_data_from_external_consultancies, dg_gastos.external_consultancies),
                (scraper.get_data_from_support_staff, dg_gastos.support_staff),
            ):
                with self.subTest(content=content, reader=read.__name__):
                    read()
                    self.assertFalse(any(collected.values()))

    def test_readers_raise_when_page_has_no_table_or_empty_marker(self):
        scraper = self.open_scraper_on(NO_DATA.replace('Los datos aún no han sido publicados',
                                                       'Error al cargar la página'))
        for read in (scraper.get_data_from_operational_costs_table,
                     scraper.get_data_from_external_consultancies,
                     scraper.get_data_from_support_staff):
            with self.subTest(reader=read.__name__):
                with self.assertRaises(TimeoutException):
                    read()

    def test_annual_consultancy_timeout_identifies_all_months(self):
        scraper = self.open_scraper_on(
            f'<select id="{dg_gastos.MONTH_SELECTOR_CSS[1:]}">'
            '<option>Todos</option><option selected>marzo</option></select>')

        scraper.select_all_months_in_month_dropwdown()

        with self.assertRaisesRegex(TimeoutException, 'Florcita Alarcón Rojas, Todos de 2021'):
            scraper.get_data_from_external_consultancies()

    def test_readers_propagate_webdriver_errors(self):
        scraper = self.open_scraper_on(
            table(('Personal de apoyo', '1', 'Ana Soto', 'Secretaria', '$1.200.000', 'No', '')))
        for read in (scraper.get_data_from_external_consultancies,
                     scraper.get_data_from_support_staff):
            with self.subTest(reader=read.__name__):
                with mock.patch.object(self.driver, 'find_elements',
                                       side_effect=WebDriverException('browser disconnected')):
                    with self.assertRaisesRegex(WebDriverException, 'browser disconnected'):
                        read()

    def test_missing_support_staff_section_raises(self):
        scraper = self.open_scraper_on(table())

        with self.assertRaises(TimeoutException):
            scraper.get_into_supporting_staff()

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


class YearStepTest(unittest.TestCase):

    def test_year_dropdown_timeout_aborts_scrape(self):
        driver = mock.Mock()
        scraper = DeputyWebDriver(driver)
        scraper.available_years = [2021, 2020]
        scraper.webdriver_wait = mock.Mock()
        timeout = TimeoutException('Year dropdown not found')
        scraper.webdriver_wait.until.side_effect = timeout
        section_has_data = iter((False, True))
        years_read = []

        def reset_dates():
            scraper.there_is_more_data_to_scrap = next(section_has_data)

        def read_consultancies():
            years_read.append(scraper.current_year)
            self.assertEqual(years_read, [2021], 'Scraper reread the same period')

        with mock.patch.object(dg_gastos, 'get_driver', return_value=driver), \
             mock.patch.object(dg_gastos, 'DeputyWebDriver', return_value=scraper), \
             mock.patch.multiple(
                 scraper,
                 get_deputies_from_dropdown=mock.Mock(return_value=[('Deputy', '1008')]),
                 _handle_select_to_change_deputy=mock.Mock(),
                 get_deputy_name=mock.Mock(return_value='Deputy'),
                 get_into_operational_costs_section=mock.Mock(),
                 get_into_external_consultancies=mock.Mock(),
                 _reset_dates_for_another_section=reset_dates,
                 select_all_months_in_month_dropwdown=mock.Mock(),
                 get_data_from_external_consultancies=read_consultancies):
            with self.assertRaisesRegex(RuntimeError, 'No se pudo cambiar del año 2021 al año 2020') as error:
                dg_gastos.main()

        self.assertIs(error.exception.__cause__, timeout)

    def test_month_refresh_timeout_after_year_selection_aborts_year_step(self):
        scraper = DeputyWebDriver(mock.Mock())
        scraper.available_years = [2021, 2020]
        dropdown = mock.Mock()
        timeout = TimeoutException('Month dropdown not found')
        scraper.webdriver_wait = mock.Mock()
        scraper.webdriver_wait.until.side_effect = [dropdown, dropdown, timeout]
        scraper.postback_wait = mock.Mock()

        with mock.patch.object(dg_gastos, 'Select') as select:
            select.return_value.first_selected_option.text = '2020'
            with self.assertRaisesRegex(RuntimeError, 'No se pudo cambiar del año 2021 al año 2020') as error:
                scraper.set_one_year_backward()

        select.assert_called_with(dropdown)
        select.return_value.select_by_visible_text.assert_called_once_with('2020')
        self.assertEqual(scraper.current_year, 2021)
        self.assertIs(error.exception.__cause__, timeout)


if __name__ == '__main__':
    unittest.main()
