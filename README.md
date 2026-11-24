# ChileanCongressDataAnalyzer
This project makes data mining on the Chilean Congress cost report using the following pages:

http://opendata.camara.cl/camaradiputados/

https://www.camara.cl/diputados/detalle/gastosoperacionales.aspx

Project explanation:

The folder diputados contains all information regarding deputies.
dg_gastos.py includes a scraper written using Selenium that gets all available data regarding costs.
The subfolder collected_data contains the results of the scrapped data. Please note that there are a lot of deputies, and there is a lot of data that must be recorded, so this application may take a while (it took me like 4 hours to get all data running this program)

The subfolder analysis_results will contain notebooks and queries with interesting data. We will use this in the future to make a page for transparency about politicians in Chile, crossing information between them.

## Setup

Install Python 3.11. From the repository root, create a virtual environment and
install the Python dependencies:

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Keep the virtual environment active for the commands below.

## Run the scraper

Install Firefox and run the scraper in a desktop session where Firefox can open
a window. Selenium Manager can download geckodriver automatically; if it cannot
download the driver, install a compatible geckodriver and put it on your
`PATH`. The example below uses Firefox. To use an installed copy of Chrome,
replace `unset DRIVER` with `export DRIVER=chrome`.

Start from the repository root. The scraper writes to `collected_data/`
relative to its working directory:

```sh
unset DRIVER
cd diputados
python dg_gastos.py
```

A complete scrape can take several hours. A live run can stop before exporting
if the external consultancy link redirects to the deputies listing, which has
no year selector.

Run the scraper in a separate clone or back up `diputados/collected_data/`
first. If the scrape completes, it replaces the CSVs with only the rows it
collected; it does not preserve archived rows. To update the bundled CSVs
without discarding archived periods, use the [daily expense refresh](#daily-expense-refresh).

## Run the analysis notebook

The notebook can use the CSVs included in the repository, so you do not need to
run the scraper first. Start from the repository root and run the notebook from
its own directory so it can read `../collected_data/`:

```sh
cd diputados/analysis_results
jupyter nbconvert --to notebook --execute analysis.ipynb --output analysis.executed.ipynb
```

Open `analysis.executed.ipynb` to inspect the results. The source notebook is
not overwritten.

## Daily expense refresh

Run the following on a persistent host with Python 3.11, Firefox, and a working graphical session. The working configuration uses Selenium 4.54.0 with Selenium Manager providing geckodriver, and pandas 1.5.3 (the analysis uses pandas 1.x).

```sh
python3.11 -m venv ~/.venvs/congress
~/.venvs/congress/bin/pip install 'selenium==4.54.0' 'pandas==1.5.3' 'numpy<2'
DISPLAY=:0 PYTHONDONTWRITEBYTECODE=1 ~/.venvs/congress/bin/python diputados/refresh_expenses.py
```

The command selects the current year and month in Chile, checks the public per-deputy operational cost pages and the monthly Transparencia Activa lists for external consultancies and support staff, and stages data outside the checkout. It verifies that it checked every roster entry and requested bulk month and validates rows before replacing any CSV. Archived periods outside the refreshed coverage remain in `diputados/collected_data/`. A selected month with no published records does not remove existing records.

To run daily, add a cron job on that host with the actual checkout path and X display. For example, at 06:15 in the host's local time:

```cron
15 6 * * * flock -n "$HOME/.camara-expenses.lock" env DISPLAY=:0 PYTHONDONTWRITEBYTECODE=1 "$HOME/.venvs/congress/bin/python" "$HOME/repos/ChileanCongressDataAnalyzer/diputados/refresh_expenses.py" >> "$HOME/camara-expenses.log" 2>&1
```

Verify that this job can open Firefox and the three source pages before enabling it. Ordinary HTTP requests returned Cloudflare 403 in the tested environment; graphical Firefox worked. A run can fail on source timeouts or challenges without replacing the last published files. Rerun with the same `--stage` to resume incomplete checkpoints; use a new directory to recheck previously completed selections. Use `--publish-only --stage PATH` to validate and publish a completed staged run without reopening the browser. When reusing a stage from a different date, also supply the original `--year`, `--month` and `--bulk-start-year`.

The operational pages checked in November 2026 displayed only 2026 in the year selector, so the refresh does not fill the 2022–2025 operational gap. Use `--bulk-start-year 2022` for a longer staff and consultancy refresh. The refresh converts consolidated report names to full names only when they match one candidate in the roster and archive; it prints and preserves unmatched or ambiguous names. To apply the same rule to the existing CSVs without browsing, run `python diputados/normalize_deputy_names.py`. The consultancy export records the publication month as `YYYY-MM` in `Fecha`, not an exact transaction date; the list does not supply `Detalle`.
