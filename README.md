# ChileanCongressDataAnalyzer
This project makes data mining on the Chilean Congress cost report using the following pages:

http://opendata.camara.cl/camaradiputados/

https://www.camara.cl/diputados/detalle/gastosoperacionales.aspx

Project explanation:

The folder diputados contains all information regarding deputies.
dg_gastos.py includes a scraper written using Selenium that gets all available data regarding costs.
The subfolder collected_data contains the results of the scrapped data. Please note that there are a lot of deputies, and there is a lot of data that must be recorded, so this application may take a while (it took me like 4 hours to get all data running this program)

The subfolder analysis_results will contain notebooks and queries with interesting data. We will use this in the future to make a page for transparency about politicians in Chile, crossing information between them.
