"""Рисует слайды инструкции по боту в app/assets/guide/*.png (запуск: python tools/make_guide.py).

Нужен Pillow; в самом боте он не требуется, он только показывает готовые картинки.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "app" / "assets" / "guide"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
W, H = 1280, 960
BG, INK, ACCENT, SOFT = (250, 246, 240), (40, 36, 32), (200, 90, 50), (236, 226, 214)

SLIDES = [
    ("★", "Добро пожаловать!", "Это внутренний бот ресторанов.",
     ["Здесь учебные материалы, карточки блюд и напитков,",
      "запись на тренинги и обратная связь.",
      "Всё в одном месте и всегда под рукой.",
      "Дальше несколько простых слайдов."]),
    ("1", "Кнопки внизу экрана", "Это главное меню бота.",
     ["Нажимайте на нужный раздел внизу, как на кнопки.",
      "Пропали кнопки? Отправьте боту /start.",
      "Передумали на полпути? Нажмите «Отмена»."]),
    ("2", "Мой старт", "Чек-лист для новичков.",
     ["Откройте материал, изучите его",
      "и нажмите «Изучил(а)».",
      "Полоска показывает, сколько уже пройдено.",
      "Когда пройдёте всё, менеджер по обучению узнает."]),
    ("3", "База знаний и карточки", "Ответы на рабочие вопросы.",
     ["Выберите раздел и откройте нужный материал.",
      "Презентации приходят слайдами-картинками,",
      "а кнопка «Скачать PDF» отдаёт полный файл.",
      "В карточках: состав, подача, аллергены."]),
    ("4", "Тренинги", "Запись и напоминания.",
     ["Выберите тренинг и нажмите «Записаться».",
      "Если мест нет, вы встанете в очередь.",
      "Бот напомнит о тренинге заранее",
      "и пришлёт файл для вашего календаря."]),
    ("5", "Обратная связь", "Можно анонимно.",
     ["Напишите предложение или проблему.",
      "При анонимной отправке бот не хранит автора,",
      "а только ваш ресторан."]),
    ("6", "Если что-то не получилось", "Мы поможем.",
     ["В разделе «Помощь и контакты» есть,",
      "к кому обратиться по любому вопросу.",
      "Пишите — это нормально, спрашивать можно."]),
]


def font(path, size):
    return ImageFont.truetype(path, size)


def draw_slide(i, mark, title, sub, lines):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 18], fill=ACCENT)
    d.ellipse([80, 110, 230, 260], fill=ACCENT)
    f = font(BOLD, 84 if len(mark) == 1 else 72)
    box = d.textbbox((0, 0), mark, font=f)
    d.text((155 - (box[2] - box[0]) / 2 - box[0], 185 - (box[3] - box[1]) / 2 - box[1]), mark, font=f, fill="white")
    d.text((270, 120), title, font=font(BOLD, 56), fill=INK)
    d.text((270, 200), sub, font=font(FONT, 36), fill=ACCENT)
    d.rounded_rectangle([80, 330, W - 80, H - 130], radius=28, fill=SOFT)
    y = 380
    for line in lines:
        size = 40
        while d.textlength(line, font=font(FONT, size)) > W - 260:
            size -= 2
        d.text((130, y), line, font=font(FONT, size), fill=INK)
        y += 82
    d.text((80, H - 80), f"{i} из {len(SLIDES)}", font=font(FONT, 30), fill=(120, 110, 100))
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    for i, s in enumerate(SLIDES, 1):
        draw_slide(i, *s).save(OUT / f"{i:02d}.png", optimize=True)


if __name__ == "__main__":
    main()
