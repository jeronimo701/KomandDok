"""Independent A4 print forms based on the user's examples."""
from io import BytesIO
from pathlib import Path
import os
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape
from PIL import Image, ImageOps, ImageSequence
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Flowable, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from pypdf import PdfReader, PdfWriter
from domain import CATEGORIES, totals, calculate, money

def register_fonts():
    if 'TripTimes' in pdfmetrics.getRegisteredFontNames(): return
    roots = [Path(__file__).parent/'fonts', Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts', Path('/usr/share/fonts/truetype/dejavu')]
    for root in roots:
        for normal, bold in [('times.ttf','timesbd.ttf'), ('DejaVuSerif.ttf','DejaVuSerif-Bold.ttf'), ('LiberationSans-Regular.ttf','LiberationSans-Bold.ttf')]:
            if (root/normal).exists() and (root/bold).exists():
                pdfmetrics.registerFont(TTFont('TripTimes', str(root/normal)))
                pdfmetrics.registerFont(TTFont('TripTimesBold', str(root/bold)))
                pdfmetrics.registerFontFamily('TripTimes', normal='TripTimes', bold='TripTimesBold', italic='TripTimes', boldItalic='TripTimesBold')
                return
    raise ValueError('Не найден шрифт с кириллицей. Нужен Times New Roman в Windows или DejaVu Serif в папке fonts.')

def ru_date(value):
    d = date.fromisoformat(value)
    months = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря']
    return f'{d.day} {months[d.month-1]} {d.year} года'

def short_date(value):
    return date.fromisoformat(value).strftime('%d.%m.%Y') if value else ''

def p(value, size=12, align=0, bold=False):
    return Paragraph(escape(str(value)).replace('\n', '<br/>'), ParagraphStyle('text', fontName='TripTimesBold' if bold else 'TripTimes', fontSize=size, leading=size*1.3, alignment=align, spaceAfter=3*mm))

DEFAULT_PLACEMENT = {'dx':0, 'dy':0, 'scale':1}

class SignatureMark(Flowable):
    """Reserve a fixed slot in the form and draw the signature relative to its centre."""
    def __init__(self, path, placement, editing):
        super().__init__()
        self.width, self.height = 28*mm, 12*mm
        self.hAlign = 'CENTER'
        self.image = ImageReader(str(path))
        width, height = self.image.getSize()
        fit = min(self.width/width, self.height/height)
        self.base_width, self.base_height = width*fit, height*fit
        self.placement, self.editing = placement, editing
        self.anchor = None

    def draw(self):
        canvas = self.canv
        slot_x, slot_y = self.width/2, self.height/2
        x, y = canvas.absolutePosition(slot_x, slot_y)
        page_width, page_height = A4
        y = page_height-y
        self.anchor = dict(x=x,y=y,width=self.base_width,height=self.base_height,
                           page=canvas.getPageNumber()-1,pageWidth=page_width,pageHeight=page_height)
        if self.editing:
            return
        width = self.base_width*self.placement['scale']
        height = self.base_height*self.placement['scale']
        center_x = min(page_width-width/2,max(width/2,x+self.placement['dx']))
        center_y = min(page_height-height/2,max(height/2,y+self.placement['dy']))
        canvas.drawImage(self.image,slot_x+center_x-x-width/2,slot_y+y-center_y-height/2,
                         width=width,height=height,mask='auto')

def form(path, trip, kind, signature_path=None, placement=None, editing=False):
    register_fonts()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=25*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm, title={'request':'Заявка на командировку','memo':'Служебная записка','report':'Авансовый отчет','details':'Расшифровка расходов'}[kind], author=trip['employee'])
    width = A4[0]-45*mm
    document_date = trip.get(kind+'_date') or trip['document_date']
    mark = SignatureMark(signature_path,placement or DEFAULT_PLACEMENT,editing) if signature_path else None
    flow = []
    if kind in ('request','memo'):
        recipient = '\n'.join([trip['recipient_title'],trip['organization'],trip['recipient'],f"от {trip['role']}",trip['employee_genitive']])
        header = Table([['', p(recipient, 14)]], colWidths=[width*.54,width*.46])
        header.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
        flow += [header, Spacer(1,14*mm), p('СЛУЖЕБНАЯ ЗАПИСКА',14,TA_CENTER,True)]
        if kind == 'request':
            flow += [p('о направлении в служебную командировку',14,TA_CENTER),Spacer(1,7*mm)]
            body = (f"Прошу выплатить на зарплатную карту денежные средства сотруднику {trip['employee_dative']}, "
                f"направляемому в служебную командировку в г. {trip['city']} с {ru_date(trip['start'])} по {ru_date(trip['end'])} "
                f"для {trip['purpose']}.")
            flow += [p(body,14,TA_JUSTIFY),Spacer(1,5*mm)]
            rows = [[p(CATEGORIES[k],14),p(money(calculate(trip['planned'][k]))+' руб.',14,TA_RIGHT)] for k in CATEGORIES if k != 'other' or calculate(trip['planned'][k])]
            rows.append([p('Итого',14,bold=True),p(money(totals(trip)['planned'])+' руб.',14,TA_RIGHT,True)])
            table = Table(rows,colWidths=[width*.65,width*.35])
            table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEABOVE',(0,-1),(-1,-1),.6,colors.black),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
            flow += [table]
        else:
            body = trip['memo_text'] or (f"Прошу выплатить на зарплатную карту денежные средства в размере {money(calculate(trip['memo_amount']))} руб. "
                f"сотруднику {trip['employee_dative']} для {trip['memo_purpose']}.")
            flow += [Spacer(1,8*mm),p(body,14,TA_JUSTIFY)]
        if mark:
            signature = Table([[p(short_date(document_date)+' г.'), '', mark, p(trip['employee'],align=TA_RIGHT)]],
                colWidths=[width*.30,width*.18,width*.20,width*.32],
                style=[('VALIGN',(0,0),(-1,-1),'MIDDLE')])
        else:
            signature = Table([[p(short_date(document_date)+' г.'),p('____________  '+trip['employee'],12,TA_RIGHT)]],colWidths=[width*.33,width*.67])
        flow += [Spacer(1,16*mm),signature]
    elif kind == 'report':
        t = totals(trip)
        signed_by = (Table([[p(short_date(document_date)), mark]], colWidths=[28*mm,32*mm],
            style=[('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),0)])
            if mark else p(short_date(document_date)+'   ______________'))
        flow += [p('АВАНСОВЫЙ ОТЧЕТ',16,TA_CENTER,True),p(trip['organization'],12,TA_CENTER),
            p(f"Командировка: {trip['city']}",14,TA_CENTER),p(f"с {short_date(trip['start'])} по {short_date(trip['end'])}",12,TA_CENTER),Spacer(1,5*mm)]
        data = [
            [p('Подотчетное лицо'),p(trip['employee']), ''],
            [p('Дата и номер РКС'),p(trip['rks']), ''],
            [p('Выданная сумма'),'',p(money(t['issued']),align=TA_RIGHT)],
            [p('Сколько потрачено'),'',p(money(t['spent']),align=TA_RIGHT,bold=True)],
            [p('Дата и номер ВОВ'),p(trip['vov']), ''],
            [p('На что и где потрачено, кому переданы деньги, кому переданы материальные ценности'),p('Суточные'),p(money(t['categories']['daily']),align=TA_RIGHT)],
            ['',p('Проживание'),p(money(t['categories']['hotel']),align=TA_RIGHT)],
            ['',p('Транспортные и прочие расходы (билеты, услуги такси, автобус и другие расходы)'),p(money(sum((Decimal(t['categories'][k]) for k in ('tickets','taxi','other')),Decimal(0))),align=TA_RIGHT)],
            [p('Дата и номер ПКС'),p(trip['pks']), ''],
            ['',p('К возврату'),p(money(t['refund']),align=TA_RIGHT)],
            ['',p('Перерасход к возмещению'),p(money(t['overrun']),align=TA_RIGHT)],
            [p('Дата и подпись подотчетного лица'),signed_by, ''],
            [p('Дата и подпись руководителя'),p('________________________'), ''],
        ]
        table = Table(data,colWidths=[width*.43,width*.36,width*.21])
        table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.6,colors.black),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('SPAN',(1,0),(2,0)),('SPAN',(1,1),(2,1)),('SPAN',(1,4),(2,4)),('SPAN',(0,5),(0,7)),
            ('SPAN',(1,8),(2,8)),('SPAN',(1,11),(2,11)),('SPAN',(1,12),(2,12)),
            ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        flow += [table,p('Все суммы указаны в рублях.',10)]
    else:
        flow += [p('РАСШИФРОВКА РАСХОДОВ',15,TA_CENTER,True),p(f"{trip['employee']} • {trip['city']} • {short_date(trip['start'])} - {short_date(trip['end'])}",11),Spacer(1,4*mm)]
        rows = [[p('Дата',10,bold=True),p('Вид и описание расхода',10,bold=True),p('Чек / документ',10,bold=True),p('Сумма, руб.',10,bold=True)]]
        for row in trip['expenses']:
            rows.append([p(short_date(row['date']),10),p(CATEGORIES[row['category']]+'\n'+row['description'],10),p(row['receipt'],10),p(money(calculate(row['amount'])),10,TA_RIGHT)])
        rows.append(['',p('Итого',11,bold=True),'',p(money(totals(trip)['spent']),11,TA_RIGHT,True)])
        table=Table(rows,colWidths=[width*.15,width*.44,width*.23,width*.18],repeatRows=1)
        table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.black),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        flow.append(table)
    doc.build(flow)
    return mark.anchor if mark else None

def image_pdf(path):
    """Place each original image/frame on A4; preserve aspect ratio and orientation."""
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    out=BytesIO()
    canvas=Canvas(out,pagesize=A4)
    with Image.open(path) as original:
        for frame in ImageSequence.Iterator(original):
            im=ImageOps.exif_transpose(frame.copy()).convert('RGBA')
            white=Image.new('RGB',im.size,'white'); white.paste(im,mask=im.getchannel('A'))
            w,h=A4; ratio=min((w-20*mm)/white.width,(h-20*mm)/white.height)
            iw,ih=white.width*ratio,white.height*ratio
            canvas.drawImage(ImageReader(white),(w-iw)/2,(h-ih)/2,width=iw,height=ih)
            canvas.showPage()
    canvas.save(); out.seek(0)
    return out

def combine(entries, destination):
    writer=PdfWriter()
    for path,copies in entries:
        try:
            reader=PdfReader(str(path) if path.suffix.lower()=='.pdf' else image_pdf(path))
            if reader.is_encrypted and not reader.decrypt(''):
                raise ValueError('PDF защищен паролем')
            if not reader.pages: raise ValueError('В документе нет страниц')
            for _ in range(copies):
                for page in reader.pages: writer.add_page(page)
        except Exception as exc:
            raise ValueError(f'Не удалось добавить «{path.name}»: {exc}') from exc
    if not writer.pages: raise ValueError('Выберите хотя бы один документ или чек для печати.')
    writer.write(str(destination))
    return len(writer.pages)
