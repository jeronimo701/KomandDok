'use strict';
const layoutDialog = $('#signature-layout');
const layoutStage = $('#signature-layout-page');
const layoutMark = $('#signature-layout-mark');
const layoutHandle = $('#signature-layout-handle');
const layoutScale = $('#signature-layout-scale');
let signatureLayout = null;
let layoutDrag = null;

function signaturePageURL(key, path, page) {
    return '/page.jpg?id='+encodeURIComponent(key)+'&path='+encodeURIComponent(path)+'&n='+page;
}

async function openSignatureLayout(kind) {
    await save();
    const route = '/api/trips/'+current.id+'/signature-layout/'+kind;
    const result = await api(route,{method:'POST',body:{revision:current.revision}});
    signatureLayout = {...result,kind,route,revision:current.revision,
        previous:result.placement,placement:{...result.placement},returnToPreview:true};
    $('#signature-layout-error').hidden = true;
    layoutStage.style.aspectRatio = result.anchor.pageWidth+'/'+result.anchor.pageHeight;
    $('#signature-layout-paper').src = signaturePageURL(current.id,result.path,result.anchor.page)+'&v='+Date.now();
    $('#signature-layout-ink').src = current.signature_thumbnail;
    $('#pdf-preview').close();
    renderSignatureLayout();
    layoutDialog.showModal();
    const scroll = $('#signature-layout-scroll');
    scroll.scrollTop = layoutMark.offsetTop+layoutMark.offsetHeight/2-scroll.clientHeight/2;
}

function renderSignatureLayout() {
    const {anchor,placement} = signatureLayout;
    const width = anchor.width*placement.scale;
    const height = anchor.height*placement.scale;
    const x = Math.min(anchor.pageWidth-width/2,Math.max(width/2,anchor.x+placement.dx));
    const y = Math.min(anchor.pageHeight-height/2,Math.max(height/2,anchor.y+placement.dy));
    placement.dx = x-anchor.x;
    placement.dy = y-anchor.y;
    layoutMark.style.left = (x-width/2)/anchor.pageWidth*100+'%';
    layoutMark.style.top = (y-height/2)/anchor.pageHeight*100+'%';
    layoutMark.style.width = width/anchor.pageWidth*100+'%';
    layoutMark.style.height = height/anchor.pageHeight*100+'%';
    layoutScale.value = Math.round(placement.scale*100);
    $('#signature-layout-value').textContent = layoutScale.value+'%';
}

layoutMark.addEventListener('pointerdown',event=>{
    if (!signatureLayout || layoutDrag || event.button!==0) return;
    const {anchor,placement} = signatureLayout;
    layoutDrag = {id:event.pointerId,x:event.clientX,y:event.clientY,start:{...placement},
        resize:event.target===layoutHandle,stage:layoutStage.getBoundingClientRect(),
        width:anchor.width,height:anchor.height};
    layoutMark.setPointerCapture(event.pointerId);
    event.preventDefault();
});
layoutMark.addEventListener('pointermove',event=>{
    if (layoutDrag?.id!==event.pointerId) return;
    const {anchor,placement} = signatureLayout;
    const drag = layoutDrag;
    const dx = (event.clientX-drag.x)/drag.stage.width*anchor.pageWidth;
    const dy = (event.clientY-drag.y)/drag.stage.height*anchor.pageHeight;
    if (drag.resize) {
        const change = (dx*drag.width+dy*drag.height)/(drag.width**2+drag.height**2);
        placement.scale = Math.min(3.5,Math.max(.35,drag.start.scale+change));
        const growth = placement.scale-drag.start.scale;
        placement.dx = drag.start.dx+drag.width*growth/2;
        placement.dy = drag.start.dy+drag.height*growth/2;
    } else {
        placement.dx = drag.start.dx+dx;
        placement.dy = drag.start.dy+dy;
    }
    renderSignatureLayout();
});
layoutMark.addEventListener('lostpointercapture',()=>{layoutDrag=null;});
layoutMark.addEventListener('keydown',event=>{
    const direction = {ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];
    if (!signatureLayout || !direction || event.target!==layoutMark) return;
    const step = event.shiftKey?10:2;
    signatureLayout.placement.dx += direction[0]*step;
    signatureLayout.placement.dy += direction[1]*step;
    renderSignatureLayout();
    event.preventDefault();
});
layoutScale.oninput = ()=>{
    signatureLayout.placement.scale = Number(layoutScale.value)/100;
    renderSignatureLayout();
};
$('#signature-layout-reset').onclick = ()=>{
    signatureLayout.placement = {dx:0,dy:0,scale:1};
    renderSignatureLayout();
};
$('#signature-layout-cancel').onclick = ()=>layoutDialog.close();
layoutDialog.addEventListener('close',()=>{
    layoutDrag = null;
    if (signatureLayout?.returnToPreview && !$('#pdf-preview').open && !serverClosed) $('#pdf-preview').showModal();
    signatureLayout = null;
});
layoutDialog.addEventListener('cancel',event=>{
    if ($('#signature-layout-save').disabled) event.preventDefault();
});
$('#signature-layout-save').onclick = async event=>{
    const editor = signatureLayout;
    const error = $('#signature-layout-error');
    event.target.disabled = true;
    $('#signature-layout-cancel').disabled = true;
    error.hidden = true;
    try {
        const result = await api(editor.route,{method:'PUT',
            body:{revision:editor.revision,previous:editor.previous,placement:editor.placement}});
        const hadForms = current.generated_revision===current.revision;
        current = result;
        editor.returnToPreview = false;
        layoutDialog.close();
        await action(async ()=>{
            if (hadForms && result.generated_revision!==result.revision) {
                try {
                    current = await api('/api/trips/'+current.id+'/generate',{method:'POST',body:{revision:current.revision}});
                } finally {
                    syncFiles(current.files);
                    hidePack();
                }
            } else {
                syncFiles(current.files);
                hidePack();
            }
            await previewDocument(editor.kind,false,true);
        });
    } catch (failure) {
        error.textContent = failure.message;
        error.hidden = false;
    } finally {
        event.target.disabled = false;
        $('#signature-layout-cancel').disabled = false;
    }
};
