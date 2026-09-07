#!/usr/bin/env python3
"""
Gallery UX & Layout Stability Test Suite
Verifies that lightbox navigation produces zero caption layout shifts, zero jumps,
and flawless responsive sizing across mixed photo/video galleries.
"""
import asyncio
import json
import sys
import urllib.request
import websockets

CDP_URL = "http://localhost:9225/json"
BASE_URL = "http://localhost:8000"

async def run_ux_test():
    try:
        tabs = json.loads(urllib.request.urlopen(CDP_URL).read().decode('utf-8'))
    except Exception as e:
        print(f"Error: Chrome CDP not reachable at {CDP_URL}: {e}")
        return 1

    page_tab = [t for t in tabs if t.get('type') == 'page' and 'chrome://' not in t.get('url')]
    if not page_tab:
        print("Error: No open page tab found in Chrome.")
        return 1

    ws_url = page_tab[0]['webSocketDebuggerUrl']
    print(f"Connecting to Chrome tab: {page_tab[0].get('url')} ...")

    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        msg_id = 0
        async def cmd(method, params={}):
            nonlocal msg_id
            msg_id += 1
            await ws.send(json.dumps({'id': msg_id, 'method': method, 'params': params}))
            while True:
                raw = await ws.recv()
                data = json.loads(raw)
                if data.get('id') == msg_id:
                    return data.get('result', {})

        # Test 1: Desktop Claw Machine (50 mixed media items)
        print("\n--- Test 1: Desktop 50-Item Forward & Backward Navigation ---")
        await cmd('Page.navigate', {'url': f"{BASE_URL}/major-builds/claw-machine/"})
        await asyncio.sleep(1.5)

        # Open first item
        await cmd('Runtime.evaluate', {'expression': 'openLightbox(0);'})
        await asyncio.sleep(0.3)

        shifts_forward = []
        last_top = None
        for i in range(50):
            res = await cmd('Runtime.evaluate', {'expression': '''(() => {
                const cap = document.querySelector('.lightbox-caption');
                const r = cap.getBoundingClientRect();
                return {
                    top: Math.round(r.top),
                    bottom: Math.round(r.bottom),
                    distFromBottom: Math.round(window.innerHeight - r.bottom)
                };
            })()''', 'returnByValue': True})
            val = res.get('result', {}).get('value')
            if last_top is not None and val['top'] != last_top:
                shifts_forward.append((i, val['top'] - last_top))
            last_top = val['top']
            await cmd('Runtime.evaluate', {'expression': 'nextLightbox();'})
            await asyncio.sleep(0.04)

        if shifts_forward:
            print(f"FAILED: Detected {len(shifts_forward)} caption shifts during forward navigation: {shifts_forward}")
            return 1
        print("PASSED: 50 items navigated forward with 0px caption layout shift.")

        shifts_backward = []
        last_top = None
        for i in range(50):
            await cmd('Runtime.evaluate', {'expression': 'prevLightbox();'})
            await asyncio.sleep(0.04)
            res = await cmd('Runtime.evaluate', {'expression': '''(() => {
                const cap = document.querySelector('.lightbox-caption');
                const r = cap.getBoundingClientRect();
                return { top: Math.round(r.top) };
            })()''', 'returnByValue': True})
            top = res.get('result', {}).get('value', {}).get('top')
            if last_top is not None and top != last_top:
                shifts_backward.append((i, top - last_top))
            last_top = top

        if shifts_backward:
            print(f"FAILED: Detected {len(shifts_backward)} caption shifts during backward navigation: {shifts_backward}")
            return 1
        print("PASSED: 50 items navigated backward with 0px caption layout shift.")

        # Test 2: Mobile Emulation (390x844)
        print("\n--- Test 2: Mobile 50-Item Navigation ---")
        await cmd('Emulation.setDeviceMetricsOverride', {
            'width': 390,
            'height': 844,
            'deviceScaleFactor': 2,
            'mobile': True
        })
        await asyncio.sleep(0.3)

        shifts_mobile = []
        last_top = None
        for i in range(50):
            await cmd('Runtime.evaluate', {'expression': 'nextLightbox();'})
            await asyncio.sleep(0.04)
            res = await cmd('Runtime.evaluate', {'expression': '''(() => {
                const cap = document.querySelector('.lightbox-caption');
                const r = cap.getBoundingClientRect();
                return { top: Math.round(r.top), bottom: Math.round(r.bottom) };
            })()''', 'returnByValue': True})
            val = res.get('result', {}).get('value', {})
            top = val.get('top')
            if last_top is not None and top != last_top:
                shifts_mobile.append((i, top - last_top))
            last_top = top

        await cmd('Emulation.clearDeviceMetricsOverride')

        if shifts_mobile:
            print(f"FAILED: Detected {len(shifts_mobile)} caption shifts during mobile navigation: {shifts_mobile}")
            return 1
        print("PASSED: 50 items navigated on mobile with 0px caption layout shift.")

        # Test 3: Zoom In & Zoom Out
        print("\n--- Test 3: Lightbox Zoom In/Out ---")
        await cmd('Runtime.evaluate', {'expression': 'openLightbox(0);'})
        await asyncio.sleep(0.3)

        res_zoom = await cmd('Runtime.evaluate', {'expression': '''(() => {
            const img = document.getElementById('lightbox-img');
            img.click();
            return {
                zoomed: img.classList.contains('is-zoomed'),
                transform: img.style.transform
            };
        })()''', 'returnByValue': True})
        val_zoom = res_zoom.get('result', {}).get('value')
        if not val_zoom.get('zoomed'):
            print("FAILED: Click did not zoom image in.")
            return 1

        res_unzoom = await cmd('Runtime.evaluate', {'expression': '''(() => {
            const img = document.getElementById('lightbox-img');
            img.click();
            return {
                zoomed: img.classList.contains('is-zoomed'),
                transform: img.style.transform
            };
        })()''', 'returnByValue': True})
        val_unzoom = res_unzoom.get('result', {}).get('value')
        if val_unzoom.get('zoomed'):
            print("FAILED: Click did not zoom image out.")
            return 1
        print("PASSED: Single click zoom in and zoom out verified.")

        # Close lightbox
        await cmd('Runtime.evaluate', {'expression': 'closeLightbox();'})
        print("\nALL GALLERY UX STABILITY TESTS PASSED!")
        return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(run_ux_test()))
