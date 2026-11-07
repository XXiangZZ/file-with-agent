"""Optional real OCR smoke test; uses local weights only, no data upload."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))
from PIL import Image, ImageDraw, ImageFont
from assistant.parsing import Parser


def main():
    image = Image.new('RGB', (1300, 300), 'white')
    font = ImageFont.truetype('C:/Windows/Fonts/simhei.ttf', 40)
    ImageDraw.Draw(image).multiline_text((30, 30), '题名：关于示例培训安排的通知\n日期：2026年11月07日\n责任者：示例办公室', font=font, fill='black', spacing=18)
    path = ROOT / 'evaluation' / 'fixtures' / 'sample_scan.png'
    image.save(path)
    result = {'fixture': 'synthetic rendered image, not a real archive scan'}
    try:
        docs = Parser().parse(path)
        from assistant.generation import suggest
        fields = [{'key': 'title', 'name': '题名'}, {'key': 'date', 'name': '日期'}, {'key': 'author', 'name': '责任者'}]
        result.update(status='success', text=docs[0].page_content, suggestions=suggest(docs, fields))
    except Exception as exc:
        result.update(status='unavailable', error=f'{type(exc).__name__}: {exc}')
    (ROOT / 'evaluation' / 'ocr_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(result['status'])


if __name__ == '__main__':
    main()
