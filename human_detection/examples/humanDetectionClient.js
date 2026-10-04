/**
 * Client trinh duyet cho server human_detection — chep file nay vao web app.
 *
 *   import { HumanDetectionClient } from './humanDetectionClient.js';
 *   const hd = new HumanDetectionClient('http://127.0.0.1:8765');
 *   hd.onEngaged = (event) => startWelcome();   // co nguoi dung vao truoc kiosk
 *   hd.onLeft = (event) => backToIdle();        // nguoi do da di
 *   await hd.start(videoElement);               // <video> dang phat camera
 *
 * Server phai chay voi --cors-origin <origin cua app> (hoac app tu proxy /frame).
 * Gui tuan tu (frame sau doi frame truoc xong) nen tu cham lai theo toc do server.
 */
export class HumanDetectionClient {
    constructor(baseUrl = 'http://127.0.0.1:8765', { intervalMs = 120, quality = 0.8, width = 1280 } = {}) {
        this.baseUrl = baseUrl.replace(/\/$/, '');
        this.intervalMs = intervalMs;
        this.quality = quality;
        this.width = width;       // co frame gui len (giu ti le camera); nho = nhanh hon
        this.onResult = null;     // (result) => {} moi frame
        this.onEngaged = null;    // (event) => {} USER_ENGAGED
        this.onLeft = null;       // (event) => {} USER_LEFT
        this.onError = null;      // (error) => {}
        this._running = false;
        this._canvas = document.createElement('canvas');
    }

    /** Bat dau gui frame tu mot <video> dang phat (getUserMedia). */
    async start(video) {
        this._running = true;
        while (this._running) {
            const started = performance.now();
            try {
                if (video.readyState >= 2 && video.videoWidth) {
                    const result = await this.sendFrame(video);
                    this._dispatch(result);
                }
            } catch (error) {
                if (this.onError) this.onError(error);
            }
            const wait = this.intervalMs - (performance.now() - started);
            if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
        }
    }

    stop() {
        this._running = false;
    }

    /** Chup mot frame tu video/canvas/img roi gui; tra ve ket qua cua server. */
    async sendFrame(source) {
        const sw = source.videoWidth || source.width;
        const sh = source.videoHeight || source.height;
        const scale = Math.min(1, this.width / sw);
        this._canvas.width = Math.round(sw * scale);
        this._canvas.height = Math.round(sh * scale);
        this._canvas.getContext('2d').drawImage(source, 0, 0, this._canvas.width, this._canvas.height);
        const blob = await new Promise((resolve) => this._canvas.toBlob(resolve, 'image/jpeg', this.quality));
        const response = await fetch(`${this.baseUrl}/frame?timestampMs=${Math.round(performance.now())}`, {
            method: 'POST', headers: { 'Content-Type': 'image/jpeg' }, body: blob,
        });
        if (!response.ok) throw new Error(`/frame ${response.status}: ${await response.text()}`);
        return response.json();
    }

    async reset() {
        const response = await fetch(`${this.baseUrl}/reset`, { method: 'POST' });
        return response.json();
    }

    async status() {
        return (await fetch(`${this.baseUrl}/status`)).json();
    }

    _dispatch(result) {
        if (this.onResult) this.onResult(result);
        for (const event of result.events) {
            if (event.event === 'USER_ENGAGED' && this.onEngaged) this.onEngaged(event);
            if (event.event === 'USER_LEFT' && this.onLeft) this.onLeft(event);
        }
    }
}
