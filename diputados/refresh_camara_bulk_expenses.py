import argparse
import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from refresh_camara_expenses import REPORTS, browser, select, selector

URLS = {
    "ConsultoriasExternas": "https://www.camara.cl/transparencia/asesoriasexternasgral.aspx",
    "SupportStaff": "https://www.camara.cl/transparencia/personalapoyogral.aspx",
}


def get_month(driver, report, year, month):
    YEAR, MONTH = 'select[id$="ddlAno"]', 'select[id$="ddlMes"]'
    select(driver, YEAR, str(year))
    select(driver, MONTH, str(month))
    if selector(driver, YEAR).get_property("value") != str(year):
        raise ValueError("Changing month reset the year")
    data = driver.execute_script("""
        const table = document.querySelector('table.tabla');
        return {
            headers: Array.from(table?.rows[0]?.cells ?? [], cell => cell.innerText.trim()),
            rows: Array.from(table?.rows ?? []).slice(1).map(row =>
                Array.from(row.cells, cell => ({text:cell.innerText.trim()}))),
            heading: document.querySelector('.rotulo')?.innerText,
            body: document.body.innerText
                 .split('\n').map(s=>s.trim()).filter(s=>/no (se |existen|hay|han sido)|sin (datos|registros)/i.test(s)).slice(-8),
        }
    """.replace(".split('\n')", ".split('\\n')"))
    rows = []
    if report == "ConsultoriasExternas" and data["headers"][:4] == ["Folio", "Asesor", "Monto", "Diputado"]:
        for cells in data["rows"]:
            folio, advisor, amount, deputy, _, doc, *_ = [cell["text"] for cell in cells]
            rows.append([deputy, year, doc, folio, f"{year}-{month:02}", advisor, "", amount.replace(".", "")])
    elif report == "SupportStaff" and data["headers"][:3] == ["Distrito", "Diputado", ""]:
        for cells in data["rows"]:
            values = [cell["text"] for cell in cells]
            _, deputy, _, employee, position, pay, election, _, ended, contract, *_ = values
            rows.append([deputy, year, month, contract, employee, position, pay.replace(".", ""), election, ended])
    elif not data["headers"] and any(
        re.search(r"no (han sido publicados|hay |existen |se encontraron )|sin (datos|registros)", text, re.I)
        for text in data["body"]
    ):
        return []
    else:
        raise ValueError(f"Unexpected table heading for {report}: {data['headers']!r}, {data['body']!r}")
    return rows


def scrape(out, report, url, periods):
    output = out / f"{report}.json"
    saved = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    with browser() as driver:
        for year, month in periods:
            period = f"{year}-{month:02}"
            if period in saved:
                continue
            for attempt in range(2):
                try:
                    if attempt or not driver.current_url.startswith(url):
                        driver.get(url)
                    saved[period] = get_month(driver, report, year, month)
                    pending = output.with_suffix(".tmp")
                    pending.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
                    pending.replace(output)
                    print(report, period, f"rows={len(saved[period])}", flush=True)
                    break
                except Exception as error:
                    print(report, period, f"attempt={attempt + 1}", type(error).__name__,
                          str(error).splitlines()[0], flush=True)
    fields = next(fields for name, _, fields in REPORTS if name == report)
    pending = out / f"{report}.csv.tmp"
    with pending.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(fields)
        writer.writerows(row for rows in saved.values() for row in rows)
    pending.replace(out / f"{report}.csv")
    return len(saved) == len(periods)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--end-month", type=int, choices=range(1, 13), required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    periods = [(year, month) for year in range(args.end_year, args.start_year - 1, -1)
               for month in range(args.end_month if year == args.end_year else 12, 0, -1)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(scrape, args.out, report, url, periods) for report, url in URLS.items()]
        complete = [future.result() for future in futures]
    return 0 if all(complete) else 1


if __name__ == "__main__":
    raise SystemExit(main())
