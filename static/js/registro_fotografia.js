/* MVP-02: una única evidencia; sin envío ni almacenamiento fuera del formulario. */
(() => {
    'use strict';
    const form = document.getElementById('formTicket');
    if (!form) return;
    const upload = document.getElementById('id_fotografia');
    const native = document.getElementById('fotoCamara');
    const take = document.getElementById('tomarFoto');
    const status = document.getElementById('estadoFoto');
    const preview = document.getElementById('vistaFoto');
    const image = document.getElementById('imagenFoto');
    const dialog = document.getElementById('dialogoCamara');
    const video = document.getElementById('videoCamara');
    const canvas = document.getElementById('fotoCanvas');
    const capture = document.getElementById('capturarFoto');
    const repeat = document.getElementById('repetirFoto');
    const confirm = document.getElementById('confirmarFoto');
    const cameraStatus = document.getElementById('estadoCamara');
    let stream = null, objectURL = null, session = 0, sending = false;

    function releasePreview() {
        if (objectURL) URL.revokeObjectURL(objectURL);
        objectURL = null;
    }

    function stopCamera() {
        session += 1; // Invalida también permisos o conversiones aún pendientes.
        if (stream) stream.getTracks().forEach(track => track.stop());
        stream = null;
        video.srcObject = null;
        canvas.width = canvas.height = 0;
    }

    function showFile(input, other) {
        const file = input.files[0];
        if (!file) return; // Cancelar el selector conserva la selección anterior.
        if (file.size > 5 * 1024 * 1024 || !/\.(jpe?g|png|webp|gif)$/i.test(file.name)) {
            input.value = '';
            status.textContent = 'Usa una imagen JPG, PNG, WEBP o GIF de hasta 5 MB.';
            return;
        }
        other.value = '';
        releasePreview();
        objectURL = URL.createObjectURL(file);
        image.src = objectURL;
        preview.hidden = false;
        document.getElementById('nombreFoto').textContent = file.name;
        status.textContent = 'Fotografía lista. Puedes reemplazarla antes de registrar.';
    }

    image.addEventListener('error', () => {
        preview.hidden = true;
        status.textContent = 'No se pudo mostrar la imagen. Selecciona una fotografía válida.';
    });
    upload.addEventListener('change', () => showFile(upload, native));
    native.addEventListener('change', () => showFile(native, upload));
    document.getElementById('capturaNativa').hidden = true;
    take.hidden = false;

    async function openCamera() {
        // La captura nativa es una alternativa; capture no garantiza una cámara.
        if (window.matchMedia('(pointer: coarse)').matches || !window.isSecureContext ||
                !navigator.mediaDevices?.getUserMedia || !dialog.showModal || typeof DataTransfer === 'undefined') {
            status.textContent = 'El dispositivo elegirá cómo obtener la foto. También puedes usar «Subir fotografía».';
            native.click();
            return;
        }
        stopCamera();
        const current = session;
        canvas.hidden = true;
        video.hidden = false;
        capture.hidden = false;
        capture.disabled = true;
        repeat.hidden = confirm.hidden = true;
        cameraStatus.textContent = 'Esperando acceso a la cámara…';
        if (!dialog.open) dialog.showModal();
        try {
            const opened = await navigator.mediaDevices.getUserMedia({video: {facingMode: {ideal: 'environment'}}, audio: false});
            if (current !== session || !dialog.open) {
                opened.getTracks().forEach(track => track.stop());
                return;
            }
            stream = opened;
            video.srcObject = stream;
            await video.play();
            if (current !== session) return;
            capture.disabled = false;
            cameraStatus.textContent = 'Encuadra el problema y pulsa Capturar.';
        } catch (error) {
            if (current !== session) return;
            dialog.close();
            stopCamera();
            status.textContent = 'No se pudo acceder a la cámara. Comprueba los permisos o usa «Subir fotografía».';
            upload.focus();
        }
    }

    take.addEventListener('click', openCamera);
    document.getElementById('cerrarCamara').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => { stopCamera(); take.focus(); });
    dialog.addEventListener('cancel', stopCamera);
    capture.addEventListener('click', () => {
        if (!video.videoWidth || !video.videoHeight) {
            cameraStatus.textContent = 'La cámara aún no está lista. Intenta nuevamente.';
            return;
        }
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0);
        canvas.hidden = false;
        video.hidden = true;
        capture.hidden = true;
        repeat.hidden = confirm.hidden = false;
        cameraStatus.textContent = 'Revisa la fotografía antes de usarla.';
    });
    repeat.addEventListener('click', openCamera);
    confirm.addEventListener('click', () => {
        const current = session;
        confirm.disabled = true;
        canvas.toBlob(blob => {
            confirm.disabled = false;
            if (current !== session || !dialog.open) return;
            if (!blob) {
                cameraStatus.textContent = 'No se pudo obtener la fotografía. Pulsa Repetir.';
                return;
            }
            try {
                const transfer = new DataTransfer();
                transfer.items.add(new File([blob], 'captura.jpg', {type: 'image/jpeg'}));
                upload.files = transfer.files;
                showFile(upload, native);
                dialog.close();
            } catch (error) {
                dialog.close();
                status.textContent = 'Este navegador no permite adjuntar la captura. Usa «Subir fotografía».';
                upload.focus();
            }
        }, 'image/jpeg', 0.9);
    });

    form.addEventListener('submit', event => {
        if (sending) { event.preventDefault(); return; }
        if (!upload.files.length && !native.files.length) {
            event.preventDefault();
            status.textContent = 'Adjunta una fotografía antes de registrar la incidencia.';
            upload.focus();
            return;
        }
        if (!form.reportValidity()) { event.preventDefault(); return; }
        sending = true;
        stopCamera();
        const submit = document.getElementById('enviarIncidencia');
        submit.disabled = true;
        submit.textContent = 'Registrando…';
        form.setAttribute('aria-busy', 'true');
    });
    window.addEventListener('pagehide', () => { stopCamera(); releasePreview(); });
    window.addEventListener('pageshow', event => {
        if (event.persisted) {
            sending = false;
            form.removeAttribute('aria-busy');
            const submit = document.getElementById('enviarIncidencia');
            submit.disabled = false;
            submit.textContent = 'Registrar incidencia';
        }
    });
    document.getElementById('resumenErrores')?.focus();
})();
