import re
import pandas as pd  # To store our data
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

from diputados.driver_utils import *

driver = get_driver()
driver.get('https://www.camara.cl/diputados/detalle/gastosoperacionales.aspx?prmId=1008#ficha-diputados')
deputies_dropdown = driver.find_element_by_id('ContentPlaceHolder1_ContentPlaceHolder1_ddlDiputados')
all_deputies = Select(deputies_dropdown)
counter = 0
for deputy_name in all_deputies.options:
    print(f'deputy name #{counter}: {deputy_name.text}')
    counter += 1

# test = "Diputado Florcita Alarcón Rojas"

# name = re.sub(pattern=r'Diputad[oa] ', repl='', string=test)

# print(name)

