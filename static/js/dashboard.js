// Aether Solar-Pro - Interaction Engine
document.addEventListener('DOMContentLoaded', () => {
    // State
    const state = {
        activeAgent: 'hub',
        selectedFile: null,
        currentJobId: null
    };

    // UI Elements
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('fileInput');
    const startBtn = document.getElementById('startBtn');
    const processingList = document.getElementById('processing-list');
    const resultsList = document.getElementById('results-list');

    // --- OCR Synthesis Pipeline ---
    if (dropzone) {
        dropzone.addEventListener('click', () => fileInput.click());
        dropzone.addEventListener('dragover', (e) => { 
            e.preventDefault(); 
            dropzone.style.borderColor = 'var(--accent-orange)'; 
            dropzone.style.background = 'rgba(255, 140, 0, 0.05)';
        });
        dropzone.addEventListener('dragleave', () => { 
            dropzone.style.borderColor = 'var(--border-medium)'; 
            dropzone.style.background = '#ffffff';
        });
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.style.borderColor = 'var(--border-medium)';
            dropzone.style.background = '#ffffff';
            if (e.dataTransfer.files.length > 0) handleOCRFile(e.dataTransfer.files[0]);
        });
    }

    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) handleOCRFile(e.target.files[0]);
        });
    }

    function handleOCRFile(file) {
        if (file.type !== 'application/pdf') { alert('Solar-Pro Synthesis requires PDF archives.'); return; }
        state.selectedFile = file;
        dropzone.querySelector('h2').textContent = file.name;
        dropzone.querySelector('p').textContent = `${(file.size / (1024 * 1024)).toFixed(2)} MB - Solar Analysis Ready`;
        
        startBtn.disabled = false;
        startBtn.style.boxShadow = '0 0 20px var(--orange-glow)';
    }

    if (startBtn) {
        startBtn.addEventListener('click', async () => {
            if (!state.selectedFile) return;

            const formData = new FormData();
            formData.append('file', state.selectedFile);
            formData.append('engine', 'solar-pro-v5');

            startBtn.disabled = true;
            startBtn.textContent = 'Illuminating Archives...';

            try {
                const response = await fetch('/api/upload', { method: 'POST', body: formData });
                const data = await response.json();

                if (response.ok) {
                    state.currentJobId = data.job_id;
                    startPolling(data.job_id);
                }
            } catch (err) {
                alert('Solar Link Lost. Retry.');
                startBtn.disabled = false;
            }
        });
    }

    function startPolling(jobId) {
        const interval = setInterval(async () => {
            try {
                const response = await fetch(`/api/status/${jobId}`);
                const job = await response.json();
                
                renderOCRStatus(job);

                if (job.status === 'completed' || job.status === 'failed') {
                    clearInterval(interval);
                    if (job.status === 'completed') renderOCRResults(job);
                }
            } catch (err) { console.error(err); }
        }, 2000);
    }

    function renderOCRStatus(job) {
        processingList.innerHTML = `
            <div class="pro-card-solar" style="margin-top: 32px; padding: 32px; border-radius: 20px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 16px; font-weight: 800; font-size: 0.8rem; color: var(--text-primary);">
                    <span>ILLUMINATING: ${job.filename}</span>
                    <span style="color: var(--accent-orange);">${job.progress}%</span>
                </div>
                <div style="height: 6px; background: #f1f5f9; border-radius: 10px; overflow: hidden;">
                    <div style="height: 100%; background: var(--grad-solar); width: ${job.progress}%; box-shadow: 0 0 20px var(--orange-glow);"></div>
                </div>
            </div>
        `;
    }

    function renderOCRResults(job) {
        resultsList.innerHTML = `
            <h4 style="margin: 48px 0 24px; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.1em; color: var(--text-primary);">Synthesis Complete</h4>
            ${job.output_files.map(file => `
                <div style="padding: 20px 24px; background: #fff; border: 1px solid var(--border-subtle); border-radius: 16px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; box-shadow: 0 4px 15px rgba(0,0,0,0.02);">
                    <span style="font-size: 0.9rem; font-weight: 600; color: var(--text-primary);">${file}</span>
                    <button class="btn-solar" style="padding: 10px 20px; font-size: 0.75rem;" onclick="downloadFile('${job.job_id}', '${file}')">Download PDF</button>
                </div>
            `).join('')}
        `;
        lucide.createIcons();
    }

    window.downloadFile = (jobId, filename) => {
        window.location.href = `/api/download/${jobId}/${filename}`;
    };
});
