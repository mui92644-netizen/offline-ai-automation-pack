import asyncio, json, os, httpx, time, hashlib
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

CONFIG_PATH = "agent-browsing.config.json"
with open(CONFIG_PATH) as f:
    CFG = json.load(f)

OUTPUT_DIR = Path(os.getenv("AGENT_OUTPUT_DIR", CFG["file_policy"]["output_dir"]))
ALLOWED_EXT = {ext.lstrip(".") for ext in CFG["file_policy"]["allowed_extensions"]}
MAX_SIZE = CFG["file_policy"]["max_download_mb"] * 1024 * 1024

# ---------- Helper: Structured DOM Snapshot ----------
def build_snapshot(page):
    return """
    ## STRUCTURE SNAPSHOT
    @e0 body(html:1)
    """ + "\n".join([
        f"@e{i+1} <{el['tag']}>{el['text'][:30].replace(chr(10),' ')}| href:{el.get('href','')}| clickable:{el['clickable']}"
        for i, el in enumerate(page.evaluate("""
            () => Array.from(document.querySelectorAll('*')).slice(0, 50)
                  .map((el,i)=>({i:i, tag:el.tagName, text:el.innerText?.trim(), href:el.href, clickable:el.clickable}))
        """))
    ])

# ---------- Helper: LLM Decision (FreeLLMAPI Proxy) ----------
async def get_action(snapshot, goal, task_type="scrape"):
    payload = {
        "messages": [
            {"role":"system","content":"You are a deterministic browser agent. Return ONLY a JSON object: {\"action\":\"click|type|navigate|download|wait\",\"ref\":\"@eN\",\"value\":\"optional\",\"target_url\":\"optional\"}"},
            {"role":"user","content":f"GOAL: {goal}\nCURRENT STATE:\n{snapshot}\nTASK MODE: {task_type}"}
        ],
        "model": CFG["llm_routing"]["model_fallback"][0],
        "temperature": CFG["llm_routing"]["temperature"],
        "max_tokens": CFG["llm_routing"]["max_tokens"]
    }
    headers = {"Content-Type":"application/json", "Authorization": CFG["llm_routing"]["auth_template"].replace("${FREEAPI_AGENT_KEY}", os.getenv("FREEAPI_AGENT_KEY"))}
    
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(CFG["llm_routing"]["endpoint"].replace("${FREEAPI_PROXY_URL}", os.getenv("FREEAPI_PROXY_URL")), headers=headers, json=payload)
            return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        print(f"[WARN] LLM failed: {e}. Using safe wait.")
        return {"action":"wait", "ref":"","value":""}

# ---------- Main Loop ----------
async def run_agent(url, goal, mode="scrape"):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=os.getenv("BROWSER_HEADLESS","true").lower()=="true")
        ctx = await browser.new_context(storage_state=CFG["session"]["storage_state_path"] if Path(CFG["session"]["storage_state_path"]).exists() else None)
        page = await ctx.new_page()

        downloads = []
        async def save_dl(dl):
            fname = dl.suggested_filename
            ext = fname.split(".")[-1] if "." in fname else ""
            if ext.upper() not in {e.upper() for e in ALLOWED_EXT}:
                await dl.cancel()
                return
            dest = OUTPUT_DIR / fname
            if dest.exists() and CFG["file_policy"]["auto_rename_duplicates"]:
                dest = OUTPUT_DIR / f"{Path(fname).stem}_{int(time.time())}.{ext}"
            await dl.save_as(dest)
            downloads.append(dest)

        page.on("download", save_dl)
        await page.goto(url, wait_until="networkidle", timeout=30000)

        # O-D-A-V Loop (max 5 steps)
        for step in range(5):
            snap = build_snapshot(page)
            print(f"Step {step+1} | OBSERVED")
            action = await get_action(snap, goal, mode)
            print(f"Step {step+1} | DECIDED: {action}")

            if action["action"] == "click":
                ref = action.get("ref","@e0")
                idx = int(ref[3:]) if ref.startswith("@e") else 0
                elems = page.evaluate("""() => Array.from(document.querySelectorAll('*')).slice(0,50)""")
                if 0 <= idx < len(elems) and elems[idx].get("clickable"):
                    await page.evaluate(f"""document.querySelectorAll('*').item({idx}).click()""")
                else:
                    await asyncio.sleep(1)
            elif action["action"] == "type":
                target_idx = int(action["ref"][3:]) if action["ref"].startswith("@e") else 0
                elem = page.evaluate(f"""document.querySelectorAll('*').item({target_idx})""")
                if elem:
                    await page.keyboard.type(action["value"])
            elif action["action"] == "navigate":
                await page.goto(action.get("target_url", url))
            elif action["action"] == "wait":
                await asyncio.sleep(2)
            else:
                await asyncio.sleep(1)

        await asyncio.sleep(3) # allow downloads
        print(f"✅ Finished. Extracted/Generated: {[str(p) for p in downloads]}")
        await browser.close()

if __name__ == "__main__":
    import sys
    URL = sys.argv[1] if len(sys.argv)>1 else input("🌐 Target URL: ")
    GOAL = sys.argv[2] if len(sys.argv)>2 else input("🎯 Agent Goal: ")
    MODE = sys.argv[3] if len(sys.argv)>3 else input("🔧 Mode (scrape/create_save_edit) [scrape]: ") or "scrape"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.run(run_agent(URL, GOAL, MODE))
