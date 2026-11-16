import io
import re
from base64 import b64decode
from contextlib import closing
import tempfile
import threading
import time
import socket
import unittest
from unittest.mock import patch
from decimal import Decimal
from pathlib import Path
from PIL import Image, ImageDraw
from pypdf import PdfReader
from pypdfium2 import PdfDocument
from app import create_app
from domain import calculate, default_trip, normalize, totals

class MoneyTests(unittest.TestCase):
    def test_duck_animation_lifecycle(self):
        from tray_animation import TrayAnimator
        from types import SimpleNamespace
        icon=SimpleNamespace(visible=True,icon=None)
        animation=TrayAnimator(icon,Path(__file__).resolve().parents[1]/'static/app.gif')
        self.assertGreaterEqual(len(animation.frames),20)
        self.assertGreater(len({frame.tobytes() for frame in animation.frames}),10)
        animation.start()
        for _ in range(100):
            if animation.ticks>=2: break
            time.sleep(.01)
        animation.stop()
        self.assertGreaterEqual(animation.ticks,2)
        self.assertFalse(animation._thread.is_alive())

    def test_decimal_and_expressions(self):
        self.assertEqual(calculate('0,1+0,2'),Decimal('0.30'))
        self.assertEqual(calculate('800 × 5 + (227 + 502)'),Decimal('4729.00'))
        self.assertEqual(calculate('1/8'),Decimal('.13'))
        for expression in ['1/0','-1','2**10','1e9',"__import__('os')",'nan','9999999999','9'*180]:
            with self.subTest(expression=expression):
                with self.assertRaises(ValueError): calculate(expression)

    def test_refund_overrun(self):
        trip=default_trip(); trip['issued']='32000'
        trip['expenses']=[dict(category=k,amount=v) for k,v in [('tickets','2969+3359+5303'),('hotel','15000'),('daily','4000'),('taxi','227+502+707+808+245')]]
        result=totals(trip)
        self.assertEqual(result['spent'],'33120.00')
        self.assertEqual(result['overrun'],'1120.00')
        self.assertEqual(Decimal(result['refund']),0)
        trip['issued']='35000'
        self.assertEqual(totals(trip)['refund'],'1880.00')

class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.app=create_app(self.root/'data',self.root/'print')
        self.app.testing=True
        self.client=self.app.test_client()
        html=self.client.get('/').get_data(as_text=True)
        self.token=re.search(r'window.TRIP_TOKEN="([^"]+)"',html)[1]
        self.headers={'X-Trip-Token':self.token}
        self.data=default_trip(); self.data['city']='Воронеж'
        self.data['issued_from_plan']=False; self.data['daily_from_plan']=False
        self.data['start']='2026-10-19';self.data['end']='2026-10-23'
        self.data['issued']='32000'
        self.data['planned'].update(tickets='6500',daily='4000',taxi='6500')
        self.data['memo_amount']='1859'
        self.data['include_memo']=True;self.data['include_details']=True
        self.data['expenses']=[dict(category=k,amount=v,quick=True) for k,v in [('tickets','11631'),('hotel','15000'),('daily','4000'),('taxi','2489')]]

    def tearDown(self): self.tmp.cleanup()

    def post(self,path,data):
        response=self.client.post(path,json=data,headers=self.headers)
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        return response.json

    def test_full_workflow(self):
        trip=self.post('/api/trips',self.data); key=trip['id']
        self.assertEqual(trip['totals']['overrun'],'1120.00')
        generated=self.post(f'/api/trips/{key}/generate',{'revision':trip['revision']})
        self.assertEqual(len(generated['files']),4)
        report=Path(generated['print_folder'])/'Документы/02_Авансовый_отчет.pdf'
        reader=PdfReader(report)
        self.assertEqual(len(reader.pages),1)
        text=reader.pages[0].extract_text()
        self.assertIn('33 120,00',text); self.assertIn('1 120,00',text)
        image=io.BytesIO();Image.new('RGB',(700,1100),'white').save(image,format='PNG');image.seek(0)
        upload=self.client.post(f'/api/trips/{key}/upload',headers=self.headers,data={'files':(image,'чек.png')},content_type='multipart/form-data')
        self.assertEqual(upload.status_code,200)
        files=upload.json['files']
        pack=self.post(f'/api/trips/{key}/pack',dict(revision=1,files=[dict(path=f['path'],copies=2 if '02_Авансовый' in f['name'] else 1) for f in files]))
        self.assertEqual(pack['pages'],6)
        self.assertEqual(len(PdfReader(Path(trip['print_folder'])/pack['path']).pages),6)
        for path in [report,Path(trip['print_folder'])/pack['path']]:
            self.assertGreater(path.stat().st_size,1000)

    def test_signed_variants_dates_and_form_first_pack(self):
        self.data.update(document_date='2026-10-18',report_date='2026-10-24',memo_date='2026-10-25',
                         employee='Иванов И.И.',employee_genitive='Иванова И.И.',employee_dative='Иванову И.И.')
        trip=self.post('/api/trips',self.data)
        api='/api/trips/'+trip['id']
        folder=Path(trip['print_folder'])
        image=Image.new('RGBA',(350,140))
        ImageDraw.Draw(image).line([(15,100),(140,32),(70,120),(285,52),(182,108),(330,96)],fill='#204589',width=5)
        signature=io.BytesIO()
        image.save(signature,format='PNG'); signature.seek(0)
        uploaded=self.client.post(api+'/signature',headers=self.headers,data={'files':(signature,'sign.png')})
        self.assertEqual(uploaded.status_code,200,uploaded.get_data(as_text=True))
        self.assertTrue(uploaded.json['has_signature'])
        revision=uploaded.json['revision']
        self.assertEqual(self.client.get(api+'/file?path=.signature.png').status_code,400)
        plain=self.post(api+'/preview/report',{'revision':revision})
        signed=self.post(api+'/preview/report',{'revision':revision,'signed':True})
        self.assertNotEqual(plain['path'],signed['path'])
        self.assertFalse(PdfReader(folder/plain['path']).pages[0].images)
        self.assertEqual(len(PdfReader(folder/signed['path']).pages[0].images),1)
        # Upload receipts first, and submit them first to the pack API too.
        for name,color in [('A.png','red'),('B.png','blue')]:
            receipt=io.BytesIO()
            Image.new('RGB',(20,20),color).save(receipt,format='PNG'); receipt.seek(0)
            self.assertEqual(self.client.post(api+'/upload',headers=self.headers,data={'files':(receipt,name)}).status_code,200)
        items=self.post(api+'/generate',{'revision':revision})['files']
        by_name={item['name']:item for item in items}
        chosen=[by_name['B.png'],next(f for f in items if f['signed'] and f['kind']=='memo'),
                by_name['A.png'],next(f for f in items if f['signed'] and f['kind']=='report'),
                next(f for f in items if f['kind']=='request' and not f['signed'])]
        result=self.post(api+'/pack',{'revision':revision,'files':chosen})
        pages=PdfReader(folder/result['path']).pages
        self.assertEqual(len(pages),5)
        self.assertIn('25.10.2026',pages[0].extract_text())
        self.assertIn('24.10.2026',pages[1].extract_text())
        self.assertIn('18.10.2026',pages[2].extract_text())
        self.assertEqual(pages[3].images[0].image.getpixel((0,0)),(0,0,255))
        self.assertEqual(pages[4].images[0].image.getpixel((0,0)),(255,0,0))
        removed=self.client.delete(api+'/signature',headers=self.headers)
        self.assertFalse(removed.json['has_signature'])
        self.assertFalse((folder/signed['path']).exists())
        self.assertTrue((folder/result['path']).exists())
        self.assertEqual(self.client.post(api+'/preview/report',headers=self.headers,
            json={'revision':removed.json['revision'],'signed':True}).status_code,400)

    def test_signature_photo_loses_paper_and_keeps_ink(self):
        trip=self.post('/api/trips',self.data)
        route='/api/trips/'+trip['id']+'/signature'
        photo=Image.new('RGB',(720,480))
        paper=ImageDraw.Draw(photo)
        for row in range(photo.height):
            shade=220-row//12
            paper.line((0,row,719,row),fill=(shade+6,shade,shade-13))
        paper.line([(190,298),(350,172),(283,314),(530,209)],fill=(30,57,124),width=7)
        paper.point((80,70),fill=(40,40,40))
        def upload(image):
            source=io.BytesIO()
            image.save(source,format='JPEG',quality=88); source.seek(0)
            return self.client.post(route,headers=self.headers,data={'files':(source,'photo.jpg')})

        response=upload(photo)
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        with Image.open(Path(trip['print_folder'])/'.signature.png') as clean:
            self.assertLess(clean.width,370)
            self.assertLess(clean.height,170)
            self.assertEqual(clean.getchannel('A').getextrema(),(0,255))
            self.assertEqual(clean.getpixel((0,0))[3],0)
            self.assertGreater(clean.getpixel((30,30))[2],clean.getpixel((30,30))[0]+40)
            self.assertLess(sum(clean.getchannel('A').histogram()[1:]),clean.width*clean.height//8)
        thumbnail=b64decode(response.json['signature_thumbnail'].split(',',1)[1])
        with Image.open(io.BytesIO(thumbnail)) as preview:
            self.assertLessEqual(preview.width,300)
            self.assertEqual(preview.mode,'RGBA')
        invalid=upload(Image.new('RGB',(720,480),'#e9e1cb'))
        self.assertEqual(invalid.status_code,400)
        stored=self.client.get(route.removesuffix('/signature')).json
        self.assertEqual(stored['revision'],response.json['revision'])
        self.assertEqual(stored['signature_thumbnail'],response.json['signature_thumbnail'])

    def test_signature_placement_is_per_form_and_applies_to_future_trips(self):
        def add_trip():
            trip=self.post('/api/trips',self.data)
            route='/api/trips/'+trip['id']
            image=Image.new('RGBA',(80,40),(8,48,210,255))
            image.putpixel((0,0),(0,0,0,0))
            source=io.BytesIO()
            image.save(source,format='PNG'); source.seek(0)
            uploaded=self.client.post(route+'/signature',headers=self.headers,data={'files':(source,'ink.png')})
            self.assertEqual(uploaded.status_code,200)
            return route,uploaded.json

        route,first=add_trip()
        args={'revision':first['revision']}
        generated=self.post(route+'/generate',args)
        self.assertEqual(generated['generated_revision'],first['revision'])
        layout=self.post(route+'/signature-layout/memo',args)
        anchor=layout['anchor']
        self.assertFalse(PdfReader(Path(first['print_folder'])/layout['path']).pages[anchor['page']].images)
        placement={'dx':37,'dy':-19,'scale':1.6}
        changed=self.client.put(route+'/signature-layout/memo',headers=self.headers,
            json={**args,'placement':placement,'previous':layout['placement']})
        self.assertEqual(changed.status_code,200,changed.get_data(as_text=True))
        self.assertNotIn('generated_revision',changed.json)
        self.assertEqual(self.post(route+'/signature-layout/report',args)['placement']['scale'],1)

        self.data['memo_text']='Текст служебной записки\n'*12
        new_route,second=add_trip()
        new_layout=self.post(new_route+'/signature-layout/memo',{'revision':second['revision']})
        self.assertEqual(new_layout['placement'],placement)
        new_anchor=new_layout['anchor']
        self.assertNotEqual((new_anchor['page'],new_anchor['y']),(anchor['page'],anchor['y']))
        generated=self.post(new_route+'/generate',{'revision':second['revision']})
        relative=next(f['path'] for f in generated['files'] if f['signed'] and f['kind']=='memo')
        with PdfDocument(Path(second['print_folder'])/relative) as pdf:
            with closing(pdf[new_anchor['page']]) as page:
                with closing(page.render(scale=1)) as bitmap:
                    image=bitmap.to_pil().convert('RGB')
        blue=[(index%image.width,index//image.width) for index,(r,g,b) in enumerate(image.getdata())
              if r<50 and g<100 and b>175]
        left,right=min(x for x,y in blue),max(x for x,y in blue)
        top,bottom=min(y for x,y in blue),max(y for x,y in blue)
        self.assertAlmostEqual((left+right)/2,new_anchor['x']+placement['dx'],delta=1.5)
        self.assertAlmostEqual((top+bottom)/2,new_anchor['y']+placement['dy'],delta=1.5)
        self.assertAlmostEqual(right-left,new_anchor['width']*placement['scale']*(80/88),delta=2)

    def test_validation_security_and_stale(self):
        self.assertEqual(self.client.post('/api/trips',json=self.data).status_code,403)
        self.assertEqual(self.client.post('/api/trips',json=self.data,headers={**self.headers,'Origin':'https://evil.test'}).status_code,403)
        trip=self.post('/api/trips',self.data);key=trip['id']
        self.post(f'/api/trips/{key}/generate',{'revision':1})
        revised=self.client.put(f'/api/trips/{key}',json={**self.data,'revision':1,'city':'Казань'},headers=self.headers)
        self.assertEqual(revised.status_code,200)
        self.assertEqual(revised.json['files'],[])
        stale=self.client.post(f'/api/trips/{key}/pack',json={'revision':2,'files':[{'path':'Документы/02_Авансовый_отчет.pdf'}]},headers=self.headers)
        self.assertEqual(stale.status_code,400)
        self.assertEqual(self.client.get(f'/api/trips/{key}/file?path=../../outside').status_code,400)
        conflict=self.client.put(f'/api/trips/{key}',json={**self.data,'revision':1},headers=self.headers)
        self.assertEqual(conflict.status_code,400)
        with self.assertRaises(ValueError): normalize({**self.data,'end':'2026-01-01'})

    def test_quick_calculator_and_bad_input(self):
        result=self.post('/api/estimate',self.data)
        self.assertEqual(result['totals']['spent'],'33120.00')
        self.assertEqual(result['errors'],{})
        self.data['expenses'][0]['amount']='1/0'
        result=self.post('/api/estimate',self.data)
        self.assertIn('expense_0',result['errors'])
        self.assertEqual(self.client.post('/api/trips',json=self.data,headers=self.headers).status_code,400)

    def test_attachment_collision_and_bad_pdf(self):
        trip=self.post('/api/trips',self.data);key=trip['id']
        for payload in (b'first',b'second'):
            response=self.client.post(f'/api/trips/{key}/upload',headers=self.headers,data={'files':(io.BytesIO(payload),'чек.pdf')})
            self.assertEqual(response.status_code,200)
        names={f['name'] for f in response.json['files']}
        self.assertEqual(names,{'чек.pdf','чек (2).pdf'})
        broken=self.client.post(f'/api/trips/{key}/pack',headers=self.headers,json={'revision':1,'files':[{'path':'Чеки/чек.pdf','copies':1}]})
        self.assertEqual(broken.status_code,400)
        self.assertIn('чек.pdf',broken.json['error'])
        self.assertFalse(list(Path(trip['print_folder']).glob('Комплект_*')))

    def test_plan_defaults_and_manual_override(self):
        self.data.update(issued_from_plan=True,daily_from_plan=True)
        self.data['planned']['daily']='900*5'
        trip=self.post('/api/trips',self.data)
        self.assertEqual(trip['issued'],'17500.00')
        self.assertEqual(trip['totals']['categories']['daily'],'4500.00')
        result=self.post('/api/estimate',self.data)
        self.assertEqual(result['totals']['issued'],'17500.00')
        revised={**trip,'issued_from_plan':False,'daily_from_plan':False,'issued':'20000'}
        revised['expenses'][2]['amount']='5000'
        response=self.client.put('/api/trips/'+trip['id'],json=revised,headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['issued'],'20000')
        self.assertEqual(response.json['totals']['categories']['daily'],'5000.00')

    def test_history_preview_and_folder(self):
        self.data['purpose']='выезда на объект клиента'
        trip=self.post('/api/trips',self.data);key=trip['id']
        for kind in ('request','report','memo'):
            preview=self.post(f'/api/trips/{key}/preview/{kind}',{'revision':1})
            path=Path(trip['print_folder'])/preview['path']
            self.assertEqual(len(PdfReader(path).pages),1)
            view=self.client.get(f'/api/trips/{key}/preview-view',query_string={'path':preview['path']})
            self.assertEqual(view.status_code,200)
            image=self.client.get(f'/api/trips/{key}/preview-page',query_string={'path':preview['path'],'page':0})
            self.assertEqual(image.status_code,200)
            self.assertTrue(image.data.startswith(b'\x89PNG'))
        self.assertEqual(self.client.get('/api/trips/'+key).json['files'],[])
        revised=self.client.put('/api/trips/'+key,json={**trip,'city':'Казань','purpose':'проверки оборудования'},headers=self.headers)
        self.assertEqual(revised.status_code,200)
        suggestions=self.client.get('/api/suggestions').json
        self.assertEqual(set(suggestions['cities']),{'Воронеж','Казань'})
        self.assertIn('выезда на объект клиента',suggestions['purposes'])
        self.assertIn('проверки оборудования',suggestions['purposes'])
        self.assertEqual(len(self.client.get('/api/trips').json),1)
        with patch('app.subprocess.Popen') as popen:
            result=self.post(f'/api/trips/{key}/folder',{})
            self.assertTrue(result['opened'])
            self.assertEqual(Path(popen.call_args.args[0][-1]),Path(trip['print_folder']))

    def test_server_stop_releases_port(self):
        from runtime import serve
        port=None
        for candidate in range(20970,21070):
            with socket.socket() as probe:
                try: probe.bind(('127.0.0.1',candidate));port=candidate;break
                except OSError: continue
        self.assertIsNotNone(port)
        thread=threading.Thread(target=serve,args=(self.app,port),kwargs={'open_browser':False,'tray':False})
        thread.start()
        for _ in range(100):
            if self.app.config.get('STOP_SERVER'): break
            time.sleep(.01)
        self.assertTrue(self.app.config.get('STOP_SERVER'))
        self.assertEqual(self.client.post('/api/shutdown',headers=self.headers).status_code,200)
        thread.join(3)
        self.assertFalse(thread.is_alive())
        with socket.socket() as probe: probe.bind(('127.0.0.1',port))

    def test_lifecycle_notifies_open_tabs(self):
        response=self.client.get('/api/lifecycle',buffered=False)
        stream=iter(response.response)
        self.assertIn(b'"running"',next(stream))
        self.app.config['CLOSE_SOURCE']='tray'
        self.app.config['CLOSED_EVENT'].set()
        message=next(stream)
        self.assertIn(b'"closed"',message)
        self.assertIn(b'"tray"',message)
        response.close()

    def test_project_rename_copy_trash_restore(self):
        trip=self.post('/api/trips',self.data);key=trip['id']
        generated=self.post(f'/api/trips/{key}/generate',{'revision':1})
        folder=Path(trip['print_folder'])
        receipt=folder/'Чеки/проверка.txt';receipt.write_text('receipt',encoding='utf-8')
        renamed=self.post(f'/api/trips/{key}/rename',{'name':'Клиент — Казань','revision':1})
        self.assertEqual(renamed['name'],'Клиент — Казань')
        self.assertEqual(renamed['city'],'Воронеж')
        self.assertEqual(renamed['folder'],trip['folder'])
        self.assertEqual(renamed['revision'],renamed['generated_revision'])
        self.assertEqual(len(renamed['files']),5)
        copy=self.post(f'/api/trips/{key}/copy',{})
        self.assertNotEqual(copy['id'],key)
        self.assertEqual(copy['name'],'Клиент — Казань — копия')
        self.assertEqual(copy['expenses'],renamed['expenses'])
        self.assertEqual(copy['files'],[])
        stale=self.client.delete('/api/trips/'+key,json={'revision':1},headers=self.headers)
        self.assertEqual(stale.status_code,400)
        deleted=self.client.delete('/api/trips/'+key,json={'revision':renamed['revision']},headers=self.headers)
        self.assertEqual(deleted.status_code,200)
        self.assertFalse(folder.exists())
        self.assertEqual(self.client.get('/api/trips/'+key).status_code,400)
        trash=self.client.get('/api/trash').json
        self.assertEqual([t['id'] for t in trash],[key])
        restored=self.post('/api/trash/'+key+'/restore',{})
        self.assertEqual(restored['name'],'Клиент — Казань')
        self.assertEqual(receipt.read_text(encoding='utf-8'),'receipt')
        self.assertEqual(restored['revision'],restored['generated_revision'])
        self.assertEqual(self.client.get('/api/trash').json,[])
        self.assertEqual(len(self.client.get('/api/trips').json),2)

if __name__=='__main__': unittest.main()
