/**
 * PresenceDetector - nhan dien co nguoi den gan kiosk (CAMERA SO 2).
 *
 * TRANG THAI: engine DA CO va chay duoc (kiosk-intent, tien trinh rieng
 * backend/presence_engine.py, goi qua /api/presence/detect), nhung CHUA duoc cam
 * vao day - xem truoc bang trang thu frontend/presence-test.html. Nguon cam vao
 * nen emit() khi co su kien USER_ENGAGED va goi clear() khi co USER_LEFT.
 * File nay la lop vo (interface) da chot, kem mot nguon "manual" chay bang nut
 * bam de phan huong dan van demo duoc. Cam detector vao chi la viet them mot
 * "source" - KHONG phai sua guide.js. Xem docs/presence_detector.md muc 5.
 *
 * Vong doi:
 *     var p = new PresenceDetector();
 *     p.onPresence(function () { ... });   // dang ky nguoi nghe
 *     p.trigger();                         // bao "co nguoi" (nguon goi vao)
 *
 * CACH CAM CAMERA SO 2 (lam sau):
 *     p.useSource(function (emit) {
 *         // ...mo camera 2, chay vong lap detect...
 *         // moi khi thay nguoi dung truoc kiosk:  emit();
 *         return function () { ...dong camera... };   // ham don dep (tuy chon)
 *     });
 * Goi useSource() se doi mode sang 'camera', guide.js tu an nut bam thu cong.
 *
 * Chong kich hoat lien tuc: vong lap detect ban emit() moi khung hinh cung chi
 * lam onPresence chay mot lan trong `cooldownMs`. Khi nguoi roi di, nguon goi
 * p.clear() de cho phep kich hoat lai ngay.
 */
(function (root) {
    'use strict';

    var DEFAULT_COOLDOWN_MS = 30000;   // 30s: du de ke tiep theo khong bi doc lai tu dau

    function PresenceDetector(options) {
        options = options || {};
        this._handlers = [];
        this._stopSource = null;
        this._lastAt = 0;
        this.cooldownMs = options.cooldownMs != null ? options.cooldownMs : DEFAULT_COOLDOWN_MS;

        // 'manual' = chua co camera, guide.js hien nut "Bat dau huong dan"
        // 'camera' = da cam nguon nhan dien, an nut bam di
        this.mode = 'manual';
    }

    /** Dang ky viec can lam khi phat hien co nguoi. */
    PresenceDetector.prototype.onPresence = function (cb) {
        if (typeof cb === 'function') this._handlers.push(cb);
    };

    /** Bao "co nguoi". Nguon nhan dien (hoac nut bam) goi ham nay. */
    PresenceDetector.prototype.trigger = function () {
        var now = Date.now();
        if (this._lastAt && now - this._lastAt < this.cooldownMs) return false;
        this._lastAt = now;
        this._handlers.slice().forEach(function (cb) {
            try { cb(); } catch (e) { console.error('[presence] handler loi:', e); }
        });
        return true;
    };

    /** Nguoi da roi di -> cho phep trigger() kich hoat lai ngay. */
    PresenceDetector.prototype.clear = function () {
        this._lastAt = 0;
    };

    /**
     * Cam mot nguon nhan dien.
     * @param {function(function(): void): (function(): void|undefined)} source
     *        Nhan vao ham emit, tra ve ham don dep (tuy chon).
     */
    PresenceDetector.prototype.useSource = function (source) {
        if (typeof source !== 'function') throw new TypeError('source phai la ham');
        this.stopSource();
        var self = this;
        this._stopSource = source(function () { self.trigger(); }) || null;
        this.mode = 'camera';
        return this;
    };

    /** Go nguon nhan dien dang cam, quay ve che do nut bam. */
    PresenceDetector.prototype.stopSource = function () {
        if (typeof this._stopSource === 'function') {
            try { this._stopSource(); } catch (e) { console.error('[presence] stopSource loi:', e); }
        }
        this._stopSource = null;
        this.mode = 'manual';
        return this;
    };

    root.PresenceDetector = PresenceDetector;
    if (typeof module === 'object' && module.exports) module.exports = PresenceDetector;
})(typeof window !== 'undefined' ? window : globalThis);
