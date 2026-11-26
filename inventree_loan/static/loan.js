(() => {
    'use strict';

    const L = window.LOAN || {};
    const $ = (selector, root = document) => root.querySelector(selector);
    const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

    const esc = (value) => String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');

    const num = (value) => {
        const parsed = Number.parseFloat(value);
        return Number.isFinite(parsed) ? parsed : 0;
    };

    // The public request flow borrows whole units only.
    const whole = (value) => Math.floor(num(value));

    function formatError(error) {
        if (!error) return 'Something went wrong.';
        if (typeof error === 'string') return error;
        const data = error.data;
        if (!data) return error.message || 'Request failed.';
        if (typeof data === 'string') return data;
        if (Array.isArray(data)) return data.join(' ');
        if (data.detail) return data.detail;
        if (data.error) return data.error;
        return Object.entries(data).map(([key, value]) => {
            const text = Array.isArray(value) ? value.join(' ') : String(value);
            return `${key}: ${text}`;
        }).join(' · ');
    }

    async function api(path, options = {}) {
        const headers = {
            Accept: 'application/json',
            'X-CSRFToken': L.csrf || '',
            ...(options.body ? { 'Content-Type': 'application/json' } : {}),
            ...(options.headers || {})
        };
        const response = await fetch(path, {
            credentials: 'same-origin',
            ...options,
            headers
        });
        const text = await response.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch (_) { data = text; }
        if (!response.ok) {
            const error = new Error(`HTTP ${response.status}`);
            error.status = response.status;
            error.data = data;
            throw error;
        }
        return data;
    }

    function showError(element, message) {
        if (!element) return;
        element.textContent = message;
        element.hidden = false;
    }

    function clearError(element) {
        if (!element) return;
        element.hidden = true;
        element.textContent = '';
    }

    function showSuccess(element, html) {
        if (!element) return;
        element.innerHTML = html;
        element.hidden = false;
    }

    function setBusy(button, busy, busyText = 'Working…') {
        if (!button) return;
        if (busy) {
            button.dataset.originalText = button.innerHTML;
            button.disabled = true;
            button.innerHTML = `<i class="fas fa-circle-notch fa-spin" aria-hidden="true"></i> ${esc(busyText)}`;
        } else {
            button.disabled = false;
            if (button.dataset.originalText) button.innerHTML = button.dataset.originalText;
        }
    }

    function debounce(fn, delay = 250) {
        let timer = null;
        return (...args) => {
            window.clearTimeout(timer);
            timer = window.setTimeout(() => fn(...args), delay);
        };
    }

    function statusBadge(status, label) {
        const map = {
            pending: ['loan-badge-pending', 'fa-clock'],
            approved: ['loan-badge-approved', 'fa-circle-check'],
            rejected: ['loan-badge-danger', 'fa-circle-xmark'],
            cancelled: ['loan-badge-muted', 'fa-ban'],
            fulfilled: ['loan-badge-success', 'fa-check'],
            partially_fulfilled: ['loan-badge-warning', 'fa-circle-half-stroke'],
            active: ['loan-badge-info', 'fa-arrow-right-from-bracket'],
            partially_returned: ['loan-badge-warning', 'fa-rotate-left'],
            returned: ['loan-badge-success', 'fa-circle-check'],
            overdue: ['loan-badge-danger', 'fa-triangle-exclamation'],
            lost: ['loan-badge-dark', 'fa-circle-question']
        };
        const [css, icon] = map[status] || ['loan-badge-muted', 'fa-circle'];
        return `<span class="loan-badge ${css}"><i class="fas ${icon}" aria-hidden="true"></i> ${esc(label || status)}</span>`;
    }

    function askNote({ title, message = '', submitLabel = 'Save', danger = false }) {
        if (!('HTMLDialogElement' in window)) {
            return Promise.resolve(window.prompt(message || title));
        }
        return new Promise((resolve) => {
            const dialog = document.createElement('dialog');
            dialog.className = 'loan-dialog';
            dialog.innerHTML = `
                <div class="loan-dialog-head">
                    <h2>${esc(title)}</h2>
                    <button type="button" class="loan-icon-btn" data-dialog-close aria-label="Close"><i class="fas fa-xmark" aria-hidden="true"></i></button>
                </div>
                <p class="loan-muted">${esc(message)}</p>
                <label class="loan-label" for="loan-dialog-note">Notes</label>
                <textarea class="loan-textarea" id="loan-dialog-note" rows="3" maxlength="2000"></textarea>
                <div class="loan-dialog-actions">
                    <button type="button" class="loan-btn" data-dialog-close>Cancel</button>
                    <button type="button" class="loan-btn ${danger ? 'loan-btn-danger' : 'loan-btn-primary'}" data-dialog-submit>${esc(submitLabel)}</button>
                </div>`;
            document.body.appendChild(dialog);
            const textarea = $('textarea', dialog);
            const finish = (value) => {
                dialog.close();
                dialog.remove();
                resolve(value);
            };
            $$('[data-dialog-close]', dialog).forEach((button) => {
                button.addEventListener('click', () => finish(null));
            });
            $('[data-dialog-submit]', dialog).addEventListener('click', () => finish(textarea.value.trim()));
            dialog.addEventListener('cancel', (event) => {
                event.preventDefault();
                finish(null);
            });
            dialog.showModal();
            textarea.focus();
        });
    }

    /* ------------------------------------------------------------------
       Camera scanning
       ------------------------------------------------------------------ */
    function addCameraButtons() {
        if (!('BarcodeDetector' in window) || !navigator.mediaDevices) return;
        $$('.loan-scan-row input').forEach((input) => {
            if (input.dataset.cameraReady) return;
            input.dataset.cameraReady = '1';
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'loan-btn loan-btn-sm loan-camera-btn';
            button.title = 'Scan with camera';
            button.setAttribute('aria-label', 'Scan with camera');
            button.innerHTML = '<i class="fas fa-camera" aria-hidden="true"></i>';
            button.addEventListener('click', () => openCameraScanner((value) => {
                input.value = value;
                input.dispatchEvent(new Event('change', { bubbles: true }));
                const form = input.closest('form');
                if (form) form.requestSubmit();
            }));
            input.closest('.loan-scan-row')?.appendChild(button);
        });
    }

    async function openCameraScanner(onResult) {
        let stream = null;
        let timer = null;
        const overlay = document.createElement('div');
        overlay.className = 'loan-camera-overlay';
        overlay.innerHTML = `
            <div class="loan-camera-card" role="dialog" aria-modal="true" aria-label="Camera scanner">
                <div class="loan-dialog-head">
                    <h2>Scan with camera</h2>
                    <button type="button" class="loan-icon-btn" data-camera-close aria-label="Close camera"><i class="fas fa-xmark" aria-hidden="true"></i></button>
                </div>
                <video class="loan-camera-video" playsinline muted></video>
                <p class="loan-muted loan-small">Point the camera at a QR code or barcode.</p>
            </div>`;
        document.body.appendChild(overlay);

        const close = () => {
            if (timer) window.clearInterval(timer);
            if (stream) stream.getTracks().forEach((track) => track.stop());
            overlay.remove();
        };
        $('[data-camera-close]', overlay).addEventListener('click', close);
        overlay.addEventListener('click', (event) => {
            if (event.target === overlay) close();
        });

        try {
            const wantedFormats = [
                'qr_code', 'code_128', 'code_39', 'ean_13', 'ean_8', 'data_matrix', 'itf'
            ];
            const supportedFormats = await BarcodeDetector.getSupportedFormats();
            const formats = wantedFormats.filter((format) => supportedFormats.includes(format));
            if (!formats.length) {
                throw new Error('No supported barcode formats');
            }
            const detector = new BarcodeDetector({ formats });
            stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: { ideal: 'environment' } },
                audio: false
            });
            const video = $('video', overlay);
            video.srcObject = stream;
            await video.play();
            timer = window.setInterval(async () => {
                try {
                    const codes = await detector.detect(video);
                    if (codes.length && codes[0].rawValue) {
                        const value = codes[0].rawValue;
                        close();
                        onResult(value);
                    }
                } catch (_) { /* keep scanning */ }
            }, 350);
        } catch (error) {
            close();
            window.alert('Camera scanning is unavailable. Use a USB scanner or type the code.');
        }
    }

    /* ------------------------------------------------------------------
       Dashboard scan
       ------------------------------------------------------------------ */
    function initDashboard() {
        const form = $('[data-scan-form]');
        if (!form) return;
        const input = $('[data-scan-input]', form);
        const result = $('[data-scan-result]', form);
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const barcode = input.value.trim();
            if (!barcode) return;
            result.className = 'loan-scan-result';
            result.textContent = 'Scanning…';
            try {
                const found = await api(L.api.scan, { method: 'POST', body: JSON.stringify({ barcode }) });
                if (!found.success) {
                    result.classList.add('is-error');
                    result.textContent = found.error || 'No match found.';
                    return;
                }
                result.classList.add('is-success');
                if (found.type === 'loan') {
                    result.textContent = `Loan ${found.data.reference} found. Opening…`;
                    if (L.user.isDesk) {
                        window.location.href = `${L.urls.returnPage}?loan_id=${found.data.pk}`;
                    } else {
                        window.location.href = `${L.urls.loanDetail}${found.data.pk}/`;
                    }
                    return;
                }
                if (L.user.isDesk) {
                    window.location.href = `${L.urls.checkout}?scan=${encodeURIComponent(barcode)}`;
                } else {
                    window.location.href = `${L.urls.requestNew}?scan=${encodeURIComponent(barcode)}`;
                }
            } catch (error) {
                result.classList.add('is-error');
                result.textContent = formatError(error);
            }
        });
    }

    /* ------------------------------------------------------------------
       Shared catalog helpers
       ------------------------------------------------------------------ */
    function renderCatalog(results, container, onSelect, { allowUnavailable = true } = {}) {
        if (!container) return;
        if (!results.length) {
            container.innerHTML = '<p class="loan-muted loan-small">No matching parts found.</p>';
            return;
        }
        container.innerHTML = results.map((part) => {
            const available = num(part.available);
            const cls = available <= 0 ? 'none' : available < 3 ? 'low' : 'ok';
            const label = available <= 0 ? 'Unavailable' : `${available} available`;
            return `<div class="loan-result-card">
                <div>
                    <div class="loan-result-title">${esc(part.name)}</div>
                    <div class="loan-result-meta">${esc(part.ipn || '')}${part.category ? ` · ${esc(part.category)}` : ''}</div>
                    <div class="loan-availability loan-availability-${cls}">${esc(label)}${part.on_loan ? ` · ${num(part.on_loan)} on loan` : ''}</div>
                </div>
                <div class="loan-result-action">
                    <button class="loan-btn loan-btn-sm ${available <= 0 ? '' : 'loan-btn-primary'}" type="button" data-add-part="${part.pk}" ${!allowUnavailable && available <= 0 ? 'disabled' : ''}>Add</button>
                </div>
            </div>`;
        }).join('');
        container.querySelectorAll('[data-add-part]').forEach((button) => {
            button.addEventListener('click', () => {
                const part = results.find((item) => String(item.pk) === button.dataset.addPart);
                if (part) onSelect(part);
            });
        });
    }

    async function searchCatalog(query, container, onSelect, options) {
        if (!query || query.length < 2) {
            container.innerHTML = '';
            return;
        }
        container.innerHTML = '<p class="loan-muted loan-small">Searching…</p>';
        try {
            const data = await api(`${L.api.catalog}?search=${encodeURIComponent(query)}`);
            renderCatalog(data.results || [], container, onSelect, options);
        } catch (error) {
            container.innerHTML = `<p class="loan-form-error">${esc(formatError(error))}</p>`;
        }
    }

    /* ------------------------------------------------------------------
       Request form
       ------------------------------------------------------------------ */
    function initRequestForm() {
        const root = $('[data-public-request]');
        if (!root) return;

        const scanForm = $('[data-request-scan-form]', root);
        const scanInput = $('[data-request-scan]', root);
        const scanResult = $('[data-request-scan-result]', root);
        const searchInput = $('[data-public-search]', root);
        const resultsContainer = $('[data-public-results]', root);
        const resultCount = $('[data-public-result-count]', root);
        const pageInfo = $('[data-public-page-info]', root);
        const pager = $('[data-public-pager]', root);
        const heading = $('[data-public-heading]', root);
        const categoryButtons = $$('[data-category-id]', root);
        const cartBody = $('[data-cart-body]', root);
        const cartWrap = $('[data-cart-wrap]', root);
        const cartEmpty = $('[data-cart-empty]', root);
        const cartCount = $('[data-cart-count]', root);
        const cartTotal = $('[data-cart-total]', root);
        const neededByInput = $('#needed_by');
        const returnByInput = $('#return_by');
        const submit = $('[data-request-submit]', root);
        const errorBox = $('[data-request-error]', root);
        const successBox = $('[data-request-success]', root);
        const continueButton = $('[data-scroll-to-details]', root);
        const basketDialog = $('[data-basket-dialog]', root);
        const partDialog = $('[data-part-dialog]', document);
        const partDialogContent = $('[data-part-dialog-content]', partDialog);
        const state = { lines: [], parts: new Map(), category: '', search: '', page: 0, total: 0, limit: 25 };
        let loadSequence = 0;
        const clearFieldError = (field) => {
            if (!field) return;
            const describedBy = field.getAttribute('aria-describedby');
            if (describedBy) {
                const error = document.getElementById(describedBy);
                if (error?.classList.contains('field-error')) error.remove();
            }
            field.removeAttribute('aria-describedby');
            field.removeAttribute('aria-invalid');
        };

        const setFieldError = (field, message) => {
            if (!field) return;
            clearFieldError(field);
            const id = `field-error-${field.id || Math.random().toString(36).slice(2)}`;
            const error = document.createElement('p');
            error.id = id;
            error.className = 'field-error';
            error.setAttribute('role', 'alert');
            error.textContent = message;
            field.insertAdjacentElement('afterend', error);
            field.setAttribute('aria-describedby', id);
            field.setAttribute('aria-invalid', 'true');
        };

        const syncDates = () => {
            if (!neededByInput || !returnByInput) return;
            returnByInput.min = neededByInput.value || '';
            if (neededByInput.value && returnByInput.value && returnByInput.value < neededByInput.value) {
                returnByInput.value = neededByInput.value;
            }
        };
        neededByInput?.addEventListener('change', syncDates);
        syncDates();

        window.addEventListener('beforeunload', (event) => {
            if (!state.lines.length) return;
            event.preventDefault();
            event.returnValue = '';
        });

        const scrollTo = (selector, focusSelector) => {
            const target = $(selector);
            if (!target) return;
            target.scrollIntoView({
                behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
                block: 'start'
            });
            if (focusSelector) window.setTimeout(() => $(focusSelector)?.focus(), 350);
        };
        const closeBasket = () => {
            if (basketDialog?.open) basketDialog.close();
        };
        const openBasket = () => {
            if (basketDialog && !basketDialog.open) basketDialog.showModal();
        };
        const scrollToDetails = () => {
            closeBasket();
            scrollTo('#request-details', '#requester_name');
        };
        continueButton?.addEventListener('click', scrollToDetails);
        $('[data-open-basket]', root)?.addEventListener('click', openBasket);
        $('[data-close-basket]', root)?.addEventListener('click', closeBasket);
        basketDialog?.addEventListener('click', (event) => {
            if (event.target === basketDialog) closeBasket();
        });

        const renderCart = () => {
            $$('[data-cart-count]').forEach((element) => { element.textContent = String(state.lines.length); });
            cartTotal.textContent = String(state.lines.reduce((sum, line) => sum + num(line.quantity), 0));
            if (!state.lines.length) {
                cartEmpty.hidden = false;
                cartWrap.hidden = true;
                cartBody.innerHTML = '';
                return;
            }
            cartEmpty.hidden = true;
            cartWrap.hidden = false;
            cartBody.innerHTML = state.lines.map((line, index) => `
                <tr>
                    <td>
                        <strong>${esc(line.name)}</strong>
                        ${line.ipn ? `<div class="loan-muted">${esc(line.ipn)}</div>` : ''}
                        ${line.stock_item_id ? `<div class="loan-muted">Asset: ${esc(line.label)}</div>` : ''}
                    </td>
                    <td><input class="loan-input loan-qty-input" type="number" min="1" max="${line.stock_item_id ? 1 : line.available || ''}" step="1" value="${line.quantity}" data-qty-index="${index}" aria-label="Quantity for ${esc(line.name)}"></td>
                    <td><button class="loan-icon-btn" type="button" data-remove-index="${index}" aria-label="Remove ${esc(line.name)}"><i class="fas fa-trash" aria-hidden="true"></i></button></td>
                </tr>`).join('');
            cartBody.querySelectorAll('[data-qty-index]').forEach((input) => {
                input.addEventListener('change', () => {
                    const index = Number(input.dataset.qtyIndex);
                    const line = state.lines[index];
                    const maximum = line.stock_item_id ? 1 : (num(line.available) || num(input.value));
                    const value = Math.min(Math.max(Math.round(num(input.value)), 1), Math.max(Math.round(maximum), 1));
                    line.quantity = value;
                    input.value = value;
                    renderCart();
                });
            });
            cartBody.querySelectorAll('[data-remove-index]').forEach((button) => {
                button.addEventListener('click', () => {
                    state.lines.splice(Number(button.dataset.removeIndex), 1);
                    renderCart();
                });
            });
        };

        const addPart = (part, quantity = 1) => {
            const available = whole(part.available);
            if (available < 1) {
                if (scanResult) {
                    scanResult.className = 'catalog-scan-result is-error';
                    scanResult.textContent = `${part.name} is not available to borrow.`;
                }
                return;
            }
            const existing = state.lines.find((line) => !line.stock_item_id && line.part_id === part.pk);
            if (existing) {
                existing.quantity = Math.min(
                    Math.round(num(existing.quantity)) + Math.max(Math.round(num(quantity)), 1),
                    Math.max(available, 1)
                );
            } else {
                state.lines.push({
                    part_id: part.pk,
                    name: part.name,
                    ipn: part.ipn || '',
                    quantity: Math.min(Math.max(Math.round(num(quantity)), 1), Math.max(available, 1)),
                    available,
                    trackable: Boolean(part.trackable),
                    stock_item_id: null,
                    label: ''
                });
            }
            renderCart();
        };

        const addStockItem = (item, part) => {
            if (whole(item.available ?? item.quantity) < 1) return;
            if (state.lines.some((line) => line.stock_item_id === item.pk)) {
                if (scanResult) {
                    scanResult.className = 'catalog-scan-result is-error';
                    scanResult.textContent = 'This asset is already in the request.';
                }
                return;
            }
            state.lines.push({
                part_id: part.pk,
                name: part.name || item.part_name,
                ipn: part.ipn || item.ipn || '',
                quantity: 1,
                available: whole(item.available ?? item.quantity),
                trackable: true,
                stock_item_id: item.pk,
                label: item.serial || item.label || `#${item.pk}`
            });
            renderCart();
        };

        const closePartDialog = () => {
            if (partDialog?.open) partDialog.close();
        };

        const renderPartDialog = (part) => {
            const stockItems = part.stock_items || [];
            const totalAvailable = whole(part.available);
            const availabilityClass = totalAvailable < 1 ? 'is-none' : totalAvailable < 3 ? 'is-low' : '';
            const image = `<i class="fas fa-box" aria-hidden="true"></i>${part.image ? `<img src="${esc(part.image)}" alt="" loading="lazy" onerror="this.remove()">` : ''}`;
            const stockRows = stockItems.map((item) => `
                <div class="stock-row">
                    <div class="stock-row-main">
                        <div class="stock-row-title">${esc(item.label || `Item #${item.pk}`)}</div>
                        <div class="stock-row-meta">${esc(item.part_name || '')}${item.part_name && item.location ? ' · ' : ''}${esc(item.location || 'No location')} · ${whole(item.available)} available</div>
                    </div>
                    <button class="it-btn it-btn-small it-btn-primary" type="button" data-dialog-add-stock="${item.pk}" aria-label="Add ${esc(item.label || `item ${item.pk}`)}" ${whole(item.available) < 1 ? 'disabled' : ''}>Add</button>
                </div>`).join('');
            const variants = part.variants || [];
            const variantRows = variants.map((variant) => `
                <div class="stock-row">
                    <div class="stock-row-main">
                        <div class="stock-row-title">${esc(variant.name)}${variant.ipn ? ` · ${esc(variant.ipn)}` : ''}</div>
                        <div class="stock-row-meta">${variant.trackable ? 'Tracked asset · ' : ''}${whole(variant.available)} available</div>
                    </div>
                    <button class="it-btn it-btn-small it-btn-primary" type="button" data-dialog-add-variant="${variant.pk}" aria-label="Add ${esc(variant.name)}" ${whole(variant.available) < 1 ? 'disabled' : ''}>Add</button>
                </div>`).join('');
            const addControl = stockItems.length
                ? (part.trackable
                    ? `<p class="stock-row-meta">Choose a specific unit from the list below.</p>`
                    : `<div class="quantity-add">
                        <label class="loan-label" for="dialog-quantity">Quantity</label>
                        <input id="dialog-quantity" type="number" min="1" step="1" value="1" max="${totalAvailable}" data-dialog-quantity>
                        <button class="it-btn it-btn-primary" type="button" data-dialog-add-part aria-label="Add ${esc(part.name)} to request">Add</button>
                    </div>`)
                : `<p class="part-dialog-desc">No units are available to borrow right now.</p>`;

            partDialogContent.innerHTML = `
                <div class="part-dialog-head">
                    <div>
                        <h2 id="part-dialog-title">${esc(part.name)}</h2>
                        <p>${esc(part.ipn || 'No part number')}${part.category ? ` · ${esc(part.category)}` : ''}</p>
                    </div>
                    <button class="it-btn it-btn-small" type="button" data-close-part>Close</button>
                </div>
                <div class="part-dialog-layout">
                    <div class="part-dialog-image">${image}</div>
                    <div>
                        <span class="availability ${availabilityClass}">${totalAvailable > 0 ? `${totalAvailable} available` : 'Unavailable'}</span>
                        ${part.trackable ? '<span class="loan-badge loan-badge-info" style="margin-left:6px">Tracked asset</span>' : ''}
                        <p class="part-dialog-desc">${esc(part.description || 'No description available.')}</p>
                        <div class="part-dialog-section">${addControl}</div>
                        ${variants.length ? `<div class="part-dialog-section"><h3>Variants</h3><div class="stock-list">${variantRows}</div></div>` : ''}
                        ${stockItems.length ? `<div class="part-dialog-section"><h3>${part.trackable ? 'Available units' : 'Stock'}</h3><div class="stock-list">${stockRows}</div></div>` : ''}
                    </div>
                </div>`;

            partDialogContent.querySelector('[data-close-part]')?.addEventListener('click', closePartDialog);
            partDialogContent.querySelector('[data-dialog-add-part]')?.addEventListener('click', () => {
                const quantity = Math.max(1, Math.round(num(partDialogContent.querySelector('[data-dialog-quantity]')?.value || 1)));
                addPart(part, quantity);
                closePartDialog();
            });
            partDialogContent.querySelectorAll('[data-dialog-add-stock]').forEach((button) => {
                button.addEventListener('click', () => {
                    const item = stockItems.find((entry) => String(entry.pk) === button.dataset.dialogAddStock);
                    if (item) {
                        addStockItem(item, {
                            pk: item.part,
                            name: item.part_name,
                            ipn: item.ipn,
                            trackable: item.trackable
                        });
                        closePartDialog();
                    }
                });
            });
            partDialogContent.querySelectorAll('[data-dialog-add-variant]').forEach((button) => {
                button.addEventListener('click', () => {
                    const variant = variants.find((entry) => String(entry.pk) === button.dataset.dialogAddVariant);
                    if (!variant) return;
                    if (variant.trackable) {
                        openPart(variant.pk, variant);
                    } else {
                        addPart(variant, 1);
                        closePartDialog();
                    }
                });
            });
        };

        const openPart = async (pk, fallback = null) => {
            if (!partDialog || !partDialogContent) return;
            if (!partDialog.open) partDialog.showModal();
            partDialogContent.innerHTML = '<p class="catalog-empty">Loading item details…</p>';
            try {
                const part = await api(`${L.api.publicPart.replace('/0/', `/${pk}/`)}`);
                renderPartDialog(part);
            } catch (error) {
                if (fallback) {
                    renderPartDialog(fallback);
                } else {
                    partDialogContent.innerHTML = `<p class="catalog-empty">${esc(formatError(error))}</p>`;
                }
            }
        };

        if (partDialog) {
            partDialog.addEventListener('click', (event) => {
                if (event.target === partDialog) closePartDialog();
            });
        }

        const renderPager = () => {
            if (!pager) return;
            const pages = Math.max(Math.ceil(state.total / state.limit), 1);
            const current = state.page;
            const buttons = [];
            buttons.push(`<button class="it-page-btn" type="button" data-page="${current - 1}" ${current <= 0 ? 'disabled' : ''} aria-label="Previous page">‹</button>`);
            const first = Math.max(0, current - 2);
            const last = Math.min(pages - 1, first + 4);
            for (let page = first; page <= last; page += 1) {
                buttons.push(`<button class="it-page-btn ${page === current ? 'is-active' : ''}" type="button" data-page="${page}" aria-current="${page === current ? 'page' : 'false'}">${page + 1}</button>`);
            }
            buttons.push(`<button class="it-page-btn" type="button" data-page="${current + 1}" ${current >= pages - 1 ? 'disabled' : ''} aria-label="Next page">›</button>`);
            pager.innerHTML = buttons.join('');
            pager.querySelectorAll('[data-page]').forEach((button) => {
                button.addEventListener('click', () => {
                    if (button.disabled) return;
                    state.page = Number(button.dataset.page);
                    loadCatalog();
                });
            });
            if (pageInfo) {
                const start = state.total ? state.page * state.limit + 1 : 0;
                const end = Math.min((state.page + 1) * state.limit, state.total);
                pageInfo.textContent = `${start.toLocaleString()} - ${end.toLocaleString()} / ${state.total.toLocaleString()}`;
            }
        };

        const renderResults = (parts) => {
            if (resultCount) resultCount.textContent = `${state.total.toLocaleString()} ${state.total === 1 ? 'item' : 'items'}`;
            if (!parts.length) {
                resultsContainer.innerHTML = '<tr><td colspan="6" class="it-table-empty">No matching items. Try another category or search.</td></tr>';
                renderPager();
                return;
            }
            resultsContainer.innerHTML = parts.map((part) => {
                const available = whole(part.available);
                return `<tr>
                    <td><button class="it-link" type="button" data-open-part="${part.pk}" aria-label="View details for ${esc(part.name)}">${esc(part.name)}</button>${part.variant_count ? `<div class="part-card-meta">${part.variant_count} variant${part.variant_count === 1 ? '' : 's'}</div>` : ''}</td>
                    <td>${esc(part.ipn || '—')}</td>
                    <td class="it-ellipsis" title="${esc(part.description || '')}">${esc(part.description || '—')}</td>
                    <td>${esc(part.category || '—')}</td>
                    <td class="it-num">${available > 0 ? available.toLocaleString() : '<span class="it-dim">Unavailable</span>'}</td>
                    <td class="it-actions">
                        <button class="it-btn it-btn-light it-btn-small" type="button" data-add-part="${part.pk}" aria-label="Add ${esc(part.name)} to request" ${available < 1 ? 'disabled' : ''}>Add</button>
                    </td>
                </tr>`;
            }).join('');
            resultsContainer.querySelectorAll('[data-open-part]').forEach((button) => {
                button.addEventListener('click', () => openPart(button.dataset.openPart));
            });
            resultsContainer.querySelectorAll('[data-add-part]').forEach((button) => {
                button.addEventListener('click', () => {
                    const part = state.parts.get(String(button.dataset.addPart));
                    if (!part) return;
                    if (part.trackable || part.is_template) {
                        openPart(part.pk, part);
                    } else {
                        addPart(part, 1);
                    }
                });
            });
            renderPager();
        };

        const loadCatalog = async () => {
            if (!resultsContainer) return;
            const sequence = ++loadSequence;
            resultsContainer.innerHTML = '<tr><td colspan="6" class="it-table-empty">Loading catalogue…</td></tr>';
            const params = new URLSearchParams({
                limit: String(state.limit),
                offset: String(state.page * state.limit)
            });
            if (state.search) params.set('search', state.search);
            if (state.category) params.set('category', state.category);
            try {
                const data = await api(`${L.api.publicCatalog}?${params.toString()}`);
                if (sequence !== loadSequence) return;
                const parts = data.results || [];
                state.total = num(data.total);
                state.parts = new Map(parts.map((part) => [String(part.pk), part]));
                renderResults(parts);
            } catch (error) {
                if (sequence !== loadSequence) return;
                resultsContainer.innerHTML = `<tr><td colspan="6" class="it-table-empty">${esc(formatError(error))}</td></tr>`;
            }
        };

        categoryButtons.forEach((button) => {
            button.addEventListener('click', () => {
                categoryButtons.forEach((item) => {
                    item.classList.remove('is-active');
                    item.setAttribute('aria-pressed', 'false');
                });
                button.classList.add('is-active');
                button.setAttribute('aria-pressed', 'true');
                state.category = button.dataset.categoryId || '';
                state.page = 0;
                if (heading) {
                    heading.textContent = button.querySelector('span')?.textContent || button.textContent;
                }
                loadCatalog();
            });
        });

        if (searchInput) {
            searchInput.addEventListener('input', debounce(() => {
                state.search = searchInput.value.trim();
                state.page = 0;
                loadCatalog();
            }, 220));
        }

        const handleScan = async (barcode) => {
            if (!barcode) return;
            if (scanResult) {
                scanResult.className = 'catalog-scan-result';
                scanResult.textContent = 'Looking up barcode…';
            }
            try {
                const found = await api(L.api.publicScan, {
                    method: 'POST',
                    body: JSON.stringify({ barcode })
                });
                if (!found.success) {
                    if (scanResult) {
                        scanResult.className = 'catalog-scan-result is-error';
                        scanResult.textContent = found.error || 'No match found.';
                    }
                    return;
                }
                if (found.type === 'stockitem') {
                    addStockItem(found.data, {
                        pk: found.data.part,
                        name: found.data.part_name,
                        ipn: found.data.ipn
                    });
                    if (scanResult) {
                        scanResult.className = 'catalog-scan-result is-success';
                        scanResult.textContent = `${found.data.part_name} added to the request.`;
                    }
                } else if (found.type === 'part') {
                    openPart(found.data.pk, { ...found.data, available: 0, stock_items: [] });
                    if (scanResult) {
                        scanResult.className = 'catalog-scan-result is-success';
                        scanResult.textContent = `Showing ${found.data.name}.`;
                    }
                } else {
                    throw new Error('That barcode belongs to a loan, not an item.');
                }
            } catch (error) {
                if (scanResult) {
                    scanResult.className = 'catalog-scan-result is-error';
                    scanResult.textContent = formatError(error);
                }
            }
        };

        if (scanForm) {
            scanForm.addEventListener('submit', (event) => {
                event.preventDefault();
                const barcode = scanInput.value.trim();
                scanInput.value = '';
                handleScan(barcode);
            });
        }

        // Signature pad
        const signatureCanvas = $('[data-signature-canvas]', root);
        let signatureValue = '';
        let clearSignature = () => {};
        if (signatureCanvas) {
            const context = signatureCanvas.getContext('2d');
            let drawing = false;
            let lastPoint = null;
            const setupCanvas = () => {
                const ratio = window.devicePixelRatio || 1;
                const width = Math.max(signatureCanvas.clientWidth || 600, 280);
                signatureCanvas.width = Math.round(width * ratio);
                signatureCanvas.height = Math.round(150 * ratio);
                context.setTransform(ratio, 0, 0, ratio, 0, 0);
                context.lineWidth = 2;
                context.lineCap = 'round';
                context.lineJoin = 'round';
                context.strokeStyle = '#17212b';
            };
            window.requestAnimationFrame(setupCanvas);
            const point = (event) => {
                const rect = signatureCanvas.getBoundingClientRect();
                return { x: event.clientX - rect.left, y: event.clientY - rect.top };
            };
            signatureCanvas.addEventListener('pointerdown', (event) => {
                event.preventDefault();
                drawing = true;
                lastPoint = point(event);
                signatureCanvas.setPointerCapture?.(event.pointerId);
            });
            signatureCanvas.addEventListener('pointermove', (event) => {
                if (!drawing) return;
                event.preventDefault();
                const next = point(event);
                context.beginPath();
                context.moveTo(lastPoint.x, lastPoint.y);
                context.lineTo(next.x, next.y);
                context.stroke();
                lastPoint = next;
            });
            const finish = (event) => {
                if (!drawing) return;
                event.preventDefault();
                drawing = false;
                lastPoint = null;
                signatureValue = signatureCanvas.toDataURL('image/png');
            };
            signatureCanvas.addEventListener('pointerup', finish);
            signatureCanvas.addEventListener('pointerleave', finish);
            clearSignature = () => {
                context.clearRect(0, 0, signatureCanvas.width, signatureCanvas.height);
                signatureValue = '';
            };
            $('[data-signature-clear]', root)?.addEventListener('click', clearSignature);
        }

        submit?.addEventListener('click', async (event) => {
            event.preventDefault();
            clearError(errorBox);
            $$('.field-error', root).forEach((error) => error.remove());
            $$('[aria-invalid="true"]', root).forEach((field) => clearFieldError(field));
            successBox.hidden = true;
            const name = $('#requester_name')?.value.trim() || '';
            const email = $('#requester_email')?.value.trim() || '';
            const phone = $('#requester_phone')?.value.trim() || '';
            const organization = $('#requester_organization')?.value.trim() || '';
            const identifier = $('#requester_identifier')?.value.trim() || '';
            const purpose = $('#purpose')?.value.trim() || '';
            const project = $('#project')?.value.trim() || '';
            const notes = $('#notes')?.value.trim() || '';
            const acknowledged = $('#responsibility_ack')?.checked;
            const neededBy = $('#needed_by')?.value;
            const returnBy = $('#return_by')?.value;
            const fail = (message, field) => {
                showError(errorBox, message);
                if (field?.type !== 'checkbox') setFieldError(field, message);
                field?.focus();
                return undefined;
            };
            if (!state.lines.length) {
                showError(errorBox, 'Add at least one item to the request.');
                searchInput?.focus();
                return undefined;
            }
            if (!name) return fail('Enter your full name.', $('#requester_name'));
            if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
                return fail('Enter a valid email address.', $('#requester_email'));
            }
            if (!purpose) return fail('Describe what you will use the items for.', $('#purpose'));
            if (!acknowledged) return fail('Accept the responsibility statement to continue.', $('#responsibility_ack'));
            if (!signatureValue) return fail('Sign the request before sending it.', signatureCanvas);
            if (neededBy && returnBy && returnBy < neededBy) {
                return fail('Choose a return date on or after the pickup date.', $('#return_by'));
            }

            const payload = {
                requester_name: name,
                requester_email: email,
                requester_phone: phone,
                requester_organization: organization,
                requester_identifier: identifier,
                lines: state.lines.map((line) => ({
                    part_id: line.part_id,
                    stock_item_id: line.stock_item_id,
                    quantity: line.quantity
                })),
                purpose,
                needed_by: neededBy || null,
                return_by: returnBy || null,
                notes,
                contact: phone,
                project,
                responsibility_ack: Boolean(acknowledged),
                signature: signatureValue
            };
            setBusy(submit, true, 'Sending…');
            try {
                const created = await api(L.api.publicRequests, {
                    method: 'POST',
                    body: JSON.stringify(payload)
                });
                state.lines = [];
                renderCart();
                closeBasket();
                clearSignature();
                showSuccess(
                    successBox,
                    `Your request reference is <strong>${esc(created.reference)}</strong>.<br><a href="${esc(created.track_url)}">Track this request</a> · <a href="${esc(created.receipt_url)}" target="_blank" rel="noopener">Print request receipt</a>.`
                );
                submit.innerHTML = 'Request sent';
                submit.disabled = true;
                successBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
            } catch (error) {
                setBusy(submit, false);
                showError(errorBox, formatError(error));
            }
        });

        $$('.loan-input, .loan-textarea', root).forEach((field) => {
            field.addEventListener('input', () => clearFieldError(field));
            field.addEventListener('change', () => clearFieldError(field));
        });
        signatureCanvas?.addEventListener('pointerdown', () => clearFieldError(signatureCanvas));
        renderCart();
        loadCatalog();
    }

    /* ------------------------------------------------------------------
       Request actions
       ------------------------------------------------------------------ */
    function initRequestActions() {
        $$('[data-request-action]').forEach((button) => {
            button.addEventListener('click', async () => {
                const id = button.dataset.requestId;
                const action = button.dataset.requestAction;
                if (!id || !action) return;
                let notes = '';
                if (action !== 'cancel') {
                    notes = await askNote({
                        title: action === 'approve' ? 'Approve request' : 'Reject request',
                        message: action === 'approve'
                            ? 'Optionally add a note for the requester.'
                            : 'Explain why this request is being rejected.',
                        submitLabel: action === 'approve' ? 'Approve' : 'Reject',
                        danger: action === 'reject'
                    });
                    if (notes === null) return;
                } else {
                    if (!window.confirm('Cancel this request?')) return;
                }
                setBusy(button, true);
                try {
                    await api(`${L.api.requests}${id}/${action}/`, {
                        method: 'POST',
                        body: JSON.stringify({ notes })
                    });
                    window.location.reload();
                } catch (error) {
                    setBusy(button, false);
                    window.alert(formatError(error));
                }
            });
        });
    }

    /* ------------------------------------------------------------------
       Checkout
       ------------------------------------------------------------------ */
    function initCheckout() {
        const root = $('[data-checkout]');
        if (!root) return;
        const requestId = root.dataset.requestId ? Number(root.dataset.requestId) : null;
        const state = {
            borrowerId: root.dataset.borrowerId ? Number(root.dataset.borrowerId) : null,
            borrowerName: '',
            lines: []
        };

        const scanForm = $('[data-checkout-scan-form]');
        const scanInput = $('[data-checkout-scan]');
        const scanResult = $('[data-checkout-scan-result]');
        const searchInput = $('[data-checkout-catalog]');
        const searchResults = $('[data-checkout-results]');
        const borrowerInput = $('[data-borrower-search]');
        const borrowerResults = $('[data-borrower-results]');
        const borrowerCard = $('[data-borrower-selected]');
        const body = $('[data-checkout-body]');
        const cart = $('[data-checkout-cart]');
        const empty = $('[data-checkout-empty]');
        const count = $('[data-checkout-count]');
        const submit = $('[data-checkout-submit]');
        const errorBox = $('[data-checkout-error]');
        const successBox = $('[data-checkout-success]');

        const renderCart = () => {
            count.textContent = String(state.lines.length);
            if (!state.lines.length) {
                empty.hidden = false;
                cart.hidden = true;
                body.innerHTML = '';
                return;
            }
            empty.hidden = true;
            cart.hidden = false;
            body.innerHTML = state.lines.map((line, index) => `
                <tr>
                    <td><strong>${esc(line.name)}</strong>${line.stock_item_id ? `<div class="loan-muted">Asset: ${esc(line.label || line.stock_item_id)}</div>` : ''}</td>
                    <td><input class="loan-input loan-qty-input" type="number" min="${line.stock_item_id ? 1 : 0.00001}" step="any" value="${line.quantity}" data-checkout-qty="${index}" aria-label="Quantity for ${esc(line.name)}"></td>
                    <td><button class="loan-icon-btn" type="button" data-checkout-remove="${index}" aria-label="Remove ${esc(line.name)}"><i class="fas fa-trash" aria-hidden="true"></i></button></td>
                </tr>`).join('');
            body.querySelectorAll('[data-checkout-qty]').forEach((input) => {
                input.addEventListener('change', () => {
                    const index = Number(input.dataset.checkoutQty);
                    state.lines[index].quantity = Math.max(num(input.value), 0.00001);
                    input.value = state.lines[index].quantity;
                });
            });
            body.querySelectorAll('[data-checkout-remove]').forEach((button) => {
                button.addEventListener('click', () => {
                    state.lines.splice(Number(button.dataset.checkoutRemove), 1);
                    renderCart();
                });
            });
        };

        const addPart = (part) => {
            const existing = state.lines.find((line) => !line.stock_item_id && line.part_id === part.pk);
            if (existing) existing.quantity += 1;
            else state.lines.push({
                part_id: part.pk,
                stock_item_id: null,
                name: part.name,
                label: '',
                quantity: 1
            });
            renderCart();
        };

        const addStockItem = (item, part) => {
            if (state.lines.some((line) => line.stock_item_id === item.pk)) {
                if (scanResult) {
                    scanResult.className = 'loan-scan-result is-error';
                    scanResult.textContent = 'That asset is already in the loan.';
                }
                return;
            }
            if (item.on_loan) {
                if (scanResult) {
                    scanResult.className = 'loan-scan-result is-error';
                    scanResult.textContent = `This item is already on loan${item.loan_reference ? ` (${item.loan_reference})` : ''}.`;
                }
                return;
            }
            state.lines.push({
                part_id: item.part,
                stock_item_id: item.pk,
                name: part.name,
                label: item.serial || `#${item.pk}`,
                quantity: 1
            });
            renderCart();
            if (scanResult) {
                scanResult.className = 'loan-scan-result is-success';
                scanResult.textContent = `${part.name} added.`;
            }
        };

        if (searchInput) {
            searchInput.addEventListener('input', debounce(() => {
                searchCatalog(searchInput.value.trim(), searchResults, (part) => {
                    addPart(part);
                    if (scanResult) {
                        scanResult.className = 'loan-scan-result is-success';
                        scanResult.textContent = `${part.name} added.`;
                    }
                });
            }));
        }

        if (borrowerInput) {
            borrowerInput.addEventListener('input', debounce(async () => {
                const query = borrowerInput.value.trim();
                if (query.length < 2) {
                    borrowerResults.innerHTML = '';
                    return;
                }
                borrowerResults.innerHTML = '<p class="loan-muted loan-small">Searching…</p>';
                try {
                    const data = await api(`${L.api.userSearch}?search=${encodeURIComponent(query)}`);
                    const results = data.results || [];
                    if (!results.length) {
                        borrowerResults.innerHTML = '<p class="loan-muted loan-small">No users found.</p>';
                        return;
                    }
                    borrowerResults.innerHTML = results.map((user) => `
                        <div class="loan-result-card">
                            <div><div class="loan-result-title">${esc(user.name)}</div><div class="loan-result-meta">${esc(user.username)}${user.email ? ` · ${esc(user.email)}` : ''}</div></div>
                            <button class="loan-btn loan-btn-sm loan-btn-primary" type="button" data-select-borrower="${user.pk}" data-borrower-label="${esc(user.name)}" data-borrower-mail="${esc(user.email || '')}">Select</button>
                        </div>`).join('');
                    borrowerResults.querySelectorAll('[data-select-borrower]').forEach((button) => {
                        button.addEventListener('click', () => {
                            state.borrowerId = Number(button.dataset.selectBorrower);
                            state.borrowerName = button.dataset.borrowerLabel;
                            borrowerCard.hidden = false;
                            $('[data-borrower-name]', borrowerCard).textContent = button.dataset.borrowerLabel;
                            $('[data-borrower-email]', borrowerCard).textContent = button.dataset.borrowerMail;
                            borrowerResults.innerHTML = '';
                            borrowerInput.value = '';
                        });
                    });
                } catch (error) {
                    borrowerResults.innerHTML = `<p class="loan-form-error">${esc(formatError(error))}</p>`;
                }
            }));
        }
        $('[data-borrower-clear]')?.addEventListener('click', () => {
            state.borrowerId = null;
            borrowerCard.hidden = true;
        });

        const handleScan = async (barcode) => {
            if (!barcode) return;
            if (scanResult) {
                scanResult.className = 'loan-scan-result';
                scanResult.textContent = 'Looking up barcode…';
            }
            try {
                const found = await api(L.api.scan, { method: 'POST', body: JSON.stringify({ barcode }) });
                if (!found.success) {
                    if (scanResult) {
                        scanResult.className = 'loan-scan-result is-error';
                        scanResult.textContent = found.error || 'No match found.';
                    }
                    return;
                }
                if (found.type === 'loan') {
                    window.location.href = `${L.urls.returnPage}?loan_id=${found.data.pk}`;
                    return;
                }
                if (found.type === 'stockitem') {
                    addStockItem(found.data, { name: found.data.part_name });
                } else if (found.type === 'part') {
                    addPart({ ...found.data });
                } else {
                    throw new Error('Unsupported barcode type.');
                }
            } catch (error) {
                if (scanResult) {
                    scanResult.className = 'loan-scan-result is-error';
                    scanResult.textContent = formatError(error);
                }
            }
        };

        if (scanForm) {
            scanForm.addEventListener('submit', (event) => {
                event.preventDefault();
                if (requestId) {
                    scanResult.className = 'loan-scan-result is-error';
                    scanResult.textContent = 'This loan is prepared from the request. Use the request lines above.';
                    return;
                }
                const barcode = scanInput.value.trim();
                scanInput.value = '';
                handleScan(barcode);
            });
        }

        submit?.addEventListener('click', async (event) => {
            event.preventDefault();
            clearError(errorBox);
            $$('.field-error', root).forEach((error) => error.remove());
            $$('[aria-invalid="true"]', root).forEach((field) => clearFieldError(field));
            successBox.hidden = true;
            const due = $('[data-checkout-due]')?.value;
            const notes = $('[data-checkout-notes]')?.value.trim() || '';
            if (!requestId && !state.borrowerId) return showError(errorBox, 'Select a borrower.');
            if (!requestId && !state.lines.length) return showError(errorBox, 'Add at least one item.');

            const payload = requestId
                ? { request_id: requestId, due_at: due ? `${due}T23:59:59` : null, notes }
                : {
                    borrower_id: state.borrowerId,
                    due_at: due ? `${due}T23:59:59` : null,
                    notes,
                    items: state.lines.map((line) => ({
                        part_id: line.part_id,
                        stock_item_id: line.stock_item_id,
                        quantity: line.quantity
                    }))
                };
            setBusy(submit, true, 'Handing out…');
            try {
                const loan = await api(L.api.checkout, { method: 'POST', body: JSON.stringify(payload) });
                state.lines = [];
                renderCart();
                showSuccess(successBox, `
                    <strong>Loan ${esc(loan.reference)} issued.</strong>
                    <div class="loan-success-actions">
                        <a class="loan-btn loan-btn-sm" href="${L.urls.loanDetail}${loan.pk}/">View loan</a>
                        <a class="loan-btn loan-btn-sm" href="${loan.receipt_url}" target="_blank" rel="noopener">Print receipt</a>
                        <a class="loan-btn loan-btn-sm loan-btn-primary" href="${L.urls.checkout}">New handout</a>
                    </div>`);
                setBusy(submit, false);
            } catch (error) {
                setBusy(submit, false);
                showError(errorBox, formatError(error));
            }
        });

        const scanParam = new URLSearchParams(window.location.search).get('scan');
        if (scanParam) handleScan(scanParam);
        renderCart();
    }

    /* ------------------------------------------------------------------
       Returns
       ------------------------------------------------------------------ */
    function initReturn() {
        const root = $('[data-return]');
        if (!root) return;
        const scanForm = $('[data-return-scan-form]');
        const scanInput = $('[data-return-scan]');
        const scanResult = $('[data-return-scan-result]');
        const panel = $('[data-return-panel]');
        const body = $('[data-return-body]');
        const submit = $('[data-return-submit]');
        const errorBox = $('[data-return-error]');
        const successBox = $('[data-return-success]');
        const returnAll = $('[data-return-all]');
        const state = { loan: null };

        const renderLoan = (loan) => {
            state.loan = loan;
            panel.hidden = false;
            $('[data-return-reference]').textContent = loan.reference;
            $('[data-return-meta]').textContent = `${loan.item_count} item(s) · issued ${loan.issued_at.slice(0, 10)}`;
            $('[data-return-status]').innerHTML = statusBadge(loan.status, loan.status_display);
            $('[data-return-borrower]').textContent = loan.borrower;
            $('[data-return-due]').textContent = loan.due_at.slice(0, 16).replace('T', ' ');
            const openItems = (loan.items || []).filter((item) => !item.lost && num(item.remaining_quantity) > 0);
            $('[data-return-count]').textContent = `${openItems.length} open item(s)`;
            body.innerHTML = openItems.map((item) => `
                <tr data-return-item="${item.pk}">
                    <td><strong>${esc(item.part_name)}</strong>${item.ipn ? `<div class="loan-muted">${esc(item.ipn)}</div>` : ''}</td>
                    <td>${esc(item.stock_item_label)}</td>
                    <td>${item.remaining_quantity}</td>
                    <td><input class="loan-input loan-qty-input" type="number" min="0" max="${item.remaining_quantity}" step="any" value="${item.remaining_quantity}" data-return-qty="${item.pk}" aria-label="Return quantity for ${esc(item.part_name)}"></td>
                    <td>
                        <select class="loan-select" data-return-condition="${item.pk}" aria-label="Condition for ${esc(item.part_name)}">
                            <option value="good">Good</option>
                            <option value="damaged">Damaged</option>
                            <option value="incomplete">Incomplete</option>
                            <option value="other">Other</option>
                        </select>
                    </td>
                </tr>`).join('');
            if (returnAll?.checked) {
                body.querySelectorAll('[data-return-qty]').forEach((input) => {
                    input.value = input.max;
                });
            }
            if (!openItems.length) {
                body.innerHTML = '<tr><td colspan="5"><div class="loan-empty"><i class="fas fa-circle-check" aria-hidden="true"></i><strong>All items have been returned.</strong></div></td></tr>';
            }
        };

        const loadLoan = async (id) => {
            try {
                const loan = await api(`${L.api.loans}${id}/`);
                renderLoan(loan);
                if (scanResult) {
                    scanResult.className = 'loan-scan-result is-success';
                    scanResult.textContent = `Loan ${loan.reference} loaded.`;
                }
            } catch (error) {
                if (scanResult) {
                    scanResult.className = 'loan-scan-result is-error';
                    scanResult.textContent = formatError(error);
                }
            }
        };

        if (returnAll) {
            returnAll.addEventListener('change', () => {
                if (!returnAll.checked) return;
                body.querySelectorAll('[data-return-qty]').forEach((input) => {
                    input.value = input.max;
                });
            });
        }

        const handleScan = async (barcode) => {
            if (!barcode) return;
            if (scanResult) {
                scanResult.className = 'loan-scan-result';
                scanResult.textContent = 'Looking up barcode…';
            }
            try {
                const found = await api(L.api.scan, { method: 'POST', body: JSON.stringify({ barcode }) });
                if (!found.success) {
                    if (scanResult) {
                        scanResult.className = 'loan-scan-result is-error';
                        scanResult.textContent = found.error || 'No match found.';
                    }
                    return;
                }
                if (found.type === 'loan') {
                    await loadLoan(found.data.pk);
                } else if (found.type === 'stockitem' && found.data.loan_id) {
                    await loadLoan(found.data.loan_id);
                } else {
                    throw new Error('That item is not currently on loan.');
                }
            } catch (error) {
                if (scanResult) {
                    scanResult.className = 'loan-scan-result is-error';
                    scanResult.textContent = formatError(error);
                }
            }
        };

        if (scanForm) {
            scanForm.addEventListener('submit', (event) => {
                event.preventDefault();
                const barcode = scanInput.value.trim();
                scanInput.value = '';
                handleScan(barcode);
            });
        }

        submit?.addEventListener('click', async (event) => {
            event.preventDefault();
            if (!state.loan) return showError(errorBox, 'Scan or load a loan first.');
            clearError(errorBox);
            $$('.field-error', root).forEach((error) => error.remove());
            $$('[aria-invalid="true"]', root).forEach((field) => clearFieldError(field));
            successBox.hidden = true;
            const lines = [];
            body.querySelectorAll('[data-return-qty]').forEach((input) => {
                const quantity = num(input.value);
                if (quantity <= 0) return;
                const itemId = Number(input.dataset.returnQty);
                const condition = $(`[data-return-condition="${itemId}"]`)?.value || 'good';
                lines.push({ item_id: itemId, quantity, condition });
            });
            if (!lines.length) return showError(errorBox, 'Enter at least one return quantity.');
            setBusy(submit, true, 'Returning…');
            try {
                const loan = await api(`${L.api.loans}${state.loan.pk}/return/`, {
                    method: 'POST',
                    body: JSON.stringify({ lines, notes: $('#return-notes')?.value.trim() || '' })
                });
                renderLoan(loan);
                showSuccess(successBox, loan.status === 'returned'
                    ? `Loan ${esc(loan.reference)} is fully returned.`
                    : `Partial return recorded for ${esc(loan.reference)}.`);
                setBusy(submit, false);
            } catch (error) {
                setBusy(submit, false);
                showError(errorBox, formatError(error));
            }
        });

        const initial = root.dataset.initialLoan;
        if (initial) loadLoan(initial);
    }

    /* ------------------------------------------------------------------
       Loan detail actions
       ------------------------------------------------------------------ */
    function initLoanDetail() {
        const root = $('[data-loan-id]');
        if (!root) return;
        const loanId = root.dataset.loanId;

        $('[data-renew-submit]')?.addEventListener('click', async (event) => {
            const button = event.currentTarget;
            const due = $('[data-renew-due]')?.value;
            const errorBox = $('[data-renew-error]');
            clearError(errorBox);
            if (!due) return showError(errorBox, 'Choose a new due date.');
            setBusy(button, true);
            try {
                await api(`${L.api.loans}${loanId}/renew/`, {
                    method: 'POST',
                    body: JSON.stringify({ due_at: `${due}T23:59:59` })
                });
                window.location.reload();
            } catch (error) {
                setBusy(button, false);
                showError(errorBox, formatError(error));
            }
        });

        $$('[data-lost-item]').forEach((button) => {
            button.addEventListener('click', async () => {
                const notes = await askNote({
                    title: 'Mark item lost',
                    message: 'This closes the line and marks the stock item as Lost. Add any details for the audit trail.',
                    submitLabel: 'Mark lost',
                    danger: true
                });
                if (notes === null) return;
                setBusy(button, true);
                try {
                    await api(`${L.api.loans}${loanId}/items/${button.dataset.lostItem}/lost/`, {
                        method: 'POST',
                        body: JSON.stringify({ notes })
                    });
                    window.location.reload();
                } catch (error) {
                    setBusy(button, false);
                    window.alert(formatError(error));
                }
            });
        });
    }

    /* ------------------------------------------------------------------
       Staff
       ------------------------------------------------------------------ */
    function initStaff() {
        const root = $('[data-staff-page]');
        if (!root) return;
        const errorBox = $('[data-staff-error]');
        const successBox = $('[data-staff-success]');
        const addButton = $('[data-staff-add]');

        addButton?.addEventListener('click', async () => {
            clearError(errorBox);
            $$('.field-error', root).forEach((error) => error.remove());
            $$('[aria-invalid="true"]', root).forEach((field) => clearFieldError(field));
            successBox.hidden = true;
            const username = $('[data-staff-username]')?.value.trim();
            const role = $('[data-staff-role]')?.value || 'approver';
            if (!username) return showError(errorBox, 'Enter a username.');
            setBusy(addButton, true);
            try {
                await api(L.api.staff, {
                    method: 'POST',
                    body: JSON.stringify({ username, role, active: true })
                });
                window.location.reload();
            } catch (error) {
                setBusy(addButton, false);
                showError(errorBox, formatError(error));
            }
        });

        $$('[data-staff-toggle]').forEach((button) => {
            button.addEventListener('click', async () => {
                const id = button.dataset.staffToggle;
                const active = button.dataset.active === 'true';
                setBusy(button, true);
                try {
                    await api(`${L.api.staff}${id}/`, {
                        method: 'PATCH',
                        body: JSON.stringify({ active: !active })
                    });
                    window.location.reload();
                } catch (error) {
                    setBusy(button, false);
                    showError(errorBox, formatError(error));
                }
            });
        });

        $$('[data-staff-remove]').forEach((button) => {
            button.addEventListener('click', async () => {
                if (!window.confirm('Remove this loan staff role?')) return;
                setBusy(button, true);
                try {
                    await api(`${L.api.staff}${button.dataset.staffRemove}/`, { method: 'DELETE' });
                    window.location.reload();
                } catch (error) {
                    setBusy(button, false);
                    showError(errorBox, formatError(error));
                }
            });
        });
    }

    function focusDeskInput() {
        if (!window.matchMedia('(pointer: fine)').matches) return;
        const input = $('[data-checkout-scan]') || $('[data-return-scan]') || $('[data-scan-input]');
        if (input && !input.disabled) {
            input.focus();
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        addCameraButtons();
        initDashboard();
        initRequestForm();
        initRequestActions();
        initCheckout();
        initReturn();
        initLoanDetail();
        initStaff();
        focusDeskInput();
    });
})();
