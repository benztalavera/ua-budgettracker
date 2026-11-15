/* Shared report pagination. No dependencies; keep a readable no-JS source. */
(function () {
    'use strict';
    var source = document.querySelector('.p-doc'), pages, sheets = [], current;
    if (!source) return;
    var originalFooter = source.querySelector('.p-foot');
    var title = source.querySelector('.p-title');
    var company = source.querySelector('.p-company strong');
    var oversized = false, ready = false;
    function fits() {
        // ScrollHeight is rounded; use geometry as well to avoid a hidden 1px spill.
        var body = current.body, last = body.lastElementChild;
        return body.scrollHeight <= body.clientHeight + 1 && (!last || last.getBoundingClientRect().bottom <= body.getBoundingClientRect().bottom + 1);
    }
    function newSheet() {
        var sheet = document.createElement('section');
        sheet.className = 'p-sheet';
        var body = document.createElement('div');
        body.className = 'p-sheet-body';
        sheet.appendChild(body);
        var footer = originalFooter ? originalFooter.cloneNode(true) : document.createElement('footer');
        footer.classList.add('p-foot');
        var number = document.createElement('span');
        number.className = 'p-page-number';
        footer.appendChild(number);
        sheet.appendChild(footer);
        pages.appendChild(sheet);
        current = { sheet: sheet, body: body, number: number };
        sheets.push(current);
        if (sheets.length > 1) {
            var head = document.createElement('div');
            head.className = 'p-continuation';
            var name = document.createElement('strong'); name.textContent = title ? title.textContent : 'Report';
            var org = document.createElement('span'); org.textContent = company ? company.textContent : '';
            head.appendChild(name); head.appendChild(org); body.appendChild(head);
        }
        return current;
    }
    function carryHeading() {
        var last = current.body.lastElementChild;
        if (last && /^H[1-6]$/.test(last.tagName)) { last.remove(); return last; }
        return null;
    }
    function hasContent() {
        return Array.prototype.some.call(current.body.children, function (el) { return !el.classList.contains('p-continuation'); });
    }
    function markOversize() {
        // Do not crop or discard pathological entries taller than a whole sheet.
        // Allow native fragmentation and explicitly avoid claiming an exact count.
        oversized = true;
        current.sheet.classList.add('p-sheet-oversize');
    }
    function appendBlock(node) {
        current.body.appendChild(node);
        var reserve = /^H[1-6]$/.test(node.tagName) ? 50 : 0;
        var enough = fits() && (!reserve || node.getBoundingClientRect().bottom + reserve < current.body.getBoundingClientRect().bottom);
        if (enough) return;
        node.remove();
        var heading = carryHeading();
        if (hasContent()) newSheet();
        if (heading) current.body.appendChild(heading);
        current.body.appendChild(node);
        if (!fits()) markOversize();
    }
    function tableShell(table) {
        var shell = table.cloneNode(false);
        Array.prototype.forEach.call(table.children, function (el) {
            if (/^(COLGROUP|THEAD|CAPTION)$/.test(el.tagName)) shell.appendChild(el.cloneNode(true));
        });
        var body = document.createElement('tbody'); shell.appendChild(body);
        return { table: shell, body: body, count: 0 };
    }
    function appendTable(table) {
        var frag = tableShell(table);
        current.body.appendChild(frag.table);
        var items = [];
        Array.prototype.forEach.call(table.children, function (group) {
            if (group.tagName === 'TBODY') Array.prototype.forEach.call(group.rows, function (row) { items.push(row); });
            // Totals are printed once, together, at the end, not repeated on every page.
            if (group.tagName === 'TFOOT') items.push(group);
        });
        items.forEach(function (item) {
            var clone = item.cloneNode(true);
            function add() { if (clone.tagName === 'TFOOT') frag.table.appendChild(clone); else frag.body.appendChild(clone); }
            add();
            if (!fits()) {
                clone.remove();
                var heading = null;
                if (!frag.count) { frag.table.remove(); heading = carryHeading(); }
                if (hasContent()) newSheet();
                if (heading) current.body.appendChild(heading);
                if (frag.count) frag = tableShell(table);
                current.body.appendChild(frag.table);
                add();
                if (!fits()) markOversize();
            }
            frag.count++;
        });
    }
    function paginate() {
        if (ready) return;
        source.classList.add('p-source');
        pages = document.createElement('main'); pages.id = 'p-pages'; pages.setAttribute('aria-label', 'Print preview pages');
        source.parentNode.insertBefore(pages, source.nextSibling);
        newSheet();
        try {
            Array.prototype.forEach.call(source.children, function (node) {
                if (node.classList.contains('p-foot') || /^(STYLE|SCRIPT)$/.test(node.tagName)) return;
                if (node.tagName === 'TABLE') appendTable(node); else appendBlock(node.cloneNode(true));
            });
            sheets.forEach(function (page, index) {
                page.number.textContent = 'Page ' + (index + 1) + (oversized ? '' : ' of ' + sheets.length);
                page.sheet.setAttribute('aria-label', 'Page ' + (index + 1));
            });
            var note = document.querySelector('.p-bar-title small');
            if (note) note.textContent = 'A4 ' + (document.body.classList.contains('p-landscape') ? 'landscape' : 'portrait') + ' · ' + (oversized ? 'Long entry: use printer page count' : sheets.length + ' page' + (sheets.length === 1 ? '' : 's')) + ' · ' + (note.dataset.org || '');
            if (oversized) {
                var warning = document.createElement('div'); warning.className = 'p-print-warning no-print-bar';
                warning.textContent = 'An entry is taller than a complete sheet. Its full contents are preserved and may continue onto another printed page. Use your browser’s final print-dialog page count.';
                pages.parentNode.insertBefore(warning, pages);
            }
            source.setAttribute('aria-hidden', 'true'); ready = true;
        } catch (error) {
            // A script failure must not make the report blank or hide the data.
            pages.remove(); source.classList.remove('p-source'); source.removeAttribute('aria-hidden');
            if (window.console) console.error('Print pagination:', error);
        }
    }
    window.printReport = function () { paginate(); window.print(); };
    window.addEventListener('beforeprint', paginate);
    window.closePreview = function () {
        var fallback = document.body.getAttribute('data-return') || '/';
        var back = fallback;
        try { if (document.referrer && new URL(document.referrer).origin === location.origin && new URL(document.referrer).searchParams.get('do') !== 'print') back = document.referrer; } catch (e) {}
        if (window.opener) { try { window.close(); } catch (e) {} }
        setTimeout(function () { if (!window.closed) location.href = back; }, 150);
    };
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') window.closePreview(); });
    function settled() {
        var images = Array.prototype.map.call(source.querySelectorAll('img'), function (img) {
            if (img.complete) return Promise.resolve();
            return new Promise(function (resolve) { img.addEventListener('load', resolve, {once:true}); img.addEventListener('error', resolve, {once:true}); });
        });
        if (document.fonts && document.fonts.ready) images.push(document.fonts.ready);
        Promise.all(images).then(paginate);
    }
    if (document.readyState === 'complete') settled(); else window.addEventListener('load', settled);
})();
