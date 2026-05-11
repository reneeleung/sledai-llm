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
    
    // Extract Quantitative thresholds
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
    
    // Extract Qualitative handling
    const qualMatch = rulesText.match(/Qualitative value handling:\n([\s\S]*?)(?=\n\nExclusions:|\n\nNotes:|$)/i);
    if (qualMatch) {
        result.qualitative = qualMatch[1].trim();
    }
    
    // Extract Exclusions
    const exclMatch = rulesText.match(/Exclusions:\n([\s\S]*?)(?=\n\nNotes:|$)/i);
    if (exclMatch) {
        result.exclusions = exclMatch[1].trim();
    }
    
    // Extract Notes
    const notesMatch = rulesText.match(/Notes:\n([\s\S]*?)$/i);
    if (notesMatch) {
        result.notes = notesMatch[1].trim();
    }
    
    return result;
}

// Build rules text from structured Type B data
function buildRulesTextFromStructured(descriptorData, isTypeB) {
    if (!isTypeB) {
        // Type A: format with criteria, exclusions, notes
        if (descriptorData.criteria) {
            let rulesText = `Diagnostic criteria:\n${descriptorData.criteria}`;
            if (descriptorData.exclusions) rulesText += `\n\nExclusions:\n${descriptorData.exclusions}`;
            if (descriptorData.notes) rulesText += `\n\nNotes:\n${descriptorData.notes}`;
            return rulesText;
        }
        return '';
    }
    
    // Type B: Quantitative FIRST, then Qualitative
    let rulesText = '';
    
    // Quantitative thresholds first
    if (descriptorData.thresholds && descriptorData.thresholds.length > 0) {
        rulesText += `Quantitative thresholds:\n`;
        descriptorData.thresholds.forEach(t => {
            rulesText += `- ${t.date_range}: ${t.condition} ${t.value} ${t.units}\n`;
        });
        rulesText += `\n`;
    }
    
    // Qualitative handling second
    if (descriptorData.qualitative) {
        rulesText += `Qualitative value handling:\n${descriptorData.qualitative}\n\n`;
    }
    
    // Exclusions
    if (descriptorData.exclusions) {
        rulesText += `Exclusions:\n${descriptorData.exclusions}\n\n`;
    }
    
    // Notes
    if (descriptorData.notes) {
        rulesText += `Notes:\n${descriptorData.notes}`;
    }
    
    return rulesText;
}

// Parse rules text into components (for Type A)
function parseRulesText(rulesText) {
    const result = {
        criteria: '',
        exclusions: '',
        notes: ''
    };
    
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
        
        const countElement = safeGetElement('descriptorCount');
        if (countElement) countElement.textContent = `(${weights.length})`;
        
        renderDescriptorList();
        
        if (weights.length > 0) {
            selectDescriptor(weights[0][0]);
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
    
    const descriptors = weights
        .filter(w => w[0].toLowerCase().includes(searchTerm))
        .map(w => w[0]);
    
    container.innerHTML = descriptors.map(desc => `
        <div class="descriptor-item ${descriptorTypes[desc] === 'TYPE_A' ? 'type-a' : 'type-b'} ${currentDescriptor === desc ? 'active' : ''}" data-descriptor="${desc}">
            <strong>${formatName(desc)}</strong>
            <small>Score: ${descriptorScores[desc]} | ${descriptorTypes[desc] === 'TYPE_A' ? 'Clinical' : 'Lab'}</small>
        </div>
    `).join('');
    
    document.querySelectorAll('.descriptor-item').forEach(el => {
        el.addEventListener('click', () => selectDescriptor(el.dataset.descriptor));
    });
}

function formatName(name) {
    return name.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

function buildKeywordsText(desc) {
    const keywords = keywordsList[desc] || {};
    let keywordsText = '';
    
    // For Type A descriptors (clinical)
    if (descriptorTypes[desc] === 'TYPE_A') {
        if (keywords.diagnostic) {
            keywordsText += 'List of diagnostic keywords:\n' + keywords.diagnostic;
        } else {
            keywordsText += 'No diagnostic keywords.';
        }
        if (keywords.symptoms) {
            keywordsText += '\n\nList of symptoms/signs keywords:\n' + keywords.symptoms;
        }
        if (keywords.paraclinical) {
            keywordsText += '\n\nList of paraclinical keywords:\n' + keywords.paraclinical;
        }
    } 
    // For Type B descriptors (lab)
    else {
        if (keywords.keywords) {
            keywordsText += 'List of keywords:\n' + keywords.keywords;
        } else {
            keywordsText += 'No keywords defined.';
        }
    }
    
    return keywordsText;
}

// Add threshold row function
function addThresholdRow(dateRange = '', condition = '<', value = '', units = '') {
    const container = safeGetElement('thresholdRows');
    if (!container) return;
    
    // If this is the first row, clear any empty state
    if (container.children.length === 0) {
        container.innerHTML = '';
    }
    
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
    
    const inputs = row.querySelectorAll('input, select');
    inputs.forEach(input => {
        input.addEventListener('input', updateRawFromStructured);
    });
}

function selectDescriptor(desc) {
    currentDescriptor = desc;
    renderDescriptorList();
    
    const editorElement = safeGetElement('descriptorEditor');
    if (editorElement) editorElement.style.display = 'block';
    
    const titleElement = safeGetElement('currentDescriptorTitle');
    if (titleElement) {
        titleElement.innerHTML = `${formatName(desc)} <span style="font-size:0.7rem; opacity:0.7;">Score: ${descriptorScores[desc]}</span>`;
    }
    
    const isTypeB = descriptorTypes[desc] === 'TYPE_B';
    const descriptorData = definitions[desc];
    
    let rulesText = '';
    let structuredData = null;
    
    // Handle both old and new formats
    if (typeof descriptorData === 'string') {
        rulesText = descriptorData;
        // Try to parse as structured if it looks like Type B format
        if (isTypeB && (rulesText.includes('Quantitative thresholds:') || rulesText.includes('Qualitative value handling:'))) {
            structuredData = parseStructuredFromText(rulesText);
        }
    } else if (typeof descriptorData === 'object') {
        structuredData = descriptorData;
        if (isTypeB) {
            rulesText = buildRulesTextFromStructured(descriptorData, true);
        } else {
            rulesText = buildRulesTextFromStructured(descriptorData, false);
        }
    }
    
    // Parse rules text for display in editors (for Type A)
    const parsed = parseRulesText(rulesText);
    
    // Handle Type B Editor
    const typeBEditor = safeGetElement('typeBEditor');
    const typeAEditor = safeGetElement('typeAEditor');
    
    if (isTypeB) {
        if (typeBEditor) typeBEditor.style.display = 'block';
        if (typeAEditor) typeAEditor.style.display = 'none';
        
        // Populate thresholds (Quantitative)
        const thresholdRowsContainer = safeGetElement('thresholdRows');
        if (thresholdRowsContainer) {
            thresholdRowsContainer.innerHTML = '';
            const thresholds = structuredData?.thresholds || [];
            
            if (thresholds.length === 0) {
                thresholdRowsContainer.innerHTML = '';
            } else {
                thresholds.forEach(t => {
                    addThresholdRow(
                        t.date_range || '',
                        t.condition || '<',
                        t.value || '',
                        t.units || ''
                    );
                });
            }
        }
        
        // Populate Qualitative
        const qualitativeRules = safeGetElement('qualitativeRules');
        if (qualitativeRules) {
            qualitativeRules.value = structuredData?.qualitative || '';
        }
        
        // Populate Keywords for Type B
        const typeBKeywords = safeGetElement('typeBKeywords');
        if (typeBKeywords) {
            // Get keywords from keywordsList for this descriptor
            const keywords = keywordsList[desc] || {};
            typeBKeywords.value = keywords.keywords || '';
        }
        
        // Populate Exclusions
        const exclusionCriteria = safeGetElement('exclusionCriteria');
        if (exclusionCriteria) {
            exclusionCriteria.value = structuredData?.exclusions || '';
        }
        
        // Populate Notes
        const labNotes = safeGetElement('labNotes');
        if (labNotes) {
            labNotes.value = structuredData?.notes || '';
        }
        
    } else {
        if (typeBEditor) typeBEditor.style.display = 'none';
        if (typeAEditor) typeAEditor.style.display = 'block';
        
        // Type A population
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
        
        // Build quantitative thresholds from rows
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
        
        if (qualitative) {
            newRules += `Qualitative value handling:\n${qualitative}\n\n`;
        }
        
        if (exclusions) {
            newRules += `Exclusions:\n${exclusions}\n\n`;
        }
        
        if (notes) {
            newRules += `Notes:\n${notes}`;
        }
        
        // Also update the keywordsList in memory (though not saved to JSON)
        if (keywords && currentDescriptor) {
            if (!keywordsList[currentDescriptor]) {
                keywordsList[currentDescriptor] = {};
            }
            keywordsList[currentDescriptor].keywords = keywords;
        }
        
    } else {
        // Type A handling
        const diagnosticCriteria = safeGetElement('diagnosticCriteria');
        const clinicalExclusions = safeGetElement('clinicalExclusions');
        const clinicalNotes = safeGetElement('clinicalNotes');
        
        const criteria = diagnosticCriteria ? diagnosticCriteria.value : '';
        const exclusions = clinicalExclusions ? clinicalExclusions.value : '';
        const notes = clinicalNotes ? clinicalNotes.value : '';
        
        newRules = `Diagnostic criteria:\n${criteria}`;
        if (exclusions) newRules += `\n\nExclusions:\n${exclusions}`;
        if (notes) newRules += `\n\nNotes:\n${notes}`;
        
        // Update keywords for Type A (though not saved to JSON)
        const keywords = safeGetElement('keywords');
        if (keywords && keywords.value && currentDescriptor) {
            // Keywords are already displayed but not saved to JSON
        }
    }
    
    const rulesEditor = safeGetElement('rulesEditor');
    if (rulesEditor) {
        rulesEditor.value = newRules;
    }
    generateOutput();
}

function resetToDefault() {
    if (!currentDescriptor) return;
    const descriptorData = definitions[currentDescriptor];
    let defaultRules = '';
    const isTypeB = descriptorTypes[currentDescriptor] === 'TYPE_B';
    
    if (typeof descriptorData === 'string') {
        defaultRules = descriptorData;
    } else if (typeof descriptorData === 'object') {
        defaultRules = buildRulesTextFromStructured(descriptorData, isTypeB);
    }
    
    const rulesEditor = safeGetElement('rulesEditor');
    if (rulesEditor) rulesEditor.value = defaultRules;
    
    // Reload the descriptor to refresh all UI fields
    selectDescriptor(currentDescriptor);
    
    generateOutput();
    showToast(`Reset ${formatName(currentDescriptor)} to default`, 'success');
}

function formatDate(dateInput) {
    if (!dateInput) return '[DATE NEEDED]';
    
    const parts = dateInput.split('-');
    if (parts.length === 3) {
        return `${parts[2]}/${parts[1]}/${parts[0]}`;
    }
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
    
    let output = '';
    
    if (outputMode === 'full') {
        output = buildFullPrompt(noteType, currentDescriptor, customRules);
    } else {
        output = buildDescriptorOnly(currentDescriptor, customRules);
    }
    
    const outputContent = safeGetElement('outputContent');
    if (outputContent) outputContent.textContent = output;
}

function buildFullPrompt(noteType, descriptor, customRules) {
    const clinicalNote = safeGetElement('clinicalNote');
    const assessmentDate = safeGetElement('assessmentDate');
    
    // Use placeholder if clinical note is empty
    let clinicalNoteText = clinicalNote ? clinicalNote.value : '';
    if (!clinicalNoteText || clinicalNoteText.trim() === '') {
        clinicalNoteText = '[INSERT CLINICAL NOTE HERE]';
    }
    
    let dateString = '';
    let template = '';
    
    if (noteType === 'outpatient') {
        const dateInput = assessmentDate ? assessmentDate.value : '';
        dateString = formatDate(dateInput);
        template = templates.outpatient;
    } else {
        dateString = '[ADMISSION DATE FROM NOTE]';
        template = templates.discharge;
    }
    
    // Build keywords text using the structured format
    const keywordsText = buildKeywordsText(descriptor);
    
    // Determine which additional prompts to include
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
        natureOfIntentionToTreatText = '';
        npsleTipsText = '';
    }
    
    // Replace all placeholders
    let result = template
        .replace(/\{\{\s*date\s*\}\}/g, dateString)
        .replace(/\{\{\s*descriptor\s*\}\}/g, descriptor)
        .replace(/\{\{\s*information\s*\}\}/g, customRules)
        .replace(/\{\{\s*clinical_note\s*\}\}/g, clinicalNoteText)
        .replace(/\{\{\s*keywords\s*\}\}/g, keywordsText)
        .replace(/\{\{\s*intention_to_treat\s*\}\}/g, intentionToTreatText)
        .replace(/\{\{\s*nature_of_intention_to_treat\s*\}\}/g, natureOfIntentionToTreatText)
        .replace(/\{\{\s*npsle_tips\s*\}\}/g, npsleTipsText);
    
    // Remove any remaining placeholders
    result = result.replace(/\{\{\s*\w+\s*\}\}/g, '');
    
    return result;
}

function buildDescriptorOnly(descriptor, customRules) {
    return `# Descriptor: ${descriptor}
# SLEDAI-2K Score: ${descriptorScores[descriptor]}
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
        if (outputMode === 'descriptor') {
            clinicalNoteCard.style.display = 'none';
        } else {
            clinicalNoteCard.style.display = 'block';
        }
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
    
    if (noteTypeSelect) {
        noteTypeSelect.addEventListener('change', () => {
            updateDateFieldVisibility();
            generateOutput();
        });
    }
    
    if (outputModeSelect) {
        outputModeSelect.addEventListener('change', () => {
            toggleClinicalNoteVisibility();
            generateOutput();
        });
    }
    
    if (descriptorSearch) {
        descriptorSearch.addEventListener('input', renderDescriptorList);
    }
    
    if (resetDescriptorBtn) {
        resetDescriptorBtn.addEventListener('click', resetToDefault);
    }
    
    if (copyOutputBtn) {
        copyOutputBtn.addEventListener('click', copyOutput);
    }
    
    if (clearNoteBtn) {
        clearNoteBtn.addEventListener('click', () => {
            if (clinicalNote) clinicalNote.value = '';
            generateOutput();
        });
    }
    
    if (toggleRawEditor) {
        toggleRawEditor.addEventListener('click', () => {
            const rawEditor = safeGetElement('rawEditor');
            if (rawEditor) {
                const isVisible = rawEditor.style.display === 'block';
                rawEditor.style.display = isVisible ? 'none' : 'block';
            }
        });
    }
    
    if (addThresholdBtn) {
        addThresholdBtn.addEventListener('click', () => addThresholdRow());
    }
    
    if (clinicalNote) {
        clinicalNote.addEventListener('input', generateOutput);
    }
    
    if (assessmentDate) {
        assessmentDate.addEventListener('input', generateOutput);
    }
    
    if (rulesEditor) {
        rulesEditor.addEventListener('input', generateOutput);
    }
    
    // Bind structured editors for Type A
    const typeAFields = ['diagnosticCriteria', 'clinicalExclusions', 'clinicalNotes'];
    typeAFields.forEach(field => {
        const el = safeGetElement(field);
        if (el) el.addEventListener('input', updateRawFromStructured);
    });
    
    // Bind structured editors for Type B
    const typeBFields = ['qualitativeRules', 'exclusionCriteria', 'labNotes', 'typeBKeywords'];
    typeBFields.forEach(field => {
        const el = safeGetElement(field);
        if (el) el.addEventListener('input', updateRawFromStructured);
    });
    
    const keywords = safeGetElement('keywords');
    if (keywords) keywords.addEventListener('input', updateRawFromStructured);
    
    // Listen for threshold row changes (delegation)
    const thresholdRowsContainer = safeGetElement('thresholdRows');
    if (thresholdRowsContainer) {
        thresholdRowsContainer.addEventListener('input', updateRawFromStructured);
        thresholdRowsContainer.addEventListener('click', (e) => {
            if (e.target.classList.contains('remove-row')) {
                setTimeout(updateRawFromStructured, 50);
            }
        });
    }
    
    updateDateFieldVisibility();
    toggleClinicalNoteVisibility();
});