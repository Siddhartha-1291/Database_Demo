/**
 * ICDTRA Website – Section Navigation & Cancer Genomics Database Integration
 *
 * All data is read from the global `DB` object defined in data.js,
 * so the website works when opened via file:// (double-clicking index.html).
 */
document.addEventListener('DOMContentLoaded', function () {

    /* ======================================================================
     *  SECTION NAVIGATION
     * ====================================================================== */
    const menuButtons = document.querySelectorAll('.menu-btn');
    const contentSections = document.querySelectorAll('.content-section');
    const mainContent = document.getElementById('main-content');

    menuButtons.forEach(function (button) {
        button.addEventListener('click', function () {
            var sectionId = this.getAttribute('data-section');
            menuButtons.forEach(function (btn) { btn.classList.remove('active'); });
            this.classList.add('active');
            contentSections.forEach(function (section) {
                var sectionName = section.id.replace('section-', '');
                if (sectionName === sectionId) {
                    section.classList.add('active');
                } else {
                    section.classList.remove('active');
                }
            });
            if (mainContent) {
                mainContent.classList.remove('genomics-active', 'proteomics-active');
                if (sectionId === 'genomics') {
                    mainContent.classList.add('genomics-active');
                } else if (sectionId === 'proteomics') {
                    mainContent.classList.add('proteomics-active');
                }
            }
            if (sectionId === 'home') {
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }
        });
    });

    /* ======================================================================
     *  ERROR / INFO MODAL (dismissable)
     * ====================================================================== */
    var errorModal = document.getElementById('error-modal');
    var errorModalText = document.getElementById('error-modal-text');
    var errorModalClose = document.getElementById('error-modal-close');

    function showErrorModal(msg) {
        if (errorModalText) errorModalText.textContent = msg;
        if (errorModal) errorModal.classList.add('active');
    }
    function hideErrorModal() {
        if (errorModal) errorModal.classList.remove('active');
    }
    if (errorModalClose) {
        errorModalClose.addEventListener('click', hideErrorModal);
    }

    /* ======================================================================
     *  CANCER GENOMICS – DOM REFERENCES
     * ====================================================================== */
    var searchInput       = document.getElementById('protein-gene-search');
    var pathwayCheckboxes = document.querySelectorAll('input[name="pathway"]');
    var subsetRadios      = document.querySelectorAll('input[name="subset"]');
    var subsetsOptions    = document.querySelector('.subsets-options');
    var searchBtn         = document.getElementById('search-btn');
    var clearBtn          = document.getElementById('clear-btn');
    var proteinsList      = document.getElementById('proteins-list');
    var dataPanel         = document.querySelector('.data-panel-inner');
    var downloadBtn       = document.getElementById('download-btn');

    /* ======================================================================
     *  STATE VARIABLES
     * ====================================================================== */
    var selectedProteins = {};          // protein name -> true/false
    var lastValidatedSearchName = null; // last valid protein/gene name from search box

    /* ======================================================================
     *  DATA-ACCESS HELPERS  (reads from global DB object in data.js)
     * ====================================================================== */

    /**
     * Search for an exact match of `name` across Protein_Name and Gene_Name
     * columns of both signalling-proteins tables.
     *
     * Returns an array of result objects:
     *   { proteinName: string,
     *     searchedGeneName: string|null,   // the gene name the user typed (if matched via Gene_Name)
     *     matchedByGene: boolean }          // true when the match was via Gene_Name, not Protein_Name
     *
     * matchedByGene is only set to true when the gene name that matched
     * is different from the protein name in the same row.
     */
    function searchProteinInDB(name) {
        var tables = ['MTOR_signalling_proteins', 'Wnt_signalling_proteins'];
        var found = [];
        var seen = {};

        tables.forEach(function (tbl) {
            var tableData = DB[tbl];
            if (!tableData) return;
            var cols = tableData.columns;
            var pIdx = cols.indexOf('Protein_Name');
            var gIdx = cols.indexOf('Gene_Name');
            if (pIdx === -1) return;

            tableData.rows.forEach(function (row) {
                var proteinName = row[pIdx] || '';
                // 1) Exact Protein Name match
                if (proteinName === name) {
                    if (!seen[proteinName]) {
                        seen[proteinName] = true;
                        found.push({ proteinName: proteinName, searchedGeneName: null, matchedByGene: false });
                    }
                    return;
                }
                // 2) Exact Gene Name match (space-separated)
                if (gIdx !== -1) {
                    var geneField = row[gIdx] || '';
                    var geneNames = geneField.split(/\s+/);
                    for (var i = 0; i < geneNames.length; i++) {
                        if (geneNames[i] === name) {
                            if (!seen[proteinName]) {
                                seen[proteinName] = true;
                                // Only flag matchedByGene when the gene name differs from protein name
                                var isDifferent = (name !== proteinName);
                                found.push({
                                    proteinName: proteinName,
                                    searchedGeneName: isDifferent ? name : null,
                                    matchedByGene: isDifferent
                                });
                            }
                            break;
                        }
                    }
                }
            });
        });
        return found;
    }

    /**
     * Return set of protein names for a given pathway key ("wnt" or "mtor").
     */
    function getPathwayProteinSet(pathwayKey) {
        var tableMap = {
            'wnt': 'Wnt_signalling_proteins',
            'mtor': 'MTOR_signalling_proteins'
        };
        var tbl = tableMap[pathwayKey];
        if (!tbl || !DB[tbl]) return {};
        var cols = DB[tbl].columns;
        var pIdx = cols.indexOf('Protein_Name');
        if (pIdx === -1) return {};
        var s = {};
        DB[tbl].rows.forEach(function (row) {
            var n = row[pIdx];
            if (n) s[n] = true;
        });
        return s;
    }

    /**
     * Get pathway proteins filtered by subset.
     * pathwayKeys: array of strings, e.g. ["wnt","mtor"]
     * subset: "entire" | "common" | "notcommon" | ""
     * Returns { proteins: [str], error: str|null }
     */
    function getPathwayProteins(pathwayKeys, subset) {
        var sets = [];
        pathwayKeys.forEach(function (key) {
            sets.push(getPathwayProteinSet(key));
        });

        if (sets.length === 0) {
            return { proteins: [], error: 'No pathway selected.' };
        }

        // Single pathway or no subset → union
        if (pathwayKeys.length === 1 || !subset) {
            var union = {};
            sets.forEach(function (s) { for (var k in s) union[k] = true; });
            return { proteins: Object.keys(union).sort(), error: null };
        }

        if (subset === 'entire') {
            var union2 = {};
            sets.forEach(function (s) { for (var k in s) union2[k] = true; });
            return { proteins: Object.keys(union2).sort(), error: null };
        }

        if (subset === 'common') {
            // Intersection
            var result = {};
            for (var k in sets[0]) result[k] = true;
            for (var i = 1; i < sets.length; i++) {
                var next = {};
                for (var k2 in result) {
                    if (sets[i][k2]) next[k2] = true;
                }
                result = next;
            }
            var arr = Object.keys(result).sort();
            if (arr.length === 0) {
                return { proteins: [], error: 'There are no proteins that are common to all of the selected signalling pathways.' };
            }
            return { proteins: arr, error: null };
        }

        if (subset === 'notcommon') {
            // Proteins appearing in exactly one set
            var counts = {};
            sets.forEach(function (s) {
                for (var k3 in s) {
                    counts[k3] = (counts[k3] || 0) + 1;
                }
            });
            var exclusive = [];
            for (var k4 in counts) {
                if (counts[k4] === 1) exclusive.push(k4);
            }
            exclusive.sort();
            if (exclusive.length === 0) {
                return { proteins: [], error: 'All proteins are shared across the selected pathways.' };
            }
            return { proteins: exclusive, error: null };
        }

        return { proteins: [], error: 'Invalid subset.' };
    }

    /**
     * Get differential expression data for a protein.
     * Returns { columns: [str], rows: [[str]] } or null.
     */
    function getProteinData(proteinName) {
        var tableName = proteinName.replace(/[^a-zA-Z0-9_]/g, '_') + '_diffr_expr_cancer';
        var entry = DB.diff_expr[tableName];
        if (!entry) return null;
        return { columns: entry.columns, rows: entry.rows };
    }

    /**
     * Get the URL for a protein from the URLs table.
     */
    function getProteinURL(proteinName) {
        if (!DB.URLs) return null;
        var cols = DB.URLs.columns;
        var pIdx = cols.indexOf('Protein_Name');
        var uIdx = cols.indexOf('URL');
        if (pIdx === -1 || uIdx === -1) return null;
        for (var i = 0; i < DB.URLs.rows.length; i++) {
            if (DB.URLs.rows[i][pIdx] === proteinName) {
                return DB.URLs.rows[i][uIdx];
            }
        }
        return null;
    }

    /* ======================================================================
     *  SUBSETS OF PROTEINS – ENABLE / DISABLE
     * ====================================================================== */
    function getSelectedPathways() {
        var result = [];
        pathwayCheckboxes.forEach(function (c) {
            if (c.checked) result.push(c.value);
        });
        return result;
    }

    function getSelectedSubset() {
        var checked = document.querySelector('input[name="subset"]:checked');
        return checked ? checked.value : '';
    }

    function updateSubsetsState() {
        var checked = getSelectedPathways();
        if (checked.length > 1) {
            subsetsOptions.classList.remove('disabled');
        } else {
            subsetsOptions.classList.add('disabled');
            // Deselect all subset radios
            subsetRadios.forEach(function (r) { r.checked = false; });
        }
    }

    /* ======================================================================
     *  RESET HELPERS
     * ====================================================================== */

    /** Reset search-box method and its associated state. */
    function resetSearchBoxState() {
        searchInput.value = '';
        lastValidatedSearchName = null;
    }

    /** Reset pathway/subset menus and their associated state. */
    function resetPathwayState() {
        pathwayCheckboxes.forEach(function (cb) { cb.checked = false; });
        subsetRadios.forEach(function (r) { r.checked = false; });
        updateSubsetsState();
    }

    /** Clear both display panels and their associated state. */
    function clearDisplayPanels() {
        proteinsList.innerHTML = '';
        dataPanel.innerHTML = '';
        selectedProteins = {};
        litGeneSelected = {};
        updateDownloadBtn();
    }

    /** Full reset – everything back to initial state. */
    function fullReset() {
        resetSearchBoxState();
        resetPathwayState();
        clearDisplayPanels();
        litGeneSelected = {};
    }

    /* litGeneSelected is declared later but hoisted; initialised here for clarity */
    var litGeneSelected = {};

    /** Enable/disable the download button based on data panel content. */
    function updateDownloadBtn() {
        if (!downloadBtn) return;
        var table = dataPanel.querySelector('table');
        var hasRows = table && table.querySelector('tbody') &&
                      table.querySelector('tbody').children.length > 0;
        downloadBtn.disabled = !hasRows;
    }

    /* ======================================================================
     *  MUTUAL EXCLUSIVITY
     *  - Typing in the search box → resets pathway menus & panels
     *  - Selecting a pathway checkbox → clears search box & panels
     *  - Changing subset → clears display panels only
     * ====================================================================== */
    searchInput.addEventListener('input', function () {
        // User is typing in search box → reset pathway-related controls & panels
        resetPathwayState();
        clearDisplayPanels();
    });

    pathwayCheckboxes.forEach(function (cb) {
        cb.addEventListener('change', function () {
            // User toggled a pathway checkbox → clear search box & panels
            resetSearchBoxState();
            clearDisplayPanels();
            updateSubsetsState();
        });
    });

    subsetRadios.forEach(function (r) {
        r.addEventListener('change', function () {
            // User changed subset → clear display panels (keep pathway selections)
            clearDisplayPanels();
        });
    });

    // Initialise subsets state (disabled on load)
    updateSubsetsState();

    /* ======================================================================
     *  SEARCH-BOX BLUR – validate protein / gene name
     *  Shows error if invalid, but does NOT display proteins
     *  (proteins are only displayed on Search button click).
     * ====================================================================== */
    searchInput.addEventListener('blur', function () {
        var name = searchInput.value.trim();
        if (!name) {
            lastValidatedSearchName = null;
            return;
        }
        var found = searchProteinInDB(name);
        if (found.length > 0) {
            lastValidatedSearchName = name;
        } else {
            lastValidatedSearchName = null;
            showErrorModal(
                'The Protein/gene name provided is either not in the database, ' +
                'at present, or is misspelt. Please re-check the spelling and ' +
                'try again, if you altered it.'
            );
        }
    });

    /* ======================================================================
     *  SEARCH BUTTON
     * ====================================================================== */
    searchBtn.addEventListener('click', function () {
        var name = searchInput.value.trim();
        var pathways = getSelectedPathways();
        var subset = getSelectedSubset();

        /* --- Case 1: Protein / Gene name entered --- */
        if (name) {
            var found = searchProteinInDB(name);
            if (found.length > 0) {
                lastValidatedSearchName = name;
                displayProteins(found);
            } else {
                lastValidatedSearchName = null;
                showErrorModal(
                    'The Protein/gene name provided is either not in the database, ' +
                    'at present, or is misspelt. Please re-check the spelling and ' +
                    'try again, if you altered it.'
                );
            }
            return;
        }

        /* --- Case 2: Pathway(s) selected --- */
        if (pathways.length > 0) {
            var result = getPathwayProteins(pathways, subset);
            if (result.error && result.proteins.length === 0) {
                showErrorModal(result.error);
                return;
            }
            displayProteins(result.proteins);
            return;
        }

        /* --- Nothing entered or selected --- */
        showErrorModal('Please enter a Protein/Gene name or select a Signalling Pathway before searching.');
    });

    /* ======================================================================
     *  CLEAR BUTTON – full reset
     * ====================================================================== */
    clearBtn.addEventListener('click', function () {
        fullReset();
    });

    /**
     * Check whether a protein has a corresponding _diffr_expr_cancer table.
     */
    function hasExpressionData(proteinName) {
        var tableName = proteinName.replace(/[^a-zA-Z0-9_]/g, '_') + '_diffr_expr_cancer';
        return !!(DB.diff_expr && DB.diff_expr[tableName]);
    }

    /* ======================================================================
     *  DISPLAY PROTEINS IN THE PROTEINS PANEL
     *
     *  `items` can be:
     *    - an array of plain strings (protein names)  – from pathway search
     *    - an array of result objects { proteinName, searchedGeneName, matchedByGene }
     *      – from search-box search
     * ====================================================================== */
    function displayProteins(items) {
        proteinsList.innerHTML = '';
        dataPanel.innerHTML = '';
        selectedProteins = {};

        items.forEach(function (item) {
            // Normalise: accept both plain strings and objects
            var proteinName, displayLabel, searchedGeneName;
            if (typeof item === 'string') {
                proteinName = item;
                displayLabel = item;
                searchedGeneName = null;
            } else {
                proteinName = item.proteinName;
                searchedGeneName = item.searchedGeneName || null;
                // Show "ProteinName/GeneName" only when matched by a different gene name
                if (item.matchedByGene && searchedGeneName) {
                    displayLabel = proteinName + '/' + searchedGeneName;
                } else {
                    displayLabel = proteinName;
                }
            }

            var div = document.createElement('div');
            div.className = 'protein-option';

            var hasData = hasExpressionData(proteinName);

            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.name = 'protein-select';
            cb.value = proteinName;
            cb.id = 'prot-' + proteinName;

            if (hasData) {
                cb.addEventListener('change', (function (pn) {
                    return function () { onProteinToggle(pn, this.checked); };
                })(proteinName));
            } else {
                // Disable checkbox – no diff expr data for this protein
                cb.disabled = true;
                cb.classList.add('disabled-checkbox');
            }

            var lbl = document.createElement('label');
            lbl.setAttribute('for', 'prot-' + proteinName);
            lbl.textContent = displayLabel;

            if (!hasData) {
                lbl.classList.add('disabled-label');
            }

            // Intercept clicks on the disabled checkbox or its label
            if (!hasData) {
                var cbWrapper = document.createElement('span');
                cbWrapper.className = 'disabled-cb-wrapper';
                cbWrapper.appendChild(cb);
                cbWrapper.appendChild(lbl);
                cbWrapper.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    showErrorModal(
                        'There is no differential gene expression data in the ' +
                        'EMBL-EBI Expression Atlas for this protein.'
                    );
                });
                div.appendChild(cbWrapper);
            } else {
                div.appendChild(cb);
                div.appendChild(lbl);
            }

            var urlBtn = document.createElement('button');
            urlBtn.type = 'button';
            urlBtn.className = 'url-btn';
            urlBtn.textContent = 'URL';
            urlBtn.addEventListener('click', (function (pn) {
                return function () { openProteinURL(pn); };
            })(proteinName));

            div.appendChild(urlBtn);
            proteinsList.appendChild(div);
        });
    }

    /* ======================================================================
     *  PROTEIN CHECKBOX TOGGLE – show / hide data in expression panel
     * ====================================================================== */
    function onProteinToggle(proteinName, isChecked) {
        if (isChecked) {
            selectedProteins[proteinName] = true;
            loadProteinData(proteinName);
        } else {
            delete selectedProteins[proteinName];
            removeProteinData(proteinName);
        }
    }

    function loadProteinData(proteinName) {
        var data = getProteinData(proteinName);
        if (!data) {
            console.warn('No differential expression data for', proteinName);
            return;
        }
        appendDataToPanel(proteinName, data.columns, data.rows);
    }

    function appendDataToPanel(proteinName, columns, rows) {
        // If no table exists yet, create one with headers
        var table = dataPanel.querySelector('table');
        if (!table) {
            table = document.createElement('table');
            var thead = document.createElement('thead');
            var tr = document.createElement('tr');
            columns.forEach(function (col) {
                var th = document.createElement('th');
                th.textContent = col;
                tr.appendChild(th);
            });
            thead.appendChild(tr);
            table.appendChild(thead);
            var tbody = document.createElement('tbody');
            table.appendChild(tbody);
            dataPanel.appendChild(table);
        }
        var tbody2 = table.querySelector('tbody');
        rows.forEach(function (row) {
            var tr2 = document.createElement('tr');
            tr2.setAttribute('data-protein', proteinName);
            row.forEach(function (cell) {
                var td = document.createElement('td');
                td.textContent = cell;
                tr2.appendChild(td);
            });
            tbody2.appendChild(tr2);
        });
        updateDownloadBtn();
    }

    function removeProteinData(proteinName) {
        var table = dataPanel.querySelector('table');
        if (!table) return;
        var tbody = table.querySelector('tbody');
        var rows = tbody.querySelectorAll('tr[data-protein="' + proteinName + '"]');
        rows.forEach(function (r) { r.remove(); });
        // If no selected proteins remain, remove the whole table (including headers)
        var anySelected = false;
        for (var k in selectedProteins) {
            if (selectedProteins[k]) { anySelected = true; break; }
        }
        if (!anySelected) {
            dataPanel.innerHTML = '';
        }
        updateDownloadBtn();
    }

    /* ======================================================================
     *  DOWNLOAD DISPLAYED DATA AS CSV
     * ====================================================================== */
    if (downloadBtn) {
        downloadBtn.addEventListener('click', function () {
            var table = dataPanel.querySelector('table');
            if (!table) return;

            var csvRows = [];
            // Header row
            var thead = table.querySelector('thead');
            if (thead) {
                var headerCells = thead.querySelectorAll('th');
                var headerArr = [];
                headerCells.forEach(function (th) {
                    headerArr.push('"' + th.textContent.replace(/"/g, '""') + '"');
                });
                csvRows.push(headerArr.join(','));
            }
            // Data rows
            var tbody = table.querySelector('tbody');
            if (tbody) {
                var dataRows = tbody.querySelectorAll('tr');
                dataRows.forEach(function (tr) {
                    var cells = tr.querySelectorAll('td');
                    var rowArr = [];
                    cells.forEach(function (td) {
                        rowArr.push('"' + td.textContent.replace(/"/g, '""') + '"');
                    });
                    csvRows.push(rowArr.join(','));
                });
            }

            var csvContent = csvRows.join('\n');
            var blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = 'diffr_gene_expr_data.csv';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        });
    }

    /* ======================================================================
     *  OPEN PROTEIN URL IN NEW TAB
     * ====================================================================== */
    function openProteinURL(proteinName) {
        var url = getProteinURL(proteinName);
        if (url) {
            window.open(url, '_blank');
        } else {
            showErrorModal('No URL found for ' + proteinName + '.');
        }
    }

    /* ======================================================================
     *  CANCER LITERATURE – populate year dropdown menus
     * ====================================================================== */
    var litDropdowns = document.getElementById('literature-dropdowns');
    if (litDropdowns && typeof LITERATURE !== 'undefined') {
        // LITERATURE keys are years (descending in the object from literature_data.js)
        var years = Object.keys(LITERATURE).sort(function (a, b) {
            return parseInt(b) - parseInt(a);  // newest first
        });

        years.forEach(function (year) {
            var files = LITERATURE[year];
            if (!files || files.length === 0) return;

            var select = document.createElement('select');
            select.className = 'literature-year-select';

            // First option: the year label (non-downloadable)
            var labelOpt = document.createElement('option');
            labelOpt.value = '';
            labelOpt.textContent = year + ' (' + files.length + ' articles)';
            labelOpt.disabled = true;
            labelOpt.selected = true;
            select.appendChild(labelOpt);

            // One option per PDF file
            files.forEach(function (fname) {
                var opt = document.createElement('option');
                opt.value = fname;
                opt.textContent = fname.replace(/\.pdf$/i, '');
                select.appendChild(opt);
            });

            // On change: trigger download as a file (fetch as blob first so
            // the browser does not simply display the PDF in a new tab).
            select.addEventListener('change', function () {
                var selectedFile = this.value;
                if (!selectedFile) return;
                var dropdown = this;                // keep reference for reset

                var filePath = 'Articles_Differential_Expression/' + year + '/' + encodeURIComponent(selectedFile);

                fetch(filePath)
                    .then(function (response) {
                        if (!response.ok) throw new Error('Network response was not ok');
                        return response.blob();
                    })
                    .then(function (blob) {
                        var blobUrl = URL.createObjectURL(blob);
                        var a = document.createElement('a');
                        a.href = blobUrl;
                        a.download = selectedFile;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(blobUrl);
                    })
                    .catch(function () {
                        // Fallback: if fetch fails (e.g. file:// protocol),
                        // use a direct link with target _blank
                        var a = document.createElement('a');
                        a.href = filePath;
                        a.download = selectedFile;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                    });

                // Reset dropdown to the year label
                dropdown.selectedIndex = 0;
            });

            litDropdowns.appendChild(select);
        });
    }

    /* ======================================================================
     *  CANCER GENOMICS – "Load Differential Expression Data From Cancer
     *  Literature" BUTTON
     * ====================================================================== */
    var loadLitGeneBtn = document.getElementById('load-lit-gene-btn');
    if (loadLitGeneBtn) {
        loadLitGeneBtn.addEventListener('click', function () {
            // Clear everything first
            fullReset();

            // Show two literature options in the Proteins panel
            var optionsInfo = [
                { id: 'lit-gene-main', table: 'Differential_Gene_Expression_From_Literature',
                  label: 'Differential Gene Expression From Literature' },
                { id: 'lit-gene-dq',   table: 'Differential_Gene_Expression_From_Literature_Direct_Quote',
                  label: 'Differential Gene Expression From Literature- Directly Quoted Data' }
            ];

            optionsInfo.forEach(function (opt) {
                var div = document.createElement('div');
                div.className = 'protein-option';

                var cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.name = 'lit-gene-select';
                cb.value = opt.table;
                cb.id = opt.id;

                cb.addEventListener('change', function () {
                    onLiteratureGeneToggle(opt.table, this.checked);
                });

                var lbl = document.createElement('label');
                lbl.setAttribute('for', opt.id);
                lbl.textContent = opt.label;

                div.appendChild(cb);
                div.appendChild(lbl);
                proteinsList.appendChild(div);
            });
        });
    }

    function onLiteratureGeneToggle(tableName, isChecked) {
        if (isChecked) {
            litGeneSelected[tableName] = true;
            loadLiteratureData(tableName, dataPanel);
        } else {
            delete litGeneSelected[tableName];
            removeLiteratureData(tableName, dataPanel, litGeneSelected);
        }
        updateDownloadBtn();
    }

    /**
     * Generic helper: load a literature_expr table into a given panel element.
     * Adds the CSS class 'literature-table' for responsive font sizing.
     */
    function loadLiteratureData(tableName, panelEl) {
        if (!DB.literature_expr || !DB.literature_expr[tableName]) return;
        var entry = DB.literature_expr[tableName];
        var columns = entry.columns;
        var rows = entry.rows;

        var table = panelEl.querySelector('table');
        if (!table) {
            table = document.createElement('table');
            table.className = 'literature-table';
            var thead = document.createElement('thead');
            var tr = document.createElement('tr');
            columns.forEach(function (col) {
                var th = document.createElement('th');
                th.textContent = col;
                tr.appendChild(th);
            });
            thead.appendChild(tr);
            table.appendChild(thead);
            var tbody = document.createElement('tbody');
            table.appendChild(tbody);
            panelEl.appendChild(table);
        }
        var tbody2 = table.querySelector('tbody');
        rows.forEach(function (row) {
            var tr2 = document.createElement('tr');
            tr2.setAttribute('data-lit-table', tableName);
            row.forEach(function (cell) {
                var td = document.createElement('td');
                td.textContent = cell;
                tr2.appendChild(td);
            });
            tbody2.appendChild(tr2);
        });
    }

    /**
     * Generic helper: remove rows for a literature table from a panel.
     * If no selected tables remain, remove the whole table.
     */
    function removeLiteratureData(tableName, panelEl, selectedTracker) {
        var table = panelEl.querySelector('table');
        if (!table) return;
        var tbody = table.querySelector('tbody');
        var rows = tbody.querySelectorAll('tr[data-lit-table="' + tableName + '"]');
        rows.forEach(function (r) { r.remove(); });
        // If nothing is selected, remove table entirely
        var anySelected = false;
        for (var k in selectedTracker) {
            if (selectedTracker[k]) { anySelected = true; break; }
        }
        if (!anySelected) {
            panelEl.innerHTML = '';
        }
    }

    /* ======================================================================
     *  CANCER PROTEOMICS – literature checkboxes, data loading & download
     * ====================================================================== */
    var protDataPanel = document.getElementById('prot-data-panel-inner');
    var downloadProtBtn = document.getElementById('download-prot-btn');
    var protLitCheckboxes = document.querySelectorAll('input[name="prot-lit-select"]');

    /** State tracker for which literature-protein tables are loaded. */
    var litProtSelected = {};

    function updateDownloadProtBtn() {
        if (!downloadProtBtn || !protDataPanel) return;
        var table = protDataPanel.querySelector('table');
        var hasRows = table && table.querySelector('tbody') &&
                      table.querySelector('tbody').children.length > 0;
        downloadProtBtn.disabled = !hasRows;
    }

    protLitCheckboxes.forEach(function (cb) {
        cb.addEventListener('change', function () {
            var tableName = this.value;
            if (this.checked) {
                litProtSelected[tableName] = true;
                loadLiteratureData(tableName, protDataPanel);
            } else {
                delete litProtSelected[tableName];
                removeLiteratureData(tableName, protDataPanel, litProtSelected);
            }
            updateDownloadProtBtn();
        });
    });

    /* Download button for proteomics panel */
    if (downloadProtBtn) {
        downloadProtBtn.addEventListener('click', function () {
            if (!protDataPanel) return;
            var table = protDataPanel.querySelector('table');
            if (!table) return;

            var csvRows = [];
            var thead = table.querySelector('thead');
            if (thead) {
                var headerCells = thead.querySelectorAll('th');
                var headerArr = [];
                headerCells.forEach(function (th) {
                    headerArr.push('"' + th.textContent.replace(/"/g, '""') + '"');
                });
                csvRows.push(headerArr.join(','));
            }
            var tbody = table.querySelector('tbody');
            if (tbody) {
                var dataRows = tbody.querySelectorAll('tr');
                dataRows.forEach(function (tr) {
                    var cells = tr.querySelectorAll('td');
                    var rowArr = [];
                    cells.forEach(function (td) {
                        rowArr.push('"' + td.textContent.replace(/"/g, '""') + '"');
                    });
                    csvRows.push(rowArr.join(','));
                });
            }

            var csvContent = csvRows.join('\n');
            var blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = 'diffr_prot_expr_data.csv';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        });
    }

});
