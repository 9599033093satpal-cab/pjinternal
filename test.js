
lucide.createIcons();
setGreeting();

let activeJobId = null;
let pollInterval = null;
let sessionPages = 0;
let sessionJobs = 0;

function setGreeting() {
    const now = new Date();
    const hours = now.getHours();
    let greet = "Good Morning";
    if (hours >= 12 && hours < 17) greet = "Good Afternoon";
    else if (hours >= 17) greet = "Good Evening";
    
    document.getElementById('greeting-box').innerHTML = `<span style="color:var(--gold);">⚡ ${greet},</span> ${sessionStorage.getItem('userName') || 'Aether User'}`;
}

function collapsePanel(side) {
    const left = document.querySelector('#val-workspace > div:first-child');
    const right = document.getElementById('val-right-panel');
    
    if (side === 'left') {
        const isCollapsed = left.style.flex === '0 0 40px';
        left.style.flex = isCollapsed ? '1' : '0 0 40px';
        left.style.overflow = isCollapsed ? 'hidden' : 'hidden';
        left.querySelector('div:nth-child(2)').style.display = isCollapsed ? 'flex' : 'none';
        left.querySelector('button').textContent = isCollapsed ? '◀' : '▶';
    } else {
        const isCollapsed = right.style.flex === '0 0 40px';
        right.style.flex = isCollapsed ? '1' : '0 0 40px';
        right.querySelector('div:nth-child(2)').style.display = isCollapsed ? 'block' : 'none';
        right.querySelector('button').textContent = isCollapsed ? '▶' : '◀';
    }
}

// ── Drop Zone ──
const dz = document.getElementById('dropzone');
const fi = document.getElementById('fileInput');
let selectedFile = null;

dz.addEventListener('dragover', e => { e.preventDefault(); dz.style.borderColor = 'var(--gold)'; dz.style.background = 'var(--gold-pale)'; });
dz.addEventListener('dragleave', () => { dz.style.borderColor = ''; dz.style.background = ''; });
dz.addEventListener('drop', e => {
    e.preventDefault(); dz.style.borderColor = ''; dz.style.background = '';
    if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
});
fi.addEventListener('change', () => { if (fi.files[0]) setFile(fi.files[0]); });

function setFile(file) {
    if (!file.name.toLowerCase().endsWith('.pdf')) { alert('Please upload a PDF file.'); return; }
    selectedFile = file;
    document.getElementById('drop-title').textContent = file.name;
    document.getElementById('drop-sub').textContent = (file.size / (1024*1024)).toFixed(1) + ' MB · Ready to process';
    dz.style.borderColor = 'var(--gold)';
    const btn = document.getElementById('startBtn');
    btn.disabled = false; btn.style.opacity = '1'; btn.style.cursor = 'pointer';
    btn.textContent = 'Start OCR Processing →';
}

// ── Start OCR ──
async function startOCR() {
    if (!selectedFile) return;
    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('language', document.getElementById('lang-select').value);
    formData.append('dpi', document.getElementById('dpi-select').value);
    formData.append('workers', document.getElementById('workers-select').value);

    const btn = document.getElementById('startBtn');
    btn.disabled = true; btn.textContent = 'Uploading...';

    try {
        const res = await fetch('/api/upload', { method: 'POST', body: formData });
        const data = await res.json();
        if (res.ok) {
            activeJobId = data.job_id;
            startPolling(data.job_id, data.filename);
            sessionJobs++;
            document.getElementById('stat-total').textContent = sessionJobs;
        } else {
            alert('Error: ' + (data.error || 'Upload failed'));
            btn.disabled = false; btn.textContent = 'Start OCR Processing →';
        }
    } catch (e) {
        alert('Connection error. Is the server running?');
        btn.disabled = false; btn.textContent = 'Start OCR Processing →';
    }
}

// ── Polling ──
function startPolling(jobId, filename) {
    document.getElementById('job-progress').style.display = 'block';
    document.getElementById('prog-filename').textContent = filename;
    document.getElementById('startBtn').textContent = 'Processing...';

    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(() => pollJob(jobId), 1500);
}

async function pollJob(jobId) {
    try {
        const res = await fetch(`/api/status/${jobId}`);
        const job = await res.json();
        updateProgress(job);
        updatePulse(job);
        if (job.status === 'completed' || job.status === 'failed') {
            clearInterval(pollInterval);
            onJobComplete(job);
        }
    } catch(e) { console.error(e); }
}

function updateProgress(job) {
    document.getElementById('prog-pct').textContent = job.progress + '%';
    document.getElementById('prog-bar').style.width = job.progress + '%';
    document.getElementById('prog-pages').textContent =
        job.status === 'refining' ? 'Neural Refinement: Structuring JSON... 🧠' :
        job.total_pages > 0 ? `Page ${job.current_page} of ${job.total_pages}` : 'Initializing engine...';
}

function updatePulse(job) {
    const pulse = document.getElementById('pulse-active');
    const isRefining = job.status === 'refining';
    pulse.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
            <div style="width:7px;height:7px;border-radius:50%;background:${isRefining?'#34d399':'var(--gold)'};animation:pulseDot 1s infinite;"></div>
            <span style="font-weight:800;font-size:0.8rem;color:${isRefining?'#34d399':'var(--gold)'};">${isRefining?'REFINING':'PROCESSING'}</span>
        </div>
        <div style="font-size:0.78rem;color:var(--text-bright);font-weight:700;margin-bottom:6px;">${job.filename}</div>
        <div style="font-size:0.72rem;color:var(--text-dim);margin-bottom:10px;">${isRefining?'Applying Neural Logic...':`${job.current_page}/${job.total_pages} pages · ${job.progress}%`}</div>
        <div style="height:4px;background:var(--ink-soft);border-radius:100px;overflow:hidden;">
            <div style="height:100%;background:${isRefining?'linear-gradient(90deg,#34d399,#10b981)':'var(--grad-gold)'};width:${job.progress}%;transition:width 0.5s;border-radius:10px;"></div>
        </div>`;
}

function onJobComplete(job) {
    if (job.status === 'completed') {
        sessionPages += job.total_pages;
        document.getElementById('stat-pages').textContent = sessionPages.toLocaleString();

        // Show download buttons for TXT, Raw JSON, and Semantic JSON
        const files = document.getElementById('prog-files');
        files.innerHTML = job.output_files.filter(f => f.endsWith('.txt') || f.endsWith('.json') && !f.includes('metadata')).map(f => {
            let label = f;
            let style = "background:var(--ink);color:var(--text-bright);";
            if (f.endsWith('_semantic.json')) { label = 'Neural Insight JSON'; style = "background:var(--grad-gold);color:var(--ink);font-weight:900;"; }
            else if (f.endsWith('_combined.json')) { label = 'Raw JSON'; style = "background:var(--ink-soft);color:var(--text-mid);"; }
            return `<a href="/api/download/${job.job_id}/${f}" class="btn-solar" style="padding:10px 20px;font-size:0.78rem;${style}">⬇ ${label}</a>`;
        }).join('');

        document.getElementById('prog-pages').textContent = `✓ Complete — ${job.total_pages} pages processed`;
        document.getElementById('prog-bar').style.background = 'linear-gradient(135deg,#34d399,#10b981)';
        document.getElementById('prog-pct').style.color = '#34d399';

        document.getElementById('pulse-active').innerHTML = `
            <div style="font-weight:800;font-size:0.82rem;color:#34d399;margin-bottom:6px;">✓ Job Complete</div>
            <div style="font-size:0.72rem;color:var(--text-dim);">${job.total_pages} pages · ${job.output_files.filter(f=>f.endsWith('.txt')).length} files ready</div>`;

        const btn = document.getElementById('startBtn');
        btn.disabled = false; btn.textContent = 'Process Another PDF →'; btn.style.opacity = '1';
        selectedFile = null;
    } else {
        document.getElementById('prog-pages').textContent = '✗ Failed: ' + (job.error || 'Unknown error');
        document.getElementById('startBtn').disabled = false;
        document.getElementById('startBtn').textContent = 'Retry →';
    }
}

// ── Job History ──
async function loadJobs() {
    const res = await fetch('/api/jobs');
    const jobs = await res.json();
    const el = document.getElementById('jobs-list');
    if (!jobs.length) { el.innerHTML = '<div style="text-align:center;padding:80px;color:var(--text-dim);">No jobs yet. Start your first OCR job.</div>'; return; }
    el.innerHTML = jobs.map(job => `
        <div style="background:var(--ink-mid);border:1px solid var(--border);border-radius:16px;padding:24px;margin-bottom:16px;display:flex;justify-content:space-between;align-items:center;gap:20px;">
            <div style="flex:1;min-width:0;">
                <div style="font-weight:800;font-size:0.95rem;color:var(--text-bright);margin-bottom:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${job.filename}</div>
                <div style="font-size:0.75rem;color:var(--text-dim);">${job.total_pages} pages · ${job.language.toUpperCase()} · ${new Date(job.started_at).toLocaleString()}</div>
            </div>
            <div style="display:flex;align-items:center;gap:12px;flex-shrink:0;">
                <span style="padding:4px 12px;border-radius:100px;font-size:0.68rem;font-weight:900;background:${job.status==='completed'?'rgba(52,211,153,0.1)':job.status==='processing'?'var(--gold-pale)':'rgba(248,113,113,0.1)'};color:${job.status==='completed'?'#34d399':job.status==='processing'?'var(--gold)':'#f87171'};">${job.status.toUpperCase()}</span>
                ${job.status==='completed' ? job.output_files.filter(f=>f.endsWith('.txt') || f.endsWith('.json') && !f.includes('metadata')).map(f=> {
                    let label = f.endsWith('_semantic.json') ? 'INSIGHT' : f.endsWith('_combined.json') ? 'JSON' : f;
                    let style = f.endsWith('_semantic.json') ? "background:var(--gold);color:var(--ink);" : "background:var(--ink);color:var(--text-bright);";
                    return `<a href="/api/download/${job.job_id}/${f}" class="btn-solar" style="padding:8px 16px;font-size:0.72rem;${style}">⬇ ${label}</a>`;
                }).join('') : ''}
                <button onclick="deleteJob('${job.job_id}')" style="background:none;border:1px solid var(--border);border-radius:8px;padding:6px 10px;color:var(--text-dim);cursor:pointer;font-size:0.72rem;transition:all 0.2s;" onmouseover="this.style.borderColor='#f87171';this.style.color='#f87171'" onmouseout="this.style.borderColor='';this.style.color='';">✕</button>
            </div>
        </div>
    `).join('');
}

async function deleteJob(jobId) {
    if (!confirm('Delete this job and its files?')) return;
    await fetch(`/api/delete/${jobId}`, { method: 'DELETE' });
    loadJobs();
    if (typeof loadValidationJobs === 'function') {
        loadValidationJobs();
    }
}

// ── View routing ──
const views = { upload: 'New OCR Job', validation: 'Validation Dashboard', jobs: 'Job History', settings: 'OCR Settings' };
function showView(name) {
    document.querySelectorAll('.ocr-view').forEach(v => v.style.display = 'none');
    document.getElementById('view-' + name).style.display = (name === 'validation') ? 'flex' : 'block';
    document.getElementById('view-title').textContent = views[name];
    
    document.querySelectorAll('.sidebar-item').forEach(i => {
        i.classList.remove('active');
        if (i.getAttribute('onclick') && i.getAttribute('onclick').includes(name)) {
            i.classList.add('active');
        }
    });

    if (name === 'jobs') loadJobs();
    if (name === 'validation') loadValidationJobs();
}

// ── Validation HITL Logic ──
let valCurrentJobId = null;
let valCurrentPage = 1;
let valTotalPages = 1;
let valJsonData = null;

async function loadValidationJobs() {
    showValidationList(); // Ensure list is visible
    const res = await fetch('/api/jobs');
    const jobs = await res.json();
    const container = document.getElementById('val-job-list-container');
    
    if (jobs.length === 0) {
        container.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-dim);background:var(--ink-mid);border-radius:16px;border:1px dashed var(--border);">No files available yet.</div>';
        return;
    }
    
    let tableHTML = `
    <div style="background:var(--ink-mid);border:1px solid var(--border);border-radius:12px;overflow:hidden;">
        <table style="width:100%;border-collapse:collapse;font-size:0.85rem;text-align:left;">
            <thead>
                <tr style="background:var(--ink-soft);border-bottom:1px solid var(--border);color:var(--text-dim);">
                    <th style="padding:16px;font-weight:700;">File Name</th>
                    <th style="padding:16px;font-weight:700;">Status</th>
                    <th style="padding:16px;font-weight:700;">Accuracy</th>
                    <th style="padding:16px;font-weight:700;">Started</th>
                    <th style="padding:16px;font-weight:700;text-align:right;">Actions</th>
                </tr>
            </thead>
            <tbody>
    `;

    tableHTML += jobs.map(job => {
        const dateStr = new Date(job.started_at).toLocaleString();
        
        let statusBadge = '';
        if (job.status === 'ready_for_export') {
            statusBadge = '<span style="padding:4px 10px;border-radius:100px;font-size:0.65rem;font-weight:900;background:rgba(59,130,246,0.1);color:#3b82f6;">🚀 READY FOR EXPORT</span>';
        } else if (job.status === 'exported') {
            statusBadge = '<span style="padding:4px 10px;border-radius:100px;font-size:0.65rem;font-weight:900;background:rgba(16,185,129,0.1);color:#10b981;">✅ EXPORTED</span>';
        } else if (job.status === 'completed') {
            statusBadge = job.is_locked ? 
                '<span style="padding:4px 10px;border-radius:100px;font-size:0.65rem;font-weight:900;background:rgba(168,85,247,0.1);color:#a855f7;">🔒 VERIFIED & LOCKED</span>' :
                '<span style="padding:4px 10px;border-radius:100px;font-size:0.65rem;font-weight:900;background:rgba(52,211,153,0.1);color:#34d399;">READY FOR HITL</span>';
        } else if (job.status === 'processing') {
            statusBadge = '<span style="padding:4px 10px;border-radius:100px;font-size:0.65rem;font-weight:900;background:var(--gold-pale);color:var(--gold);">PROCESSING</span>';
        } else {
            statusBadge = '<span style="padding:4px 10px;border-radius:100px;font-size:0.65rem;font-weight:900;background:rgba(248,113,113,0.1);color:#f87171;">FAILED</span>';
        }

        let accuracyHtml = '-';
        if (job.accuracy_score !== null) {
            let color = job.accuracy_score >= 90 ? '#34d399' : '#fbbf24';
            accuracyHtml = `<span style="font-weight:800;color:${color};">${job.accuracy_score}%</span>`;
        }

        let editCountHtml = '';
        if (job.audit_summary && job.audit_summary.edit_count > 0) {
            editCountHtml = `<div style="font-size:0.65rem;color:var(--gold);margin-top:4px;font-weight:700;">✏️ ${job.audit_summary.edit_count} times edited</div>`;
        }

        let actionsHtml = `<div style="display:flex;justify-content:flex-end;gap:8px;">`;
        
        // Always allow deletion
        const deleteBtn = `<button onclick="deleteJob('${job.job_id}')" style="padding:6px 10px;font-size:0.8rem;background:transparent;color:#f87171;border:1px solid rgba(248,113,113,0.3);border-radius:6px;cursor:pointer;" title="Delete">🗑️</button>`;

        if (job.status === 'processing') {
            actionsHtml += `<span style="font-size:0.7rem;color:var(--text-dim);">Processing...</span>`;
        } else if (job.status === 'failed') {
            actionsHtml += `<button onclick="loadValidationData('${job.job_id}', ${job.total_pages})" style="padding:6px 12px;font-size:0.75rem;background:var(--grad-gold);color:var(--ink);border:none;border-radius:6px;cursor:pointer;font-weight:700;">Retry</button>`;
        } else {
            // Always allow Validate
            actionsHtml += `<button onclick="loadValidationData('${job.job_id}', ${job.total_pages})" style="padding:6px 12px;font-size:0.75rem;background:var(--grad-gold);color:var(--ink);border:none;border-radius:6px;cursor:pointer;font-weight:700;">🔍 Validate</button>`;

            // Raw JSON button
            let rawJsonFile = Array.isArray(job.output_files) ? job.output_files.find(f => typeof f === 'string' && f.endsWith('_combined.json')) : null;
            if (rawJsonFile) {
                actionsHtml += `<a href="/api/download/${job.job_id}/${rawJsonFile}" target="_blank" style="padding:6px 12px;font-size:0.75rem;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;cursor:pointer;font-weight:700;text-decoration:none;">⬇ Raw JSON</a>`;
            }

            // Audited / Verified JSON and Audit buttons
            if (job.audit_summary && job.audit_summary.edit_count > 0) {
                actionsHtml += `<a href="/api/download_verified/${job.job_id}" target="_blank" style="padding:6px 12px;font-size:0.75rem;background:rgba(16,185,129,0.1);color:#10b981;border:1px solid rgba(16,185,129,0.25);border-radius:6px;cursor:pointer;font-weight:700;text-decoration:none;">✅ Verified JSON</a>`;
                actionsHtml += `<button onclick="showAuditForJob('${job.job_id}')" style="padding:6px 12px;font-size:0.75rem;background:rgba(168,85,247,0.1);color:#a855f7;border:1px solid rgba(168,85,247,0.25);border-radius:6px;cursor:pointer;font-weight:700;">📋 Audit</button>`;
            }

            if (job.status === 'ready_for_export' || job.status === 'exported') {
                actionsHtml += `<button onclick="openExportModalDirect('${job.job_id}')" style="padding:6px 12px;font-size:0.75rem;background:rgba(59,130,246,0.15);color:#3b82f6;border:1px solid rgba(59,130,246,0.3);border-radius:6px;cursor:pointer;font-weight:700;">🚀 Export</button>`;
            }
        }
        
        actionsHtml += deleteBtn;
        actionsHtml += `</div>`;

        return `
        <tr style="border-bottom:1px solid var(--border);transition:background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.02)'" onmouseout="this.style.background='transparent'">
            <td style="padding:16px;">
                <a href="/api/download_pdf/${job.job_id}" target="_blank" title="Download Original PDF" style="display:inline-block;font-weight:800;color:#60a5fa;text-decoration:none;margin-bottom:4px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;transition:color 0.2s;" onmouseover="this.style.color='#93c5fd'" onmouseout="this.style.color='#60a5fa'">📄 ${job.filename}</a>
                <div style="font-size:0.65rem;color:var(--text-dim);font-family:monospace;">ID: ${job.job_id.substring(0,8)}...</div>
                ${editCountHtml}
            </td>
            <td style="padding:16px;">${statusBadge}</td>
            <td style="padding:16px;">${accuracyHtml}</td>
            <td style="padding:16px;color:var(--text-mid);font-size:0.75rem;">${dateStr}</td>
            <td style="padding:16px;">${actionsHtml}</td>
        </tr>
        `;
    }).join('');

    tableHTML += `
            </tbody>
        </table>
    </div>`;
    
    container.innerHTML = tableHTML;
}

// Helper to show audit directly from the table
async function showAuditForJob(jobId) {
    try {
        const res = await fetch(`/api/audit/${jobId}`);
        const audit = await res.json();
        if (res.ok) {
            window._lastAudit = audit;
            showAuditModal();
        } else {
            alert('Error loading audit log');
        }
    } catch (e) {
        alert('Error loading audit log: ' + e);
    }
}

function showValidationList() {
    document.getElementById('val-workspace').style.display = 'none';
    document.getElementById('val-job-list-container').style.display = 'block';
    document.getElementById('val-back-btn').style.display = 'none';
    
    // Reset buttons
    document.getElementById('audit-btn').style.display = 'none';
    document.getElementById('download-verified-btn').style.display = 'none';
    document.getElementById('export-form-btn').style.display = 'none';
    document.getElementById('accuracy-badge').style.display = 'none';
    
    const saveBtn = document.getElementById('save-verified-btn');
    saveBtn.textContent = '💾 Save Verified Data';
    saveBtn.style.background = 'var(--grad-gold)';
    saveBtn.style.color = 'var(--ink)';
    saveBtn.style.border = 'none';

    valCurrentJobId = null;
}

async function loadValidationData(jobId, totalPages) {
    if (!jobId) return;
    
    valCurrentJobId = jobId;
    valTotalPages = totalPages || 1;
    valCurrentPage = 1;
    
    document.getElementById('val-job-list-container').style.display = 'none';
    document.getElementById('val-workspace').style.display = 'flex';
    document.getElementById('val-back-btn').style.display = 'inline-block';
    
    // 1. Fetch JSON
    document.getElementById('val-json-editor').innerHTML = '<div style="color:var(--text-dim);">Loading semantic data...</div>';
    try {
        const res = await fetch(`/api/semantic_data/${jobId}`);
        if (!res.ok) throw new Error(await res.text());
        valJsonData = await res.json();
        renderJsonEditor();
    } catch (e) {
        document.getElementById('val-json-editor').innerHTML = `<div style="color:#f87171;">Error loading JSON: ${e.message}</div>`;
        valJsonData = null;
    }
    
    // 2. Load Image
    updateValImage();

    // 3. Show Action Buttons if data exists
    if (valJsonData) {
        document.getElementById('download-verified-btn').style.display = 'inline-block';
        document.getElementById('export-form-btn').style.display = 'inline-block';
        // Check if audit exists for this job (best effort)
        fetch(`/api/audit/${jobId}`).then(res => {
            if (res.ok) document.getElementById('audit-btn').style.display = 'inline-block';
        }).catch(() => {});
    }
}

function updateValImage() {
    if (!valCurrentJobId) return;
    document.getElementById('val-page-indicator').textContent = `Pg ${valCurrentPage} / ${valTotalPages}`;
    const img = document.getElementById('val-doc-img');
    img.src = '';
    img.alt = 'Loading page image...';
    // Add cache buster to force reload if needed
    img.src = `/api/file_image/${valCurrentJobId}/${valCurrentPage}?t=${new Date().getTime()}`;
    
    // Reset zoom
    valScale = 1; valTranslateX = 0; valTranslateY = 0;
    applyTransform();
}

function changeValPage(delta) {
    const newPage = valCurrentPage + delta;
    if (newPage >= 1 && newPage <= valTotalPages) {
        valCurrentPage = newPage;
        updateValImage();
    }
}

// -- JSON Editor UI Builder --
function renderJsonEditor() {
    const container = document.getElementById('val-json-editor');
    container.innerHTML = '';
    
    if (!valJsonData) {
        container.innerHTML = '<div style="color:var(--text-dim);">No semantic data available to edit.</div>';
        return;
    }
    
    const form = document.createElement('form');
    form.id = 'val-form';
    buildFormFields(valJsonData, form, '');
    container.appendChild(form);
}

function buildFormFields(obj, parentElement, path) {
    if (obj === null || obj === undefined) return;
    
    if (Array.isArray(obj)) {
        const wrapper = document.createElement('div');
        wrapper.style.marginLeft = '12px';
        wrapper.style.paddingLeft = '12px';
        wrapper.style.borderLeft = '2px solid var(--border)';
        wrapper.style.marginBottom = '12px';
        
        obj.forEach((item, index) => {
            const itemPath = path ? `${path}[${index}]` : `[${index}]`;
            
            const itemHeader = document.createElement('div');
            itemHeader.style.fontSize = '0.7rem';
            itemHeader.style.color = 'var(--gold)';
            itemHeader.style.marginTop = '12px';
            itemHeader.style.marginBottom = '4px';
            itemHeader.style.fontWeight = 'bold';
            itemHeader.textContent = `Item ${index + 1}`;
            wrapper.appendChild(itemHeader);
            
            if (typeof item === 'object') {
                buildFormFields(item, wrapper, itemPath);
            } else {
                createInputField(item, wrapper, itemPath);
            }
        });
        parentElement.appendChild(wrapper);
    } 
    else if (typeof obj === 'object') {
        const wrapper = document.createElement('div');
        wrapper.style.marginBottom = '8px';
        
        for (const key in obj) {
            const newPath = path ? `${path}.${key}` : key;
            const fieldWrapper = document.createElement('div');
            fieldWrapper.style.marginBottom = '12px';
            
            const label = document.createElement('label');
            label.textContent = key.replace(/_/g, ' ').toUpperCase();
            label.style.display = 'block';
            label.style.fontSize = '0.7rem';
            label.style.color = 'var(--text-dim)';
            label.style.marginBottom = '4px';
            label.style.fontWeight = '800';
            fieldWrapper.appendChild(label);
            
            if (typeof obj[key] === 'object' && obj[key] !== null) {
                const nested = document.createElement('div');
                nested.style.marginLeft = '12px';
                nested.style.paddingLeft = '12px';
                nested.style.borderLeft = '1px dashed var(--border)';
                buildFormFields(obj[key], nested, newPath);
                fieldWrapper.appendChild(nested);
            } else {
                createInputField(obj[key], fieldWrapper, newPath);
            }
            wrapper.appendChild(fieldWrapper);
        }
        parentElement.appendChild(wrapper);
    }
}

function createInputField(value, parent, path) {
    const isMultiline = typeof value === 'string' && value.length > 80;
    const input = document.createElement(isMultiline ? 'textarea' : 'input');
    
    input.name = path;
    input.value = value || '';
    input.className = 'input-solar';
    input.style.width = '100%';
    input.style.backgroundColor = 'rgba(0,0,0,0.2)';
    input.style.fontFamily = 'monospace';
    input.style.fontSize = '0.85rem';
    input.style.fontSize = '0.85rem';
    input.style.color = 'var(--text-bright)';
    input.style.border = '1px solid var(--border)';
    input.style.borderRadius = '8px';
    input.style.padding = '10px 12px';
    input.style.transition = 'all 0.2s ease';
    input.style.outline = 'none';
    
    input.onfocus = () => {
        input.style.borderColor = 'var(--gold)';
        input.style.backgroundColor = 'rgba(212,175,55,0.05)';
        input.style.boxShadow = '0 0 10px rgba(212,175,55,0.2)';
    };
    input.onblur = () => {
        input.style.borderColor = 'var(--border)';
        input.style.backgroundColor = 'rgba(0,0,0,0.2)';
        input.style.boxShadow = 'none';
    };
    
    if (isMultiline) {
        input.style.resize = 'vertical';
        input.style.minHeight = '80px';
    }
    
    // Add nice focus effects defined in css
    parent.appendChild(input);
}

// -- Save JSON --
async function saveValidationData() {
    if (!valCurrentJobId || !valJsonData) { alert('No data loaded.'); return; }

    const form = document.getElementById('val-form');
    const formData = new FormData(form);
    let updatedJson = JSON.parse(JSON.stringify(valJsonData));
    for (let [path, value] of formData.entries()) { setNestedValue(updatedJson, path, value); }

    const btn = document.getElementById('save-verified-btn');
    btn.textContent = 'Saving...'; btn.style.opacity = '0.7'; btn.disabled = true;

    // ── 1. Save to server (best-effort) ──
    let accuracy = null;
    let auditData = null;
    try {
        const res = await fetch(`/api/semantic_data/${valCurrentJobId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updatedJson)
        });
        const result = await res.json();
        if (res.ok) {
            accuracy = result.accuracy;
            auditData = result.audit;
            window._lastAudit = auditData;
        }
    } catch (e) {
        console.warn('Server save failed (offline?), proceeding with local save:', e);
    }

    // ── 2. Always update local state ──
    valJsonData = updatedJson;
    window._verifiedJson = updatedJson;  // store for download

    // ── 3. Show Accuracy Badge ──
    const accBadge = document.getElementById('accuracy-badge');
    if (accuracy !== null) {
        accBadge.textContent = `✓ ${accuracy}% Accurate`;
        accBadge.style.background = accuracy >= 90
            ? 'rgba(52,211,153,0.12)' : 'rgba(251,191,36,0.12)';
        accBadge.style.color = accuracy >= 90 ? '#34d399' : '#fbbf24';
        accBadge.style.border = `1px solid ${accuracy >= 90 ? 'rgba(52,211,153,0.3)' : 'rgba(251,191,36,0.3)'}`;
    } else {
        accBadge.textContent = '✓ Saved Locally';
        accBadge.style.background = 'rgba(52,211,153,0.12)';
        accBadge.style.color = '#34d399';
        accBadge.style.border = '1px solid rgba(52,211,153,0.3)';
    }
    accBadge.style.display = 'inline-block';

    // ── 4. Removed Lock Badge ──
    document.getElementById('lock-badge').style.display = 'none';

    // ── 5. Show Audit, Download & Export buttons ──
    if (auditData) document.getElementById('audit-btn').style.display = 'inline-block';
    document.getElementById('download-verified-btn').style.display = 'inline-block';
    document.getElementById('export-form-btn').style.display = 'inline-block';

    // ── 6. Update Save button (keep enabled) ──
    btn.textContent = '💾 Saved';
    btn.style.background = 'rgba(52,211,153,0.15)';
    btn.style.color = '#34d399';
    btn.style.border = '1px solid rgba(52,211,153,0.3)';
    btn.style.opacity = '1';
    btn.disabled = false;
}

let customSchemaContent = null;
let activeJobId = null;

function openExportModalDirect(jobId) {
    activeJobId = jobId;
    openExportModal();
}

async function openExportModal() {
    if (!activeJobId && valCurrentJobId) activeJobId = valCurrentJobId;
    if (!activeJobId) { alert("Please select a job first."); return; }

    document.getElementById('export-modal').style.display = 'flex';
    document.getElementById('mapping-result-container').style.display = 'none';
    document.getElementById('generate-map-btn').style.display = 'block';
    document.getElementById('custom-schema-preview').style.display = 'none';
    customSchemaContent = null;
    
    // Load available forms
    try {
        const res = await fetch('/api/forms');
        const forms = await res.json();
        const select = document.getElementById('target-form-select');
        select.innerHTML = '<option value="">-- Choose a target format --</option><option value="custom">✨ Upload Custom Schema (.json)</option>';
        forms.forEach(f => {
            select.innerHTML += `<option value="${f.id}">${f.name}</option>`;
        });
        
        select.onchange = (e) => {
            if (e.target.value === 'custom') {
                document.getElementById('custom-schema-file').click();
            } else {
                document.getElementById('custom-schema-preview').style.display = 'none';
                customSchemaContent = null;
            }
        };
    } catch (e) {
        console.error('Error fetching forms:', e);
    }
}

function handleCustomSchemaUpload(input) {
    const file = input.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            customSchemaContent = JSON.parse(e.target.result);
            document.getElementById('custom-schema-preview').style.display = 'block';
            document.getElementById('custom-schema-name').textContent = file.name;
        } catch (err) {
            alert("Invalid JSON schema file.");
            input.value = '';
        }
    };
    reader.readAsText(file);
}

function clearCustomSchema() {
    customSchemaContent = null;
    document.getElementById('custom-schema-preview').style.display = 'none';
    document.getElementById('target-form-select').value = '';
    document.getElementById('custom-schema-file').value = '';
}

async function generateMapping() {
    const formId = document.getElementById('target-form-select').value;
    if (!formId) { alert('Please select a target form.'); return; }
    if (formId === 'custom' && !customSchemaContent) { alert('Please upload a custom schema.'); return; }

    const loader = document.getElementById('mapping-loader');
    const resultContainer = document.getElementById('mapping-result-container');
    const btn = document.getElementById('generate-map-btn');

    loader.style.display = 'block';
    resultContainer.style.display = 'none';
    btn.style.display = 'none';

    try {
        let endpoint = `/api/map_form/${activeJobId}?form_id=${formId}`;
        let body = null;
        let headers = {};

        if (formId === 'custom') {
            endpoint = `/api/map_custom_form/${activeJobId}`;
            body = JSON.stringify({ schema: customSchemaContent });
            headers = { 'Content-Type': 'application/json' };
        }

        const res = await fetch(endpoint, {
            method: formId === 'custom' ? 'POST' : 'GET',
            headers: headers,
            body: body
        });
        const result = await res.json();
        
        if (result.success) {
            document.getElementById('mapping-json-display').textContent = JSON.stringify(result.mapped_data, null, 2);
            resultContainer.style.display = 'block';
            window._lastMappedData = result.mapped_data;
            // Refresh jobs list to show EXPORTED status
            if (document.getElementById('view-validation').style.display !== 'none') loadValidationJobs();
        } else {
            alert('Mapping failed: ' + result.error);
            btn.style.display = 'block';
        }
    } catch (e) {
        alert('Error: ' + e);
        btn.style.display = 'block';
    } finally {
        loader.style.display = 'none';
    }
}

function downloadMappedJson() {
    if (!window._lastMappedData) return;
    const blob = new Blob([JSON.stringify(window._lastMappedData, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `mapped_form_${valCurrentJobId}.json`;
    a.click();
}

// -- Download Verified JSON (always works, uses in-memory data) --
function downloadVerifiedJson() {
    const data = window._verifiedJson || valJsonData;
    if (!data) { alert('No verified data available. Please save first.'); return; }

    const jsonStr = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `verified_${valCurrentJobId || 'output'}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}


function showAuditModal() {
    const audit = window._lastAudit;
    if (!audit) { alert('No audit data. Please save first.'); return; }

    const statsRow = document.getElementById('audit-stats-row');
    statsRow.innerHTML = [
        { label: 'Total Fields', val: audit.total_fields, color: '#f8fafc' },
        { label: 'Matched (AI Correct)', val: audit.matches, color: '#34d399' },
        { label: 'Human Corrections', val: audit.corrections, color: '#f87171' },
        { label: 'Accuracy', val: ((audit.matches / audit.total_fields) * 100).toFixed(1) + '%', color: '#e8a020' }
    ].map(s => `
        <div style="flex:1;padding:20px;text-align:center;border-right:1px solid rgba(255,255,255,0.07);">
            <div style="font-size:1.5rem;font-weight:900;color:${s.color};font-family:'Outfit',sans-serif;">${s.val}</div>
            <div style="font-size:0.65rem;color:#64748b;text-transform:uppercase;margin-top:4px;">${s.label}</div>
        </div>`).join('');

    const tbody = document.getElementById('audit-table-body');
    if (!audit.trail || audit.trail.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" style="padding:40px;text-align:center;color:#64748b;">No audit data available.</td></tr>`;
    } else {
        tbody.innerHTML = audit.trail.map(row => {
            const isCorrected = row.status === 'corrected';
            const statusBadge = isCorrected 
                ? '<span style="padding:3px 8px;background:rgba(248,113,113,0.1);color:#f87171;border-radius:6px;font-size:0.68rem;font-weight:800;">CORRECTED</span>'
                : '<span style="padding:3px 8px;background:rgba(52,211,153,0.1);color:#34d399;border-radius:6px;font-size:0.68rem;font-weight:800;">MATCHED</span>';
                
            const accuracyVal = isCorrected ? '0%' : '100%';
            const accColor = isCorrected ? '#f87171' : '#34d399';

            return `
            <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
                <td style="padding:12px 16px;vertical-align:top;color:#94a3b8;font-family:monospace;font-size:0.75rem;">${row.field}</td>
                <td style="padding:12px 16px;vertical-align:top;color:#cbd5e1;font-size:0.8rem;">${row.machine || '<em style="color:#475569">empty</em>'}</td>
                <td style="padding:12px 16px;vertical-align:top;color:#cbd5e1;font-size:0.8rem;">${isCorrected ? `<span style="color:#34d399">${row.human}</span>` : `<span style="color:#64748b">-</span>`}</td>
                <td style="padding:12px 16px;vertical-align:top;">
                    <div style="display:flex;align-items:center;gap:12px;">
                        ${statusBadge}
                        <span style="font-weight:800;font-size:0.75rem;color:${accColor};">${accuracyVal}</span>
                    </div>
                </td>
            </tr>`;
        }).join('');
    }
    document.getElementById('audit-modal').style.display = 'flex';
}

function closeAuditModal() {
    document.getElementById('audit-modal').style.display = 'none';
}


function setNestedValue(obj, path, value) {
    // Basic path parser (e.g. "personal_information.name" or "skills[0]")
    const parts = path.replace(/\[(\w+)\]/g, '.$1').split('.');
    let current = obj;
    for (let i = 0; i < parts.length - 1; i++) {
        current = current[parts[i]];
    }
    
    // Convert string back to number if original was number
    let finalKey = parts[parts.length - 1];
    if (typeof current[finalKey] === 'number') {
        current[finalKey] = Number(value);
    } else {
        current[finalKey] = value;
    }
}

// -- Zoom & Pan Logic --
const imgContainer = document.getElementById('val-img-container');
const docImg = document.getElementById('val-doc-img');
let valScale = 1;
let valTranslateX = 0;
let valTranslateY = 0;
let isDragging = false;
let startX, startY;

imgContainer.addEventListener('wheel', (e) => {
    e.preventDefault();
    const zoomFactor = 0.1;
    if (e.deltaY < 0) valScale += zoomFactor;
    else valScale = Math.max(0.5, valScale - zoomFactor);
    applyTransform();
});

imgContainer.addEventListener('mousedown', (e) => {
    isDragging = true;
    startX = e.clientX - valTranslateX;
    startY = e.clientY - valTranslateY;
    imgContainer.style.cursor = 'grabbing';
});

window.addEventListener('mouseup', () => {
    isDragging = false;
    imgContainer.style.cursor = 'default';
});

window.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    e.preventDefault();
    valTranslateX = e.clientX - startX;
    valTranslateY = e.clientY - startY;
    applyTransform();
});

function applyTransform() {
    docImg.style.transform = `translate(${valTranslateX}px, ${valTranslateY}px) scale(${valScale})`;
}

function valZoom(factor) {
    valScale = Math.max(0.5, valScale + factor);
    applyTransform();
}

function valZoomReset() {
    valScale = 1;
    valTranslateX = 0;
    valTranslateY = 0;
    applyTransform();
}

function toggleValPanel() {
    const rightPanel = document.getElementById('val-right-panel');
    if (rightPanel.style.display === 'none') {
        rightPanel.style.display = 'flex';
    } else {
        rightPanel.style.display = 'none';
    }
}

