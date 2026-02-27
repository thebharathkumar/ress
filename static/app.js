/* ═══════════════════════════════════════════════════
   Resume AI — Frontend Logic
   ═══════════════════════════════════════════════════ */

// ── Base Resume Script (pre-filled) ──────────────────
const BASE_SCRIPT = `from reportlab.lib.pagesizes import letter
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import black
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus.frames import Frame
from reportlab.platypus.doctemplate import PageTemplate
from pathlib import Path

FONTS_DIR = Path(__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont('Carlito', str(FONTS_DIR / 'Carlito-Regular.ttf')))
pdfmetrics.registerFont(TTFont('Carlito-Bold', str(FONTS_DIR / 'Carlito-Bold.ttf')))
pdfmetrics.registerFont(TTFont('Carlito-Italic', str(FONTS_DIR / 'Carlito-Italic.ttf')))
pdfmetrics.registerFont(TTFont('Carlito-BoldItalic', str(FONTS_DIR / 'Carlito-BoldItalic.ttf')))
pdfmetrics.registerFontFamily('Carlito', normal='Carlito', bold='Carlito-Bold', italic='Carlito-Italic', boldItalic='Carlito-BoldItalic')

PAGE_WIDTH, PAGE_HEIGHT = letter
LM = 30; RM = PAGE_WIDTH - 582; TM = 18; BM = 12
CW = PAGE_WIDTH - LM - RM

ns  = ParagraphStyle("N", fontName="Carlito-Bold", fontSize=13, alignment=TA_CENTER, spaceAfter=0, leading=14)
cs_ = ParagraphStyle("C", fontName="Carlito", fontSize=9, alignment=TA_CENTER, spaceAfter=0, leading=11)
ss  = ParagraphStyle("S", fontName="Carlito-Bold", fontSize=10, alignment=TA_LEFT, spaceBefore=0, spaceAfter=0, leading=11)
bst = ParagraphStyle("B", fontName="Carlito", fontSize=9, alignment=TA_JUSTIFY, leading=10.8, leftIndent=10, firstLineIndent=0, spaceAfter=0.5)
kst = ParagraphStyle("K", fontName="Carlito", fontSize=9, alignment=TA_LEFT, leading=11, spaceAfter=0)
ust = ParagraphStyle("U", fontName="Carlito", fontSize=9, alignment=TA_JUSTIFY, leading=10.8, spaceAfter=0)

story = []
# ... (full script — backend uses structured data, this is for reference)
`;

// ── DOM References ────────────────────────────────────
const form = document.getElementById('tailor-form');
const generateBtn = document.getElementById('generate-btn');
const scriptBtn = document.getElementById('script-btn');
const btnLabel = document.getElementById('btn-label');
const baseScriptTA = document.getElementById('base-script');
const resetScriptBtn = document.getElementById('reset-script-btn');
const resultsPanel = document.getElementById('results-panel');
const errorPanel = document.getElementById('error-panel');
const errorBody = document.getElementById('error-body');
const errorClose = document.getElementById('error-close');
const changesSummary = document.getElementById('changes-summary');
const loadingOverlay = document.getElementById('loading-overlay');
const scriptModal = document.getElementById('script-modal');
const scriptOutput = document.getElementById('script-output');
const changesModal = document.getElementById('changes-modal-summary');
const copyScriptBtn = document.getElementById('copy-script-btn');
const dlScriptBtn = document.getElementById('dl-script-btn');
const modalClose = document.getElementById('modal-close');

// ── Tabs ──────────────────────────────────────────────
document.getElementById('jd-tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('.tab');
    if (!tab) return;
    const target = tab.dataset.tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`tab-${target}`).classList.add('active');
});

// ── Pre-fill base script ──────────────────────────────
baseScriptTA.value = BASE_SCRIPT.trim();
resetScriptBtn.addEventListener('click', () => {
    baseScriptTA.value = BASE_SCRIPT.trim();
});

// ── Loading Steps ─────────────────────────────────────
const STEPS = ['step-1', 'step-2', 'step-3', 'step-4'];
let stepTimer = null;

function showLoading() {
    loadingOverlay.classList.remove('hidden');
    STEPS.forEach(s => {
        const el = document.getElementById(s);
        el.classList.remove('active', 'done');
    });
    let idx = 0;
    document.getElementById(STEPS[0]).classList.add('active');
    stepTimer = setInterval(() => {
        if (idx < STEPS.length - 1) {
            document.getElementById(STEPS[idx]).classList.remove('active');
            document.getElementById(STEPS[idx]).classList.add('done');
            idx++;
            document.getElementById(STEPS[idx]).classList.add('active');
        }
    }, 4000);
}

function hideLoading() {
    clearInterval(stepTimer);
    loadingOverlay.classList.add('hidden');
    STEPS.forEach(s => document.getElementById(s).classList.remove('active', 'done'));
}

// ── Collect Form Data ─────────────────────────────────
function collectFormData() {
    const activeTab = document.querySelector('.tab.active')?.dataset.tab;
    return {
        base_script: form['base_script'].value.trim(),
        jd_api_endpoint: activeTab === 'api' ? (form['jd_api_endpoint']?.value?.trim() || '') : '',
        jd_api_key: activeTab === 'api' ? (form['jd_api_key']?.value?.trim() || '') : '',
        job_id: activeTab === 'api' ? (form['job_id']?.value?.trim() || '') : '',
        jd_raw: activeTab === 'paste' ? (form['jd_raw']?.value?.trim() || '') : '',
        candidate_name: form['candidate_name']?.value?.trim() || 'BHARATH KUMAR RAJESH',
        target_role: form['target_role']?.value?.trim() || '',
        company_name: form['company_name']?.value?.trim() || '',
    };
}

// ── Validate ─────────────────────────────────────────
function validate(data) {
    const activeTab = document.querySelector('.tab.active')?.dataset.tab;
    if (activeTab === 'paste' && !data.jd_raw) {
        return 'Please paste a job description.';
    }
    if (activeTab === 'api' && !data.job_id) {
        return 'Please enter a Job ID or Job URL.';
    }
    return null;
}

// ── Show/Hide UI ──────────────────────────────────────
function showResults(summary, pages) {
    resultsPanel.classList.remove('hidden');
    changesSummary.textContent = summary || 'Resume tailored successfully using Claude AI.';
    document.getElementById('page-badge').textContent = `📄 ${pages} Page${pages !== 1 ? 's' : ''} · ATS Ready`;
    resultsPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function showError(msg) {
    errorPanel.classList.remove('hidden');
    errorBody.textContent = msg;
    errorPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideMessages() {
    resultsPanel.classList.add('hidden');
    errorPanel.classList.add('hidden');
}

errorClose.addEventListener('click', () => errorPanel.classList.add('hidden'));

// ── Generate PDF ──────────────────────────────────────
form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = collectFormData();
    const err = validate(data);
    if (err) { hideMessages(); showError(err); return; }

    hideMessages();
    showLoading();
    generateBtn.disabled = true;
    scriptBtn.disabled = true;
    btnLabel.textContent = 'Tailoring…';

    try {
        const resp = await fetch('/tailor', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });

        if (!resp.ok) {
            let detail = `Server error ${resp.status}`;
            try { const j = await resp.json(); detail = j.detail || detail; } catch (_) { }
            throw new Error(detail);
        }

        const pages = parseInt(resp.headers.get('X-Pages') || '1', 10);
        const changes = decodeURIComponent(resp.headers.get('X-Changes-Summary') || '');

        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'Bharath_Kumar_Tailored_Resume.pdf';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showResults(changes, pages);

    } catch (err) {
        showError(err.message || 'An unexpected error occurred. Check the server logs.');
    } finally {
        hideLoading();
        generateBtn.disabled = false;
        scriptBtn.disabled = false;
        btnLabel.textContent = 'Generate Tailored PDF';
    }
});

// ── Get Script ────────────────────────────────────────
scriptBtn.addEventListener('click', async () => {
    const data = collectFormData();
    const err = validate(data);
    if (err) { hideMessages(); showError(err); return; }

    hideMessages();
    showLoading();
    generateBtn.disabled = true;
    scriptBtn.disabled = true;

    try {
        const resp = await fetch('/script', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });

        if (!resp.ok) {
            let detail = `Server error ${resp.status}`;
            try { const j = await resp.json(); detail = j.detail || detail; } catch (_) { }
            throw new Error(detail);
        }

        const json = await resp.json();
        scriptOutput.value = json.script || '';
        changesModal.textContent = json.changes_summary || '';
        scriptModal.classList.remove('hidden');

    } catch (err) {
        showError(err.message || 'Script generation failed. Check the server logs.');
    } finally {
        hideLoading();
        generateBtn.disabled = false;
        scriptBtn.disabled = false;
    }
});

// ── Modal Controls ─────────────────────────────────────
modalClose.addEventListener('click', () => scriptModal.classList.add('hidden'));
scriptModal.addEventListener('click', (e) => {
    if (e.target === scriptModal) scriptModal.classList.add('hidden');
});

copyScriptBtn.addEventListener('click', async () => {
    try {
        await navigator.clipboard.writeText(scriptOutput.value);
        copyScriptBtn.textContent = '✓ Copied!';
        setTimeout(() => copyScriptBtn.textContent = 'Copy', 2000);
    } catch (_) {
        scriptOutput.select();
        document.execCommand('copy');
    }
});

dlScriptBtn.addEventListener('click', () => {
    const blob = new Blob([scriptOutput.value], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'Bharath_Kumar_Tailored_Resume.py';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
});

// ── Keyboard Shortcut ─────────────────────────────────
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') scriptModal.classList.add('hidden');
});
