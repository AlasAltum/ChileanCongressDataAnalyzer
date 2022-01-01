"""
data getter: información de gastos de cada diputado
@Author: AlasAltum
"""
import re
import pandas as pd
import time
from selenium.webdriver import Remote as RemoteWebDriver
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import (StaleElementReferenceException,
                                        TimeoutException,
                                        NoSuchWindowException,
                                        ElementClickInterceptedException,
                                        NoSuchElementException)
from selenium.webdriver.support.ui import WebDriverWait
from driver_utils import get_driver, _by_css_selector, _by_xpath_selector, _by_id

THERE_IS_TABLE = 0
THERE_IS_NO_TABLE_BUT_TEXT = 1
NEED_TO_RELOAD = 2

DRIVER = 'mozilla'  # Aquí se tiene que entregar el driver de chrome o mozzilla
FIRST_DIPUTY_URL = 'https://www.camara.cl/diputados/detalle/gastosoperacionales.aspx?prmId=1008#ficha-diputados'
DIPUTY_SELECTOR_CSS = '#ContentPlaceHolder1_ContentPlaceHolder1_ddlDiputados'
YEAR_SELECTOR_CSS = '#ContentPlaceHolder1_ContentPlaceHolder1_DetallePlaceHolder_ddlAno'
MONTH_SELECTOR_CSS = '#ContentPlaceHolder1_ContentPlaceHolder1_DetallePlaceHolder_ddlMes'
DEPUTIES_DROPDOWN_ID = 'ContentPlaceHolder1_ContentPlaceHolder1_ddlDiputados'
CURRENT_MONTH_XPATH = '//select[@id="ContentPlaceHolder1_ContentPlaceHolder1_DetallePlaceHolder_ddlMes"]/option[@selected="selected"]'
CURRENT_YEAR_CSS = 'ContentPlaceHolder1_ContentPlaceHolder1_DetallePlaceHolder_ddlAno'
OPERATIONAL_COSTS_CSS = '#ContentPlaceHolder1_ContentPlaceHolder1_btGasop'
NO_DATA_PARRAGRAPH_XPATH = '//div[@id="ContentPlaceHolder1_ContentPlaceHolder1_DetallePlaceHolder_nodata"]/p'
TABLE_ROW_XPATH = '//table[@class="tabla"]/tbody/tr'
DEPUTY_COST_TABLE_XPATH = '//table[@class="tabla"]/tbody'
MONTHS = (
    'Todos', # This one appears only in some cases.
    'enero',
    'febrero',
    'marzo',
    'abril',
    'mayo',
    'junio',
    'julio',
    'agosto',
    'septiembre',
    'octubre',
    'noviembre',
    'diciembre',
)
MONTH_TEXT_TO_NUMBER = {
    'Todos': 0,
    'enero': 1,
    'febrero': 2,
    'marzo': 3,
    'abril': 4,
    'mayo': 5,
    'junio': 6,
    'julio': 7,
    'agosto': 8,
    'septiembre': 9,
    'octubre': 10,
    'noviembre': 11,
    'diciembre': 12,
}
WAITING_TIME = 2

operational_costs = {
        'diputado': [],
        'Anio': [],
        'Mes': [],
        'Gastos': [],
        'Montos': [],
    }

external_consultancies = {
        'Diputado': [],
        'Anio': [],
        'Doc': [],
        'Folio': [],
        'Fecha': [],
        'Asesor': [],
        'Detalle': [],
        'Monto': [],
    }

support_staff = {
    'Diputado': [],
    'Anio': [],
    'Mes': [],
    'Tipo': [],
    'Nombre': [],
    'Cargo': [],
    'Sueldo': [],
    'Cargo Elección (Servel)': [],
    'Cese de Funciones': [],
}

# TODO: add party to each current deputy
# logger = logging.getLogger(name='DeputyLogger')
# logger.setLevel(logging.DEBUG)
# handler = logging.StreamHandler(sys.stdout)
# handler.setLevel(logging.DEBUG)
# logger.addHandler(handler)


class DeputyWebDriver:
    """
    Class for scrapping data from chilean deputies
    using the page: https://www.camara.cl/diputados/
    """
    def __init__(self, _webdriver: RemoteWebDriver, logger_name='DeputyLogger'):
        self.driver : RemoteWebDriver = _webdriver
        self.webdriver_wait : WebDriverWait = WebDriverWait(_webdriver, WAITING_TIME)
        self.current_deputy = ''
        self.current_month_index = 12  # initializes in december
        self.current_year = 2021
        self.available_years = []
        self.there_is_more_data_to_scrap = True
        # self.logger = None
        self.driver.get(FIRST_DIPUTY_URL)

    def _log(self, log_msg : str):
        """
        Log the phase the scraper is on by using the logger
        """
        # self.logger.log(level=0,msg=log_msg)
        print(log_msg)

    def get_deputies_names_from_dropdown(self) -> tuple([list[str], Select]):
        self._log('Obteniendo nombres de los diputados.')
        all_deputies_names = []
        deputies_dropdown = self.webdriver_wait.until(_by_id(DEPUTIES_DROPDOWN_ID))
        all_deputies = Select(deputies_dropdown)

        for deputy_name in all_deputies.options:
            all_deputies_names.append(deputy_name.text)

        self._log(f'Se obtuvieron {len(all_deputies_names)} nombres.')
        return all_deputies_names, all_deputies


    def _handle_select_to_change_deputy(self, index_to_select):
        """
        When changing between deputies, sometimes appear some
        exceptions, so we need to repeat them
        """
        try:
            _, deputies_select = self.get_deputies_names_from_dropdown()
            deputies_select.select_by_index(index_to_select)

        # If we have an error, repeat after some time
        except ElementClickInterceptedException:
            self.driver.refresh()
            TIME_TO_AVOID_CLICK_INTERCEPTION = 2.0
            time.sleep(TIME_TO_AVOID_CLICK_INTERCEPTION)
            
            return self._handle_select_to_change_deputy(index_to_select)

    def get_deputy_name(self) -> str:
        """
        Gets the name of a given deputy from the page
        """
        self._log('Obteniendo nombre del siguiente diputado...')
        name_css = '.rotulo' 
        # example: Diputado Florcita Alarcón Rojas
        name = self.webdriver_wait.until(_by_css_selector(name_css))
         # remove prefix Diputado or Diputada
        name_without_prefix = re.sub(pattern=r'Diputad[oa] ', repl='', string=name.text)
        self.current_deputy = name_without_prefix
        self._log(f'Nombre del diputado cuyos datos se extraen: {self.current_deputy}')
        return name_without_prefix

    def get_into_operational_costs_section(self):
        """
        Move the webdriver into the section of operational costs
        """
        operational_costs = self.webdriver_wait.until(_by_css_selector(OPERATIONAL_COSTS_CSS))
        operational_costs.click()

    def get_and_update_current_year(self):
        """
        Gets the current year in the selector and select it as the current year
        """
        self._log('Obteniendo el año que aparece en la página...')
        current_year = self.webdriver_wait.until(_by_css_selector(YEAR_SELECTOR_CSS))
        # example: 2018\n2019\n2020\n2021
        # after map(int, example) -> [2018, 2019, 2020, 2021]
        self.available_years = list(map(int, current_year.text.split('\n')))
        # get the current year
        self.current_year = int(Select(current_year).first_selected_option.text)
        self._log(f'Año actual actualizado a: {self.current_year}')

    def get_and_update_current_month(self):
        """
        
        """
        self._log('Obteniendo el mes que aparece en la página...')
        current_month = self.webdriver_wait.until(_by_xpath_selector(CURRENT_MONTH_XPATH))
        self.current_month_index = MONTH_TEXT_TO_NUMBER[current_month.text]
        self._log(f'Mes actual: {current_month.text}')


    def set_one_year_backward(self):
        """
        Set scroller of years one year in the past by moving the selector.
        """
        # TODO: Check if CSS is different in
        self._log(f'Cambiando al año anterior: Año actual {self.current_year}')
        try:   
            dropdown_year = self.webdriver_wait.until(_by_css_selector(YEAR_SELECTOR_CSS))
            dropdown_year_select = Select(dropdown_year)
            previous_year = self.current_year - 1 
            # if previous_year has available data:
            if previous_year in self.available_years:
                self.current_year = self.current_year - 1
                dropdown_year_select.select_by_visible_text(str(self.current_year))
                self._log(f'Se restó un año satisfactoriamente, año actual: {self.current_year}')
                self.get_and_update_current_month()
                return True
            else:  # Case we reach a year without data
                self.there_is_more_data_to_scrap = False
                self._log('No hay datos del 2017...')
                return False
        except Exception as e:
            return False

    def _get_month_dropdown_select_and_change_one_month_backward(self):
        try:
            dropdown_month = self.webdriver_wait.until(_by_css_selector(MONTH_SELECTOR_CSS))
            dropdown_month_select = Select(dropdown_month)
            # We use self.current_month_index - 1 and then substract one to current month
            # because select by index method usually causes exceptions.
            dropdown_month_select.select_by_index(self.current_month_index - 1)
            self.current_month_index = self.current_month_index - 1

        except (ElementClickInterceptedException, StaleElementReferenceException):
            # this exception may happen due to high latency or
            # when the browser is slow. There is no problem with repetition
            # since the current month index is updated once the month is successfully changed
            return self._get_month_dropdown_select_and_change_one_month_backward()

    def set_one_month_backward(self) -> bool:
        """
        Set scroller of month one month in the past by moving the selector.
        
        Returns False when iteration it has reached year 2017
        """
        # January case
        if self.current_month_index == 0:
            # Get back one year, return to december.
            self.set_one_year_backward() # no hay datos debe ocurrir antes
            self.current_month_index = 12
            # If there is no more data: stop scrapping
            if self.there_is_more_data_to_scrap:
                return False

        # Get the dropdown element and set one month backward
        self._get_month_dropdown_select_and_change_one_month_backward()
        return True


    def _fast_check_if_there_is_data_section(self) -> bool:
        """
        Return True if the webdriver found the table, elsewise return False. 
        If neither the table or text was found, use an implicit wait
        """
        try:
            if self.driver.find_element_by_xpath(DEPUTY_COST_TABLE_XPATH):
                return True
        except NoSuchElementException:
            pass  # just ignore, maybe it is not ready or it won't find the element
        try:
            text_parragraph = self.driver.find_element_by_xpath(NO_DATA_PARRAGRAPH_XPATH)
            if text_parragraph and 'no han sido publicados' in text_parragraph.text:
                return False
        except NoSuchElementException:
            pass  # same as before.

        # Maybe the page is still loading. Use implicit wait.
        try:
            table = self.webdriver_wait.until(_by_xpath_selector(DEPUTY_COST_TABLE_XPATH))
            if table:
                return True

        except (NoSuchElementException, TimeoutException):
            return False


    def get_data_from_operational_costs_table(self) -> None:
        """
        Gets data from operational costs table and adds it to
        operational_costs, including current deputy, year, month
        and the data displayed
        Format:
        Gastos: str 	Monto: int 
        """
        if not (1 <= self.current_month_index <= 12):
            # do not get information for month "Todos", because it is not
            # possible in this section.
            return

        try:
            available_data = self._fast_check_if_there_is_data_section()
            if available_data is False:
                self._log(f'Mes {MONTHS[self.current_month_index]} del año '
                  f'{self.current_year} no tiene datos. Saltando...')

            if available_data:
                gasto_elements = self.driver.find_elements_by_xpath('//table[@class="tabla"]/tbody/tr/td[1]')
                monto_elements = self.driver.find_elements_by_xpath('//table[@class="tabla"]/tbody/tr/td[2]')

                gastos_text = [element.text for element in gasto_elements]
                monto_text = [element.text for element in monto_elements]

                for gasto, monto in zip(gastos_text, monto_text):
                    operational_costs['diputado'].append(self.current_deputy)
                    operational_costs['Anio'].append(self.current_year)
                    operational_costs['Mes'].append(self.current_month_index)
                    operational_costs['Gastos'].append(gasto)
                    operational_costs['Montos'].append(monto)

                self._log('Se agregaron datos de costos operacionales para el mes '
                          f'{MONTHS[self.current_month_index]} satisfactoriamente')

        except TimeoutException:
            # Elements not found
            self._log(f'Mes {MONTHS[self.current_month_index]} del año '
                  f'{self.current_year} no tiene datos. Saltando...')

        except StaleElementReferenceException:
            self.get_data_from_operational_costs_table()


    def select_all_months_in_month_dropwdown(self) -> None:
        """
        In the section external consultancies, there is an option
        'Todos' in the dropdown element, where all consultancies
        for a given year are displayed.
        This function locates the dropdown element and selects
        'Todos'
        """
        try:
            dropdown_month = self.webdriver_wait.until(_by_css_selector(MONTH_SELECTOR_CSS))
            dropdown_month_select = Select(dropdown_month)
            dropdown_month_select.select_by_index(0)
        except StaleElementReferenceException:
            self.select_all_months_in_month_dropwdown()

    def get_into_external_consultancies(self) -> None:
        """
        
        """
        external_consultancies_element = self.driver.find_element_by_id('ContentPlaceHolder1_ContentPlaceHolder1_btnAsexterna')
        external_consultancies_element.click()


    def get_data_from_external_consultancies(self) -> None:
        """
        Get the data from external consultancies of a deputy during a whole year
        """
        try:
            available_data = self._fast_check_if_there_is_data_section()
            if available_data is False:
                self._log(f'Mes {MONTHS[self.current_month_index]} del año '
                  f'{self.current_year} no tiene datos. Saltando...')

            if available_data:
                xpath_prefix = '//table[@class="tabla"]/tbody/tr/td'
                # This first time is to make sure the data was loaded and
                # there were no changes in the DOM
                doc_elements = self.webdriver_wait.until(_by_xpath_selector(xpath_prefix + '[1]'))

                doc_elements = self.driver.find_elements_by_xpath(xpath_prefix + '[1]')
                folio_elements = self.driver.find_elements_by_xpath(xpath_prefix + '[2]')
                fecha_elements = self.driver.find_elements_by_xpath(xpath_prefix + '[3]')
                asesor_elements = self.driver.find_elements_by_xpath(xpath_prefix + '[4]')
                detalle_elements = self.driver.find_elements_by_xpath(xpath_prefix + '[5]')
                monto_elements = self.driver.find_elements_by_xpath(xpath_prefix + '[6]')
                # TODO: Agregar link documento
                doc_text = [element.text for element in doc_elements] # StaleElementReferenceException
                folio_text = [element.text for element in folio_elements]
                fecha_text = [element.text for element in fecha_elements]
                asesor_text = [element.text for element in asesor_elements]
                detalle_text = [element.text for element in detalle_elements]
                monto_text = [element.text for element in monto_elements]

                for doc, folio, fecha, asesor, detalle, monto in zip(
                        doc_text, folio_text, fecha_text, asesor_text, detalle_text, monto_text):
                    external_consultancies['Diputado'].append(self.current_deputy)
                    external_consultancies['Anio'].append(self.current_year)
                    external_consultancies['Doc'].append(doc)
                    external_consultancies['Folio'].append(folio)
                    external_consultancies['Fecha'].append(fecha)
                    external_consultancies['Asesor'].append(asesor)
                    external_consultancies['Detalle'].append(detalle)
                    external_consultancies['Monto'].append(monto)

                self._log('Se obtuvieron los datos de las asesorías externas para el año '
                          f'{self.current_year} y el mes {MONTHS[self.current_month_index]}')
        except StaleElementReferenceException as e:
            # This might happen when changes were made too fast
            self.get_data_from_external_consultancies()
        
        except Exception as e:
            self._log('No se encontraron datos en asesorías externas'
                    f'para el año {self.current_year}')


    def get_into_supporting_staff(self) -> bool:
        """
        Get into supporting staff element for the current deputy
        If click was sucessfull, return True
        Return False if error
        """
        try:
            LIST_CSS = '#ContentPlaceHolder1_ContentPlaceHolder1_btpeapo'
            supporting_staff_element = self.webdriver_wait.until(_by_css_selector(LIST_CSS))
            supporting_staff_element.click()
            return True
        except (TimeoutException, NoSuchElementException):
            return False


    def get_data_from_support_staff(self):
        """
        
        """
        if not (1 <= self.current_month_index <= 12):
            # do not get information for month "Todos", because it is not
            # possible in this section.
            return

        try:
            available_data = self._fast_check_if_there_is_data_section()
            if available_data is False:
                self._log(f'Mes {MONTHS[self.current_month_index]} del año '
                  f'{self.current_year} no tiene datos. Saltando...')

            if available_data:
                # these XPATHS were the ones in the HTML for the following elements:
                tipo_elements = self.driver.find_elements_by_xpath('//table[@class="tabla"]/tbody/tr/td[1]')
                nombre_elements = self.driver.find_elements_by_xpath('//table[@class="tabla"]/tbody/tr/td[3]')
                cargo_elements = self.driver.find_elements_by_xpath('//table[@class="tabla"]/tbody/tr/td[4]')
                sueldo_elements = self.driver.find_elements_by_xpath('//table[@class="tabla"]/tbody/tr/td[5]')
                cargo_eleccion_elements = self.driver.find_elements_by_xpath('//table[@class="tabla"]/tbody/tr/td[6]')
                cese_funciones_elements = self.driver.find_elements_by_xpath('//table[@class="tabla"]/tbody/tr/td[7]')

                tipo_text = [element.text for element in tipo_elements]
                nombre_text = [element.text for element in nombre_elements]
                cargo_text = [element.text for element in cargo_elements]
                sueldo_text = [element.text for element in sueldo_elements]
                cargo_eleccion_text = [element.text for element in cargo_eleccion_elements]
                cese_funciones_text = [element.text for element in cese_funciones_elements]

                for tipo, nombre, cargo, sueldo, cargo_eleccion, cese in zip(
                    tipo_text, nombre_text, cargo_text, sueldo_text, cargo_eleccion_text, cese_funciones_text):
                    support_staff['Diputado'].append(self.current_deputy)
                    support_staff['Anio'].append(self.current_year)
                    support_staff['Mes'].append(self.current_month_index)
                    support_staff['Tipo'].append(tipo)
                    support_staff['Nombre'].append(nombre)
                    support_staff['Cargo'].append(cargo)
                    support_staff['Sueldo'].append(sueldo)
                    support_staff['Cargo Elección (Servel)'].append(cargo_eleccion)
                    support_staff['Cese de Funciones'].append(cese)

                self._log(f'Se obtuvieron datos de personal de apoyo para el mes '
                          f'{MONTHS[self.current_month_index]} del año {self.current_year}')

        except StaleElementReferenceException:
            self.get_data_from_support_staff()  # Just reload

        except Exception as e:
            # Case Elements not found
            self._log('No se encontraron datos en personal de apoyo para el mes de '
                      f'{MONTHS[self.current_month_index]} en el año {self.current_year}')

    def _reset_dates_for_another_section(self):
        self.get_and_update_current_year()
        self.get_and_update_current_month()
        self.there_is_more_data_to_scrap = True

def main():
    """
    Init the webdriver, get the data of every deputy and once all data
    has been collected, save a .csv file with this data

    """
    # init web driver
    driver = get_driver()
    webdriver = DeputyWebDriver(driver)
    deputies_names, _ = webdriver.get_deputies_names_from_dropdown()
    deputies_collected_data  = set()

    # # Do this for every deputy, since we know all the names
    # # We know we should have data for every deputy    
    # ElementClickInterceptedException
    while len(deputies_collected_data) < len(deputies_names):
        webdriver._handle_select_to_change_deputy(len(deputies_collected_data))
        current_deputy_name = webdriver.get_deputy_name()

        # get all operational costs
        webdriver.get_into_operational_costs_section()
        webdriver._reset_dates_for_another_section()
        while webdriver.there_is_more_data_to_scrap: 
            webdriver.get_data_from_operational_costs_table()
            webdriver.set_one_month_backward()
        
        webdriver._log('Se terminó de obtener costos operacionales de '
                       f'{current_deputy_name}, pasando a asesorías externas...')
        # get all external consultancies
        webdriver.get_into_external_consultancies()
        webdriver._reset_dates_for_another_section()
        # This section has the value "Todos" in its dropdown which allows us
        # to see all data in a whole year, therefore, we select
        # all months at once in the month dropdown and advance per year
        while webdriver.there_is_more_data_to_scrap:
            webdriver.select_all_months_in_month_dropwdown()
            webdriver.get_data_from_external_consultancies()
            webdriver.set_one_year_backward()

        webdriver._log('Se terminaron de obtener los datos de asesorías externas de '
                       f'{current_deputy_name}, pasando a Personal de apoyo...')
        # get all supporting staff
        webdriver.get_into_supporting_staff()
        webdriver._reset_dates_for_another_section()
        while webdriver.there_is_more_data_to_scrap:
            webdriver.get_data_from_support_staff()
            webdriver.set_one_month_backward()

        deputies_collected_data.add(current_deputy_name)

        webdriver._log('Se terminaron de obtener datos de: '
                       f'{current_deputy_name}. Seguimos con...')


if __name__ == "__main__":
    try:
        main()

        operational_costs_df = pd.DataFrame.from_dict(operational_costs)
        operational_costs_df.to_csv('collected_data/CostosOperacionales.csv')

        monto_to_int = lambda x: int(re.sub(r'[$.\s]', '', x))
        external_consultancies['Monto'] = [monto_to_int(monto) for monto in  external_consultancies['Monto']] 
        external_consultancies_df = pd.DataFrame.from_dict(external_consultancies)
        external_consultancies_df.to_csv('collected_data/ConsultoriasExternas.csv')

        # change format of text to avoid int truncation
        # if we not apply this, values like: 
        #  '822.400   ' will be passed as 822.4
        str_to_int = lambda x: int(re.sub(r'[.\s]', '', x))
        support_staff['Sueldo'] = [str_to_int(num) for num in support_staff['Sueldo']]
        # Export collected data to a csv file
        support_staff_df = pd.DataFrame.from_dict(support_staff)
        support_staff_df.to_csv('collected_data/SupportStaff.csv')

    except NoSuchWindowException:
        print('Se cerró el navegador')
        raise

# 
# Examples:
# Diputado Bernardo Berger Fett
# Asesorías Externas: BONNIE MARQUEZ JEREZ Año 2018
# Personal de apoyo: Márquez Jerez Bonnie Cindy

