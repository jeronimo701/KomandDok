"""Functional checks for the Python engine shared by the Android shell."""
import json
from pathlib import Path
import tempfile
from PIL import Image, ImageDraw
from pypdf import PdfReader
import mobile

def api(method, route, payload=None, uploads=None, observer=None):
    result=json.loads(mobile.dispatch(method,route,json.dumps(payload) if payload is not None else '',
                                      json.dumps(uploads or []),observer))
    assert result['ok'],result
    return result['data']

def check(root):
    root=Path(root)
    mobile.start(root/'test')
    card=api('GET','/api/defaults')
    card.update(city='Казань',name='Проверка Android',include_memo=True,
               report_date='2026-10-24',memo_date='2026-10-25',
               expenses=[{'category':'taxi','amount':'200+25,5'}])
    card['planned'].update(tickets='5000',daily='700*3')
    card=api('POST','/api/trips',card)
    assert card['totals']['issued']=='7100.00' and card['totals']['spent']=='2325.50'
    key=card['id'];route=f'/api/trips/{key}'
    png=root/'receipt.png'
    Image.new('RGB',(400,600),'white').save(png)
    uploaded=api('POST',route+'/upload',uploads=[{'staged':str(png),'name':'Чек.png'}])
    assert uploaded['files'][0]['name']=='Чек.png'
    generated=api('POST',route+'/generate',{'revision':1})
    assert len(generated['files'])==4
    report=api('POST',route+'/preview/report',{'revision':1})
    report_path=mobile.attachment(key,report['path'])
    extracted=PdfReader(report_path).pages[0].extract_text()
    assert 'АВАНСОВЫЙ ОТЧЕТ' in extracted and '2 325,50' in extracted
    class PackObserver:
        def __init__(self):
            self.percentages=[]

        def update(self, percent, message):
            assert message
            self.percentages.append(percent)
            if percent==100:
                assert list(Path(card['print_folder']).glob('Комплект_*.pdf'))

    observer=PackObserver()
    pack=api('POST',route+'/pack',{'revision':1,'files':[{'path':f['path'],'copies':2 if f['name'].startswith('02_') else 1} for f in generated['files']]},
             observer=observer)
    assert observer.percentages==[2,7,28,49,70,95,100],observer.percentages
    source=mobile.attachment(key,pack['path'])
    assert pack['pages']==5 and len(PdfReader(source).pages)==5
    mobile.print_ranges(source,str(root/'printed.pdf'),'[[1,2]]')
    assert len(PdfReader(root/'printed.pdf').pages)==2
    png=root/'signature.jpg'
    sign=Image.new('RGB',(550,340),'#e9e1cb')
    ImageDraw.Draw(sign).line([(15,100),(140,32),(70,120),(285,52),(182,108),(330,96)],fill='#204589',width=5)
    sign.save(png)
    updated=api('POST',route+'/signature',uploads=[{'staged':str(png),'name':'Подпись.jpg'}])
    assert updated['has_signature']
    assert updated['signature_thumbnail'].startswith('data:image/png;base64,')
    layout_args={'revision':updated['revision']}
    layout=api('POST',route+'/signature-layout/report',layout_args)
    assert layout['anchor']['page']==0 and layout['anchor']['width']>0
    placement={'dx':12,'dy':-4,'scale':1.4}
    api('PUT',route+'/signature-layout/report',{**layout_args,'previous':layout['placement'],'placement':placement})
    assert api('POST',route+'/signature-layout/report',layout_args)['placement']==placement
    signed=api('POST',route+'/preview/report',{'revision':updated['revision'],'signed':True})
    signed_page=PdfReader(mobile.attachment(key,signed['path'])).pages[0]
    assert '24.10.2026' in signed_page.extract_text() and len(signed_page.images)==1
    signed=api('POST',route+'/preview/memo',{'revision':updated['revision'],'signed':True})
    assert '25.10.2026' in PdfReader(mobile.attachment(key,signed['path'])).pages[0].extract_text()
    cleared=api('DELETE',route+'/signature')
    assert not cleared['has_signature']
    assert len(api('POST',route+'/generate',{'revision':cleared['revision']})['files'])==4
    api('DELETE',route,{'revision':cleared['revision']})
    restored=api('POST','/api/trash/'+key+'/restore',{})
    assert len(restored['files'])==4
    try: mobile.attachment(key,'../../Командировки/'+key+'.json')
    except ValueError: pass
    else: raise AssertionError('attachment outside its project accepted')
    return 'OK: estimates, receipts, Cyrillic PDFs, pack order and progress, print subset, signature picker bridge, dates and restore'

if __name__=='__main__':
    with tempfile.TemporaryDirectory() as temp:
        print(check(temp))
