"""その日のリール動画を作る（GitHub Actions から実行）
GAS（PETA受付ボット）から今日の画像のURLをもらい、make_reel.py で動画と表紙を作って reels/ に保存する。"""
import base64, datetime, json, os, pathlib, subprocess, sys, time
import requests

GAS = 'https://script.google.com/macros/s/AKfycbze-njgb4_xhXh5qXtHni0MgTOQ7cuf4AJKl3Aal2bgMS0-uGqHq6dkdhFwwxDSzmIT/exec'
FONT_URL = 'https://raw.githubusercontent.com/google/fonts/main/ofl/mplusrounded1c/MPLUSRounded1c-{}.ttf'
HERE = pathlib.Path(__file__).resolve().parent
JST = datetime.timezone(datetime.timedelta(hours=9))

def get(url, tries=4):
    for i in range(tries):
        try:
            r = requests.get(url, timeout=300)
            if r.status_code == 200: return r
            print('HTTP', r.status_code, url[:80])
        except Exception as e: print('エラー', e)
        time.sleep(10 * (i + 1))
    sys.exit('取得できませんでした: ' + url[:80])

def main():
    date = os.environ.get('REEL_DATE') or datetime.datetime.now(JST).strftime('%Y-%m-%d')
    info = get(f'{GAS}?action=reel&date={date}').json()
    print(json.dumps({k: v for k, v in info.items() if k != 'urls'}, ensure_ascii=False))
    if not info.get('ok'): sys.exit('GASから素材をもらえませんでした')
    work = HERE / 'work'; work.mkdir(exist_ok=True)
    fonts = HERE / 'fonts'; fonts.mkdir(exist_ok=True)
    for w in ('ExtraBold', 'Bold', 'Medium'):
        p = fonts / f'MPLUSRounded1c-{w}.ttf'
        if not p.exists():
            try: p.write_bytes(get(FONT_URL.format(w), 2).content)
            except SystemExit: print('フォントは標準のものを使います')
    for k, u in info['urls'].items():
        (work / f'{k}.jpg').write_bytes(get(u).content)
    (work / 'logo.jpg').write_bytes(base64.b64decode((HERE / 'logo_b64.txt').read_text()))
    out = HERE / 'reels'; out.mkdir(exist_ok=True)
    cmd = [sys.executable, str(HERE / 'make_reel.py'), '--photo', str(work / 'photo.jpg'), '--cover', str(work / 'stamp.jpg'),
           '--sheet', str(work / 'sheet.jpg'), '--price', str(work / 'price.jpg'), '--logo', str(work / 'logo.jpg'),
           '--out', str(out / f'{date}.mp4'), '--thumb', str(out / f'{date}.jpg'), '--seed', str(info.get('seed', 0))]
    subprocess.run(cmd, check=True)
    # 3週間より前の動画は消す（保存場所を増やしすぎない）
    limit = (datetime.datetime.now(JST) - datetime.timedelta(days=21)).strftime('%Y-%m-%d')
    for f in out.glob('*'):
        if f.stem < limit: f.unlink()
    print('できました', date)

if __name__ == '__main__':
    main()
