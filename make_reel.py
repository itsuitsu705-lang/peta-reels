#!/usr/bin/env python3
"""『PETA』リール動画（本番用の型・毎回同じ構成）
縦1080×1920／30fps／約25秒／字幕・効果・オルゴール風BGM入り

構成（毎回同じ）
  1 つかみ        「うちの子が LINEスタンプに なったら…？」＋ペットの写真
  2 写真→スタンプ 写真が上に移動し、矢印の先にスタンプがポンと登場「写真を送るだけで この子らしいスタンプに」
  3 スタンプ紹介  9コマが1つずつポンと登場（セリフ付き）「表情もセリフも この子らしく」
  4 使う場面      LINEのトーク画面風（青い背景・白い吹き出し）でスタンプを送る「家族とのLINEが もっと楽しく」
  ※スタンプを見せる場面の背景はLINEのトーク画面と同じ青
  5 料金          料金表「はじめての方は 500円OFF」
  6 案内          「コメントくれた方に 詳細をDMでお送りします」「保存して、あとで見返してね」

使い方:
  python make_reel.py --photo photo.png --cover cover.png --sheet sheet.png --price sns_price.jpg --logo logo.png --out reel.mp4
  （セリフや字幕は --config で JSON を渡すと差し替えられる）
"""
import argparse, json, math, subprocess, tempfile, wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
# インスタのリールは上（約250px）と下（約450px）、右下にボタンや説明文が重なるので、大事なものは y=250〜1480 に置く
# プロフィール一覧では中央の3:4（y=240〜1680）だけが表示されるので、表紙の文字はその内側に置く
CAP_Y = 1365                     # 字幕の帯の中心
LINE_BG = (140, 171, 216)        # LINEのトーク画面の背景（青）
INK = (44, 52, 84)               # 文字の色
HERE = Path(__file__).resolve().parent
FONT_DIRS = [HERE / 'fonts', Path.home() / '.fonts']

DEFAULT = {
    'hook': ['うちの子が', 'LINEスタンプに', 'なったら…？'],
    'sub_photo': ['写真を送るだけで', 'この子らしいスタンプに'],
    'tag_photo': '写真', 'tag_stamp': 'スタンプ',
    'thumb': ['うちの子の写真が', 'LINEスタンプに！'],
    'words': ['おはよう', 'ありがとう', 'おやすみ', 'わーい！', 'OK！', 'ごめんね', '大好き', 'ごはん\nまだ？', 'えっ！？'],
    'word_colors': ['#F08A24', '#E8517A', '#5B6CD6', '#F2A10C', '#2FA36B', '#7C6BD6', '#E8517A', '#D9822B', '#3C8CE0'],
    'sub_stickers': ['表情もセリフも', 'この子らしく'],
    'sub_chat': ['家族とのLINEが', 'もっと楽しく'],
    'sub_price': ['はじめての方は', '500円OFF'],
    'cta': ['コメントくれた方に', '詳細をDMで', 'お送りします'],
    'save': '保存して、あとで見返してね',
    'note': '※画像はAIで作ったイメージです',
}


# トークの内容（毎回変える。--seed の値で順番に選ぶ）
# 数字はスタンプの番号：0おはよう 1ありがとう 2おやすみ 3わーい！ 4OK！ 5ごめんね 6大好き 7ごはんまだ？ 8えっ！？
CHAT_SETS = [
    ('かぞく（3）', '18:29', [['left', '今日は早めに帰るね'], ['right', 3], ['left', 'いつもありがとうね'], ['right', 6]]),
    ('お母さん', '7:12', [['left', 'おはよう、今朝は冷えるね'], ['right', 0], ['left', '風邪ひかないようにね'], ['right', 1]]),
    ('かぞく（4）', '17:45', [['left', '駅に着いたよ'], ['right', 4], ['left', '晩ごはんはカレーだよ'], ['right', 3]]),
    ('みか', '22:10', [['left', 'そろそろ寝るね'], ['right', 2], ['left', '明日のランチ楽しみ'], ['right', 6]]),
    ('姉妹（3）', '12:05', [['left', 'お土産買ったよ'], ['right', 8], ['left', '週末に持っていくね'], ['right', 3]]),
    ('お父さん', '19:02', [['left', 'ごめん、少し遅くなる'], ['right', 4], ['left', '先に食べててね'], ['right', 7]]),
    ('かぞく（3）', '15:30', [['left', '雨が降ってきたよ'], ['right', 8], ['left', '傘持っていった？'], ['right', 5]]),
    ('ゆき', '20:15', [['left', 'お誕生日おめでとう！'], ['right', 1], ['left', 'プレゼント届いたかな'], ['right', 6]]),
    ('かぞく（4）', '10:20', [['left', '孫が遊びに来たよ'], ['right', 3], ['left', 'また来週も来るって'], ['right', 6]]),
    ('お母さん', '18:40', [['left', 'ちゃんと食べてる？'], ['right', 4], ['left', '野菜を送ったからね'], ['right', 1]]),
    ('さとみ', '21:30', [['left', '今日はおつかれさま'], ['right', 1], ['left', 'ゆっくり休んでね'], ['right', 2]]),
    ('かぞく（3）', '8:05', [['left', 'いってきます'], ['right', 0], ['left', '帰りに牛乳買うね'], ['right', 4]]),
]


def chat_of(seed):
    title, t0, chat = CHAT_SETS[seed % len(CHAT_SETS)]
    h, m = map(int, t0.split(':'))
    times = [f'{h + (m + k) // 60}:{(m + k) % 60:02d}' for k in (0, 1, 2, 2)]
    import re
    g = re.search(r'（(\d+)）', title)               # グループなら「既読 人数-1」、1対1なら「既読」
    return {'chat_title': title, 'chat': chat, 'chat_times': times, 'read': f'既読 {int(g.group(1)) - 1}' if g else '既読'}


def font(size, weight='ExtraBold'):
    for d in FONT_DIRS:
        p = d / f'MPLUSRounded1c-{weight}.ttf'
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', size)


def ease(t):
    t = max(0.0, min(1.0, t)); return t * t * (3 - 2 * t)


def back_out(t):   # ポンと少し大きくなって戻る
    t = max(0.0, min(1.0, t)); c = 1.9
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def hex2rgb(h): h = h.lstrip('#'); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lighten(c, k): return tuple(int(v + (255 - v) * k) for v in c)


def bg_color(img):
    a = np.asarray(img.convert('RGB').resize((32, 32)))
    corners = np.concatenate([a[:3, :3].reshape(-1, 3), a[:3, -3:].reshape(-1, 3), a[-3:, :3].reshape(-1, 3), a[-3:, -3:].reshape(-1, 3)])
    return tuple(int(x) for x in corners.mean(0))


def gradient(c1, c2):
    g = np.linspace(0, 1, H)[:, None, None]
    arr = (np.array(c1)[None, None, :] * (1 - g) + np.array(c2)[None, None, :] * g).astype(np.uint8)
    return Image.fromarray(np.repeat(arr, W, axis=1), 'RGB')


def cutout(img, bg, tol=38):
    """背景色に近い画素を透明にする（白フチのおかげでキャラは残る）"""
    a = np.asarray(img.convert('RGB')).astype(np.int16)
    dist = np.abs(a - np.array(bg)[None, None, :]).sum(2)
    alpha = np.clip((dist - tol) * 6, 0, 255).astype(np.uint8)
    am = Image.fromarray(alpha).filter(ImageFilter.GaussianBlur(0.8))
    im = img.convert('RGBA'); im.putalpha(am)
    bbox = am.point(lambda v: 255 if v > 160 else 0).filter(ImageFilter.MinFilter(5)).getbbox()   # ノイズを除いた本体の範囲
    if bbox: bbox = (max(0, bbox[0] - 6), max(0, bbox[1] - 6), min(im.width, bbox[2] + 6), min(im.height, bbox[3] + 6))
    return im.crop(bbox) if bbox else im


def split_sheet(sheet, bg, tol=38):
    """表情シートから9コマを、それぞれの形で切り抜く（つながった塊ごとに分ける）"""
    from scipy import ndimage
    a = np.asarray(sheet.convert('RGB')).astype(np.int16)
    fg = np.abs(a - np.array(bg)[None, None, :]).sum(2) > tol
    fg = ndimage.binary_closing(fg, iterations=3)
    fg = ndimage.binary_fill_holes(fg)
    lab, n = ndimage.label(fg)
    sizes = ndimage.sum(fg, lab, range(1, n + 1))
    keep = [k + 1 for k in np.argsort(sizes)[::-1][:9]]
    objs = ndimage.find_objects(lab)
    items = []
    for k in keep:
        sl = objs[k - 1]
        y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        crop = sheet.crop((x0, y0, x1, y1)).convert('RGBA')
        m = (lab[y0:y1, x0:x1] == k).astype(np.uint8) * 255
        crop.putalpha(Image.fromarray(m).filter(ImageFilter.GaussianBlur(0.8)))
        items.append(((y0 + y1) / 2, (x0 + x1) / 2, crop))
    if len(items) < 9:   # うまく分けられないときは3×3で区切る
        w, h = sheet.size
        return [cutout(sheet.crop((int(c * w / 3), int(r * h / 3), int((c + 1) * w / 3), int((r + 1) * h / 3))), bg) for r in range(3) for c in range(3)]
    items.sort(key=lambda t: t[0])
    rows = [sorted(items[i:i + 3], key=lambda t: t[1]) for i in (0, 3, 6)]
    return [t[2] for r in rows for t in r]


def outlined(draw, xy, text, f, fill, stroke=(255, 255, 255), sw=8, anchor='mm', spacing=4):
    draw.multiline_text(xy, text, font=f, fill=fill, stroke_width=sw, stroke_fill=stroke, anchor=anchor, align='center', spacing=spacing)


def shadowed(canvas, im, cx, cy, scale=1.0, rot=0, shadow=True):
    if scale <= 0.01: return
    w, h = max(1, int(im.width * scale)), max(1, int(im.height * scale))
    s = im.resize((w, h), Image.LANCZOS)
    if rot: s = s.rotate(rot, resample=Image.BICUBIC, expand=True)
    x, y = int(cx - s.width / 2), int(cy - s.height / 2)
    if shadow and s.mode == 'RGBA':
        a = s.split()[3].point(lambda v: v * 0.35).filter(ImageFilter.GaussianBlur(14))
        canvas.paste((60, 50, 80), (x + 8, y + 16), a)
    canvas.paste(s, (x, y), s if s.mode == 'RGBA' else None)


def card(canvas, img, scale, cx, cy, radius=44):
    w, h = int(img.width * scale), int(img.height * scale)
    im = img.resize((w, h), Image.LANCZOS)
    x, y = int(cx - w / 2), int(cy - h / 2)
    sh = Image.new('L', (w + 80, h + 80), 0)
    ImageDraw.Draw(sh).rounded_rectangle((40, 52, w + 40, h + 52), radius=radius, fill=90)
    canvas.paste((40, 30, 50), (x - 40, y - 40), sh.filter(ImageFilter.GaussianBlur(26)))
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
    canvas.paste(im, (x, y), mask)


def polaroid(img, width=760):
    """写真を白いフチのプリント風にする"""
    sc = width / img.width; ph = img.resize((width, int(img.height * sc)), Image.LANCZOS)
    pad = int(width * 0.035); w, h = ph.width + pad * 2, ph.height + pad * 2
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=pad, fill=(255, 255, 255, 255))
    m = Image.new('L', ph.size, 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, ph.width - 1, ph.height - 1), radius=pad // 2, fill=255)
    im.paste(ph, (pad, pad), m)
    return im


def tag(d, xy, text, k=1.0, size=50):
    if k <= 0.02: return
    f = font(size); tw = d.textlength(text, font=f); x, y = xy
    d.rounded_rectangle((x - tw / 2 - 34, y - size * 0.85, x + tw / 2 + 34, y + size * 0.85), radius=size, fill=(255, 255, 255, int(245 * k)))
    d.text((x, y), text, font=f, fill=INK + (int(255 * k),), anchor='mm')


def arrow(d, x, y0, y1, k=1.0, color=(240, 120, 150)):
    """下向きの太い矢印（k で伸びる）"""
    if k <= 0.02: return
    ye = y0 + (y1 - y0) * k; w = 34; hw = 78; hl = 70
    a = int(255 * min(1, k * 2))
    d.rounded_rectangle((x - w / 2, y0, x + w / 2, max(y0 + 1, ye - hl + 10)), radius=w // 2, fill=color + (a,))
    d.polygon([(x - hw / 2, ye - hl), (x + hw / 2, ye - hl), (x, ye)], fill=color + (a,))


# ---------------------------------------------------------------- BGM（その場で作曲）
def make_bgm(path, seconds, seed=0):
    sr = 44100; rng = np.random.default_rng(seed); n = int(sr * seconds); out = np.zeros(n)
    beat = 60 / 100; scale = [0, 2, 4, 7, 9, 12, 14, 16, 19]; root = 72
    chords = [[0, 4, 7], [9, 12, 16], [5, 9, 12], [7, 11, 14]]
    mid = lambda m: 440 * 2 ** ((m - 69) / 12)
    def tone(freq, dur, amp, decay):
        t = np.arange(int(sr * dur)) / sr
        env = np.exp(-t * decay) * np.minimum(1, t * 300)
        return amp * env * (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t) + 0.1 * np.sin(6 * np.pi * freq * t))
    def add(s, seg):
        s = int(s * sr)
        if s < n: out[s:s + len(seg)] += seg[:n - s]
    motif = [4, 5, 6, 5, 4, 2, 3, 4]   # 覚えやすい短いフレーズを繰り返す
    steps = int(seconds / (beat / 2)); p = 4
    for i in range(steps):
        t0 = i * beat / 2; bar = int(t0 / (beat * 4)) % 4
        if i % 8 == 0:
            for k in chords[bar]: add(t0, tone(mid(root - 12 + k), beat * 4, 0.05, 1.0))
            add(t0, tone(mid(root - 24 + chords[bar][0]), beat * 2, 0.07, 1.5))
        if i % 2 == 0 or rng.random() < 0.4:
            p = motif[i % 8] if (i // 8) % 2 == 0 else int(np.clip(p + rng.integers(-1, 2), 1, 8))
            add(t0, tone(mid(root + scale[p]), beat * 1.6, 0.085, 4.0))
    out[:int(sr * .2)] *= np.linspace(0, 1, int(sr * .2)); f = int(sr * 1.5); out[-f:] *= np.linspace(1, 0, f)
    out = out / (np.abs(out).max() + 1e-9) * 0.5
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((out * 32767).astype(np.int16).tobytes())
    return sr


def add_pops(path, times, sr=44100):
    """スタンプが出るときの「ポン」という小さな効果音を足す"""
    with wave.open(str(path), 'rb') as w: a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64) / 32767
    t = np.arange(int(sr * .12)) / sr
    pop = 0.35 * np.sin(2 * np.pi * (900 - 2500 * t) * t) * np.exp(-t * 40)
    for tt in times:
        s = int(tt * sr)
        if s < len(a): a[s:s + len(pop)] += pop[:len(a) - s]
    a = a / max(1.0, np.abs(a).max())
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((a * 32767).astype(np.int16).tobytes())


# ---------------------------------------------------------------- 本体
def build(a, cfg):
    cover = Image.open(a.cover).convert('RGB'); sheet = Image.open(a.sheet).convert('RGB')
    price = Image.open(a.price).convert('RGB'); logo = Image.open(a.logo).convert('RGB')
    photo = polaroid(Image.open(a.photo).convert('RGB'))
    base = bg_color(cover)
    bg = gradient(lighten(LINE_BG, 0.42), LINE_BG)       # 全体の背景：LINEのトーク画面の青
    char = cutout(cover, base)
    stickers = split_sheet(sheet, bg_color(sheet))
    F_cap, F_hook, F_note = font(68), font(98), font(28, 'Medium')
    pops = []

    def caption(d, lines, t=1.0):
        if not lines: return
        k = ease(min(1, t * 6))
        lh = 92; top = CAP_Y - lh * len(lines) // 2 + int(30 * (1 - k))
        wmax = max(d.textlength(l, font=F_cap) for l in lines)
        d.rounded_rectangle((W / 2 - wmax / 2 - 46, top - 34, W / 2 + wmax / 2 + 46, top + lh * len(lines) + 18), radius=40, fill=(46, 40, 60, int(200 * k)))
        for i, l in enumerate(lines):
            d.text((W / 2, top + i * lh + 38), l, font=F_cap, fill=(255, 255, 255, int(255 * k)), anchor='mm')

    def note(d):
        d.text((W / 2, 1492), cfg['note'], font=F_note, fill=(40, 48, 78), anchor='mm')   # 目立たせず、隠れない位置に

    PH0 = (W / 2, 1010, 0.78, -3)       # つかみでの写真（中心x, 中心y, 大きさ, 傾き）
    PH1 = (W / 2, 500, 0.48, -5)  # 写真→スタンプの場面で上に移動したあと
    ST = (W / 2, 1000)              # スタンプの位置
    st_scale = 480 / max(char.width, char.height)
    AX = W - 170                         # 右側の「写真 ↓ スタンプ」の列

    def s_hook(c, d, t, T):
        k = back_out(min(1, t * 1.6))
        shadowed(c, photo, PH0[0], PH0[1], PH0[2] * k * (1 + 0.03 * t), rot=PH0[3])
        for i, l in enumerate(cfg['hook']):
            k = ease(min(1, max(0, t * 3 - i * 0.35)))
            outlined(d, (W / 2, 300 + i * 120 + int(40 * (1 - k))), l, F_hook, INK + (int(255 * k),), stroke=(255, 255, 255, int(255 * k)), sw=14)
        note(d)

    def s_photo(c, d, t, T):
        sec = t * T
        m = ease(min(1, sec / 0.8))                      # 写真が上へ移動
        lerp = lambda i: PH0[i] + (PH1[i] - PH0[i]) * m
        shadowed(c, photo, lerp(0), lerp(1), lerp(2), rot=lerp(3))
        ks = back_out(min(1, max(0, (sec - 0.95) / 0.45)))   # スタンプがポンと登場
        if ks > 0.01:
            shadowed(c, char, ST[0], ST[1], st_scale * ks * (1 + 0.03 * max(0, sec - 1.4) / T))
        d = ImageDraw.Draw(c, 'RGBA')
        caption(d, cfg['sub_photo'], max(0, sec - 1.0) / 0.6)
        note(d)

    gap = 0.42
    def s_stickers(c, d, t, T):
        sec = t * T
        cw, ch = W / 3, 290
        for i, st in enumerate(stickers):
            r, col = divmod(i, 3)
            appear = 0.2 + i * gap
            if sec < appear: continue
            k = back_out(min(1, (sec - appear) / 0.35))
            cx, cy = cw * (col + 0.5), 330 + ch * (r + 0.5) + 40
            sc = min(cw * 0.86 / st.width, ch * 0.80 / st.height)
            shadowed(c, st, cx, cy + 18, sc * k)
            if k > 0.6:
                f = font(54 if '\n' not in cfg['words'][i] else 46)
                outlined(d, (cx, cy - ch * 0.36), cfg['words'][i], f, hex2rgb(cfg['word_colors'][i]), sw=9)
        caption(d, cfg['sub_stickers'], max(0, sec - 0.2) / 0.6)
        note(d)

    def s_chat(c, d, t, T):
        """LINEのトーク画面風：青い背景・上に名前のバー・相手は白い吹き出し・自分のスタンプは右に大きく"""
        sec = t * T
        top, bottom = 0, 1240
        d.rectangle((0, top, W, bottom), fill=LINE_BG + (255,))
        d.rectangle((0, 0, W, 340), fill=(245, 247, 251, 255))                       # 上のバー
        d.line((54, 297, 84, 267), fill=INK, width=8); d.line((54, 297, 84, 327), fill=INK, width=8)   # 戻る「＜」
        d.text((W / 2, 297), cfg['chat_title'], font=font(48, 'Bold'), fill=INK, anchor='mm')
        d.rectangle((0, bottom - 100, W, bottom), fill=(255, 255, 255, 255))            # 下の入力欄
        d.text((70, bottom - 50), '＋', font=font(64, 'Bold'), fill=(120, 128, 150), anchor='mm')
        d.rounded_rectangle((130, bottom - 85, W - 70, bottom - 15), radius=35, fill=(240, 242, 246, 255))
        d.text((165, bottom - 50), 'Aa', font=font(36, 'Medium'), fill=(160, 166, 182), anchor='lm')
        y = 370; tm = cfg['chat_times']
        for j, (side, val) in enumerate(cfg['chat']):
            appear = 0.25 + j * 1.0
            if sec < appear: break
            k = ease(min(1, (sec - appear) / 0.3)); dy = int(20 * (1 - k)); al = int(255 * k)
            if side == 'left':      # 相手の吹き出し（アイコン・名前はなし）
                f = font(48, 'Bold'); tw = d.textlength(val, font=f)
                bx0, by0, bx1, by1 = 70, y + dy, 70 + tw + 72, y + 96 + dy
                d.rounded_rectangle((bx0, by0, bx1, by1), radius=50, fill=(255, 255, 255, al))
                d.polygon([(bx0 + 8, by0 + 26), (bx0 - 16, by0 + 18), (bx0 + 14, by0 + 52)], fill=(255, 255, 255, al))   # 吹き出しのしっぽ
                d.text((bx0 + 38, (by0 + by1) / 2), val, font=f, fill=(30, 30, 40, al), anchor='lm')
                d.text((bx1 + 14, by1 - 8), tm[j], font=font(26, 'Medium'), fill=(40, 48, 78, al), anchor='lb')
                y += 125
            else:                   # 自分が送ったスタンプ（右に大きく）
                st = stickers[int(val)]; size = 190
                sc = size / max(st.width, st.height) * back_out(min(1, (sec - appear) / 0.35))
                cx, cy = W - 250, y + 55 + size / 2
                shadowed(c, st, cx, cy, sc, shadow=False)
                if k > 0.6:
                    outlined(d, (cx, y + 30), cfg['words'][int(val)], font(44), hex2rgb(cfg['word_colors'][int(val)]), sw=8)
                    d.text((cx - size / 2 - 20, cy + size / 2 - 40), cfg['read'], font=font(26, 'Medium'), fill=(40, 48, 78), anchor='rb')
                    d.text((cx - size / 2 - 20, cy + size / 2 - 6), tm[j], font=font(26, 'Medium'), fill=(40, 48, 78), anchor='rb')
                y += 55 + size + 25
        caption(d, cfg['sub_chat'], sec / 0.6)

    def s_price(c, d, t, T):
        card(c, price, 0.70 + 0.02 * t, W / 2, 760)
        caption(d, cfg['sub_price'], t * T / 0.6)

    def s_cta(c, d, t, T):
        k = back_out(min(1, t * 2.2))
        card(c, logo, 0.45 * k if k > 0.05 else 0.05, W / 2, 520, radius=60)
        for i, l in enumerate(cfg['cta']):
            outlined(d, (W / 2, 880 + i * 108), l, font(80), INK, sw=12)
        kk = ease(min(1, max(0, t * 3 - 1)))
        d.rounded_rectangle((150, 1250, W - 150, 1380), radius=65, fill=(232, 81, 122, int(255 * kk)))
        d.text((W / 2, 1315), cfg['save'], font=font(52), fill=(255, 255, 255, int(255 * kk)), anchor='mm')

    scenes = [(2.8, s_hook), (3.8, s_photo), (0.2 + 9 * gap + 1.6, s_stickers), (4.6, s_chat), (3.6, s_price), (4.2, s_cta)]
    start = 2.8 + 3.8
    pops = [2.8 + 0.95] + [start + 0.2 + i * gap for i in range(9)]   # スタンプ登場の音も
    cstart = start + scenes[2][0]
    pops += [cstart + 0.25 + j * 1.0 for j, (s, _) in enumerate(cfg['chat']) if s == 'right']
    total = sum(s for s, _ in scenes)

    tmp = Path(tempfile.mkdtemp()); wav = tmp / 'bgm.wav'
    make_bgm(wav, total + 0.3, seed=a.seed); add_pops(wav, pops)
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
           '-i', str(wav), '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-r', str(FPS),
           '-c:a', 'aac', '-b:a', '192k', '-ar', '44100', '-shortest', '-movflags', '+faststart', a.out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    XF = 0.3; prev = None
    for sec_len, fn in scenes:
        nf = int(sec_len * FPS); last = None
        for k in range(nf):
            t = k / max(1, nf - 1)
            cv = bg.copy(); d = ImageDraw.Draw(cv, 'RGBA')
            fn(cv, d, t, sec_len)
            if prev is not None and k < XF * FPS: cv = Image.blend(prev, cv, k / (XF * FPS))
            p.stdin.write(cv.tobytes()); last = cv
        prev = last
    p.stdin.close(); p.wait()
    if p.returncode: raise SystemExit('ffmpeg failed')
    if a.thumb:   # リールの表紙（1枚目の見せ場）
        th = bg.copy(); d = ImageDraw.Draw(th, 'RGBA')
        shadowed(th, photo, W / 2, 830, 0.42, rot=-5); shadowed(th, char, W / 2, 1290, st_scale * 0.95)
        d = ImageDraw.Draw(th, 'RGBA')
        for i, l in enumerate(cfg['thumb']): outlined(d, (W / 2, 360 + i * 115), l, font(86), INK, sw=14)
        d.text((W / 2, 1650), cfg['note'], font=F_note, fill=(40, 48, 78), anchor='mm'); th.convert('RGB').save(a.thumb, quality=92)
    return total


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    for k in ('photo', 'cover', 'sheet', 'price', 'logo', 'out'): ap.add_argument('--' + k, required=True)
    ap.add_argument('--thumb', default=''); ap.add_argument('--config', default=''); ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    cfg = dict(DEFAULT); cfg.update(chat_of(a.seed))   # トークの内容は seed（例：日付の番号）で毎回変わる
    if a.config: cfg.update(json.load(open(a.config, encoding='utf-8')))
    print('秒数', round(build(a, cfg), 1))
