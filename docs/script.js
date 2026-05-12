// Global state
let definitions = {};
let weights = [];
let descriptorTypes = {};
let descriptorScores = {};
let keywordsList = {};
let templates = { outpatient: '', discharge: '' };
let currentDescriptor = null;
let thresholdRowCounter = 0;
let additionalPrompts = {};
let typeAHard = [];
let currentEditingTemplate = 'outpatient';

// Helper function to safely get element
function safeGetElement(id) {
    return document.getElementById(id);
}

// Helper to escape HTML
function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>]/g, function(m) {
        if (m === '&') return '&amp;';
        if (m === '<') return '&lt;';
        if (m === '>') return '&gt;';
        return m;
    });
}

// Parse structured text format back into structured data
function parseStructuredFromText(rulesText) {
    const result = {
        qualitative: '',
        thresholds: [],
        exclusions: '',
        notes: ''
    };
    
    const quantMatch = rulesText.match(/Quantitative thresholds:\n([\s\S]*?)(?=\n\nQualitative value handling:|\n\nExclusions:|\n\nNotes:|$)/i);
    if (quantMatch) {
        const lines = quantMatch[1].split('\n');
        lines.forEach(line => {
            const match = line.match(/^-\s*(.*?):\s*([<\<=>=>]+)\s*([\d.]+)\s*(.*)$/);
            if (match) {
                result.thresholds.push({
                    date_range: match[1].trim(),
                    condition: match[2].trim(),
                    value: match[3].trim(),
                    units: match[4].trim()
                });
            }
        });
    }
    
    const qualMatch = rulesText.match(/Qualitative value handling:\n([\s\S]*?)(?=\n\nExclusions:|\n\nNotes:|$)/i);
    if (qualMatch) result.qualitative = qualMatch[1].trim();
    
    const exclMatch = rulesText.match(/Exclusions:\n([\s\S]*?)(?=\n\nNotes:|$)/i);
    if (exclMatch) result.exclusions = exclMatch[1].trim();
    
    const notesMatch = rulesText.match(/Notes:\n([\s\S]*?)$/i);
    if (notesMatch) result.notes = notesMatch[1].trim();
    
    return result;
}

// Build rules text from structured data
function buildRulesTextFromStructured(descriptorData, isTypeB) {
    if (!isTypeB) {
        if (descriptorData.criteria) {
            let rulesText = `Diagnostic criteria:\n${descriptorData.criteria}`;
            if (descriptorData.exclusions) rulesText += `\n\nExclusions:\n${descriptorData.exclusions}`;
            if (descriptorData.notes) rulesText += `\n\nNotes:\n${descriptorData.notes}`;
            return rulesText;
        }
        return '';
    }
    
    let rulesText = '';
    if (descriptorData.thresholds && descriptorData.thresholds.length > 0) {
        rulesText += `Quantitative thresholds:\n`;
        descriptorData.thresholds.forEach(t => {
            rulesText += `- ${t.date_range}: ${t.condition} ${t.value} ${t.units}\n`;
        });
        rulesText += `\n`;
    }
    if (descriptorData.qualitative) rulesText += `Qualitative value handling:\n${descriptorData.qualitative}\n\n`;
    if (descriptorData.exclusions) rulesText += `Exclusions:\n${descriptorData.exclusions}\n\n`;
    if (descriptorData.notes) rulesText += `Notes:\n${descriptorData.notes}`;
    
    return rulesText;
}

// Parse rules text into components
function parseRulesText(rulesText) {
    const result = { criteria: '', exclusions: '', notes: '' };
    const criteriaMatch = rulesText.match(/Diagnostic criteria:\s*([\s\S]*?)(?=\n\nExclusions:|\n\nNotes:|$)/i);
    result.criteria = criteriaMatch ? criteriaMatch[1].trim() : '';
    const exclusionsMatch = rulesText.match(/Exclusions:\s*([\s\S]*?)(?=\n\nNotes:|$)/i);
    result.exclusions = exclusionsMatch ? exclusionsMatch[1].trim() : '';
    const notesMatch = rulesText.match(/Notes:\s*([\s\S]*?)$/i);
    result.notes = notesMatch ? notesMatch[1].trim() : '';
    return result;
}

// Load prompts from JSON
async function loadPrompts() {
    try {
        const response = await fetch('prompts.json');
        const data = await response.json();
        
        definitions = data.definitions;
        weights = data.weights;
        descriptorTypes = data.descriptor_types;
        descriptorScores = data.scores;
        keywordsList = data.keywords_list;
        templates = data.templates;
        additionalPrompts = data.additional_prompts || {};
        typeAHard = data.type_a_hard || [];

        renderDescriptorList();
        
        if (weights.length > 0) {
            selectDescriptor(weights[0][0], false);
        }
    } catch (error) {
        console.error('Error:', error);
        showToast('Error loading prompts.json', 'error');
    }
}

function renderDescriptorList() {
    const container = document.getElementById('descriptorList');
    if (!container) return;
    
    const searchTerm = document.getElementById('descriptorSearch')?.value.toLowerCase() || '';
    const descriptors = weights.filter(w => w[0].toLowerCase().includes(searchTerm)).map(w => w[0]);
    
    container.innerHTML = descriptors.map(desc => `
        <div class="descriptor-item ${descriptorTypes[desc] === 'TYPE_A' ? 'type-a' : 'type-b'} ${currentDescriptor === desc ? 'active' : ''}" data-descriptor="${desc}">
            <div class="descriptor-header">
                <strong>${formatName(desc)}</strong>
                <span class="descriptor-meta">Weight: ${descriptorScores[desc]} | ${descriptorTypes[desc] === 'TYPE_A' ? 'Clinical' : 'Lab'}</span>
            </div>
        </div>
    `).join('');
    
    document.querySelectorAll('.descriptor-item').forEach(el => {
        el.addEventListener('click', () => selectDescriptor(el.dataset.descriptor, true));
    });
}

function formatName(name) {
    return name.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

function buildKeywordsText(desc) {
    const keywords = keywordsList[desc] || {};
    let keywordsText = '';
    
    if (descriptorTypes[desc] === 'TYPE_A') {
        if (keywords.diagnostic) {
            keywordsText += 'List of diagnostic keywords:\n' + keywords.diagnostic;
        } else {
            keywordsText += 'No diagnostic keywords.';
        }
        if (keywords.symptoms) keywordsText += '\n\nList of symptoms/signs keywords:\n' + keywords.symptoms;
        if (keywords.paraclinical) keywordsText += '\n\nList of paraclinical keywords:\n' + keywords.paraclinical;
    } else {
        if (keywords.keywords) {
            keywordsText += 'List of keywords:\n' + keywords.keywords;
        } else {
            keywordsText += 'No keywords defined.';
        }
    }
    return keywordsText;
}

// Auto-scroll to descriptor title card with offset for navbar
function scrollToDescriptorEditor() {
    const titleCard = document.querySelector('#descriptorEditor .main-card-header');
    if (!titleCard) return;
    
    const navbar = document.querySelector('.navbar');
    const navbarHeight = navbar ? navbar.offsetHeight : 64;
    
    const elementPosition = titleCard.getBoundingClientRect().top;
    const offsetPosition = elementPosition + window.pageYOffset - navbarHeight - 16;
    
    window.scrollTo({
        top: offsetPosition,
        behavior: 'smooth'
    });
}

// Add threshold row function
function addThresholdRow(dateRange = '', condition = '<', value = '', units = '') {
    const container = safeGetElement('thresholdRows');
    if (!container) return;
    if (container.children.length === 0) container.innerHTML = '';
    
    const row = document.createElement('div');
    row.className = 'threshold-row';
    row.innerHTML = `
        <div class="threshold-date">
            <input type="text" placeholder="e.g., Always, After 2020-01-01, Before 2018-12-24, C3, C4" value="${escapeHtml(dateRange)}">
        </div>
        <div class="threshold-value-row">
            <div class="threshold-condition">
                <select>
                    <option value="<" ${condition === '<' ? 'selected' : ''}>&lt;</option>
                    <option value="<=" ${condition === '<=' ? 'selected' : ''}>&lt;=</option>
                    <option value=">" ${condition === '>' ? 'selected' : ''}>&gt;</option>
                    <option value=">=" ${condition === '>=' ? 'selected' : ''}>&gt;=</option>
                    <option value="=" ${condition === '=' ? 'selected' : ''}>=</option>
                </select>
            </div>
            <div class="threshold-value">
                <input type="text" placeholder="Value" value="${escapeHtml(value)}">
            </div>
            <div class="threshold-units">
                <input type="text" placeholder="Units" value="${escapeHtml(units)}">
            </div>
        </div>
        <div class="threshold-remove">
            <button class="remove-row" onclick="this.closest('.threshold-row').remove(); updateRawFromStructured();">✕</button>
        </div>
    `;
    container.appendChild(row);
    
    row.querySelectorAll('input, select').forEach(input => {
        input.addEventListener('input', updateRawFromStructured);
    });
}

function selectDescriptor(desc, fromUserClick = false) {
    currentDescriptor = desc;
    renderDescriptorList();
    
    const editorElement = safeGetElement('descriptorEditor');
    if (editorElement) editorElement.style.display = 'block';
    
    const titleElement = safeGetElement('currentDescriptorTitle');
    if (titleElement) {
        titleElement.innerHTML = `${formatName(desc)} <span style="font-size:0.7rem; opacity:0.7;">Weight: ${descriptorScores[desc]}</span>`;
    }
    
    const isTypeB = descriptorTypes[desc] === 'TYPE_B';
    const descriptorData = definitions[desc];
    let rulesText = '';
    let structuredData = null;
    
    if (typeof descriptorData === 'string') {
        rulesText = descriptorData;
        if (isTypeB && (rulesText.includes('Quantitative thresholds:') || rulesText.includes('Qualitative value handling:'))) {
            structuredData = parseStructuredFromText(rulesText);
        }
    } else if (typeof descriptorData === 'object') {
        structuredData = descriptorData;
        rulesText = buildRulesTextFromStructured(descriptorData, isTypeB);
    }
    
    const parsed = parseRulesText(rulesText);
    const typeBEditor = safeGetElement('typeBEditor');
    const typeAEditor = safeGetElement('typeAEditor');
    
    if (isTypeB) {
        if (typeBEditor) typeBEditor.style.display = 'block';
        if (typeAEditor) typeAEditor.style.display = 'none';
        
        const thresholdRowsContainer = safeGetElement('thresholdRows');
        if (thresholdRowsContainer) {
            thresholdRowsContainer.innerHTML = '';
            const thresholds = structuredData?.thresholds || [];
            thresholds.forEach(t => {
                addThresholdRow(t.date_range || '', t.condition || '<', t.value || '', t.units || '');
            });
        }
        
        const qualitativeRules = safeGetElement('qualitativeRules');
        if (qualitativeRules) qualitativeRules.value = structuredData?.qualitative || '';
        
        const typeBKeywords = safeGetElement('typeBKeywords');
        if (typeBKeywords) {
            const keywords = keywordsList[desc] || {};
            typeBKeywords.value = keywords.keywords || '';
        }
        
        const exclusionCriteria = safeGetElement('exclusionCriteria');
        if (exclusionCriteria) exclusionCriteria.value = structuredData?.exclusions || '';
        
        const labNotes = safeGetElement('labNotes');
        if (labNotes) labNotes.value = structuredData?.notes || '';
    } else {
        if (typeBEditor) typeBEditor.style.display = 'none';
        if (typeAEditor) typeAEditor.style.display = 'block';
        
        const diagnosticCriteria = safeGetElement('diagnosticCriteria');
        const clinicalExclusions = safeGetElement('clinicalExclusions');
        const clinicalNotes = safeGetElement('clinicalNotes');
        const keywords = safeGetElement('keywords');
        
        if (diagnosticCriteria) diagnosticCriteria.value = parsed.criteria;
        if (clinicalExclusions) clinicalExclusions.value = parsed.exclusions;
        if (clinicalNotes) clinicalNotes.value = parsed.notes;
        if (keywords) keywords.value = buildKeywordsText(currentDescriptor).replace(/\n/g, '\n');
    }
    
    const rulesEditor = safeGetElement('rulesEditor');
    if (rulesEditor) rulesEditor.value = rulesText;
    generateOutput();
    
    if (fromUserClick) {
        scrollToDescriptorEditor();
    }
}

function updateRawFromStructured() {
    if (!currentDescriptor) return;
    
    const isTypeB = descriptorTypes[currentDescriptor] === 'TYPE_B';
    let newRules = '';
    
    if (isTypeB) {
        const qualitativeRules = safeGetElement('qualitativeRules');
        const exclusionCriteria = safeGetElement('exclusionCriteria');
        const labNotes = safeGetElement('labNotes');
        const typeBKeywords = safeGetElement('typeBKeywords');
        
        const qualitative = qualitativeRules ? qualitativeRules.value : '';
        const exclusions = exclusionCriteria ? exclusionCriteria.value : '';
        const notes = labNotes ? labNotes.value : '';
        const keywords = typeBKeywords ? typeBKeywords.value : '';
        
        const rows = document.querySelectorAll('.threshold-row');
        if (rows.length > 0) {
            newRules += `Quantitative thresholds:\n`;
            rows.forEach(row => {
                const dateInput = row.querySelector('.threshold-date input');
                const valueInput = row.querySelector('.threshold-value input');
                const unitsInput = row.querySelector('.threshold-units input');
                const conditionSelect = row.querySelector('.threshold-condition select');
                
                const dateRange = dateInput ? dateInput.value : '';
                const threshold = valueInput ? valueInput.value : '';
                const units = unitsInput ? unitsInput.value : '';
                const condition = conditionSelect ? conditionSelect.value : '<';
                
                if (threshold) {
                    newRules += `- ${dateRange || 'Default'}: ${condition} ${threshold} ${units}\n`;
                }
            });
            newRules += `\n`;
        }
        
        if (qualitative) newRules += `Qualitative value handling:\n${qualitative}\n\n`;
        if (exclusions) newRules += `Exclusions:\n${exclusions}\n\n`;
        if (notes) newRules += `Notes:\n${notes}`;
        
        if (keywords && currentDescriptor) {
            if (!keywordsList[currentDescriptor]) keywordsList[currentDescriptor] = {};
            keywordsList[currentDescriptor].keywords = keywords;
        }
    } else {
        const diagnosticCriteria = safeGetElement('diagnosticCriteria');
        const clinicalExclusions = safeGetElement('clinicalExclusions');
        const clinicalNotes = safeGetElement('clinicalNotes');
        
        const criteria = diagnosticCriteria ? diagnosticCriteria.value : '';
        const exclusions = clinicalExclusions ? clinicalExclusions.value : '';
        const notes = clinicalNotes ? clinicalNotes.value : '';
        
        newRules = `Diagnostic criteria:\n${criteria}`;
        if (exclusions) newRules += `\n\nExclusions:\n${exclusions}`;
        if (notes) newRules += `\n\nNotes:\n${notes}`;
    }
    
    const rulesEditor = safeGetElement('rulesEditor');
    if (rulesEditor) rulesEditor.value = newRules;
    generateOutput();
}

function resetToDefault() {
    if (!currentDescriptor) return;
    const descriptorData = definitions[currentDescriptor];
    const isTypeB = descriptorTypes[currentDescriptor] === 'TYPE_B';
    let defaultRules = '';
    
    if (typeof descriptorData === 'string') {
        defaultRules = descriptorData;
    } else if (typeof descriptorData === 'object') {
        defaultRules = buildRulesTextFromStructured(descriptorData, isTypeB);
    }
    
    const rulesEditor = safeGetElement('rulesEditor');
    if (rulesEditor) rulesEditor.value = defaultRules;
    selectDescriptor(currentDescriptor, false);
    generateOutput();
    showToast(`Reset ${formatName(currentDescriptor)} to default`, 'success');
}

function formatDate(dateInput) {
    if (!dateInput) return '[DATE NEEDED]';
    const parts = dateInput.split('-');
    if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
    return dateInput;
}

function generateOutput() {
    if (!currentDescriptor) return;
    
    const noteTypeSelect = safeGetElement('noteTypeSelect');
    const outputModeSelect = safeGetElement('outputModeSelect');
    const rulesEditor = safeGetElement('rulesEditor');
    
    const noteType = noteTypeSelect ? noteTypeSelect.value : 'outpatient';
    const outputMode = outputModeSelect ? outputModeSelect.value : 'full';
    const customRules = rulesEditor ? rulesEditor.value : '';
    
    const output = outputMode === 'full' 
        ? buildFullPrompt(noteType, currentDescriptor, customRules)
        : buildDescriptorOnly(currentDescriptor, customRules);
    
    const outputContent = safeGetElement('outputContent');
    if (outputContent) outputContent.textContent = output;
}

function buildFullPrompt(noteType, descriptor, customRules) {
    const clinicalNote = safeGetElement('clinicalNote');
    const assessmentDate = safeGetElement('assessmentDate');
    
    let clinicalNoteText = clinicalNote ? clinicalNote.value : '';
    if (!clinicalNoteText || clinicalNoteText.trim() === '') {
        clinicalNoteText = '[INSERT CLINICAL NOTE HERE]';
    }
    
    let dateString = '';
    let template = '';
    
    if (noteType === 'outpatient') {
        dateString = formatDate(assessmentDate ? assessmentDate.value : '');
        template = templates.outpatient;
    } else {
        dateString = '[ADMISSION DATE FROM NOTE]';
        template = templates.discharge;
    }
    
    const keywordsText = buildKeywordsText(descriptor);
    const isHardDescriptor = typeAHard.includes(descriptor);
    
    let intentionToTreatText = '';
    let natureOfIntentionToTreatText = '';
    let npsleTipsText = '';
    
    if (isHardDescriptor) {
        intentionToTreatText = additionalPrompts.intention_to_treat_prompt || '';
        natureOfIntentionToTreatText = additionalPrompts.nature_of_intention_to_treat_prompt || '';
        npsleTipsText = additionalPrompts.npsle_tips || '';
    } else {
        intentionToTreatText = additionalPrompts.treatment_response_prompt || '';
        intentionToTreatText = intentionToTreatText.replace(/\{\{\s*descriptor\s*\}\}/g, descriptor);
        natureOfIntentionToTreatText = '';
        npsleTipsText = '';
    }
    
    let result = template
        .replace(/\{\{\s*date\s*\}\}/g, dateString)
        .replace(/\{\{\s*descriptor\s*\}\}/g, descriptor)
        .replace(/\{\{\s*information\s*\}\}/g, customRules)
        .replace(/\{\{\s*clinical_note\s*\}\}/g, clinicalNoteText)
        .replace(/\{\{\s*keywords\s*\}\}/g, keywordsText)
        .replace(/\{\{\s*treatment_logic\s*\}\}/g, intentionToTreatText)
        .replace(/\{\{\s*nature_of_intention_to_treat\s*\}\}/g, natureOfIntentionToTreatText)
        .replace(/\{\{\s*npsle_tips\s*\}\}/g, npsleTipsText);
    
    return result.replace(/\{\{\s*\w+\s*\}\}/g, '');
}

function buildDescriptorOnly(descriptor, customRules) {
    return `# Descriptor: ${descriptor}
# SLEDAI-2K Weight: ${descriptorScores[descriptor]}
# Type: ${descriptorTypes[descriptor] === 'TYPE_A' ? 'Clinical' : 'Laboratory'}

'${descriptor}': '''${customRules}
''',`;
}

function updateDateFieldVisibility() {
    const noteTypeSelect = safeGetElement('noteTypeSelect');
    const dateSection = document.querySelector('.date-section');
    const dateLabel = safeGetElement('dateLabel');
    const helpText = safeGetElement('dateHelpText');
    const noteType = noteTypeSelect ? noteTypeSelect.value : 'outpatient';
    
    if (noteType === 'outpatient') {
        if (dateSection) dateSection.classList.remove('hidden');
        if (dateLabel) dateLabel.innerHTML = '📅 Assessment Date (Visit Date)';
        if (helpText) helpText.textContent = 'Select the visit date for outpatient notes';
    } else {
        if (dateSection) dateSection.classList.add('hidden');
    }
    generateOutput();
}

function toggleClinicalNoteVisibility() {
    const outputModeSelect = safeGetElement('outputModeSelect');
    const clinicalNoteCard = safeGetElement('clinicalNoteCard');
    const outputMode = outputModeSelect ? outputModeSelect.value : 'full';
    
    if (clinicalNoteCard) {
        clinicalNoteCard.style.display = outputMode === 'descriptor' ? 'none' : 'block';
    }
}

function toggleConfig() {
    const card = document.querySelector('.collapsible');
    if (card) card.classList.toggle('collapsed');
}

function copyOutput() {
    const outputContent = safeGetElement('outputContent');
    const content = outputContent ? outputContent.textContent : '';
    navigator.clipboard.writeText(content);
    showToast('Copied to clipboard!', 'success');
}

// Template Modal Functions
function openTemplateModal() {
    const modal = safeGetElement('templateModal');
    if (!modal) return;
    
    const templateEditor = safeGetElement('templateEditor');
    if (templateEditor) {
        templateEditor.value = templates[currentEditingTemplate === 'outpatient' ? 'outpatient' : 'discharge'] || '';
    }
    
    modal.style.display = 'flex';
}

function closeTemplateModal() {
    const modal = safeGetElement('templateModal');
    if (modal) modal.style.display = 'none';
}

function switchTemplateTab(templateType) {
    currentEditingTemplate = templateType;
    
    const tabs = document.querySelectorAll('.modal-tab');
    tabs.forEach(tab => {
        if (tab.dataset.templateType === templateType) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });
    
    const editor = safeGetElement('templateEditor');
    if (editor) {
        editor.value = templates[templateType] || '';
    }
}

function saveTemplate() {
    const templateEditor = safeGetElement('templateEditor');
    if (templateEditor) {
        if (currentEditingTemplate === 'outpatient') {
            templates.outpatient = templateEditor.value;
        } else if (currentEditingTemplate === 'discharge') {
            templates.discharge = templateEditor.value;
        }
    }
    
    showToast(`Saved ${currentEditingTemplate === 'outpatient' ? 'Outpatient' : 'Discharge'} template`, 'success');
    if (currentDescriptor) generateOutput();
    closeTemplateModal();
}

// Treatment Logic Modal Functions
function openTreatmentLogicModal() {
    const modal = safeGetElement('treatmentLogicModal');
    if (!modal) return;
    
    const treatmentResponse = safeGetElement('treatmentResponseEditor');
    const intentionToTreat = safeGetElement('intentionToTreatEditor');
    
    if (treatmentResponse) treatmentResponse.value = additionalPrompts.treatment_response_prompt || '';
    if (intentionToTreat) intentionToTreat.value = additionalPrompts.intention_to_treat_prompt || '';
    
    modal.style.display = 'flex';
}

function closeTreatmentLogicModal() {
    const modal = safeGetElement('treatmentLogicModal');
    if (modal) modal.style.display = 'none';
}

function saveTreatmentLogicPrompt() {
    const treatmentResponse = safeGetElement('treatmentResponseEditor');
    const intentionToTreat = safeGetElement('intentionToTreatEditor');
    
    if (treatmentResponse) additionalPrompts.treatment_response_prompt = treatmentResponse.value;
    if (intentionToTreat) additionalPrompts.intention_to_treat_prompt = intentionToTreat.value;
    
    showToast('Both treatment prompts saved successfully!', 'success');
    if (currentDescriptor) generateOutput();
    closeTreatmentLogicModal();
}

// NPSLE Modal Functions
function openNpsleModal() {
    const modal = safeGetElement('npsleModal');
    const editor = safeGetElement('npsleModalEditor');
    if (!modal) return;
    
    if (editor) editor.value = additionalPrompts.npsle_tips || '';
    modal.style.display = 'flex';
}

function closeNpsleModal() {
    const modal = safeGetElement('npsleModal');
    if (modal) modal.style.display = 'none';
}

function saveNpslePrompt() {
    const editor = safeGetElement('npsleModalEditor');
    if (editor) additionalPrompts.npsle_tips = editor.value;
    showToast('NPSLE Tips saved', 'success');
    if (currentDescriptor) generateOutput();
    closeNpsleModal();
}

// Add click handlers to legend placeholders
function setupLegendClickHandlers() {
    const legendCodes = document.querySelectorAll('.legend-list code');
    legendCodes.forEach(code => {
        code.addEventListener('click', (e) => {
            e.stopPropagation();
            const placeholderText = code.textContent;
            if (placeholderText === '{{ treatment_logic }}') {
                openTreatmentLogicModal();
            } else if (placeholderText === '{{ npsle_tips }}') {
                openNpsleModal();
            }
        });
    });
}

// Setup click detection on template editor
function setupTemplateEditorClickDetection() {
    const editor = safeGetElement('templateEditor');
    if (!editor) return;
    
    editor.addEventListener('click', function(e) {
        const cursorPos = this.selectionStart;
        const text = this.value;
        const placeholderRegex = /\{\{\s*([\w_]+)\s*\}\}/g;
        let match;
        
        while ((match = placeholderRegex.exec(text)) !== null) {
            const start = match.index;
            const end = start + match[0].length;
            if (cursorPos >= start && cursorPos <= end) {
                const placeholderName = match[1];
                if (placeholderName === 'treatment_logic') {
                    openTreatmentLogicModal();
                } else if (placeholderName === 'npsle_tips') {
                    openNpsleModal();
                }
                break;
            }
        }
    });
}

function initTemplateModal() {
    const editBtn = safeGetElement('editTemplateBtn');
    if (editBtn) editBtn.addEventListener('click', openTemplateModal);
    
    const saveBtn = safeGetElement('saveTemplateBtn');
    if (saveBtn) saveBtn.addEventListener('click', saveTemplate);
    
    const saveTreatmentLogicBtn = safeGetElement('saveTreatmentLogicBtn');
    if (saveTreatmentLogicBtn) saveTreatmentLogicBtn.addEventListener('click', saveTreatmentLogicPrompt);
    
    const saveNpsleBtn = safeGetElement('saveNpsleBtn');
    if (saveNpsleBtn) saveNpsleBtn.addEventListener('click', saveNpslePrompt);
    
    const tabs = document.querySelectorAll('.modal-tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => switchTemplateTab(tab.dataset.templateType));
    });
    
    setupTemplateEditorClickDetection();
    setupLegendClickHandlers();
    
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeTemplateModal();
            closeTreatmentLogicModal();
            closeNpsleModal();
        }
    });
    
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', () => {
            closeTemplateModal();
            closeTreatmentLogicModal();
            closeNpsleModal();
        });
    });
}

function showToast(message, type) {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2000);
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    loadPrompts();
    
    const noteTypeSelect = safeGetElement('noteTypeSelect');
    const outputModeSelect = safeGetElement('outputModeSelect');
    const descriptorSearch = safeGetElement('descriptorSearch');
    const resetDescriptorBtn = safeGetElement('resetDescriptorBtn');
    const copyOutputBtn = safeGetElement('copyOutputBtn');
    const clearNoteBtn = safeGetElement('clearNoteBtn');
    const toggleRawEditor = safeGetElement('toggleRawEditor');
    const clinicalNote = safeGetElement('clinicalNote');
    const assessmentDate = safeGetElement('assessmentDate');
    const rulesEditor = safeGetElement('rulesEditor');
    const addThresholdBtn = safeGetElement('addThresholdRow');
    
    if (noteTypeSelect) noteTypeSelect.addEventListener('change', () => { updateDateFieldVisibility(); generateOutput(); });
    if (outputModeSelect) outputModeSelect.addEventListener('change', () => { toggleClinicalNoteVisibility(); generateOutput(); });
    if (descriptorSearch) descriptorSearch.addEventListener('input', renderDescriptorList);
    if (resetDescriptorBtn) resetDescriptorBtn.addEventListener('click', resetToDefault);
    if (copyOutputBtn) copyOutputBtn.addEventListener('click', copyOutput);
    if (clearNoteBtn) clearNoteBtn.addEventListener('click', () => { if (clinicalNote) clinicalNote.value = ''; generateOutput(); });
    if (toggleRawEditor) toggleRawEditor.addEventListener('click', () => {
        const rawEditor = safeGetElement('rawEditor');
        if (rawEditor) {
            rawEditor.style.display = rawEditor.style.display === 'block' ? 'none' : 'block';
        }
    });
    if (addThresholdBtn) addThresholdBtn.addEventListener('click', () => addThresholdRow());
    if (clinicalNote) clinicalNote.addEventListener('input', generateOutput);
    if (assessmentDate) assessmentDate.addEventListener('input', generateOutput);
    if (rulesEditor) rulesEditor.addEventListener('input', generateOutput);
    
    const typeAFields = ['diagnosticCriteria', 'clinicalExclusions', 'clinicalNotes'];
    typeAFields.forEach(field => {
        const el = safeGetElement(field);
        if (el) el.addEventListener('input', updateRawFromStructured);
    });
    
    const typeBFields = ['qualitativeRules', 'exclusionCriteria', 'labNotes', 'typeBKeywords'];
    typeBFields.forEach(field => {
        const el = safeGetElement(field);
        if (el) el.addEventListener('input', updateRawFromStructured);
    });
    
    const keywords = safeGetElement('keywords');
    if (keywords) keywords.addEventListener('input', updateRawFromStructured);
    
    const thresholdRowsContainer = safeGetElement('thresholdRows');
    if (thresholdRowsContainer) {
        thresholdRowsContainer.addEventListener('input', updateRawFromStructured);
        thresholdRowsContainer.addEventListener('click', (e) => {
            if (e.target.classList.contains('remove-row')) setTimeout(updateRawFromStructured, 50);
        });
    }
    
    initTemplateModal();
    updateDateFieldVisibility();
    toggleClinicalNoteVisibility();
});