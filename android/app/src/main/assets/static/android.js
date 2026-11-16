/* Android-only integration for the shared J701 interface. */
const pending = new Map();
let nextCall = 0;
let activePackCall = null;
window.J701Reply = (id, raw) => {
    const done = pending.get(id);
    if (!done) return;
    pending.delete(id);
    try {
        const response = JSON.parse(raw);
        if (response.ok) done.resolve(response.data);
        else done.reject(Error(response.data?.error || 'Не удалось выполнить действие.'));
    } catch (error) { done.reject(error); }
};
function nativeCall(method, ...args) {
    return new Promise((resolve, reject) => {
        const id = ++nextCall;
        pending.set(id, {resolve, reject});
        try { J701Native[method](id, ...args); }
        catch (error) { pending.delete(id); reject(error); }
    });
}

function setPackProgress(percent,message) {
    $('#pack-progress').value=percent;
    $('#pack-progress-percent').textContent=percent+'%';
    $('#pack-progress-status').textContent=message;
}

window.J701PackProgress = (id,percent,message) => {
    if (id===activePackCall) setPackProgress(percent,message);
};

async function androidRequest(path,{method='GET',body}={}) {
    const payload=body ? JSON.stringify(body) : '';
    if (method!=='POST' || !path.endsWith('/pack')) return nativeCall('request',method,path,payload);

    $('#busy-spinner').hidden=true;
    $('#pack-progress-box').hidden=false;
    setPackProgress(0,'Проверяем выбранные файлы');
    activePackCall=nextCall+1;
    try {
        return await nativeCall('request',method,path,payload);
    } finally {
        activePackCall=null;
        $('#pack-progress-box').hidden=true;
        $('#busy-spinner').hidden=false;
    }
}
function androidDocument(mode, path) {
    J701Native.document(mode, current.id, path);
}
function configureAndroid() {
    $('#add-receipts').onclick = () => action(async () => {
        await save();
        const result = await nativeCall('pick', current.id, 'upload');
        if (!result) return;
        syncFiles(result.files); hidePack();
        notice('Чеки добавлены к поездке.');
    });
    $('#signature-pick').onclick = () => action(async () => {
        await save();
        const result = await nativeCall('pick', current.id, 'signature');
        if (result) signatureUpdated(result);
    });
    document.addEventListener('click', event => {
        const link = event.target.closest('a[href^="/api/trips/"]');
        if (!link) return;
        event.preventDefault();
        const url = new URL(link.href);
        const id = url.pathname.split('/')[3];
        J701Native.document(url.searchParams.has('download') ? 'export' : 'open', id, url.searchParams.get('path'));
    });
}
window.J701Back = () => {
    const dialog = document.querySelector('dialog[open]');
    if (dialog?.id === 'signature-layout' && $('#signature-layout-save').disabled) return;
    if (dialog) dialog.close();
    else if (!$('.layout').classList.contains('sidebar-collapsed')) setSidebarCollapsed(true);
    else if ($('.tabs button.active')?.dataset.tab !== 'trip') activate('trip');
    else if (!dirty || confirm('Есть несохранённые изменения. Выйти из приложения?')) J701Native.exit();
};
