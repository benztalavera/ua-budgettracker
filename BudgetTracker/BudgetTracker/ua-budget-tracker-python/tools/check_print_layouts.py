"""Optional Chromium/PDF audit; use a disposable test copy and environment credentials."""

import asyncio, base64, json, re, http.cookiejar, urllib.request, urllib.parse, os
from pathlib import Path
from choreographer import Browser
from pypdf import PdfReader

ROOT = Path(os.getenv("OUTPUT_DIR", "print-audit"))
ROOT.mkdir(exist_ok=True)
BASE = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def login(email, password):
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    html = op.open(BASE + "/login").read().decode()
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    result = op.open(
        BASE + "/login",
        urllib.parse.urlencode(
            {"csrf_token": token, "email": email, "password": password}
        ).encode(),
    )
    assert "/login" not in result.url, result.url
    return next(c.value for c in jar if c.name == "session")


def val(r):
    return r.get("result", {}).get("result", {}).get("value")


async def main():
    cookies = {
        "admin": login(os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"]),
        "student": login(os.environ["STUDENT_EMAIL"], os.environ["STUDENT_PASSWORD"]),
    }
    report = []
    async with Browser(os.environ["CHROME_BIN"]) as b:
        tab = await b.create_tab()
        await tab.send_command("Page.enable")
        await tab.send_command("Network.enable")

        async def nav(path, role=None):
            await tab.send_command("Network.clearBrowserCookies")
            if role:
                await tab.send_command(
                    "Network.setCookie",
                    {
                        "name": "session",
                        "value": cookies[role],
                        "domain": urllib.parse.urlparse(BASE).hostname,
                        "path": "/",
                        "httpOnly": True,
                    },
                )
            fut = tab.subscribe_once("Page.loadEventFired")
            await tab.send_command("Page.navigate", {"url": BASE + path})
            await asyncio.wait_for(fut, 25)
            await asyncio.sleep(0.4)

        async def js(expr):
            return val(
                await tab.send_command(
                    "Runtime.evaluate", {"expression": expr, "returnByValue": True}
                )
            )

        async def shot(name):
            r = await tab.send_command(
                "Page.captureScreenshot",
                {"format": "png", "captureBeyondViewport": False},
            )
            (ROOT / (name + ".png")).write_bytes(base64.b64decode(r["result"]["data"]))

        await tab.send_command(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
        )
        for role, path, name in [
            (None, "/", "public"),
            ("admin", "/admin", "admin"),
            ("admin", "/admin/landing", "studio"),
            ("student", "/user/dashboard", "student"),
        ]:
            await nav(path, role)
            await shot(name)
            print(
                name,
                await js(
                    "JSON.stringify({title:document.title,width:innerWidth,scroll:document.documentElement.scrollWidth,broken:Array.from(document.images).filter(i=>!i.complete||!i.naturalWidth).map(i=>i.src)})"
                ),
                flush=True,
            )
        paths = (
            [
                ("admin", "/admin/" + p + "?do=print")
                for p in [
                    "events",
                    "galleries",
                    "videos",
                    "advertisements",
                    "categories",
                    "users",
                    "registrations",
                    "monitor",
                    "reports",
                    "howto",
                    "flowchart",
                ]
            ]
            + [
                (
                    "admin",
                    "/admin/monitor?student=" + os.environ["STUDENT_ID"] + "&do=print",
                )
            ]
            + [
                ("student", "/user/" + p + "?do=print")
                for p in ["incomes", "expenses", "budgets", "behavior", "reports"]
            ]
        )
        for role, path in paths:
            await nav(path, role)
            measure = json.loads(
                await js(
                    """JSON.stringify((()=>{var src=document.querySelector('.p-doc');var sheets=Array.from(document.querySelectorAll('.p-sheet,.fc-sheet'));var errors=[];sheets.forEach(s=>{var b=s.querySelector('.p-sheet-body');if(!b)return;if(b.scrollHeight>b.clientHeight+2)errors.push('height overflow');var r=b.getBoundingClientRect();b.querySelectorAll('table').forEach(t=>{if(t.getBoundingClientRect().right>r.right+1)errors.push('table overflow')});b.querySelectorAll('td,th').forEach(c=>{if(c.scrollWidth>c.clientWidth+2)errors.push('cell overflow')})});return {pages:sheets.length,errors,sourceRows:src?src.querySelectorAll('tbody tr').length:0,visibleRows:sheets.reduce((n,s)=>n+s.querySelectorAll('tbody tr').length,0)}})())"""
                )
            )
            r = await tab.send_command(
                "Page.printToPDF", {"printBackground": True, "preferCSSPageSize": True}
            )
            name = path.replace("/", "-").replace("?", "-").replace("&", "-")
            file = ROOT / (name + ".pdf")
            file.write_bytes(base64.b64decode(r["result"]["data"]))
            reader = PdfReader(file)
            measure.update(path=path, pdfPages=len(reader.pages))
            report.append(measure)
            print("PRINT", json.dumps(measure), flush=True)
            assert (
                measure["pages"] == measure["pdfPages"]
                and not measure["errors"]
                and measure["sourceRows"] == measure["visibleRows"]
            ), measure
        await tab.send_command(
            "Emulation.setDeviceMetricsOverride",
            {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True},
        )
        for role, path, name in [
            (None, "/", "mobile-public"),
            ("student", "/user/dashboard", "mobile-student"),
            ("admin", "/admin/landing", "mobile-studio"),
        ]:
            await nav(path, role)
            await shot(name)
            result = json.loads(
                await js(
                    "JSON.stringify({width:innerWidth,scroll:document.documentElement.scrollWidth})"
                )
            )
            print(name, result, flush=True)
            assert result["width"] == result["scroll"], result
    (ROOT / "print-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
