'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const categories={tickets:'Проезд / билеты',hotel:'Отель / проживание',daily:'Суточные',taxi:'Такси',other:'Всякое / прочее'};
let current=null,dirty=false,tripList=[],fileRows=[],estimateTimer,estimateSequence=0,busy=false,serverClosed=false;
const form=$('#form');
function setSidebarCollapsed(collapsed){
    $('.layout').classList.toggle('sidebar-collapsed',collapsed);
    const toggle=$('#sidebar-toggle'),label=collapsed?'Развернуть меню':'Свернуть меню';
    toggle.textContent=collapsed?'›':'‹';toggle.title=label;
    toggle.setAttribute('aria-label',label);toggle.setAttribute('aria-expanded',String(!collapsed));
    try{localStorage.setItem('J701.sidebarCollapsed',String(collapsed));}catch{}
}
let savedSidebar=true;
try{savedSidebar=localStorage.getItem('J701.sidebarCollapsed')!=='false';}catch{}
setSidebarCollapsed(savedSidebar);
$('#sidebar-toggle').onclick=()=>setSidebarCollapsed(!$('.layout').classList.contains('sidebar-collapsed'));
const fmt=v=>new Intl.NumberFormat('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(v))+' ₽';
function el(tag,props={},content){const e=document.createElement(tag);for(const [k,v]of Object.entries(props)){if(k==='class')e.className=v;else if(k==='text')e.textContent=v;else e.setAttribute(k,v)}if(content)e.append(...content);return e}
function notice(text,error=false){const node=$('#message');node.textContent=text;node.classList.toggle('error',error);node.hidden=false;if(error)node.scrollIntoView({behavior:'smooth',block:'nearest'})}
function hidePack(){const n=$('#pack-result');n.hidden=true;n.replaceChildren()}
async function api(path,options={}){return androidRequest(path,options);}
async function action(fn){if(busy||serverClosed)return;busy=true;$('#busy').hidden=false;$('#message').hidden=true;try{await fn()}catch(error){if(!serverClosed)notice(error.message,true)}finally{busy=false;$('#busy').hidden=true}}
function markDirty(){dirty=true;$('#save-state').textContent='Есть изменения';hidePack();scheduleEstimate()}
function setTitle(){const city=form.elements.city.value.trim();$('#title').textContent=current?.name||city||'Новая командировка';$('#subtitle').textContent=current?'Карточка командировки · данные для всех документов':'Заполните данные один раз для всех документов.'}
function optionList(selected){return Object.entries(categories).map(([key,name])=>{const o=el('option',{value:key,text:name});o.selected=key===selected;return o})}
function drawExpense(row={}){const tr=el('tr');const fields=[['date','input',{type:'date',value:row.date||form.elements.start.value}],['category','select',{}],['description','input',{placeholder:'Например, автобус',value:row.description||''}],['amount','input',{placeholder:'0 или 300 + 250',value:row.amount||''}],['receipt','input',{placeholder:'Чек № / имя файла',value:row.receipt||''}]];for(const[key,tag,props]of fields){const td=el('td'),input=el(tag,{'data-field':key,...props});if(tag==='select')input.append(...optionList(row.category||'other'));td.append(input);if(key==='amount')td.append(el('div',{class:'row-result',text:'0,00 ₽'}));tr.append(td)}const td=el('td'),remove=el('button',{type:'button',class:'remove',title:'Убрать расход',text:'×'});remove.onclick=()=>{tr.remove();updateEmpty();markDirty()};td.append(remove);tr.append(td);$('#expense-rows').append(tr);updateEmpty();return tr}
function updateEmpty(){$('#expense-empty').hidden=$$('#expense-rows tr').length>0}
function getData(){const data={};for(const field of form.elements){if(!field.name)continue;data[field.name]=field.type==='checkbox'?field.checked:field.value}data.planned={};for(const key of Object.keys(categories))data.planned[key]=$(`[data-planned="${key}"]`).value;data.expenses=[];for(const key of Object.keys(categories)){data.expenses.push({category:key,amount:$(`[data-quick="${key}"]`).value,date:'',description:'Общая сумма по категории',receipt:'',quick:true})}for(const row of $$('#expense-rows tr')){const entry={quick:false};for(const field of row.querySelectorAll('[data-field]'))entry[field.dataset.field]=field.value;data.expenses.push(entry)}if(current){data.revision=current.revision;data.id=current.id;data.name=current.name||''}return data}
function scheduleEstimate(){clearTimeout(estimateTimer);estimateTimer=setTimeout(estimate,250)}
async function estimate(){clearTimeout(estimateTimer);const seq=++estimateSequence;try{const data=getData(),result=await api('/api/estimate',{method:'POST',body:data});if(seq!==estimateSequence)return;if(form.elements.issued_from_plan.checked)form.elements.issued.value=result.values.issued;if(form.elements.daily_from_plan.checked)$('[data-quick="daily"]').value=data.planned.daily;updateAutoFields();const invalid=Object.keys(result.errors).length>0;for(const key of ['spent','refund','overrun'])$('#'+key).textContent=invalid?'—':fmt(result.totals[key]);$('#planned-total').textContent=Object.keys(result.errors).some(k=>k.startsWith('planned_'))?'Проверьте суммы':fmt(result.totals.planned);$$('.invalid').forEach(e=>{e.classList.remove('invalid');e.removeAttribute('title')});for(const[key,message]of Object.entries(result.errors)){let field;if(key.startsWith('planned_'))field=$(`[data-planned="${key.slice(8)}"]`);else if(key.startsWith('expense_')){const i=Number(key.slice(8));field=i<5?$(`[data-quick="${Object.keys(categories)[i]}"]`):$$('#expense-rows tr')[i-5]?.querySelector('[data-field="amount"]')}else field=form.elements[key];if(field){field.classList.add('invalid');field.title=message}}for(const[key,index]of Object.keys(categories).map((k,i)=>[k,i])){const node=$(`[data-quick="${key}"]`).nextElementSibling;node.textContent=result.errors['expense_'+index]||'= '+fmt(result.values['expense_'+index]);node.classList.toggle('row-error',!!result.errors['expense_'+index])}$$('#expense-rows tr').forEach((row,i)=>{const node=row.querySelector('.row-result');node.textContent=result.errors['expense_'+(i+5)]||'= '+fmt(result.values['expense_'+(i+5)]);node.classList.toggle('row-error',!!result.errors['expense_'+(i+5)])});$('#category-totals').replaceChildren(...Object.entries(categories).map(([k,label])=>el('span',{text:label+': '+fmt(result.totals.categories[k])})));}catch(error){notice(error.message,true)}}
function fill(data){estimateSequence++;form.elements.issued_from_plan.checked=!!data.issued_from_plan;form.elements.daily_from_plan.checked=!!data.daily_from_plan;if(current?.id!==data.id)fileRows=[];current=data.id?data:null;for(const field of form.elements){if(!field.name||!(field.name in data))continue;if(field.type==='checkbox')field.checked=!!data[field.name];else field.value=data[field.name]??''}for(const key of Object.keys(categories)){$(`[data-planned="${key}"]`).value=data.planned?.[key]||'0';const quick=(data.expenses||[]).filter(r=>r.quick&&r.category===key);$(`[data-quick="${key}"]`).value=quick.map(r=>'('+r.amount+')').join(' + ')||'0';if(quick.length===1)$(`[data-quick="${key}"]`).value=quick[0].amount}$('#expense-rows').replaceChildren();for(const row of data.expenses||[])if(!row.quick)drawExpense(row);updateEmpty();dirty=false;$('#save-state').textContent=current?'Сохранено':'Новая карточка';$('#folder-path').textContent='Чеки и документы хранятся в карточке поездки.';setTitle();syncFiles(data.files||[]);hidePack();estimate();renderTrips()}
async function loadTrips(){tripList=await api('/api/trips');renderTrips()}
function renderTrips(){
    const query=$('#search').value.toLowerCase();
    $('#trips').replaceChildren(...tripList.filter(t=>((t.name||'')+' '+t.city+' '+t.employee).toLowerCase().includes(query)).map(trip=>{
        const row=el('div',{class:'trip-row'+(current?.id===trip.id?' active':'')});
        const open=el('button',{type:'button',class:'trip-open'});
        open.append(el('span',{text:trip.name||trip.city}),el('small',{text:trip.start.split('-').reverse().join('.')+' · '+trip.employee}));
        open.onclick=()=>action(async()=>{if(dirty&&!confirm('Есть несохранённые изменения. Открыть другую командировку без сохранения?'))return;fill(await api('/api/trips/'+trip.id));if(innerWidth<=760)setSidebarCollapsed(true);$('#message').hidden=true});
        const edit=el('button',{type:'button',class:'trip-edit','aria-label':'Редактировать проект '+(trip.name||trip.city),title:'Редактировать проект',text:'✎'});
        edit.onclick=()=>action(()=>openProjectEditor(trip.id));row.append(open,edit);return row;
    }));
}
async function save(){await estimate();if(!form.checkValidity()){const invalid=$('#form :invalid');const section=invalid?.closest('.panel');if(section)activate(section.id.replace('tab-',''));form.reportValidity();throw Error('Заполните обязательные поля карточки.')}if(current&&!dirty)return current;const saved=await api(current?'/api/trips/'+current.id:'/api/trips',{method:current?'PUT':'POST',body:getData()});current=saved;dirty=false;$('#save-state').textContent='Сохранено';syncFiles(saved.files);setTitle();await loadTrips();await loadSuggestions();return saved}
function fileURL(path,download=false){return '/api/trips/'+current.id+'/file?path='+encodeURIComponent(path)+(download?'&download=1':'')}
function syncFiles(incoming){
    const old=new Map(fileRows.map((f,i)=>[f.path,{...f,index:i}]));
    fileRows=incoming.map(f=>({...f,selected:old.get(f.path)?.selected??(f.supported&&!f.signed),
        copies:old.get(f.path)?.copies??(f.kind==='report'?Number(form.elements.report_copies.value)||2:1)}));
    fileRows.sort((a,b)=>Number(b.generated)-Number(a.generated)||
        (old.get(a.path)?.index??Infinity)-(old.get(b.path)?.index??Infinity));
    $('#signature-state').textContent=current?.has_signature?'Подпись добавлена к этой поездке.':'Подпись пока не добавлена.';
    $('#signature-remove').disabled=!current?.has_signature;
    const signaturePreview=$('#signature-preview');
    const thumbnail=current?.signature_thumbnail;
    signaturePreview.hidden=!thumbnail;
    if(thumbnail) signaturePreview.src=thumbnail;
    else signaturePreview.removeAttribute('src');
    $$('[data-signed], [data-share-signed]').forEach(button=>button.hidden=!current?.has_signature);
    renderFiles();
}
function moveFile(index,dir){
    const root=$('#files'), moving=fileRows[index].path;
    const before=new Map([...root.children].map(row=>[row.dataset.path,row.getBoundingClientRect().top]));
    [fileRows[index],fileRows[index+dir]]=[fileRows[index+dir],fileRows[index]];
    renderFiles();
    hidePack();
    for(const row of root.children){
        const offset=before.get(row.dataset.path)-row.getBoundingClientRect().top;
        if(offset&&!matchMedia('(prefers-reduced-motion: reduce)').matches){
            row.animate([{transform:'translateY('+offset+'px)'},{transform:'translateY(0)'}],
                {duration:300,easing:'cubic-bezier(.2,.75,.25,1)'});
        }
        if(row.dataset.path===moving){
            row.classList.add('just-moved');
            setTimeout(()=>row.classList.remove('just-moved'),650);
            (row.querySelector('[data-dir="'+dir+'"]:enabled')||row.querySelector('button:enabled'))?.focus({preventScroll:true});
        }
    }
}
function renderFiles(){
    const root=$('#files');root.replaceChildren();
    if(!fileRows.length){root.append(el('div',{class:'empty',text:'Пока здесь нет файлов. Подготовьте документы и добавьте чеки.'}));return}
    fileRows.forEach((file,index)=>{
        const row=el('div',{class:'file-row','data-path':file.path}),check=el('input',{type:'checkbox','aria-label':'Включить '+file.name});
        check.checked=file.selected;check.disabled=!file.supported;
        check.onchange=()=>{
            file.selected=check.checked;
            if(file.selected&&file.kind)for(const other of fileRows){
                if(other!==file&&other.kind===file.kind){
                    other.selected=false;
                    [...root.children].find(node=>node.dataset.path===other.path).querySelector('input[type=checkbox]').checked=false;
                }
            }
            hidePack();
        };
        const name=el('div',{class:'filename'});
        name.append(el('a',{text:file.name,href:fileURL(file.path),target:'_blank',rel:'noopener'}),
            el('small',{text:(file.signed?'Форма с подписью':file.generated?'Печатная форма':file.path)+' · '+Math.max(1,Math.round(file.size/1024))+' КБ'+(!file.supported?' · скачивание, без общей печати':'')}));
        const copies=el('input',{type:'number',min:'1',max:'10',value:file.copies,'aria-label':'Количество копий '+file.name});
        copies.disabled=!file.supported;copies.onchange=()=>{file.copies=Number(copies.value);hidePack()};
        row.append(check,name,copies);
        for(const[dir,label]of[[-1,'↑'],[1,'↓']]){
            const title=dir<0?'Раньше':'Позже';
            const button=el('button',{type:'button',text:label,title,'aria-label':title+': '+file.name,'data-dir':dir});
            button.disabled=fileRows[index+dir]?.generated!==file.generated;
            button.onclick=()=>moveFile(index,dir);
            row.append(button);
        }
        root.append(row);
    });
}
function signatureUpdated(result){
    current=result;syncFiles(result.files);hidePack();
    notice(result.has_signature?'Подпись добавлена. Можно открыть PDF с подписью или подготовить формы для комплекта.':'Образец подписи удалён.');
}
$('#signature-remove').onclick=()=>action(async()=>{
    if(!confirm('Удалить образец подписи из этой командировки? Уже собранные комплекты сохранятся.'))return;
    await save();
    signatureUpdated(await api('/api/trips/'+current.id+'/signature',{method:'DELETE'}));
});

function activate(name){$$('.tabs button').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));$$('.panel').forEach(p=>p.classList.toggle('active',p.id==='tab-'+name))}
function manageDialog(title){
    $('#project-manager')?.remove();
    const dialog=el('dialog',{id:'project-manager',class:'manage-dialog'}),top=el('div',{class:'manage-header'}),close=el('button',{type:'button',text:'×','aria-label':'Закрыть меню проекта'});
    close.onclick=()=>dialog.close();top.append(el('h2',{text:title}),close);dialog.append(top,el('div',{class:'manage-error',role:'status'}));document.body.append(dialog);return dialog;
}
function manageAction(fn){return action(async()=>{try{await fn();}catch(error){const target=$('#project-manager .manage-error');if(target)target.textContent=error.message;throw error;}});}
async function openProjectEditor(id){
    let trip=await api('/api/trips/'+id);
    if(current?.id===id&&current.revision!==trip.revision)throw Error('Проект изменён в другой вкладке. Откройте его заново.');
    const dialog=manageDialog('Редактирование проекта'),label=el('label',{text:'Название проекта'}),name=el('input',{value:trip.name||trip.city,maxlength:'120','aria-label':'Название проекта'});
    label.append(name);dialog.append(label,el('p',{class:'hint',text:'Название используется в списке проектов. Город и текст печатных документов задаются в карточке поездки.'}));
    const rename=el('button',{type:'button',class:'primary',text:'Сохранить название'});
    rename.onclick=()=>manageAction(async()=>{
        const result=await api('/api/trips/'+id+'/rename',{method:'POST',body:{name:name.value,revision:trip.revision}});
        if(current?.id===id){current.name=result.name;current.revision=result.revision;current.generated_revision=result.generated_revision;setTitle();}
        await loadTrips();dialog.close();notice('Название проекта сохранено.');
    });
    const open=el('button',{type:'button',text:'Открыть карточку'});
    open.onclick=()=>manageAction(async()=>{if(dirty)await save();fill(await api('/api/trips/'+id));dialog.close();activate('trip');});
    const copy=el('button',{type:'button',text:'Создать копию'});
    copy.onclick=()=>manageAction(async()=>{if(dirty)await save();const result=await api('/api/trips/'+id+'/copy',{method:'POST'});fill(result);await loadTrips();dialog.close();activate('trip');notice('Копия карточки создана. Чеки и готовые PDF в неё не копируются.');});
    const remove=el('button',{type:'button',class:'danger',text:'Удалить в корзину'});
    remove.onclick=()=>manageAction(async()=>{
        if(!confirm('Переместить проект «'+(trip.name||trip.city)+'» и его файлы в корзину? Его можно будет восстановить.'))return;
        if(current?.id===id&&dirty){await save();trip=current;}
        await api('/api/trips/'+id,{method:'DELETE',body:{revision:trip.revision}});
        if(current?.id===id){fill(await api('/api/defaults'));activate('trip');}
        await loadTrips();dialog.close();notice('Проект перемещён в корзину вместе с файлами.');
    });
    const actions=el('div',{class:'manage-actions'});actions.append(rename,open,copy,remove);dialog.append(actions,el('p',{class:'hint',text:'Копия содержит данные карточки без вложений. Удаление переносит карточку и папку печати в корзину.'}));dialog.showModal();name.focus();name.select();
}
$('#trash').onclick=()=>action(async()=>{
    const items=await api('/api/trash'),dialog=manageDialog('Корзина проектов');
    if(!items.length)dialog.append(el('p',{text:'Корзина пуста.'}));
    for(const item of items){
        const row=el('div',{class:'trash-row'}),text=el('div');text.append(el('strong',{text:item.name}),el('p',{class:'hint',text:item.city+' · '+item.start.split('-').reverse().join('.')}));
        const restore=el('button',{type:'button',text:'Восстановить','aria-label':'Восстановить '+item.name});
        restore.onclick=()=>manageAction(async()=>{await api('/api/trash/'+item.id+'/restore',{method:'POST'});await loadTrips();row.remove();notice('Проект восстановлен вместе с файлами.');if(!dialog.querySelector('.trash-row'))dialog.append(el('p',{text:'Корзина пуста.'}));});
        row.append(text,restore);dialog.append(row);
    }
    dialog.showModal();
});
function updateAutoFields(){form.elements.issued.readOnly=form.elements.issued_from_plan.checked;$('[data-quick="daily"]').readOnly=form.elements.daily_from_plan.checked;}
async function loadSuggestions(){const data=await api('/api/suggestions');for(const[group,id]of[['cities','cities-history'],['purposes','purposes-history']])$('#'+id).replaceChildren(...data[group].map(value=>el('option',{value})));}
async function previewDocument(kind,printNow=false,signed=false,shareNow=false){
    await save();
    let path;
    if(kind==='pack'){
        if(current.generated_revision!==current.revision){
            current=await api('/api/trips/'+current.id+'/generate',{method:'POST',body:{revision:current.revision}});
            syncFiles(current.files);
        }
        const selected=fileRows.filter(f=>f.selected&&f.supported);
        const result=await api('/api/trips/'+current.id+'/pack',{method:'POST',body:{revision:current.revision,files:selected.map(f=>({path:f.path,copies:f.copies}))}});
        path=result.path;
    }else{
        const result=await api('/api/trips/'+current.id+'/preview/'+kind,{method:'POST',body:{revision:current.revision,signed}});
        path=result.path;
    }
    const dialog=$('#pdf-preview'),frame=$('#preview-frame');
    $('#preview-title').textContent={request:'Заявка на командировку',report:'Авансовый отчёт',memo:'Служебная записка',pack:'Комплект для печати'}[kind]+(signed?' · с подписью':'');
    $('#preview-open').href=fileURL(path);
    const editSignature=$('#preview-signature-layout');
    editSignature.hidden=!signed;
    editSignature.onclick=()=>action(()=>openSignatureLayout(kind));
    ['print','share','export'].forEach(mode=>$('#preview-'+mode).onclick=()=>androidDocument(mode,path));
    if(shareNow){androidDocument('share',path);return;}
    if(printNow){androidDocument('print',path);return;}
    frame.src='/preview?id='+encodeURIComponent(current.id)+'&path='+encodeURIComponent(path);
    dialog.showModal();
}
$$('[data-preview]').forEach(button=>button.onclick=()=>action(()=>previewDocument(button.dataset.preview)));
$$('[data-print]').forEach(button=>button.onclick=()=>action(()=>previewDocument(button.dataset.print,true)));
$$('[data-signed]').forEach(button=>button.onclick=()=>action(()=>previewDocument(button.dataset.signed,false,true)));
$$('[data-share], [data-share-signed]').forEach(button=>button.onclick=()=>action(()=>previewDocument(button.dataset.share||button.dataset.shareSigned,false,!!button.dataset.shareSigned,true)));
$('#preview-close').onclick=()=>{$('#pdf-preview').close();$('#preview-frame').src='about:blank';};
for(const[key,name]of Object.entries(categories)){for(const[id,attr]of[['planned','data-planned'],['quick-expenses','data-quick']]){const label=el('label',{text:name+' · руб.'}),input=el('input',{[attr]:key,placeholder:'0 или 300 + 250',inputmode:'text'});label.append(input);if(attr==='data-quick')label.append(el('div',{class:'row-result',text:'= 0,00 ₽'}));$('#'+id).append(label)}}
$$('.tabs button').forEach(b=>b.onclick=()=>activate(b.dataset.tab));
form.addEventListener('submit',event=>{event.preventDefault();action(save)});
form.addEventListener('input',event=>{if(event.target.closest('#files')||event.target.type==='file')return;markDirty();if(event.target.name==='city')setTitle();if(event.target.name==='report_copies'){for(const f of fileRows)if(f.kind==='report')f.copies=Number(event.target.value)||2;renderFiles()}});
$('#save').onclick=()=>action(async()=>{await save();notice('Командировка сохранена.');});
$('#new').onclick=()=>action(async()=>{if(dirty&&!confirm('Есть несохранённые изменения. Создать новую карточку без сохранения?'))return;fileRows=[];fill(await api('/api/defaults'));activate('trip');if(innerWidth<=760)setSidebarCollapsed(true)});
$('#search').oninput=renderTrips;
$('#add-expense').onclick=()=>{$('.expense-details').open=true;drawExpense().querySelector('[data-field="amount"]').focus();markDirty()};
$('#generate').onclick=()=>action(async()=>{await save();const result=await api('/api/trips/'+current.id+'/generate',{method:'POST',body:{revision:current.revision}});current=result;syncFiles(result.files);notice('Документы готовы. Откройте их для проверки или соберите общий PDF.');});
$('#refresh').onclick=()=>action(async()=>{await save();const result=await api('/api/trips/'+current.id);syncFiles(result.files);hidePack();notice('Список файлов обновлён.');});
$('#pack').onclick=()=>action(async()=>{await save();if(['request','report','memo','details'].some(k=>form.elements['include_'+k].checked)&&current.generated_revision!==current.revision)throw Error('Данные изменились. Сначала нажмите «Подготовить документы», затем соберите комплект.');const chosen=fileRows.filter(f=>f.selected&&f.supported);if(!chosen.length)throw Error('Подготовьте документы или выберите чеки для печати.');const result=await api('/api/trips/'+current.id+'/pack',{method:'POST',body:{revision:current.revision,files:chosen.map(f=>({path:f.path,copies:f.copies}))}});const node=$('#pack-result');node.replaceChildren(el('p',{text:'Комплект готов · страниц: '+result.pages}));const a=el('button',{type:'button',text:'Поделиться PDF'});a.onclick=()=>androidDocument('share',result.path);const download=el('a',{href:fileURL(result.path,true),text:'Сохранить PDF'});node.append(a,document.createTextNode('   ·   '),download,el('p',{text:'Число копий уже учтено при сборке. PDF можно сохранить или отправить.'}));node.hidden=false;node.scrollIntoView({behavior:'smooth',block:'nearest'})});
action(async()=>{await loadTrips();await loadSuggestions();fill(await api('/api/defaults'));});


configureAndroid();
