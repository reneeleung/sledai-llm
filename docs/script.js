// Global state
let definitions = {};
let weights = [];
let descriptorTypes = {};
let descriptorScores = {};
let keywordsList = {};
let originalKeywordsList = {};
let editableTemplates = {};
let nonEditableTemplates = {};
let additionalPrompts = {};
let typeAHard = [];
let currentDescriptor = null;
let thresholdRowCounter = 0;
let customRules = {};
let currentClinicalNote = '';
let currentAssessmentDate = '';

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

// Get current note type from DOM
function getCurrentNoteType() {
    const noteTypeSelect = safeGetElement('noteTypeSelect');
    return noteTypeSelect ? noteTypeSelect.value : 'outpatient';
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
            rulesText += `- ${t.date_range} ${t.condition} ${t.value} ${t.units}\n`;
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
        originalKeywordsList = JSON.parse(JSON.stringify(keywordsList));

        editableTemplates = data.editable_templates || {};
        nonEditableTemplates = data.non_editable_templates || {};
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
    
    window.scrollTo({ top: offsetPosition, behavior: 'smooth' });
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
            <input type="text" placeholder="Biomarkers (e.g. C3, C4)" value="${escapeHtml(dateRange)}">
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
                <input type="text" placeholder="Unit" value="${escapeHtml(units)}">
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

function updateClinicalNotePreview() {
    const previewDiv = safeGetElement('clinicalNotePreview');
    const datePreviewDiv = safeGetElement('clinicalNoteDatePreview');
    const isOutpatient = getCurrentNoteType() === 'outpatient';
    
    if (previewDiv) {
        if (currentClinicalNote) {
            let preview = currentClinicalNote.substring(0, 120);
            if (currentClinicalNote.length > 120) preview += '...';
            previewDiv.textContent = preview;
        } else {
            previewDiv.textContent = 'No clinical note entered yet';
        }
    }
    
    if (datePreviewDiv) {
        if (isOutpatient && currentAssessmentDate) {
            const formattedDate = formatDate(currentAssessmentDate);
            datePreviewDiv.innerHTML = `📅 <strong>Date:</strong> ${formattedDate}`;
            datePreviewDiv.style.display = 'block';
        } else {
            datePreviewDiv.style.display = 'none';
        }
    }
}

function openClinicalNoteModal() {
    const modal = safeGetElement('clinicalNoteModal');
    const modalClinicalNote = safeGetElement('modalClinicalNote');
    const modalAssessmentDate = safeGetElement('modalAssessmentDate');
    const modalDateSection = safeGetElement('modalDateSection');
    const isOutpatient = getCurrentNoteType() === 'outpatient';
    
    if (!modal) return;
    
    if (modalClinicalNote) modalClinicalNote.value = currentClinicalNote;
    if (modalAssessmentDate) modalAssessmentDate.value = currentAssessmentDate;
    
    // Show/hide date section and update label
    if (modalDateSection) {
        modalDateSection.style.display = isOutpatient ? 'block' : 'none';
        const dateLabel = modalDateSection.querySelector('.editor-label');
        if (dateLabel) {
            dateLabel.textContent = isOutpatient ? '📅 Visit Date (for Outpatient)' : '';
        }
    }
    
    modal.style.display = 'flex';
}


function closeClinicalNoteModal() {
    const modal = safeGetElement('clinicalNoteModal');
    if (modal) modal.style.display = 'none';
}

function clearClinicalNote() {
    const modalClinicalNote = safeGetElement('modalClinicalNote');
    const modalAssessmentDate = safeGetElement('modalAssessmentDate');
    
    if (modalClinicalNote) modalClinicalNote.value = '';
    if (modalAssessmentDate) modalAssessmentDate.value = '';
    
    showToast('Clinical note cleared', 'success');
}

function saveClinicalNote() {
    const modalClinicalNote = safeGetElement('modalClinicalNote');
    const modalAssessmentDate = safeGetElement('modalAssessmentDate');
    const isOutpatient = getCurrentNoteType() === 'outpatient';
    
    if (modalClinicalNote) currentClinicalNote = modalClinicalNote.value;
    if (isOutpatient && modalAssessmentDate) {
        currentAssessmentDate = modalAssessmentDate.value;
    } else {
        currentAssessmentDate = '';
    }
    
    updateClinicalNotePreview();
    closeClinicalNoteModal();
    generateOutput();
    showToast('Clinical note saved!', 'success');
}

// Update selectDescriptor to load saved rules
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
    
    // Load saved custom rules or use default
    let rulesText = '';
    let structuredData = null;
    
    if (customRules[desc]) {
        rulesText = customRules[desc];
        if (isTypeB && (rulesText.includes('Quantitative thresholds:') || rulesText.includes('Qualitative value handling:'))) {
            structuredData = parseStructuredFromText(rulesText);
        }
    } else if (typeof descriptorData === 'string') {
        rulesText = descriptorData;
        if (isTypeB && (rulesText.includes('Quantitative thresholds:') || rulesText.includes('Qualitative value handling:'))) {
            structuredData = parseStructuredFromText(rulesText);
        }
    } else if (typeof descriptorData === 'object') {
        structuredData = descriptorData;
        rulesText = buildRulesTextFromStructured(descriptorData, isTypeB);
        if (isTypeB && !customRules[desc]) {
            customRules[desc] = rulesText;
        }
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
    
    // Update the preview (read-only)
    const rulesPreview = safeGetElement('rulesPreview');
    if (rulesPreview) rulesPreview.value = rulesText;
    generateOutput();
    
    if (fromUserClick) {
        scrollToDescriptorEditor();
    }
}

// Update updateRawFromStructured to save changes
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
        const keywords = safeGetElement('keywords');
        
        const criteria = diagnosticCriteria ? diagnosticCriteria.value : '';
        const exclusions = clinicalExclusions ? clinicalExclusions.value : '';
        const notes = clinicalNotes ? clinicalNotes.value : '';
        const keywordsValue = keywords ? keywords.value : '';
        
        newRules = `Diagnostic criteria:\n${criteria}`;
        if (exclusions) newRules += `\n\nExclusions:\n${exclusions}`;
        if (notes) newRules += `\n\nNotes:\n${notes}`;
        
        // Parse keywords text to extract diagnostic, symptoms, paraclinical
        if (keywordsValue && currentDescriptor) {
            if (!keywordsList[currentDescriptor]) keywordsList[currentDescriptor] = {};
            
            // Clear existing
            delete keywordsList[currentDescriptor].diagnostic;
            delete keywordsList[currentDescriptor].symptoms;
            delete keywordsList[currentDescriptor].paraclinical;
            
            // Parse based on headers
            const diagnosticMatch = keywordsValue.match(/List of diagnostic keywords:\n([\s\S]*?)(?=\n\nList of|$)/i);
            const symptomsMatch = keywordsValue.match(/List of symptoms\/signs keywords:\n([\s\S]*?)(?=\n\nList of|$)/i);
            const paraclinicalMatch = keywordsValue.match(/List of paraclinical keywords:\n([\s\S]*?)(?=\n\nList of|$)/i);
            
            if (diagnosticMatch) {
                let diagText = diagnosticMatch[1].trim();
                // Remove any "No diagnostic keywords." line if present
                if (diagText === 'No diagnostic keywords.' || diagText.startsWith('No diagnostic keywords')) {
                    // Don't store anything for diagnostic
                } else {
                    keywordsList[currentDescriptor].diagnostic = diagText;
                }
            }
            
            if (symptomsMatch) {
                let symptomsText = symptomsMatch[1].trim();
                if (symptomsText && !symptomsText.startsWith('No')) {
                    keywordsList[currentDescriptor].symptoms = symptomsText;
                }
            }
            
            if (paraclinicalMatch) {
                let paraText = paraclinicalMatch[1].trim();
                if (paraText && !paraText.startsWith('No')) {
                    keywordsList[currentDescriptor].paraclinical = paraText;
                }
            }
            
            // If no headers found at all, assume whole text is diagnostic
            if (!diagnosticMatch && !symptomsMatch && !paraclinicalMatch && keywordsValue.trim()) {
                if (keywordsValue.trim() !== 'No diagnostic keywords.') {
                    keywordsList[currentDescriptor].diagnostic = keywordsValue.trim();
                }
            }
        }
    }
    
    // Update the preview (read-only)
    const rulesPreview = safeGetElement('rulesPreview');
    if (rulesPreview) rulesPreview.value = newRules;
    
    customRules[currentDescriptor] = newRules;
    
    generateOutput();
}

function updateDownloadButtonText() {
    const isOutpatient = getCurrentNoteType() === 'outpatient';
    const downloadBtn = safeGetElement('downloadPromptBtn');
    if (downloadBtn) {
        downloadBtn.textContent = isOutpatient ? '📥 Download prompt.py (Outpatient)' : '📥 Download prompt.py (Inpatient)';
    }
}

// Add download prompt.py function
function downloadPromptPy() {
    const isOutpatient = getCurrentNoteType() === 'outpatient';
    
    let content = `# SLEDAI-2K Prompt Configuration - ${isOutpatient ? 'OUTPATIENT' : 'INPATIENT'}\n`;
    content += `# Generated from SLEDAI-2K Prompt Customizer\n# Note Type: ${isOutpatient ? 'Outpatient (assess at visit date)' : 'Inpatient/Discharge (assess at admission date)'}\n\n`;
    
    // Add type constants
    content += "TYPE_A = 'type_a'\n";
    content += "TYPE_B = 'type_b'\n\n";

    // Add weights
    content += 'weights = [\n';
    weights.forEach(w => {
        content += `    ('${w[0]}', ${w[1]}, ${w[2].toUpperCase()}),\n`;
    });
    content += ']\n\n';

    // Add descriptors list and derived variables
    content += 'descriptors = [w[0] for w in weights]\n';
    content += 'sledai_weights = {w[0]: w[1] for w in weights}\n';
    content += 'type_a_hard = [w[0] for w in weights if w[1] >= 8]\n';
    content += 'type_a_others = [w[0] for w in weights if w[2] == TYPE_A and w[0] not in type_a_hard]\n';
    content += 'type_b = [w[0] for w in weights if w[2] == TYPE_B]\n\n';
    
    // Add additional prompts
    content += 'treatment_response_prompt = """' + (additionalPrompts.treatment_response_prompt || '') + '"""\n\n';
    content += 'intention_to_treat_prompt = """' + (additionalPrompts.intention_to_treat_prompt || '') + '"""\n\n';
    content += 'nature_of_intention_to_treat_prompt = """' + (additionalPrompts.nature_of_intention_to_treat_prompt || '') + '"""\n\n';
    content += 'npsle_tips = """' + (additionalPrompts.npsle_tips || '') + '"""\n\n';
    
    // Add editable guidelines templates
    const guidelinesKey = isOutpatient ? 'outpatient_guidelines' : 'inpatient_guidelines';
    content += '# Editable Guidelines Templates\n';
    content += 'guidelines_template = """\n' + (editableTemplates[guidelinesKey] || '') + '\n"""\n\n';
    
    // Add clinical note template
    const clinicalNoteKey = isOutpatient ? 'outpatient_clinical_note' : 'inpatient_clinical_note';
    content += '# Clinical Note Template\n';
    content += 'clinical_note_template = """' + (nonEditableTemplates[clinicalNoteKey] || '') + '"""\n\n';
    
    // Add combined score template
    content += '# Combined Score Template\n';
    content += 'score_template = guidelines_template + clinical_note_template\n\n';
    
    // Add output template
    content += '# Output Template (for JSON formatting)\n';
    content += 'output_template = """' + (nonEditableTemplates.output_template || '') + '"""\n\n';
    
    // Add keywords_list
    content += 'keywords_list = {\n';
    for (const [desc, keywords] of Object.entries(keywordsList)) {
        content += `    '${desc}': {\n`;
        if (descriptorTypes[desc] === 'TYPE_A') {
            // Type A has diagnostic, symptoms, paraclinical
            const diagnostic = keywords.diagnostic || '';
            const symptoms = keywords.symptoms || '';
            const paraclinical = keywords.paraclinical || '';
            if (diagnostic) content += `        'diagnostic': '''${diagnostic.replace(/'/g, "\\'")}''',\n`;
            if (symptoms) content += `        'symptoms': '''${symptoms.replace(/'/g, "\\'")}''',\n`;
            if (paraclinical) content += `        'paraclinical': '''${paraclinical.replace(/'/g, "\\'")}''',\n`;
        } else {
            // Type B has keywords
            const kw = keywords.keywords || '';
            if (kw) content += `        'keywords': '''${kw.replace(/'/g, "\\'")}''',\n`;
        }
        content += `    },\n`;
    }
    content += '}\n\n';

    // Add descriptor definitions
    content += 'definitions = {\n';
    for (const [desc, descriptorData] of Object.entries(definitions)) {
        let rulesText;
        const savedRule = customRules[desc];
        
        if (savedRule) {
            rulesText = savedRule;
        } else if (typeof descriptorData === 'string') {
            rulesText = descriptorData;
        } else if (typeof descriptorData === 'object') {
            rulesText = buildRulesTextFromStructured(descriptorData, descriptorTypes[desc] === 'TYPE_B');
        } else {
            rulesText = '';
        }
        
        const escapedRules = rulesText.replace(/'''/g, "\\'\\'\\'");
        content += `    '${desc}': '''${escapedRules}\n''',\n\n`;
    }
    content += '}\n';
    
    // Create download
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'prompt.py';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast(`${isOutpatient ? 'Outpatient' : 'Inpatient'} prompt.py downloaded successfully!`, 'success');
}

function resetToDefault() {
    if (!currentDescriptor) return;

    if (customRules[currentDescriptor]) {
        delete customRules[currentDescriptor];
    }

    const descriptorData = definitions[currentDescriptor];
    const isTypeB = descriptorTypes[currentDescriptor] === 'TYPE_B';
    let defaultRules = '';
    
    if (typeof descriptorData === 'string') {
        defaultRules = descriptorData;
    } else if (typeof descriptorData === 'object') {
        defaultRules = buildRulesTextFromStructured(descriptorData, isTypeB);
    }
    
    // Update preview
    const rulesPreview = safeGetElement('rulesPreview');
    if (rulesPreview) rulesPreview.value = defaultRules;
    
    if (isTypeB) {
        const typeBKeywords = safeGetElement('typeBKeywords');
        if (typeBKeywords) {
            const originalKeywords = originalKeywordsList[currentDescriptor]?.keywords || '';
            typeBKeywords.value = originalKeywords;
            if (!keywordsList[currentDescriptor]) keywordsList[currentDescriptor] = {};
            keywordsList[currentDescriptor].keywords = originalKeywords;
        }
    } else {
        const keywords = safeGetElement('keywords');
        if (keywords) {
            const originalKw = originalKeywordsList[currentDescriptor] || {};
            let keywordsText = '';
            if (originalKw.diagnostic) keywordsText += 'List of diagnostic keywords:\n' + originalKw.diagnostic;
            if (originalKw.symptoms) keywordsText += (keywordsText ? '\n\n' : '') + 'List of symptoms/signs keywords:\n' + originalKw.symptoms;
            if (originalKw.paraclinical) keywordsText += (keywordsText ? '\n\n' : '') + 'List of paraclinical keywords:\n' + originalKw.paraclinical;
            if (!keywordsText) keywordsText = 'No diagnostic keywords.';
            
            keywords.value = keywordsText;
            
            // Restore the keywordsList
            keywordsList[currentDescriptor] = {
                diagnostic: originalKw.diagnostic || '',
                symptoms: originalKw.symptoms || '',
                paraclinical: originalKw.paraclinical || ''
            };
        }
    }
    
    if (!isTypeB) {
        const diagnosticCriteria = safeGetElement('diagnosticCriteria');
        const clinicalExclusions = safeGetElement('clinicalExclusions');
        const clinicalNotes = safeGetElement('clinicalNotes');
        
        const parsed = parseRulesText(defaultRules);
        if (diagnosticCriteria) diagnosticCriteria.value = parsed.criteria;
        if (clinicalExclusions) clinicalExclusions.value = parsed.exclusions;
        if (clinicalNotes) clinicalNotes.value = parsed.notes;
    }
    
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
    
    const rulesPreview = safeGetElement('rulesPreview');
    const customRulesContent = rulesPreview ? rulesPreview.value : '';
    
    const output = buildFullPrompt(customRulesContent);
    
    const outputContent = safeGetElement('outputContent');
    if (outputContent) outputContent.textContent = output;
}

function buildFullPrompt(customRulesContent) {
    const noteType = getCurrentNoteType();
    const isOutpatient = noteType === 'outpatient';
    
    let clinicalNoteText = currentClinicalNote || '[INSERT CLINICAL NOTE HERE]';
    let dateString = '';
    let guidelinesTemplate = '';
    let clinicalNoteTemplate = '';
    let outputTemplate = nonEditableTemplates.output_template;
    
    if (isOutpatient) {
        dateString = formatDate(currentAssessmentDate);
        guidelinesTemplate = editableTemplates.outpatient_guidelines;
        clinicalNoteTemplate = nonEditableTemplates.outpatient_clinical_note;
    } else {
        guidelinesTemplate = editableTemplates.inpatient_guidelines;
        clinicalNoteTemplate = nonEditableTemplates.inpatient_clinical_note;
    }
    
    const keywordsText = buildKeywordsText(currentDescriptor);
    const isHardDescriptor = typeAHard.includes(currentDescriptor);
    
    let treatmentLogicText = '';
    let natureOfIntentionToTreatText = '';
    let npsleTipsText = '';
    
    if (isHardDescriptor) {
        treatmentLogicText = additionalPrompts.intention_to_treat_prompt || '';
        treatmentLogicText = treatmentLogicText.replace(/\{\{\s*descriptor\s*\}\}/g, formatName(currentDescriptor));
        natureOfIntentionToTreatText = additionalPrompts.nature_of_intention_to_treat_prompt || '';
        npsleTipsText = additionalPrompts.npsle_tips || '';
    } else {
        treatmentLogicText = additionalPrompts.treatment_response_prompt || '';
        treatmentLogicText = treatmentLogicText.replace(/\{\{\s*descriptor\s*\}\}/g, formatName(currentDescriptor));
        natureOfIntentionToTreatText = '';
        npsleTipsText = '';
    }
    
    // Assemble full template: editable guidelines + non-editable clinical_note + non-editable output
    let fullTemplate = guidelinesTemplate + clinicalNoteTemplate + outputTemplate;
    
    let result = fullTemplate
        .replace(/\{\{\s*date\s*\}\}/g, dateString)
        .replace(/\{\{\s*descriptor\s*\}\}/g, currentDescriptor)
        .replace(/\{\{\s*information\s*\}\}/g, customRulesContent)
        .replace(/\{\{\s*clinical_note\s*\}\}/g, clinicalNoteText)
        .replace(/\{\{\s*keywords\s*\}\}/g, keywordsText)
        .replace(/\{\{\s*treatment_logic\s*\}\}/g, treatmentLogicText)
        .replace(/\{\{\s*nature_of_intention_to_treat\s*\}\}/g, natureOfIntentionToTreatText)
        .replace(/\{\{\s*npsle_tips\s*\}\}/g, npsleTipsText);
    
    return result.replace(/\{\{\s*\w+\s*\}\}/g, '');
}

function updateDateFieldVisibility() {
    generateOutput();
}

function toggleClinicalNoteSidebar() {
    const card = document.getElementById('clinicalNoteSidebarCard');
    if (card) {
        card.classList.toggle('collapsed');
    }
    // Adjust descriptor list height - but without forcing reflow
    const descriptorList = document.querySelector('.descriptor-list');
    if (descriptorList) {
        if (card.classList.contains('collapsed')) {
            descriptorList.classList.add('expanded');
        } else {
            descriptorList.classList.remove('expanded');
        }
    }
}

function toggleConfig() {
    const card = document.querySelector('.collapsible');
    if (!card) return;
    
    // Toggle collapsed class
    card.classList.toggle('collapsed');
    
    // Adjust descriptor list height - but without forcing reflow
    const descriptorList = document.querySelector('.descriptor-list');
    if (descriptorList) {
        if (card.classList.contains('collapsed')) {
            descriptorList.classList.add('expanded');
        } else {
            descriptorList.classList.remove('expanded');
        }
    }
}

function initDescriptorListHeight() {
    const card = document.querySelector('.collapsible');
    const descriptorList = document.querySelector('.descriptor-list');
    if (card && descriptorList) {
        if (card.classList.contains('collapsed')) {
            descriptorList.classList.add('expanded');
        } else {
            descriptorList.classList.remove('expanded');
        }
    }
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
    const modalTitle = safeGetElement('templateModalTitle');
    if (!modal) return;
    
    const currentNoteType = getCurrentNoteType();
    const isOutpatient = currentNoteType === 'outpatient';
    
    // Update modal title
    if (modalTitle) {
        modalTitle.textContent = isOutpatient ? 'Edit Outpatient Template' : 'Edit Inpatient Template';
    }
    
    const templateEditor = safeGetElement('templateEditor');
    if (templateEditor) {
        if (isOutpatient) {
            templateEditor.value = editableTemplates.outpatient_guidelines || '';
        } else {
            templateEditor.value = editableTemplates.inpatient_guidelines || '';
        }
    }
    
    modal.style.display = 'flex';
}

function closeTemplateModal() {
    const modal = safeGetElement('templateModal');
    if (modal) modal.style.display = 'none';
}

function switchTemplateTab(templateType) {
    const editor = safeGetElement('templateEditor');
    if (editor) {
        if (templateType === 'outpatient') {
            editor.value = editableTemplates.outpatient_guidelines || '';
        } else if (templateType === 'inpatient') {
            editor.value = editableTemplates.inpatient_guidelines || '';
        }
    }
}

function saveTemplate() {
    const templateEditor = safeGetElement('templateEditor');
    const currentNoteType = getCurrentNoteType();
    
    if (templateEditor) {
        const templateKey = currentNoteType === 'outpatient' ? 'outpatient_guidelines' : 'inpatient_guidelines';
        editableTemplates[templateKey] = templateEditor.value;
    }
    
    showToast(`Saved ${currentNoteType === 'outpatient' ? 'Outpatient' : 'Inpatient'} guidelines template`, 'success');
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
    
    setupTemplateEditorClickDetection();
    setupLegendClickHandlers();
    
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeTemplateModal();
            closeTreatmentLogicModal();
            closeNpsleModal();
            closeClinicalNoteModal();
        }
    });
    
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', () => {
            closeTemplateModal();
            closeTreatmentLogicModal();
            closeNpsleModal();
            closeClinicalNoteModal();
        });
    });
}

function initClinicalNoteModal() {
    const editBtn = safeGetElement('editClinicalNoteBtn');
    if (editBtn) editBtn.addEventListener('click', openClinicalNoteModal);
    
    const saveBtn = safeGetElement('saveClinicalNoteBtn');
    if (saveBtn) saveBtn.addEventListener('click', saveClinicalNote);
    
    const clearBtn = safeGetElement('clearClinicalNoteBtn');
    if (clearBtn) clearBtn.addEventListener('click', clearClinicalNote);
}

function initDownloadButton() {
    const downloadBtn = safeGetElement('downloadPromptBtn');
    if (downloadBtn) {
        downloadBtn.addEventListener('click', downloadPromptPy);
    }
    updateDownloadButtonText();
}

function showToast(message, type) {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2000);
}

function openHelpModal() {
    const modal = safeGetElement('helpModal');
    if (modal) modal.style.display = 'flex';
}

function closeHelpModal() {
    const modal = safeGetElement('helpModal');
    if (modal) modal.style.display = 'none';
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    loadPrompts();
    
    const noteTypeSelect = safeGetElement('noteTypeSelect');
    const descriptorSearch = safeGetElement('descriptorSearch');
    const resetDescriptorBtn = safeGetElement('resetDescriptorBtn');
    const copyOutputBtn = safeGetElement('copyOutputBtn');
    const toggleRawPreview = safeGetElement('toggleRawPreview');
    const addThresholdBtn = safeGetElement('addThresholdRow');
    const helpBtn = safeGetElement('helpBtn');
    
    if (noteTypeSelect) {
        noteTypeSelect.addEventListener('change', () => {
            updateDownloadButtonText();
            updateClinicalNotePreview();
            generateOutput(); 
        });
    }
    if (descriptorSearch) descriptorSearch.addEventListener('input', renderDescriptorList);
    if (resetDescriptorBtn) resetDescriptorBtn.addEventListener('click', resetToDefault);
    if (copyOutputBtn) copyOutputBtn.addEventListener('click', copyOutput);
    if (addThresholdBtn) addThresholdBtn.addEventListener('click', () => addThresholdRow());
    if (helpBtn) helpBtn.addEventListener('click', openHelpModal);
    
    if (toggleRawPreview) {
        toggleRawPreview.addEventListener('click', () => {
            const rawPreview = safeGetElement('rawPreview');
            if (rawPreview) {
                rawPreview.style.display = rawPreview.style.display === 'block' ? 'none' : 'block';
            }
        });
    }
    
    const typeAFields = ['diagnosticCriteria', 'clinicalExclusions', 'clinicalNotes', 'keywords'];
    typeAFields.forEach(field => {
        const el = safeGetElement(field);
        if (el) el.addEventListener('input', updateRawFromStructured);
    });
    
    const typeBFields = ['qualitativeRules', 'exclusionCriteria', 'labNotes', 'typeBKeywords'];
    typeBFields.forEach(field => {
        const el = safeGetElement(field);
        if (el) el.addEventListener('input', updateRawFromStructured);
    });
    
    const thresholdRowsContainer = safeGetElement('thresholdRows');
    if (thresholdRowsContainer) {
        thresholdRowsContainer.addEventListener('input', updateRawFromStructured);
        thresholdRowsContainer.addEventListener('click', (e) => {
            if (e.target.classList.contains('remove-row')) setTimeout(updateRawFromStructured, 50);
        });
    }
    
    initTemplateModal();
    initClinicalNoteModal();
    initDownloadButton();
    initGenerateButton();
    initDescriptorListHeight();
    updateClinicalNotePreview();
});