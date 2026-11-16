"""Extract pen strokes from a photo of a signature on paper."""
from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat


def remove_specks(mask):
    """Drop tiny isolated marks, keeping connected strokes and their soft edges."""
    width, height = mask.size
    values = mask.tobytes()
    visited = bytearray(len(values))
    cleaned = bytearray(len(values))
    min_area = max(12, len(values) // 75_000)
    for start, value in enumerate(values):
        if not value or visited[start]:
            continue
        visited[start] = 1
        component = [start]
        for index in component:
            row, col = divmod(index, width)
            for y in range(max(0, row-1), min(height, row+2)):
                for x in range(max(0, col-1), min(width, col+2)):
                    neighbor = y*width+x
                    if values[neighbor] and not visited[neighbor]:
                        visited[neighbor] = 1
                        component.append(neighbor)
        if len(component) >= min_area and sum(values[index] >= 120 for index in component) >= 4:
            for index in component:
                cleaned[index] = values[index]
    return Image.frombytes('L', mask.size, bytes(cleaned))


def extract_ink(photo):
    """Estimate local paper brightness to account for lighting and paper tint."""
    photo.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(photo)
    paper = gray.copy()
    paper.thumbnail((320, 320), Image.Resampling.BOX)
    paper = paper.filter(ImageFilter.MaxFilter(13)).filter(ImageFilter.MinFilter(13))
    paper = paper.filter(ImageFilter.GaussianBlur(3)).resize(gray.size, Image.Resampling.BILINEAR)
    contrast = ImageChops.subtract(paper, gray)
    alpha = remove_specks(contrast.point(lambda value: min(255, max(0, (value-15)*5))))
    peak = alpha.getextrema()[1]
    if peak < 100:
        raise ValueError('Не удалось выделить подпись. Сфотографируйте её крупнее на светлой бумаге.')
    core = alpha.point(lambda value: 255 if value >= peak*.85 else 0)
    ink = tuple(ImageStat.Stat(photo, mask=core).median)
    result = Image.new('RGBA', photo.size, ink)
    result.putalpha(alpha)
    return result


def save_signature(source, destination):
    try:
        with Image.open(source) as image:
            if image.format not in ('PNG', 'JPEG') or image.width * image.height > 24_000_000:
                raise ValueError('Выберите PNG или JPEG размером не больше 24 мегапикселей.')
            normalized = ImageOps.exif_transpose(image).convert('RGBA')
            if normalized.getchannel('A').getextrema()[0] == 255:
                normalized = extract_ink(normalized.convert('RGB'))
            bounds = normalized.getchannel('A').getbbox()
            if not bounds:
                raise ValueError('Изображение подписи пустое.')
            normalized = ImageOps.expand(normalized.crop(bounds), border=4)
            normalized.thumbnail((1000, 400), Image.Resampling.LANCZOS)
            normalized.save(destination, format='PNG')
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Не удалось прочитать изображение подписи.') from exc
