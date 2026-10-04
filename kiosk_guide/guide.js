/**
 * Kiosk Guided Tour - bo may dieu khien huong dan nguoi dan.
 *
 * File nay chi lo phan KY THUAT (spotlight, chan click, doi su kien, luu trang thai).
 * Toan bo LOI THOAI va THU TU BUOC nam trong tour-config.js  -> sua noi dung o do.
 * Khong phu thuoc gi vao app ben ngoai: chi can PresenceDetector.js nap truoc.
 * Cach nhung vao app khac: xem README.md cung thu muc.
 *
 * Khong dung ES module de trang khong dung module cung chay duoc.
 */
(function (window, document) {
    'use strict';

    var STORAGE_KEY = 'kiosk_guide_state';
    var MUTE_KEY = 'kiosk_guide_muted';   // nho lua chon tat tieng qua ca 2 trang
    var TARGET_TIMEOUT_MS = 10000;   // toi da cho phan tu muc tieu xuat hien
    var POLL_MS = 250;               // nhip kiem tra dieu kien (vd: da nhan dien giay to chua)

    // Thu muc chua chinh file nay (vd: 'kiosk_guide/') -> tim audio/ theo do, de
    // dat ca thu muc o dau trong app ben kia cung khong phai sua duong dan.
    var BASE_URL = (function () {
        var s = document.currentScript;
        return s && s.src ? s.src.replace(/[?#].*$/, '').replace(/[^/]*$/, '') : '';
    })();

    /* ---------------------------------------------------------------------
     * Narrator - phat file mp3 loi thoai cua tung buoc.
     * Cau hinh trong voice-config.js.
     * Thieu file mp3 -> chi hien chu, tour van chay binh thuong.
     * ------------------------------------------------------------------- */
    function Narrator() {
        var cfg = window.KIOSK_VOICE_CONFIG || {};

        this.enabled = cfg.enabled !== false;
        this.dir = cfg.dir || BASE_URL + 'audio/';
        this.ext = cfg.ext || '.mp3';
        this.volume = cfg.volume != null ? cfg.volume : 1;
        this.audio = null;
        this._unlock = null;

        this.muted = false;
        try { this.muted = localStorage.getItem(MUTE_KEY) === '1'; } catch (e) { }
    }

    /** Phat mp3 cua mot buoc. Goi lai o buoc sau se tu cat tieng cua buoc truoc. */
    Narrator.prototype.say = function (step) {
        this.stop();
        if (!this.enabled || this.muted || !step) return;

        var file = step.audio || step.id;    // mac dinh: <id buoc>.mp3
        if (!file) return;

        var src = this.dir + file + this.ext;
        var audio = new Audio(src);
        audio.volume = this.volume;
        this.audio = audio;

        var self = this;
        var p = audio.play();
        if (p && p.catch) {
            p.catch(function () {
                if (audio.error) {
                    // Chua co file mp3 (404) hoac file hong -> im lang, khong chan tour
                    console.warn('[guide] khong phat duoc: ' + src);
                    return;
                }
                // Trinh duyet chan tu dong phat (vua chuyen trang, chua co thao tac)
                // -> cho nguoi dung cham man hinh mot cai roi phat lai.
                self._retryOnTouch(audio);
            });
        }
    };

    Narrator.prototype._retryOnTouch = function (audio) {
        var self = this;
        var retry = function () {
            document.removeEventListener('pointerdown', retry, true);
            self._unlock = null;
            if (self.audio === audio) audio.play().catch(function () { });
        };
        document.addEventListener('pointerdown', retry, true);
        this._unlock = function () {
            document.removeEventListener('pointerdown', retry, true);
        };
    };

    Narrator.prototype.setMuted = function (muted) {
        this.muted = !!muted;
        try { localStorage.setItem(MUTE_KEY, this.muted ? '1' : '0'); } catch (e) { }
        if (this.muted) this.stop();
    };

    /** Co bat giong doc khong? (enabled: false thi khong hien nut loa) */
    Narrator.prototype.available = function () {
        return this.enabled;
    };

    Narrator.prototype.stop = function () {
        if (this._unlock) { this._unlock(); this._unlock = null; }
        if (this.audio) {
            this.audio.pause();
            this.audio.currentTime = 0;
            this.audio = null;
        }
    };

    /* ---------------------------------------------------------------------
     * PresenceDetector - nhan dien nguoi den gan kiosk (camera so 2).
     * Dinh nghia nam o PresenceDetector.js (cung thu muc), phai nap TRUOC file nay.
     * Chua cam camera -> detector chay o mode 'manual' (nut bam thay the).
     * ------------------------------------------------------------------- */
    var PresenceDetector = window.PresenceDetector;
    if (!PresenceDetector) {
        throw new Error('Thieu PresenceDetector.js - phai nap truoc guide.js');
    }

    /* ---------------------------------------------------------------------
     * Tien ich
     * ------------------------------------------------------------------- */
    function el(tag, cls, parent) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (parent) parent.appendChild(n);
        return n;
    }

    function toArray(v) {
        if (v == null) return [];
        return Array.isArray(v) ? v : [v];
    }

    /** Gia tri trong config co the la ham (tinh lai moi lan doc) hoac gia tri thuong. */
    function valueOf(v) {
        return typeof v === 'function' ? v() : v;
    }

    /** Gop bounding box cua nhieu phan tu thanh mot vung sang duy nhat. */
    function unionRect(nodes) {
        var r = null;
        nodes.forEach(function (n) {
            var b = n.getBoundingClientRect();
            if (b.width === 0 && b.height === 0) return;
            if (!r) {
                r = { top: b.top, left: b.left, right: b.right, bottom: b.bottom };
            } else {
                r.top = Math.min(r.top, b.top);
                r.left = Math.min(r.left, b.left);
                r.right = Math.max(r.right, b.right);
                r.bottom = Math.max(r.bottom, b.bottom);
            }
        });
        if (!r) return null;
        return { top: r.top, left: r.left, width: r.right - r.left, height: r.bottom - r.top };
    }

    /* ---------------------------------------------------------------------
     * Tour engine
     * ------------------------------------------------------------------- */
    function Tour(config) {
        this.steps = config.steps || [];
        this.page = config.page;                  // gia tri data-kiosk-page cua trang dang mo
        this.devMode = !!config.devMode;
        this.narrator = new Narrator();
        this.presence = new PresenceDetector();

        this.active = false;
        this.current = null;
        this.rings = [];
        this._nodes = null;
        this._timer = 0;
        this._raf = 0;
        this._clickCleanups = [];
        this._onResize = this._reposition.bind(this);
    }

    Tour.prototype.stepById = function (id) {
        for (var i = 0; i < this.steps.length; i++) {
            if (this.steps[i].id === id) return this.steps[i];
        }
        return null;
    };

    Tour.prototype.stepIndex = function (id) {
        for (var i = 0; i < this.steps.length; i++) {
            if (this.steps[i].id === id) return i;
        }
        return -1;
    };

    /** Buoc ke tiep theo thu tu khai bao, bo qua buoc thuoc trang khac. */
    Tour.prototype.nextIdAfter = function (id) {
        var i = this.stepIndex(id);
        if (i < 0) return null;
        for (var j = i + 1; j < this.steps.length; j++) {
            return this.steps[j].id;
        }
        return null;
    };

    /* --- Luu / khoi phuc trang thai khi chuyen trang --------------------- */

    Tour.prototype._persist = function (stepId) {
        try {
            sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
                stepId: stepId,
                at: Date.now()
            }));
        } catch (e) { /* rieng tu / het dung luong -> bo qua */ }
    };

    Tour.prototype._clearPersisted = function () {
        try { sessionStorage.removeItem(STORAGE_KEY); } catch (e) { }
    };

    Tour.prototype._readPersisted = function () {
        try {
            var raw = sessionStorage.getItem(STORAGE_KEY);
            if (!raw) return null;
            var data = JSON.parse(raw);
            // Qua 30 phut thi coi nhu phien cu, bo di
            if (!data || Date.now() - data.at > 30 * 60 * 1000) return null;
            return data;
        } catch (e) { return null; }
    };

    /** Goi luc trang vua tai: tiep tuc tour neu buoc dang do thuoc trang nay. */
    Tour.prototype.resumeIfPending = function () {
        var data = this._readPersisted();
        if (!data) return false;
        var step = this.stepById(data.stepId);
        if (!step || step.page !== this.page) return false;
        this.start(data.stepId);
        return true;
    };

    /* --- Vong doi ------------------------------------------------------- */

    Tour.prototype.start = function (stepId) {
        if (this.active) return;
        var first = stepId ? this.stepById(stepId) : null;
        if (!first) {
            first = this.steps.filter(function (s) { return s.page === this.page; }, this)[0];
        }
        if (!first) return;

        this.active = true;
        document.documentElement.classList.add('kg-tour-active');
        this._buildDom();
        window.addEventListener('resize', this._onResize);
        window.addEventListener('scroll', this._onResize, true);
        this.goTo(first.id);
    };

    Tour.prototype.stop = function (opts) {
        if (!this.active) return;
        this._teardownStep();
        this.active = false;
        this.current = null;
        this.narrator.stop();
        if (!(opts && opts.keepState)) this._clearPersisted();
        document.documentElement.classList.remove('kg-tour-active');
        window.removeEventListener('resize', this._onResize);
        window.removeEventListener('scroll', this._onResize, true);
        if (this.root) {
            this.root.remove();
            this.root = null;
        }
        this.rings = [];
    };

    Tour.prototype.isActive = function () { return this.active; };

    Tour.prototype.next = function () {
        if (!this.current) return;
        var id = this.current.nextId || this.nextIdAfter(this.current.id);
        if (id) this.goTo(id); else this.finish();
    };

    Tour.prototype.finish = function () {
        this.stop();
    };

    Tour.prototype.goTo = function (id) {
        var step = this.stepById(id);
        if (!step) return this.finish();

        // Buoc thuoc trang khac -> luu lai, cho trang do tu tiep tuc
        if (step.page !== this.page) {
            this._persist(id);
            return;
        }

        this._teardownStep();
        this.current = step;
        this._persist(id);

        if (typeof step.onEnter === 'function') {
            try { step.onEnter(this); } catch (e) { console.warn('[guide] onEnter loi:', e); }
        }

        this._renderPanel(step);
        this._acquireTarget(step);
    };

    Tour.prototype._teardownStep = function () {
        this.narrator.stop();   // buoc truoc con doc do dang -> cat ngay
        if (this.current && typeof this.current.onLeave === 'function') {
            try { this.current.onLeave(this); } catch (e) { }
        }
        if (this._timer) { clearInterval(this._timer); this._timer = 0; }
        if (this._raf) { cancelAnimationFrame(this._raf); this._raf = 0; }
        this._clickCleanups.forEach(function (fn) { fn(); });
        this._clickCleanups = [];
        this._nodes = null;
    };

    /* --- Dung khung DOM cua lop phu -------------------------------------- */

    Tour.prototype._buildDom = function () {
        var root = el('div', 'kg-root');
        root.setAttribute('role', 'dialog');
        root.setAttribute('aria-live', 'polite');

        this.blockers = [];
        for (var i = 0; i < 4; i++) {
            this.blockers.push(el('div', 'kg-blocker', root));
        }

        this.spot = el('div', 'kg-spot', root);

        var panel = el('div', 'kg-panel', root);
        var head = el('div', 'kg-panel__head', panel);
        var avatar = el('div', 'kg-panel__avatar', head);
        avatar.textContent = '💬';
        this.headLabel = el('span', null, head);
        this.headLabel.textContent = 'Hướng dẫn';
        this.progress = el('span', 'kg-panel__progress', head);

        // Nut bat/tat tieng - chi hien khi co giong doc
        if (this.narrator.available()) {
            var self = this;
            this.muteBtn = el('button', 'kg-mute', head);
            this.muteBtn.type = 'button';
            this.muteBtn.addEventListener('click', function () {
                self.narrator.setMuted(!self.narrator.muted);
                self._syncMuteBtn();
                // Bat lai tieng -> doc lai loi thoai cua buoc dang dung
                if (!self.narrator.muted && self.current) self.narrator.say(self.current);
            });
            this._syncMuteBtn();
        }

        this.speech = el('p', 'kg-speech', panel);
        this.hint = el('p', 'kg-hint', panel);
        this.actions = el('div', 'kg-actions', panel);

        this.panel = panel;
        this.root = root;
        document.body.appendChild(root);
    };

    Tour.prototype._syncMuteBtn = function () {
        if (!this.muteBtn) return;
        var muted = this.narrator.muted;
        this.muteBtn.textContent = muted ? '🔇' : '🔊';
        this.muteBtn.title = muted ? 'Bật tiếng' : 'Tắt tiếng';
        this.muteBtn.setAttribute('aria-label', this.muteBtn.title);
        this.muteBtn.classList.toggle('kg-mute--off', muted);
    };

    /* --- Ve mot buoc ----------------------------------------------------- */

    Tour.prototype._renderPanel = function (step) {
        var self = this;

        this.speech.textContent = step.say || '';
        this.speech.classList.toggle('kg-speaking', !!step.say);
        this.narrator.say(step);

        this.hint.textContent = step.hint || '';
        this.hint.style.display = step.hint ? '' : 'none';

        this.headLabel.textContent = step.title || 'Hướng dẫn';

        // Nhanh re (lay so / chung thuc) co so buoc khac nhau nen dat nhan thu cong
        this.progress.textContent = step.progressLabel || '';

        this.actions.innerHTML = '';
        this.waitBox = null;
        this.waitText = null;
        var adv = step.advance || { kind: 'next' };

        if (adv.kind === 'choice') {
            adv.options.forEach(function (opt) {
                var b = el('button', 'kg-btn ' + (opt.variant === 'ghost' ? 'kg-btn--ghost' : 'kg-btn--primary'), self.actions);
                b.type = 'button';
                b.textContent = opt.label;
                b.addEventListener('click', function () { self.goTo(opt.go); });
            });
        } else if (adv.kind === 'next') {
            var nb = el('button', 'kg-btn kg-btn--primary', this.actions);
            nb.type = 'button';
            nb.textContent = adv.label || 'Tiếp tục';
            nb.addEventListener('click', function () { self.next(); });
        } else if (adv.kind === 'anywhere') {
            // Khong co nut bam - cham vao bat ky dau tren man hinh la sang buoc sau
            var tap = el('div', 'kg-tap-hint', this.actions);
            el('span', 'kg-tap-hint__ripple', tap);
            var tapText = el('span', null, tap);
            tapText.textContent = adv.tapText || 'Chạm vào bất kỳ đâu trên màn hình để tiếp tục';
        } else if (adv.kind === 'click' || adv.kind === 'condition') {
            var w = el('div', 'kg-waiting', this.actions);
            el('span', 'kg-waiting__dot', w);
            var t = el('span', null, w);
            t.textContent = valueOf(adv.waitText) || 'Đang chờ thao tác của quý khách...';
            this.waitBox = w;
            this.waitText = t;
        }

        // Nut thoat luon co, de nguoi dan bo qua huong dan bat cu luc nao
        if (!step.hideExit) {
            var x = el('button', 'kg-btn kg-btn--quiet', this.actions);
            x.type = 'button';
            x.textContent = step.exitLabel || 'Bỏ qua hướng dẫn';
            x.addEventListener('click', function () { self.stop(); });
        }

        // Nut DEV: bo qua buoc dang cho (vd: chua nhan dien duoc giay to)
        if (this.devMode && (adv.kind === 'click' || adv.kind === 'condition')) {
            var d = el('button', 'kg-btn kg-btn--dev', this.actions);
            d.type = 'button';
            d.textContent = 'DEV: bỏ qua bước này ⏭';
            d.addEventListener('click', function () {
                if (step.devSkipTo) self.goTo(step.devSkipTo); else self.next();
            });
        }

        this._armAdvance(step, adv);
    };

    /** Gan dieu kien chuyen buoc: cho bam nut that, hoac cho mot dieu kien dung. */
    Tour.prototype._armAdvance = function (step, adv) {
        var self = this;

        // Cham vao BAT KY DAU tren man hinh de sang buoc sau - dung cho cac buoc
        // chi giai thich, khong bat nguoi dan phai bam dung mot nut nao.
        // Ngoai le: cac nut dieu khien cua bang thoai (Bo qua huong dan, loa, DEV)
        // van giu viec cua rieng chung.
        if (adv.kind === 'anywhere') {
            var fired = false;
            var onTap = function (e) {
                if (fired || self.current !== step) return;
                var node = e.target;
                if (node && node.closest && node.closest('.kg-panel button')) return;
                fired = true;
                // Cham dung vao phan tu that dang duoc lam sang -> co the di huong khac
                var goId = (self._hitsTarget(node) && adv.onTargetGo)
                    || adv.go || step.nextId || self.nextIdAfter(step.id);
                setTimeout(function () {
                    if (self.current === step) self.goTo(goId);
                }, adv.delay != null ? adv.delay : 250);
            };
            document.addEventListener('click', onTap, true);
            this._clickCleanups.push(function () {
                document.removeEventListener('click', onTap, true);
            });
            return;
        }

        if (adv.kind === 'click') {
            var sels = toArray(adv.selector || step.target);
            sels.forEach(function (sel) {
                Array.prototype.forEach.call(document.querySelectorAll(sel), function (node) {
                    var handler = function () {
                        var goId = adv.go || step.nextId || self.nextIdAfter(step.id);
                        if (adv.navigates) {
                            // Trang sap chuyen: chi luu buoc ke tiep, de trang moi tu tiep tuc
                            self._persist(goId);
                            self._markWaitingOk(adv.navigatingText || 'Đang chuyển màn hình...');
                        } else {
                            setTimeout(function () { self.goTo(goId); }, adv.delay || 350);
                        }
                    };
                    node.addEventListener('click', handler);
                    self._clickCleanups.push(function () {
                        node.removeEventListener('click', handler);
                    });
                });
            });
            return;
        }

        if (adv.kind === 'condition') {
            var seenOk = false;
            this._timer = setInterval(function () {
                var ok = false;
                try { ok = !!adv.check(); } catch (e) { ok = false; }
                if (ok && !seenOk) {
                    seenOk = true;
                    self._markWaitingOk(adv.okText || 'Đã nhận diện được!');
                    setTimeout(function () {
                        if (self.current === step) {
                            self.goTo(adv.go || step.nextId || self.nextIdAfter(step.id));
                        }
                    }, adv.holdMs != null ? adv.holdMs : 1200);
                } else if (!ok && seenOk) {
                    // mat dieu kien truoc khi kip chuyen -> quay lai trang thai cho
                    seenOk = false;
                    self._markWaiting(valueOf(adv.waitText));
                } else if (!ok && typeof adv.waitText === 'function') {
                    // Dong chu cho thay doi theo tinh trang (vd: "Da chup 3 anh")
                    var text = valueOf(adv.waitText);
                    if (text && self.waitText && self.waitText.textContent !== text) {
                        self.waitText.textContent = text;
                    }
                }
            }, POLL_MS);
        }
    };

    /** Diem vua cham co nam trong phan tu that dang duoc lam sang khong? */
    Tour.prototype._hitsTarget = function (node) {
        if (!node || !this._nodes) return false;
        for (var i = 0; i < this._nodes.length; i++) {
            if (this._nodes[i] === node || this._nodes[i].contains(node)) return true;
        }
        return false;
    };

    Tour.prototype._markWaitingOk = function (text) {
        if (!this.waitBox) return;
        this.waitBox.classList.add('kg-waiting--ok');
        if (text) this.waitText.textContent = text;
    };

    Tour.prototype._markWaiting = function (text) {
        if (!this.waitBox) return;
        this.waitBox.classList.remove('kg-waiting--ok');
        if (text) this.waitText.textContent = text;
    };

    /* --- Tim phan tu muc tieu (co the chua ton tai ngay) ----------------- */

    Tour.prototype._acquireTarget = function (step) {
        var self = this;

        // Buoc tha tay: khong cho, khong chan nut - _reposition tu tim lai muc tieu
        // moi khung hinh (danh sach nut can nhac co the doi theo so anh da chup).
        if (step.modal === false) {
            this._startTracking();
            return;
        }

        var sels = toArray(step.target);

        if (!sels.length) {
            this._nodes = null;
            this._reposition();
            return;
        }

        var deadline = Date.now() + (step.targetTimeout || TARGET_TIMEOUT_MS);

        (function look() {
            if (self.current !== step) return;
            var nodes = [];
            sels.forEach(function (sel) {
                Array.prototype.push.apply(nodes, document.querySelectorAll(sel));
            });
            nodes = nodes.filter(function (n) {
                var b = n.getBoundingClientRect();
                return b.width > 0 || b.height > 0;
            });

            if (nodes.length) {
                self._nodes = nodes;
                self._shieldNodes(step, nodes);
                // Cuon muc tieu vao tam nhin (danh sach dich vu co the dai hon man hinh)
                try {
                    nodes[0].scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
                } catch (e) { }
                self._startTracking();
                return;
            }

            if (Date.now() < deadline) {
                self._raf = requestAnimationFrame(look);
            } else {
                // Khong tim thay -> van hien loi thoai, chi la khong co vung sang
                self._nodes = null;
                self._reposition();
                console.warn('[guide] khong tim thay muc tieu cua buoc "' + step.id + '":', sels);
            }
        })();
    };

    /**
     * blockTarget: nuot cu bam vao nut that dang duoc lam sang.
     * Vung sang (kg-spot) da che san nut roi, nhung luc no dang truot tu buoc truoc
     * sang (transition 0.35s) van con khe ho -> chan them ngay tren chinh nut do.
     * Nghe o pha capture, nhung doc-level listener cua 'anywhere' chay truoc nen
     * tour van chuyen buoc binh thuong.
     */
    Tour.prototype._shieldNodes = function (step, nodes) {
        if (!step.blockTarget) return;
        var self = this;
        nodes.forEach(function (node) {
            var swallow = function (e) {
                e.preventDefault();
                e.stopPropagation();
            };
            node.addEventListener('click', swallow, true);
            self._clickCleanups.push(function () {
                node.removeEventListener('click', swallow, true);
            });
        });
    };

    /** Bam theo vi tri muc tieu moi khung hinh (video/camera co the doi kich thuoc). */
    Tour.prototype._startTracking = function () {
        var self = this;
        (function tick() {
            if (!self.active) return;
            self._reposition();
            self._raf = requestAnimationFrame(tick);
        })();
    };

    /* --- Dat vung sang + 4 mieng che + bang thoai ------------------------ */

    Tour.prototype._reposition = function () {
        if (!this.active || !this.root) return;

        var vw = window.innerWidth;
        var vh = window.innerHeight;
        var step = this.current || {};

        var soft = step.modal === false;
        this.root.classList.toggle('kg-soft', soft);
        this.panel.classList.toggle('kg-panel--docked', soft);
        if (soft) {
            this._drawRings(step);
            this._dockPanel(step.dock || {}, vw, vh);
            return;
        }
        this._hideRings();

        var rect = this._nodes ? unionRect(this._nodes) : null;

        if (!rect) {
            // Khong co muc tieu: che toi toan man hinh, an vung sang
            this.root.classList.add('kg-no-target');
            this.spot.style.display = 'none';
            this.blockers.forEach(function (b, i) {
                b.style.cssText = i === 0
                    ? 'top:0;left:0;width:100%;height:100%'
                    : 'display:none';
            });
            this._placePanel(null, vw, vh);
            return;
        }

        this.root.classList.remove('kg-no-target');
        this.spot.style.display = '';

        var pad = step.padding != null ? step.padding : 14;
        var top = rect.top - pad;
        var left = rect.left - pad;
        var w = rect.width + pad * 2;
        var h = rect.height + pad * 2;

        if (step.shape === 'circle') {
            // Hinh tron bao tron nut: lay canh dai nhat lam duong kinh
            var d = Math.max(w, h);
            left -= (d - w) / 2;
            top -= (d - h) / 2;
            w = d; h = d;
        }

        // Khong de vung sang tran ra ngoai man hinh
        top = Math.max(0, top);
        left = Math.max(0, left);
        w = Math.min(w, vw - left);
        h = Math.min(h, vh - top);

        this.spot.classList.toggle('kg-circle', step.shape === 'circle');
        // blockTarget: van lam sang nut that nhung KHONG cho bam vao (vd: nut Xoa)
        // -> vung sang tu nhan lay cu cham thay cho nut ben duoi.
        this.spot.style.pointerEvents = step.blockTarget ? 'auto' : 'none';
        this.spot.style.top = top + 'px';
        this.spot.style.left = left + 'px';
        this.spot.style.width = w + 'px';
        this.spot.style.height = h + 'px';
        if (step.shape !== 'circle') {
            this.spot.style.borderRadius = (step.radius != null ? step.radius : 16) + 'px';
        }

        // 4 mieng che: tren / duoi / trai / phai - chua lai dung "lo" cho muc tieu
        var b = this.blockers;
        b[0].style.cssText = 'top:0;left:0;width:100%;height:' + top + 'px';
        b[1].style.cssText = 'top:' + (top + h) + 'px;left:0;width:100%;height:' + Math.max(0, vh - top - h) + 'px';
        b[2].style.cssText = 'top:' + top + 'px;left:0;width:' + left + 'px;height:' + h + 'px';
        b[3].style.cssText = 'top:' + top + 'px;left:' + (left + w) + 'px;width:' + Math.max(0, vw - left - w) + 'px;height:' + h + 'px';

        this._placePanel({ top: top, height: h }, vw, vh);
    };

    /**
     * Bang thoai luon nam o nua man hinh doi dien vung sang de khong che mat.
     * step.panelAt = 'top' | 'bottom' de ep vi tri (vd: loi thoai nhac toi cac nut
     * phia duoi trong khi vung sang lai o phia tren).
     */
    Tour.prototype._placePanel = function (spot, vw, vh) {
        var margin = 24;
        var at = (this.current && this.current.panelAt) ||
            (spot && spot.top + spot.height / 2 >= vh * 0.55 ? 'top' : 'bottom');

        this.panel.style.left = '';
        this.panel.style.width = '';
        if (at === 'top') {
            this.panel.style.bottom = '';
            this.panel.style.top = margin + 'px';
        } else {
            this.panel.style.top = '';
            this.panel.style.bottom = margin + 'px';
        }
    };

    /* --- Buoc tha tay (modal: false) ------------------------------------- */

    /** Vong sang nhap nhay quanh tung nut can nhac - khong che toi, khong chan bam. */
    Tour.prototype._drawRings = function (step) {
        var nodes = [];
        toArray(valueOf(step.target)).forEach(function (sel) {
            Array.prototype.push.apply(nodes, document.querySelectorAll(sel));
        });
        this._nodes = nodes;

        var pad = step.padding != null ? step.padding : 10;
        var radius = step.radius != null ? step.radius : 16;
        var shown = 0;
        for (var i = 0; i < nodes.length; i++) {
            var b = nodes[i].getBoundingClientRect();
            if (b.width === 0 && b.height === 0) continue;
            var ring = this.rings[shown] || (this.rings[shown] = el('div', 'kg-ring', this.root));
            ring.style.cssText = 'display:block;top:' + (b.top - pad) + 'px;left:' + (b.left - pad) +
                'px;width:' + (b.width + pad * 2) + 'px;height:' + (b.height + pad * 2) +
                'px;border-radius:' + radius + 'px';
            shown++;
        }
        for (var j = shown; j < this.rings.length; j++) this.rings[j].style.display = 'none';
    };

    Tour.prototype._hideRings = function () {
        this.rings.forEach(function (r) { r.style.display = 'none'; });
    };

    /**
     * Bang thoai thu nho, nep vao khoang trong lon nhat canh `dock.beside` ben trong
     * `dock.within` (vd: dai den hai ben hinh camera) de khong che hinh, danh sach anh
     * hay hang nut. Khong du cho -> nep vao goc tren ben phai cua `within`.
     */
    Tour.prototype._dockPanel = function (dock, vw, vh) {
        var margin = 16;
        var minW = dock.minWidth || 280;
        var maxW = dock.maxWidth || 480;
        var withinEl = dock.within && document.querySelector(dock.within);
        var box = withinEl ? withinEl.getBoundingClientRect()
            : { top: 0, left: 0, right: vw, bottom: vh, width: vw, height: vh };
        var besideEl = dock.beside && document.querySelector(dock.beside);
        var left = null;
        var width = Math.min(maxW, box.width - margin * 2);

        if (besideEl) {
            var b = besideEl.getBoundingClientRect();
            var gapL = b.left - box.left;
            var gapR = box.right - b.right;
            var gap = Math.max(gapL, gapR) - margin * 2;
            if (gap >= minW) {
                width = Math.min(maxW, gap);
                left = gapR >= gapL
                    ? b.right + (gapR - width) / 2
                    : box.left + (gapL - width) / 2;
            }
        }
        if (left === null) left = box.right - margin - width;

        this.panel.style.bottom = '';
        this.panel.style.top = (box.top + margin) + 'px';
        this.panel.style.left = left + 'px';
        this.panel.style.width = width + 'px';
    };

    /* ---------------------------------------------------------------------
     * Khoi tao
     * ------------------------------------------------------------------- */
    function boot() {
        var cfg = window.KIOSK_TOUR_CONFIG;
        if (!cfg) {
            console.warn('[guide] thieu tour-config.js (window.KIOSK_TOUR_CONFIG)');
            return;
        }

        var page = document.body.getAttribute('data-kiosk-page');
        if (!page) return;

        var devMode = /[?&]dev=1/.test(location.search) ||
            localStorage.getItem('kiosk_guide_dev') === '1';

        var tour = new Tour({
            steps: cfg.steps,
            page: page,
            devMode: devMode
        });
        window.KioskGuide = tour;

        // Camera nhan dien nguoi chua co -> tam thoi bam nut de bat dau
        tour.presence.onPresence(function () {
            if (!tour.isActive()) tour.start(cfg.entryStep);
        });

        // Nut bat dau chi hien o trang chua buoc dau tien (mac dinh: trang cua entryStep)
        var entry = tour.stepById(cfg.entryStep) || cfg.steps[0];
        var startPage = cfg.startButtonPage || (entry && entry.page);
        if (page === startPage) {
            var btn = el('button', null, document.body);
            btn.id = 'kg-start-btn';
            btn.type = 'button';
            btn.textContent = cfg.startButtonText || 'Bắt đầu hướng dẫn';
            btn.addEventListener('click', function () { tour.presence.trigger(); });

            // App cam / go camera (useSource / stopSource) luc nao cung duoc -> an / hien nut theo
            var presence = tour.presence;
            var syncBtn = function () { btn.style.display = presence.mode === 'manual' ? '' : 'none'; };
            ['useSource', 'stopSource'].forEach(function (name) {
                var orig = presence[name];
                presence[name] = function () {
                    var r = orig.apply(this, arguments);
                    syncBtn();
                    return r;
                };
            });
            syncBtn();
        }

        // Dang giua chung tour va vua chuyen trang -> tiep tuc dung buoc dang do
        tour.resumeIfPending();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }

    window.KioskGuideTour = Tour;
})(window, document);
