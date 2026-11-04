// Pruebas de lógica con DOM/cámara simulados; no sustituyen pruebas de navegador.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const source = readFileSync('static/js/registro_fotografia.js', 'utf8');

function preparar({mobile = false, media} = {}) {
    const elements = new Map();
    let calls = 0, stops = 0;
    const stream = {getTracks: () => [{stop: () => stops++}]};
    function element(id) {
        if (!elements.has(id)) {
            const events = {};
            const e = {files: [], hidden: false, open: false, videoWidth: 640, videoHeight: 480,
                addEventListener: (name, fn) => { (events[name] ||= []).push(fn); },
                emit: async (name, event = {}) => { for (const fn of events[name] || []) await fn(event); },
                click() { this.clicked = true; }, focus() { this.focused = true; },
                showModal() { this.open = true; },
                close() { this.open = false; this.emit('close'); },
                play: async () => {}, reportValidity: () => true,
                setAttribute() {}, removeAttribute() {},
                getContext: () => ({drawImage() {}}),
                toBlob: callback => callback({size: 100, type: 'image/jpeg'}),
            };
            let value = '';
            Object.defineProperty(e, 'value', {get: () => value, set: v => {value = v; if (!v) e.files = [];}});
            elements.set(id, e);
        }
        return elements.get(id);
    }
    class Transfer {
        files = [];
        items = {add: file => this.files.push(file)};
    }
    const windowEvents = {};
    vm.runInNewContext(source, {
        document: {getElementById: id => id === 'resumenErrores' ? null : element(id)},
        window: {isSecureContext: true, matchMedia: () => ({matches: mobile}),
                 addEventListener: (name, fn) => {windowEvents[name] = fn;}},
        navigator: {mediaDevices: {getUserMedia: () => {calls++; return media ? media(stream) : Promise.resolve(stream);}}},
        DataTransfer: Transfer,
        File: class {constructor(parts, name, options) {this.name = name; this.size = parts[0].size; this.type = options.type;}},
        URL: {createObjectURL: () => 'blob:prueba', revokeObjectURL() {}},
    });
    return {element, windowEvents, calls: () => calls, stops: () => stops};
}

test('la cámara requiere acción y libera tracks al cerrar', async () => {
    const app = preparar();
    assert.equal(app.calls(), 0);
    await app.element('tomarFoto').emit('click');
    assert.equal(app.calls(), 1);
    app.element('dialogoCamara').close();
    assert.equal(app.stops(), 1);
});

test('cerrar mientras se esperan permisos libera el stream tardío', async () => {
    let resolver;
    const app = preparar({media: stream => new Promise(resolve => {resolver = () => resolve(stream);})});
    const abrir = app.element('tomarFoto').emit('click');
    app.element('dialogoCamara').close();
    resolver();
    await abrir;
    assert.equal(app.stops(), 1);
    assert.equal(app.element('videoCamara').srcObject, null);
});

test('permiso denegado permite subir archivo', async () => {
    const app = preparar({media: () => Promise.reject(new Error('denegado'))});
    await app.element('tomarFoto').emit('click');
    assert.equal(app.element('dialogoCamara').open, false);
    assert.equal(app.element('id_fotografia').focused, true);
    assert.match(app.element('estadoFoto').textContent, /Subir fotografía/);
});

test('móvil usa captura nativa sin abrir getUserMedia', async () => {
    const app = preparar({mobile: true});
    await app.element('tomarFoto').emit('click');
    assert.equal(app.calls(), 0);
    assert.equal(app.element('fotoCamara').clicked, true);
});

test('captura confirmada usa el archivo canónico y libera cámara', async () => {
    const app = preparar();
    await app.element('tomarFoto').emit('click');
    await app.element('capturarFoto').emit('click');
    await app.element('confirmarFoto').emit('click');
    assert.equal(app.element('id_fotografia').files[0].name, 'captura.jpg');
    assert.equal(app.element('vistaFoto').hidden, false);
    assert.equal(app.stops(), 1);
});

test('requiere foto y bloquea el segundo envío', async () => {
    const app = preparar();
    let rechazados = 0;
    const event = {preventDefault: () => rechazados++};
    await app.element('formTicket').emit('submit', event);
    assert.equal(rechazados, 1);
    app.element('id_fotografia').files = [{name: 'prueba.jpg', size: 100}];
    await app.element('id_fotografia').emit('change');
    await app.element('formTicket').emit('submit', event);
    assert.equal(app.element('enviarIncidencia').disabled, true);
    await app.element('formTicket').emit('submit', event);
    assert.equal(rechazados, 2);
});

test('salir de la página libera cámara', async () => {
    const app = preparar();
    await app.element('tomarFoto').emit('click');
    app.windowEvents.pagehide();
    assert.equal(app.stops(), 1);
});
