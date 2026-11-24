import argparse
import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from selenium.common.exceptions import ElementClickInterceptedException
from selenium.webdriver import Firefox
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from dg_gastos import (
    DEPUTIES_DROPDOWN_ID,
    MONTH_SELECTOR_CSS,
    YEAR_SELECTOR_CSS,
    external_consultancies,
    operational_costs,
    support_staff,
)

BASE = "https://www.camara.cl/diputados/detalle/"
REPORTS = (
    ("CostosOperacionales", "gastosoperacionales", operational_costs),
    ("ConsultoriasExternas", "asesoriaexterna", external_consultancies),
    ("SupportStaff", "personaldepoyo", support_staff),
)


def browser():
    options = Options()
    options.page_load_strategy = "eager"
    driver = Firefox(options=options)
    driver.set_page_load_timeout(20)
    return driver


def open_report(driver, page, deputy_id=None):
    query = "?" + urlencode({"prmId": deputy_id}) if deputy_id else ""
    driver.get(f"{BASE}{page}.aspx{query}")
    WebDriverWait(driver, 8).until(
        EC.presence_of_element_located((By.ID, DEPUTIES_DROPDOWN_ID))
    )
    if deputy_id and parse_qs(urlsplit(driver.current_url).query).get("prmId") != [deputy_id]:
        raise ValueError(f"Report did not open for deputy {deputy_id}")


def selector(driver, css):
    return WebDriverWait(driver, 8).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, css))
    )


def values(driver, css):
    return [option.get_attribute("value") for option in Select(selector(driver, css)).options]


def select(driver, css, value):
    element = selector(driver, css)
    if element.get_attribute("value") != value:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", element)
        try:
            Select(element).select_by_value(value)
        except ElementClickInterceptedException:
            driver.execute_script("""
                const select = arguments[0], value = arguments[1];
                if (!Array.from(select.options).some(option => option.value === value)) {
                    throw new Error('Requested option is not present');
                }
                select.value = value;
                select.dispatchEvent(new Event('change', {bubbles: true}));
            """, element, value)
        WebDriverWait(driver, 15).until(EC.staleness_of(element))
        WebDriverWait(driver, 8).until(
            lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
            and d.find_element(By.CSS_SELECTOR, css).get_property("value") == value
        )


def report_data(driver, report, name, year, month):
    data = driver.execute_script("""
        return {
          headers: Array.from(document.querySelector('table.tabla tr')?.cells ?? [],
                              c => c.textContent.trim().replace(/\s+/g,' ')),
          rows: Array.from(document.querySelectorAll('table.tabla tr'))
                .filter(row => row.querySelector('td') && !row.querySelector('th'))
                .map(row => Array.from(row.cells, cell => cell.innerText.trim())),
          noData: document.querySelector('[id$="_nodata"]')?.innerText ?? '',
          text: Array.from(document.querySelectorAll('p, span, div')).filter(e => e.children.length === 0)
                     .map(e => e.innerText?.trim()).filter(Boolean).filter(s => s.length<200 && /no (existen|registra|hay|se encontr|han sido)|sin (datos|registros)/i.test(s)),
        }
    """)
    if not data["headers"]:
        if "no han sido publicados" in data["noData"] or any(
            re.search(r"no (existen|registra|hay|se encontr)|sin (datos|registros)", text, re.I)
            for text in data["text"]
        ):
            return []
        if report == "ConsultoriasExternas":
            return []
        raise ValueError(f"Missing table and explicit no-data message: {data['noData']!r} {data['text']!r}")
    result = []
    for cells in data["rows"]:
        if report == "CostosOperacionales" and len(cells) in (2, 3):
            result.append([name, year, month, *cells[:2]])
        elif report == "ConsultoriasExternas" and len(cells) >= 6:
            result.append([name, year, *cells[:6]])
        elif report == "SupportStaff" and len(cells) == 7:
            result.append([name, year, month, cells[0], *cells[2:]])
        else:
            raise ValueError(f"Unexpected {report} table: {data['headers']!r}; {len(cells)} cells")
    return result


def scrape(driver, deputy_id, report, page, year, min_month):
    open_report(driver, page, deputy_id)
    name = re.sub(r"^Diputad[oa]\s+", "", driver.find_element(By.CSS_SELECTOR, ".rotulo").text).strip()
    if not name or name in ("Diputado", "Diputada"):
        raise ValueError("No deputy name")
    if str(year) not in values(driver, YEAR_SELECTOR_CSS):
        return name, [], []
    select(driver, YEAR_SELECTOR_CSS, str(year))
    options = values(driver, MONTH_SELECTOR_CSS)
    if report == "ConsultoriasExternas" and "00" in options:
        months = ["00"]
    else:
        months = sorted((m for m in options if m.isdigit() and min_month <= int(m) <= 12),
                        key=int, reverse=True)
    rows = []
    for month in months:
        select(driver, MONTH_SELECTOR_CSS, month)
        if selector(driver, YEAR_SELECTOR_CSS).get_property("value") != str(year):
            raise ValueError("Changing month reset the year")
        rows.extend(report_data(driver, report, name, year, int(month)))
    return name, months, rows


def checkpoint(out, report, deputy_id):
    return out / "checkpoints" / f"{report}-{deputy_id}.json"


def run_shard(out, deputies, year, min_month, reports):
    with browser() as driver:
        for deputy_id in deputies:
            for report, page, _ in reports:
                path = checkpoint(out, report, deputy_id)
                if path.exists():
                    continue
                diagnostic = None
                for _ in range(2):
                    try:
                        name, months, rows = scrape(driver, deputy_id, report, page, year, min_month)
                        pending = path.with_suffix(".tmp")
                        pending.write_text(json.dumps(dict(deputy=name, months=months, rows=rows),
                                                      ensure_ascii=False), encoding="utf-8")
                        pending.replace(path)
                        print(report, deputy_id, name, f"slots={','.join(months)}", f"rows={len(rows)}", flush=True)
                        break
                    except Exception as error:
                        diagnostic = f"{type(error).__name__}: {str(error).splitlines()[0]}"
                else:
                    print(f"FAILED {report} {deputy_id}: {diagnostic}", flush=True)


def export(out, deputies, reports):
    for report, _, fields in reports:
        complete = 0
        rows = []
        for deputy_id in deputies:
            path = checkpoint(out, report, deputy_id)
            if path.exists():
                complete += 1
                rows.extend(json.loads(path.read_text(encoding="utf-8"))["rows"])
        pending = out / f"{report}.csv.tmp"
        with pending.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(fields)
            writer.writerows(rows)
        pending.replace(out / f"{report}.csv")
        print(f"{report}: {len(rows)} rows, {complete}/{len(deputies)} deputies checked")
    return all(checkpoint(out, report, deputy_id).exists()
               for report, _, _ in reports for deputy_id in deputies)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--min-month", type=int, choices=range(1, 13), default=1)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--report", choices=[report for report, _, _ in REPORTS], action="append")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--export-only", action="store_true")
    args = parser.parse_args()
    reports = [report for report in REPORTS if not args.report or report[0] in args.report]
    out = args.out
    (out / "checkpoints").mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.json"
    settings = {"year": args.year, "min_month": args.min_month, "limit": args.limit}
    if manifest.exists():
        saved = json.loads(manifest.read_text(encoding="utf-8"))
        if saved["settings"] != settings:
            parser.error("reuse the original run parameters or choose another output directory")
        deputies = saved["deputies"]
    else:
        if args.export_only:
            parser.error("no run manifest in the output directory")
        with browser() as driver:
            open_report(driver, REPORTS[0][1])
            deputies = [value for value in values(driver, "#" + DEPUTIES_DROPDOWN_ID)
                        if value.isdigit() and int(value) > 0][:args.limit]
        if not deputies:
            raise RuntimeError("Deputy roster was empty")
        manifest.write_text(json.dumps(dict(settings=settings, deputies=deputies)), encoding="utf-8")
    print(f"Roster: {len(deputies)} deputies", flush=True)
    if not args.export_only:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(run_shard, out, deputies[i::args.workers], args.year, args.min_month, reports)
                       for i in range(args.workers)]
            for future in futures:
                future.result()
    return 0 if export(out, deputies, reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
