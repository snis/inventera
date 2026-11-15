// Execute the rendered page script with controlled AJAX completions.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function page() {
    const handlers = {};
    const requests = [];
    const elements = new Map();
    const document = {};
    function $(key) {
        key = key === document ? 'document' : key;
        if (!elements.has(key)) {
            const state = {value: '2', attrs: {'data-version': '1'}, classes: new Set(['is-dirty'])};
            const element = {
                state,
                ready(fn) { fn(); return this; },
                each() { return this; },
                click(fn) { handlers[key] = fn; return this; },
                on(events, fn) { handlers[key] = fn; return this; },
                data() { return 1; },
                val(value) { if (value === undefined) return state.value; state.value = value; return this; },
                attr(name, value) { if (value === undefined) return state.attrs[name]; state.attrs[name] = value; return this; },
                css() { return this; },
                addClass(name) { state.classes.add(name); return this; },
                removeClass(name) { state.classes.delete(name); return this; },
                text() { return this; },
                find() { return this; }
            };
            elements.set(key, element);
        }
        return elements.get(key);
    }
    $.ajax = request => requests.push(request);
    vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {
        $, document, console, alert() {}, setTimeout() {}, localStorage: {getItem() { return null; }}
    });
    return {
        $, requests,
        click() { handlers['.btn-save'].call('save', {preventDefault() {}}); },
        edit(value) { $('#qty-input-1').val(value); handlers['.input-qty'].call('input'); },
        dirty() { return $('#btn-save-1').state.classes.has('is-dirty'); }
    };
}

const reply = (quantity, version) => ({
    status: 'success', item_id: 1, new_quantity: quantity, version,
    warning_color: 'green', row_color: 'green'
});

// Rapid saves are serialized and the queued save uses the acknowledged version.
const queued = page();
queued.click();
queued.edit('3');
queued.click();
assert.equal(queued.requests.length, 1);
queued.requests[0].success(reply('2', 2));
assert.equal(queued.requests.length, 2);
assert.equal(queued.requests[1].data.new_quantity, '3');
assert.equal(queued.requests[1].data.version, 2);
assert.equal(queued.dirty(), true);
queued.requests[1].success(reply('3', 3));
assert.equal(queued.dirty(), false);

// Editing without another save click must remain visibly unsaved after an old reply.
const edited = page();
edited.click();
edited.edit('3');
edited.requests[0].success(reply('2', 2));
assert.equal(edited.requests.length, 1);
assert.equal(edited.dirty(), true);

// A conflict must leave the edit unsaved and discard queued attempts with a stale version.
const conflict = page();
conflict.click();
conflict.edit('3');
conflict.click();
conflict.requests[0].error({responseJSON: {message: 'Conflict'}});
assert.equal(conflict.requests.length, 1);
assert.equal(conflict.dirty(), true);
assert.equal(conflict.$('#item-row-1').attr('data-version'), '1');
