"""Text payloads shared by the MP4 renderer and optional editor exporter."""


def text_items(item):
    if item.get('text'):
        return [(item.get('language', 'zh'), item['text'])]
    return [(lang, item[lang]) for lang in ('zh', 'en', 'es') if item.get(lang)]
