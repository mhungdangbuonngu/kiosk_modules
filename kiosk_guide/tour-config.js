/**
 * NOI DUNG HUONG DAN - sua loi thoai va thu tu buoc tai day.
 *
 * Moi buoc:
 *   id            ma buoc (duy nhat)
 *   page          trang chua buoc nay = gia tri <body data-kiosk-page="...">
 *                 (o app goc: 'home' = trang chu, 'scan' = man hinh chung thuc)
 *   title         nhan nho o goc bang thoai
 *   say           LOI THOAI - se doc thanh tieng khi bat voice (Narrator)
 *   hint          dong chu phu, khong doc
 *   target        selector phan tu duoc lam sang (chuoi hoac mang chuoi)
 *   shape         'rect' (mac dinh) | 'circle'
 *   radius        bo goc vung sang khi shape = 'rect'
 *   padding       do nới rong vung sang quanh phan tu
 *   panelAt       'top' | 'bottom' - ep vi tri bang thoai (mac dinh: nua man hinh
 *                 doi dien vung sang)
 *   blockTarget   true = van lam sang nut that nhung khong cho bam vao no
 *                 (dung cho buoc chi giai thich nut Xoa - bam that la mat anh)
 *   modal         false = buoc "tha tay": bo lop che toi, moi nut deu bam duoc;
 *                 target chi con la vong sang nhac nut (co the la ham tra ve selector).
 *                 Bang thoai thu nho, nep theo dock: {within, beside}
 *   exitLabel     chu tren nut thoat (mac dinh "Bỏ qua hướng dẫn")
 *   advance       cach chuyen sang buoc sau:
 *                   {kind:'next'}       - nguoi dan bam "Tiep tuc"
 *                   {kind:'choice'}     - cho chon nhanh
 *                   {kind:'click'}      - cho bam dung nut that tren man hinh
 *                   {kind:'condition'}  - cho mot dieu kien dung (vd: da nhan dien giay to)
 *                                         waitText   chu luc cho (co the la ham -> cap nhat lien tuc)
 *                                         go         buoc se toi (mac dinh: buoc ke tiep)
 *                   {kind:'anywhere'}   - cham vao BAT KY DAU tren man hinh la di tiep
 *                                         tapText    dong chu goi y (mac dinh da co san)
 *                                         go         buoc se toi (mac dinh: buoc ke tiep)
 *                                         onTargetGo buoc se toi rieng khi cham dung nut that
 *                   {kind:'click', navigates:true} - bam xong trang se chuyen;
 *                                         navigatingText  chu hien trong luc cho trang moi
 *   devSkipTo     nut "DEV: bo qua" se nhay toi buoc nay (chi hien khi ?dev=1)
 *
 * Cap cao nhat: entryStep (buoc bat dau), startButtonPage / startButtonText
 * (nut "Bat dau huong dan" khi chua cam camera; mac dinh hien o trang cua entryStep).
 */
(function (window) {
    'use strict';

    var END = '__end__';   // nextId = END  ->  ket thuc tour

    /* ---------------------------------------------------------------------
     * HOOKS - 3 cho DUY NHAT kich ban doc trang thai cua app quet giay to.
     * Mac dinh doc tu app goc (window.App, #pdf-modal). App khac thi khong sua
     * file nay: dinh nghia window.KIOSK_GUIDE_HOOKS TRUOC khi nap tour-config.js
     *     window.KIOSK_GUIDE_HOOKS = {
     *         documentDetected: function () { return ...; },  // true/false
     *         capturedCount:    function () { return ...; },  // so anh da chup
     *         certifySucceeded: function () { return ...; }   // true khi nop xong
     *     };
     * Thieu ham nao thi dung ham mac dinh ben duoi.
     * ------------------------------------------------------------------- */
    var DEFAULT_HOOKS = {
        /** Bo quet tai lieu da nhan dien duoc giay to trong khung hinh chua? */
        documentDetected: function () {
            var app = window.App;
            return !!(app && app.documentScanner && app.documentScanner.lastLiveDetection);
        },
        /** So anh da chup va cat nen. */
        capturedCount: function () {
            var app = window.App;
            return (app && app.imageStore && app.imageStore.count) || 0;
        },
        /** Nop ho so thanh cong: Api.certifyDocuments chi mo modal PDF khi da gui xong. */
        certifySucceeded: function () {
            return !!document.getElementById('pdf-modal');
        }
    };

    function hook(name) {
        return function () {
            var custom = window.KIOSK_GUIDE_HOOKS && window.KIOSK_GUIDE_HOOKS[name];
            return (typeof custom === 'function' ? custom : DEFAULT_HOOKS[name])();
        };
    }

    var documentDetected = hook('documentDetected');
    var capturedCount = hook('capturedCount');
    var certifySucceeded = hook('certifySucceeded');

    window.KIOSK_TOUR_CONFIG = {

        // Buoc bat dau khi camera nhan dien co nguoi den gan
        entryStep: 'welcome',

        steps: [

            /* ============ TRANG CHU (index.html) ============ */

            {
                id: 'welcome',
                page: 'home',
                title: 'Xin chào',
                progressLabel: 'Bước 1',
                say: 'Xin chào quý khách! Tôi sẽ đồng hành cùng quý khách trong suốt quá trình làm thủ tục. Quý khách muốn chứng thực giấy tờ, hay lấy số thứ tự để gặp cán bộ?',
                hint: 'Quý khách chạm vào lựa chọn bên dưới.',
                target: null,
                hideExit: false,
                advance: {
                    kind: 'choice',
                    options: [
                        { label: 'Chứng thực giấy tờ', go: 'pick-certify' },
                        { label: 'Lấy số thứ tự', go: 'pick-ticket', variant: 'ghost' }
                    ]
                }
            },

            /* ---- Nhánh A: lấy số thứ tự ---- */
            {
                id: 'pick-ticket',
                page: 'home',
                title: 'Lấy số thứ tự',
                progressLabel: 'Lấy số · 1/2',
                say: 'Quý khách vui lòng chọn quầy phù hợp với thủ tục của mình bằng cách chạm vào một trong các ô đang sáng.',
                hint: 'Máy sẽ tự động in phiếu số thứ tự sau khi quý khách chọn quầy.',
                target: '.feature-card[data-service-id]',
                padding: 10,
                radius: 18,
                advance: {
                    kind: 'click',
                    waitText: 'Đang chờ quý khách chọn quầy...',
                    go: 'ticket-done',
                    delay: 500
                },
                devSkipTo: 'ticket-done'
            },
            {
                id: 'ticket-done',
                page: 'home',
                title: 'Hoàn tất',
                progressLabel: 'Lấy số · 2/2',
                say: 'Phiếu số thứ tự của quý khách đang được in ra. Quý khách vui lòng lấy phiếu và ngồi chờ đến lượt được gọi. Xin cảm ơn!',
                target: null,
                nextId: END,
                advance: { kind: 'next', label: 'Hoàn tất' }
            },

            /* ---- Nhánh B: chứng thực giấy tờ ---- */
            {
                id: 'pick-certify',
                page: 'home',
                title: 'Chứng thực giấy tờ',
                progressLabel: 'Chứng thực · 1/9',
                say: 'Mời quý khách chạm vào ô Dịch vụ chứng thực đang sáng để bắt đầu quét giấy tờ.',
                hint: 'Màn hình sẽ chuyển sang khu vực quét giấy tờ.',
                target: '.feature-card[href="index2.html"]',
                padding: 12,
                radius: 18,
                advance: {
                    kind: 'click',
                    waitText: 'Đang chờ quý khách chạm vào ô Dịch vụ chứng thực...',
                    navigates: true,      // bam xong se chuyen sang index2.html
                    navigatingText: 'Đang mở màn hình chứng thực...',
                    go: 'scan-intro'
                },
                devSkipTo: 'pick-certify'  // dev: bam nut that de sang trang
            },

            /* ============ MÀN HÌNH CHỨNG THỰC (index2.html) ============ */

            {
                id: 'scan-intro',
                page: 'scan',
                title: 'Màn hình chứng thực',
                progressLabel: 'Chứng thực · 2/9',
                say: 'Đây là màn hình chứng thực. Vùng đang sáng là hình ảnh trực tiếp từ camera quét giấy tờ. Bên cạnh là danh sách những ảnh quý khách đã chụp.',
                hint: 'Chạm "Tiếp tục" khi quý khách đã sẵn sàng.',
                target: '#camera-viewport',
                padding: 8,
                radius: 12,
                targetTimeout: 15000,      // cho camera khoi dong
                advance: { kind: 'next' }
            },
            {
                id: 'scan-controls',
                page: 'scan',
                title: 'Các nút thao tác',
                progressLabel: 'Chứng thực · 3/9',
                say: 'Phía dưới là các nút thao tác. Nút Chụp ảnh màu đỏ để chụp giấy tờ, nút Xóa tất cả để xóa ảnh và chụp lại từ đầu, còn nút Chứng thực màu xanh để nộp hồ sơ.',
                hint: 'Các bước tiếp theo sẽ hướng dẫn quý khách dùng từng nút.',
                // Hang nut o day man hinh -> bang thoai tu len tren, khong che nut
                target: ['#capture-btn', '#reset-btn', '#certify-btn'],
                padding: 16,
                radius: 18,
                // Chi gioi thieu - bam that luc nay chua co anh, Chung thuc se bao loi
                blockTarget: true,
                advance: { kind: 'next' }
            },
            {
                id: 'scan-place',
                page: 'scan',
                title: 'Đặt giấy tờ',
                progressLabel: 'Chứng thực · 4/9',
                say: 'Quý khách vui lòng đặt giấy tờ cần chứng thực vào hộp quét bên cạnh màn hình, mặt cần chụp úp xuống dưới.',
                hint: 'Đặt giấy tờ nằm gọn trong lòng hộp quét.',
                target: '#camera-viewport',
                padding: 8,
                radius: 12,
                advance: { kind: 'next', label: 'Tôi đã đặt giấy tờ' }
            },
            {
                id: 'scan-align',
                page: 'scan',
                title: 'Căn chỉnh giấy tờ',
                progressLabel: 'Chứng thực · 5/9',
                say: 'Quý khách chỉnh cho giấy tờ nằm ngay ngắn, bốn góc vuông vắn và không bị che khuất. Khi máy nhận ra giấy tờ, một khung viền sẽ hiện lên bao quanh bốn góc.',
                hint: 'Nếu khung viền chưa hiện, quý khách thử vuốt phẳng giấy hoặc dịch giấy vào giữa hộp quét.',
                target: '#camera-viewport',
                padding: 8,
                radius: 12,
                advance: {
                    kind: 'condition',
                    check: documentDetected,
                    waitText: 'Đang tìm giấy tờ trong khung hình...',
                    okText: 'Đã nhận diện được giấy tờ!',
                    holdMs: 1400
                },
                devSkipTo: 'scan-capture'
            },
            {
                id: 'scan-capture',
                page: 'scan',
                title: 'Chụp ảnh',
                progressLabel: 'Chứng thực · 6/9',
                say: 'Máy đã nhận diện được giấy tờ. Nếu quý khách thấy giấy tờ đã rõ nét và đầy đủ, hãy chạm vào nút Chụp ảnh đang sáng. Máy sẽ tự động cắt bỏ phần nền thừa xung quanh.',
                hint: 'Quý khách có thể chụp nhiều trang, mỗi lần một trang.',
                target: '#capture-btn',
                padding: 16,
                radius: 999,
                advance: {
                    kind: 'condition',
                    check: function () { return capturedCount() > 0; },
                    waitText: 'Đang chờ quý khách chạm nút Chụp ảnh...',
                    okText: 'Đã chụp và cắt nền xong!',
                    holdMs: 1500
                },
                devSkipTo: 'scan-reset'
            },
            {
                id: 'scan-reset',
                page: 'scan',
                title: 'Nút xóa',
                progressLabel: 'Chứng thực · 7/9',
                say: 'Nếu ảnh chưa vừa ý, quý khách chạm nút Xóa tất cả đang sáng để xóa toàn bộ ảnh đã chụp và quét lại từ đầu.',
                hint: 'Lưu ý: nút này xóa tất cả ảnh, không chỉ ảnh cuối cùng.',
                target: '#reset-btn',
                padding: 16,
                radius: 999,
                // Khong bat nguoi dan bam that - bam vao la mat het anh vua chup
                blockTarget: true,
                advance: { kind: 'anywhere' }
            },
            {
                id: 'scan-delete-one',
                page: 'scan',
                title: 'Xóa từng ảnh',
                progressLabel: 'Chứng thực · 8/9',
                say: 'Nếu chỉ một tấm ảnh chưa vừa ý, quý khách không cần xóa hết. Mỗi ảnh trong danh sách đều có một dấu nhân nhỏ màu đỏ ở góc trên bên phải. Quý khách chạm vào dấu nhân đó để xóa riêng tấm ảnh ấy, các ảnh còn lại vẫn được giữ nguyên.',
                hint: 'Xóa một ảnh không ảnh hưởng đến những ảnh khác.',
                target: '.image-item:first-child .delete-btn',
                shape: 'circle',
                padding: 14,
                // Chi gioi thieu - khong xoa that tam anh cua nguoi dan
                blockTarget: true,
                // Nut X chi hien khi ro chuot -> ep hien trong suot buoc nay
                onEnter: function () {
                    document.documentElement.classList.add('kg-show-delete-btn');
                },
                onLeave: function () {
                    document.documentElement.classList.remove('kg-show-delete-btn');
                },
                advance: { kind: 'anywhere' }
            },
            {
                id: 'scan-submit',
                page: 'scan',
                title: 'Chụp tiếp hoặc nộp hồ sơ',
                progressLabel: 'Chứng thực · 9/9',
                say: 'Từ đây quý khách có thể tự thao tác. Giấy tờ có nhiều trang thì quý khách đặt trang tiếp theo vào hộp quét và chạm Chụp ảnh, mỗi lần một trang. Khi đã chụp đủ, hãy chạm nút Chứng thực để nộp hồ sơ cho cán bộ xử lý.',
                // Buoc tha tay: bo lop che toi, nguoi dan chup them / xoa anh tuy y,
                // khong bi ep nop ngay. Huong dan o lai den khi nop xong hoac bam tat.
                modal: false,
                // Bang thoai nep vao dai den canh hinh camera: khong che hinh, anh, nut
                dock: { within: '#camera-viewport', beside: '#video' },
                // Chua co anh thi chi nhac Chup anh (bam Chung thuc luc nay chi bao loi)
                target: function () {
                    return capturedCount() > 0 ? ['#capture-btn', '#certify-btn'] : '#capture-btn';
                },
                padding: 10,
                radius: 14,
                exitLabel: 'Tắt hướng dẫn',
                advance: {
                    kind: 'condition',
                    check: certifySucceeded,
                    waitText: function () {
                        var n = capturedCount();
                        return n > 0
                            ? 'Đã chụp ' + n + ' ảnh. Chụp thêm, hoặc chạm Chứng thực khi đã đủ.'
                            : 'Chưa có ảnh nào. Đặt giấy tờ vào hộp quét rồi chạm Chụp ảnh.';
                    },
                    okText: 'Đã gửi hồ sơ!',
                    holdMs: 400,
                    go: 'scan-done'
                },
                devSkipTo: 'scan-done'
            },
            {
                id: 'scan-done',
                page: 'scan',
                title: 'Hoàn tất',
                say: 'Hồ sơ của quý khách đã được gửi đi. Quý khách vui lòng lấy lại giấy tờ trong hộp quét và chờ cán bộ tiếp nhận. Xin cảm ơn quý khách!',
                target: null,
                nextId: END,
                advance: { kind: 'next', label: 'Hoàn tất' }
            }
        ]
    };
})(window);
